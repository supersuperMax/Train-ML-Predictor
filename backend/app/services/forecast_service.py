"""Запросы к прогнозу: горизонт → период, фильтры маршрут/остановка/часы, агрегация по шагу времени."""
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import Literal

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

from app.errors import ApiError, bad_request, not_found, not_ready
from dataclasses import replace

from app.services import datasets
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
    source: str = "model"                # model | baseline | file:<id>


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


_views: dict[tuple[str, str], Snapshot] = {}


def view(source: str | None = "model") -> Snapshot:
    """Данные для отображения: model — прогноз модели, baseline — полный baseline, file:<id> — прогноз модели
    только для ключей залитого файла. Все варианты — тот же Snapshot с подменённым кубом."""
    s = snapshot()
    src = (source or "model").strip()
    if src == "model":
        return s
    key = (s.version, src)
    if key in _views:
        return _views[key]
    if src == "baseline":
        if s.baseline_cube is None:
            raise not_found("Baseline недоступен: пайплайн его не опубликовал.", code="no_baseline")
        cube = s.baseline_cube
        src_arr = np.where(np.isnan(cube).all(axis=2), -1, SOURCES.index("baseline")).astype(np.int8)
    elif src.startswith("file:"):
        mask = datasets.aligned_mask(src[5:], s.routes, s.start, s.days)
        cube = np.where(mask, s.cube, np.nan).astype(np.float32)
        src_arr = np.where(mask.any(axis=2), s.source, -1).astype(np.int8)
    else:
        raise bad_request(f"Неизвестный источник данных «{src}». Допустимо: model, baseline, file:<id>.", code="unknown_source")
    if len(_views) > 32:
        _views.clear()
    _views[key] = replace(s, cube=cube, source=src_arr, day_total=np.nan_to_num(cube).sum(axis=2))
    return _views[key]


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
    s = view(q.source)
    r = resolve(s, q)
    w = weights(s, q.route, q.stop_id)
    points = _series(s, q, w, r)
    return {"query": _describe(s, q, r), "unit": "посадки", "total": round(sum(p["value"] for p in points), 1),
            "points": points}


def forecast(q: Query) -> dict:
    return _forecast_cached(snapshot().version, q)


@lru_cache(maxsize=4096)
def _summary_cached(version: str, q: Query) -> dict:
    s = view(q.source)
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
    s = view(q.source)
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
def _map_cached(version: str, day: str | None, hour: int | None, route: int | None, source: str) -> dict:
    s = view(source)
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


def map_state(day: str | None, hour: int | None, route: int | None, source: str = "model") -> dict:
    return _map_cached(snapshot().version, day, hour, route, source)



PREDICT_ERRORS = ["", "маршрут не число", "маршрут отсутствует в прогнозе", "дата не в формате ГГГГ-ММ-ДД",
                  "дата вне прогноза", "час не целое число", "час вне диапазона 0–23"]



def _as_str(a) -> pa.Array:
    """Колонка ключей → строки Arrow без пробелов по краям; None/NaN → ''."""
    if isinstance(a, pa.ChunkedArray):
        a = a.combine_chunks()
    if not isinstance(a, pa.Array):
        a = pa.array(["" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v) for v in a], pa.string())
    if a.type != pa.string():
        a = pc.cast(a, pa.string())
    return pc.fill_null(pc.utf8_trim_whitespace(a), "")


def _as_int(a: pa.Array) -> tuple[np.ndarray, np.ndarray]:
    """Целые из строк ('17', '17.0' из Excel). → (значения, признак корректности)."""
    valid = pc.match_substring_regex(a, r"^[+-]?\d{1,9}(\.0*)?$")
    clean = pc.if_else(valid, pc.replace_substring_regex(a, r"\.0*$", ""), "0")
    return pc.cast(clean, pa.int64()).to_numpy(), valid.to_numpy(zero_copy_only=False)


def predict_arrays(routes, dates, hours=None, source: str = "model") -> tuple[np.ndarray, pa.Array, pa.Array, int, dict]:
    """Векторный прогноз для набора ключей (маршрут, дата, час); пустой час — сумма за день.

    Колонки — массивы Arrow или списки. Разбор идёт в pyarrow.compute без объектов Python, поэтому быстро
    и с малой памятью. Возвращает значения (NaN при ошибке), источник и текст ошибки ('' — без ошибки), число строк без ошибок
    и индексы ключей (для маски набора данных).
    """
    s = view(source)
    rs, ds = _as_str(routes), _as_str(dates)
    n = len(rs)
    err = np.zeros(n, dtype=np.int8)

    def mark(cond, code):
        err[(err == 0) & cond] = code

    rt, rt_ok = _as_int(rs)
    mark(~rt_ok, 1)
    lut = np.full(max(s.routes) + 2, -1, dtype=np.int64)
    lut[s.routes] = np.arange(len(s.routes))
    ri = np.where(err == 0, lut[np.clip(rt, -1, len(lut) - 1)], -1)
    mark(ri < 0, 2)

    ts = pc.strptime(pc.utf8_slice_codeunits(ds, 0, 10), format="%Y-%m-%d", unit="s", error_is_null=True)
    secs = pc.fill_null(pc.cast(ts, pa.int64()), -(10 ** 12)).to_numpy()
    mark(secs == -(10 ** 12), 3)
    di = secs // 86400 - np.datetime64(s.start, "D").astype(np.int64)
    mark((di < 0) | (di >= s.days), 4)

    if hours is None:
        no_hour = np.ones(n, dtype=bool)
        hr = np.zeros(n, dtype=np.int64)
    else:
        hs = _as_str(hours)
        no_hour = pc.equal(hs, "").to_numpy(zero_copy_only=False)
        hr, hr_ok = _as_int(hs)
        mark(~no_hour & ~hr_ok, 5)
        mark(~no_hour & ((hr < 0) | (hr > 23)), 6)

    ok = err == 0
    values = np.full(n, np.nan)
    r_ok, d_ok = ri[ok], di[ok]
    v = s.day_total[r_ok, d_ok].astype(float)
    by_hour = ~no_hour[ok]
    if by_hour.any():
        v[by_hour] = np.nan_to_num(s.cube[r_ok[by_hour], d_ok[by_hour], hr[ok][by_hour]])
    values[ok] = v

    src = np.full(n, len(SOURCES) + 1, dtype=np.int8)              # '' для строк с ошибкой
    codes = s.source[r_ok, d_ok]
    src[ok] = np.where(codes >= 0, codes, len(SOURCES))              # 'none' — нет прогноза
    sources = pa.DictionaryArray.from_arrays(pa.array(src), pa.array(SOURCES + ["none", ""])).dictionary_decode()
    messages = list(PREDICT_ERRORS)
    messages[4] = f"дата вне прогноза ({_period_text(s)})"
    errors = pa.DictionaryArray.from_arrays(pa.array(err), pa.array(messages)).dictionary_decode()
    keys = {"ok": ok, "route": ri, "day": di, "hour": hr, "no_hour": no_hour}
    return values, sources, errors, int(ok.sum()), keys

def predict_keys(routes, dates, hours, source: str = "model") -> tuple[np.ndarray, list[str], list[str]]:
    """То же, что predict_arrays, для небольших списков (одно значение в GET /api/predict)."""
    values, sources, errors, _, _ = predict_arrays(routes, dates, hours, source)
    return values, sources.to_pylist(), errors.to_pylist()
