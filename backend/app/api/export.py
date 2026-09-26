from io import BytesIO, StringIO
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
import pandas as pd
from app.services.forecast_service import service

router = APIRouter(tags=["export"])

def get_df(route, date_from, date_to):
    return pd.DataFrame(service.forecast(route, date_from, date_to))

@router.get("/export/csv")
def export_csv(route: Optional[str] = None, date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to")):
    df = get_df(route, date_from, date_to)
    content = df.to_csv(index=False).encode("utf-8-sig")
    return StreamingResponse(BytesIO(content), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=forecast.csv"})

@router.get("/export/xlsx")
def export_xlsx(route: Optional[str] = None, date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to")):
    df = get_df(route, date_from, date_to)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="forecast")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=forecast.xlsx"})
