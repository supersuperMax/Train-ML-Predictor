from pathlib import Path

import pandas as pd

from .calendar import calendar
from .settings import (ANOMALY_THRESHOLD, HOLIDAYS, KEYS, LEVEL_WEEKS, REGIME_START, REGIMES, SHORT_DAYS,
                       WORKING_WEEKENDS)


def load_grid(labels_dir):
    parts = [pd.read_csv(Path(labels_dir) / f"labels_day_{part}.csv", sep=";", parse_dates=["date"])
             for part in ("train", "test")]
    raw = pd.concat(parts, ignore_index=True)
    index = pd.MultiIndex.from_product(
        [sorted(raw.route.unique()), pd.date_range(raw.date.min(), raw.date.max()), range(24)], names=KEYS)
    return raw.set_index(KEYS)["boardings"].reindex(index, fill_value=0).reset_index()


def daily_totals(grid):
    d = grid.groupby(["route", "date"], as_index=False).boardings.sum()
    return d.join(calendar(d.date.unique()), on="date")


def anomalies(d):
    d = d.sort_values(["route", "date"])
    special = d.date.isin(HOLIDAYS) | d.date.isin(SHORT_DAYS) | d.date.isin(WORKING_WEEKENDS)
    regime = d.route.isin(REGIMES.values()) & (d.date >= REGIME_START) & (d.date.dt.dayofweek >= 5)
    y = d.boardings.where(~special).astype(float)
    same_weekday = y.groupby([d.route, d.date.dt.dayofweek])
    expected = pd.concat([same_weekday.shift(s) for s in (-3, -2, -1, 1, 2, 3)], axis=1).median(axis=1, skipna=True)
    ratio = d.boardings / expected
    mask = (ratio - 1).abs().gt(ANOMALY_THRESHOLD) & ~special & ~regime & expected.gt(0)
    return mask.reindex(d.index).fillna(False).astype(bool)


def _regular_weekdays(d):
    return d[(d.dow < 5) & (d.is_holiday == 0) & (d.is_short_day == 0) & (d.is_post_holiday == 0)]


def month_levels(grid):
    d = _regular_weekdays(daily_totals(grid))
    d = d[~anomalies(d)]
    return d.groupby(["route", d.date.dt.to_period("M")]).boardings.mean()


def recent_levels(grid, end):
    window = grid[(grid.date <= end) & (grid.date > end - pd.Timedelta(weeks=LEVEL_WEEKS + 6))]
    d = _regular_weekdays(daily_totals(window))
    return d.sort_values("date").groupby("route").tail(5 * LEVEL_WEEKS).groupby("route").boardings.mean()
