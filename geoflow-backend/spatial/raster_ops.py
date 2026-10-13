"""Raster algorithms: map algebra, spectral indices, reclassification, clipping, zonal statistics."""
import ast
import operator
import os

import geopandas as gpd
import numpy as np
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds, transform as window_transform

from .common import InputError
from .raster_io import Raster, align_to, category_colors

TABLE_DIR = os.path.join("files", "tables")
MAX_ZONES = 5000

# ---- Raster calculator (map algebra) ---------------------------------------

_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
            ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
_CMP_OPS = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le,
            ast.Eq: operator.eq, ast.NotEq: operator.ne}
_FUNCS = {"sqrt": np.sqrt, "abs": np.abs, "log": np.log, "log10": np.log10, "exp": np.exp,
          "sin": np.sin, "cos": np.cos, "tan": np.tan, "min": np.fmin, "max": np.fmax,
          "where": np.where, "clip": np.clip, "round": np.round, "floor": np.floor, "ceil": np.ceil}


def evaluate(expression, variables):
    """Evaluates an arithmetic expression over arrays.

    Parsed with `ast` and walked node by node, so only numbers, variables,
    arithmetic, comparisons and the whitelisted functions are possible —
    never arbitrary Python.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise InputError(f"Expression has a syntax error: {e.msg}")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise InputError(f"Unknown variable '{node.id}'. Available: {', '.join(sorted(variables))}")
            return variables[node.id]
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            key = f"{node.value.id}.{node.attr.lower()}"
            if key not in variables:
                raise InputError(f"Input {node.value.id} has no band named '{node.attr}'.")
            return variables[key]
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = ev(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMP_OPS:
            return _CMP_OPS[type(node.ops[0])](ev(node.left), ev(node.comparators[0])).astype(np.float32)
        if isinstance(node, ast.BoolOp):
            values = [np.asarray(ev(v)) != 0 for v in node.values]
            combine = np.logical_and if isinstance(node.op, ast.And) else np.logical_or
            result = values[0]
            for v in values[1:]:
                result = combine(result, v)
            return result.astype(np.float32)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise InputError(f"'{ast.unparse(node)}' is not allowed in an expression.")

    with np.errstate(all="ignore"):
        return ev(tree)


def raster_calculator(inputs, expression):
    """`inputs` maps handle letters (A–D) to rasters; all are aligned to the first one.

    Variables: A (band 1), A1…An (band n), A.red / A.nir (named bands).
    """
    if not inputs:
        raise InputError("Connect at least one raster to input A.")
    ref_key = sorted(inputs)[0]
    ref = inputs[ref_key]
    variables = {}
    for key, raster in inputs.items():
        aligned = align_to(raster, ref)
        variables[key] = aligned.data[0]
        for i, name in enumerate(aligned.names):
            variables[f"{key}{i + 1}"] = aligned.data[i]
            variables[f"{key}.{str(name).lower()}"] = aligned.data[i]
    result = evaluate(expression, variables)
    result = np.broadcast_to(np.asarray(result, dtype=np.float32), ref.shape).copy()
    result[~np.isfinite(result)] = np.nan
    return ref.with_data(result[None], ["result"])


# ---- Spectral indices -------------------------------------------------------

def _nd(a, b):
    return (a - b) / (a + b)


SPECTRAL_INDICES = {
    "ndvi": {"label": "NDVI", "bands": ("nir", "red"), "fn": lambda b: _nd(b["nir"], b["red"]),
             "cmap": "RdYlGn", "range": (-0.2, 0.9), "about": "vegetation"},
    "ndwi": {"label": "NDWI", "bands": ("green", "nir"), "fn": lambda b: _nd(b["green"], b["nir"]),
             "cmap": "RdBu", "range": (-0.6, 0.6), "about": "open water"},
    "mndwi": {"label": "MNDWI", "bands": ("green", "swir16"), "fn": lambda b: _nd(b["green"], b["swir16"]),
              "cmap": "RdBu", "range": (-0.6, 0.6), "about": "water (urban-robust)"},
    "ndbi": {"label": "NDBI", "bands": ("swir16", "nir"), "fn": lambda b: _nd(b["swir16"], b["nir"]),
             "cmap": "RdBu_r", "range": (-0.5, 0.5), "about": "built-up area"},
    "nbr": {"label": "NBR", "bands": ("nir", "swir22"), "fn": lambda b: _nd(b["nir"], b["swir22"]),
            "cmap": "RdYlGn", "range": (-0.5, 0.8), "about": "burn severity"},
    "savi": {"label": "SAVI", "bands": ("nir", "red"),
             "fn": lambda b: 1.5 * (b["nir"] - b["red"]) / (b["nir"] + b["red"] + 0.5),
             "cmap": "RdYlGn", "range": (-0.2, 0.8), "about": "vegetation, soil-adjusted"},
    "evi": {"label": "EVI", "bands": ("nir", "red", "blue"),
            "fn": lambda b: 2.5 * (b["nir"] - b["red"]) / (b["nir"] + 6 * b["red"] - 7.5 * b["blue"] + 1),
            "cmap": "RdYlGn", "range": (-0.2, 0.8), "about": "vegetation, enhanced"},
}


def spectral_index(raster, key):
    spec = SPECTRAL_INDICES[key]
    bands = {}
    for name in spec["bands"]:
        band = raster.band(name)
        if band is None:
            raise InputError(f"{spec['label']} needs a raster with bands named {', '.join(spec['bands'])} "
                             f"(this one has: {', '.join(map(str, raster.names))}). Use a Sentinel-2/Landsat "
                             "STAC Search, or the Raster Calculator with band numbers, e.g. (A4 - A3) / (A4 + A3).")
        bands[name] = band
    with np.errstate(all="ignore"):
        result = spec["fn"](bands).astype(np.float32)
    result[~np.isfinite(result)] = np.nan
    return raster.with_data(result[None], [key])


# ---- Reclassify -------------------------------------------------------------

def _format(v):
    return f"{v:,.4g}"


def reclassify(raster, method, breaks_text, class_count, labels_text, unit=""):
    """Continuous values → classes 1..k. Returns (raster, categories for the legend)."""
    arr = raster.data[0]
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        raise InputError("The input raster has no valid values.")
    if method == "manual":
        try:
            breaks = sorted(float(v) for v in breaks_text.replace(";", ",").split(",") if v.strip())
        except ValueError:
            raise InputError("Breaks must be numbers separated by commas, e.g. 15, 30")
        if not breaks:
            raise InputError("Enter at least one break value, e.g. 15, 30")
    else:
        k = int(class_count)
        if method == "quantile":
            breaks = list(np.unique(np.percentile(finite, np.linspace(0, 100, k + 1)[1:-1])))
        else:
            breaks = list(np.linspace(finite.min(), finite.max(), k + 1)[1:-1])

    classes = (np.digitize(arr, breaks) + 1).astype(np.float32)
    classes[~np.isfinite(arr)] = np.nan
    count = len(breaks) + 1
    labels = [s.strip() for s in labels_text.split(",")] if labels_text.strip() else []
    colors = category_colors(count)
    categories = []
    for i in range(count):
        if i == 0:
            rng = f"< {_format(breaks[0])}{unit}"
        elif i == count - 1:
            rng = f"≥ {_format(breaks[-1])}{unit}"
        else:
            rng = f"{_format(breaks[i - 1])} – {_format(breaks[i])}{unit}"
        name = labels[i] if i < len(labels) and labels[i] else f"Class {i + 1}"
        share = float(np.mean(classes[np.isfinite(classes)] == i + 1)) * 100
        categories.append({"value": i + 1, "label": f"{name} ({rng})", "color": colors[i], "percent": round(share, 1)})
    return raster.with_data(classes[None], ["class"]), categories


# ---- Clip raster ------------------------------------------------------------

def clip_raster(raster, mask_gdf, crop=True):
    geoms = [g for g in mask_gdf.to_crs(raster.crs).geometry if g is not None and not g.is_empty]
    if not geoms:
        raise InputError("The mask has no geometry.")
    inside = geometry_mask(geoms, out_shape=raster.shape, transform=raster.transform, invert=True, all_touched=True)
    if not inside.any():
        raise InputError("The mask does not overlap the raster.")
    data = raster.data.copy()
    data[:, ~inside] = np.nan
    if not crop:
        return raster.with_data(data, raster.names)
    rows = np.flatnonzero(inside.any(axis=1))
    cols = np.flatnonzero(inside.any(axis=0))
    window = Window(cols[0], rows[0], cols[-1] - cols[0] + 1, rows[-1] - rows[0] + 1)
    sliced = data[:, rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    return Raster(sliced, raster.crs, window_transform(window, raster.transform), raster.names)


# ---- Zonal statistics -------------------------------------------------------

def zonal_statistics(raster, zones, band_index, tag):
    """Per-polygon count/mean/min/max/std/sum of one band. Returns (zones gdf, csv path)."""
    zones = zones[zones.geometry.geom_type.str.contains("Polygon")].copy()
    if zones.empty:
        raise InputError("Zonal statistics needs polygon zones (e.g. a Boundary at ADM1/ADM2).")
    if len(zones) > MAX_ZONES:
        raise InputError(f"Too many zones ({len(zones):,}); the limit is {MAX_ZONES:,}.")
    if not 0 <= band_index < raster.data.shape[0]:
        raise InputError(f"The raster has {raster.data.shape[0]} band(s); band {band_index + 1} does not exist.")
    arr = raster.data[band_index]
    height, width = raster.shape
    projected = zones.to_crs(raster.crs)
    stats = {k: [] for k in ("count", "mean", "min", "max", "std", "sum")}

    for geom in projected.geometry:
        win = from_bounds(*geom.bounds, transform=raster.transform).round_offsets().round_lengths()
        r0, c0 = max(0, int(win.row_off)), max(0, int(win.col_off))
        r1, c1 = min(height, int(win.row_off + win.height) + 1), min(width, int(win.col_off + win.width) + 1)
        values = np.array([])
        if r1 > r0 and c1 > c0:
            sub_transform = window_transform(Window(c0, r0, c1 - c0, r1 - r0), raster.transform)
            inside = geometry_mask([geom], out_shape=(r1 - r0, c1 - c0), transform=sub_transform,
                                   invert=True, all_touched=False)
            if not inside.any():   # zone smaller than a pixel: use any touched pixel
                inside = geometry_mask([geom], out_shape=(r1 - r0, c1 - c0), transform=sub_transform,
                                       invert=True, all_touched=True)
            block = arr[r0:r1, c0:c1][inside]
            values = block[np.isfinite(block)]
        stats["count"].append(int(values.size))
        for key, fn in (("mean", np.mean), ("min", np.min), ("max", np.max), ("std", np.std), ("sum", np.sum)):
            stats[key].append(float(fn(values)) if values.size else np.nan)

    for key, values in stats.items():
        zones[key] = values
    os.makedirs(TABLE_DIR, exist_ok=True)
    csv_path = os.path.join(TABLE_DIR, f"zonal_{tag}.csv")
    zones.drop(columns=zones.geometry.name).to_csv(csv_path, index=False)
    return zones, csv_path
