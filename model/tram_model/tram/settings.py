import pandas as pd

ROUTES = [1, 5, 7, 11, 12, 17, 25, 26, 28, 50]
HORIZON = pd.date_range("2025-11-01", "2025-12-31")
HISTORY_END = pd.Timestamp("2025-10-31")
KEYS = ["route", "date", "hour"]

HOLIDAYS = pd.to_datetime([
    "2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05", "2025-01-06", "2025-01-07", "2025-01-08",
    "2025-02-23", "2025-03-08", "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-08", "2025-05-09",
    "2025-05-10", "2025-05-11", "2025-06-12", "2025-06-13", "2025-06-14", "2025-06-15", "2025-11-02", "2025-11-03",
    "2025-11-04", "2025-12-31", "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06",
    "2026-01-07", "2026-01-08",
])
WORKING_WEEKENDS = pd.to_datetime(["2025-11-01"])
SHORT_DAYS = pd.to_datetime(["2025-03-07", "2025-04-30", "2025-06-11", "2025-11-01"])
NEW_YEAR = pd.date_range("2025-01-01", "2025-01-08")
NEW_YEAR_EVE = pd.Timestamp("2025-12-31")
MOSCOW_LAT = 55.75
DAYLIGHT_FLOOR_DAY = pd.Timestamp("2025-01-15")

REGIMES = {"weekend_closed": 50, "weekend_reduced": 7}
REGIME_START = pd.Timestamp("2025-09-01")
REGIME_END = pd.Timestamp("2025-11-30")

SUMMER_MONTHS = [7, 8]
SUMMER_WEIGHT = 0.3
ANOMALY_THRESHOLD = 0.3
LEVEL_WEEKS = 4

LEVEL_K = 1.045
WEEKEND_K = 1.04

ROUTE5_START = pd.Timestamp("2025-12-16")
ROUTE5_WEEKDAY = 5500
ROUTE5_ANALOGS = [17, 25]
BRIDGE_DAYS = ["2025-12-29", "2025-12-30"]
BRIDGE_K = 0.90
FREE_NIGHT_FROM = pd.Timestamp("2025-12-31 20:00")

CALIBRATION_SKIP_DAYS = ["2025-12-29", "2025-12-30", "2025-12-31"]
_REST = [1, 7, 25, 26, 28, 50]
ROUTE_MONTH_K = {
    11: {17: 0.9627, 11: 0.9857, 12: 0.9857, **dict.fromkeys(_REST, 0.9885)},
    12: {17: 0.975, 11: 0.9936, 12: 0.9936, **dict.fromkeys(_REST, 0.9975)},
}
DAY_K = {"2025-11-01": 0.92}

LGB_PARAMS = dict(objective="l1", learning_rate=0.03, num_leaves=31, min_data_in_leaf=50, feature_fraction=0.9,
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, seed=42, verbose=-1)
LGB_ROUNDS = 378
CAT_PARAMS = dict(loss_function="MAE", depth=6, learning_rate=0.05, l2_leaf_reg=3, random_seed=42, iterations=1017)
