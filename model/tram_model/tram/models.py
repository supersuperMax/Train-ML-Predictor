from functools import partial

import catboost as cb
import lightgbm as lgb
import numpy as np
import pandas as pd

from .features import FEATURES, regular
from .settings import CAT_PARAMS, LGB_PARAMS, LGB_ROUNDS

WORKING_SATURDAY_K = 0.9
WEEKDAY_HOLIDAY_K = 0.9
REGIME_WINDOW_DAYS = 56
ROUTE_GROUPS = {1: "city", 11: "city", 12: "city", 25: "city", 26: "city", 28: "city", 17: "r17", 7: "reg", 50: "reg"}


class Profile:
    def fit(self, train):
        self.base = train[regular(train)].groupby(["route", "dow", "hour"]).target.median()
        recent = train.date > train.date.max() - pd.Timedelta(days=REGIME_WINDOW_DAYS)
        regime = (train.weekend_closed == 1) | (train.weekend_reduced == 1)
        self.regime = train[regime & recent & (train.weight > 0)].groupby(["route", "dow", "hour"]).target.median()
        sunday_total = self.base.xs(6, level="dow").groupby("route").sum()
        holidays = train[(train.is_holiday == 1) & (train.is_newyear == 0)]
        days = holidays.groupby(["route", "date", "is_weekend"]).target.sum().reset_index()
        days["ratio"] = days.target / days.route.map(sunday_total)
        self.holiday_k = days.groupby("is_weekend").ratio.median().to_dict()
        return self

    def predict(self, df):
        p = self.base.reindex(pd.MultiIndex.from_arrays([df.route, df.dow_eff, df.hour])).values.copy()
        sunday = self.base.reindex(pd.MultiIndex.from_arrays([df.route, np.full(len(df), 6), df.hour])).values
        holiday = (df.is_holiday == 1).values
        k = np.where(df.is_weekend.values == 1, self.holiday_k.get(1, 1.0), self.holiday_k.get(0, WEEKDAY_HOLIDAY_K))
        p[holiday] = sunday[holiday] * k[holiday]
        p[(df.is_working_weekend == 1).values] *= WORKING_SATURDAY_K
        regime = ((df.weekend_closed == 1) | (df.weekend_reduced == 1)).values
        if regime.any() and len(self.regime):
            dow = np.where(holiday, 6, df.dow_eff.values)
            r = self.regime.reindex(pd.MultiIndex.from_arrays([df.route, dow, df.hour])).values
            known = regime & ~np.isnan(r)
            p[known] = r[known]
        return np.nan_to_num(p, nan=0.0).clip(min=0)


class LightGBM:
    def __init__(self, threads):
        self.params = {**LGB_PARAMS, "num_threads": threads}

    def _x(self, df):
        x = df[FEATURES].copy()
        x["route"] = pd.Categorical(x.route, categories=self.routes)
        return x

    def fit(self, train):
        train = train[train.weight > 0]
        self.routes = sorted(train.route.unique())
        data = lgb.Dataset(self._x(train), train.target, weight=train.weight, categorical_feature=["route"])
        self.model = lgb.train(self.params, data, LGB_ROUNDS)
        return self

    def predict(self, df):
        return self.model.predict(self._x(df)).clip(min=0)


class BySegment:
    def __init__(self, make, segment):
        self.make, self.segment = make, segment

    def fit(self, train):
        seg = self.segment(train)
        self.models = {s: self.make().fit(train[seg == s]) for s in np.unique(seg)}
        return self

    def predict(self, df):
        seg = self.segment(df)
        out = np.zeros(len(df))
        for s, model in self.models.items():
            rows = seg == s
            if rows.any():
                out[rows] = model.predict(df[rows])
        return out


def by_daytype(df):
    return np.where(df.daytype.values == 0, "weekday", "weekend")


def by_hours(df):
    h = df.hour.values
    return np.where(((h >= 6) & (h <= 10)) | ((h >= 16) & (h <= 20)), "peak", np.where((h >= 11) & (h <= 15), "day", "night"))


def by_route_group(df):
    return df.route.map(ROUTE_GROUPS).fillna("city").values


class LightGBMPool:
    def __init__(self, threads):
        make = partial(LightGBM, threads)
        self.members = [make(), BySegment(make, by_daytype), BySegment(make, by_hours), BySegment(make, by_route_group)]

    def fit(self, train):
        for m in self.members:
            m.fit(train)
        return self

    def predict(self, df):
        return np.mean([m.predict(df) for m in self.members], axis=0)


class CatBoost:
    def __init__(self, threads):
        self.params = {**CAT_PARAMS, "thread_count": threads}

    @staticmethod
    def _x(df):
        x = df[FEATURES].copy()
        x["route"] = x.route.astype(str)
        return x

    def fit(self, train):
        train = train[train.weight > 0]
        self.model = cb.CatBoostRegressor(**self.params, verbose=False, allow_writing_files=False)
        self.model.fit(cb.Pool(self._x(train), train.target, weight=train.weight, cat_features=["route"]))
        return self

    def predict(self, df):
        return self.model.predict(self._x(df)).clip(min=0)
