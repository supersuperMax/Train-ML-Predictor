from fastapi import APIRouter
from app.services.forecast_service import service

router = APIRouter(tags=["reference"])

@router.get("/routes")
def routes():
    if service.df.empty:
        return []
    return sorted(service.df["route"].astype(str).unique().tolist())

@router.get("/stops")
def stops():
    # Будет подключено после получения справочника остановок.
    return []
