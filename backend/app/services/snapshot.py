"""Загрузка опубликованного worker'ом snapshot в память.

Прогноз хранится плотным массивом cube[маршрут, день, час] (float32): любой запрос — это срез и сумма,
без pandas-фильтрации на каждый запрос. Для остановок — матрица долей share[маршрут, остановка].
"""
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

SNAPSHOT_DIR = Path(os.environ.get("SNAPSHOT_DIR") or Path(__file__).resolve().parents[3] / "data" / "snapshot")
RELOAD_SEC = float(os.environ.get("SNAPSHOT_RELOAD_SEC", 5))

SOURCES = ["model", "baseline"]


@dataclass
class Snapshot:
    version: str
    manifest: dict
    start: date
    days: int
    routes: list[int]
    route_idx: dict[int, int]
    route_names: dict[int, str | None]
    cube: np.ndarray            # [R, D, 24] float32, NaN — нет прогноза
    source: np.ndarray          # [R, D] int8: 0 model, 1 baseline, -1 нет данных
    daytype: np.ndarray         # [D] str
    stops: pd.DataFrame         # stop_id, name, lat, lon, routes
    stop_idx: dict[int, int]
    share: np.ndarray           # [R, S] float32
    lines: list[dict] = field(default_factory=list)

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.days - 1)

    def day(self, d: date) -> int:
        return (d - self.start).days

    def date_at(self, i: int) -> date:
        return self.start + timedelta(days=int(i))


def load(folder: Path) -> Snapshot:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    fc = pd.read_parquet(folder / "forecast.parquet")
    fc["date"] = pd.to_datetime(fc["date"]).dt.date
    routes = sorted(int(r) for r in fc["route"].unique())
    route_idx = {r: i for i, r in enumerate(routes)}
    start, end = min(fc["date"]), max(fc["date"])
    days = (end - start).days + 1

    ri = fc["route"].map(route_idx).to_numpy()
    di = np.array([(d - start).days for d in fc["date"]])
    hi = fc["hour"].to_numpy().astype(int)
    cube = np.full((len(routes), days, 24), np.nan, dtype=np.float32)
    cube[ri, di, hi] = fc["prediction"].to_numpy(dtype=np.float32)
    source = np.full((len(routes), days), -1, dtype=np.int8)
    source[ri, di] = fc["source"].astype(str).map({s: i for i, s in enumerate(SOURCES)}).fillna(0).to_numpy(np.int8)

    cal = pd.read_parquet(folder / "calendar.parquet")
    cal["date"] = pd.to_datetime(cal["date"]).dt.date
    daytype = np.full(days, "weekday", dtype=object)
    for d, t in zip(cal["date"], cal["daytype"]):
        if start <= d <= end:
            daytype[(d - start).days] = t

    rs = pd.read_parquet(folder / "route_stops.parquet")
    rs = rs[rs["route"].isin(routes)] if len(rs) else rs
    names = pd.read_parquet(folder / "routes.parquet")
    route_names = {r: None for r in routes}
    route_names.update({int(r): n for r, n in zip(names["route"], names["name"]) if int(r) in route_idx})

    if len(rs):
        stops = (rs.groupby("stop_id", as_index=False)
                 .agg(name=("name", "first"), lat=("lat", "first"), lon=("lon", "first"),
                      routes=("route", lambda s: sorted({int(x) for x in s}))))
    else:
        stops = pd.DataFrame(columns=["stop_id", "name", "lat", "lon", "routes"])
    stop_idx = {int(s): i for i, s in enumerate(stops["stop_id"])}
    share = np.zeros((len(routes), len(stops)), dtype=np.float32)
    for r, s, w in rs.groupby(["route", "stop_id"], as_index=False)["share"].sum().itertuples(index=False):
        share[route_idx[int(r)], stop_idx[int(s)]] += w

    lines = [{"route": int(r), "direction": int(d),
              "coordinates": g.sort_values("seq")[["lon", "lat"]].round(6).to_numpy().tolist()}
             for (r, d), g in rs.groupby(["route", "direction"])] if len(rs) else []

    return Snapshot(version=manifest["version"], manifest=manifest, start=start, days=days, routes=routes,
                    route_idx=route_idx, route_names=route_names, cube=cube, source=source, daytype=daytype,
                    stops=stops, stop_idx=stop_idx, share=share, lines=lines)


class SnapshotStore:
    """Держит текущий snapshot и перечитывает его, когда worker переключает data/snapshot/CURRENT."""

    def __init__(self, folder: Path = SNAPSHOT_DIR, reload_sec: float = RELOAD_SEC):
        self.folder, self.reload_sec = folder, reload_sec
        self._snap: Snapshot | None = None
        self._checked = 0.0
        self._lock = threading.Lock()

    def _pointer(self) -> str | None:
        p = self.folder / "CURRENT"
        try:
            return p.read_text().strip() or None
        except FileNotFoundError:
            return None

    def get(self) -> Snapshot | None:
        now = time.monotonic()
        if self._snap is not None and now - self._checked < self.reload_sec:
            return self._snap
        with self._lock:
            if self._snap is not None and now - self._checked < self.reload_sec:
                return self._snap
            self._checked = now
            version = self._pointer()
            if version and (self._snap is None or self._snap.version != version):
                try:
                    self._snap = load(self.folder / version)
                    log.info("Загружен snapshot %s", version)
                except Exception:
                    log.exception("Не удалось загрузить snapshot %s — остаётся предыдущий", version)
            return self._snap

    def last_run(self) -> dict | None:
        try:
            return json.loads((self.folder / "LAST_RUN.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None


store = SnapshotStore()
