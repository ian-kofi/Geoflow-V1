"""Rasters (grids of values such as heights or NDVI): reading, saving, lining up and previewing.

Every raster node finishes by calling raster_result, which does three things:
    1. saves the data as a GeoTIFF in files/rasters
    2. draws a coloured preview picture (WebP) in outputs/, plus its legend
    3. saves a small style file in files/styles saying how it was coloured, so map tiles
       drawn later (see tiles.py) look exactly the same as the preview
"""
import json
import math
import os
from dataclasses import dataclass

import numpy as np
import rasterio
from affine import Affine
from matplotlib import colormaps
from matplotlib.colors import to_hex
from PIL import Image
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform, reproject

from .common import InputError

RASTER_DIR = os.path.join("files", "rasters")
STYLE_DIR = os.path.join("files", "styles")
OUTPUT_DIR = "outputs"
LOW_MEMORY = os.environ.get("GEOFLOW_LOW_MEMORY") == "1"   # small servers, like the free 512 MB demo
MAX_PIXELS = 6_000_000 if LOW_MEMORY else 40_000_000   # per band; anything bigger has to be cut down first
PREVIEW_MAX = 2048             # longest side of preview pictures, in pixels
EARTH_RADIUS = 6378137.0
MAX_LAT = 85.05112878          # web maps stop at this latitude


@dataclass
class Raster:
    """A raster held in memory.

    data        the values, shaped (bands, rows, columns), as 32 bit floats. NaN means no data.
    crs         the coordinate system
    transform   where the grid sits: the top left corner and the size of each cell
    names       a name for each band, such as "elevation" or "nir"
    """
    data: np.ndarray
    crs: CRS
    transform: Affine
    names: list

    def __post_init__(self):
        self.crs = CRS.from_user_input(self.crs)
        if self.data.ndim == 2:
            self.data = self.data[None]   # a single band is stored with a bands dimension of 1

    @property
    def shape(self):
        """(rows, columns)."""
        return self.data.shape[1:]

    def bounds(self):
        """(west, south, east, north) in the raster's own coordinate system."""
        return array_bounds(*self.shape, self.transform)

    def band_index(self, name):
        """Position of the band with this name (any case), or None."""
        wanted = name.lower()
        return next((i for i, n in enumerate(self.names) if str(n).lower() == wanted), None)

    def band(self, name):
        """The values of the band with this name, or None."""
        i = self.band_index(name)
        return None if i is None else self.data[i]

    def with_data(self, data, names):
        """A new raster on the same grid with different values, for example slope worked out from a DEM."""
        return Raster(np.asarray(data, dtype=np.float32), self.crs, self.transform, list(names))


def read_raster(path):
    """Reads a raster file. No-data cells become NaN."""
    with rasterio.open(path) as src:
        if src.width * src.height > MAX_PIXELS:
            raise InputError(f"Raster is too large ({src.width}×{src.height} px). Clip it to a smaller area first.")
        data = src.read(out_dtype="float32", masked=True).filled(np.nan)
        names = [d or f"band{i + 1}" for i, d in enumerate(src.descriptions)]
        return Raster(data, src.crs or CRS.from_epsg(4326), src.transform, names)


def write_raster(raster, name, tag, dtype="float32"):
    """Saves a raster as a compressed GeoTIFF in files/rasters and returns the path.

    Use dtype "uint8" for classes (0 then means no data), otherwise values are saved as floats.
    """
    os.makedirs(RASTER_DIR, exist_ok=True)
    path = os.path.join(RASTER_DIR, f"{name}_{tag}.tif" if tag else f"{name}.tif")
    height, width = raster.shape
    if dtype == "uint8":
        nodata = 0
        out = np.where(np.isfinite(raster.data), raster.data, 0).astype(np.uint8)
    else:
        nodata = np.nan
        out = raster.data.astype(np.float32)
    profile = dict(driver="GTiff", height=height, width=width, count=out.shape[0], dtype=dtype,
                   crs=raster.crs, transform=raster.transform, nodata=nodata, compress="deflate",
                   predictor=3 if dtype == "float32" else 2, tiled=width >= 256 and height >= 256,
                   BIGTIFF="IF_SAFER")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(out)
        for i, band_name in enumerate(raster.names, start=1):
            dst.set_band_description(i, str(band_name))
        # Also store smaller copies (half size, quarter size and so on) inside the file. Map tiles
        # for a zoomed out view can then read one of those instead of every pixel.
        factors = [f for f in (2, 4, 8, 16, 32) if min(height, width) / f >= 64]
        if factors:
            dst.build_overviews(factors, Resampling.nearest if dtype == "uint8" else Resampling.average)
    return path


def same_grid(a, b):
    """True if both rasters have exactly the same cells."""
    return a.crs == b.crs and a.shape == b.shape and a.transform.almost_equals(b.transform)


def align_to(src, ref, resampling=Resampling.bilinear):
    """Moves `src` onto the same grid as `ref` (same coordinate system, area and cell size).

    Needed before comparing two rasters cell by cell, for example a slope and a water map
    that came from different sources.
    """
    if same_grid(src, ref):
        return src
    out = np.full((src.data.shape[0], *ref.shape), np.nan, dtype=np.float32)
    for i in range(src.data.shape[0]):
        reproject(source=src.data[i], destination=out[i], src_transform=src.transform, src_crs=src.crs,
                  dst_transform=ref.transform, dst_crs=ref.crs, src_nodata=np.nan, dst_nodata=np.nan,
                  resampling=resampling)
    return Raster(out, ref.crs, ref.transform, src.names)


def pixel_size_m(raster):
    """Cell width and height in metres, as (dx, dy).

    For a raster in latitude and longitude, a degree of longitude gets shorter away from the
    equator, so dx is then a column of values, one per row.
    """
    t = raster.transform
    if raster.crs.is_geographic:
        rows = np.arange(raster.shape[0]) + 0.5
        lat = np.radians(t.f + t.e * rows)
        return (abs(t.a) * 111_320.0 * np.cos(lat))[:, None], abs(t.e) * 110_540.0
    factor = raster.crs.linear_units_factor[1] if raster.crs.linear_units_factor else 1.0
    return abs(t.a) * factor, abs(t.e) * factor


def resolution_label(raster):
    """The cell size written for people, like "30.0 m"."""
    t = raster.transform
    if raster.crs.is_geographic:
        return f"{abs(t.a):.6f}° (~{abs(t.a) * 111_320:.0f} m)"
    return f"{abs(t.a):.1f} m"


def band_stats(arr):
    """Lowest, highest, mean and spread of a band, and the share of cells that have data."""
    values = arr[np.isfinite(arr)]
    if values.size == 0:
        return None
    return {"min": float(values.min()), "max": float(values.max()), "mean": float(values.mean()),
            "std": float(values.std()), "validPercent": round(100.0 * values.size / arr.size, 1)}


# Previews

def _mercator_to_lonlat(x, y):
    """Web Mercator metres to longitude and latitude."""
    return math.degrees(x / EARTH_RADIUS), math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2)


def _to_web_mercator(raster, bands, resampling):
    """Reprojects some bands to Web Mercator, the projection the map in the browser uses.

    The result is at most PREVIEW_MAX pixels on its longest side. Returns the values, the
    area covered as [south, north, west, east], and the same area in Mercator metres.
    """
    height, width = raster.shape
    west, south, east, north = raster.bounds()
    if raster.crs.is_geographic:
        south, north = max(south, -MAX_LAT), min(north, MAX_LAT)
    dst_crs = CRS.from_epsg(3857)
    transform, w2, h2 = calculate_default_transform(raster.crs, dst_crs, width, height, west, south, east, north)
    scale = max(w2, h2) / PREVIEW_MAX
    if scale > 1:
        new_w, new_h = max(1, round(w2 / scale)), max(1, round(h2 / scale))
        transform = transform * Affine.scale(w2 / new_w, h2 / new_h)
        w2, h2 = new_w, new_h
    out = np.full((len(bands), h2, w2), np.nan, dtype=np.float32)
    for i, b in enumerate(bands):
        reproject(source=raster.data[b], destination=out[i], src_transform=raster.transform, src_crs=raster.crs,
                  dst_transform=transform, dst_crs=dst_crs, src_nodata=np.nan, dst_nodata=np.nan,
                  resampling=resampling)
    left, bottom, right, top = array_bounds(h2, w2, transform)
    lon0, lat0 = _mercator_to_lonlat(left, bottom)
    lon1, lat1 = _mercator_to_lonlat(right, top)
    return out, [lat0, lat1, lon0, lon1], [left, bottom, right, top]


def _percentile_limits(arr, low=2, high=98):
    """The value range for colouring, ignoring the lowest and highest 2% so a few odd values
    don't wash out the rest."""
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return [0.0, 1.0]
    lo, hi = np.percentile(finite, [low, high])
    return [float(lo), float(hi)]


def _gradient(cmap, stops=8):
    """A few evenly spaced colours from a colour scale, for drawing it in the legend."""
    cm = colormaps[cmap]
    return [to_hex(cm(i / (stops - 1))) for i in range(stops)]


def category_colors(count, cmap="RdYlGn_r"):
    """`count` colours spread evenly along a colour scale, one per class."""
    cm = colormaps[cmap]
    return [to_hex(cm(0.5 if count == 1 else i / (count - 1))) for i in range(count)]


def _apply_shade(rgba, shade):
    """Darkens the colours where the hillshade is dark, so hills look three dimensional.

    shade runs from 0 to 255. Even the darkest slopes keep 35% of their colour.
    """
    factor = 0.35 + 0.65 * np.clip(np.nan_to_num(shade, nan=255) / 255.0, 0, 1)
    rgba[..., :3] = (rgba[..., :3] * factor[..., None]).astype(np.uint8)
    return rgba


def colorize(data, style, shade=None):
    """Turns values into coloured pixels (red, green, blue, transparency) following a style.

    Used for both previews and map tiles, so they always look the same. The style's mode is:
        "rgb"          three bands shown as a photo
        "categorical"  each class value gets its own colour
        "continuous"   one band coloured along a colour scale between vmin and vmax
    Cells with no data come out transparent.
    """
    mode = style["mode"]
    rgba = np.zeros((*data.shape[1:], 4), dtype=np.uint8)
    if mode == "rgb":
        for i, (lo, hi) in enumerate(style["rgbLimits"]):
            scaled = np.clip((data[i] - lo) / ((hi - lo) or 1), 0, 1)
            rgba[..., i] = (np.nan_to_num(scaled) ** 0.9 * 255).astype(np.uint8)
        rgba[..., 3] = np.where(np.all(np.isfinite(data[:3]), axis=0), 255, 0)
    elif mode == "categorical":
        values = np.round(data[0])
        for cat in style["categories"]:
            hex_color = cat["color"].lstrip("#")
            rgba[values == cat["value"]] = [int(hex_color[i:i + 2], 16) for i in (0, 2, 4)] + [255]
    else:
        vmin, vmax = style["vmin"], style["vmax"]
        norm = np.clip((data[0] - vmin) / ((vmax - vmin) or 1), 0, 1)
        rgba = colormaps[style["cmap"]](np.nan_to_num(norm), bytes=True)
        rgba[..., 3] = np.where(np.isfinite(data[0]), 255, 0)
    if shade is not None:
        rgba = _apply_shade(rgba, shade)
    return rgba


def render_preview(raster, name, tag, mode="continuous", cmap="viridis", vmin=None, vmax=None,
                   unit="", label="", rgb=("red", "green", "blue"), categories=None, band=0, shade=None):
    """Draws the preview picture (a WebP in Web Mercator, transparent where there's no data).

    Returns the file name, the area as [south, north, west, east], the legend and the style.
    The style records every colouring choice, including value ranges worked out here, so map
    tiles drawn later look exactly the same.

    band    which band to show (not used for photos)
    shade   optional hillshade on the same grid, to give the colours shaded relief
    """
    if mode == "rgb":
        bands = [raster.band_index(b) for b in rgb]
        if None in bands:
            bands = [0, 1, 2] if raster.data.shape[0] >= 3 else [0, 0, 0]
        resampling = Resampling.average
    else:
        bands = [band]
        resampling = Resampling.nearest if mode == "categorical" else Resampling.average

    source = raster
    if shade is not None:
        # Add the hillshade as an extra band, so it gets reprojected the same way as the values.
        source = Raster(np.concatenate([raster.data, shade[None].astype(np.float32)]), raster.crs,
                        raster.transform, [*raster.names, "_shade"])
    extra = [source.data.shape[0] - 1] if shade is not None else []
    data, bounds, mercator_bounds = _to_web_mercator(source, bands + extra, resampling)
    values = data[: len(bands)]

    style = {"mode": mode, "bands": bands, "shade": shade is not None, "mercatorBounds": mercator_bounds}
    if mode == "rgb":
        style["rgbLimits"] = [_percentile_limits(values[i]) for i in range(3)]
        legend = {"type": "rgb", "label": label or "True colour"}
    elif mode == "categorical":
        style["categories"] = categories
        legend = {"type": "categorical", "label": label, "classes": categories}
    else:
        if vmin is None or vmax is None:
            lo, hi = _percentile_limits(values[0])
            vmin = lo if vmin is None else vmin
            vmax = hi if vmax is None else vmax
        style.update(cmap=cmap, vmin=float(vmin), vmax=float(vmax))
        legend = {"type": "continuous", "label": label, "unit": unit, "min": vmin, "max": vmax,
                  "colors": _gradient(cmap), "cmap": cmap}

    rgba = colorize(values, style, data[-1] if extra else None)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"{name}_{tag}.webp" if tag else f"{name}.webp"
    # WebP keeps transparency and is far smaller than PNG (a satellite preview drops from
    # about 5 MB to 0.5 MB). Classes are saved without any loss so their colours stay exact.
    Image.fromarray(rgba, "RGBA").save(os.path.join(OUTPUT_DIR, filename), "WEBP", quality=88,
                                       lossless=mode == "categorical", method=4)
    return filename, bounds, legend, style


def save_style(style, raster_path, name, tag):
    """Saves the style, together with the raster's path, for the map tiles to use. Returns the style file's path."""
    os.makedirs(STYLE_DIR, exist_ok=True)
    path = os.path.join(STYLE_DIR, f"{name}_{tag}.json" if tag else f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({**style, "rasterPath": raster_path}, f)
    return path


def preview_like(legend, raster):
    """Preview settings that make a result look like the one it came from.

    Used by nodes that don't change what the values mean, like Cut to Outline, so a cut
    slope map keeps the same colours and legend as the slope map.
    """
    legend = legend or {}
    if legend.get("type") == "rgb" and raster.data.shape[0] >= 3:
        return {"mode": "rgb", "label": legend.get("label", "")}
    if legend.get("type") == "categorical":
        return {"mode": "categorical", "categories": legend["classes"], "label": legend.get("label", "")}
    if legend.get("type") == "continuous" and legend.get("cmap") in colormaps:
        return {"mode": "continuous", "cmap": legend["cmap"], "vmin": legend.get("min"), "vmax": legend.get("max"),
                "unit": legend.get("unit", ""), "label": legend.get("label", "")}
    return {"mode": "continuous", "cmap": "viridis", "label": str(raster.names[0])}


def raster_result(raster, name, tag, preview, details=None, dtype="float32", existing_path=None):
    """Saves a raster result with its preview and style, and returns the fields the node sends back.

    preview      settings for render_preview (mode, colour scale, label and so on)
    details      extra lines for the node's details panel
    existing_path  if the values haven't changed (Colour Map only restyles), pass the existing
                 file here and no copy is written
    """
    if not np.isfinite(raster.data).any():
        raise InputError("The result has no valid pixels. Check that the inputs overlap.")
    path = existing_path or write_raster(raster, name, tag, dtype=dtype)
    image, bounds, legend, style = render_preview(raster, name, tag, **preview)
    style_path = save_style(style, path, name, tag)
    height, width = raster.shape
    band = preview.get("band", 0)
    return {
        "rasterPath": path,
        "stylePath": style_path,
        "outputImage": image,
        "rasterBounds": bounds,
        "legend": legend,
        "bands": raster.names,
        "stats": band_stats(raster.data[band]),
        "details": {
            **(details or {}),
            "Size": f"{width} × {height} px",
            "Resolution": resolution_label(raster),
            "CRS": raster.crs.to_string(),
            "Bands": ", ".join(map(str, raster.names)),
        },
    }
