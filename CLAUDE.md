# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

Hackathon web service that forecasts hourly tram boardings (`route × date × hour`) on Moscow tram routes. README, UI text, API error messages and code comments are in Russian; keep new ones in Russian.

**The forecast model comes from another team and its format is not fixed.** Never couple the service to a specific model. It plugs in only through the adapter contract in `worker/model_adapter.py` (documented in `model/README.md`). `model/predictions.csv` is a stand-in: the `submission.csv` of the research CatBoost model in the parent directory (`../main.ipynb`, `../MODEL_REPORT.md`), which is not the model to integrate.

Load testing is deferred. The README "Производительность" section is intentionally a placeholder without numbers.

## Commands

```bash
docker compose up --build                       # frontend :3000 (proxies /api/ to api), postgres :5432; api has no host port
python -m worker run --once                      # full pipeline locally → data/snapshot/ (run from repo root)
python -m worker run --step inference --step snapshot   # individual steps
cd backend && uvicorn app.main:app --reload --port 8000  # API locally (reads ../data/snapshot)
cd frontend && npm run dev                        # :5173, vite proxies /api to :8000
cd frontend && npm run typecheck                  # tsc --noEmit (npm run build also typechecks)
pytest                                            # from repo root; pytest.ini puts . and backend/ on sys.path
pytest tests/test_api.py::test_horizons           # single test
```

Deps: `worker/requirements.txt`, `backend/requirements.txt`, `requirements-dev.txt` (pytest, httpx).

## Architecture

Data flows one way: **worker → snapshot files → api → frontend**. The API never talks to Postgres.

- **worker/** (package, `python -m worker`): the pipeline in `pipeline.py` runs steps in the fixed order `ingest → normalize → geo → inference → snapshot`. Each step reads and writes files under `DATA_DIR` (`data/`), so steps can run on their own:
  - `ingest`: `data/incoming/*.csv` → `data/store/staging/`;
  - `normalize`: staging plus seed `data/history/*.csv` → `data/store/history.parquet`. Seeds are read only when the store file is missing, and new data is **summed** into history, so re-ingesting the same file double-counts;
  - `geo`: `data/reference/*.xlsx` → `route_stops.parquet` with a per-stop `share` of the route's boardings;
  - `inference`: runs the model adapter → `forecast.parquet` with a `source` column (`model` | `baseline`);
  - `snapshot`: writes `data/snapshot/<version>/`, then atomically swaps `data/snapshot/CURRENT` and mirrors the data to Postgres (optional, skipped if `DATABASE_URL` is unset or unreachable).

  A failed step aborts the run and leaves the previous snapshot live. Runs are logged to `data/store/runs.jsonl`, `data/snapshot/LAST_RUN.json` and the `pipeline_runs` table. Without CLI flags, `loop()` reruns on the `PIPELINE_INTERVAL_MIN` interval and whenever the input fingerprint changes (incoming files, `model/`, reference, history seeds).
- **Model adapter** (`MODEL_MODE`):
  - `file`: `model/predictions.{parquet,csv}`; the file defines the date range;
  - `plugin`: `model/predictor.py::predict(keys, features, history)`, with optional `MAX_DATE`;
  - `baseline`: a built-in profile forecast, not ML.

  With `MODEL_FALLBACK=baseline` (the default), dates beyond the model's range up to `FORECAST_END` are filled by the baseline and marked `source=baseline`; the UI greys them out. All model output goes through `validate()`, which requires a complete 24h grid per route. Calendar features (Russian production calendar 2025–2026) live in `worker/features.py`.
- **backend/** (FastAPI):
  - `services/snapshot.py`: `SnapshotStore` re-reads `CURRENT` every `SNAPSHOT_RELOAD_SEC` and loads the forecast into a dense `cube[route, day, hour]` numpy array, plus `share[route, stop]`;
  - `services/forecast_service.py`: every query is a cube slice weighted by a per-route vector (all routes, one route, or a stop's share column), then bucketed by granularity. Horizon resolution: `day`/`month`/`year` from anchor `date`, or explicit `from`/`to`; the default granularity comes from the horizon. Results are `lru_cache`d keyed on snapshot version;
  - `api/params.py`: the shared query dependency for `/forecast`, `/summary` and export;
  - `errors.py`: all errors go out as `{"error": {"code", "message"}}`; raise `bad_request` / `not_found` / `not_ready` from `app.errors`, don't raise `HTTPException`;
  - `main.py`: an ETag/304 middleware keyed on snapshot version + URL.
- **frontend/** (React 19, TS 5.9, Vite 8, Tailwind CSS 4, Recharts 3, MapLibre 6 with OSM raster tiles, all versions pinned):
  - styling is Tailwind v4 via `@tailwindcss/vite` (no `tailwind.config.js`). Theme tokens (`ink`, `muted`, `page`, `line`, `accent`…, breakpoint `wide` = 1080px) and the few component classes (`card`, `btn`, `control`, `field-label`, `alert-*`) live in `src/style.css`; everything else is utilities in JSX. Scanning is limited to `src/` (`source(".")`). Write class names as full literal strings — never build them by concatenation, or Tailwind won't generate them;
  - `src/api.ts`: `useApi` (abortable fetch; surfaces the backend's `error.message`) and `forecastParams`, which maps UI filters to query params;
  - the map (`components/MapPanel.tsx`, `MapView.tsx`) is lazy-loaded as a separate chunk;
  - the API base is `import.meta.env.VITE_API ?? '/api'`.
- **Docker**:
  - build contexts are the repo root, so `COPY` paths are relative to `server/`; `.dockerignore` keeps `node_modules`, `dist` and generated `data/` out of the context;
  - worker bind-mounts `./data:/data` and `./model:/model:ro`, and api mounts `./data/snapshot` read-only. Generated `data/store/` and `data/snapshot/` are gitignored;
  - api is limited to 2 CPU / 2 GB and runs `WEB_CONCURRENCY` uvicorn workers. It scales with `docker compose up --scale api=N`. nginx (`frontend/nginx.conf`) re-resolves `api` via Docker DNS (`resolver 127.0.0.11`, `proxy_pass $api`), so recreated or scaled api containers are picked up without restarting nginx. Do not switch back to a static `upstream` block: it pins the IP at startup and gives 502 after api is recreated. nginx-generated 502/504 are returned as JSON `api_unavailable`.

## Data caveats

- Stop coordinates exist only for routes 1, 5, 7, 11, 12 (reference routes 2/3/4/6/10 have no forecast and are filtered out).
- Raw validations have no stop (`place_id` is a depot), so stop forecasts are route forecasts × a heuristic share. Route 5 has no history, so its forecast is 0.
- Seed history files have partial edge days; `normalize.trim_partial_edges` drops edge days below 20% of the median day, but only for files covering at least 3 days.
