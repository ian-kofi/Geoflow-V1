"""Place search for the Place node's dropdown, using OpenStreetMap's Nominatim service.

Each result includes the place's OpenStreetMap id. Later nodes use that id to get exactly the
place the user picked, rather than searching for a name like "Tema" again and maybe getting
a different one.

Nominatim is free but asks for no more than one request a second, so every request goes
through _throttled_get, and answers are remembered so the same search isn't sent twice.
"""
import threading
import time
from functools import lru_cache

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {"User-Agent": "GeoFlowApp/1.0", "Accept-Language": "en"}
MIN_INTERVAL = 1.0      # seconds between requests, as Nominatim's rules ask
MAX_RESULTS = 8

_lock = threading.Lock()
_last_request = 0.0


def _throttled_get(params, url=NOMINATIM_URL):
    """Sends a request to Nominatim, waiting first if the last one was less than a second ago."""
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
    """Turns one Nominatim result into the place format the rest of GeoFlow uses."""
    address = item.get("address") or {}
    name = item.get("name") or item["display_name"].split(",")[0]
    kind = item.get("addresstype") or item.get("type") or item.get("category") or "place"
    bbox = item.get("boundingbox")
    return {
        "id": f"{item['osm_type'][0].upper()}{item['osm_id']}",   # like R12803764, the form osmnx expects
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
    """Up to 8 places matching the text, best match first. Fewer than 2 letters gives no results."""
    query = query.strip()
    if len(query) < 2:
        return []
    data = _throttled_get({"q": query, "format": "jsonv2", "addressdetails": 1,
                           "limit": MAX_RESULTS, "dedupe": 1})
    return [_to_place(item) for item in data if item.get("osm_type") and item.get("osm_id")]


@lru_cache(maxsize=256)
def enclosing_area(lat, lon):
    """The id (like "R123") and name of the smallest area around a point.

    Some towns, Tema and Kumasi for example, are only mapped as a single point. This finds the
    town or district area around that point instead. Nominatim's zoom 10 means roughly town
    level and 8 roughly district or county level, so we try 10 first, then 8.
    """
    for zoom in (10, 8):
        data = _throttled_get({"lat": lat, "lon": lon, "zoom": zoom, "format": "jsonv2"}, REVERSE_URL)
        if data.get("osm_type") in ("relation", "way") and data.get("osm_id"):
            return f"{data['osm_type'][0].upper()}{data['osm_id']}", data.get("display_name", "")
    return None, None
