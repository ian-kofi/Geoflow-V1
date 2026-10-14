"""Cuts satellite imagery to the shape of an outline.

Used in two places: the Satellite Photo node's picture (clip_satellite), and the zoomable
satellite layer on the map, which asks for one tile at a time (clipped_tile). Anything outside
the outline becomes transparent.

Everything here works in Web Mercator (EPSG:3857), the projection web maps use. The tiles are
already in it, so each pixel is an equal step in metres and the maths stays simple.
"""
import io
import math
import os
from functools import lru_cache

import numpy as np
import geopandas as gpd
import shapely
from PIL import Image
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from shapely.geometry import box
from shapely.ops import unary_union
from shapely.prepared import prep

from compositor import EARTH_RADIUS, _to_mercator, lonlat_to_mercator
from satellite_fetcher import TILE_SIZE, _fetch_tile

HALF_WORLD = math.pi * EARTH_RADIUS   # distance from the map's centre to its edge, in metres
TILE_CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}   # browsers may keep tiles a week


def _empty_png():
    """A fully transparent tile, sent for tiles that are completely outside the outline."""
    buffer = io.BytesIO()
    Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0)).save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


EMPTY_TILE = _empty_png()


def mercator_to_lonlat(x, y):
    """Web Mercator metres back to longitude and latitude."""
    return math.degrees(x / EARTH_RADIUS), math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2)


@lru_cache(maxsize=16)
def _load_boundary(path, mtime):
    """Reads an outline file. `mtime` is only there so the cache notices when the file changes."""
    gdf = _to_mercator(gpd.read_file(path))
    # Merge regions into one shape, so the borders between them don't show as thin gaps.
    geom = unary_union(gdf.geometry.make_valid())
    return geom, prep(geom)


def boundary_shape(path):
    """The outline as one shape in Web Mercator, plus a "prepared" copy for fast overlap tests.

    The map asks for many tiles in a row, so the outline is kept in memory until its file changes.
    """
    return _load_boundary(path, os.path.getmtime(path))


def _mask(geom, bounds, width, height):
    """A grid of True and False, the size of the picture, saying which pixels are inside the outline."""
    minx, miny, maxx, maxy = bounds
    part = shapely.clip_by_rect(geom, minx, miny, maxx, maxy)
    if part.is_empty:
        return np.zeros((height, width), dtype=bool)
    transform = from_bounds(minx, miny, maxx, maxy, width, height)
    return rasterize([(part, 1)], out_shape=(height, width), transform=transform,
                     fill=0, dtype=np.uint8).astype(bool)


def clip_satellite(image_path, sat_bounds, boundary_path, tag=""):
    """Cuts the stitched satellite picture to the outline and trims off the empty edges.

    Returns the new picture's file name (a WebP, transparent outside the outline) and the
    area it now covers, as [south, north, west, east].
    """
    south, north, west, east = (float(v) for v in sat_bounds)
    x0, y0 = lonlat_to_mercator(west, south)
    x1, y1 = lonlat_to_mercator(east, north)

    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    geom, _ = boundary_shape(boundary_path)
    mask = _mask(geom, (x0, y0, x1, y1), width, height)
    if not mask.any():
        raise ValueError("The boundary does not overlap the satellite image")

    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1

    rgb = np.asarray(img)[r0:r1, c0:c1]
    alpha = (mask[r0:r1, c0:c1] * 255).astype(np.uint8)
    clipped = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")

    output_filename = f"satellite_{tag}_clipped.webp" if tag else "satellite_clipped.webp"
    # WebP keeps the transparency, and for photos it's a fraction of the size of a PNG.
    clipped.save(os.path.join("outputs", output_filename), "WEBP", quality=88, method=4)

    px_w, px_h = (x1 - x0) / width, (y1 - y0) / height
    new_west, new_north = mercator_to_lonlat(x0 + c0 * px_w, y1 - r0 * px_h)
    new_east, new_south = mercator_to_lonlat(x0 + c1 * px_w, y1 - r1 * px_h)
    print(f"Satellite clipped to boundary: {output_filename} ({c1 - c0}x{r1 - r0})")
    return output_filename, [new_south, new_north, new_west, new_east]


def clipped_tile(z, x, y, boundary_path):
    """One map tile cut to the outline. Returns the image bytes and their type.

    Tiles completely outside the outline come back empty without downloading anything, and
    tiles completely inside are sent as they are. Only tiles on the edge need cutting.
    """
    geom, prepared = boundary_shape(boundary_path)
    size = 2 * HALF_WORLD / 2 ** z
    minx = -HALF_WORLD + x * size
    maxy = HALF_WORLD - y * size
    bounds = (minx, maxy - size, minx + size, maxy)
    tile_box = box(*bounds)

    if not prepared.intersects(tile_box):
        return EMPTY_TILE, "image/png"
    tile = _fetch_tile(z, x, y)
    if tile is None:
        return EMPTY_TILE, "image/png"

    buffer = io.BytesIO()
    if prepared.contains(tile_box):
        tile.save(buffer, "JPEG", quality=90)        # all inside, so nothing to cut
        return buffer.getvalue(), "image/jpeg"

    mask = _mask(geom, bounds, tile.width, tile.height)
    rgba = np.dstack([np.asarray(tile), (mask * 255).astype(np.uint8)])
    Image.fromarray(rgba, "RGBA").save(buffer, "PNG")
    return buffer.getvalue(), "image/png"
