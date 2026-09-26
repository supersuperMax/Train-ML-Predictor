"""Календарные признаки: производственный календарь РФ, тип дня, сезон.

Сервис считает их сам и передаёт модели (режим plugin) — модель может ими пользоваться или игнорировать.
"""
import numpy as np
import pandas as pd

# Нерабочие праздничные дни, включая переносы и выходные внутри праздничных блоков.
# 2025 — как в исследовательском ноутбуке; 2026 — по постановлению Правительства РФ о переносе выходных.
HOLIDAYS = pd.to_datetime([
    "2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05", "2025-01-06",
    "2025-01-07", "2025-01-08", "2025-02-23", "2025-03-08", "2025-05-01", "2025-05-02",
    "2025-05-03", "2025-05-04", "2025-05-08", "2025-05-09", "2025-05-10", "2025-05-11",
    "2025-06-12", "2025-06-13", "2025-06-14", "2025-06-15", "2025-11-02", "2025-11-03",
    "2025-11-04", "2025-12-31",
    "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06",
    "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-10", "2026-01-11", "2026-02-23",
    "2026-03-08", "2026-03-09", "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-09",
    "2026-05-10", "2026-05-11", "2026-06-12", "2026-06-13", "2026-06-14", "2026-11-04",
    "2026-12-31",
])
WORKING_WEEKENDS = pd.to_datetime(["2025-11-01"])  # суббота — рабочий день
SHORT_DAYS = pd.to_datetime([                       # предпраздничные сокращённые
    "2025-03-07", "2025-04-30", "2025-06-11", "2025-11-01",
    "2026-04-30", "2026-05-08", "2026-06-11", "2026-11-03",
])

SEASONS = np.array(["winter", "winter", "spring", "spring", "spring", "summer",
                    "summer", "summer", "autumn", "autumn", "autumn", "winter"])

FACTORS = {
    "hour": "час суток",
    "dow": "день недели (рабочая суббота считается пятницей)",
    "daytype": "тип дня: будни / суббота / воскресенье / праздник",
    "is_holiday": "праздник по производственному календарю РФ",
    "is_short": "предпраздничный сокращённый день",
    "after_holiday": "первый будний день после праздника",
    "month": "месяц",
    "season": "сезон",
}


def calendar(dates) -> pd.DataFrame:
    """Одна строка на дату: признаки календаря."""
    d = pd.to_datetime(pd.Series(pd.unique(pd.to_datetime(dates)))).sort_values().reset_index(drop=True)
    hol = d.isin(HOLIDAYS)
    work_we = d.isin(WORKING_WEEKENDS)
    dow = d.dt.dayofweek
    eff_dow = np.where(work_we, 4, dow)
    return pd.DataFrame({
        "date": d,
        "dow": eff_dow.astype("int8"),
        "daytype": np.select([hol, eff_dow == 5, eff_dow == 6], ["holiday", "sat", "sun"], "weekday"),
        "is_holiday": hol.astype("int8"),
        "is_short": d.isin(SHORT_DAYS).astype("int8"),
        "is_working_weekend": work_we.astype("int8"),
        "after_holiday": ((d - pd.Timedelta(days=1)).isin(HOLIDAYS) & ~hol & (dow < 5)).astype("int8"),
        "month": d.dt.month.astype("int8"),
        "season": SEASONS[d.dt.month.values - 1],
    })


def for_keys(keys: pd.DataFrame) -> pd.DataFrame:
    """Признаки для сетки ключей route × date × hour (в том же порядке строк)."""
    cal = calendar(keys["date"])
    out = keys.merge(cal, on="date", how="left")
    out["hour"] = keys["hour"].values
    return out
