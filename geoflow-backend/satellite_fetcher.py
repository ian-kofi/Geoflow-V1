"""Satellite photos for the Satellite Photo node.

The photo is made by downloading Esri World Imagery tiles (the same 256 pixel squares a web
map uses) for the area and stitching them into one picture. Tiles are kept in cache/tiles, so
running the same area again is almost instant.

Zoom works like on a web map: each step up doubles the detail and the number of tiles across.
"""
import os
import math
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from io import BytesIO

import requests
from requests.adapters import HTTPAdapter
from PIL import Image

TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
HEADERS = {"User-Agent": "GeoFlowApp/1.0"}
TILE_SIZE = 256
MAX_TILES_PER_SIDE = 24          # if the area needs more tiles than this, the zoom is lowered
MAX_LAT = 85.05112878            # web maps stop at this latitude
TILE_CACHE_DIR = os.path.join("cache", "tiles")
DOWNLOAD_WORKERS = 8             # Esri starts dropping connections if we ask for more at once
TILE_ATTEMPTS = 4
MISSING_TILE_COLOR = (11, 15, 26)   # dark blue for any tile that couldn't be downloaded

_session = requests.Session()
_session.headers.update(HEADERS)
_session.mount("https://", HTTPAdapter(pool_connections=DOWNLOAD_WORKERS, pool_maxsize=DOWNLOAD_WORKERS))


def lat_lon_to_tile(lat, lon, zoom):
    """The x and y number of the map tile containing a point, at a given zoom."""
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    lon = max(-180.0, min(180.0, lon))
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tile_to_lon_lat(x, y, zoom):
    """The longitude and latitude of a tile's top left corner."""
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_rad)
    return lon, lat


@lru_cache(maxsize=256)
def get_country_bounds(location):
    """The box around a place, as (south, north, west, east), from a Nominatim search.

    Only used when there's no outline to go on. Answers are remembered while the server runs.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": location, "format": "json", "limit": 1}
    response = _session.get(url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not data:
        raise ValueError(f"Location '{location}' not found")
    bbox = data[0]["boundingbox"]
    return float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])


def _tile_range(south, north, west, east, zoom):
    """The first and last tile numbers, across and down, that cover the box."""
    x_min, y_max = lat_lon_to_tile(south, west, zoom)
    x_max, y_min = lat_lon_to_tile(north, east, zoom)
    x_min, x_max = min(x_min, x_max), max(x_min, x_max)
    y_min, y_max = min(y_min, y_max), max(y_min, y_max)
    return x_min, x_max, y_min, y_max


def _fetch_tile(zoom, x, y):
    """Gets one tile as a picture, from the cache if we have it, otherwise from Esri.

    A busy server gets a few more tries, waiting a little longer each time. Returns None if
    the tile can't be had (for example, there's no imagery that far zoomed in).
    """
    cache_path = os.path.join(TILE_CACHE_DIR, str(zoom), str(x), f"{y}.img")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            content = f.read()
    else:
        content = None
        for attempt in range(TILE_ATTEMPTS):
            try:
                response = _session.get(TILE_URL.format(z=zoom, x=x, y=y), timeout=15)
                if response.status_code == 200 and response.content:
                    content = response.content
                    break
                if response.status_code not in (429, 500, 502, 503, 504):
                    return None
            except requests.RequestException as e:
                if attempt == TILE_ATTEMPTS - 1:
                    print(f"  Tile {x},{y} failed after {TILE_ATTEMPTS} attempts: {type(e).__name__}")
            time.sleep(0.4 * 2 ** attempt)
        if content is None:
            return None
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "wb") as f:
            f.write(content)
    try:
        return Image.open(BytesIO(content)).convert("RGB")
    except Exception as e:
        print(f"  Tile {x},{y} decode error: {e}")
        return None


def fetch_satellite(location, zoom=7, bounds=None, tag=""):
    """Makes one satellite picture of an area.

    bounds is the area as [south, north, west, east]. Without it, the place name is looked up.
    Returns the JPEG's file name in outputs/ and the exact area it covers, which is a bit
    bigger than asked for because whole tiles are used.
    """
    zoom = max(0, min(19, int(zoom)))
    print(f"Fetching satellite image for {location} at zoom {zoom}...")
    os.makedirs("outputs", exist_ok=True)
    output_filename = f"satellite_{tag}.jpg" if tag else "satellite.jpg"
    output_path = os.path.join("outputs", output_filename)

    if bounds is not None:
        south, north, west, east = (float(v) for v in bounds)
    else:
        south, north, west, east = get_country_bounds(location)

    # Add the same 3% margin Combine Layers uses, so its pictures have imagery right to the edge.
    pad = 0.03 * max(north - south, east - west)
    south, north, west, east = south - pad, north + pad, west - pad, east + pad

    # If the area needs too many tiles, step the zoom down until it fits. That's better than
    # quietly cutting part of the area off.
    requested_zoom = zoom
    x_min, x_max, y_min, y_max = _tile_range(south, north, west, east, zoom)
    while zoom > 0 and max(x_max - x_min, y_max - y_min) + 1 > MAX_TILES_PER_SIDE:
        zoom -= 1
        x_min, x_max, y_min, y_max = _tile_range(south, north, west, east, zoom)
    if zoom != requested_zoom:
        print(f"Area too large for zoom {requested_zoom}; using zoom {zoom}")

    num_x = x_max - x_min + 1
    num_y = y_max - y_min + 1
    coords = [(x, y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1)]
    print(f"Downloading {len(coords)} tiles ({num_x}x{num_y})...")

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        tiles = list(pool.map(lambda c: _fetch_tile(zoom, *c), coords))

    canvas = Image.new("RGB", (num_x * TILE_SIZE, num_y * TILE_SIZE), MISSING_TILE_COLOR)
    for (x, y), tile in zip(coords, tiles):
        if tile is not None:
            canvas.paste(tile, ((x - x_min) * TILE_SIZE, (y - y_min) * TILE_SIZE))

    canvas.save(output_path, quality=90)
    tile_west, tile_north = tile_to_lon_lat(x_min, y_min, zoom)
    tile_east, tile_south = tile_to_lon_lat(x_max + 1, y_max + 1, zoom)
    actual_bounds = [tile_south, tile_north, tile_west, tile_east]
    print(f"Satellite image saved: {output_path}")
    return output_filename, actual_bounds
