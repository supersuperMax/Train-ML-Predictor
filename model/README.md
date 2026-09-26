# Контракт модели прогноза

Сервис не зависит от устройства модели. Worker подключает её через адаптер (`worker/model_adapter.py`) в одном из режимов. Режим выбирается переменной `MODEL_MODE`.

## Текущая модель — `tram_model/`

Модель команды лежит в [tram_model/](tram_model/README.md): профиль + LightGBM + CatBoost, прогноз на ноябрь–декабрь 2025. Сервис читает её готовый прогноз `tram_model/artifacts/forecast.csv` в режиме `file` и **не пересобирает модель**: lightgbm и catboost в worker не нужны. Даты после 31.12.2025 достраивает baseline (`MODEL_FALLBACK=baseline`).

Пересборка — только у команды и вне сервиса:

```bash
cd model/tram_model && pip install -r requirements.txt && python -m tram.forecast
```

Новый `forecast.csv` worker подхватит сам (он следит за папкой `model/`).

## Режим `file` (по умолчанию)

Файл прогноза ищется в `MODEL_DIR` по порядку: `predictions.parquet`, `predictions.csv`, `tram_model/artifacts/forecast.csv`. Другой путь задаётся переменной `MODEL_FILE` (относительно `MODEL_DIR`). У CSV разделитель `;` или `,`, кодировка UTF-8.

| Колонка | Тип | Значения |
|---|---|---|
| `route` | int | номер маршрута |
| `date` | `YYYY-MM-DD` | дата |
| `hour` | int | 0…23 |
| `prediction` | число ≥ 0 | прогноз числа посадок за час |

Что проверяет сервис:
- колонки есть и числовые;
- нет пустых значений и повторяющихся ключей `route/date/hour`;
- у каждого маршрута полная сетка: все даты диапазона × 24 часа;
- отрицательные значения обрезаются до 0 с предупреждением в логе.

Если проверка не прошла, прогон пайплайна завершается ошибкой, и сервис продолжает отдавать предыдущий прогноз. Ошибку видно в `/api/meta` (`last_run.error`) и в таблице `pipeline_runs`.

Горизонт прогноза задаёт сам файл. Даты за его пределами (например, до конца следующего года для горизонта «год») достраивает встроенный baseline, если `MODEL_FALLBACK=baseline`. Такие точки помечаются `source: "baseline"`, и интерфейс показывает это. Чтобы отключить достройку, задайте `MODEL_FALLBACK=none`.

## Режим `plugin`

Положите в эту папку `predictor.py` и артефакты модели (веса и т. п.). Зависимости допишите в `worker/requirements.txt`.

```python
import pandas as pd

NAME = "CatBoost v2 (команда N)"   # необязательно: название для /api/meta
MAX_DATE = "2026-12-31"            # необязательно: последняя дата, которую модель умеет прогнозировать

def predict(keys: pd.DataFrame, features: pd.DataFrame, history: pd.DataFrame):
    """
    keys     — сетка ключей: route (int), date (datetime64), hour (int), по строке на час;
    features — те же строки плюс календарные признаки сервиса: dow, daytype, is_holiday, is_short,
               is_working_weekend, after_holiday, month, season (модель может их игнорировать);
    history  — почасовая история посадок: route, date, hour, boardings.
    Вернуть массив прогнозов длиной len(keys) в том же порядке строк.
    """
```

Артефакты читайте относительно файла: `Path(__file__).parent / "model.cbm"`.

Worker запрашивает прогноз от дня после конца истории до `FORECAST_END` (по умолчанию 31 декабря следующего года), по маршрутам из `FORECAST_ROUTES`. Если задан `MAX_DATE`, дальше него прогноз достраивает baseline (при `MODEL_FALLBACK=baseline`).

Рабочий пример — `predictor_example.py`: переименуйте его в `predictor.py` и задайте `MODEL_MODE=plugin`.

## Режим `baseline`

Встроенный профильный прогноз, это не ML-модель: средний профиль маршрута по типу дня и часу за последние 5 недель истории × сезонный индекс месяца. Используется для проверки сервиса без модели.

## Как пересчитать прогноз после замены модели

Worker следит за этой папкой и сам запускает пайплайн при изменении файлов (раз в `PIPELINE_POLL_SEC`). Можно запустить и вручную:

```bash
docker compose run --rm worker python -m worker run --step inference --step snapshot
```
