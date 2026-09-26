import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from worker import config

ROOT = Path(__file__).resolve().parents[1]
ROUTES = (1, 17)


def write_history(folder: Path, start="2025-09-01", end="2025-10-31") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    idx = pd.MultiIndex.from_product([ROUTES, pd.date_range(start, end), range(24)], names=["route", "date", "hour"])
    df = idx.to_frame(index=False)
    rng = np.random.default_rng(0)
    df["boardings"] = (100 + 50 * np.sin(df["hour"] / 24 * 2 * np.pi) + rng.integers(0, 20, len(df))).astype(int)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df.to_csv(folder / "history.csv", index=False)


def write_model_file(folder: Path, start="2025-11-01", end="2025-11-30", routes=ROUTES) -> pd.DataFrame:
    folder.mkdir(parents=True, exist_ok=True)
    idx = pd.MultiIndex.from_product([routes, pd.date_range(start, end), range(24)], names=["route", "date", "hour"])
    df = idx.to_frame(index=False)
    df["prediction"] = (df["route"] * 10 + df["hour"]).astype(int)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df.to_csv(folder / "predictions.csv", sep=";", index=False)
    return df


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    data, model = tmp_path / "data", tmp_path / "model"
    write_history(data / "history")
    (data / "reference").mkdir(parents=True)
    shutil.copy(ROOT / "data" / "reference" / "tram_reference.xlsx", data / "reference")
    write_model_file(model)
    base = config.load()
    return replace(base, data_dir=data, model_dir=model, model_mode="file", model_fallback="none",
                   forecast_start="", forecast_end="", routes=ROUTES, database_url="")
