"""Place search for the Location node's dropdown (OpenStreetMap Nominatim).

Each result carries a unique OSM id, so downstream nodes can use the exact
place the user picked instead of re-geocoding an ambiguous name like "Tema".
"""
import threading
import time
from functools import lru_cache

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {"User-Agent": "GeoFlowApp/1.0", "Accept-Language": "en"}
MIN_INTERVAL = 1.0      # Nominatim usage policy: at most 1 request per second
MAX_RESULTS = 8

_lock = threading.Lock()
_last_request = 0.0


def _throttled_get(params, url=NOMINATIM_URL):
    global _last_request
    with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
    response = requests.get(url, params=params, headers=HEADERS, timeout=15)
    response.raise_for_status()
    return response.json()


def _to_place(item):
    address = item.get("address") or {}
    name = item.get("name") or item["display_name"].split(",")[0]
    kind = item.get("addresstype") or item.get("type") or item.get("category") or "place"
    bbox = item.get("boundingbox")
    return {
        "id": f"{item['osm_type'][0].upper()}{item['osm_id']}",   # e.g. R12803764, osmnx by_osmid format
        "osmType": item["osm_type"],
        "name": name,
        "displayName": item["display_name"],
        "kind": kind.replace("_", " "),
        "isCountry": kind == "country",
        "country": address.get("country"),
        "countryCode": (address.get("country_code") or "").upper() or None,
        "bbox": [float(v) for v in bbox] if bbox else None,          # [south, north, west, east]
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
    }


@lru_cache(maxsize=512)
def search_places(query):
    query = query.strip()
    if len(query) < 2:
        return []
    data = _throttled_get({"q": query, "format": "jsonv2", "addressdetails": 1,
                           "limit": MAX_RESULTS, "dedupe": 1})
    return [_to_place(item) for item in data if item.get("osm_type") and item.get("osm_id")]


@lru_cache(maxsize=256)
def enclosing_area(lat, lon):
    """OSM id ('R123') and name of the smallest area polygon containing a point.

    Many towns (e.g. Tema, Kumasi) are mapped only as a point; this finds their
    city or district outline instead. Zoom 10 ≈ city, 8 ≈ district/county.
    """
    for zoom in (10, 8):
        data = _throttled_get({"lat": lat, "lon": lon, "zoom": zoom, "format": "jsonv2"}, REVERSE_URL)
        if data.get("osm_type") in ("relation", "way") and data.get("osm_id"):
            return f"{data['osm_type'][0].upper()}{data['osm_id']}", data.get("display_name", "")
    return None, None
