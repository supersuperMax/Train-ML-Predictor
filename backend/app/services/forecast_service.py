from datetime import date, datetime, timedelta
from pathlib import Path
import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data"

class ForecastService:
    def __init__(self):
        self.df = self._load()

    def _load(self):
        path = DATA / "predictions.parquet"
        csv_path = DATA / "predictions.csv"
        if path.exists():
            df = pd.read_parquet(path)
        elif csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            df = pd.DataFrame(columns=["route", "date", "hour", "prediction"])
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def forecast(self, route=None, date_from=None, date_to=None):
        df = self.df
        if route is not None:
            df = df[df.route.astype(str) == str(route)]
        if date_from:
            df = df[df.date >= date.fromisoformat(date_from)]
        if date_to:
            df = df[df.date <= date.fromisoformat(date_to)]
        return df.to_dict(orient="records")

    def summary(self, route=None, date_from=None, date_to=None):
        rows = self.forecast(route, date_from, date_to)
        if not rows:
            return {"count": 0, "total": 0, "average": 0, "max": 0}
        values = [float(x["prediction"]) for x in rows]
        return {
            "count": len(values),
            "total": sum(values),
            "average": sum(values) / len(values),
            "max": max(values),
        }

service = ForecastService()
