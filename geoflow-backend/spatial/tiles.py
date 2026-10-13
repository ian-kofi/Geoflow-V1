"""On-demand map tiles for raster results.

A single preview image goes soft as soon as the map zooms past its pixels.
Instead, each 256 px Web Mercator tile is rendered from the GeoTIFF when the
map asks for it: zoomed out it reads a small overview level; zoomed in past the
data's own resolution it interpolates bicubically (smooth instead of blocky),
and hillshade relief is recomputed at the tile's own scale so it stays crisp.
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
PAD = 2                       # extra pixels so hillshade/interpolation have neighbours at tile edges
HALF_WORLD = math.pi * EARTH_RADIUS
MERCATOR = CRS.from_epsg(3857)
CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}


def _empty_png():
    buffer = io.BytesIO()
    Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0)).save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


EMPTY_TILE = _empty_png()


@lru_cache(maxsize=128)
def _load_style(path, mtime):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _mercator_lat(y):
    return math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2)


def render_tile(style_path, z, x, y, safe_path):
    style = _load_style(style_path, os.path.getmtime(style_path))
    raster_path = safe_path(style.get("rasterPath"))
    if not raster_path:
        return EMPTY_TILE

    span = 2 * HALF_WORLD / 2 ** z
    minx, maxy = -HALF_WORLD + x * span, HALF_WORLD - y * span
    bounds = style.get("mercatorBounds")
    if bounds and (minx > bounds[2] or minx + span < bounds[0] or maxy < bounds[1] or maxy - span > bounds[3]):
        return EMPTY_TILE

    res = span / TILE_SIZE
    size = TILE_SIZE + 2 * PAD
    transform = from_origin(minx - PAD * res, maxy + PAD * res, res, res)
    latitude = _mercator_lat(maxy - span / 2)
    ground_res = res * math.cos(math.radians(latitude))   # metres on the ground per tile pixel
    categorical = style["mode"] == "categorical"
    bands = [b + 1 for b in style["bands"]]

    with rasterio.open(raster_path) as src:
        native = abs(src.res[0]) * (111_320 if src.crs and src.crs.is_geographic else 1)
        level = None
        for i, factor in enumerate(src.overviews(1) or []):
            if factor * native <= ground_res:
                level = i
    if categorical:
        resampling = Resampling.nearest
    elif ground_res < native:
        resampling = Resampling.cubic      # zoomed in past the data: smooth interpolation, no blocky pixels
    else:
        resampling = Resampling.average
    with rasterio.open(raster_path, **({"overview_level": level} if level is not None else {})) as src:
        with WarpedVRT(src, crs=MERCATOR, transform=transform, width=size, height=size, resampling=resampling,
                       src_nodata=src.nodata, nodata=np.nan, dtype="float32") as vrt:
            data = vrt.read(bands)

    shade = None
    if style.get("shade"):
        # Mercator pixels are 1/cos(lat) larger than on the ground; correct so slopes aren't flattened.
        tile_dem = Raster(data[0], MERCATOR, transform, ["z"])
        shade = terrain.hillshade(tile_dem, z_factor=1 / math.cos(math.radians(latitude)))[PAD:-PAD, PAD:-PAD]
    data = data[:, PAD:-PAD, PAD:-PAD]

    rgba = colorize(data, style, shade)
    if not rgba[..., 3].any():
        return EMPTY_TILE
    buffer = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buffer, "PNG", compress_level=3)
    return buffer.getvalue()
