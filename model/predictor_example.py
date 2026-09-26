"""Пример модели в режиме plugin: переименуйте в predictor.py и задайте MODEL_MODE=plugin.

Простейшая «модель»: средние посадки маршрута по (тип дня, час) за всю историю.
Показывает контракт — модель другой команды заменит этот файл своим.
"""
import pandas as pd

NAME = "пример: средний профиль по типу дня"
MAX_DATE = "2026-12-31"


def _daytype(dates: pd.Series) -> pd.Series:
    dow = dates.dt.dayofweek
    return dow.map(lambda d: "sat" if d == 5 else "sun" if d == 6 else "weekday")


def predict(keys: pd.DataFrame, features: pd.DataFrame, history: pd.DataFrame):
    h = history.assign(daytype=_daytype(history["date"]))
    n_days = h.groupby(["route", "daytype"])["date"].nunique().rename("n").reset_index()
    profile = h.groupby(["route", "daytype", "hour"], as_index=False)["boardings"].sum().merge(n_days)
    profile["value"] = profile["boardings"] / profile["n"]

    # Праздники ходят по расписанию выходного дня.
    f = features[["route", "hour"]].assign(daytype=features["daytype"].replace({"holiday": "sun"}))
    out = f.merge(profile[["route", "daytype", "hour", "value"]], on=["route", "daytype", "hour"], how="left")
    return out["value"].fillna(0).to_numpy()
