# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

MVP web service for a hackathon task: forecasting hourly tram boardings (`route × date × hour`) on Moscow tram routes for Nov–Dec 2025. The ML work (EDA, CatBoost model, `submission.csv`) lives in the **parent directory** (`../main.ipynb`, `../MODEL_REPORT.md`, `../EDA_FINDINGS.md`, `../README.md`); this `server/` repo only serves precomputed predictions. Route/stop reference data (with coordinates) is in `../spravochniki/*.xlsx` and is not yet wired in (`/api/stops` returns `[]`). README and UI text are in Russian.

## Commands

No tests, linters, or CI are configured.

```bash
# Full stack (frontend :3000, api :8000, postgres :5432, worker)
docker compose up --build

# Backend locally — run from backend/ so `app.*` imports resolve
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000

# Frontend locally
cd frontend && npm install && npm run dev
```

## Architecture

- **backend/** (FastAPI): `app/main.py` mounts three routers under `/api` (`forecast.py` → `/forecast`, `/summary`; `routes.py` → `/routes`, `/stops`; `export.py` → `/export/csv`, `/export/xlsx`). All of them go through a single module-level singleton `service` in `app/services/forecast_service.py`. It loads the whole predictions table into a pandas DataFrame **once at import time** and filters it in memory on every request. Query params `from`/`to` are aliased to `date_from`/`date_to` (ISO dates, inclusive).
- **Data loading**: `ForecastService` resolves `data/` as `parents[2]` of its file. That works both locally (`server/data`) and in the container (`/app/data`, copied by the Dockerfile). It prefers `data/predictions.parquet` and falls back to `data/predictions.csv`. Expected columns: `route, date, hour, prediction`. The checked-in `data/predictions.csv` is **synthetic placeholder data**. The real model output (`../submission.csv`) uses `;` as its separator, while `pd.read_csv` here assumes commas, so convert it (or pass `sep=";"`) before dropping it in.
- **worker/**: a stub (`while True: sleep`). The planned pipeline is ingest → normalize → aggregate → inference → snapshot. Its Dockerfile does `COPY model ./model`, but `model/` is empty and git doesn't track empty dirs, so on a fresh clone that build step fails until the directory has content.
- **postgres**: provisioned in compose and `DATABASE_URL` is passed to api/worker, but no code uses it yet.
- **frontend/** (React + Vite + Recharts, one page in `src/App.tsx`): the API base URL is hardcoded as `http://localhost:8000/api`, and the production image is static files served by nginx with no proxy. There is no `vite.config.*` or `tsconfig.json`, and every dependency is pinned to `latest`.
- Docker build contexts are the repo root (`context: .`), so Dockerfile `COPY` paths are relative to `server/`, not to each service's folder.
