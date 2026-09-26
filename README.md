# ML прогноз

Веб-сервис прогноза посадок (успешных валидаций) на трамвайных маршрутах. Что он делает:
- прогноз на три горизонта: день по часам, месяц по дням, год по месяцам;
- агрегация по маршруту, остановке, интервалу часов и шагу времени;
- карта Москвы с загрузкой остановок и анимацией по часам суток;
- выгрузка в CSV и XLSX;
- пайплайн приёма, нормализации и геопривязки валидаций, который работает по расписанию.

## Архитектура

```
data/incoming/*.csv ─┐
data/history/*.csv ──┤                         ┌─► data/snapshot/<версия>/ ──► api (FastAPI) ──► frontend (nginx + React)
data/reference/*.xlsx┤  worker (пайплайн)      │        (parquet + manifest)       ▲ :3000/api/         :3000
model/ (модель) ─────┘  ingest → normalize →   │
                        geo → inference ───────┴─► PostgreSQL (история, прогноз, справочники, pipeline_runs)
```

| Сервис | Стек | Роль |
|---|---|---|
| `frontend` | React 19, TypeScript 5, Vite, Recharts, MapLibre + OSM | Дашборд. nginx раздаёт статику и проксирует `/api/` на `api` |
| `api` | FastAPI, numpy | REST API. Держит опубликованный прогноз в памяти и перечитывает его при новой версии без перезапуска |
| `worker` | pandas, pyarrow | Пайплайн: приём → нормализация → геопривязка → прогноз модели → публикация snapshot |
| `postgres` | PostgreSQL 16 | Хранилище истории, прогноза, справочников и журнала прогонов |

API читает только snapshot-файлы. Поэтому у него нет состояния, он не зависит от базы и масштабируется горизонтально.

## Запуск

```bash
docker compose up --build
```

- Дашборд: http://localhost:3000
- API: http://localhost:3000/api/…, документация Swagger: http://localhost:3000/api/docs
- PostgreSQL: `localhost:5432`, база/пользователь/пароль `tram`

При старте worker сразу выполняет полный прогон пайплайна (несколько секунд), и дашборд показывает прогноз. Пока прогноз не опубликован, API отвечает `503` с понятным сообщением, а дашборд ждёт и сам обновляется.

Масштабирование API: `docker compose up --scale api=3`. Чтобы nginx увидел новые реплики, перезапустите `frontend`.

### Локальная разработка без Docker

```bash
pip install -r worker/requirements.txt -r backend/requirements.txt -r requirements-dev.txt
python -m worker run --once                                   # построить snapshot в data/snapshot/
cd backend && uvicorn app.main:app --reload --port 8000       # API
cd frontend && npm install && npm run dev                     # http://localhost:5173, /api проксируется на :8000
pytest                                                        # тесты пайплайна и API (из корня репозитория)
```

## Пайплайн данных

### Шаги

| Шаг | Вход | Выход | Что делает |
|---|---|---|---|
| `ingest` | `data/incoming/*.csv` | `data/store/staging/*.parquet` | Читает сырые валидации (разделитель `;`) по частям по `INGEST_CHUNK_ROWS` строк. Берёт только `tran_date_time`, `validation_result`, `ngpt_route` и сворачивает до счётчиков. Принятый файл переносится в `incoming/processed/`, битый — в `incoming/failed/` |
| `normalize` | staging, `data/history/*.csv` | `data/store/history.parquet` | Посадка = `validation_result == 1`. Маршрут — число из `ngpt_route` (`"25 трамвай"` → 25). Дата и час берутся из `tran_date_time`. Неполные крайние дни файла отбрасываются. Итог — почасовая история `route × date × hour`. При первом запуске история засевается из `data/history/` |
| `geo` | `data/reference/*.xlsx` | `data/store/route_stops.parquet` | Геопривязка: маршруты, порядок остановок по направлениям, координаты и доля каждой остановки в посадках маршрута |
| `inference` | история, `model/` | `data/store/forecast.parquet` | Сетка ключей и календарные признаки передаются модели через адаптер. Результат проверяется: схема, полнота сетки, пустые и отрицательные значения |
| `snapshot` | `data/store/*` | `data/snapshot/<версия>/`, PostgreSQL | Публикует версию для API: атомарно переключает `data/snapshot/CURRENT` и хранит `KEEP_SNAPSHOTS` последних версий. Зеркалирует данные в PostgreSQL |

Если шаг упал, остальные пропускаются, а API продолжает отдавать предыдущий прогноз. Ошибка попадает в журнал.

### Как запускать

Полный прогон один раз:

```bash
docker compose run --rm worker python -m worker run --once
# без Docker: python -m worker run --once
```

Отдельные шаги (порядок всегда ingest → normalize → geo → inference → snapshot):

```bash
docker compose run --rm worker python -m worker run --step ingest --step normalize
docker compose run --rm worker python -m worker run --step inference --step snapshot
```

По расписанию: сервис `worker` в `docker compose up` запускает пайплайн при старте и затем каждые `PIPELINE_INTERVAL_MIN` минут. Раз в `PIPELINE_POLL_SEC` секунд он проверяет входы и запускает внеочередной прогон, если появились новые файлы в `data/incoming/`, изменилась модель в `model/` или обновились справочники и история.

Загрузить новые валидации — положите CSV в формате сырых файлов хакатона (`tran_date_time;validation_result;ngpt_route;…`) в `data/incoming/`. Worker подхватит их в течение `PIPELINE_POLL_SEC` секунд, либо запустите `--step ingest --step normalize --step inference --step snapshot`.

Подложить модель другой команды — см. [model/README.md](model/README.md):
- **режим `file`** (по умолчанию): файл `model/predictions.csv` или `.parquet` с колонками `route, date, hour, prediction`;
- **режим `plugin`**: `model/predictor.py` с функцией `predict(keys, features, history)`, включается через `MODEL_MODE=plugin docker compose up`.

После замены файлов worker пересчитает прогноз сам.

### Как проверить результат

- `GET /api/meta` — версия snapshot, доступный период, модель, `last_run` (статус и ошибка последнего прогона);
- `data/store/runs.jsonl` — журнал всех прогонов с деталями по шагам;
- таблица `pipeline_runs` в PostgreSQL:

```bash
docker compose exec postgres psql -U tram -c "SELECT id, started_at, status, version, error FROM pipeline_runs ORDER BY id DESC LIMIT 5"
```

### Настройки worker

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `MODEL_MODE` | `file` | `file` / `plugin` / `baseline` |
| `MODEL_FALLBACK` | `baseline` | Достраивать горизонт за пределами модели встроенным baseline (`none` — не достраивать) |
| `FORECAST_START` / `FORECAST_END` | день после истории / 31.12 следующего года | Период прогноза |
| `FORECAST_ROUTES` | `1,5,7,11,12,17,25,26,28,50` | Маршруты для режимов `plugin` / `baseline` |
| `PIPELINE_INTERVAL_MIN` | `60` | Период плановых прогонов |
| `PIPELINE_POLL_SEC` | `30` | Период проверки новых входных файлов |
| `INGEST_CHUNK_ROWS` | `5000000` | Размер части при чтении сырых CSV |
| `KEEP_SNAPSHOTS` | `3` | Сколько версий snapshot хранить |
| `DATA_DIR`, `MODEL_DIR` | `data/`, `model/` | Папки данных и модели |
| `DATABASE_URL` | — | PostgreSQL. Без него пайплайн работает только с файлами |

## API

Все ответы — JSON. Ошибки приходят в едином формате `{"error": {"code": "...", "message": "понятный текст"}}` с кодами 400, 404, 422 и 503.

| Метод | Назначение |
|---|---|
| `GET /api/forecast` | Прогноз с агрегацией |
| `GET /api/summary` | Итог, среднее, пики, разбивка по типу дня (будни / сб / вс / праздники) |
| `GET /api/export/csv`, `/api/export/xlsx` | Выгрузка: те же параметры, ряды по каждому маршруту |
| `GET /api/routes` | Маршруты с прогнозом: название, есть ли остановки |
| `GET /api/stops?route=` | Остановки с координатами и линии маршрутов |
| `GET /api/map?date=&hour=&route=` | Нагрузка на остановки в момент времени (без `hour` — за день) |
| `GET /api/meta` | Версия прогноза, период, модель, факторы, статус пайплайна |
| `GET /health`, `/ready` | Живость и готовность (snapshot загружен) |

Параметры `/api/forecast`, `/api/summary` и экспорта:

| Параметр | Значение |
|---|---|
| `horizon` | `day` (по часам), `month` (по дням), `year` (по месяцам) |
| `date` | Дата начала горизонта, `ГГГГ-ММ-ДД`. По умолчанию — первый день прогноза |
| `from`, `to` | Явный период вместо `horizon`/`date` |
| `route` | Маршрут. Без него — сумма по всем |
| `stop_id` | Остановка |
| `hour_from`, `hour_to` | Интервал часов суток, 0–23 |
| `granularity` | Шаг: `hour`, `day`, `week`, `month`. По умолчанию выводится из горизонта |

Примеры:

```bash
curl "http://localhost:3000/api/forecast?horizon=day&date=2025-11-10&route=17"          # день по часам
curl "http://localhost:3000/api/forecast?horizon=month&date=2025-11-01&route=1&stop_id=2594"  # месяц по остановке
curl "http://localhost:3000/api/forecast?horizon=year&date=2025-11-01"                   # год по месяцам
curl "http://localhost:3000/api/forecast?from=2025-11-01&to=2025-11-30&hour_from=7&hour_to=10&granularity=week"  # утренний пик по неделям
curl "http://localhost:3000/api/summary?horizon=month&route=50"
curl -OJ "http://localhost:3000/api/export/xlsx?horizon=month&route=7"
```

В каждой точке есть `source`: `model` — прогноз модели, `baseline` — достроено встроенным профильным прогнозом (не ML) за пределами горизонта модели. Дашборд показывает такие точки серым.

## Учёт факторов

Сервис сам считает календарные признаки и передаёт их модели в режиме `plugin`:
- час суток;
- день недели, причём рабочая суббота считается пятницей;
- тип дня: будни, суббота, воскресенье, праздник;
- праздники и сокращённые дни по производственному календарю РФ на 2025–2026 годы, первый день после праздника;
- месяц и сезон.

Разбивка по типу дня видна в `/api/summary` и на дашборде.

**Погода не учитывается:** данных о погоде нет. Точка расширения — дополнительные признаки в `worker/features.py` или внутри модели в режиме `plugin`.

## Ограничения

- **Остановки.** Координаты остановок есть в справочнике только для маршрутов 1, 5, 7, 11, 12. В сырых валидациях нет остановки: `place_id` — это депо. Поэтому прогноз по остановке — это прогноз маршрута × доля остановки: внутри направления посадки линейно убывают к конечной, направления делят поток поровну. Расписание в справочнике — лишь выборка из нескольких рейсов, поэтому доли не различаются по часам.
- **Маршрут 5** отсутствует в истории, его прогноз равен 0.
- **Горизонт «год»** зависит от модели. Сейчас в `model/predictions.csv` лежит заглушка на ноябрь–декабрь 2025, а остальной период до конца 2026 года достраивает baseline с пометкой `source: baseline`.

## Производительность

> Нагрузочное тестирование ещё не проводилось — раздел будет заполнен результатами замеров.

Стенд для замеров — контейнер `api` с лимитами из `docker-compose.yml`:

| Параметр | Значение |
|---|---|
| CPU / RAM | 2 vCPU / 2 ГБ (`cpus: 2`, `mem_limit: 2g`) |
| Процессы | `WEB_CONCURRENCY=2` воркера uvicorn |
| Цель ТЗ | сотни RPS, p95 < 200–300 мс, CPU 60–80 %, RAM стабильна без swap |

Что сделано для производительности:
- прогноз лежит в памяти плотным массивом `маршрут × день × час`, и запрос сводится к срезу и сумме в numpy без pandas-фильтрации;
- результаты кешируются по версии snapshot (LRU);
- ответы сериализуются через ORJSON и сжимаются GZip;
- работают `ETag` и `304 Not Modified`, `Cache-Control`;
- snapshot перечитывается без остановки сервиса.

| Сценарий | RPS | p50 | p95 | p99 | CPU | RAM |
|---|---|---|---|---|---|---|
| _будет заполнено_ | | | | | | |
