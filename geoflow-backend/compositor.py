"""Burns boundaries and vector layers onto a satellite background.

Everything is done in Web Mercator (EPSG:3857): satellite tiles are Mercator
images, so interpolating them linearly in latitude (as a plain lon/lat
transform would) misaligns vectors and imagery by many pixels at country scale.
"""
import os
import math

import numpy as np
import geopandas as gpd
from PIL import Image
from rasterio.transform import from_bounds
from rasterio.features import rasterize as rio_rasterize
from scipy.ndimage import binary_dilation

from plotting import LAYER_COLORS

EARTH_RADIUS = 6378137.0
MAX_LAT = 85.05112878
MAX_SIZE = 2048
PADDING = 0.03

BACKGROUND = np.array([11, 15, 26], dtype=np.float32) / 255.0
INSIDE_FILL = np.array([26, 37, 71], dtype=np.float32) / 255.0
BOUNDARY_COLOR = np.array([0.67, 0.23, 1.0], dtype=np.float32)
OUTSIDE_DIM = 0.4

_EXTENT = getattr(Image, "Transform", Image).EXTENT
_BICUBIC = getattr(Image, "Resampling", Image).BICUBIC


def _hex_to_rgb(color):
    color = color.lstrip("#")
    return np.array([int(color[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


OVERLAY_COLORS = {name: _hex_to_rgb(c) for name, c in LAYER_COLORS.items()}


def lonlat_to_mercator(lon, lat):
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    return (EARTH_RADIUS * math.radians(lon),
            EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _to_mercator(gdf):
    gdf = gdf.to_crs(epsg=4326)
    gdf = gdf.set_geometry(gdf.geometry.clip_by_rect(-180, -MAX_LAT, 180, MAX_LAT))
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    return gdf.to_crs(epsg=3857)


def _burn(geoms, shape, transform, all_touched=False):
    shapes = [(g, 1) for g in geoms if g is not None and not g.is_empty]
    if not shapes:
        return np.zeros(shape, dtype=bool)
    return rio_rasterize(shapes, out_shape=shape, transform=transform, fill=0,
                         dtype=np.uint8, all_touched=all_touched).astype(bool)


def _load_background(path, sat_bounds, extent, size):
    minx, miny, maxx, maxy = extent
    width, height = size
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        # Clipped imagery: flatten transparent areas onto the background colour.
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, tuple(int(c * 255) for c in BACKGROUND))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        img = flat
    else:
        img = img.convert("RGB")
    img_w, img_h = img.size

    if sat_bounds:
        south, north, west, east = (float(v) for v in sat_bounds)
        src_x0, src_y0 = lonlat_to_mercator(west, south)
        src_x1, src_y1 = lonlat_to_mercator(east, north)
    else:
        src_x0, src_y0, src_x1, src_y1 = minx, miny, maxx, maxy

    # Source pixel window that corresponds to the output extent (may extend past the image).
    px0 = (minx - src_x0) / (src_x1 - src_x0) * img_w
    px1 = (maxx - src_x0) / (src_x1 - src_x0) * img_w
    py0 = (src_y1 - maxy) / (src_y1 - src_y0) * img_h
    py1 = (src_y1 - miny) / (src_y1 - src_y0) * img_h

    # Box-filter down first when shrinking a lot; a bicubic transform alone would alias.
    factor = int(min((px1 - px0) / width, (py1 - py0) / height))
    if factor >= 2:
        img = img.reduce(factor)
        px0, px1, py0, py1 = px0 / factor, px1 / factor, py0 / factor, py1 / factor

    fill = tuple(int(c * 255) for c in BACKGROUND)
    out = img.transform((width, height), _EXTENT, (px0, py0, px1, py1), resample=_BICUBIC, fillcolor=fill)
    return np.asarray(out, dtype=np.float32) / 255.0


def composite_geodata(base_geojson_path, overlay_data, alpha=0.6,
                      background_image_path=None, sat_bounds=None, tag="", max_size=MAX_SIZE):
    os.makedirs("outputs", exist_ok=True)
    output_filename = f"composite_{tag}.png" if tag else "composite.png"
    output_path = os.path.join("outputs", output_filename)
    alpha = max(0.0, min(1.0, float(alpha)))

    base_gdf = _to_mercator(gpd.read_file(base_geojson_path))
    if base_gdf.empty:
        raise ValueError("Base boundary has no usable geometry")

    minx, miny, maxx, maxy = base_gdf.total_bounds
    pad = PADDING * max(maxx - minx, maxy - miny)
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad

    # Keep the real aspect ratio instead of squashing into a square.
    span_x, span_y = maxx - minx, maxy - miny
    if span_x >= span_y:
        width, height = max_size, max(1, round(max_size * span_y / span_x))
    else:
        width, height = max(1, round(max_size * span_x / span_y)), max_size
    shape = (height, width)
    transform = from_bounds(west=minx, south=miny, east=maxx, north=maxy, width=width, height=height)

    has_background = bool(background_image_path and os.path.exists(background_image_path))
    if has_background:
        composite = _load_background(background_image_path, sat_bounds, (minx, miny, maxx, maxy), (width, height))
    else:
        composite = np.empty((height, width, 3), dtype=np.float32)
        composite[:] = BACKGROUND

    inside = _burn(base_gdf.geometry, shape, transform)
    if has_background:
        composite[~inside] *= OUTSIDE_DIM          # spotlight the area of interest
    else:
        composite[inside] = INSIDE_FILL

    for overlay in overlay_data:
        path = overlay.get("path")
        layer_type = overlay.get("layer_type") or "default"
        if not path or not os.path.exists(path):
            continue
        try:
            gdf = _to_mercator(gpd.read_file(path))
            gdf = gdf.cx[minx:maxx, miny:maxy]
            if gdf.empty:
                continue
            # all_touched keeps thin lines continuous at country scale.
            burned = _burn(gdf.geometry, shape, transform, all_touched=layer_type != "buildings")
            color = OVERLAY_COLORS.get(layer_type, OVERLAY_COLORS["default"])
            composite[burned] = composite[burned] * (1 - alpha) + color * alpha
        except Exception as e:
            print(f"Error burning overlay {path}: {e}")

    line_width = max(1, round(max(width, height) / 1000))
    edge = _burn(base_gdf.geometry.boundary, shape, transform, all_touched=True)
    if line_width > 1:
        edge = binary_dilation(edge, iterations=line_width - 1)
    glow = binary_dilation(edge, iterations=line_width + 2) & ~edge
    composite[glow] = composite[glow] * 0.55 + BOUNDARY_COLOR * 0.45
    composite[edge] = BOUNDARY_COLOR

    Image.fromarray((np.clip(composite, 0, 1) * 255).astype(np.uint8)).save(output_path)
    print(f"Composite saved: {output_path} ({width}x{height})")
    return output_filename
