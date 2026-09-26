import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .calendar import calendar
from .data import load_grid, recent_levels
from .features import fit_stats, frame, history, with_stats
from .models import CatBoost, LightGBMPool, Profile
from .settings import (BRIDGE_DAYS, BRIDGE_K, CALIBRATION_SKIP_DAYS, DAY_K, FREE_NIGHT_FROM, HISTORY_END, HORIZON,
                       KEYS, LEVEL_K, REGIME_END, REGIMES, ROUTE5_ANALOGS, ROUTE5_START, ROUTE5_WEEKDAY,
                       ROUTE_MONTH_K, ROUTES, WEEKEND_K)

ROOT = Path(__file__).resolve().parents[1]


def grid_keys(routes, dates):
    return pd.MultiIndex.from_product([routes, pd.DatetimeIndex(dates), range(24)], names=KEYS).to_frame(index=False)


def model_forecast(grid, threads):
    train = history(grid)
    stats = fit_stats(train)
    train = with_stats(train, stats)
    future = with_stats(frame(grid_keys(sorted(grid.route.unique()), HORIZON), REGIME_END), stats)
    shape = np.mean([m.fit(train).predict(future) for m in (Profile(), LightGBMPool(threads), CatBoost(threads))],
                    axis=0)
    pred = shape * future.route.map(recent_levels(grid, HISTORY_END)).values * LEVEL_K
    pred = np.where((future.daytype.values > 0) & (future.is_holiday.values == 0), pred * WEEKEND_K, pred)
    out = grid_keys(ROUTES, HORIZON).merge(future[KEYS].assign(prediction=pred), how="left", on=KEYS)
    out["prediction"] = out.prediction.fillna(0).clip(lower=0)
    out["date"] = out.date.dt.strftime("%Y-%m-%d")
    return out


def route5_profile(sub):
    dt = pd.to_datetime(sub.date)
    weekday = dt.map(calendar(dt.unique()).daytype).values == 0
    december = dt.dt.month == 12
    n_weekdays = (calendar(pd.date_range("2025-12-01", "2025-12-31")).daytype == 0).sum()
    shares = []
    for route in ROUTE5_ANALOGS:
        rows = december & (sub.route == route)
        mean_weekday = sub.prediction[rows & weekday].sum() / n_weekdays
        shares.append(pd.Series(sub.prediction[rows].values / mean_weekday, index=[dt[rows].values, sub.hour[rows].values]))
    unit = pd.concat(shares, axis=1).mean(axis=1)
    target = ((sub.route == 5) & (dt >= ROUTE5_START)).values
    out = np.zeros(len(sub))
    out[target] = unit.reindex(pd.MultiIndex.from_arrays([dt[target].values, sub.hour[target].values])).values
    return out


def with_events(sub):
    sub = sub.copy()
    route5 = (sub.route == 5).values
    sub.loc[route5, "prediction"] = (route5_profile(sub) * ROUTE5_WEEKDAY)[route5]
    sub.loc[sub.date.isin(BRIDGE_DAYS).values, "prediction"] *= BRIDGE_K
    moment = pd.to_datetime(sub.date) + pd.to_timedelta(sub.hour, unit="h")
    sub.loc[(moment >= FREE_NIGHT_FROM).values, "prediction"] = 0.0
    sub["prediction"] = sub.prediction.round().astype(int)
    return sub


def calibrated(sub):
    dt = pd.to_datetime(sub.date)
    regime = sub.route.isin(REGIMES.values()) & (dt <= REGIME_END) & (dt.dt.dayofweek >= 5)
    factor = np.ones(len(sub))
    for month, routes in ROUTE_MONTH_K.items():
        for route, k in routes.items():
            factor[((sub.route == route) & (dt.dt.month == month) & ~sub.date.isin(CALIBRATION_SKIP_DAYS)
                    & ~regime).values] *= k
    for day, k in DAY_K.items():
        factor[((sub.date == day) & ~regime).values] *= k
    return sub.assign(prediction=np.round(sub.prediction * factor).astype(int))


def build(labels_dir=ROOT / "data", threads=4):
    return calibrated(with_events(model_forecast(load_grid(labels_dir), threads)))


def main():
    parser = argparse.ArgumentParser(description="Прогноз посадок трамвая по маршрутам и часам на ноябрь–декабрь 2025")
    parser.add_argument("--labels", default=ROOT / "data", type=Path)
    parser.add_argument("--out", default=ROOT / "artifacts" / "forecast.csv", type=Path)
    parser.add_argument("--threads", default=4, type=int)
    args = parser.parse_args()
    forecast = build(args.labels, args.threads)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    forecast.to_csv(args.out, sep=";", index=False, lineterminator="\n")
    print(f"{args.out}: {len(forecast)} строк, {forecast.prediction.sum():,} посадок")


if __name__ == "__main__":
    main()
