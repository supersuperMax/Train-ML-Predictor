# Tram Forecast MVP

MVP сервиса прогнозирования пассажиропотока.

## Архитектура
- Frontend: React + TypeScript + Recharts
- Backend: FastAPI
- Worker: realtime/batch pipeline (подключается к готовой ML-модели)
- PostgreSQL: история, агрегаты и состояние pipeline
- Parquet/Arrow: быстрые снапшоты прогнозов

## API
- GET `/health`
- GET `/api/routes`
- GET `/api/stops`
- GET `/api/forecast?route=...&from=...&to=...`
- GET `/api/summary?...`
- GET `/api/export/csv?...`
- GET `/api/export/xlsx?...`

## Следующий шаг
Подключить фактический формат готовой модели и реальные `predictions.parquet`/справочники из датасета.
