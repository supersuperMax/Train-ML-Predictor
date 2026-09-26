"""Шаг normalize: счётчики из staging → почасовая история посадок store/history.parquet.

Посадка = успешная валидация (validation_result == 1). Маршрут — число из ngpt_route ("25 трамвай" → 25).
Дата и час — из tran_date_time. Неполные крайние дни файла (суточный «хвост» в соседний месяц) отбрасываются.
При первом запуске история засевается из data/history/*.csv (route, date, hour, boardings).
"""
import logging

import pandas as pd

from worker.config import Config

log = logging.getLogger(__name__)

HISTORY_COLUMNS = ["route", "date", "hour", "boardings"]
EDGE_DAY_SHARE = 0.2   # крайний день с объёмом < 20% медианного дня считается неполным
MIN_DAYS_FOR_TRIM = 3  # короткие (потоковые) порции не обрезаем


def history_path(cfg: Config):
    return cfg.store_dir / "history.parquet"


def trim_partial_edges(df: pd.DataFrame) -> pd.DataFrame:
    daily = df.groupby("date")["boardings"].sum().sort_index()
    if len(daily) < MIN_DAYS_FOR_TRIM:
        return df
    threshold = daily.median() * EDGE_DAY_SHARE
    full = daily[daily >= threshold].index
    if full.empty:
        return df
    return df[df["date"].between(full.min(), full.max())]


def from_counts(counts: pd.DataFrame) -> pd.DataFrame:
    ok = counts[counts["validation_result"].astype(str).str.strip() == "1"].copy()
    ok["route"] = pd.to_numeric(ok["ngpt_route"].astype(str).str.extract(r"^\s*(\d+)")[0], errors="coerce")
    ts = pd.to_datetime(ok["ts_hour"], format="%Y-%m-%d %H", errors="coerce")
    ok = ok.assign(date=ts.dt.normalize(), hour=ts.dt.hour).dropna(subset=["route", "date"])
    out = ok.groupby(["route", "date", "hour"], as_index=False)["n"].sum().rename(columns={"n": "boardings"})
    return _typed(trim_partial_edges(out))


def read_seed(path) -> pd.DataFrame:
    with open(path, encoding="utf-8") as f:
        sep = ";" if ";" in f.readline() else ","
    df = pd.read_csv(path, sep=sep)
    df = df.rename(columns={"prediction": "boardings"})[HISTORY_COLUMNS]
    df["date"] = pd.to_datetime(df["date"])
    return _typed(trim_partial_edges(df))


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    return df.astype({"route": "int16", "hour": "int8", "boardings": "int64"})[HISTORY_COLUMNS]


def merge(history: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    both = pd.concat([history, new], ignore_index=True)
    out = both.groupby(["route", "date", "hour"], as_index=False)["boardings"].sum()
    return _typed(out).sort_values(["route", "date", "hour"]).reset_index(drop=True)


def load_history(cfg: Config) -> pd.DataFrame:
    path = history_path(cfg)
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in
                         zip(HISTORY_COLUMNS, ["int16", "datetime64[ns]", "int8", "int64"])})


def run(cfg: Config) -> dict:
    cfg.store_dir.mkdir(parents=True, exist_ok=True)
    path = history_path(cfg)
    history = load_history(cfg)
    seeded = []
    if not path.exists():
        for seed in sorted(cfg.history_seed_dir.glob("*.csv")):
            history = merge(history, read_seed(seed))
            seeded.append(seed.name)

    staged = sorted(cfg.staging_dir.glob("*.parquet")) if cfg.staging_dir.exists() else []
    added = 0
    for f in staged:
        new = from_counts(pd.read_parquet(f))
        history = merge(history, new)
        added += int(new["boardings"].sum())

    if seeded or staged or not path.exists():
        tmp = path.with_suffix(".tmp")
        history.to_parquet(tmp, index=False)
        tmp.replace(path)
    for f in staged:  # удаляем staging только после успешной записи истории
        f.unlink()

    rng = (str(history["date"].min().date()), str(history["date"].max().date())) if len(history) else (None, None)
    return {"seeded": seeded, "staged_files": len(staged), "boardings_added": added,
            "rows": len(history), "range": rng}
