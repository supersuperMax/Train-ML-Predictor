import csv
from datetime import date, timedelta

import numpy as np

STEPS = ("hour", "day", "month")


class Forecast:
    def __init__(self, routes, first_day, cube):
        self.routes = tuple(routes)
        self.first_day = first_day
        self.last_day = first_day + timedelta(days=cube.shape[1] - 1)
        self._route_index = {r: i for i, r in enumerate(self.routes)}
        self._cube = cube
        self._cube.setflags(write=False)

    @classmethod
    def load(cls, path):
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f, delimiter=";"))[1:]
        routes = sorted({int(r[0]) for r in rows})
        days = sorted({r[1] for r in rows})
        route_index = {r: i for i, r in enumerate(routes)}
        day_index = {d: i for i, d in enumerate(days)}
        cube = np.zeros((len(routes), len(days), 24), dtype=np.int32)
        for route, day, hour, value in rows:
            cube[route_index[int(route)], day_index[day], int(hour)] = int(float(value))
        return cls(routes, date.fromisoformat(days[0]), cube)

    def get(self, route=None, start=None, end=None, step="hour"):
        if step not in STEPS:
            raise ValueError(f"step должен быть одним из {STEPS}")
        routes = self.routes if route is None else (int(route),)
        unknown = [r for r in routes if r not in self._route_index]
        if unknown:
            raise ValueError(f"нет прогноза для маршрута {unknown[0]}; есть {self.routes}")
        start = self._day(start, self.first_day)
        end = self._day(end, self.last_day)
        if not self.first_day <= start <= end <= self.last_day:
            raise ValueError(f"период должен быть внутри {self.first_day} … {self.last_day}, start <= end")
        a, b = (start - self.first_day).days, (end - self.first_day).days + 1
        return [row for r in routes for row in self._rows(r, self._cube[self._route_index[r], a:b], start, step)]

    def total(self, start=None, end=None):
        return sum(row["boardings"] for row in self.get(None, start, end, "month"))

    @staticmethod
    def _day(value, default):
        if value is None:
            return default
        return value if isinstance(value, date) else date.fromisoformat(str(value))

    @staticmethod
    def _rows(route, block, start, step):
        days = [start + timedelta(days=i) for i in range(block.shape[0])]
        if step == "hour":
            return [{"route": route, "date": d.isoformat(), "hour": h, "boardings": int(block[i, h])}
                    for i, d in enumerate(days) for h in range(24)]
        daily = block.sum(axis=1)
        if step == "day":
            return [{"route": route, "date": d.isoformat(), "boardings": int(v)} for d, v in zip(days, daily)]
        months = {}
        for d, v in zip(days, daily):
            key = d.strftime("%Y-%m")
            months[key] = months.get(key, 0) + int(v)
        return [{"route": route, "month": m, "boardings": v} for m, v in months.items()]
