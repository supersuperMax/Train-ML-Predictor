"""Сырые валидации хакатона (tran_no;device_no;tran_date_time;…;ngpt_route;…) → фактические посадки route × date × hour.

Правило то же, что у шага normalize пайплайна: посадка = validation_result == 1, маршрут — число в начале ngpt_route
("25 трамвай" → 25), дата и час — из tran_date_time. CSV (до 2,5 ГБ) читается блоками через pyarrow и сразу
сворачивается до счётчиков, поэтому память ограничена размером блока. Отказы и строки без маршрута или даты
не ломают файл, а считаются пропущенными. Неполные крайние дни (выгрузка обрезана посреди суток, например ночные
поездки после полуночи последнего дня) отбрасываются тем же правилом, что в пайплайне (normalize.trim_partial_edges).
"""
import csv
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pa_csv

from app.errors import bad_request

RAW_COLUMNS = ["tran_date_time", "validation_result", "ngpt_route"]
KEYS = ["route", "date", "hour"]
BLOCK_BYTES = 16 * 1024 ** 2
MIN_DAYS_FOR_TRIM = 3     # как в worker/normalize.py
EDGE_DAY_SHARE = 0.2


def csv_header(path: Path) -> tuple[list[str], str]:
    """Заголовок CSV и разделитель."""
    with open(path, "rb") as f:
        head = f.readline(1024 * 1024)
    try:
        first = head.decode("utf-8-sig").rstrip("\r\n")
    except UnicodeDecodeError:
        raise bad_request("Файл не в кодировке UTF-8. Сохраните CSV в UTF-8 или загрузите XLSX.", code="bad_file")
    if not first.strip():
        raise bad_request("В первой строке файла нет заголовка.", code="bad_file")
    sep = ";" if first.count(";") >= first.count(",") else ","
    return next(csv.reader([first], delimiter=sep)), sep


def is_raw(names: list[str]) -> bool:
    return set(RAW_COLUMNS) <= {str(n).strip().lower() for n in names}


def _names(names: list[str]) -> dict[str, str]:
    return {key: next(n for n in names if str(n).strip().lower() == key) for key in RAW_COLUMNS}


def _boardings(ts: pa.Array, result: pa.Array, route: pa.Array) -> tuple[pa.Table, int]:
    """Блок валидаций → посадки (route, date, hour, fact) и число пропущенных строк."""
    ts, result, route = (pc.fill_null(pc.utf8_trim_whitespace(a), "") for a in (ts, result, route))
    num = pc.struct_field(pc.extract_regex(route, r"^(?P<r>\d{1,6})"), [0])
    day = pc.utf8_slice_codeunits(ts, 0, 10)
    hour = pc.utf8_slice_codeunits(ts, 11, 13)
    valid_day = pc.is_valid(pc.strptime(day, format="%Y-%m-%d", unit="s", error_is_null=True))
    valid_hour = pc.match_substring_regex(hour, r"^([01]\d|2[0-3])$")
    keep = pc.and_(pc.and_(pc.equal(result, "1"), pc.is_valid(num)), pc.and_(valid_day, valid_hour))
    keep = pc.fill_null(keep, False)
    t = pa.table({"route": pc.cast(pc.filter(num, keep), pa.int32()), "date": pc.filter(day, keep),
                  "hour": pc.cast(pc.filter(hour, keep), pa.int32())})
    agg = t.group_by(KEYS).aggregate([([], "count_all")]).rename_columns(KEYS + ["fact"])
    return agg, len(ts) - t.num_rows


def trim_partial_edges(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Отбрасывает крайние дни с посадками меньше EDGE_DAY_SHARE медианы дня. → (данные, отброшенные даты)."""
    daily = df.groupby("date")["fact"].sum().sort_index()
    if len(daily) < MIN_DAYS_FOR_TRIM:
        return df, []
    full = daily[daily >= daily.median() * EDGE_DAY_SHARE].index
    if full.empty:
        return df, []
    dropped = [d for d in daily.index if d < full.min() or d > full.max()]
    return df[df["date"].between(full.min(), full.max())].reset_index(drop=True), dropped


def aggregate(path: Path, name: str) -> tuple[pd.DataFrame, int, int, list[str]]:
    """Файл сырых валидаций → (посадки route, date, hour, fact; всего строк; пропущено строк; отброшенные неполные дни)."""
    parts, rows, skipped = [], 0, 0
    if name.lower().endswith((".xlsx", ".xls")):
        try:
            df = pd.read_excel(path, dtype=str)
        except Exception as e:
            raise bad_request(f"Не удалось прочитать XLSX: {e}", code="bad_file")
        cols = _names([str(c) for c in df.columns])
        agg, n_skip = _boardings(*(pa.array(df[cols[c]].astype(object).where(df[cols[c]].notna(), None), pa.string())
                                   for c in RAW_COLUMNS))
        parts, rows, skipped = [agg], len(df), n_skip
    else:
        names, sep = csv_header(path)
        cols = _names(names)
        broken = [0]

        def skip_row(_row) -> str:  # строка с лишними/недостающими полями — пропустить, а не ронять весь файл
            broken[0] += 1
            return "skip"

        try:
            reader = pa_csv.open_csv(
                path,
                read_options=pa_csv.ReadOptions(column_names=names, skip_rows=1, block_size=BLOCK_BYTES),
                parse_options=pa_csv.ParseOptions(delimiter=sep, invalid_row_handler=skip_row),
                convert_options=pa_csv.ConvertOptions(include_columns=[cols[c] for c in RAW_COLUMNS],
                                                      column_types={cols[c]: pa.string() for c in RAW_COLUMNS}),
            )
            for batch in reader:
                if batch.num_rows == 0:
                    continue
                agg, n_skip = _boardings(*(batch.column(batch.schema.get_field_index(cols[c])) for c in RAW_COLUMNS))
                parts.append(agg)
                rows += batch.num_rows
                skipped += n_skip
        except pa.ArrowInvalid as e:
            raise bad_request(f"Не удалось разобрать CSV: {e}", code="bad_file")
        rows += broken[0]
        skipped += broken[0]
    if rows == 0:
        raise bad_request("В файле нет строк с данными.", code="bad_file")
    table = pa.concat_tables(parts).group_by(KEYS).aggregate([("fact", "sum")]).rename_columns(KEYS + ["fact"])
    df = table.to_pandas().sort_values(KEYS).reset_index(drop=True)
    if df.empty:
        raise bad_request(f"В файле нет успешных валидаций с маршрутом и датой: из {rows} строк все пропущены "
                          "(validation_result ≠ 1, пустой ngpt_route или неверная tran_date_time).", code="no_boardings")
    df, trimmed = trim_partial_edges(df)
    return df, rows, skipped, trimmed
