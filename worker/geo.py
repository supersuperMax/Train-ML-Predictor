"""Шаг geo: геопривязка по справочникам data/reference/*.xlsx.

Из справочника берутся маршруты (GTFS_ROUTES) и порядок остановок с координатами по направлениям.
Валидации в данных не привязаны к остановкам (place_id — это депо), поэтому прогноз по остановке
получается распределением прогноза маршрута: share(route, stop).

Доля остановки: внутри направления посадки убывают линейно к конечной (на конечной не садятся),
направления делят поток поровну. Доли одного маршрута в сумме дают 1. Расписание в справочнике —
только выборка из нескольких рейсов, поэтому доли по часам не различаются.
"""
import logging

import numpy as np
import pandas as pd

from worker.config import Config

log = logging.getLogger(__name__)

STOPS_SHEET = "Порядок_с_координатами"
ROUTES_SHEET = "Маршруты"


def _sheet(xls: pd.ExcelFile, prefix: str) -> str | None:
    return next((s for s in xls.sheet_names if s.startswith(prefix)), None)


def _header_row(xls: pd.ExcelFile, sheet: str, marker: str) -> int:
    """В справочнике над заголовком бывает строка с описаниями колонок — ищем строку с `marker`."""
    head = pd.read_excel(xls, sheet_name=sheet, header=None, nrows=5)
    for i, row in head.iterrows():
        if marker in row.astype(str).tolist():
            return int(i)
    return 0


def stop_shares(route_stops: pd.DataFrame) -> pd.Series:
    def per_direction(g: pd.DataFrame) -> pd.Series:
        n = len(g)
        w = np.arange(n, 0, -1, dtype=float) - 1  # n-1 … 0: на конечной посадок нет
        if w.sum() == 0:
            w = np.ones(n)
        return pd.Series(w / w.sum(), index=g.index)

    g = route_stops.sort_values(["route", "direction", "seq"])
    within = g.groupby(["route", "direction"], group_keys=False)[["seq"]].apply(per_direction)
    n_dirs = g.groupby("route")["direction"].transform("nunique")
    return within.reindex(g.index) / n_dirs


def load_reference(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    files = sorted(cfg.reference_dir.glob("*.xlsx")) if cfg.reference_dir.exists() else []
    stops_parts, routes_parts = [], []
    for f in files:
        xls = pd.ExcelFile(f)
        s_sheet, r_sheet = _sheet(xls, STOPS_SHEET), _sheet(xls, ROUTES_SHEET)
        if s_sheet:
            df = pd.read_excel(xls, sheet_name=s_sheet, header=_header_row(xls, s_sheet, "stop_id"))
            stops_parts.append(pd.DataFrame({
                "route": df["route_short_name"].astype(int),
                "direction": df["direction_id"].astype(int),
                "seq": df["stop_sequence"].astype(int),
                "stop_id": df["stop_id"].astype(int),
                "name": df["stop_name"].astype(str),
                "lat": df["stop_lat"].astype(float),
                "lon": df["stop_lon"].astype(float),
            }))
        if r_sheet:
            df = pd.read_excel(xls, sheet_name=r_sheet, header=_header_row(xls, r_sheet, "route_short_name"))
            routes_parts.append(pd.DataFrame({
                "route": pd.to_numeric(df["route_short_name"], errors="coerce"),
                "name": df["route_long_name"].astype(str),
            }).dropna(subset=["route"]).astype({"route": int}))
        if not (s_sheet or r_sheet):
            log.warning("%s: нет листов «%s» / «%s», пропускаю", f.name, STOPS_SHEET, ROUTES_SHEET)

    route_stops = (pd.concat(stops_parts, ignore_index=True).drop_duplicates(["route", "direction", "seq"])
                   if stops_parts else pd.DataFrame(columns=["route", "direction", "seq", "stop_id", "name", "lat", "lon"]))
    routes = (pd.concat(routes_parts, ignore_index=True).drop_duplicates("route")
              if routes_parts else pd.DataFrame(columns=["route", "name"]))
    return route_stops, routes


def run(cfg: Config) -> dict:
    route_stops, routes = load_reference(cfg)
    route_stops = route_stops.dropna(subset=["lat", "lon"])
    if len(route_stops):
        route_stops = route_stops.assign(share=stop_shares(route_stops))
    else:
        route_stops = route_stops.assign(share=pd.Series(dtype=float))
    cfg.store_dir.mkdir(parents=True, exist_ok=True)
    route_stops.to_parquet(cfg.store_dir / "route_stops.parquet", index=False)
    routes.to_parquet(cfg.store_dir / "routes.parquet", index=False)
    return {"routes_in_reference": sorted(int(r) for r in routes["route"]),
            "routes_with_stops": sorted(int(r) for r in route_stops["route"].unique()),
            "stops": int(route_stops["stop_id"].nunique())}
