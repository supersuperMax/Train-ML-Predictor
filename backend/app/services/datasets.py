"""Наборы данных из залитых файлов: маска ключей route × date × hour и результат прогона для скачивания.

Хранятся на диске (DATASETS_DIR), чтобы набор видели все процессы uvicorn и реплики api. Маска сохраняется вместе
с маршрутами и начальной датой и при смене версии прогноза выравнивается по датам и маршрутам.
"""
import json
import os
import re
import shutil
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.errors import not_found
from app.services.snapshot import SNAPSHOT_DIR

DATASETS_DIR = Path(os.environ.get("DATASETS_DIR") or SNAPSHOT_DIR.parent / "uploads")
KEEP = int(os.environ.get("DATASETS_KEEP", 10))
_ID = re.compile(r"^[0-9a-f]{12}$")


def new_dir() -> tuple[str, Path]:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    ds_id = uuid.uuid4().hex[:12]
    path = DATASETS_DIR / ds_id
    path.mkdir()
    return ds_id, path


def path_for(ds_id: str) -> Path:
    path = DATASETS_DIR / ds_id
    if not _ID.match(ds_id) or not (path / "meta.json").exists():
        raise not_found("Набор данных не найден или устарел — загрузите файл заново.", code="unknown_dataset")
    return path


def save(ds_id: str, mask: np.ndarray, routes: list[int], start: date, meta: dict) -> dict:
    path = DATASETS_DIR / ds_id
    np.savez_compressed(path / "mask.npz", mask=mask, routes=np.array(routes), start=np.array(start.toordinal()))
    meta = {**meta, "id": ds_id, "created_at": datetime.now(timezone.utc).isoformat()}
    (path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    _prune()
    return meta


def _prune() -> None:
    done = [p for p in DATASETS_DIR.iterdir() if (p / "meta.json").exists()]
    for old in sorted(done, key=lambda p: p.stat().st_mtime)[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)


def info(ds_id: str) -> dict:
    return json.loads((path_for(ds_id) / "meta.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=16)
def _load(ds_id: str) -> tuple[np.ndarray, list[int], date]:
    with np.load(path_for(ds_id) / "mask.npz") as z:
        return z["mask"], [int(r) for r in z["routes"]], date.fromordinal(int(z["start"]))


def aligned_mask(ds_id: str, routes: list[int], start: date, days: int) -> np.ndarray:
    """Маска набора в осях текущего прогноза [маршрут, день, час]."""
    mask, m_routes, m_start = _load(ds_id)
    out = np.zeros((len(routes), days, 24), dtype=bool)
    shift = (m_start - start).days
    a, b = max(0, shift), min(days, shift + mask.shape[1])
    if a >= b:
        return out
    idx = {r: i for i, r in enumerate(m_routes)}
    for i, r in enumerate(routes):
        if r in idx:
            out[i, a:b] = mask[idx[r], a - shift:b - shift]
    return out
