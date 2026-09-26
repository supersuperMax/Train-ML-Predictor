"""Адаптер модели прогноза. Сервис не зависит от устройства модели — только от контракта (см. model/README.md).

Режимы (MODEL_MODE):
- file     — готовый файл model/predictions.{parquet,csv}: колонки route, date, hour, prediction;
- plugin   — model/predictor.py с функцией predict(keys, features, history) -> массив прогнозов;
- baseline — встроенный профильный прогноз (не ML): средний профиль маршрута по типу дня и часу
             за последние 5 недель истории × сезонный индекс месяца. Нужен, пока нет модели,
             и для достраивания горизонта за пределами модели (MODEL_FALLBACK=baseline).
"""
import importlib.util
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from worker import features

log = logging.getLogger(__name__)

KEY_COLUMNS = ["route", "date", "hour"]
OUTPUT_COLUMNS = KEY_COLUMNS + ["prediction"]


class ModelError(Exception):
    """Модель вернула некорректный результат — текущий snapshot не трогаем."""


def grid(routes, start, end) -> pd.DataFrame:
    idx = pd.MultiIndex.from_product([sorted(routes), pd.date_range(start, end), range(24)], names=KEY_COLUMNS)
    df = idx.to_frame(index=False)
    return df.astype({"route": "int16", "hour": "int8"})


def validate(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Проверка результата модели: схема, типы, дубликаты, полнота сетки, значения ≥ 0."""
    missing = [c for c in OUTPUT_COLUMNS if c not in df.columns]
    if missing:
        raise ModelError(f"{source}: нет колонок {missing}; ожидаются {OUTPUT_COLUMNS}")
    out = pd.DataFrame({
        "route": pd.to_numeric(df["route"], errors="coerce"),
        "date": pd.to_datetime(df["date"], errors="coerce"),
        "hour": pd.to_numeric(df["hour"], errors="coerce"),
        "prediction": pd.to_numeric(df["prediction"], errors="coerce"),
    })
    bad = out.isna().any(axis=1) | ~np.isfinite(out["prediction"].fillna(0))
    if bad.any():
        raise ModelError(f"{source}: {int(bad.sum())} строк с пустыми или нечисловыми значениями "
                         f"(пример: {df[bad].head(1).to_dict('records')})")
    if not out["hour"].between(0, 23).all():
        raise ModelError(f"{source}: час вне диапазона 0–23")
    out = out.astype({"route": "int16", "hour": "int8", "prediction": "float32"})
    dups = out.duplicated(KEY_COLUMNS)
    if dups.any():
        raise ModelError(f"{source}: {int(dups.sum())} повторяющихся ключей route/date/hour")
    negative = int((out["prediction"] < 0).sum())
    if negative:
        log.warning("%s: %d отрицательных прогнозов обрезаны до 0", source, negative)
        out["prediction"] = out["prediction"].clip(lower=0)
    days = out["date"].nunique()
    per_route = out.groupby("route").size()
    incomplete = per_route[per_route != days * 24]
    if len(incomplete):
        raise ModelError(f"{source}: неполная сетка — у маршрутов {incomplete.index.tolist()} "
                         f"не хватает часов (ожидается {days} дн. × 24 ч)")
    return out


class FileModel:
    mode = "file"

    def __init__(self, model_dir: Path):
        candidates = [model_dir / "predictions.parquet", model_dir / "predictions.csv"]
        self.path = next((p for p in candidates if p.exists()), None)
        if self.path is None:
            raise ModelError(f"MODEL_MODE=file: не найден {candidates[0].name} или {candidates[1].name} в {model_dir}")

    def describe(self) -> str:
        return f"файл {self.path.name}"

    def predict(self, keys: pd.DataFrame | None, feats, history) -> pd.DataFrame:
        if self.path.suffix == ".parquet":
            df = pd.read_parquet(self.path)
        else:
            with open(self.path, encoding="utf-8-sig") as f:
                sep = ";" if ";" in f.readline() else ","
            df = pd.read_csv(self.path, sep=sep, encoding="utf-8-sig")
        out = validate(df, self.path.name)
        if keys is not None:  # ограничиваем запрошенным диапазоном дат
            out = out[out["date"].between(keys["date"].min(), keys["date"].max())]
        return out


class PluginModel:
    mode = "plugin"

    def __init__(self, model_dir: Path):
        path = model_dir / "predictor.py"
        if not path.exists():
            raise ModelError(f"MODEL_MODE=plugin: не найден {path}")
        spec = importlib.util.spec_from_file_location("team_predictor", path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        if not hasattr(self.module, "predict"):
            raise ModelError("predictor.py должен определять функцию predict(keys, features, history)")
        self.max_date = pd.Timestamp(getattr(self.module, "MAX_DATE")) if hasattr(self.module, "MAX_DATE") else None

    def describe(self) -> str:
        return f"плагин predictor.py ({getattr(self.module, 'NAME', 'без названия')})"

    def predict(self, keys: pd.DataFrame, feats: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
        if self.max_date is not None:
            m = keys["date"] <= self.max_date
            keys, feats = keys[m].reset_index(drop=True), feats[m].reset_index(drop=True)
        values = np.asarray(self.module.predict(keys.copy(), feats.copy(), history.copy()), dtype="float64")
        if values.shape != (len(keys),):
            raise ModelError(f"predictor.predict вернул {values.shape}, ожидается ({len(keys)},)")
        return validate(keys.assign(prediction=values), "predictor.py")


class BaselineModel:
    mode = "baseline"
    WINDOW_DAYS = 35

    def describe(self) -> str:
        return "встроенный профильный baseline (не ML)"

    @staticmethod
    def _profile_daytype(daytype: pd.Series) -> pd.Series:
        return daytype.replace({"holiday": "sun"})  # праздники ходят по расписанию выходного дня

    def predict(self, keys: pd.DataFrame, feats: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
        if history.empty:
            raise ModelError("baseline: нет истории посадок")
        cal = features.calendar(history["date"])
        h = history.merge(cal[["date", "daytype", "month"]], on="date")
        h["pdt"] = self._profile_daytype(h["daytype"])

        window = h[h["date"] > h["date"].max() - pd.Timedelta(days=self.WINDOW_DAYS)]
        n_days = window.groupby(["route", "pdt"])["date"].nunique().rename("n_days").reset_index()
        profile = window.groupby(["route", "pdt", "hour"], as_index=False)["boardings"].sum().merge(n_days)
        profile["profile"] = profile["boardings"] / profile["n_days"]
        profile = profile[["route", "pdt", "hour", "profile"]]

        daily = h.groupby("date").agg(total=("boardings", "sum"), month=("month", "first"))
        base = daily[daily.index > daily.index.max() - pd.Timedelta(days=self.WINDOW_DAYS)]["total"].mean()
        season = (daily.groupby("month")["total"].mean() / base).rename("season_index")

        f = feats.assign(pdt=self._profile_daytype(feats["daytype"]))
        f = f.merge(profile, on=["route", "pdt", "hour"], how="left")
        f = f.merge(season.reset_index(), on="month", how="left")
        values = f["profile"].fillna(0) * f["season_index"].fillna(1.0)
        return validate(keys.assign(prediction=values.values), "baseline")


def load(mode: str, model_dir: Path):
    if mode == "file":
        return FileModel(model_dir)
    if mode == "plugin":
        return PluginModel(model_dir)
    if mode == "baseline":
        return BaselineModel()
    raise ModelError(f"Неизвестный MODEL_MODE={mode!r}; допустимо: file, plugin, baseline")
