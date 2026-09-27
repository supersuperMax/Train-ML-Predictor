# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

Hackathon web service that forecasts hourly tram boardings (`route × date × hour`) on Moscow tram routes. README, UI text, API error messages and code comments are in Russian; keep new ones in Russian.

**The forecast model comes from another team and its format is not fixed.** Never couple the service to a specific model. It plugs in only through the adapter contract in `worker/model_adapter.py` (documented in `model/README.md`). The current model is the team's `model/tram_model/` (profile + LightGBM + CatBoost, Nov–Dec 2025). The service only reads its ready `tram_model/artifacts/forecast.csv` in `file` mode (auto-discovered via `FILE_CANDIDATES`, or `MODEL_FILE`) and never retrains it; retraining is the team's `python -m tram.forecast`, outside the service. The research CatBoost in the parent directory (`../main.ipynb`) is not the model to integrate.

Load testing is deferred. The README "Производительность" section is intentionally a placeholder without numbers.

## Commands

```bash
docker compose up --build                       # frontend :3000 (proxies /api/ to api), postgres :5432; api has no host port
python -m worker run --once                      # full pipeline locally → data/snapshot/ (run from repo root)
python -m worker run --step inference --step snapshot   # individual steps
python -m worker osm                             # one-off: OSM tram stops/tracks/rails → data/reference/osm_tram.geojson (network)
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
  - `geo`: `data/reference/*.xlsx` + `osm_tram.geojson` → `route_stops.parquet` with a per-stop `share` of the route's boardings, and `route_lines.parquet` (map polylines). OSM stops are added only for routes absent from the xlsx; an OSM stop with the same normalized name within 80 m of an xlsx stop reuses its `stop_id`, others get `90_000_000 + rank` (Postgres `stop_id` is int4). Lines: each stop pair follows the OSM relation track (monotone projection), else the shortest path over the whole OSM rail network (`Rails`, for terminal loops missing from relations), else a straight segment. The worker never hits the network; `python -m worker osm` (`worker/osm.py`, Overpass with a mirror fallback — the main endpoint often 504s) regenerates the file;
  - `inference`: runs the model adapter → `forecast.parquet` with a `source` column (`model` | `baseline`);
  - `snapshot`: writes `data/snapshot/<version>/`, then atomically swaps `data/snapshot/CURRENT` and mirrors the data to Postgres (optional, skipped if `DATABASE_URL` is unset or unreachable).

  A failed step aborts the run and leaves the previous snapshot live. Runs are logged to `data/store/runs.jsonl`, `data/snapshot/LAST_RUN.json` and the `pipeline_runs` table. Without CLI flags, `loop()` reruns on the `PIPELINE_INTERVAL_MIN` interval and whenever the input fingerprint changes (incoming files, `model/`, reference, history seeds).
- **Model date shift**: `MODEL_SHIFT_YEARS` (default 0) can move the file model's dates forward calendar-aware (`model_adapter.shift_years`: same daytype + weekday, nearest to t−N years). By default the site shows tram_model's own dates, Nov–Dec 2025 (the user wants 2025 data, not a 2026 projection). The site opens on the first model date (`meta.sources.model[0]`) with the **baseline** source selected (`App.tsx`, if `meta.has_baseline`); the Модель/Baseline/Файл toggle switches every block.
- **Model adapter** (`MODEL_MODE`):
  - `file`: `model/predictions.{parquet,csv}`; the file defines the date range;
  - `plugin`: `model/predictor.py::predict(keys, features, history)`, with optional `MAX_DATE`;
  - `baseline`: a built-in profile forecast, not ML.

  With `MODEL_FALLBACK=baseline` (the default), gaps are filled by the baseline and marked `source=baseline`; the UI greys them out (except in baseline view, `ForecastChart solid`). In `file` mode the forecast period is the file's range: baseline fills only the gap between history end and the file start, and a tail after the file only when `FORECAST_END` is set explicitly; in `plugin`/`baseline` modes the period runs to `FORECAST_END` (default Dec 31 of next year). All model output goes through `validate()`, which requires a complete 24h grid per route. Calendar features (Russian production calendar 2025–2026) live in `worker/features.py`.
- **backend/** (FastAPI):
  - `services/snapshot.py`: `SnapshotStore` re-reads `CURRENT` every `SNAPSHOT_RELOAD_SEC` and loads the forecast into a dense `cube[route, day, hour]` numpy array, plus `share[route, stop]`;
  - `services/forecast_service.py`: every query is a cube slice weighted by a per-route vector (all routes, one route, or a stop's share column), then bucketed by granularity. Horizon resolution: `day`/`month`/`year` from anchor `date`, or explicit `from`/`to`; the default granularity comes from the horizon. Results are `lru_cache`d keyed on snapshot version;
  - `api/params.py`: the shared query dependency for `/forecast`, `/summary` and export;
  - `errors.py`: all errors go out as `{"error": {"code", "message"}}`; raise `bad_request` / `not_found` / `not_ready` from `app.errors`, don't raise `HTTPException`;
  - `main.py`: an ETag/304 middleware keyed on snapshot version + URL.
  - data source for display: `forecast_service.view(source)`. `model` = the snapshot; `baseline` = the full baseline cube (`baseline.parquet`, written by inference for the whole range); `file:<id>` = model cube × key mask of an uploaded dataset. All return the same `Snapshot` with a swapped cube. Every query (`Query.source`, `/map?source=`, export) goes through it, and LRU keys include the source.
  - `api/datasets.py` + `services/datasets.py` + `services/validations.py`: `POST /api/datasets` sniffs the header. Raw hackathon validations (`tran_date_time`, `validation_result`, `ngpt_route`, …; this is what the site's upload and «Шаблон» use) are aggregated block-wise in pyarrow to boardings `route × date × hour` (same rules as worker `normalize` incl. `trim_partial_edges`, duplicated because the api image has no `worker/`) and stored as a `fact` cube **on the file's own date axis** (no mask: the model forecast is never cut down to file keys). `view("file:<id>")` extends the snapshot's date axis to the union with the fact period (`_extend`: NaN cube, source −1, weekday-based daytype) and sets `Snapshot.fact_cube`, so the hackathon `test.csv` (Sep–Oct validations) shows fact Sep–Oct then forecast Nov–Dec on one chart. Missing data is `null`, not 0 (`Grid.has_value/has_fact`); `/forecast` adds `fact`, `fact_total` and `compare` (overlap only); `/summary` counts only days with forecast; `/map` shows fact × share on days without forecast (`source: "fact"`); export gets «Факт посадок». Otherwise (keys `route;date;hour`) it streams the file through the same `_process` as batch, builds a bool mask `[route, day, hour]` and stores `mask.npz`, `result.csv` and `meta.json` in `DATASETS_DIR` (a shared volume, so every uvicorn process and replica sees it; the last 10 are kept). The mask is realigned to the current snapshot by dates and routes.
  - `api/predict.py`: `GET /api/predict` (one key) and `POST /api/predict/batch` (file). Batch accepts a raw body (what the site sends, with `?filename=`) or multipart. CSV up to 1 GB is streamed: temp file → `pyarrow.csv.open_csv` blocks → `forecast_service.predict_arrays` (vectorized in `pyarrow.compute`, never Python objects per row) → `CSVWriter` → `FileResponse`. XLSX input is limited to 50 MB (read whole), XLSX/JSON output to 1,048,575 / 100k rows. nginx streams this location (`proxy_request_buffering off`, 1100m body). `SelectiveGZip` skips `/api/predict/batch` and `/api/export/`.
- **frontend/** (React 19, TS 5.9, Vite 8, Tailwind CSS 4, Recharts 3, MapLibre 6 with OSM raster tiles, all versions pinned):
  - styling is classic Tailwind v4 via `@tailwindcss/vite`: default palette (slate/blue), no custom theme or `@apply`. Repeated class sets are string constants in `src/ui.ts` (`card`, `btn`, `control`, `alert*`…). Dark mode is class-based (`@custom-variant dark` in `src/style.css`): an inline script in `index.html` sets `dark` on `<html>` before the bundle loads (saved choice in `localStorage.theme`, else system preference), and `src/theme.ts` `useTheme()` toggles it. Every colored class needs a `dark:` pair; the chart and map take a `dark` prop (the map darkens the OSM raster via raster-brightness inversion + hue-rotate; CARTO basemaps need an API key, do not use them). Scanning covers `src/` and `index.html`. Write class names as full literal strings — never build them by concatenation, or Tailwind won't generate them;
  - `src/api.ts`: `useApi` (abortable fetch; surfaces the backend's `error.message`) and `forecastParams`, which maps UI filters to query params;
  - the map (`components/MapPanel.tsx`, `MapView.tsx`) is lazy-loaded as a separate chunk; MapLibre's worker is bundled via `import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'` + `setWorkerUrl` (without it GeoJSON layers — routes and stops — silently don't render). The map has `maxBounds` = all of Moscow incl. New Moscow, rotation/pitch disabled (no right-drag rotate), and a custom React zoom control (+ / vertical range / −, themed) instead of `NavigationControl`. The stop popup is re-rendered from the `setData` effect for the hovered stop (`hoverRef`), so it follows hour changes during playback. Popup colors for both themes are in `src/style.css` (MapLibre's popup is always white otherwise);
  - the API base is `import.meta.env.VITE_API ?? '/api'`.
- **Docker**:
  - build contexts are the repo root, so `COPY` paths are relative to `server/`; `.dockerignore` keeps `node_modules`, `dist` and generated `data/` out of the context;
  - worker bind-mounts `./data:/data` and `./model:/model:ro`, and api mounts `./data/snapshot` read-only. Generated `data/store/` and `data/snapshot/` are gitignored;
  - api is limited to 2 CPU / 2 GB and runs `WEB_CONCURRENCY` uvicorn workers. It scales with `docker compose up --scale api=N`. nginx (`frontend/nginx.conf`) re-resolves `api` via Docker DNS (`resolver 127.0.0.11`, `proxy_pass $api`), so recreated or scaled api containers are picked up without restarting nginx. Do not switch back to a static `upstream` block: it pins the IP at startup and gives 502 after api is recreated. nginx-generated 502/504 are returned as JSON `api_unavailable`.

## Data caveats

- Stop coordinates: routes 1, 5, 7, 11, 12 from the xlsx reference, 17, 25, 26, 28, 50 from OSM (`osm_tram.geojson`). Reference routes 2/3/4/6/10 have no forecast and are filtered out. Reference terminal stops often sit on turnaround loops 100–300 m off the OSM relation track; that's why `Rails` exists.
- Raw validations have no stop (`place_id` is a depot), so stop forecasts are route forecasts × a heuristic share. Route 5 has no history, so its forecast is 0.
- Seed history files have partial edge days; `normalize.trim_partial_edges` drops edge days below 20% of the median day, but only for files covering at least 3 days.
