"""Vector reading/writing and map previews."""
import os

import geopandas as gpd
import numpy as np
from matplotlib import colormaps
from matplotlib.colors import to_hex

from plotting import BOUNDARY_EDGE, new_map_figure, save_figure
from .common import InputError

VECTOR_DIR = os.path.join("files", "vectors")
OUTPUT_DIR = "outputs"
MAX_FEATURES = 200_000
PREVIEW_COLOR = "#38bdf8"


def read_vector(path):
    gdf = gpd.read_file(path)
    if len(gdf) > MAX_FEATURES:
        raise InputError(f"Too many features ({len(gdf):,}). Filter or clip the data first.")
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    return gdf.to_crs(epsg=4326)


def _serializable(gdf):
    """GeoJSON can't hold lists/dicts in properties; stringify them."""
    gdf = gdf.copy()
    for col in gdf.columns:
        if col != gdf.geometry.name and gdf[col].dtype == object:
            gdf[col] = gdf[col].map(lambda v: v if v is None or isinstance(v, (str, int, float, bool)) else str(v))
    return gdf


def write_vector(gdf, name, tag):
    os.makedirs(VECTOR_DIR, exist_ok=True)
    path = os.path.join(VECTOR_DIR, f"{name}_{tag}.geojson" if tag else f"{name}.geojson")
    if os.path.exists(path):
        os.remove(path)
    _serializable(gdf.to_crs(epsg=4326)).to_file(path, driver="GeoJSON", COORDINATE_PRECISION=7)
    return path


def geometry_kinds(gdf):
    kinds = set()
    for geom_type in gdf.geometry.geom_type.unique():
        kinds.add("polygon" if "Polygon" in geom_type else "line" if "Line" in geom_type else "point")
    return kinds


def render_vector(gdf, name, tag, column=None, cmap="viridis", outline=None):
    minx, miny, maxx, maxy = gdf.total_bounds
    pad = max(maxx - minx, maxy - miny, 1e-4) * 0.04
    fig, ax = new_map_figure((minx - pad, miny - pad, maxx + pad, maxy + pad))
    if outline is not None:
        outline.boundary.plot(ax=ax, color=BOUNDARY_EDGE, linewidth=0.8, alpha=0.6)
    style = {"column": column, "cmap": cmap} if column else {"color": PREVIEW_COLOR}
    kinds = geometry_kinds(gdf)
    if "polygon" in kinds:
        polys = gdf[gdf.geometry.geom_type.str.contains("Polygon")]
        polys.plot(ax=ax, edgecolor="#e2e8f0", linewidth=0.4, alpha=0.75, **style)
    if "line" in kinds:
        gdf[gdf.geometry.geom_type.str.contains("Line")].plot(ax=ax, linewidth=0.8, **style)
    if "point" in kinds:
        gdf[gdf.geometry.geom_type.str.contains("Point")].plot(ax=ax, markersize=8, **style)
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"{name}_{tag}.png" if tag else f"{name}.png"
    save_figure(fig, os.path.join(OUTPUT_DIR, filename), dpi=150)
    return filename


def column_legend(gdf, column, cmap, label):
    values = gdf[column].astype(float)
    return {"type": "continuous", "label": label, "unit": "", "min": float(np.nanmin(values)),
            "max": float(np.nanmax(values)), "colors": [to_hex(colormaps[cmap](i / 7)) for i in range(8)]}


def vector_result(gdf, name, tag, column=None, cmap="viridis", legend_label=None, details=None, outline=None):
    """Saves the vector + preview and returns the node's output fields.

    Polygon results are also exposed as a boundary, so they can drive
    Satellite clipping, OSM layers, STAC searches and composites downstream.
    """
    if gdf.empty:
        raise InputError("The result is empty — no features matched.")
    gdf = gdf.to_crs(epsg=4326)
    path = write_vector(gdf, name, tag)
    image = render_vector(gdf, name, tag, column=column, cmap=cmap, outline=outline)
    minx, miny, maxx, maxy = (float(v) for v in gdf.total_bounds)
    bounds = [miny, maxy, minx, maxx]
    kinds = geometry_kinds(gdf)
    result = {
        "vectorPath": path,
        "outputImage": image,
        "vectorBounds": bounds,
        "featureCount": int(len(gdf)),
        "legend": column_legend(gdf, column, cmap, legend_label or column) if column else None,
        "details": {**(details or {}), "Features": f"{len(gdf):,}",
                    "Geometry": ", ".join(sorted(kinds))},
    }
    if kinds == {"polygon"}:
        result["boundaryShpPath"] = path
        result["boundaryBounds"] = bounds
    return result
