"""Настройки пайплайна из переменных окружения."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ROUTES = "1,5,7,11,12,17,25,26,28,50"


def _path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name) or default)


@dataclass(frozen=True)
class Config:
    data_dir: Path
    model_dir: Path
    model_mode: str            # file | plugin | baseline
    model_fallback: str        # none | baseline — чем достраивать горизонт за пределами модели
    model_shift_years: int     # сдвиг дат файла модели на N лет (с учётом календаря), режим file
    forecast_start: str        # пусто = день после конца истории
    forecast_end: str          # пусто = 31 декабря следующего года
    routes: tuple[int, ...]
    chunk_rows: int
    interval_min: float
    poll_sec: float
    keep_snapshots: int
    database_url: str

    @property
    def incoming_dir(self) -> Path:
        return self.data_dir / "incoming"

    @property
    def history_seed_dir(self) -> Path:
        return self.data_dir / "history"

    @property
    def reference_dir(self) -> Path:
        return self.data_dir / "reference"

    @property
    def store_dir(self) -> Path:
        return self.data_dir / "store"

    @property
    def staging_dir(self) -> Path:
        return self.store_dir / "staging"

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshot"


def load() -> Config:
    return Config(
        data_dir=_path("DATA_DIR", ROOT / "data"),
        model_dir=_path("MODEL_DIR", ROOT / "model"),
        model_mode=os.environ.get("MODEL_MODE", "file").strip().lower(),
        model_fallback=os.environ.get("MODEL_FALLBACK", "baseline").strip().lower(),
        # tram_model прогнозирует ноябрь–декабрь 2025 (даты хакатона) — сервис показывает этот прогноз на 2026 год
        model_shift_years=int(os.environ.get("MODEL_SHIFT_YEARS", 1)),
        forecast_start=os.environ.get("FORECAST_START", "").strip(),
        forecast_end=os.environ.get("FORECAST_END", "").strip(),
        routes=tuple(int(r) for r in os.environ.get("FORECAST_ROUTES", DEFAULT_ROUTES).split(",") if r.strip()),
        chunk_rows=int(os.environ.get("INGEST_CHUNK_ROWS", 5_000_000)),
        interval_min=float(os.environ.get("PIPELINE_INTERVAL_MIN", 60)),
        poll_sec=float(os.environ.get("PIPELINE_POLL_SEC", 30)),
        keep_snapshots=int(os.environ.get("KEEP_SNAPSHOTS", 3)),
        database_url=os.environ.get("DATABASE_URL", "").strip(),
    )
