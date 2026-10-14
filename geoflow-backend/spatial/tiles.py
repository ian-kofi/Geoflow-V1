"""Map tiles for analysis results, drawn when the map asks for them.

A single preview picture turns blurry as soon as you zoom in past its pixels. So instead, the
map asks for 256 pixel tiles and each one is drawn from the saved GeoTIFF:
    zoomed out, a smaller copy stored inside the GeoTIFF (an "overview") is read, which is quick
    zoomed in past the data's own detail, values are smoothly interpolated rather than shown as
        big square blocks
    if the result has shaded relief, the shading is worked out again at the tile's own scale,
        so hills stay crisp at every zoom

How to colour a result is read from the style file saved next to it (see raster_io.save_style).
"""
import io
import json
import math
import os
from functools import lru_cache

import numpy as np
import rasterio
from PIL import Image
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

from . import terrain
from .raster_io import EARTH_RADIUS, Raster, colorize

TILE_SIZE = 256
PAD = 2                       # a few extra pixels round the edge, so shading has neighbours there too
HALF_WORLD = math.pi * EARTH_RADIUS
MERCATOR = CRS.from_epsg(3857)
CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}   # browsers may keep tiles a week


def _empty_png():
    """A fully transparent tile, for areas the result doesn't cover."""
    buffer = io.BytesIO()
    Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0)).save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


EMPTY_TILE = _empty_png()


@lru_cache(maxsize=128)
def _load_style(path, mtime):
    """Reads a style file. `mtime` makes the cache read it again after it changes."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _mercator_lat(y):
    """The latitude of a Web Mercator y coordinate."""
    return math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2)


def render_tile(style_path, z, x, y, safe_path):
    """Draws tile (z, x, y) of the result described by style_path. Returns PNG bytes."""
    style = _load_style(style_path, os.path.getmtime(style_path))
    raster_path = safe_path(style.get("rasterPath"))
    if not raster_path:
        return EMPTY_TILE

    span = 2 * HALF_WORLD / 2 ** z
    minx, maxy = -HALF_WORLD + x * span, HALF_WORLD - y * span
    bounds = style.get("mercatorBounds")
    # Nothing to draw if the tile doesn't overlap the result at all
    if bounds and (minx > bounds[2] or minx + span < bounds[0] or maxy < bounds[1] or maxy - span > bounds[3]):
        return EMPTY_TILE

    res = span / TILE_SIZE
    size = TILE_SIZE + 2 * PAD
    transform = from_origin(minx - PAD * res, maxy + PAD * res, res, res)
    latitude = _mercator_lat(maxy - span / 2)
    ground_res = res * math.cos(math.radians(latitude))   # metres on the ground per tile pixel
    categorical = style["mode"] == "categorical"
    bands = [b + 1 for b in style["bands"]]

    # Pick the smallest overview that still has at least as much detail as the tile needs
    with rasterio.open(raster_path) as src:
        native = abs(src.res[0]) * (111_320 if src.crs and src.crs.is_geographic else 1)
        level = None
        for i, factor in enumerate(src.overviews(1) or []):
            if factor * native <= ground_res:
                level = i
    if categorical:
        resampling = Resampling.nearest    # classes can't be blended, so take the nearest cell
    elif ground_res < native:
        resampling = Resampling.cubic      # zoomed in past the data, so blend smoothly between cells
    else:
        resampling = Resampling.average    # zoomed out, so average the cells under each pixel
    with rasterio.open(raster_path, **({"overview_level": level} if level is not None else {})) as src:
        with WarpedVRT(src, crs=MERCATOR, transform=transform, width=size, height=size, resampling=resampling,
                       src_nodata=src.nodata, nodata=np.nan, dtype="float32") as vrt:
            data = vrt.read(bands)

    shade = None
    if style.get("shade"):
        # Web Mercator stretches distances away from the equator, so tile pixels look bigger than
        # they are on the ground. Scaling the heights by the same amount keeps slopes correct.
        tile_dem = Raster(data[0], MERCATOR, transform, ["z"])
        shade = terrain.hillshade(tile_dem, z_factor=1 / math.cos(math.radians(latitude)))[PAD:-PAD, PAD:-PAD]
    data = data[:, PAD:-PAD, PAD:-PAD]

    rgba = colorize(data, style, shade)
    if not rgba[..., 3].any():
        return EMPTY_TILE
    buffer = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buffer, "PNG", compress_level=3)
    return buffer.getvalue()
