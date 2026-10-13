"""Request handlers for the spatial analysis node types.

Each handler takes a Context and returns the node's output fields. Raster
outputs carry `rasterPath`; vector outputs carry `vectorPath`; both include
`outputImage` (a preview PNG in outputs/) for the canvas and map.
"""
import math
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
from matplotlib import colormaps
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds
from scipy import ndimage

from . import hydrology, raster_ops, stac, terrain, vector_ops
from .common import Context, InputError
from .raster_io import (MAX_PIXELS, Raster, align_to, category_colors, pixel_size_m, preview_like, raster_result,
                        read_raster, resolution_label)
from .vector_io import read_vector, vector_result

RASTER_EXTENSIONS = (".tif", ".tiff", ".img", ".vrt", ".jp2")
VECTOR_EXTENSIONS = (".geojson", ".json", ".gpkg", ".kml", ".shp", ".fgb", ".zip")


# ---- Ingestion --------------------------------------------------------------

def stac_search(ctx: Context):
    bounds = ctx.area_bounds()
    if not bounds:
        raise InputError("Satellite & Elevation Data needs an area — connect a Place or an Outline.")
    collection = ctx.choice("collection", stac.COLLECTIONS, "sentinel-2-l2a")
    end = ctx.date("endDate", date.today())
    start = ctx.date("startDate", end - timedelta(days=90))
    if start > end:
        raise InputError("The start date is after the end date.")
    # With an outline connected, cloud gaps only need filling inside it (not in neighbouring countries).
    area = None
    try:
        outline = ctx.vector_input()
        polygons = outline[outline.geometry.geom_type.str.contains("Polygon")]
        if not polygons.empty:
            area = polygons.geometry.union_all().simplify(0.005)
    except InputError:
        pass
    raster, details, optical = stac.load(collection, bounds, start, end, ctx.number("maxCloud", 20, 0, 100), area)
    if optical:
        preview = {"mode": "rgb", "label": "True colour (red, green, blue)"}
    elif collection == "jrc-gsw":
        preview = {"mode": "continuous", "cmap": "Blues", "vmin": 0, "vmax": 100, "unit": "%",
                   "label": "Time underwater, 1984–2021"}
    else:
        preview = {"mode": "continuous", "cmap": "terrain", "unit": "m", "label": "Ground height"}
    short = collection.split("-")[0]
    return raster_result(raster, f"stac_{short}", ctx.tag, preview, details)


def local_file(ctx: Context):
    paths = list(ctx.uploads)
    folder = os.path.join("uploads", ctx.tag) if ctx.tag else None
    if not paths and folder and os.path.isdir(folder):
        # Nothing re-sent (e.g. after a page reload): reuse what this node uploaded before.
        paths = [os.path.join(folder, f) for f in sorted(os.listdir(folder))]
    if not paths:
        raise InputError("Choose a GeoTIFF, GeoJSON, GeoPackage, KML or zipped shapefile to load.")

    lower = {p: p.lower() for p in paths}
    raster_path = next((p for p in paths if lower[p].endswith(RASTER_EXTENSIONS)), None)
    if raster_path:
        raster = read_raster(raster_path)
        bands = raster.data.shape[0]
        rgb = bands >= 3 and all(raster.band_index(b) is not None for b in ("red", "green", "blue"))
        preview = ({"mode": "rgb", "label": "Bands red, green, blue"} if rgb or bands >= 3 else
                   {"mode": "continuous", "cmap": "viridis", "label": str(raster.names[0])})
        return raster_result(raster, "local", ctx.tag, preview, {"File": os.path.basename(raster_path)})

    vector_path = (next((p for p in paths if lower[p].endswith(".shp")), None)
                   or next((p for p in paths if lower[p].endswith(VECTOR_EXTENSIONS)), None))
    if not vector_path:
        names = ", ".join(os.path.basename(p) for p in paths)
        raise InputError(f"Unsupported file type ({names}). Use GeoTIFF, GeoJSON, GeoPackage, KML or a shapefile.")
    source = f"zip://{os.path.abspath(vector_path)}" if lower[vector_path].endswith(".zip") else vector_path
    return vector_result(read_vector(source), "local", ctx.tag, details={"File": os.path.basename(vector_path)})


# ---- Terrain ----------------------------------------------------------------

def _z_factor(ctx):
    """Whole numbers from 1 up (vertical exaggeration; 1 = elevation already in metres)."""
    return float(round(ctx.number("zFactor", 1, 1, 1000)))


def _dem(ctx):
    return ctx.raster_input(label="a DEM (e.g. STAC Search → Copernicus DEM)")


def slope(ctx: Context):
    dem = _dem(ctx)
    units = ctx.choice("units", ("degrees", "percent"), "degrees")
    values = terrain.slope(dem, units, _z_factor(ctx))
    unit = "°" if units == "degrees" else "%"
    preview = {"mode": "continuous", "cmap": "YlOrRd", "vmin": 0, "unit": unit, "label": "Steepness"}
    return raster_result(dem.with_data(values[None], ["slope"]), "slope", ctx.tag, preview, {"Units": units})


def aspect(ctx: Context):
    dem = _dem(ctx)
    preview = {"mode": "continuous", "cmap": "twilight", "vmin": 0, "vmax": 360, "unit": "°",
               "label": "Facing direction (0° = north, clockwise)"}
    return raster_result(dem.with_data(terrain.aspect(dem)[None], ["aspect"]), "aspect", ctx.tag, preview)


def ruggedness(ctx: Context):
    dem = _dem(ctx)
    preview = {"mode": "continuous", "cmap": "magma", "vmin": 0, "unit": "m", "label": "Ruggedness"}
    return raster_result(dem.with_data(terrain.ruggedness(dem)[None], ["tri"]), "tri", ctx.tag, preview)


def hillshade(ctx: Context):
    dem = _dem(ctx)
    values = terrain.hillshade(dem, ctx.number("azimuth", 315, 0, 360), ctx.number("altitude", 45, 0, 90),
                               _z_factor(ctx))
    preview = {"mode": "continuous", "cmap": "gray", "vmin": 0, "vmax": 255, "label": "Shaded relief"}
    return raster_result(dem.with_data(values[None], ["hillshade"]), "hillshade", ctx.tag, preview)


def contours(ctx: Context):
    dem = _dem(ctx)
    interval = ctx.number("interval", 50, 0.01, 1e6)
    lines = terrain.contours(dem, interval)
    return vector_result(lines, "contours", ctx.tag, column="elevation", cmap="terrain", legend_label="Height (m)",
                         details={"Interval": f"{interval:g} m", "Levels": str(lines['elevation'].nunique())})


LOWLAND_RELIEF_M = 40   # York 23 m, Hull 9 m, Lagos 22 m vs Accra 71 m, Akosombo 270 m


def height_above_river(ctx: Context):
    """HAND: each cell's height above the river it drains into (flood susceptibility)."""
    # Older saves connect the DEM without a handle name; anything not on 'rivers' is the DEM.
    dem_parents = [p for p in ctx.parents if p.get("_input") != "rivers"]
    dem = Context(ctx.node_type, ctx.params, dem_parents, ctx.tag, ctx.location, ctx.place,
                  safe_path=ctx.safe_path).raster_input(label="a DEM (e.g. Satellite & Elevation Data → Copernicus DEM)")
    if dem.crs.is_geographic:
        raise InputError("Height Above River needs a DEM in metres (e.g. from Satellite & Elevation Data).")
    dx, dy = pixel_size_m(dem)
    min_area = ctx.number("minArea", 1.0, 0.05, 10_000)
    rivers = _river_mask(ctx, dem) if ctx.inputs("rivers") else None
    # In low-relief land, streams traced from a 30 m surface model follow noise (hedges, buildings,
    # trees) rather than real channels, so with a river map connected only mapped rivers count.
    z = dem.data[0]
    relief = float(np.nanpercentile(z, 95) - np.nanpercentile(z, 5)) if np.isfinite(z).any() else 0.0
    mode = ctx.choice("terrainStreams", ("auto", "yes", "no"), "auto")
    derive = mode == "yes" or (mode == "auto" and (rivers is None or relief >= LOWLAND_RELIEF_M))
    hand, streams, details = hydrology.height_above_drainage(z, dx, dy, min_area, rivers, derive)
    if mode == "auto" and rivers is not None and not derive:
        details["Streams from terrain"] = f"skipped: low-lying area ({relief:.0f} m of relief), mapped rivers only"
    preview = {"mode": "continuous", "cmap": "YlGnBu_r", "vmin": 0, "vmax": 30, "unit": "m",
               "label": "Height above nearest river"}
    output = raster_result(dem.with_data(hand[None], ["hand"]), "hand", ctx.tag, preview, details)
    output["details"]["How to read"] = "0–5 m: floods first · 5–15 m: occasional · above 15 m: rarely floods"
    return output


def _river_mask(ctx, dem):
    """Known rivers on the DEM grid: lines/areas (e.g. Map Features → Main rivers) or a raster
    where cells above 0 are water."""
    for parent in ctx.inputs("rivers"):
        path = ctx.safe_path(parent.get("rasterPath"))
        if path:
            water = align_to(read_raster(path), dem, Resampling.nearest).data[0]
            return np.nan_to_num(water, nan=0) > 0
    features = ctx.vector_input("rivers", label="river lines")
    features = features[features.geometry.notna() & ~features.geometry.is_empty]
    if features.empty:
        return np.zeros(dem.data.shape[1:], dtype=bool)
    shapes = ((geom, 1) for geom in features.to_crs(dem.crs).geometry)
    return rasterize(shapes, out_shape=dem.data.shape[1:], transform=dem.transform, fill=0, dtype="uint8",
                     all_touched=True).astype(bool)


# ---- Raster algorithms ------------------------------------------------------

def raster_calculator(ctx: Context):
    inputs = {}
    for key in ("A", "B", "C", "D"):
        if ctx.inputs(key):
            inputs[key] = ctx.raster_input(key)
    expression = ctx.text("expression", "A")
    result = raster_ops.raster_calculator(inputs, expression)
    preview = {"mode": "continuous", "cmap": "viridis", "label": expression}
    return raster_result(result, "calc", ctx.tag, preview, {"Expression": expression})


def spectral_index(ctx: Context):
    raster = ctx.raster_input(label="a multispectral raster (e.g. STAC Search → Sentinel-2)")
    key = ctx.choice("index", raster_ops.SPECTRAL_INDICES, "ndvi")
    spec = raster_ops.SPECTRAL_INDICES[key]
    result = raster_ops.spectral_index(raster, key)
    vmin, vmax = spec["range"]
    preview = {"mode": "continuous", "cmap": spec["cmap"], "vmin": vmin, "vmax": vmax, "label": spec["label"]}
    return raster_result(result, key, ctx.tag, preview, {"Index": f"{spec['label']} ({spec['about']})"})


def reclassify(ctx: Context):
    raster = ctx.raster_input()
    method = ctx.choice("method", ("manual", "equal", "quantile"), "manual")
    # Name the key after what was measured, e.g. "Steepness, grouped" with ranges in degrees.
    source = next((p for p in ctx.inputs() if p.get("rasterPath")), {})
    upstream = source.get("legend") or {}
    unit = upstream.get("unit", "") if upstream.get("type") == "continuous" else ""
    unit = unit if unit in ("°", "%") else f" {unit}" if unit else ""
    # "Flood susceptibility (0 = low, 1 = high)" → "Flood susceptibility"
    measured = (upstream.get("label") or str(raster.names[0])).split(" (")[0]
    classes, categories = raster_ops.reclassify(raster, method, ctx.text("breaks"), ctx.number("classes", 3, 2, 12),
                                                ctx.text("labels"), unit)
    preview = {"mode": "categorical", "categories": categories, "label": f"{measured}, grouped"}
    return raster_result(classes, "reclass", ctx.tag, preview, {"Method": method}, dtype="uint8")


def clip_raster(ctx: Context):
    raster = ctx.raster_input("raster")
    mask = ctx.vector_input("mask", label="a polygon mask (e.g. a Boundary)")
    clipped = raster_ops.clip_raster(raster, mask, ctx.flag("crop", True))
    # Keep the input's look (NDVI stays red→green, a DEM stays terrain-coloured, imagery stays true colour).
    source = next((p for p in ctx.inputs("raster") if p.get("rasterPath")), {})
    dtype = "uint8" if (source.get("legend") or {}).get("type") == "categorical" else "float32"
    return raster_result(clipped, "clip", ctx.tag, preview_like(source.get("legend"), clipped), dtype=dtype)


def zonal_statistics(ctx: Context):
    raster = ctx.raster_input("raster")
    zones = ctx.vector_input("zones", label="polygon zones (e.g. a Boundary at ADM1/ADM2)")
    band = int(ctx.number("band", 1, 1, 999)) - 1
    stat = ctx.choice("stat", ("mean", "min", "max", "std", "sum", "count"), "mean")
    result, csv_path = raster_ops.zonal_statistics(raster, zones, band, ctx.tag)
    output = vector_result(result, "zonal", ctx.tag, column=stat, cmap="viridis",
                           legend_label=f"{stat} of {raster.names[band]}",
                           details={"Band": str(raster.names[band]), "Zones": f"{len(result):,}"})
    output["tablePath"] = csv_path
    return output


# Resampling techniques, named as in ArcGIS's Resample tool where one exists.
RESAMPLE_METHODS = {
    "nearest": ("Nearest", Resampling.nearest),
    "bilinear": ("Bilinear", Resampling.bilinear),
    "cubic": ("Cubic convolution", Resampling.cubic),
    "lanczos": ("Lanczos", Resampling.lanczos),
    "average": ("Average", Resampling.average),
    "mode": ("Majority", Resampling.mode),
}
MAX_CATEGORIES = 60


def _cell_size(ctx):
    """Output cell size in metres. Older Upscale nodes only had a factor, so default to 10 m."""
    return ctx.number("cellSize", 10.0, 0.1, 100_000)


def resample(ctx: Context):
    """Change a raster's cell size (ArcGIS: Resample), or turn vector features into a raster
    at a chosen cell size (ArcGIS: Feature to Raster). Finer or coarser both work."""
    cell = _cell_size(ctx)
    source = next((p for p in ctx.inputs() if ctx.safe_path(p.get("rasterPath"))), None)
    if source is None:
        return _features_to_raster(ctx, cell)

    raster = read_raster(ctx.safe_path(source["rasterPath"]))
    legend = source.get("legend") or {}
    categorical = legend.get("type") == "categorical"
    method = ctx.choice("method", RESAMPLE_METHODS, "cubic")
    if categorical and method not in ("nearest", "mode"):
        method = "nearest"   # interpolating class codes would invent classes that don't exist
    method_label, resampling = RESAMPLE_METHODS[method]

    # The cell size is in metres; geographic rasters store degrees.
    new_res = cell / 111_320 if raster.crs.is_geographic else cell / (raster.crs.linear_units_factor[1] or 1)
    west, south, east, north = raster.bounds()
    new_w, new_h = max(1, math.ceil((east - west) / new_res)), max(1, math.ceil((north - south) / new_res))
    if new_w * new_h * raster.data.shape[0] > MAX_PIXELS:
        raise InputError(f"A {cell:g} m cell size would make {new_w:,} × {new_h:,} px × {raster.data.shape[0]} band(s), "
                         "too large. Use a bigger cell size or cut the raster to a smaller outline first.")
    transform = from_origin(west, north, new_res, new_res)
    out = np.full((raster.data.shape[0], new_h, new_w), np.nan, dtype=np.float32)
    for i in range(raster.data.shape[0]):
        reproject(source=raster.data[i], destination=out[i], src_transform=raster.transform, src_crs=raster.crs,
                  dst_transform=transform, dst_crs=raster.crs, src_nodata=np.nan, dst_nodata=np.nan,
                  resampling=resampling)
    result = Raster(out, raster.crs, transform, raster.names)

    old_res = abs(raster.transform.a) * (111_320 if raster.crs.is_geographic else 1)
    details = {"Cell size": f"{resolution_label(raster)} → {resolution_label(result)}", "Technique": method_label}
    if cell < old_res * 0.95:
        details["Note"] = "Finer cells are interpolated: smoother, but no detail beyond the source data is created"
    return raster_result(result, "resample", ctx.tag, preview_like(legend, result), details,
                         dtype="uint8" if categorical else "float32")


def _features_to_raster(ctx, cell):
    """ArcGIS Feature to Raster: burn vector features into a grid with the chosen cell size."""
    features = ctx.vector_input(label="a raster or vector features to convert")
    field = ctx.text("field")
    west, south, east, north = features.total_bounds
    pad = 0.01 * max(east - west, north - south, 1e-4)
    crs = stac._utm_crs((west + east) / 2, (south + north) / 2)
    minx, miny, maxx, maxy = transform_bounds("EPSG:4326", crs, west - pad, south - pad, east + pad, north + pad)
    width, height = math.ceil((maxx - minx) / cell), math.ceil((maxy - miny) / cell)
    if width * height > MAX_PIXELS:
        raise InputError(f"A {cell:g} m cell size would make {width:,} × {height:,} px, too large. Use a bigger cell size.")
    transform = from_origin(minx, maxy, cell, cell)
    projected = features.to_crs(crs)

    categories = None
    if not field:
        values = np.ones(len(projected), dtype=np.float32)
        categories = [{"value": 1, "label": "Inside features", "color": "#2563eb"}]
    elif field not in projected.columns:
        columns = ", ".join(c for c in projected.columns if c != projected.geometry.name)
        raise InputError(f"No attribute named '{field}'. Available: {columns or 'none'}")
    else:
        numeric = pd.to_numeric(projected[field], errors="coerce")
        if numeric.notna().mean() >= 0.9:
            values = numeric.to_numpy(dtype=np.float32)
        else:
            # Text attribute: one code per value, like ArcGIS's VALUE field.
            names = sorted(projected[field].dropna().astype(str).unique())
            if len(names) > MAX_CATEGORIES:
                raise InputError(f"'{field}' has {len(names)} different values; up to {MAX_CATEGORIES} are supported.")
            codes = {name: i + 1 for i, name in enumerate(names)}
            values = projected[field].astype(str).map(codes).to_numpy(dtype=np.float32)
            colours = category_colors(len(names), "tab20")
            categories = [{"value": i + 1, "label": name, "color": colours[i]} for i, name in enumerate(names)]

    out = np.full((height, width), np.nan, dtype=np.float32)
    # Polygons: cells whose centre is inside. Lines/points: every cell they touch (otherwise thin lines vanish).
    for polygons_only in (False, True):
        pairs = [(geom, float(v)) for geom, v in zip(projected.geometry, values)
                 if geom is not None and not geom.is_empty and np.isfinite(v)
                 and ("Polygon" in geom.geom_type) == polygons_only]
        if pairs:
            burned = rasterize(pairs, out_shape=(height, width), transform=transform, fill=np.nan, dtype="float32",
                               all_touched=not polygons_only)
            out = np.where(np.isfinite(burned), burned, out)
    if not np.isfinite(out).any():
        raise InputError("No features were large enough to fill a cell; try a smaller cell size.")

    result = Raster(out, crs, transform, [field or "value"])
    if categories:
        preview = {"mode": "categorical", "categories": categories, "label": field or "Features"}
    else:
        preview = {"mode": "continuous", "cmap": "viridis", "label": field}
    details = {"Converted": f"{len(projected):,} features → raster", "Cell size": f"{cell:g} m",
               "Value": field or "1 inside features"}
    return raster_result(result, "rasterize", ctx.tag, preview, details,
                         dtype="uint8" if categories and len(categories) < 255 else "float32")


def weighted_overlay(ctx: Context):
    """Multi-criteria overlay: rescale each factor to 0–1 risk, then a weighted average."""
    factors = []
    for key in ("A", "B", "C", "D"):
        if not ctx.inputs(key):
            continue
        weight = ctx.number(f"weight{key}", 1, 0, 1000)
        if weight == 0:
            continue
        factors.append((key, ctx.raster_input(key), weight, ctx.choice(f"risk{key}", ("high", "low"), "high"),
                        ctx.text(f"range{key}")))
    if not factors:
        raise InputError("Connect at least one factor raster to input A (and give it a weight above 0).")

    reference = factors[0][1]
    total = np.zeros(reference.shape, dtype=np.float64)
    weights = np.zeros(reference.shape, dtype=np.float64)
    summary = []
    for key, raster, weight, risk, value_range in factors:
        values = align_to(raster, reference).data[0]
        if value_range:
            try:
                low, high = sorted(float(v) for v in value_range.replace(";", ",").split(",")[:2])
            except ValueError:
                raise InputError(f"Range for {key} must be two numbers, e.g. 0, 15")
        else:
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                raise InputError(f"Input {key} has no values where it overlaps input A.")
            low, high = (float(v) for v in np.percentile(finite, [2, 98]))
        score = np.clip((values - low) / ((high - low) or 1), 0, 1)
        if risk == "low":
            score = 1 - score
        present = np.isfinite(score)
        total += np.where(present, score * weight, 0)
        weights += np.where(present, weight, 0)
        direction = "lower = more risk" if risk == "low" else "higher = more risk"
        summary.append(f"{key} ({raster.names[0]}): weight {weight:g}, {direction}, scaled {low:g}–{high:g}")

    with np.errstate(invalid="ignore", divide="ignore"):
        combined = np.where(weights > 0, total / weights, np.nan)
    combined[~np.isfinite(reference.data[0])] = np.nan     # stay inside input A's area
    name = ctx.text("resultName", "Combined score")
    preview = {"mode": "continuous", "cmap": "YlOrRd", "vmin": 0, "vmax": 1, "label": f"{name} (0 = low, 1 = high)"}
    details = {f"Factor {i + 1}": text for i, text in enumerate(summary)}
    return raster_result(reference.with_data(combined[None].astype(np.float32), ["score"]), "overlay", ctx.tag,
                         preview, details)


# ---- Cartography ------------------------------------------------------------

def colour_map(ctx: Context):
    """Restyles an upstream raster. The data file is passed through untouched."""
    source = next((p for p in ctx.inputs() if ctx.safe_path(p.get("rasterPath"))), None)
    if not source:
        raise InputError("Connect a raster result (e.g. a DEM from STAC Search, Slope or NDVI) to restyle it.")
    path = ctx.safe_path(source["rasterPath"])
    raster = read_raster(path)

    cmap = ctx.text("colormap", "viridis")
    if cmap not in colormaps:
        raise InputError(f"Unknown colour map '{cmap}'.")
    if ctx.flag("reverse"):
        cmap = cmap[:-2] if cmap.endswith("_r") else f"{cmap}_r"
    band = int(ctx.number("band", 1, 1, raster.data.shape[0])) - 1
    values = raster.data[band]
    upstream = source.get("legend") or {}
    same_band = band == 0
    shade = terrain.hillshade(raster.with_data(values[None], ["z"])) if ctx.flag("hillshade") else None
    details = {"Colour map": cmap, "Band": str(raster.names[band])}

    if upstream.get("type") == "categorical" and same_band:
        # Classified raster: keep the classes, recolour them along the chosen map.
        classes = upstream["classes"]
        colours = category_colors(len(classes), cmap)
        preview = {"mode": "categorical", "label": upstream.get("label", ""), "shade": shade,
                   "categories": [{**c, "color": colour} for c, colour in zip(classes, colours)]}
    else:
        stretch = ctx.choice("stretch", ("auto", "minmax", "custom"), "auto")
        vmin = vmax = None
        if stretch == "minmax":
            finite = values[np.isfinite(values)]
            vmin, vmax = (float(finite.min()), float(finite.max())) if finite.size else (None, None)
        elif stretch == "custom":
            vmin, vmax = ctx.number("min", None), ctx.number("max", None)
            if vmin is None or vmax is None or vmax <= vmin:
                raise InputError("For a custom range, enter a Min and a Max (Max must be larger).")
        details["Range"] = (f"{vmin:g} to {vmax:g}" if stretch == "custom" else
                            "full min–max" if stretch == "minmax" else "2nd–98th percentile")
        continuous = upstream.get("type") == "continuous" and same_band
        preview = {"mode": "continuous", "cmap": cmap, "vmin": vmin, "vmax": vmax, "band": band, "shade": shade,
                   "unit": upstream.get("unit", "") if continuous else "",
                   "label": upstream.get("label", "") if continuous else str(raster.names[band])}
    return raster_result(raster, "style", ctx.tag, preview, details, existing_path=path)


# ---- Vector algorithms ------------------------------------------------------

def buffer(ctx: Context):
    data = ctx.vector_input()
    distance = ctx.number("distance", 1000, -1e6, 1e6)
    result = vector_ops.buffer(data, distance, ctx.flag("dissolve", False))
    return vector_result(result, "buffer", ctx.tag, details={"Distance": f"{distance:g} m"})


def spatial_filter(ctx: Context):
    data = ctx.vector_input("data", label="the data to filter")
    mask = ctx.vector_input("mask", label="a mask")
    mode = ctx.choice("mode", vector_ops.FILTER_MODES, "intersects")
    result = vector_ops.spatial_filter(data, mask, mode)
    # Contours keep their height colours (and colour key) after being cut to an outline.
    heights = "elevation" in result.columns
    return vector_result(result, "filter", ctx.tag, outline=mask,
                         column="elevation" if heights else None, cmap="terrain",
                         legend_label="Height (m)" if heights else None,
                         details={"Mode": vector_ops.FILTER_MODES[mode], "Input features": f"{len(data):,}"})


def distance_to_features(ctx: Context):
    """Straight-line distance (m) from every cell to the nearest feature (e.g. rivers)."""
    features = ctx.vector_input("features", label="the features to measure from (e.g. Map Features → rivers)")
    reference = None
    for parent in ctx.inputs("extent"):
        path = ctx.safe_path(parent.get("rasterPath"))
        if path:
            reference = read_raster(path)
            break
    if reference is not None:
        west, south, east, north = transform_bounds(reference.crs, "EPSG:4326", *reference.bounds())
        bounds = [south, north, west, east]
    else:
        try:
            area = ctx.vector_input("extent")
        except InputError:
            area = features
        minx, miny, maxx, maxy = area.total_bounds
        bounds = [miny, maxy, minx, maxx]
    south, north, west, east = bounds
    pad = 0.02 * max(north - south, east - west)
    grid = stac._target_grid([south - pad, north + pad, west - pad, east + pad], 30)
    crs, transform, width, height, res = grid

    shapes = [g for g in features.to_crs(crs).geometry if g is not None and not g.is_empty]
    burned = rasterize([(g, 1) for g in shapes], out_shape=(height, width), transform=transform, fill=0,
                       dtype=np.uint8, all_touched=True).astype(bool)
    if not burned.any():
        raise InputError("None of the features fall inside this area.")
    distance = ndimage.distance_transform_edt(~burned, sampling=(res, res)).astype(np.float32)
    result = Raster(distance, crs, transform, ["distance"])
    if reference is not None:
        result = align_to(result, reference)
        result.data[:, ~np.isfinite(reference.data[0])] = np.nan
    finite = result.data[0][np.isfinite(result.data[0])]
    preview = {"mode": "continuous", "cmap": "viridis", "vmin": 0, "vmax": float(np.percentile(finite, 98)) if finite.size else 1,
               "unit": "m", "label": "Distance to nearest feature"}
    return raster_result(result, "distance", ctx.tag, preview, {"Features": f"{len(shapes):,}"})


def dissolve(ctx: Context):
    data = ctx.vector_input()
    field = ctx.text("field")
    return vector_result(vector_ops.dissolve(data, field), "dissolve", ctx.tag,
                         details={"Grouped by": field or "everything"})


HANDLERS = {
    "StacNode": stac_search,
    "LocalFileNode": local_file,
    "SlopeNode": slope,
    "AspectNode": aspect,
    "RuggednessNode": ruggedness,
    "HillshadeNode": hillshade,
    "ContourNode": contours,
    "RasterCalcNode": raster_calculator,
    "SpectralIndexNode": spectral_index,
    "ReclassifyNode": reclassify,
    "ClipRasterNode": clip_raster,
    "ZonalStatsNode": zonal_statistics,
    "HandNode": height_above_river,
    "WeightedOverlayNode": weighted_overlay,
    "DistanceNode": distance_to_features,
    "UpscaleNode": resample,
    "ColourMapNode": colour_map,
    "BufferNode": buffer,
    "SpatialFilterNode": spatial_filter,
    "DissolveNode": dissolve,
}
