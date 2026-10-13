"""Minimal Overpass client.

Used instead of osmnx's feature download because osmnx retries 429/504
responses indefinitely (a busy server can hang a node for 10+ minutes) and
fetches geometry as separate node lists. `out geom` returns coordinates inline,
and we race all public mirrors in parallel with hard timeouts: any single
mirror is often overloaded (HTTP 504 / timeouts), but rarely all at once.
"""
import os
import json
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import geopandas as gpd
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

HEADERS = {"User-Agent": "GeoFlowApp/1.0"}
OVERPASS_URLS = [u for u in [
    os.environ.get("GEOFLOW_OVERPASS_URL"),
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
] if u]
# Overpass schedules queries by their declared time budget, so small areas ask
# for less and get a slot sooner on a busy server.
SMALL_AREA_DEG2 = 0.5
SMALL_QUERY_TIMEOUT = 90
LARGE_QUERY_TIMEOUT = 180
RETRY_WAITS = (0, 10, 25)        # seconds before each round of parallel attempts
CACHE_DIR = os.path.join("cache", "overpass")
RETRYABLE_STATUS = (429, 502, 503, 504)


class OverpassBusy(RuntimeError):
    pass


def _selector(key, values):
    if values is True:
        return f'["{key}"]'
    return f'["{key}"~"^({"|".join(values)})$"]'


def build_query(tags, south, west, north, east, polygons=False):
    bbox = f"({south:.6f},{west:.6f},{north:.6f},{east:.6f})"
    area = abs(north - south) * abs(east - west)
    timeout = SMALL_QUERY_TIMEOUT if area <= SMALL_AREA_DEG2 else LARGE_QUERY_TIMEOUT
    parts = []
    for key, values in tags.items():
        sel = _selector(key, values)
        parts.append(f"way{sel}{bbox};")
        if polygons:
            parts.append(f'relation{sel}["type"="multipolygon"]{bbox};')
    # qt = unsorted output, which is cheaper for the server to produce.
    return f"[out:json][timeout:{timeout}];({''.join(parts)});out geom qt;", timeout


def _attempt(url, query, timeout):
    """One request. Returns ('ok', data) | ('busy', reason) | ('heavy', reason) | ('error', reason)."""
    host = url.split("/")[2]
    started = time.time()
    try:
        response = requests.post(url, data={"data": query}, headers=HEADERS, timeout=(10, timeout + 30))
    except requests.RequestException as e:
        return "busy", f"{host}: {type(e).__name__}"
    if response.status_code in RETRYABLE_STATUS:
        return "busy", f"{host}: HTTP {response.status_code}"
    if response.status_code != 200:
        return "error", f"{host}: HTTP {response.status_code} {response.text[:200]}"
    try:
        data = response.json()
    except ValueError:
        return "busy", f"{host}: invalid response"
    remark = data.get("remark", "")
    if "runtime error" in remark:
        return "heavy", remark.split(":", 1)[-1].strip()[:120]
    print(f"Overpass: {len(data.get('elements', []))} elements from {host} in {time.time() - started:.1f}s")
    return "ok", data


def _post(query, timeout):
    cache_path = os.path.join(CACHE_DIR, hashlib.sha1(query.encode()).hexdigest() + ".json")
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)

    errors, heavy = [], []
    for round_no, wait in enumerate(RETRY_WAITS, start=1):
        if wait:
            print(f"Overpass busy; retrying in {wait}s (round {round_no}/{len(RETRY_WAITS)})")
            time.sleep(wait)
        errors.clear()
        # Not a `with` block: leaving it would wait for the slower mirrors to finish too.
        pool = ThreadPoolExecutor(max_workers=len(OVERPASS_URLS))
        try:
            futures = [pool.submit(_attempt, url, query, timeout) for url in OVERPASS_URLS]
            for future in as_completed(futures):
                status, payload = future.result()
                if status == "ok":
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(payload, f)
                    return payload
                if status == "error":
                    raise RuntimeError(f"Overpass rejected the query ({payload})")
                (heavy if status == "heavy" else errors).append(payload)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if heavy and len(heavy) + len(errors) == len(OVERPASS_URLS) and len(heavy) >= 2:
            raise RuntimeError(f"Overpass could not finish the query for this area ({heavy[0]}). "
                               "Try a smaller area or a lighter layer such as highways.")

    raise OverpassBusy("OpenStreetMap Overpass servers are all busy right now "
                       f"({'; '.join(errors)}). Try again in a few minutes.")


def _relation_polygon(element):
    outers = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
              for m in element.get("members", [])
              if m.get("role") == "outer" and len(m.get("geometry") or []) >= 2]
    inners = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
              for m in element.get("members", [])
              if m.get("role") == "inner" and len(m.get("geometry") or []) >= 2]
    if not outers:
        return None
    shell = unary_union(list(polygonize(outers)))
    if inners:
        shell = shell.difference(unary_union(list(polygonize(inners))))
    return None if shell.is_empty else shell


def fetch_features(tags, south, north, west, east, polygons=False, keep=()):
    """Returns a GeoDataFrame (EPSG:4326) of ways/multipolygons matching `tags` in the bbox."""
    data = _post(*build_query(tags, south, west, north, east, polygons))
    rows = []
    for el in data.get("elements", []):
        geom = None
        if el["type"] == "way" and len(el.get("geometry") or []) >= 2:
            coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
            if polygons:
                if len(coords) >= 4 and coords[0] == coords[-1]:
                    geom = Polygon(coords)
            else:
                geom = LineString(coords)
        elif el["type"] == "relation" and polygons:
            geom = _relation_polygon(el)
        if geom is None or geom.is_empty:
            continue
        el_tags = el.get("tags", {})
        rows.append({**{k: el_tags.get(k) for k in keep}, "geometry": geom})

    if not rows:
        return gpd.GeoDataFrame({k: [] for k in keep}, geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
