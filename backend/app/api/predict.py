"""Прогон данных на модели: прогноз для одного ключа или для множества ключей из файла.

Модель не пересобирается — значения берутся из опубликованного прогноза (того же, что отдаёт /forecast).
Файл обрабатывается потоком: CSV до 1 ГБ читается и пишется блоками через pyarrow, память ограничена размером блока.
"""
import csv
import os
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pa_csv
from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, ORJSONResponse, Response
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.errors import ApiError, bad_request, not_found
from app.services import forecast_service as fs

router = APIRouter(tags=["predict"])

MAX_BYTES = int(os.environ.get("PREDICT_MAX_BYTES", int(2.5 * 1024 ** 3)))  # CSV — до 2,5 ГБ
MAX_XLSX_BYTES = int(os.environ.get("PREDICT_MAX_XLSX_BYTES", 50 * 1024 ** 2))  # XLSX читается целиком — до 50 МБ
TMP_DIR = os.environ.get("PREDICT_TMP_DIR") or None
MAX_XLSX_ROWS = 1_048_575   # предел листа Excel без заголовка
MAX_JSON_ROWS = 100_000
BLOCK_BYTES = 16 * 1024 ** 2
ALIASES = {
    "route": {"route", "маршрут", "маршрут №", "номер маршрута"},
    "date": {"date", "дата"},
    "hour": {"hour", "час"},
}


def _mb(n: int) -> str:
    return f"{n / 1024 ** 3:g} ГБ".replace(".", ",") if n >= 1024 ** 3 else f"{n / 1024 ** 2:.0f} МБ"


@router.get("/predict", summary="Прогноз для одного значения: маршрут, дата, час (без часа — за день)")
def predict_one(
    route: int = Query(..., description="Номер маршрута"),
    date: str = Query(..., description="Дата, ГГГГ-ММ-ДД"),
    hour: Optional[int] = Query(None, description="Час 0–23; без него — сумма за день"),
    source: Literal["model", "baseline"] = Query("model", description="model — прогноз модели, baseline"),
):
    values, sources, errors = fs.predict_keys([route], [date], [hour], source)
    if errors[0]:
        text = errors[0][0].upper() + errors[0][1:] + "."
        if "отсутствует" in text or "вне прогноза" in text:
            raise not_found(text, code="not_in_forecast")
        raise bad_request(text, code="invalid_key")
    return {"route": route, "date": date, "hour": hour, "prediction": round(float(values[0]), 1), "source": sources[0]}


# ---------- приём файла ----------

async def _receive(request: Request, dest: Path) -> tuple[str, int]:
    """Сохраняет тело запроса в dest. Сырое тело (сайт, curl --data-binary) или multipart (curl -F). → (имя, размер)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES + 1024 * 1024:
        raise ApiError(413, "file_too_large", f"Файл больше {_mb(MAX_BYTES)}.")
    size = 0
    ctype = request.headers.get("content-type", "")
    with open(dest, "wb") as out:
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None or isinstance(upload, str):
                raise bad_request("В форме нет файла: поле должно называться file.", code="bad_file")
            name = upload.filename or "keys.csv"
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ApiError(413, "file_too_large", f"Файл больше {_mb(MAX_BYTES)}.")
                out.write(chunk)
        else:
            name = request.query_params.get("filename") or "keys.csv"
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ApiError(413, "file_too_large", f"Файл больше {_mb(MAX_BYTES)}.")
                out.write(chunk)
    if size == 0:
        raise bad_request("Файл пустой.", code="bad_file")
    return name, size


# ---------- обработка ----------

def _columns(names: list[str]) -> dict[str, str | None]:
    found = {key: next((c for c in names if str(c).strip().lower() in aliases), None) for key, aliases in ALIASES.items()}
    missing = [k for k in ("route", "date") if found[k] is None]
    if missing:
        raise bad_request(f"В файле нет колонок {', '.join(missing)}. Нужны route, date и (необязательно) hour "
                          f"— или «Маршрут», «Дата», «Час». Найдены: {', '.join(map(str, names)) or '—'}.",
                          code="missing_columns")
    return found


def _csv_batches(path: Path):
    with open(path, "rb") as f:
        head = f.readline(1024 * 1024)
    try:
        first = head.decode("utf-8-sig").rstrip("\r\n")
    except UnicodeDecodeError:
        raise bad_request("Файл не в кодировке UTF-8. Сохраните CSV в UTF-8 или загрузите XLSX.", code="bad_file")
    if not first.strip():
        raise bad_request("В первой строке файла нет заголовка.", code="bad_file")
    sep = ";" if first.count(";") >= first.count(",") else ","
    names = next(csv.reader([first], delimiter=sep))
    cols = _columns(names)
    try:
        reader = pa_csv.open_csv(
            path,
            read_options=pa_csv.ReadOptions(column_names=names, skip_rows=1, block_size=BLOCK_BYTES),
            parse_options=pa_csv.ParseOptions(delimiter=sep),
            convert_options=pa_csv.ConvertOptions(column_types={n: pa.string() for n in names},
                                                  strings_can_be_null=False, quoted_strings_can_be_null=False),
        )
    except pa.ArrowInvalid as e:
        raise bad_request(f"Не удалось разобрать CSV: {e}", code="bad_file")
    return cols, reader


def _xlsx_batches(path: Path, size: int):
    if size > MAX_XLSX_BYTES:
        raise bad_request(f"XLSX больше {_mb(MAX_XLSX_BYTES)}: сохраните таблицу как CSV (UTF-8) — CSV принимается до {_mb(MAX_BYTES)}.",
                          code="xlsx_too_large")
    try:
        df = pd.read_excel(path, dtype=str).fillna("")
    except Exception as e:
        raise bad_request(f"Не удалось прочитать XLSX: {e}", code="bad_file")
    df.columns = [str(c) for c in df.columns]
    cols = _columns(list(df.columns))
    return cols, pa.Table.from_pandas(df, preserve_index=False).to_batches(max_chunksize=1_000_000)


def _predict_batch(batch: pa.RecordBatch, cols: dict, mask: np.ndarray | None = None) -> tuple[pa.RecordBatch, int]:
    col = lambda name: batch.column(batch.schema.get_field_index(name))
    hours = col(cols["hour"]) if cols["hour"] else None
    values, sources, errors, n_ok, keys = fs.predict_arrays(col(cols["route"]), col(cols["date"]), hours)
    if mask is not None:  # набор данных для графиков: отмечаем ключи файла (без часа — весь день)
        ok = keys["ok"]
        by_hour, whole_day = ok & ~keys["no_hour"], ok & keys["no_hour"]
        mask[keys["route"][by_hour], keys["day"][by_hour], keys["hour"][by_hour]] = True
        mask[keys["route"][whole_day], keys["day"][whole_day], :] = True
    out = pa.RecordBatch.from_arrays(
        [*batch.columns, pa.array(np.round(values, 1), from_pandas=True), sources, errors],
        names=[*batch.schema.names, "prediction", "source", "error"],
    )
    return out, n_ok


def _process(src: Path, name: str, size: int, out_csv: Path, fmt: str | None, mask: np.ndarray | None = None) -> dict:
    is_xlsx = name.lower().endswith((".xlsx", ".xls"))
    cols, batches = _xlsx_batches(src, size) if is_xlsx else _csv_batches(src)
    fmt = fmt or ("xlsx" if is_xlsx else "csv")
    keep_limit = {"xlsx": MAX_XLSX_ROWS, "json": MAX_JSON_ROWS}.get(fmt)
    rows = ok = 0
    kept: list[pa.RecordBatch] = []
    writer = None
    with open(out_csv, "wb") as f:
        f.write("﻿".encode())  # BOM — Excel откроет UTF-8 CSV без кракозябр
        try:
            for batch in batches:
                if batch.num_rows == 0:
                    continue
                res, n_ok = _predict_batch(batch, cols, mask)
                rows += res.num_rows
                ok += n_ok
                if keep_limit is not None:
                    if rows > keep_limit:
                        raise bad_request(f"Для ответа в {fmt.upper()} допускается до {keep_limit:,} строк".replace(",", " ")
                                          + " — выберите format=csv.", code="too_many_rows")
                    kept.append(res)
                else:
                    if writer is None:
                        # заголовок пишем сами: Arrow всегда берёт имена колонок в кавычки
                        f.write((";".join(res.schema.names) + "\n").encode())
                        writer = pa_csv.CSVWriter(f, res.schema, write_options=pa_csv.WriteOptions(
                            include_header=False, delimiter=";", quoting_style="none"))
                    writer.write_batch(res)
        except pa.ArrowInvalid as e:
            raise bad_request(f"Ошибка в данных файла: {e}", code="bad_file")
        finally:
            if writer is not None:
                writer.close()
    if rows == 0:
        raise bad_request("В файле нет строк с данными.", code="bad_file")
    table = pa.Table.from_batches(kept).to_pandas() if kept else None
    return {"rows": rows, "ok": ok, "fmt": fmt, "table": table}


@router.post("/predict/batch", summary="Прогон множества значений из файла CSV (до 2,5 ГБ) или XLSX (до 50 МБ)")
async def predict_batch(
    request: Request,
    filename: Optional[str] = Query(None, description="Имя файла при отправке сырым телом (определяет CSV/XLSX)"),
    format: Optional[Literal["csv", "xlsx", "json"]] = Query(None, description="Формат ответа; по умолчанию как у файла"),
):
    """Тело — сам файл (Content-Type: text/csv или application/octet-stream, имя в ?filename=) или multipart с полем file.
    Колонки route, date и необязательная hour (или «Маршрут», «Дата», «Час»). Ответ — тот же файл с prediction, source, error.
    """
    work = Path(tempfile.mkdtemp(prefix="predict-", dir=TMP_DIR))
    cleanup = BackgroundTask(shutil.rmtree, work, ignore_errors=True)
    try:
        name, size = await _receive(request, work / "input")
        out_csv = work / "result.csv"
        res = await run_in_threadpool(_process, work / "input", name, size, out_csv, format)
        base = Path(name).stem or "keys"
        headers = {"X-Rows": str(res["rows"]), "X-Rows-Ok": str(res["ok"]), "X-Rows-Error": str(res["rows"] - res["ok"]),
                   "Access-Control-Expose-Headers": "X-Rows, X-Rows-Ok, X-Rows-Error, Content-Disposition"}
        if res["fmt"] == "json":
            df = res["table"]
            items = df.astype(object).where(df.notna(), None).to_dict(orient="records")
            shutil.rmtree(work, ignore_errors=True)
            return ORJSONResponse({"rows": res["rows"], "ok": res["ok"], "errors": res["rows"] - res["ok"], "items": items},
                                  headers=headers)
        if res["fmt"] == "xlsx":
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                res["table"].to_excel(writer, index=False, sheet_name="prediction")
            shutil.rmtree(work, ignore_errors=True)
            return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={**headers, "Content-Disposition": f"attachment; filename*=UTF-8''{quote(base + '_prediction.xlsx')}"})
        return FileResponse(out_csv, media_type="text/csv; charset=utf-8", background=cleanup,
                            headers={**headers, "Content-Disposition": f"attachment; filename*=UTF-8''{quote(base + '_prediction.csv')}"})
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
