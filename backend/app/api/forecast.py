from typing import Optional
from fastapi import APIRouter, Query
from app.services.forecast_service import service

router = APIRouter(tags=["forecast"])

@router.get("/forecast")
def forecast(
    route: Optional[str] = None,
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
):
    return service.forecast(route, date_from, date_to)

@router.get("/summary")
def summary(
    route: Optional[str] = None,
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
):
    return service.summary(route, date_from, date_to)
