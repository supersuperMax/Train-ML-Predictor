"""Шаг ingest: приём сырых файлов валидаций из data/incoming/.

Файл читается по частям (он может весить гигабайты), берутся только нужные колонки,
и сразу сворачивается до счётчиков (маршрут, час, результат валидации) → store/staging/*.parquet.
Обработанный файл переезжает в incoming/processed/, битый — в incoming/failed/.
"""
import logging
import shutil
import time
from pathlib import Path

import pandas as pd

from worker.config import Config

log = logging.getLogger(__name__)

RAW_COLUMNS = ["tran_date_time", "validation_result", "ngpt_route"]
RAW_SUFFIXES = (".csv", ".csv.gz", ".csv.zip", ".txt")


def pending_files(cfg: Config) -> list[Path]:
    if not cfg.incoming_dir.exists():
        return []
    return sorted(p for p in cfg.incoming_dir.iterdir()
                  if p.is_file() and p.name.lower().endswith(RAW_SUFFIXES))


def read_raw(path: Path, chunk_rows: int) -> pd.DataFrame:
    """Счётчики валидаций по (ngpt_route, 'YYYY-MM-DD HH', validation_result)."""
    parts = []
    reader = pd.read_csv(path, sep=";", usecols=RAW_COLUMNS, dtype=str, chunksize=chunk_rows,
                         encoding="utf-8", on_bad_lines="skip")
    for i, chunk in enumerate(reader):
        chunk["ts_hour"] = chunk["tran_date_time"].str.slice(0, 13)
        agg = chunk.groupby(["ngpt_route", "ts_hour", "validation_result"], dropna=True).size()
        parts.append(agg.rename("n").reset_index())
        log.info("%s: часть %d, %d строк", path.name, i + 1, len(chunk))
    if not parts:
        return pd.DataFrame(columns=["ngpt_route", "ts_hour", "validation_result", "n"])
    out = pd.concat(parts, ignore_index=True)
    return out.groupby(["ngpt_route", "ts_hour", "validation_result"], as_index=False)["n"].sum()


def _move(path: Path, folder: str) -> None:
    dest = path.parent / folder
    dest.mkdir(exist_ok=True)
    shutil.move(str(path), dest / path.name)


def run(cfg: Config) -> dict:
    files = pending_files(cfg)
    cfg.staging_dir.mkdir(parents=True, exist_ok=True)
    done, failed = [], []
    for path in files:
        try:
            counts = read_raw(path, cfg.chunk_rows)
            counts.to_parquet(cfg.staging_dir / f"{path.name}.{int(time.time())}.parquet", index=False)
            _move(path, "processed")
            done.append({"file": path.name, "keys": len(counts), "validations": int(counts["n"].sum())})
        except Exception as e:  # битый файл не должен останавливать приём остальных
            log.exception("Не удалось принять %s", path.name)
            _move(path, "failed")
            failed.append({"file": path.name, "error": str(e)})
    return {"files": done, "failed": failed}
