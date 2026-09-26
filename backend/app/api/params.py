"""Общие параметры запроса прогноза — одинаковые для /forecast, /summary и экспорта."""
from typing import Optional

from fastapi import Query as Q

from app.services.forecast_service import Granularity, Horizon, Query


def forecast_query(
    horizon: Optional[Horizon] = Q(None, description="Горизонт: day (по часам), month (по дням), year (по месяцам)"),
    date: Optional[str] = Q(None, description="Дата начала горизонта, ГГГГ-ММ-ДД (по умолчанию — первый день прогноза)"),
    date_from: Optional[str] = Q(None, alias="from", description="Начало периода, ГГГГ-ММ-ДД (вместо horizon/date)"),
    date_to: Optional[str] = Q(None, alias="to", description="Конец периода включительно, ГГГГ-ММ-ДД"),
    route: Optional[int] = Q(None, description="Номер маршрута; без него — сумма по всем маршрутам"),
    stop_id: Optional[int] = Q(None, description="Остановка (stop_id из /api/stops)"),
    hour_from: int = Q(0, ge=0, le=23, description="Начальный час интервала"),
    hour_to: int = Q(23, ge=0, le=23, description="Конечный час интервала включительно"),
    granularity: Optional[Granularity] = Q(None, description="Шаг: hour, day, week, month (по умолчанию из горизонта)"),
    source: str = Q("model", description="Данные: model — прогноз модели, baseline, file:<id> — ключи залитого файла"),
) -> Query:
    return Query(horizon=horizon, anchor=date, date_from=date_from, date_to=date_to, route=route, stop_id=stop_id,
                 hour_from=hour_from, hour_to=hour_to, granularity=granularity, source=source)
