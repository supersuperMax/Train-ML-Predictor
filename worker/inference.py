"""Шаг inference: сетка ключей route × date × hour + признаки → прогноз через адаптер модели.

Результат (store/forecast.parquet) проходит валидацию. Если модель упала или вернула мусор,
шаг завершается ошибкой, и snapshot остаётся прежним.
Колонка source: model — прогноз модели, baseline — достроено встроенным baseline (MODEL_FALLBACK=baseline).
"""
import logging

import pandas as pd

from worker import features, model_adapter
from worker.config import Config
from worker.normalize import load_history

log = logging.getLogger(__name__)


def forecast_range(cfg: Config, history: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    if cfg.forecast_start:
        start = pd.Timestamp(cfg.forecast_start)
    elif len(history):
        start = history["date"].max() + pd.Timedelta(days=1)
    else:
        raise model_adapter.ModelError("Нет истории: задайте FORECAST_START")
    end = pd.Timestamp(cfg.forecast_end) if cfg.forecast_end else pd.Timestamp(year=start.year + 1, month=12, day=31)
    if end < start:
        raise model_adapter.ModelError(f"FORECAST_END ({end.date()}) раньше начала прогноза ({start.date()})")
    return start, end


def run(cfg: Config) -> dict:
    history = load_history(cfg)
    model = model_adapter.load(cfg.model_mode, cfg.model_dir, cfg.model_shift_years)

    if model.mode == "file":
        # Диапазон задаёт сам файл; FORECAST_START/END, если заданы, его обрезают.
        keys = None
        if cfg.forecast_start or cfg.forecast_end:
            start, end = forecast_range(cfg, history)
            keys = pd.DataFrame({"date": [start, end]})
        pred = model.predict(keys, None, history)
        if pred.empty:
            raise model_adapter.ModelError("Файл прогноза не содержит дат в заданном диапазоне")
        start, end = pred["date"].min(), pred["date"].max()
        if cfg.model_fallback == "baseline" and len(history):
            # baseline заполняет и промежуток между концом истории и началом модели, и хвост до FORECAST_END
            f_start, f_end = forecast_range(cfg, history)
            start, end = min(start, f_start), max(end, f_end)
    else:
        start, end = forecast_range(cfg, history)
        keys = model_adapter.grid(cfg.routes, start, end)
        pred = model.predict(keys, features.for_keys(keys), history)
    pred = pred.assign(source="model")

    filled = 0
    if cfg.model_fallback == "baseline" and model.mode != "baseline":
        routes = sorted(set(cfg.routes) | set(pred["route"].unique().tolist()))
        full = model_adapter.grid(routes, min(start, pred["date"].min()), end)
        gap = full.merge(pred[model_adapter.KEY_COLUMNS], how="left", indicator=True)
        gap = gap[gap["_merge"] == "left_only"].drop(columns="_merge").reset_index(drop=True)
        if len(gap):
            extra = model_adapter.BaselineModel().predict(gap, features.for_keys(gap), history)
            pred = pd.concat([pred, extra.assign(source="baseline")], ignore_index=True)
            filled = len(gap)
    elif cfg.model_fallback not in ("none", "baseline"):
        raise model_adapter.ModelError(f"Неизвестный MODEL_FALLBACK={cfg.model_fallback!r}; допустимо: none, baseline")

    pred = pred.sort_values(model_adapter.KEY_COLUMNS).reset_index(drop=True)
    pred["source"] = pred["source"].astype("category")
    cfg.store_dir.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(cfg.store_dir / "forecast.parquet", index=False)

    # Полный baseline на тот же период и маршруты — отдельный режим отображения на сайте (сравнение с моделью).
    baseline_path = cfg.store_dir / "baseline.parquet"
    if len(history):
        keys_all = model_adapter.grid(sorted(pred["route"].unique().tolist()), pred["date"].min(), pred["date"].max())
        model_adapter.BaselineModel().predict(keys_all, features.for_keys(keys_all), history).to_parquet(baseline_path, index=False)
    elif baseline_path.exists():
        baseline_path.unlink()

    ranges = {src: [str(g["date"].min().date()), str(g["date"].max().date())] for src, g in pred.groupby("source", observed=True)}
    return {"model": model.describe(), "mode": model.mode, "rows": len(pred), "routes": sorted(pred["route"].unique().tolist()),
            "range": [str(pred["date"].min().date()), str(pred["date"].max().date())],
            "sources": ranges, "baseline_rows": filled, "total": float(pred["prediction"].sum())}
