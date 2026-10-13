"""Terrain derivatives from a DEM, using Horn's (1981) 3×3 method — the same
formulas as ArcGIS / GDAL, so results are comparable with desktop GIS."""
import math

import contourpy
import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from .common import InputError
from .raster_io import pixel_size_m

MAX_CONTOUR_LEVELS = 250


def _window(z):
    """The 8 neighbours of every cell (edges repeat the border value)."""
    p = np.pad(z, 1, mode="edge")
    return {
        "a": p[:-2, :-2], "b": p[:-2, 1:-1], "c": p[:-2, 2:],
        "d": p[1:-1, :-2], "f": p[1:-1, 2:],
        "g": p[2:, :-2], "h": p[2:, 1:-1], "i": p[2:, 2:],
    }


def horn_gradient(dem, z_factor=1.0):
    """(dz/dx, dz/dy) per Horn, with dy measured down the rows (ESRI convention)."""
    z = dem.data[0] * z_factor
    n = _window(z)
    dx, dy = pixel_size_m(dem)
    dzdx = ((n["c"] + 2 * n["f"] + n["i"]) - (n["a"] + 2 * n["d"] + n["g"])) / (8 * dx)
    dzdy = ((n["g"] + 2 * n["h"] + n["i"]) - (n["a"] + 2 * n["b"] + n["c"])) / (8 * dy)
    return dzdx, dzdy


def slope(dem, units="degrees", z_factor=1.0):
    dzdx, dzdy = horn_gradient(dem, z_factor)
    rise = np.hypot(dzdx, dzdy)
    return rise * 100 if units == "percent" else np.degrees(np.arctan(rise))


def aspect(dem):
    """Compass direction the slope faces, degrees clockwise from north; flat cells are NaN."""
    dzdx, dzdy = horn_gradient(dem)
    angle = np.degrees(np.arctan2(dzdy, -dzdx))
    out = np.where(angle < 0, 90 - angle, np.where(angle > 90, 450 - angle, 90 - angle))
    out[(dzdx == 0) & (dzdy == 0)] = np.nan
    return out % 360


def hillshade(dem, azimuth=315.0, altitude=45.0, z_factor=1.0):
    dzdx, dzdy = horn_gradient(dem, z_factor)
    zenith = math.radians(90 - altitude)
    azimuth_math = math.radians((360 - azimuth + 90) % 360)
    slope_rad = np.arctan(np.hypot(dzdx, dzdy))
    aspect_rad = np.arctan2(dzdy, -dzdx)
    aspect_rad = np.where(aspect_rad < 0, aspect_rad + 2 * math.pi, aspect_rad)
    shade = (math.cos(zenith) * np.cos(slope_rad)
             + math.sin(zenith) * np.sin(slope_rad) * np.cos(azimuth_math - aspect_rad))
    return np.clip(shade * 255, 0, 255)


def ruggedness(dem):
    """Terrain Ruggedness Index (Riley et al. 1999): sqrt of the summed squared
    elevation differences between a cell and its 8 neighbours, in elevation units."""
    z = dem.data[0]
    n = _window(z)
    return np.sqrt(sum((n[k] - z) ** 2 for k in "abcdfghi"))


def contours(dem, interval):
    """Contour lines every `interval` elevation units, as a GeoDataFrame in EPSG:4326."""
    z = dem.data[0]
    finite = z[np.isfinite(z)]
    if finite.size == 0:
        raise InputError("The DEM has no valid elevation values.")
    first = math.ceil(finite.min() / interval) * interval
    levels = np.arange(first, finite.max() + 1e-9, interval)
    if len(levels) == 0:
        raise InputError(f"The terrain varies less than the {interval:g} contour interval; use a smaller interval.")
    if len(levels) > MAX_CONTOUR_LEVELS:
        raise InputError(f"An interval of {interval:g} gives {len(levels)} contour levels; use a larger interval.")

    generator = contourpy.contour_generator(z=np.ma.masked_invalid(z), line_type="Separate")
    t = dem.transform
    rows = []
    for level in levels:
        for line in generator.lines(level):
            if len(line) < 2:
                continue
            cols, rws = line[:, 0] + 0.5, line[:, 1] + 0.5      # cell centres
            xs = t.c + t.a * cols + t.b * rws
            ys = t.f + t.d * cols + t.e * rws
            rows.append({"elevation": float(level), "geometry": LineString(np.column_stack([xs, ys]))})
    if not rows:
        raise InputError("No contours were produced; try a smaller interval.")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=dem.crs).to_crs(epsg=4326)
