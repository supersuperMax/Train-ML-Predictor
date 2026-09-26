"""Запросы к прогнозу: горизонт → период, фильтры маршрут/остановка/часы, агрегация по шагу времени."""
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import Literal

import numpy as np

from app.errors import ApiError, bad_request, not_found, not_ready
from app.services.snapshot import SOURCES, Snapshot, store

Horizon = Literal["day", "month", "year"]
Granularity = Literal["hour", "day", "week", "month"]

DEFAULT_GRANULARITY = {"day": "hour", "month": "day", "year": "month"}
MAX_HOURLY_DAYS = 93
DAYTYPES = ["weekday", "sat", "sun", "holiday"]


@dataclass(frozen=True)
class Query:
    horizon: Horizon | None = None
    anchor: str | None = None          # дата начала горизонта (ГГГГ-ММ-ДД)
    date_from: str | None = None
    date_to: str | None = None
    route: int | None = None
    stop_id: int | None = None
    hour_from: int = 0
    hour_to: int = 23
    granularity: Granularity | None = None


@dataclass(frozen=True)
class Resolved:
    d0: date
    d1: date
    horizon: str | None
    granularity: str
    truncated: bool


def snapshot() -> Snapshot:
    snap = store.get()
    if snap is None:
        raise not_ready()
    return snap


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise bad_request(f"Неверный формат даты в параметре «{name}»: «{value}». Ожидается ГГГГ-ММ-ДД, например 2025-11-01.",
                          code="invalid_date")


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    last = (date(y + (m + 1) // 12, (m + 1) % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m + 1, min(d.day, last))


def _period_text(s: Snapshot) -> str:
    return f"{s.start.isoformat()} … {s.end.isoformat()}"


def resolve(s: Snapshot, q: Query) -> Resolved:
    if not 0 <= q.hour_from <= 23 or not 0 <= q.hour_to <= 23:
        raise bad_request("Часы должны быть в диапазоне 0–23.", code="invalid_hours")
    if q.hour_from > q.hour_to:
        raise bad_request(f"Начальный час ({q.hour_from}) больше конечного ({q.hour_to}).", code="invalid_hours")

    if q.date_from or q.date_to:
        d0 = _parse_date(q.date_from, "from") if q.date_from else s.start
        d1 = _parse_date(q.date_to, "to") if q.date_to else s.end
    else:
        horizon = q.horizon or "day"
        d0 = _parse_date(q.anchor, "date") if q.anchor else s.start
        d1 = {"day": d0, "month": _add_months(d0, 1) - timedelta(days=1),
              "year": _add_months(d0, 12) - timedelta(days=1)}[horizon]
    if d0 > d1:
        raise bad_request(f"Начало периода ({d0}) позже конца ({d1}).", code="invalid_period")
    if d1 < s.start or d0 > s.end:
        raise not_found(f"Нет прогноза за период {d0} … {d1}. Доступен прогноз за {_period_text(s)}.",
                        code="out_of_range", available={"from": s.start.isoformat(), "to": s.end.isoformat()})
    c0, c1 = max(d0, s.start), min(d1, s.end)

    horizon = None if (q.date_from or q.date_to) else (q.horizon or "day")
    span = (c1 - c0).days + 1
    if q.granularity:
        gran = q.granularity
    elif horizon:
        gran = DEFAULT_GRANULARITY[horizon]
    else:
        gran = "hour" if span == 1 else "day" if span <= 62 else "month"
    if gran == "hour" and span > MAX_HOURLY_DAYS:
        raise bad_request(f"Почасовая детализация доступна для периода до {MAX_HOURLY_DAYS} дней, запрошено {span}. "
                          f"Выберите шаг day, week или month.", code="period_too_long")
    return Resolved(c0, c1, horizon, gran, truncated=(c0, c1) != (d0, d1))


def weights(s: Snapshot, route: int | None, stop_id: int | None) -> np.ndarray:
    """Вес каждого маршрута в запрошенной сущности: все маршруты, один маршрут или доля остановки."""
    w = np.ones(len(s.routes), dtype=np.float32)
    if route is not None:
        if route not in s.route_idx:
            raise not_found(f"Маршрут {route} не найден. Доступные маршруты: {', '.join(map(str, s.routes))}.",
                            code="unknown_route")
        w = np.zeros_like(w)
        w[s.route_idx[route]] = 1
    if stop_id is not None:
        if stop_id not in s.stop_idx:
            raise not_found(f"Остановка {stop_id} не найдена. Прогноз по остановкам есть для маршрутов "
                            f"{', '.join(map(str, s.manifest.get('routes_with_stops') or [])) or '—'}.",
                            code="unknown_stop")
        col = s.share[:, s.stop_idx[stop_id]]
        w = w * col
        if not w.any():
            raise not_found(f"Остановка {stop_id} не обслуживается маршрутом {route}.", code="stop_not_on_route")
    return w


def _bucket_keys(s: Snapshot, d0: date, n_days: int, gran: str) -> list[str]:
    days = [d0 + timedelta(days=i) for i in range(n_days)]
    if gran == "day":
        return [d.isoformat() for d in days]
    if gran == "week":
        return [(d - timedelta(days=d.weekday())).isoformat() for d in days]
    return [f"{d.year}-{d.month:02d}" for d in days]


def _source_label(codes: np.ndarray) -> str:
    present = {SOURCES[c] for c in np.unique(codes) if c >= 0}
    if not present:
        return "none"
    return present.pop() if len(present) == 1 else "mixed"


def _series(s: Snapshot, q: Query, w: np.ndarray, r: Resolved) -> list[dict]:
    a, b = s.day(r.d0), s.day(r.d1) + 1
    sub = s.cube[:, a:b, q.hour_from:q.hour_to + 1]
    values = np.tensordot(w, np.nan_to_num(sub), axes=(0, 0))          # [D, H]
    active = w > 0
    src = s.source[active, a:b]                                        # [R', D]

    if r.granularity == "hour":
        points = []
        for i in range(b - a):
            d = s.date_at(a + i).isoformat()
            label = _source_label(src[:, i])
            for j, h in enumerate(range(q.hour_from, q.hour_to + 1)):
                points.append({"t": f"{d}T{h:02d}:00", "date": d, "hour": h,
                               "value": round(float(values[i, j]), 1), "source": label})
        return points

    daily = values.sum(axis=1)
    keys = _bucket_keys(s, r.d0, b - a, r.granularity)
    points, order = {}, []
    for i, k in enumerate(keys):
        if k not in points:
            points[k] = {"t": k, "value": 0.0, "days": 0, "_src": []}
            order.append(k)
        p = points[k]
        p["value"] += float(daily[i])
        p["days"] += 1
        p["_src"].append(src[:, i])
    out = []
    for k in order:
        p = points[k]
        out.append({"t": k, "value": round(p["value"], 1), "days": p["days"],
                    "source": _source_label(np.concatenate(p["_src"]) if p["_src"] else np.array([], dtype=np.int8))})
    return out


def _describe(s: Snapshot, q: Query, r: Resolved) -> dict:
    return {
        "horizon": r.horizon, "granularity": r.granularity,
        "from": r.d0.isoformat(), "to": r.d1.isoformat(),
        "hour_from": q.hour_from, "hour_to": q.hour_to,
        "route": q.route, "stop_id": q.stop_id,
        "stop_name": s.stops.iloc[s.stop_idx[q.stop_id]]["name"] if q.stop_id is not None else None,
        "truncated": r.truncated,
        "available": {"from": s.start.isoformat(), "to": s.end.isoformat()},
        "version": s.version,
    }


@lru_cache(maxsize=4096)
def _forecast_cached(version: str, q: Query) -> dict:
    s = snapshot()
    r = resolve(s, q)
    w = weights(s, q.route, q.stop_id)
    points = _series(s, q, w, r)
    return {"query": _describe(s, q, r), "unit": "посадки", "total": round(sum(p["value"] for p in points), 1),
            "points": points}


def forecast(q: Query) -> dict:
    return _forecast_cached(snapshot().version, q)


@lru_cache(maxsize=4096)
def _summary_cached(version: str, q: Query) -> dict:
    s = snapshot()
    r = resolve(s, q)
    w = weights(s, q.route, q.stop_id)
    a, b = s.day(r.d0), s.day(r.d1) + 1
    values = np.tensordot(w, np.nan_to_num(s.cube[:, a:b, q.hour_from:q.hour_to + 1]), axes=(0, 0))  # [D, H]
    daily = values.sum(axis=1)
    total = float(daily.sum())
    n_days = b - a

    hours = list(range(q.hour_from, q.hour_to + 1))
    by_hour = values.mean(axis=0)
    di, hi = np.unravel_index(int(values.argmax()), values.shape) if values.size else (0, 0)
    peak_day = int(daily.argmax()) if n_days else 0

    types = s.daytype[a:b]
    by_daytype = {}
    for t in DAYTYPES:
        m = types == t
        if m.any():
            by_daytype[t] = {"days": int(m.sum()), "total": round(float(daily[m].sum()), 1),
                             "per_day": round(float(daily[m].mean()), 1)}

    src = s.source[w > 0, a:b]
    return {
        "query": _describe(s, q, r),
        "total": round(total, 1),
        "days": n_days,
        "per_day": round(total / n_days, 1) if n_days else 0,
        "per_hour": round(float(values.mean()), 1) if values.size else 0,
        "peak": {"date": s.date_at(a + int(di)).isoformat(), "hour": hours[int(hi)],
                 "value": round(float(values[di, hi]), 1)} if values.size else None,
        "peak_day": {"date": s.date_at(a + peak_day).isoformat(), "value": round(float(daily[peak_day]), 1)} if n_days else None,
        "peak_hour_of_day": {"hour": hours[int(by_hour.argmax())], "avg": round(float(by_hour.max()), 1)} if values.size else None,
        "by_daytype": by_daytype,
        "source": _source_label(src.ravel()),
    }


def summary(q: Query) -> dict:
    return _summary_cached(snapshot().version, q)


def table(q: Query) -> tuple[list[dict], dict]:
    """Строки для экспорта: ряд по каждому маршруту (и остановке, если выбрана) с тем же шагом, что и /forecast."""
    s = snapshot()
    r = resolve(s, q)
    routes = [q.route] if q.route is not None else s.routes
    rows = []
    for route in routes:
        try:
            w = weights(s, route, q.stop_id)
        except ApiError:
            if q.route is None:   # остановка лежит не на всех маршрутах — пропускаем лишние
                continue
            raise
        for p in _series(s, q, w, r):
            row = {"period": p["t"], "route": route}
            if q.stop_id is not None:
                row["stop_id"] = q.stop_id
                row["stop_name"] = s.stops.iloc[s.stop_idx[q.stop_id]]["name"]
            row["prediction"] = p["value"]
            row["source"] = p["source"]
            rows.append(row)
    if not rows and q.stop_id is not None:
        weights(s, q.route, q.stop_id)  # поднимет понятную ошибку
    return rows, _describe(s, q, r)


@lru_cache(maxsize=4096)
def _map_cached(version: str, day: str | None, hour: int | None, route: int | None) -> dict:
    s = snapshot()
    d = _parse_date(day, "date") if day else s.start
    if not s.start <= d <= s.end:
        raise not_found(f"Нет прогноза на {d}. Доступен прогноз за {_period_text(s)}.", code="out_of_range",
                        available={"from": s.start.isoformat(), "to": s.end.isoformat()})
    if hour is not None and not 0 <= hour <= 23:
        raise bad_request("Час должен быть в диапазоне 0–23.", code="invalid_hours")
    w = weights(s, route, None)
    i = s.day(d)
    per_route = np.nan_to_num(s.cube[:, i, hour] if hour is not None else s.cube[:, i, :].sum(axis=1)) * w
    per_stop = per_route @ s.share
    mask = (s.share[w > 0].sum(axis=0) > 0) if len(s.stops) else np.array([], dtype=bool)
    stops = [{"stop_id": int(sid), "value": round(float(v), 1)}
             for sid, v, m in zip(s.stops["stop_id"], per_stop, mask) if m]
    return {
        "date": d.isoformat(), "hour": hour, "route": route, "version": s.version,
        "stops": stops,
        "max": max((x["value"] for x in stops), default=0),
        "routes": [{"route": rt, "value": round(float(per_route[s.route_idx[rt]]), 1)}
                   for rt in s.routes if w[s.route_idx[rt]] > 0],
        "source": _source_label(s.source[w > 0, i]),
    }


def map_state(day: str | None, hour: int | None, route: int | None) -> dict:
    return _map_cached(snapshot().version, day, hour, route)
