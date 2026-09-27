"""Наборы данных из файла: загрузить сырые валидации (или ключи route/date/hour) и смотреть на графиках и карте
прогноз модели по ним рядом с фактом из файла.

POST /api/datasets — файл (как у /api/predict/batch) → id набора; дальше source=file:<id> в /forecast, /summary, /map, /export.
"""
import shutil
from datetime import date
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.api.predict import MAX_XLSX_BYTES, _mb, _process, _receive
from app.errors import bad_request
from app.services import datasets, validations
from app.services import forecast_service as fs

router = APIRouter(tags=["datasets"])


def _is_raw(path: Path, name: str) -> bool:
    if name.lower().endswith((".xlsx", ".xls")):
        try:
            return validations.is_raw([str(c) for c in pd.read_excel(path, nrows=0).columns])
        except Exception:
            return False  # пусть понятную ошибку чтения даст общий путь
    return validations.is_raw(validations.csv_header(path)[0])


def _ru(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _from_validations(path: Path, name: str, out_csv: Path) -> tuple[dict, np.ndarray, list[int], date]:
    """Сырые валидации → фактические посадки route × date × hour на своей оси дат (прогноз модели ими не обрезается:
    на графике факт и прогноз идут на общей шкале), файл результата с прогнозом по тем же ключам."""
    s = fs.snapshot()
    agg, rows, skipped, trimmed = validations.aggregate(path, name)
    values, sources, errors, n_ok, _ = fs.predict_arrays(agg["route"].astype(str).tolist(), agg["date"].tolist(),
                                                         agg["hour"].astype(str).tolist())
    result = agg.assign(prediction=np.round(values, 1), source=sources.to_pylist(), error=errors.to_pylist())
    out_csv.write_bytes(result.to_csv(index=False, sep=";").encode("utf-8-sig"))

    known = agg[agg["route"].isin(s.routes)]
    if known.empty:
        raise bad_request(f"В файле нет маршрутов прогноза ({', '.join(map(str, s.routes))}): найдены "
                          f"{', '.join(map(str, sorted(agg['route'].unique())))}.", code="unknown_routes")
    dates = pd.to_datetime(known["date"]).dt.date
    f_start, f_end = dates.min(), dates.max()
    routes = sorted(int(r) for r in known["route"].unique())
    fact = np.full((len(routes), (f_end - f_start).days + 1, 24), np.nan, dtype=np.float32)
    ri = known["route"].map({r: i for i, r in enumerate(routes)}).to_numpy()
    di = np.array([(d - f_start).days for d in dates])
    fact[ri, di, known["hour"].to_numpy()] = known["fact"].to_numpy()

    lo, hi = max(f_start, s.start), min(f_end, s.end)
    meta = {
        "kind": "validations", "rows": rows, "skipped": skipped, "boardings": int(known["fact"].sum()),
        "keys": len(agg), "ok": n_ok, "errors": len(agg) - n_ok,
        "range": [f_start.isoformat(), f_end.isoformat()], "routes": routes, "trimmed_days": trimmed,
        "overlap": [lo.isoformat(), hi.isoformat()] if lo <= hi else None,
    }
    if lo > hi:
        meta["note"] = (f"Факт из файла — {_ru(f_start)}–{_ru(f_end)}, прогноз модели — {_ru(s.start)}–{_ru(s.end)}: "
                        "периоды не пересекаются, на графике они идут подряд.")
    other = sorted(int(r) for r in set(agg["route"]) - set(routes))
    if other:
        meta["warning"] = f"Маршрутов {', '.join(map(str, other))} нет в прогнозе — их посадки есть только в файле результата."
    return meta, fact, routes, f_start


@router.post("/datasets", summary="Загрузить файл сырых валидаций или ключей (CSV до 2,5 ГБ / XLSX до 50 МБ) как набор данных")
async def create_dataset(request: Request):
    """Тело — сам файл (имя в ?filename=) или multipart с полем file.

    - Сырые валидации (tran_date_time, validation_result, ngpt_route, …): посадки сворачиваются по route × date × hour
      (неполные крайние дни отбрасываются); графики и карта показывают полный прогноз модели и факт из файла на общей шкале
      дат; результат — route;date;hour;fact;prediction;source;error.
    - Файл ключей (route, date, необязательная hour): прогноз модели по ключам.

    Ответ — сведения о наборе; данные — через source=file:<id>, файл результата — /api/datasets/<id>/result.
    """
    s = fs.snapshot()
    ds_id, work = datasets.new_dir()
    try:
        name, size = await _receive(request, work / "input")
        if await run_in_threadpool(_is_raw, work / "input", name):
            if name.lower().endswith((".xlsx", ".xls")) and size > MAX_XLSX_BYTES:
                raise bad_request(f"XLSX больше {_mb(MAX_XLSX_BYTES)}: сохраните таблицу как CSV (UTF-8).", code="xlsx_too_large")
            meta, fact, routes, f_start = await run_in_threadpool(_from_validations, work / "input", name, work / "result.csv")
            (work / "input").unlink(missing_ok=True)
            meta = {"name": name, **meta, "source": f"file:{ds_id}", "result_url": f"/api/datasets/{ds_id}/result"}
            return datasets.save(ds_id, meta, routes, f_start, fact=fact)
        mask = np.zeros((len(s.routes), s.days, 24), dtype=bool)
        res = await run_in_threadpool(_process, work / "input", name, size, work / "result.csv", "csv", mask)
        (work / "input").unlink(missing_ok=True)
        days = np.flatnonzero(mask.any(axis=(0, 2)))
        routes = [s.routes[i] for i in np.flatnonzero(mask.any(axis=(1, 2)))]
        meta = {
            "name": name, "kind": "keys",
            "rows": res["rows"], "ok": res["ok"], "errors": res["rows"] - res["ok"],
            "range": [s.date_at(days[0]).isoformat(), s.date_at(days[-1]).isoformat()] if len(days) else None,
            "routes": routes,
            "cells": int(mask.sum()),
            "source": f"file:{ds_id}",
            "result_url": f"/api/datasets/{ds_id}/result",
        }
        return datasets.save(ds_id, meta, s.routes, s.start, mask=mask)
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
