"""Microsoft Planetary Computer STAC search + Cloud Optimized GeoTIFF loading.

Scenes are read straight from the COGs (only the pixels inside the area, from
the coarsest overview that still meets the target resolution), reprojected to
the local UTM zone, cloud-masked, and mosaicked least-cloudy-first so gaps in
one scene are filled from the next.
"""
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlparse

import geopandas as gpd
import numpy as np
from affine import Affine
import rasterio
import requests
from rasterio.crs import CRS
from rasterio.features import geometry_mask
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .common import InputError
from .raster_io import Raster

SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
# Tokens are scoped to a blob storage account + container (not to a collection).
TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/{account}/{container}"
HEADERS = {"User-Agent": "GeoFlowApp/1.0"}
MAX_SIDE = 3000           # px; coarser resolution is used for bigger areas
MAX_OPTICAL_SCENES = 16   # median mode (small areas); the blue stack costs 2 bytes per pixel per scene
MAX_SEARCH_ITEMS = 1000
COVERAGE_MODE_TILES = 4   # areas spanning more satellite tiles than this use the coverage-first mosaic
COVERAGE_ROUNDS = 3       # …taking up to this many photos per tile to fill cloud gaps
SCENE_WORKERS = 8         # photos read at the same time in coverage mode
GAP_TOLERANCE = 0.01      # fill gaps automatically while more than 1% of the area is empty
GAP_FILL_CLOUD = 70       # cloud limit for gap-filling photos (their clouds are masked per pixel)
GAP_FILL_DAYS = 182       # how far back gap-filling may look
TOKEN_LIFETIME = 40 * 60  # SAS tokens last ~1 h; refresh well before

GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff,.TIF",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "1",
    "VSI_CACHE": "TRUE",
}

COLLECTIONS = {
    "sentinel-2-l2a": {
        "label": "Sentinel-2 L2A", "res": 10, "dated": True, "cloud": True, "max_items": 8, "optical": True,
        "bands": {"blue": "B02", "green": "B03", "red": "B04", "nir": "B08", "swir16": "B11", "swir22": "B12"},
        "mask": "SCL",
    },
    "landsat-c2-l2": {
        "label": "Landsat 8/9 Collection 2 L2", "res": 30, "dated": True, "cloud": True, "max_items": 8,
        "optical": True, "query": {"platform": {"in": ["landsat-8", "landsat-9"]}},
        "bands": {"blue": "blue", "green": "green", "red": "red", "nir": "nir08", "swir16": "swir16",
                  "swir22": "swir22"},
        "mask": "qa_pixel",
    },
    "cop-dem-glo-30": {
        "label": "Copernicus DEM 30 m", "res": 30, "dated": False, "cloud": False, "max_items": 16,
        "optical": False, "bands": {"elevation": "data"}, "mask": None,
    },
    # How often each 30 m cell was water, 1984–2021 (0 = never, 100 = always). 255 marks no data.
    "jrc-gsw": {
        "label": "Surface water history (JRC 1984–2021)", "res": 30, "dated": False, "cloud": False,
        "max_items": 8, "optical": False, "bands": {"occurrence": "occurrence"}, "mask": None, "nodata": 255,
    },
}

# Sentinel-2 scene classes to drop: no data, saturated, cloud shadow, cloud (medium/high), cirrus
S2_BAD_CLASSES = [0, 1, 3, 8, 9, 10]
# Landsat QA_PIXEL bits: fill, dilated cloud, cloud, cloud shadow
LANDSAT_BAD_BITS = (1 << 0) | (1 << 1) | (1 << 3) | (1 << 4)

_tokens = {}
_token_lock = threading.Lock()

# Dropped connections and temporary server errors are retried with back-off (search requests are
# read-only POSTs, so retrying them is safe).
_session = requests.Session()
_session.headers.update(HEADERS)
_session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=None)))


def _token(account, container):
    key = (account, container)
    with _token_lock:
        cached = _tokens.get(key)
        if cached and cached[1] > time.time():
            return cached[0]
        response = _session.get(TOKEN_URL.format(account=account, container=container), timeout=20)
        response.raise_for_status()
        token = response.json()["token"]
        _tokens[key] = (token, time.time() + TOKEN_LIFETIME)
        return token


def _sign(href):
    """Appends a read-only SAS token for the asset's storage account/container."""
    parsed = urlparse(href)
    if not parsed.netloc.endswith(".blob.core.windows.net"):
        return href
    account = parsed.netloc.split(".")[0]
    container = parsed.path.lstrip("/").split("/")[0]
    return f"{href}{'&' if parsed.query else '?'}{_token(account, container)}"


def _utm_crs(lon, lat):
    zone = min(60, int((lon + 180) // 6) + 1)
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def _search_pages(body):
    """All matching items, following the API's "next page" links (up to MAX_SEARCH_ITEMS)."""
    items, url, request = [], SEARCH_URL, body
    while url and len(items) < MAX_SEARCH_ITEMS:
        response = _session.post(url, json=request, timeout=60)
        response.raise_for_status()
        data = response.json()
        items += data.get("features", [])
        following = next((link for link in data.get("links", []) if link.get("rel") == "next"), None)
        url = following.get("href") if following else None
        request = {**body, **(following.get("body") or {})} if following else None
    return items


def search(collection, bounds, start, end, max_cloud):
    preset = COLLECTIONS[collection]
    south, north, west, east = bounds
    body = {"collections": [collection], "bbox": [west, south, east, north], "limit": 200}
    query = dict(preset.get("query", {}))
    if preset["dated"]:
        body["datetime"] = f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z"
    if preset["cloud"]:
        query["eo:cloud_cover"] = {"lt": max_cloud}
    if query:
        body["query"] = query
    if preset["cloud"]:
        body["sortby"] = [{"field": "eo:cloud_cover", "direction": "asc"}]   # clearest first, across pages
    try:
        items = _search_pages(body)
    except requests.RequestException as e:
        raise RuntimeError(f"Planetary Computer search failed: {e}")
    if not items:
        when = f" between {start} and {end}" if preset["dated"] else ""
        cloud = f" with under {max_cloud:.0f}% cloud" if preset["cloud"] else ""
        raise InputError(f"No {preset['label']} scenes found for this area{when}{cloud}. "
                         "Widen the date range or raise the cloud limit.")
    items.sort(key=lambda it: it["properties"].get("eo:cloud_cover", 0))
    return items


def _target_grid(bounds, native_res):
    south, north, west, east = bounds
    crs = _utm_crs((west + east) / 2, (south + north) / 2)
    minx, miny, maxx, maxy = transform_bounds(CRS.from_epsg(4326), crs, west, south, east, north, densify_pts=21)
    res = float(native_res)
    if max(maxx - minx, maxy - miny) / res > MAX_SIDE:
        res = max(maxx - minx, maxy - miny) / MAX_SIDE
    width = max(1, math.ceil((maxx - minx) / res))
    height = max(1, math.ceil((maxy - miny) / res))
    return crs, from_origin(minx, maxy, res, res), width, height, res


def _read(href, grid, resampling, default_nodata=0):
    """One asset warped onto the target grid, from the best-matching COG overview."""
    crs, transform, width, height, res = grid
    with rasterio.Env(**GDAL_ENV):
        with rasterio.open(href) as src:
            src_res = abs(src.res[0]) * (111_320 if src.crs and src.crs.is_geographic else 1)
            factors = src.overviews(1) or []
        level = None
        for i, factor in enumerate(factors):
            if factor * src_res <= res:
                level = i
        open_kwargs = {"overview_level": level} if level is not None else {}
        with rasterio.open(href, **open_kwargs) as src:
            nodata = src.nodata if src.nodata is not None else default_nodata
            with WarpedVRT(src, crs=crs, transform=transform, width=width, height=height, resampling=resampling,
                           src_nodata=nodata, nodata=np.nan, dtype="float32") as vrt:
                return vrt.read(1)


def _scale(collection, item, arr):
    props = item["properties"]
    if collection == "sentinel-2-l2a":
        offset = 1000 if float(props.get("s2:processing_baseline", "0") or 0) >= 4 else 0
        return (arr - offset) / 10_000
    if collection == "landsat-c2-l2":
        return arr * 0.0000275 - 0.2
    return arr


def _bad_pixels(collection, mask):
    if collection == "sentinel-2-l2a":
        return np.isnan(mask) | np.isin(mask, S2_BAD_CLASSES)
    if collection == "landsat-c2-l2":
        qa = np.nan_to_num(mask, nan=1).astype(np.uint32)
        return (qa & LANDSAT_BAD_BITS) > 0
    return np.zeros(mask.shape, dtype=bool)


def _read_assets(item, jobs, grid, nodata=0):
    """Reads several assets of one item in parallel. Returns {name: array} or None on failure.
    `nodata` is used for files that don't declare their own no-data value."""
    try:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {name: pool.submit(_read, _sign(item["assets"][asset]["href"]), grid, rs, nodata)
                       for name, (asset, rs) in jobs.items()}
            return {name: f.result() for name, f in futures.items()}
    except rasterio.errors.RasterioError as e:
        print(f"STAC: skipping {item['id']}: {e}")
        return None


def _load_mosaic(collection, preset, items, grid, resampling):
    """Elevation / surface-water tiles don't overlap: fill the grid tile by tile."""
    crs, transform, width, height, res = grid
    names = list(preset["bands"])
    out = np.full((len(names), height, width), np.nan, dtype=np.float32)
    used = []
    for item in items[: preset["max_items"]]:
        arrays = _read_assets(item, {n: (a, resampling) for n, a in preset["bands"].items()}, grid,
                              preset.get("nodata", 0))
        if arrays is None:
            continue
        take = np.isnan(out[0]) & np.isfinite(arrays[names[0]])
        if not take.any():
            continue
        for i, name in enumerate(names):
            out[i][take] = _scale(collection, item, arrays[name])[take]
        used.append(item)
        if not np.isnan(out[0]).any():
            break
    return out, used


def _load_median_composite(collection, preset, items, grid, resampling):
    """Cloud-free composite of optical scenes.

    Pass 1 reads only the blue band + cloud mask of every scene and picks, per
    pixel, the scene whose blue reflectance is the median of the clear
    observations: clouds the mask missed are too bright and their shadows too
    dark, so both are rejected. Pass 2 reads the remaining bands only from the
    scenes that were actually chosen.
    """
    crs, transform, width, height, res = grid
    names = list(preset["bands"])
    blue_asset = preset["bands"]["blue"]
    scenes, blues = [], []
    for item in items:
        jobs = {"blue": (blue_asset, resampling)}
        if preset["mask"] in item["assets"]:
            jobs["_mask"] = (preset["mask"], Resampling.nearest)
        arrays = _read_assets(item, jobs, grid)
        if arrays is None:
            continue
        blue = _scale(collection, item, arrays["blue"])
        if "_mask" in arrays:
            blue[_bad_pixels(collection, arrays["_mask"])] = np.nan
        if np.isfinite(blue).any():
            scenes.append(item)
            blues.append(blue.astype(np.float16))   # half precision: ample for reflectance, halves memory
    if not scenes:
        return None, []

    stack = np.stack(blues)
    del blues
    clear = np.isfinite(stack).any(axis=0)
    with np.errstate(all="ignore"):
        median = np.nanmedian(stack, axis=0)
        distance = np.abs(stack - median).astype(np.float32)
    distance[~np.isfinite(distance)] = np.inf
    choice = np.where(clear, np.argmin(distance, axis=0), -1)
    del distance

    out = np.full((len(names), height, width), np.nan, dtype=np.float32)
    used = []
    other = {n: (a, resampling) for n, a in preset["bands"].items() if n != "blue"}
    for index, item in enumerate(scenes):
        take = choice == index
        if not take.any():
            continue
        arrays = _read_assets(item, other, grid)
        if arrays is None:
            continue
        out[names.index("blue")][take] = stack[index][take]
        for name, arr in arrays.items():
            out[names.index(name)][take] = _scale(collection, item, arr)[take]
        used.append(item)
        print(f"STAC: {item['id']} supplied {100 * take.mean():.0f}% of pixels")
    return out, used


def _tile_of(item):
    props = item["properties"]
    return props.get("s2:mgrs_tile") or (props.get("landsat:wrs_path"), props.get("landsat:wrs_row"))


def _load_coverage_mosaic(collection, preset, items, grid, resampling, out=None, inside=None):
    """Large areas (whole countries): every satellite tile first gets its clearest photo,
    then cloud gaps are filled from each tile's next-clearest photo, round by round.
    Unlike the median composite this never runs out of photo budget on a few tiles.
    Pass `out` to only fill the gaps left in an existing mosaic."""
    crs, transform, width, height, res = grid
    names = list(preset["bands"])
    if out is not None:
        # Only tiles whose footprint still overlaps a gap are worth reading.
        gaps = _gaps(out, inside)
        items = [it for it in items if _footprint_has_gap(it, gaps, grid)]
    by_tile = {}
    for item in items:   # already clearest-first
        by_tile.setdefault(_tile_of(item), []).append(item)
    order = [scenes[r] for r in range(COVERAGE_ROUNDS) for scenes in by_tile.values() if len(scenes) > r]
    jobs = {n: (a, resampling) for n, a in preset["bands"].items()}
    if preset["mask"]:
        jobs["_mask"] = (preset["mask"], Resampling.nearest)

    if out is None:
        out = np.full((len(names), height, width), np.nan, dtype=np.float32)
    used = []
    print(f"STAC: {len(by_tile)} tiles, up to {len(order)} photos (coverage mode)")

    def read(item, window):
        # Only the part of the grid this photo covers (~1/30 of a country), not the whole grid.
        r0, r1, c0, c1 = window
        sub_grid = (crs, transform * Affine.translation(c0, r0), c1 - c0, r1 - r0, res)
        return _read_assets(item, {k: v for k, v in jobs.items() if v[0] in item["assets"]}, sub_grid)

    queue = list(order)
    while queue and _gap_share(out, inside) >= 0.002:
        # Next few photos that can still fill something (earlier ones may have filled their area).
        gaps = _gaps(out, inside)
        batch = []
        while queue and len(batch) < SCENE_WORKERS:
            item = queue.pop(0)
            window = _item_window(item, grid)
            if window and gaps[window[0]:window[1], window[2]:window[3]].any():
                batch.append((item, window))
        if not batch:
            break
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            results = list(pool.map(lambda job: read(*job), batch))
        for (item, (r0, r1, c0, c1)), arrays in zip(batch, results):   # applied in clearest-first order
            if arrays is None or names[0] not in arrays:
                continue
            valid = np.isfinite(arrays[names[0]])
            if "_mask" in arrays:
                valid &= ~_bad_pixels(collection, arrays["_mask"])
            target = out[:, r0:r1, c0:c1]          # a view: writes go straight into `out`
            take = np.isnan(target[0]) & valid
            if not take.any():
                continue
            for i, name in enumerate(names):
                target[i][take] = _scale(collection, item, arrays[name])[take]
            used.append(item)
    return out, used


def _item_window(item, grid):
    """(row0, row1, col0, col1) of the grid covered by a photo's bounding box, or None."""
    crs, transform, width, height, res = grid
    west, south, east, north = item["bbox"]
    minx, miny, maxx, maxy = transform_bounds(CRS.from_epsg(4326), crs, west, south, east, north)
    c0, c1 = max(int((minx - transform.c) / res), 0), min(int((maxx - transform.c) / res) + 1, width)
    r0, r1 = max(int((transform.f - maxy) / res), 0), min(int((transform.f - miny) / res) + 1, height)
    return (r0, r1, c0, c1) if r1 > r0 and c1 > c0 else None


def _area_mask(area, grid):
    """Pixels inside the area of interest (the connected outline); everything when there is none."""
    crs, transform, width, height, res = grid
    if area is None:
        return np.ones((height, width), dtype=bool)
    shapes = gpd.GeoSeries([area], crs="EPSG:4326").to_crs(crs)
    return geometry_mask(shapes, out_shape=(height, width), transform=transform, invert=True, all_touched=True)


def _gaps(out, inside):
    """Still-empty pixels that matter (inside the area of interest)."""
    return np.isnan(out[0]) & (inside if inside is not None else True)


def _gap_share(out, inside):
    total = inside.sum() if inside is not None else out[0].size
    return float(_gaps(out, inside).sum()) / max(int(total), 1)


def _footprint_has_gap(item, gaps, grid):
    """True if the photo's bounding box covers any still-empty pixel that matters."""
    window = _item_window(item, grid)
    return bool(window and gaps[window[0]:window[1], window[2]:window[3]].any())


def _fill_gaps(collection, preset, bounds, start, end, max_cloud, out, grid, resampling, used, inside=None):
    """Fills cloud gaps automatically: first cloudier photos from the same dates (their clouds
    are masked out pixel by pixel), then photos from up to 6 months earlier. Returns notes."""
    notes = []
    seen = {it["id"] for it in used}
    passes = [(start, end, max(max_cloud, GAP_FILL_CLOUD), f"cloudier photos (up to {GAP_FILL_CLOUD}% cloud; clouds masked out)"),
              (start - timedelta(days=GAP_FILL_DAYS), end, max(max_cloud, GAP_FILL_CLOUD),
               f"photos from up to {GAP_FILL_DAYS // 30} months earlier")]
    for pass_start, pass_end, cloud, description in passes:
        if _gap_share(out, inside) < GAP_TOLERANCE:
            break
        try:
            extra = [it for it in search(collection, bounds, pass_start, pass_end, cloud) if it["id"] not in seen]
        except InputError:
            continue
        before = _gap_share(out, inside)
        out, added = _load_coverage_mosaic(collection, preset, extra, grid, resampling, out=out, inside=inside)
        if added:
            used += added
            seen.update(it["id"] for it in added)
            notes.append(f"{(before - _gap_share(out, inside)) * 100:.0f}% of the area filled with {description}")
    return out, notes


def _per_tile(items, per_tile, cap):
    """Least-cloudy scenes for *each* satellite tile/path, so an area spanning two
    tiles isn't left with gaps because one tile hogged the scene budget."""
    counts, chosen = {}, []
    for item in items:   # already sorted by cloud cover
        props = item["properties"]
        tile = props.get("s2:mgrs_tile") or (props.get("landsat:wrs_path"), props.get("landsat:wrs_row"))
        if counts.get(tile, 0) < per_tile:
            counts[tile] = counts.get(tile, 0) + 1
            chosen.append(item)
        if len(chosen) >= cap:
            break
    return chosen


def load(collection, bounds, start, end, max_cloud, area=None):
    """Returns (Raster, details, is_optical) — a cloud-free mosaic over `bounds` ([s, n, w, e])."""
    preset = COLLECTIONS[collection]
    items = [it for it in search(collection, bounds, start, end, max_cloud)
             if all(asset in it["assets"] for asset in preset["bands"].values())]
    grid = _target_grid(bounds, preset["res"])
    inside = _area_mask(area, grid)
    crs, transform, width, height, res = grid
    names = list(preset["bands"])
    resampling = Resampling.average if res > preset["res"] * 1.5 else Resampling.bilinear

    method = None
    if preset["optical"] and len({_tile_of(it) for it in items}) > COVERAGE_MODE_TILES:
        out, used = _load_coverage_mosaic(collection, preset, items, grid, resampling, inside=inside)
        method = "Clearest photo for each part of the area, cloud gaps filled from the next clearest"
    elif preset["optical"]:
        items = _per_tile(items, per_tile=preset["max_items"], cap=MAX_OPTICAL_SCENES)
        out, used = _load_median_composite(collection, preset, items, grid, resampling)
        method = "Median of the clearest photos (removes clouds and shadows)"
    else:
        out, used = _load_mosaic(collection, preset, items, grid, resampling)

    fill_notes = []
    if preset["optical"] and _gap_share(out, inside) >= GAP_TOLERANCE:
        out, fill_notes = _fill_gaps(collection, preset, bounds, start, end, max_cloud, out, grid, resampling, used,
                                     inside)

    if not used:
        raise InputError(f"{preset['label']} scenes were found, but none had clear pixels over this area. "
                         "Try a wider date range.")

    details = {"Collection": preset["label"], "Scenes used": str(len(used))}
    if preset["dated"]:
        dates = sorted({it["properties"]["datetime"][:10] for it in used})
        details["Dates"] = ", ".join(dates) if len(dates) <= 6 else f"{dates[0]} to {dates[-1]} ({len(dates)} days)"
    if preset["cloud"]:
        clouds = [it["properties"].get("eo:cloud_cover", 0) for it in used]
        details["Cloud cover"] = (", ".join(f"{c:.0f}%" for c in clouds) if len(clouds) <= 6
                                  else f"{min(clouds):.0f}–{max(clouds):.0f}% per photo")
    if method:
        details["Method"] = method
        if fill_notes:
            details["Gaps filled"] = "; ".join(fill_notes)
        missing = _gap_share(out, inside) * 100
        if missing >= 2:
            details["Note"] = (f"{missing:.0f}% of the area still had no cloud-free view. "
                               "Try a drier season or a longer date range.")
    return Raster(out, crs, transform, names), details, preset["optical"]
