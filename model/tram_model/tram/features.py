import numpy as np
import pandas as pd

from .calendar import calendar
from .data import anomalies, daily_totals, month_levels
from .settings import REGIME_START, REGIMES, SUMMER_MONTHS, SUMMER_WEIGHT

FEATURES = ["route", "hour", "dow_eff", "daytype", "is_holiday", "hol_block_len", "hol_day_in_block",
            "hol_days_to_end", "is_newyear", "is_pre_holiday", "is_post_holiday", "is_working_weekend",
            "is_short_day", "weekend_closed", "weekend_reduced", "tgt_med_rdh", "dow_coef", "daylight_c"]


def frame(keys, regime_end=None):
    df = keys.join(calendar(keys.date.unique()), on="date")
    weekend = df.date.dt.dayofweek >= 5
    active = (df.date >= REGIME_START) & ((df.date <= regime_end) if regime_end is not None else True)
    for name, route in REGIMES.items():
        df[name] = ((df.route == route) & active & weekend).astype(int)
    return df


def history(grid):
    df = frame(grid)
    month = pd.MultiIndex.from_arrays([df.route, df.date.dt.to_period("M")])
    df["level"] = month_levels(grid).reindex(month).values
    df["target"] = df.boardings / df.level
    d = daily_totals(grid)
    bad = d.loc[anomalies(d), ["route", "date"]].assign(anomaly=1)
    df = df.merge(bad, on=["route", "date"], how="left")
    df["anomaly"] = df.anomaly.fillna(0).astype(int)
    summer = np.where(df.date.dt.month.isin(SUMMER_MONTHS), SUMMER_WEIGHT, 1.0)
    df["weight"] = df.level * summer * (1 - df.anomaly)
    return df


def regular(df):
    return ((df.weight > 0) & ~df.date.dt.month.isin(SUMMER_MONTHS) & (df.is_holiday == 0) & (df.is_short_day == 0)
            & (df.weekend_closed == 0) & (df.weekend_reduced == 0))


def fit_stats(train):
    n = train[regular(train)]
    hour_share = n.groupby(["route", "daytype", "hour"]).target.median().rename("tgt_med_rdh")
    day = n.groupby(["route", "date", "dow"]).target.sum()
    weekday_k = day.groupby(["route", "dow"]).median().rename("dow_coef")
    return hour_share, weekday_k


def with_stats(df, stats):
    hour_share, weekday_k = stats
    df = df.join(hour_share, on=["route", "daytype", "hour"])
    df["dow_coef"] = df[["route", "dow_eff"]].rename(columns={"dow_eff": "dow"}).join(
        weekday_k, on=["route", "dow"])["dow_coef"].values
    return df
