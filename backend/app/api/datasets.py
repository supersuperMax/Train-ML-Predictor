"""Наборы данных из файла: загрузить ключи route/date/hour и смотреть прогноз модели по ним на графиках и карте.

POST /api/datasets — файл (как у /api/predict/batch) → id набора; дальше source=file:<id> в /forecast, /summary, /map, /export.
"""
import shutil
from pathlib import Path
from urllib.parse import quote

import numpy as np
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.api.predict import _process, _receive
from app.services import datasets
from app.services import forecast_service as fs

router = APIRouter(tags=["datasets"])


@router.post("/datasets", summary="Загрузить файл ключей (CSV до 2,5 ГБ / XLSX до 50 МБ) как набор данных для графиков и карты")
async def create_dataset(request: Request):
    """Тело — сам файл (имя в ?filename=) или multipart с полем file. Колонки route, date и необязательная hour.
    Ответ — сведения о наборе; прогноз по ключам файла — через source=file:<id>, файл с прогнозом — /api/datasets/<id>/result.
    """
    s = fs.snapshot()
    ds_id, work = datasets.new_dir()
    try:
        name, size = await _receive(request, work / "input")
        mask = np.zeros((len(s.routes), s.days, 24), dtype=bool)
        res = await run_in_threadpool(_process, work / "input", name, size, work / "result.csv", "csv", mask)
        (work / "input").unlink(missing_ok=True)
        days = np.flatnonzero(mask.any(axis=(0, 2)))
        routes = [s.routes[i] for i in np.flatnonzero(mask.any(axis=(1, 2)))]
        meta = {
            "name": name,
            "rows": res["rows"], "ok": res["ok"], "errors": res["rows"] - res["ok"],
            "range": [s.date_at(days[0]).isoformat(), s.date_at(days[-1]).isoformat()] if len(days) else None,
            "routes": routes,
            "cells": int(mask.sum()),
            "source": f"file:{ds_id}",
            "result_url": f"/api/datasets/{ds_id}/result",
        }
        return datasets.save(ds_id, mask, s.routes, s.start, meta)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


@router.get("/datasets/{ds_id}", summary="Сведения о наборе данных")
def get_dataset(ds_id: str):
    return datasets.info(ds_id)


@router.get("/datasets/{ds_id}/result", summary="Скачать файл ключей с прогнозом (prediction, source, error)")
def dataset_result(ds_id: str):
    path = datasets.path_for(ds_id)
    name = Path(datasets.info(ds_id)["name"]).stem or "keys"
    return FileResponse(path / "result.csv", media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name + '_prediction.csv')}"})
