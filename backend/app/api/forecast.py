from fastapi import APIRouter, Depends

from app.api.params import forecast_query
from app.services import forecast_service as fs

router = APIRouter(tags=["forecast"])


@router.get("/forecast", summary="Прогноз посадок с агрегацией по времени")
def forecast(q: fs.Query = Depends(forecast_query)):
    return fs.forecast(q)


@router.get("/summary", summary="Сводка: итог, пики, разбивка по типу дня")
def summary(q: fs.Query = Depends(forecast_query)):
    return fs.summary(q)
