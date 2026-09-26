"""Шаг snapshot: публикация прогноза для API.

Файлы пишутся в data/snapshot/<version>/, затем атомарно переключается указатель data/snapshot/CURRENT.
API перечитывает snapshot при смене CURRENT без перезапуска. Хранятся последние KEEP_SNAPSHOTS версий.
"""
import json
import os
import shutil
from datetime import datetime, timezone

import pandas as pd

from worker import db, features
from worker.config import Config
from worker.normalize import load_history


def current_version(cfg: Config) -> str | None:
    p = cfg.snapshot_dir / "CURRENT"
    return p.read_text().strip() if p.exists() else None


def _prune(cfg: Config, keep: str) -> None:
    versions = sorted(p for p in cfg.snapshot_dir.iterdir() if p.is_dir() and p.name.startswith("v"))
    for old in versions[:-cfg.keep_snapshots]:
        if old.name != keep:
            shutil.rmtree(old, ignore_errors=True)


def run(cfg: Config, details: dict | None = None) -> dict:
    forecast_path = cfg.store_dir / "forecast.parquet"
    if not forecast_path.exists():
        raise FileNotFoundError("Нет store/forecast.parquet — сначала выполните шаг inference")
    forecast = pd.read_parquet(forecast_path)
    route_stops = pd.read_parquet(cfg.store_dir / "route_stops.parquet") if (cfg.store_dir / "route_stops.parquet").exists() \
        else pd.DataFrame(columns=["route", "direction", "seq", "stop_id", "name", "lat", "lon", "share"])
    routes = pd.read_parquet(cfg.store_dir / "routes.parquet") if (cfg.store_dir / "routes.parquet").exists() \
        else pd.DataFrame(columns=["route", "name"])
    history = load_history(cfg)

    now = datetime.now(timezone.utc)
    version = "v" + now.strftime("%Y%m%dT%H%M%S%f")
    cfg.snapshot_dir.mkdir(parents=True, exist_ok=True)
    tmp = cfg.snapshot_dir / f".tmp-{version}"
    tmp.mkdir()

    forecast.to_parquet(tmp / "forecast.parquet", index=False)
    features.calendar(forecast["date"]).to_parquet(tmp / "calendar.parquet", index=False)
    route_stops.to_parquet(tmp / "route_stops.parquet", index=False)
    routes.to_parquet(tmp / "routes.parquet", index=False)

    sources = {str(src): [str(g["date"].min().date()), str(g["date"].max().date())]
               for src, g in forecast.groupby("source", observed=True)}
    manifest = {
        "version": version,
        "created_at": now.isoformat(),
        "range": [str(forecast["date"].min().date()), str(forecast["date"].max().date())],
        "sources": sources,
        "routes": sorted(int(r) for r in forecast["route"].unique()),
        "routes_with_stops": sorted(int(r) for r in set(route_stops["route"].unique()) & set(forecast["route"].unique())),
        "history_range": [str(history["date"].min().date()), str(history["date"].max().date())] if len(history) else None,
        "model": (details or {}).get("inference", {}).get("model"),
        "model_mode": cfg.model_mode,
        "model_fallback": cfg.model_fallback,
        "factors": features.FACTORS,
        "weather": "не учитывается — нет данных о погоде",
        "stop_forecast_method": "прогноз маршрута × доля остановки (посадки убывают к конечной, направления поровну)",
        "rows": len(forecast),
        "total": float(forecast["prediction"].sum()),
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    final = cfg.snapshot_dir / version
    tmp.rename(final)
    pointer = cfg.snapshot_dir / "CURRENT.tmp"
    pointer.write_text(version)
    os.replace(pointer, cfg.snapshot_dir / "CURRENT")
    _prune(cfg, version)

    mirrored = db.mirror(cfg.database_url, version, history, forecast, route_stops, routes)
    return {"version": version, "rows": len(forecast), "postgres": mirrored}
