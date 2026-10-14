"""Draws an outline and map features on top of a background picture, for the Combine Layers node.

The background can be a satellite photo or an analysis result. Roads, rivers and other
features are painted onto it pixel by pixel, each road with a thin dark edge so it stands out,
and the outline goes on last in purple.

Everything is done in Web Mercator (EPSG:3857), the projection the satellite tiles use. Doing
it in plain latitude and longitude would put the roads many pixels away from where they
appear on a country sized photo.
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
MAX_LAT = 85.05112878     # web maps stop at this latitude
MAX_SIZE = 2048           # longest side of the finished picture, in pixels
PADDING = 0.03            # margin around the outline, as a share of its size

# Colours are stored as 0 to 1 values so they can be blended with simple sums.
BACKGROUND = np.array([11, 15, 26], dtype=np.float32) / 255.0      # used when there's no background picture
INSIDE_FILL = np.array([26, 37, 71], dtype=np.float32) / 255.0     # fills the outline in that case
BOUNDARY_COLOR = np.array([0.67, 0.23, 1.0], dtype=np.float32)     # purple outline
CASING_COLOR = np.array([0.08, 0.08, 0.1], dtype=np.float32)       # dark edge along roads and rivers
PAGE = np.array([244, 244, 245], dtype=np.float32) / 255.0         # light grey around backgrounds already cut to the outline
OUTSIDE_DIM = 0.4         # how bright the photo stays outside the outline

# Pillow renamed these constants; this works with old and new versions
_EXTENT = getattr(Image, "Transform", Image).EXTENT
_BICUBIC = getattr(Image, "Resampling", Image).BICUBIC


def _hex_to_rgb(color):
    """'#facc15' to an array of three 0 to 1 values."""
    color = color.lstrip("#")
    return np.array([int(color[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


OVERLAY_COLORS = {name: _hex_to_rgb(c) for name, c in LAYER_COLORS.items()}


def lonlat_to_mercator(lon, lat):
    """Longitude and latitude to Web Mercator metres."""
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    return (EARTH_RADIUS * math.radians(lon),
            EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _to_mercator(gdf):
    """Reprojects shapes to Web Mercator, first trimming anything beyond the poles it can't show."""
    gdf = gdf.to_crs(epsg=4326)
    gdf = gdf.set_geometry(gdf.geometry.clip_by_rect(-180, -MAX_LAT, 180, MAX_LAT))
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    return gdf.to_crs(epsg=3857)


def _burn(geoms, shape, transform, all_touched=False):
    """A True and False grid marking the pixels the shapes cover.

    With all_touched, every pixel a line passes through counts, which keeps thin lines unbroken.
    """
    shapes = [(g, 1) for g in geoms if g is not None and not g.is_empty]
    if not shapes:
        return np.zeros(shape, dtype=bool)
    return rio_rasterize(shapes, out_shape=shape, transform=transform, fill=0,
                         dtype=np.uint8, all_touched=all_touched).astype(bool)


def _load_background(path, sat_bounds, extent, size):
    """Reads the background picture and stretches it to fit the output exactly.

    sat_bounds is the area the picture covers, extent the area the output should cover (in
    Web Mercator metres) and size the output's width and height in pixels. Returns the pixels
    as 0 to 1 values, and whether the picture was already cut to an outline.
    """
    minx, miny, maxx, maxy = extent
    width, height = size
    img = Image.open(path)
    clipped = img.mode in ("RGBA", "LA", "P")
    page = tuple(int(c * 255) for c in (PAGE if clipped else BACKGROUND))
    if clipped:
        # A picture that's already cut to an outline (or an analysis result) has see-through
        # surroundings. Put it on a light grey page instead.
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, page)
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

    # Which part of the source picture, in pixels, matches the output area. It can reach past
    # the picture's edges, and anything out there is filled with the page colour.
    px0 = (minx - src_x0) / (src_x1 - src_x0) * img_w
    px1 = (maxx - src_x0) / (src_x1 - src_x0) * img_w
    py0 = (src_y1 - maxy) / (src_y1 - src_y0) * img_h
    py1 = (src_y1 - miny) / (src_y1 - src_y0) * img_h

    # When shrinking a lot, average the pixels down first. Going straight to the final size
    # would make the picture look grainy and jagged.
    factor = int(min((px1 - px0) / width, (py1 - py0) / height))
    if factor >= 2:
        img = img.reduce(factor)
        px0, px1, py0, py1 = px0 / factor, px1 / factor, py0 / factor, py1 / factor

    out = img.transform((width, height), _EXTENT, (px0, py0, px1, py1), resample=_BICUBIC, fillcolor=page)
    return np.asarray(out, dtype=np.float32) / 255.0, clipped


def composite_geodata(base_geojson_path, overlay_data, alpha=0.6,
                      background_image_path=None, sat_bounds=None, tag="", max_size=MAX_SIZE):
    """Makes the Combine Layers picture and returns its file name in outputs/.

    base_geojson_path      the outline, which also sets the picture's area
    overlay_data           a list of {"path": GeoJSON file, "layer_type": "roads" and so on}
    alpha                  how strongly the features show, from 0 to 1
    background_image_path  the background picture, if any, and sat_bounds the area it covers
    """
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

    # Keep the area's real shape rather than squashing it into a square.
    span_x, span_y = maxx - minx, maxy - miny
    if span_x >= span_y:
        width, height = max_size, max(1, round(max_size * span_y / span_x))
    else:
        width, height = max(1, round(max_size * span_x / span_y)), max_size
    shape = (height, width)
    transform = from_bounds(west=minx, south=miny, east=maxx, north=maxy, width=width, height=height)

    has_background = bool(background_image_path and os.path.exists(background_image_path))
    clipped_background = False
    if has_background:
        composite, clipped_background = _load_background(background_image_path, sat_bounds,
                                                         (minx, miny, maxx, maxy), (width, height))
    else:
        composite = np.empty((height, width, 3), dtype=np.float32)
        composite[:] = BACKGROUND

    inside = _burn(base_gdf.geometry, shape, transform)
    if has_background and not clipped_background:
        composite[~inside] *= OUTSIDE_DIM          # darken outside the outline so the place stands out
    elif not has_background:
        composite[inside] = INSIDE_FILL
    casing_width = max(1, round(max(width, height) / 1400))

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
            # all_touched keeps thin lines unbroken on big maps, and combining with `inside` keeps
            # them within the outline.
            burned = _burn(gdf.geometry, shape, transform, all_touched=layer_type != "buildings") & inside
            color = OVERLAY_COLORS.get(layer_type, OVERLAY_COLORS["default"])
            if layer_type != "buildings":
                # A dark edge along each line, like on a road atlas, so it's easy to see on any background.
                casing = binary_dilation(burned, iterations=casing_width) & ~burned & inside
                composite[casing] = composite[casing] * (1 - 0.6 * alpha) + CASING_COLOR * 0.6 * alpha
            composite[burned] = composite[burned] * (1 - alpha) + color * alpha
        except Exception as e:
            print(f"Error burning overlay {path}: {e}")

    # The outline goes on last: a solid purple line with a soft glow either side of it.
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
