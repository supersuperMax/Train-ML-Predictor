"""PostgreSQL: хранилище истории, прогноза, справочников и журнала прогонов пайплайна.

API читает только snapshot-файлы (так он остаётся stateless и быстрым), а Postgres — источник для
аналитики и аудита. Если DATABASE_URL не задан или база недоступна, пайплайн работает без неё.
"""
import json
import logging
from io import StringIO

import pandas as pd

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS history_hourly (
    route smallint NOT NULL, date date NOT NULL, hour smallint NOT NULL, boardings bigint NOT NULL,
    PRIMARY KEY (route, date, hour));
CREATE TABLE IF NOT EXISTS forecast_hourly (
    route smallint NOT NULL, date date NOT NULL, hour smallint NOT NULL, prediction real NOT NULL,
    source text NOT NULL, version text NOT NULL, PRIMARY KEY (route, date, hour));
CREATE TABLE IF NOT EXISTS routes (route smallint PRIMARY KEY, name text);
CREATE TABLE IF NOT EXISTS stops (stop_id integer PRIMARY KEY, name text, lat double precision, lon double precision);
CREATE TABLE IF NOT EXISTS route_stops (
    route smallint NOT NULL, direction smallint NOT NULL, seq smallint NOT NULL, stop_id integer NOT NULL,
    share double precision NOT NULL, PRIMARY KEY (route, direction, seq));
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id bigserial PRIMARY KEY, started_at timestamptz NOT NULL, finished_at timestamptz,
    status text NOT NULL, steps text NOT NULL, version text, details jsonb, error text);
"""


def _connect(url: str):
    import psycopg
    return psycopg.connect(url, connect_timeout=5)


def _copy(cur, table: str, df: pd.DataFrame) -> None:
    buf = StringIO()
    df.to_csv(buf, index=False, header=False)
    buf.seek(0)
    with cur.copy(f"COPY {table} ({', '.join(df.columns)}) FROM STDIN WITH (FORMAT csv)") as cp:
        cp.write(buf.read())


def mirror(url: str, version: str, history: pd.DataFrame, forecast: pd.DataFrame,
           route_stops: pd.DataFrame, routes: pd.DataFrame) -> bool:
    if not url:
        return False
    try:
        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(SCHEMA)
            cur.execute("TRUNCATE history_hourly, forecast_hourly, routes, stops, route_stops")
            _copy(cur, "history_hourly", history.assign(date=history["date"].dt.date))
            _copy(cur, "forecast_hourly", forecast.assign(date=forecast["date"].dt.date, version=version)
                  [["route", "date", "hour", "prediction", "source", "version"]])
            _copy(cur, "routes", routes[["route", "name"]])
            _copy(cur, "stops", route_stops.drop_duplicates("stop_id")[["stop_id", "name", "lat", "lon"]])
            _copy(cur, "route_stops", route_stops[["route", "direction", "seq", "stop_id", "share"]])
        return True
    except Exception as e:
        log.warning("PostgreSQL недоступен, зеркалирование пропущено: %s", e)
        return False


def log_run(url: str, run: dict) -> None:
    if not url:
        return
    try:
        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(SCHEMA)
            cur.execute(
                "INSERT INTO pipeline_runs (started_at, finished_at, status, steps, version, details, error) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (run["started_at"], run["finished_at"], run["status"], ",".join(run["steps"]),
                 run.get("version"), json.dumps(run.get("details", {}), ensure_ascii=False, default=str),
                 run.get("error")))
    except Exception as e:
        log.warning("Не удалось записать прогон в pipeline_runs: %s", e)
