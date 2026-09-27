"""Шаг geo: геопривязка по справочникам data/reference/*.xlsx.

Из справочника берутся маршруты (GTFS_ROUTES) и порядок остановок с координатами по направлениям.
Валидации в данных не привязаны к остановкам (place_id — это депо), поэтому прогноз по остановке
получается распределением прогноза маршрута: share(route, stop).

Доля остановки: внутри направления посадки убывают линейно к конечной (на конечной не садятся),
направления делят поток поровну. Доли одного маршрута в сумме дают 1. Расписание в справочнике —
только выборка из нескольких рейсов, поэтому доли по часам не различаются.

Выгрузка OpenStreetMap (data/reference/*.geojson, `python -m worker osm`) дополняет справочник: остановки маршрутов,
которых в нём нет, и трассы по рельсам — линии на карте идут по путям, а не прямыми между остановками.
"""
import heapq
import json
import logging
import re
from typing import NamedTuple

import numpy as np
import pandas as pd

from worker.config import Config

log = logging.getLogger(__name__)

STOPS_SHEET = "Порядок_с_координатами"
ROUTES_SHEET = "Маршруты"
STOP_COLUMNS = ["route", "direction", "seq", "stop_id", "name", "lat", "lon"]

OSM_ID_BASE = 90_000_000  # stop_id остановок OSM: id узлов OSM больше 2³¹, а stops.stop_id в Postgres — integer
MERGE_M = 80              # остановка OSM с тем же названием ближе этого — та же остановка, что в справочнике
SNAP_M = 60               # остановка дальше от рельсов к трассе не привязывается
WINDOW_M = 300            # проекция ищется среди ближайших по ходу трассы участков, а не на её повторном проходе
LAT0 = 55.75              # широта Москвы для перевода градусов в метры


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
                   if stops_parts else pd.DataFrame(columns=STOP_COLUMNS))
    routes = (pd.concat(routes_parts, ignore_index=True).drop_duplicates("route")
              if routes_parts else pd.DataFrame(columns=["route", "name"]))
    return route_stops, routes


class Osm(NamedTuple):
    stops: pd.DataFrame                  # route, direction, seq, osm_id, name, lat, lon
    tracks: dict[int, list[np.ndarray]]  # трассы relation: route → [[lon, lat], …] по направлениям
    names: dict[int, str]                # «откуда - куда»
    rails: list[np.ndarray]              # вся сеть путей


def load_osm(cfg: Config) -> Osm:
    """Выгрузка OSM из data/reference/*.geojson; нет файла — пустая."""
    stops, tracks, names, rails = [], {}, {}, []
    files = sorted(cfg.reference_dir.glob("*.geojson")) if cfg.reference_dir.exists() else []
    for f in files:
        for ft in json.loads(f.read_text(encoding="utf-8")).get("features", []):
            p, g = ft.get("properties") or {}, ft.get("geometry") or {}
            if p.get("kind") == "rails" and g.get("type") == "MultiLineString":
                rails += [np.asarray(w, dtype=float)[:, :2] for w in g["coordinates"] if len(w) > 1]
            elif p.get("kind") == "track" and g.get("type") == "LineString" and len(g["coordinates"]) > 1:
                route = int(p["route"])
                tracks.setdefault(route, []).append(np.asarray(g["coordinates"], dtype=float)[:, :2])
                if p.get("from") and p.get("to"):
                    names.setdefault(route, f"{p['from']} - {p['to']}")
            elif p.get("kind") == "stop" and g.get("type") == "Point":
                lon, lat = g["coordinates"][:2]
                stops.append({"route": int(p["route"]), "direction": int(p["direction"]), "seq": int(p["seq"]),
                              "osm_id": int(p["osm_id"]), "name": str(p.get("name") or ""), "lat": float(lat), "lon": float(lon)})
    return Osm(pd.DataFrame(stops, columns=["route", "direction", "seq", "osm_id", "name", "lat", "lon"]), tracks, names, rails)


def _norm(name) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[«»\"'“”„]", "", str(name).lower().replace("ё", "е"))).strip()


def _xy(lon, lat) -> np.ndarray:
    """Градусы → метры (равнопромежуточная проекция): на масштабе города точности хватает."""
    lon, lat = np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)
    return np.column_stack([lon * 111_320 * np.cos(np.radians(LAT0)), lat * 110_574])


def add_osm_stops(ref: pd.DataFrame, osm: pd.DataFrame) -> pd.DataFrame:
    """Остановки OSM — только для маршрутов, которых нет в справочнике (он главнее). Остановка справочника с тем же
    названием ближе MERGE_M — это она же (её stop_id и координаты); остальным — OSM_ID_BASE + номер узла по порядку."""
    osm = osm[~osm["route"].isin(ref["route"].unique())].copy()
    if osm.empty:
        return ref
    rank = {n: i for i, n in enumerate(sorted(osm["osm_id"].unique()))}
    osm["stop_id"] = osm["osm_id"].map(rank) + OSM_ID_BASE
    if len(ref):
        cand = ref.drop_duplicates("stop_id").assign(key=lambda d: d["name"].map(_norm))[["key", "stop_id", "name", "lat", "lon"]]
        m = osm.assign(key=osm["name"].map(_norm)).reset_index().merge(cand, on="key", suffixes=("", "_ref"))
        m["dist"] = np.hypot(*(_xy(m["lon"], m["lat"]) - _xy(m["lon_ref"], m["lat_ref"])).T)
        m = m[m["dist"] < MERGE_M].sort_values("dist").drop_duplicates("index")
        for col in ("stop_id", "name", "lat", "lon"):
            osm.loc[m["index"].to_numpy(), col] = m[f"{col}_ref"].to_numpy()
    osm = osm[STOP_COLUMNS].astype({"stop_id": int})
    return pd.concat([ref, osm], ignore_index=True) if len(ref) else osm.reset_index(drop=True)


def _project(stops_xy: np.ndarray, line_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Позиции остановок вдоль трассы (м от её начала) с сохранением порядка следования и накопленная длина трассы.
    NaN — остановка дальше SNAP_M от рельсов (или позади предыдущей)."""
    a, d = line_xy[:-1], np.diff(line_xy, axis=0)
    seg = np.hypot(d[:, 0], d[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    l2 = np.maximum(seg ** 2, 1e-9)
    pos, lo = np.full(len(stops_xy), np.nan), 0.0
    for k, p in enumerate(stops_xy):
        t = np.clip(((p - a) * d).sum(axis=1) / l2, 0, 1)
        gap = np.hypot(*(a + t[:, None] * d - p).T)
        along = cum[:-1] + t * seg
        ok = (along >= lo) & (gap <= SNAP_M)
        if not ok.any():
            continue
        ok &= along <= along[ok].min() + WINDOW_M
        i = int(np.argmin(np.where(ok, gap, np.inf)))
        pos[k] = lo = along[i]
    return pos, cum


def _cut(line: np.ndarray, cum: np.ndarray, s0: float, s1: float) -> np.ndarray:
    ends = np.column_stack([np.interp([s0, s1], cum, line[:, 0]), np.interp([s0, s1], cum, line[:, 1])])
    return np.vstack([ends[:1], line[(cum > s0) & (cum < s1)], ends[1:]])


def _dedupe(coords: np.ndarray) -> np.ndarray:
    return coords[np.r_[True, (np.diff(coords, axis=0) != 0).any(axis=1)]]


def _densify(line: np.ndarray, step: float) -> np.ndarray:
    seg = np.hypot(*np.diff(_xy(line[:, 0], line[:, 1]), axis=0).T)
    n = np.maximum(1, np.ceil(seg / step)).astype(int)
    parts = [line[i] + (line[i + 1] - line[i]) * (np.arange(n[i])[:, None] / n[i]) for i in range(len(seg))]
    return np.vstack(parts + [line[-1:]])


class Rails:
    """Сеть трамвайных путей: по ней ведутся отрезки, которых нет в трассе relation (разворотные кольца на конечных).
    Пути прорежены вершинами через STEP_M, чтобы остановку можно было привязать к ближайшей вершине;
    общие точки путей (стрелки) — общие вершины."""
    STEP_M = 15

    def __init__(self, ways: list[np.ndarray]):
        index: dict[tuple[float, float], int] = {}
        edges = []
        for way in ways:
            ids = [index.setdefault((round(x, 6), round(y, 6)), len(index)) for x, y in _densify(way, self.STEP_M)]
            edges += [(a, b) for a, b in zip(ids, ids[1:]) if a != b]
        self.lonlat = np.array(list(index), dtype=float).reshape(-1, 2)
        self.xy = _xy(self.lonlat[:, 0], self.lonlat[:, 1])
        self.adj: list[list[tuple[int, float]]] = [[] for _ in range(len(index))]
        for a, b in edges:
            w = float(np.hypot(*(self.xy[a] - self.xy[b])))
            self.adj[a].append((b, w))
            self.adj[b].append((a, w))

    def _nearest(self, p: np.ndarray) -> int | None:
        d = np.hypot(*(self.xy - p).T)
        i = int(d.argmin())
        return i if d[i] <= SNAP_M else None

    def path(self, a: np.ndarray, b: np.ndarray, limit: float) -> np.ndarray | None:
        """Кратчайший путь по рельсам между точками (в метрах) не длиннее limit → [[lon, lat], …] или None."""
        if not len(self.xy):
            return None
        s, t = self._nearest(a), self._nearest(b)
        if s is None or t is None or s == t:
            return None
        dist, prev, heap = {s: 0.0}, {}, [(0.0, s)]
        while heap:
            d, u = heapq.heappop(heap)
            if u == t:
                break
            if d > dist[u]:
                continue
            for v, w in self.adj[u]:
                if d + w <= limit and d + w < dist.get(v, np.inf):
                    dist[v], prev[v] = d + w, u
                    heapq.heappush(heap, (d + w, v))
        if t not in dist:
            return None
        path = [t]
        while path[-1] != s:
            path.append(prev[path[-1]])
        return self.lonlat[path[::-1]]


def route_lines(route_stops: pd.DataFrame, tracks: dict[int, list[np.ndarray]], rails: Rails | None = None) -> tuple[pd.DataFrame, dict]:
    """Линии маршрутов для карты (route, direction, i, lon, lat). Между соседними остановками — участок трассы relation OSM;
    если остановка к ней не привязалась — кратчайший путь по сети рельсов; если и его нет или путь несоразмерно
    длиннее прямой (2.5 × прямая + 150 м) — прямой отрезок."""
    rows, stats = [], {"segments_on_track": 0, "segments_on_rails": 0, "segments_straight": 0}
    for (route, direction), g in route_stops.sort_values("seq").groupby(["route", "direction"]):
        pts = g[["lon", "lat"]].to_numpy(dtype=float)
        pts_xy = _xy(pts[:, 0], pts[:, 1])
        best = None  # трасса, к которой по порядку привязалось больше всего остановок, — это и есть своё направление
        for line in tracks.get(int(route), []):
            line = _dedupe(line)
            if len(line) < 2:
                continue
            pos, cum = _project(pts_xy, _xy(line[:, 0], line[:, 1]))
            if best is None or np.isfinite(pos).sum() > np.isfinite(best[1]).sum():
                best = (line, pos, cum)
        parts = [pts[:1]]
        for k in range(1, len(pts)):
            limit = 2.5 * float(np.hypot(*(pts_xy[k] - pts_xy[k - 1]))) + 150
            part, kind = None, "segments_straight"
            if best is not None:
                line, pos, cum = best
                s0, s1 = pos[k - 1], pos[k]
                if np.isfinite(s0) and np.isfinite(s1) and s1 - s0 <= limit:
                    part, kind = _cut(line, cum, s0, s1), "segments_on_track"
            if part is None and rails is not None:
                part = rails.path(pts_xy[k - 1], pts_xy[k], limit)
                kind = "segments_on_rails" if part is not None else kind
            stats[kind] += 1
            parts.append(part if part is not None else pts[k - 1:k + 1])
        coords = _dedupe(np.vstack(parts))
        rows.append(pd.DataFrame({"route": int(route), "direction": int(direction), "i": np.arange(len(coords)),
                                  "lon": coords[:, 0].round(6), "lat": coords[:, 1].round(6)}))
    lines = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["route", "direction", "i", "lon", "lat"])
    return lines, stats


def run(cfg: Config) -> dict:
    route_stops, routes = load_reference(cfg)
    route_stops = route_stops.dropna(subset=["lat", "lon"])
    ref_routes = {int(r) for r in route_stops["route"].unique()}
    in_reference = sorted(int(r) for r in routes["route"])
    osm = load_osm(cfg)
    route_stops = add_osm_stops(route_stops, osm.stops)
    names = {r: n for r, n in osm.names.items() if r not in {int(x) for x in routes["route"]}}
    if names:  # у маршрутов не из справочника название берётся из OSM
        extra = pd.DataFrame({"route": list(names), "name": list(names.values())})
        routes = pd.concat([routes, extra], ignore_index=True) if len(routes) else extra
    if len(route_stops):
        route_stops = route_stops.assign(share=stop_shares(route_stops))
    else:
        route_stops = route_stops.assign(share=pd.Series(dtype=float))
    lines, line_stats = route_lines(route_stops, osm.tracks, Rails(osm.rails) if osm.rails else None)
    cfg.store_dir.mkdir(parents=True, exist_ok=True)
    route_stops.to_parquet(cfg.store_dir / "route_stops.parquet", index=False)
    routes.to_parquet(cfg.store_dir / "routes.parquet", index=False)
    lines.to_parquet(cfg.store_dir / "route_lines.parquet", index=False)
    return {"routes_in_reference": in_reference,
            "routes_with_stops": sorted(int(r) for r in route_stops["route"].unique()),
            "routes_from_osm": sorted({int(r) for r in route_stops["route"].unique()} - ref_routes),
            "stops": int(route_stops["stop_id"].nunique()), **line_stats}
