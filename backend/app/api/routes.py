from typing import Optional

from fastapi import APIRouter, Query

from app.errors import not_found
from app.services import forecast_service as fs
from app.services.snapshot import store

router = APIRouter(tags=["reference"])


@router.get("/routes", summary="Маршруты с прогнозом")
def routes():
    s = fs.snapshot()
    with_stops = set(s.manifest.get("routes_with_stops") or [])
    return [{"route": r, "name": s.route_names.get(r), "has_stops": r in with_stops} for r in s.routes]


@router.get("/stops", summary="Остановки с координатами и линии маршрутов")
def stops(route: Optional[int] = Query(None, description="Только остановки маршрута")):
    s = fs.snapshot()
    df, lines = s.stops, s.lines
    if route is not None:
        if route not in s.route_idx:
            raise not_found(f"Маршрут {route} не найден. Доступные маршруты: {', '.join(map(str, s.routes))}.",
                            code="unknown_route")
        df = df[df["routes"].apply(lambda rs: route in rs)]
        lines = [ln for ln in lines if ln["route"] == route]
    return {
        "stops": [{"stop_id": int(r.stop_id), "name": r.name, "lat": float(r.lat), "lon": float(r.lon),
                   "routes": list(r.routes)} for r in df.itertuples(index=False)],
        "lines": lines,
    }


@router.get("/map", summary="Нагрузка на остановки в момент времени (для карты)")
def map_state(
    date: Optional[str] = Query(None, description="Дата, ГГГГ-ММ-ДД"),
    hour: Optional[int] = Query(None, description="Час 0–23; без него — сумма за день"),
    route: Optional[int] = Query(None, description="Только один маршрут"),
):
    return fs.map_state(date, hour, route)


@router.get("/meta", summary="Версия прогноза, доступный период, факторы модели, статус пайплайна")
def meta():
    s = store.get()
    run = store.last_run()
    last_run = {k: run.get(k) for k in ("started_at", "finished_at", "status", "error", "version")} if run else None
    if s is None:
        return {"ready": False, "last_run": last_run}
    m = s.manifest
    return {
        "ready": True,
        "version": s.version,
        "created_at": m.get("created_at"),
        "available": {"from": s.start.isoformat(), "to": s.end.isoformat()},
        "sources": m.get("sources"),
        "model": m.get("model"),
        "model_mode": m.get("model_mode"),
        "history_range": m.get("history_range"),
        "routes": s.routes,
        "routes_with_stops": m.get("routes_with_stops"),
        "factors": m.get("factors"),
        "weather": m.get("weather"),
        "stop_forecast_method": m.get("stop_forecast_method"),
        "horizons": {"day": "по часам", "month": "по дням", "year": "по месяцам"},
        "last_run": last_run,
    }
