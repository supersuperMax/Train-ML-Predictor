from io import BytesIO
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.params import forecast_query
from app.services import forecast_service as fs

router = APIRouter(tags=["export"])

COLUMNS = {"period": "Период", "route": "Маршрут", "stop_id": "ID остановки", "stop_name": "Остановка",
           "fact": "Факт посадок", "prediction": "Прогноз посадок", "source": "Источник"}


def _frame(q: fs.Query) -> tuple[pd.DataFrame, str]:
    rows, desc = fs.table(q)
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["period", "route", "prediction", "source"])
    df = df.rename(columns=COLUMNS)
    parts = ["forecast", f"route{q.route}" if q.route is not None else "all"]
    if q.stop_id is not None:
        parts.append(f"stop{q.stop_id}")
    parts += [desc["from"], desc["to"], desc["granularity"]]
    return df, "_".join(parts)


def _attachment(name: str) -> dict:
    return {"Content-Disposition": f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}"}


@router.get("/export/csv", summary="Выгрузка прогноза в CSV (разделитель ;)")
def export_csv(q: fs.Query = Depends(forecast_query)):
    df, name = _frame(q)
    content = df.to_csv(index=False, sep=";").encode("utf-8-sig")
    return Response(content, media_type="text/csv; charset=utf-8", headers=_attachment(f"{name}.csv"))


@router.get("/export/xlsx", summary="Выгрузка прогноза в XLSX")
def export_xlsx(q: fs.Query = Depends(forecast_query)):
    df, name = _frame(q)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="forecast")
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=_attachment(f"{name}.xlsx"))
