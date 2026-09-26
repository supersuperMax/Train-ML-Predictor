from functools import lru_cache

import numpy as np
import pandas as pd

from .settings import (DAYLIGHT_FLOOR_DAY, HOLIDAYS, MOSCOW_LAT, NEW_YEAR, NEW_YEAR_EVE, SHORT_DAYS,
                       WORKING_WEEKENDS)


def _daylight(days):
    decl = np.radians(23.44) * np.sin(2 * np.pi * (284 + days.dayofyear.values) / 365)
    cos_w = np.clip(-np.tan(np.radians(MOSCOW_LAT)) * np.tan(decl), -1, 1)
    return 2 * np.degrees(np.arccos(cos_w)) / 15


@lru_cache(maxsize=1)
def _table():
    days = pd.date_range("2024-12-20", "2026-01-20")
    dow = days.dayofweek.values
    holiday = days.isin(HOLIDAYS)
    working_weekend = days.isin(WORKING_WEEKENDS)
    day_off = ((dow >= 5) & ~working_weekend) | holiday

    runs = pd.Series(np.cumsum(np.r_[True, day_off[1:] != day_off[:-1]]), index=days)
    in_block = day_off & pd.Series(holiday, index=days).groupby(runs).transform("any").values
    run_len = runs.map(runs.value_counts()).values
    position = runs.groupby(runs).cumcount().values + 1
    work = ~day_off

    c = pd.DataFrame(index=days)
    c["dow"] = dow
    c["is_weekend"] = (dow >= 5).astype(int)
    c["is_holiday"] = holiday.astype(int)
    c["is_working_weekend"] = working_weekend.astype(int)
    c["is_short_day"] = days.isin(SHORT_DAYS).astype(int)
    c["is_newyear"] = days.isin(NEW_YEAR).astype(int)
    c["hol_block_len"] = np.where(in_block, np.minimum(run_len, 8), 0)
    c["hol_day_in_block"] = np.where(in_block, position, 0)
    c["hol_days_to_end"] = np.where(in_block, run_len - position, -1)
    c["is_pre_holiday"] = (work & np.r_[in_block[1:], False]).astype(int)
    c["is_post_holiday"] = (work & np.r_[False, in_block[:-1]]).astype(int)
    c["dow_eff"] = np.where(working_weekend, 4, dow)
    c["daytype"] = np.where(holiday | (dow == 6), 2, np.where((dow == 5) & ~working_weekend, 1, 0))
    c["daylight"] = _daylight(days)
    c["daylight_c"] = c.daylight.clip(lower=c.loc[DAYLIGHT_FLOOR_DAY, "daylight"])
    c.loc[NEW_YEAR_EVE, ["hol_block_len", "hol_day_in_block", "hol_days_to_end"]] = [4, 1, 3]
    return c


def calendar(dates):
    return _table().loc[pd.DatetimeIndex(dates)]
