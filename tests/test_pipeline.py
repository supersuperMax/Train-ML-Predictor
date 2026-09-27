import json
import shutil
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from worker import pipeline, snapshot
from tests.conftest import ROOT, write_model_file


def test_full_run_file_mode(cfg):
    run = pipeline.run(cfg)
    assert run["status"] == "ok", run.get("error")
    version = snapshot.current_version(cfg)
    manifest = json.loads((cfg.snapshot_dir / version / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["range"] == ["2025-11-01", "2025-11-30"]
    assert manifest["routes_with_stops"] == [1]
    fc = pd.read_parquet(cfg.snapshot_dir / version / "forecast.parquet")
    assert len(fc) == 2 * 30 * 24
    assert (fc["source"] == "model").all()


def test_baseline_fallback_extends_horizon(cfg):
    cfg = replace(cfg, model_fallback="baseline", forecast_end="2026-02-28")
    assert pipeline.run(cfg)["status"] == "ok"
    fc = pd.read_parquet(cfg.snapshot_dir / snapshot.current_version(cfg) / "forecast.parquet")
    assert fc["date"].max() == pd.Timestamp("2026-02-28")
    assert set(fc["source"].astype(str)) == {"model", "baseline"}
    assert fc.loc[fc["date"] > "2025-11-30", "source"].eq("baseline").all()


def test_broken_model_keeps_previous_snapshot(cfg):
    assert pipeline.run(cfg)["status"] == "ok"
    good = snapshot.current_version(cfg)
    df = pd.read_csv(cfg.model_dir / "predictions.csv", sep=";")
    df.drop(index=range(5)).to_csv(cfg.model_dir / "predictions.csv", sep=";", index=False)  # дыра в сетке

    run = pipeline.run(cfg)
    assert run["status"] == "error"
    assert "неполная сетка" in run["error"]
    assert snapshot.current_version(cfg) == good
    last = json.loads((cfg.snapshot_dir / "LAST_RUN.json").read_text(encoding="utf-8"))
    assert last["status"] == "error"


def test_ingest_raw_validations(cfg):
    assert pipeline.run(cfg, ["normalize"])["status"] == "ok"
    before = pd.read_parquet(cfg.store_dir / "history.parquet")["boardings"].sum()
    cfg.incoming_dir.mkdir(parents=True, exist_ok=True)
    raw = pd.DataFrame({
        "tran_no": range(6),
        "tran_date_time": ["2025-10-31 08:01:00", "2025-10-31 08:30:00", "2025-10-31 09:00:00",
                           "2025-10-31 09:10:00", "2025-10-31 09:20:00", "2025-10-31 09:30:00"],
        "validation_result": [1, 1, 1, 0, 1, 1],
        "ngpt_route": ["17 трамвай", "17 трамвай", "1 трамвай", "1 трамвай", "мусор", "1 трамвай"],
    })
    raw.to_csv(cfg.incoming_dir / "validations.csv", sep=";", index=False)

    run = pipeline.run(cfg, ["ingest", "normalize"])
    assert run["status"] == "ok", run.get("error")
    after = pd.read_parquet(cfg.store_dir / "history.parquet")["boardings"].sum()
    assert after - before == 4  # отказ и нераспознанный маршрут не считаются
    assert (cfg.incoming_dir / "processed" / "validations.csv").exists()


def test_plugin_mode(cfg):
    shutil.copy(ROOT / "model" / "predictor_example.py", cfg.model_dir / "predictor.py")
    (cfg.model_dir / "predictions.csv").unlink()
    cfg = replace(cfg, model_mode="plugin", forecast_end="2026-01-31")
    run = pipeline.run(cfg)
    assert run["status"] == "ok", run.get("error")
    assert run["details"]["inference"]["range"] == ["2025-11-01", "2026-01-31"]


def test_file_mode_uses_file_range(cfg):
    write_model_file(cfg.model_dir, "2025-12-01", "2025-12-10")
    assert pipeline.run(cfg)["status"] == "ok"
    manifest = json.loads((cfg.snapshot_dir / snapshot.current_version(cfg) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["range"] == ["2025-12-01", "2025-12-10"]


def test_file_mode_finds_tram_model_forecast(cfg):
    target = cfg.model_dir / "tram_model" / "artifacts"
    target.mkdir(parents=True)
    (cfg.model_dir / "predictions.csv").rename(target / "forecast.csv")
    run = pipeline.run(cfg)
    assert run["status"] == "ok", run.get("error")
    assert run["details"]["inference"]["model"] == "файл forecast.csv"


def test_shift_years_keeps_calendar():
    from worker.model_adapter import shift_years
    idx = pd.MultiIndex.from_product([[17], pd.date_range("2025-11-01", "2025-12-31"), range(24)], names=["route", "date", "hour"])
    pred = idx.to_frame(index=False)
    pred["prediction"] = pred["date"].dt.strftime("%m%d").astype(int).astype("float32")  # значение = исходная дата MMDD
    out = shift_years(pred, 1)
    assert out["date"].min() == pd.Timestamp("2026-11-01") and out["date"].max() == pd.Timestamp("2026-12-31")
    assert len(out) == 61 * 24
    day = out.groupby("date")["prediction"].first()
    assert day[pd.Timestamp("2026-11-04")] == 1104      # праздник → праздник
    assert day[pd.Timestamp("2026-12-31")] == 1231      # 31 декабря → 31 декабря
    assert day[pd.Timestamp("2026-11-02")] == 1110      # обычный понедельник → обычный понедельник 10.11.2025, не праздник 03.11


def test_baseline_saved_for_display(cfg):
    cfg = replace(cfg, model_fallback="baseline", forecast_end="2025-12-31")
    assert pipeline.run(cfg)["status"] == "ok"
    v = snapshot.current_version(cfg)
    manifest = json.loads((cfg.snapshot_dir / v / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["has_baseline"] is True
    base = pd.read_parquet(cfg.snapshot_dir / v / "baseline.parquet")
    assert base["date"].min() == pd.Timestamp("2025-11-01") and len(base) == 2 * 61 * 24


def test_file_mode_baseline_fills_only_gap(cfg):
    # без FORECAST_END baseline не дописывает хвост после файла модели — только промежуток между историей и файлом
    write_model_file(cfg.model_dir, "2025-11-05", "2025-11-30")
    cfg = replace(cfg, model_fallback="baseline")
    assert pipeline.run(cfg)["status"] == "ok"
    fc = pd.read_parquet(cfg.snapshot_dir / snapshot.current_version(cfg) / "forecast.parquet")
    assert fc["date"].min() == pd.Timestamp("2025-11-01") and fc["date"].max() == pd.Timestamp("2025-11-30")
    assert fc.loc[fc["date"] < "2025-11-05", "source"].eq("baseline").all()
    assert fc.loc[fc["date"] >= "2025-11-05", "source"].eq("model").all()


def test_geo_osm_stops_and_lines_on_track(cfg):
    from worker import geo
    ref = geo.load_reference(cfg)[0]
    shared = ref[ref["route"] == 1].iloc[0]  # остановка справочника, которую OSM-маршрут 17 тоже проходит
    dlon, dlat = 1000 / (111_320 * np.cos(np.radians(geo.LAT0))), 1000 / 110_574  # 1 км по долготе и широте
    a = [shared["lon"] + 0.0002, shared["lat"]]                                  # ~12 м от остановки справочника
    corner = [a[0] + dlon, a[1]]
    s2 = [corner[0], corner[1] + dlat / 2]                                        # за поворотом, на рельсах
    s3 = [corner[0] + 3 * dlon, corner[1] + 3 * dlat]                             # далеко от рельсов
    point = lambda seq, xy, name, osm_id: {  # noqa: E731
        "type": "Feature", "geometry": {"type": "Point", "coordinates": xy},
        "properties": {"kind": "stop", "route": 17, "direction": 0, "seq": seq, "osm_id": osm_id, "name": name}}
    features = [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [a, corner, [corner[0], corner[1] + dlat]]},
         "properties": {"kind": "track", "route": 17, "direction": 0, "from": "Старт", "to": "Финиш"}},
        point(1, a, shared["name"], 10_000_000_001), point(2, s2, "Поворот", 10_000_000_002), point(3, s3, "Далеко", 10_000_000_003),
    ]
    (cfg.reference_dir / "osm_tram.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")

    details = geo.run(cfg)
    assert details["routes_from_osm"] == [17]
    rs = pd.read_parquet(cfg.store_dir / "route_stops.parquet")
    r17 = rs[rs["route"] == 17].sort_values("seq")
    assert r17["stop_id"].tolist()[0] == shared["stop_id"]                       # та же остановка, что в справочнике
    assert (r17["stop_id"].iloc[1:] >= geo.OSM_ID_BASE).all()
    assert r17["share"].sum() == pytest.approx(1)
    line = pd.read_parquet(cfg.store_dir / "route_lines.parquet").query("route == 17").sort_values("i")[["lon", "lat"]].to_numpy()
    assert len(line) == 5                                   # остановка 1, начало трассы, вершина поворота, остановки 2 и 3
    assert np.allclose(line[0], [shared["lon"], shared["lat"]], atol=1e-6)
    assert np.allclose(line[2], corner, atol=1e-6)          # линия идёт через поворот, а не по диагонали
    assert np.allclose(line[-1], s3, atol=1e-6)             # далёкая остановка — прямым отрезком
    routes = pd.read_parquet(cfg.store_dir / "routes.parquet")
    assert routes.loc[routes["route"] == 17, "name"].tolist() == ["Старт - Финиш"]
