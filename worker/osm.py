"""Выгрузка трамвайных маршрутов из OpenStreetMap: остановки по порядку и трассы по рельсам.

    python -m worker osm        # → data/reference/osm_tram.geojson

Разовая команда: пайплайн в сеть не ходит, шаг geo читает готовый файл. Берутся relation route=tram (PTv2)
маршрутов FORECAST_ROUTES в границах Москвы: stop-узлы в порядке следования и пути с пустой ролью, склеенные в одну линию,
плюс вся сеть путей railway=tram (кроме депо): по ней geo ведёт отрезки, которых нет в relation, — например, разворотные кольца.
"""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from worker.config import Config

log = logging.getLogger(__name__)

ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
BBOX = (55.10, 36.75, 56.05, 38.02)  # юг, запад, север, восток — вся Москва вместе с Новой Москвой
STOP_ROLES = {"stop", "stop_entry_only", "stop_exit_only"}
FILE_NAME = "osm_tram.geojson"


def _fetch(routes) -> dict:
    refs, bbox = "|".join(str(r) for r in routes), ",".join(map(str, BBOX))
    query = (f'[out:json][timeout:180];rel["route"="tram"]["ref"~"^({refs})$"]({bbox})->.r;'
             f'.r out geom;node(r.r);out;way["railway"="tram"]["service"!="yard"]({bbox});out geom;')
    body = urllib.parse.urlencode({"data": query}).encode()
    error = None
    for attempt in range(3):
        for url in ENDPOINTS:  # overpass-api.de под нагрузкой периодически отвечает 504 — пробуем зеркало и повторяем
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "tram-forecast/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=200) as resp:
                    data = json.load(resp)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                error = e
                log.warning("Overpass %s: %s", url, e)
                continue
            if data.get("remark"):  # сервер оборвал запрос, ответ неполный
                error = data["remark"]
                log.warning("Overpass %s: %s", url, error)
                continue
            return data
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Overpass недоступен: {error}")


def _stitch(ways: list[list[tuple[float, float]]], label: str) -> list[tuple[float, float]]:
    """Пути relation по порядку → одна линия: каждый путь разворачивается так, чтобы начинаться там, где кончился предыдущий."""
    line: list[tuple[float, float]] = []
    for i, w in enumerate(ways):
        if not line:
            nxt = ways[i + 1] if i + 1 < len(ways) else None
            line = list(w[::-1] if nxt and w[0] in (nxt[0], nxt[-1]) else w)
            continue
        end = line[-1]
        if w[-1] == end:
            w = w[::-1]
        elif w[0] != end:
            near_last = (w[-1][0] - end[0]) ** 2 + (w[-1][1] - end[1]) ** 2 < (w[0][0] - end[0]) ** 2 + (w[0][1] - end[1]) ** 2
            w = w[::-1] if near_last else w
            log.warning("%s: разрыв трассы перед путём %d", label, i)
        line.extend(w[1:] if w[0] == end else w)
    return line


def build(data: dict) -> dict:
    """Ответ Overpass → GeoJSON: LineString трассы и Point остановок на каждый relation (direction — номер relation маршрута)
    и MultiLineString всей сети путей."""
    nodes = {e["id"]: e for e in data["elements"] if e["type"] == "node"}
    rels = sorted((e for e in data["elements"] if e["type"] == "relation"), key=lambda e: (int(e["tags"]["ref"]), e["id"]))
    features, directions = [], {}
    for rel in rels:
        tags, route = rel["tags"], int(rel["tags"]["ref"])
        direction = directions[route] = directions.get(route, -1) + 1
        ways = [[(p["lon"], p["lat"]) for p in m["geometry"]] for m in rel["members"]
                if m["type"] == "way" and m["role"] == "" and m.get("geometry")]
        if ways:
            coords = [[round(x, 6), round(y, 6)] for x, y in _stitch(ways, tags.get("name", str(route)))]
            features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                             "properties": {"kind": "track", "route": route, "direction": direction, "osm_id": rel["id"],
                                            "from": tags.get("from"), "to": tags.get("to")}})
        seq = 0
        for m in rel["members"]:
            node = nodes.get(m["ref"]) if m["type"] == "node" and m["role"] in STOP_ROLES else None
            if node is None:
                continue
            seq += 1
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [node["lon"], node["lat"]]},
                             "properties": {"kind": "stop", "route": route, "direction": direction, "seq": seq,
                                            "osm_id": node["id"], "name": node.get("tags", {}).get("name", "")}})
    rails = [[[round(p["lon"], 6), round(p["lat"], 6)] for p in e["geometry"]] for e in data["elements"]
             if e["type"] == "way" and e.get("tags", {}).get("railway") == "tram" and len(e.get("geometry") or []) > 1]
    if rails:
        features.append({"type": "Feature", "geometry": {"type": "MultiLineString", "coordinates": rails},
                         "properties": {"kind": "rails"}})
    return {"type": "FeatureCollection", "features": features}


def run(cfg: Config) -> dict:
    geo = build(_fetch(cfg.routes))
    cfg.reference_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.reference_dir / FILE_NAME
    path.write_text(json.dumps(geo, ensure_ascii=False), encoding="utf-8")
    kinds = [f["properties"] for f in geo["features"]]
    found = sorted({p["route"] for p in kinds if "route" in p})
    missing = sorted(set(cfg.routes) - set(found))
    if missing:
        log.warning("в OSM не найдены маршруты %s", missing)
    rails = next((f["geometry"]["coordinates"] for f in geo["features"] if f["properties"]["kind"] == "rails"), [])
    return {"file": str(path), "routes": found, "missing": missing, "tracks": sum(p["kind"] == "track" for p in kinds),
            "stops": sum(p["kind"] == "stop" for p in kinds), "rail_ways": len(rails)}
