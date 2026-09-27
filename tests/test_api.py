from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.snapshot import store
from worker import pipeline


@pytest.fixture
def client(cfg, monkeypatch):
    cfg = replace(cfg, model_fallback="baseline", forecast_end="2026-10-31")
    assert pipeline.run(cfg)["status"] == "ok"
    monkeypatch.setattr(store, "folder", cfg.snapshot_dir)
    monkeypatch.setattr(store, "reload_sec", 0)
    monkeypatch.setattr(store, "_snap", None)
    from app.services import datasets
    monkeypatch.setattr(datasets, "DATASETS_DIR", cfg.data_dir / "uploads")
    return TestClient(app)


def test_horizons(client):
    day = client.get("/api/forecast", params={"horizon": "day", "route": 1}).json()
    assert day["query"]["granularity"] == "hour" and len(day["points"]) == 24
    assert day["points"][5]["value"] == 15  # route*10 + hour из файла модели

    month = client.get("/api/forecast", params={"horizon": "month", "date": "2025-11-01"}).json()
    assert month["query"]["to"] == "2025-11-30" and len(month["points"]) == 30

    year = client.get("/api/forecast", params={"horizon": "year", "date": "2025-11-01"}).json()
    assert len(year["points"]) == 12
    assert year["points"][0]["source"] == "model" and year["points"][-1]["source"] == "baseline"


def test_aggregation_filters(client):
    full = client.get("/api/forecast", params={"horizon": "day", "route": 1}).json()
    part = client.get("/api/forecast", params={"horizon": "day", "route": 1, "hour_from": 7, "hour_to": 9}).json()
    assert [p["hour"] for p in part["points"]] == [7, 8, 9]
    assert part["total"] == sum(p["value"] for p in full["points"][7:10])

    week = client.get("/api/forecast", params={"from": "2025-11-03", "to": "2025-11-16", "granularity": "week"}).json()
    assert [p["days"] for p in week["points"]] == [7, 7]


def test_stop_forecast_is_share_of_route(client):
    stops = client.get("/api/stops", params={"route": 1}).json()["stops"]
    route_total = client.get("/api/forecast", params={"horizon": "month", "route": 1}).json()["total"]
    stop_totals = [client.get("/api/forecast", params={"horizon": "month", "route": 1, "stop_id": s["stop_id"]}).json()["total"]
                   for s in stops]
    assert abs(sum(stop_totals) - route_total) / route_total < 0.01


def test_summary_and_map(client):
    s = client.get("/api/summary", params={"horizon": "month", "route": 17}).json()
    assert set(s["by_daytype"]) >= {"weekday", "sat", "sun"}
    assert s["peak"]["hour"] == 23
    m = client.get("/api/map", params={"date": "2025-11-05", "hour": 8}).json()
    assert m["stops"] and m["max"] > 0


@pytest.mark.parametrize("params,status,code", [
    ({"date": "2025-13-01"}, 400, "invalid_date"),
    ({"from": "2025-11-10", "to": "2025-11-01"}, 400, "invalid_period"),
    ({"route": 99}, 404, "unknown_route"),
    ({"stop_id": 1}, 404, "unknown_stop"),
    ({"from": "2030-01-01", "to": "2030-01-02"}, 404, "out_of_range"),
    ({"horizon": "year", "granularity": "hour"}, 400, "period_too_long"),
    ({"hour_from": 10, "hour_to": 5}, 400, "invalid_hours"),
    ({"hour_from": "x"}, 422, "validation_error"),
])
def test_errors_are_readable(client, params, status, code):
    r = client.get("/api/forecast", params=params)
    assert r.status_code == status
    assert r.json()["error"]["code"] == code
    assert r.json()["error"]["message"]


def test_export(client):
    csv = client.get("/api/export/csv", params={"horizon": "day", "route": 1})
    assert csv.status_code == 200
    lines = csv.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Период;Маршрут") and len(lines) == 25
    xlsx = client.get("/api/export/xlsx", params={"horizon": "month"})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "folder", tmp_path)
    monkeypatch.setattr(store, "reload_sec", 0)
    monkeypatch.setattr(store, "_snap", None)
    c = TestClient(app)
    assert c.get("/health").status_code == 200
    r = c.get("/api/forecast")
    assert r.status_code == 503 and r.json()["error"]["code"] == "snapshot_not_ready"


def test_etag(client):
    r = client.get("/api/routes")
    assert client.get("/api/routes", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_predict_one(client):
    r = client.get("/api/predict", params={"route": 1, "date": "2025-11-03", "hour": 5})
    assert r.status_code == 200 and r.json()["prediction"] == 15 and r.json()["source"] == "model"
    day = client.get("/api/predict", params={"route": 1, "date": "2025-11-03"}).json()
    assert day["prediction"] == sum(10 + h for h in range(24))
    assert client.get("/api/predict", params={"route": 99, "date": "2025-11-03"}).status_code == 404
    assert client.get("/api/predict", params={"route": 1, "date": "2025-13-01"}).status_code == 400


def test_predict_batch_csv_with_errors(client):
    body = "Маршрут;Дата;Час\n1;2025-11-03;5\n17;2025-11-04;\n99;2025-11-03;1\n1;2030-01-01;1\n1;2025-11-03;30\n".encode("utf-8-sig")
    r = client.post("/api/predict/batch", files={"file": ("keys.csv", body, "text/csv")})
    assert r.status_code == 200
    assert r.headers["x-rows-ok"] == "2" and r.headers["x-rows-error"] == "3"
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0] == "Маршрут;Дата;Час;prediction;source;error"
    assert lines[1] == "1;2025-11-03;5;15;model;"
    assert "отсутствует" in lines[3] and "вне прогноза" in lines[4] and "0–23" in lines[5]


def test_predict_batch_xlsx_and_json(client):
    import io
    import pandas as pd
    buf = io.BytesIO()
    pd.DataFrame({"route": [1, 17], "date": ["2025-11-03", "2025-11-03"], "hour": [5, 8]}).to_excel(buf, index=False)
    r = client.post("/api/predict/batch", files={"file": ("keys.xlsx", buf.getvalue())})
    assert r.status_code == 200 and r.content[:2] == b"PK"
    out = pd.read_excel(io.BytesIO(r.content))
    assert out["prediction"].tolist() == [15, 178]
    j = client.post("/api/predict/batch", params={"format": "json"}, files={"file": ("k.csv", b"route,date\n1,2025-11-03\n")}).json()
    assert j["ok"] == 1 and j["items"][0]["prediction"] == sum(10 + h for h in range(24))


def test_predict_batch_bad_files(client):
    r = client.post("/api/predict/batch", files={"file": ("k.csv", b"a;b\n1;2\n")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "missing_columns"
    assert client.post("/api/predict/batch", files={"file": ("k.csv", b"")}).status_code == 400


def test_predict_batch_raw_body_large(client):
    import io
    import pandas as pd
    n = 300_000  # больше прежнего лимита в 200 000 строк
    keys = pd.DataFrame({"route": [1, 17] * (n // 2), "date": ["2025-11-10", "2025-11-20"] * (n // 2), "hour": [5, ""] * (n // 2)})
    body = keys.to_csv(index=False, sep=",").encode()
    r = client.post("/api/predict/batch", params={"filename": "big.csv"}, content=body, headers={"Content-Type": "text/csv"})
    assert r.status_code == 200 and r.headers["x-rows"] == str(n) and r.headers["x-rows-error"] == "0"
    out = pd.read_csv(io.BytesIO(r.content), sep=";", encoding="utf-8-sig")
    assert list(out.columns) == ["route", "date", "hour", "prediction", "source", "error"]
    one = client.get("/api/predict", params={"route": 1, "date": "2025-11-10", "hour": 5}).json()["prediction"]
    day = client.get("/api/predict", params={"route": 17, "date": "2025-11-20"}).json()["prediction"]
    assert out["prediction"].iloc[0] == one and out["prediction"].iloc[1] == day


def test_predict_batch_output_limits(client, monkeypatch):
    from app.api import predict
    monkeypatch.setattr(predict, "MAX_JSON_ROWS", 2)
    body = b"route;date\n1;2025-11-03\n1;2025-11-04\n1;2025-11-05\n"
    r = client.post("/api/predict/batch", params={"filename": "k.csv", "format": "json"}, content=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_many_rows"
    monkeypatch.setattr(predict, "MAX_BYTES", 10)
    r = client.post("/api/predict/batch", params={"filename": "k.csv"}, content=body)
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"


def test_source_baseline(client):
    model = client.get("/api/forecast", params={"horizon": "day", "route": 1, "date": "2025-11-03"}).json()
    base = client.get("/api/forecast", params={"horizon": "day", "route": 1, "date": "2025-11-03", "source": "baseline"}).json()
    assert model["points"][5]["value"] == 15 and model["points"][5]["source"] == "model"
    assert base["points"][5]["source"] == "baseline" and base["total"] != model["total"]
    assert client.get("/api/map", params={"date": "2025-11-03", "hour": 8, "source": "baseline"}).json()["source"] == "baseline"
    assert client.get("/api/forecast", params={"source": "xxx"}).json()["error"]["code"] == "unknown_source"


def test_dataset_from_file(client):
    body = b"route;date;hour\n1;2025-11-03;5\n1;2025-11-03;6\n17;2025-11-04;\n99;2025-11-03;1\n"
    r = client.post("/api/datasets", params={"filename": "keys.csv"}, content=body)
    assert r.status_code == 200, r.text
    ds = r.json()
    assert ds["rows"] == 4 and ds["errors"] == 1 and ds["range"] == ["2025-11-03", "2025-11-04"] and ds["routes"] == [1, 17]
    src = ds["source"]
    day = client.get("/api/forecast", params={"horizon": "day", "route": 1, "date": "2025-11-03", "source": src}).json()
    assert day["total"] == 15 + 16                       # только часы 5 и 6 из файла
    assert day["points"][0]["value"] is None             # часа нет в файле — пусто, а не 0
    whole = client.get("/api/forecast", params={"horizon": "day", "route": 17, "date": "2025-11-04", "source": src}).json()
    assert whole["total"] == sum(170 + h for h in range(24))  # строка без часа — весь день
    res = client.get(ds["result_url"])
    assert res.status_code == 200 and res.content.decode("utf-8-sig").splitlines()[1] == "1;2025-11-03;5;15;model;"
    assert client.get("/api/datasets/" + ds["id"]).json()["name"] == "keys.csv"
    assert client.get("/api/forecast", params={"source": "file:000000000000"}).status_code == 404


RAW_HEADER = ("tran_no;device_no;tran_date_time;begin_date_time;input_date_time;crd_hashcode;validation_result;tran_type_id;"
              "place_id;good_type;pass_route;ngpt_route;bus_exit_no;garage_number")


def raw_row(n, ts, result, route):
    return f"{n};100{n};{ts};{ts};{ts};h{n};{result};52;10501;СКМ МГТ;;{route};5;31018"


def test_dataset_from_raw_validations(client):
    rows = [raw_row(1, "2025-11-03 05:10:00", 1, "1 трамвай"), raw_row(2, "2025-11-03 05:40:00", 1, "1 трамвай"),
            raw_row(3, "2025-11-03 06:59:59", 1, "1 трамвай"), raw_row(4, "2025-11-03 06:10:00", 0, "1 трамвай"),
            raw_row(5, "2025-11-03 06:20:00", 1, "мусор"), raw_row(6, "2025-11-04 08:00:00", 1, "17 трамвай")]
    body = ("\n".join([RAW_HEADER, *rows]) + "\n").encode()
    r = client.post("/api/datasets", params={"filename": "validations.csv"}, content=body)
    assert r.status_code == 200, r.text
    ds = r.json()
    assert ds["kind"] == "validations" and ds["rows"] == 6 and ds["skipped"] == 2 and ds["boardings"] == 4
    assert ds["keys"] == 3 and ds["ok"] == 3 and "warning" not in ds and "note" not in ds
    assert ds["range"] == ["2025-11-03", "2025-11-04"] and ds["overlap"] == ds["range"] and ds["routes"] == [1, 17]

    day = client.get("/api/forecast", params={"horizon": "day", "route": 1, "date": "2025-11-03", "source": ds["source"]}).json()
    assert day["total"] == sum(10 + h for h in range(24))            # прогноз модели полный, файлом не обрезается
    assert day["fact_total"] == 3
    assert {p["hour"]: p["fact"] for p in day["points"] if p["fact"] is not None} == {5: 2, 6: 1}
    assert day["compare"] == {"from": "2025-11-03", "to": "2025-11-03", "forecast": 31, "fact": 3,
                              "error_pct": round((31 - 3) / 3 * 100, 1)}   # сравнение только в часах с фактом
    month = client.get("/api/forecast", params={"horizon": "month", "date": "2025-11-01", "source": ds["source"]}).json()
    assert month["fact_total"] == 4
    assert "fact" not in client.get("/api/forecast", params={"horizon": "day", "date": "2025-11-03"}).json()["points"][0]

    lines = client.get(ds["result_url"]).content.decode("utf-8-sig").splitlines()
    assert lines[0] == "route;date;hour;fact;prediction;source;error"
    assert lines[1].split(";")[:4] == ["1", "2025-11-03", "5", "2"] and float(lines[1].split(";")[4]) == 15
    export = client.get("/api/export/csv", params={"horizon": "day", "route": 1, "date": "2025-11-03", "source": ds["source"]})
    assert "Факт посадок" in export.content.decode("utf-8-sig").splitlines()[0]


def test_raw_validations_before_forecast(client):
    # октябрь (история, до прогноза) + ночные поездки после полуночи 1 ноября — неполный крайний день
    rows = [raw_row(n, f"2025-10-{day} {7 + n % 10:02d}:15:00", 1, "1 трамвай") for day in range(27, 32) for n in range(10)]
    rows.append(raw_row(999, "2025-11-01 00:30:00", 1, "1 трамвай"))
    body = ("\n".join([RAW_HEADER, *rows]) + "\n").encode()
    ds = client.post("/api/datasets", params={"filename": "test.csv"}, content=body).json()
    assert ds["range"] == ["2025-10-27", "2025-10-31"] and ds["trimmed_days"] == ["2025-11-01"]
    assert ds["overlap"] is None and "не пересекаются" in ds["note"]

    src = ds["source"]
    month = client.get("/api/forecast", params={"horizon": "month", "route": 1, "date": "2025-10-27", "source": src}).json()
    pts = {p["t"]: p for p in month["points"]}
    assert pts["2025-10-28"]["fact"] == 10 and pts["2025-10-28"]["value"] is None   # до прогноза — только факт
    assert pts["2025-11-01"]["value"] == sum(10 + h for h in range(24))            # прогноз модели полный
    assert pts["2025-11-01"]["fact"] is None                                        # ночь 1 ноября отброшена
    assert month["fact_total"] == 50 and month["compare"] is None
    m = client.get("/api/map", params={"date": "2025-10-28", "source": src}).json()
    assert m["source"] == "fact" and m["max"] > 0
    summary = client.get("/api/summary", params={"horizon": "month", "route": 1, "date": "2025-10-27", "source": src}).json()
    assert summary["days"] == 26                                                    # 01.11–26.11: только дни с прогнозом

    only_fails = ("\n".join([RAW_HEADER, raw_row(1, "2025-11-03 08:00:00", 0, "1 трамвай")]) + "\n").encode()
    r = client.post("/api/datasets", params={"filename": "fails.csv"}, content=only_fails)
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_boardings"
    r = client.post("/api/datasets", params={"filename": "x.csv"}, content=b"a;b\n1;2\n")
    assert r.status_code == 400 and r.json()["error"]["code"] == "missing_columns"

def test_meta_limits(client):
    m = client.get("/api/meta").json()
    assert m["limits"]["csv_bytes"] == int(2.5 * 1024 ** 3) and m["has_baseline"] is True


def test_map_load_scale_per_route_and_day(client):
    # прогноз = маршрут·10 + час: у маршрута 1 максимум суток в 23:00 (33), в 0:00 — 10
    top = max(client.get("/api/map", params={"date": "2025-11-03", "hour": 23}).json()["stops"], key=lambda x: x["load"])
    assert top["load"] == 1
    night = {x["stop_id"]: x["load"] for x in client.get("/api/map", params={"date": "2025-11-03", "hour": 0}).json()["stops"]}
    assert abs(night[top["stop_id"]] - 10 / 33) < 1e-3
    m = client.get("/api/map", params={"date": "2025-11-03", "hour": 0}).json()
    r1 = next(r for r in m["routes"] if r["route"] == 1)
    assert r1["day_max"] > 0 and all(0 <= x["load"] <= 1 for x in m["stops"])
    whole = client.get("/api/map", params={"date": "2025-11-03"}).json()   # за день: максимум — сумма суток
    assert max(x["load"] for x in whole["stops"]) == 1
    base = client.get("/api/map", params={"date": "2025-11-03", "hour": 23, "source": "baseline"}).json()
    assert max(x["load"] for x in base["stops"]) <= 1
