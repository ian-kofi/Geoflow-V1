"""Terrain measurements worked out from a DEM (a grid of ground heights).

Slope, aspect and hillshade use Horn's (1981) method, which looks at each cell's eight
neighbours. ArcGIS and GDAL use the same formulas, so results can be compared with desktop GIS.

Every function takes a Raster whose first band is the height in metres, on a grid measured in
metres (stac.py always delivers the DEM like that).
"""
import math

import contourpy
import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from .common import InputError
from .raster_io import pixel_size_m

MAX_CONTOUR_LEVELS = 250   # more lines than this would be unreadable and slow


def _window(z):
    """The eight neighbours of every cell, as eight shifted copies of the grid.

    The names follow the usual layout:
        a b c
        d e f      (e is the cell itself)
        g h i
    Cells on the edge reuse their own value for the missing neighbours.
    """
    p = np.pad(z, 1, mode="edge")
    return {
        "a": p[:-2, :-2], "b": p[:-2, 1:-1], "c": p[:-2, 2:],
        "d": p[1:-1, :-2], "f": p[1:-1, 2:],
        "g": p[2:, :-2], "h": p[2:, 1:-1], "i": p[2:, 2:],
    }


def horn_gradient(dem, z_factor=1.0):
    """How fast the height changes going east (dz/dx) and going down the rows (dz/dy), using Horn's method.

    Measuring dy down the rows matches how ArcGIS does it. z_factor scales the heights, for
    exaggerating relief.
    """
    z = dem.data[0] * z_factor
    n = _window(z)
    dx, dy = pixel_size_m(dem)
    dzdx = ((n["c"] + 2 * n["f"] + n["i"]) - (n["a"] + 2 * n["d"] + n["g"])) / (8 * dx)
    dzdy = ((n["g"] + 2 * n["h"] + n["i"]) - (n["a"] + 2 * n["b"] + n["c"])) / (8 * dy)
    return dzdx, dzdy


def slope(dem, units="degrees", z_factor=1.0):
    """How steep the ground is, in degrees (0 is flat, 90 a cliff) or percent (rise over run times 100)."""
    dzdx, dzdy = horn_gradient(dem, z_factor)
    rise = np.hypot(dzdx, dzdy)
    return rise * 100 if units == "percent" else np.degrees(np.arctan(rise))


def aspect(dem):
    """Which compass direction each slope faces, in degrees clockwise from north.

    0 is north, 90 east, 180 south, 270 west. Perfectly flat cells face no direction, so they
    are left empty (NaN).
    """
    dzdx, dzdy = horn_gradient(dem)
    angle = np.degrees(np.arctan2(dzdy, -dzdx))
    out = np.where(angle < 0, 90 - angle, np.where(angle > 90, 450 - angle, 90 - angle))
    out[(dzdx == 0) & (dzdy == 0)] = np.nan
    return out % 360


def hillshade(dem, azimuth=315.0, altitude=45.0, z_factor=1.0):
    """Shaded relief: how brightly each slope would be lit by a sun in a given position.

    azimuth is the sun's compass direction (315 is the north west, the usual choice) and
    altitude its height above the horizon in degrees. Returns 0 (dark) to 255 (fully lit).
    """
    dzdx, dzdy = horn_gradient(dem, z_factor)
    zenith = math.radians(90 - altitude)
    azimuth_math = math.radians((360 - azimuth + 90) % 360)   # compass angle to maths angle
    slope_rad = np.arctan(np.hypot(dzdx, dzdy))
    aspect_rad = np.arctan2(dzdy, -dzdx)
    aspect_rad = np.where(aspect_rad < 0, aspect_rad + 2 * math.pi, aspect_rad)
    shade = (math.cos(zenith) * np.cos(slope_rad)
             + math.sin(zenith) * np.sin(slope_rad) * np.cos(azimuth_math - aspect_rad))
    return np.clip(shade * 255, 0, 255)


def ruggedness(dem):
    """How rough the ground is: the Terrain Ruggedness Index (Riley et al. 1999).

    For each cell, take the height difference to each of its eight neighbours, square them,
    add them up and take the square root. The result is in metres. Flat ground is near 0.
    """
    z = dem.data[0]
    n = _window(z)
    return np.sqrt(sum((n[k] - z) ** 2 for k in "abcdfghi"))


def contours(dem, interval):
    """Lines joining places of equal height, one every `interval` metres.

    Returns them as a GeoDataFrame in latitude and longitude, with each line's height in the
    "elevation" column.
    """
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
            # contourpy works in grid positions; add half a cell to get cell centres, then
            # turn those into map coordinates with the raster's transform
            cols, rws = line[:, 0] + 0.5, line[:, 1] + 0.5
            xs = t.c + t.a * cols + t.b * rws
            ys = t.f + t.d * cols + t.e * rws
            rows.append({"elevation": float(level), "geometry": LineString(np.column_stack([xs, ys]))})
    if not rows:
        raise InputError("No contours were produced; try a smaller interval.")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=dem.crs).to_crs(epsg=4326)
