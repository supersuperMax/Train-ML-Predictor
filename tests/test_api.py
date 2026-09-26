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
