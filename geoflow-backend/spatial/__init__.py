"""Spatial analysis nodes: ingestion, terrain, raster and vector algorithms."""
from .common import Context, InputError
from .nodes import HANDLERS
from .tiles import CACHE_HEADERS as TILE_HEADERS, render_tile

# Form fields used as node settings (not uploaded files).
PARAM_KEYS = {"collection", "startDate", "endDate", "maxCloud", "units", "zFactor", "azimuth", "altitude",
              "interval", "expression", "index", "method", "breaks", "classes", "labels", "crop", "band", "stat",
              "distance", "dissolve", "mode", "field", "colormap", "reverse", "stretch", "min", "max", "hillshade", "factor", "cellSize", "minArea", "terrainStreams", "resultName",
              *(f"{name}{key}" for name in ("weight", "risk", "range") for key in "ABCD")}

__all__ = ["Context", "InputError", "HANDLERS", "PARAM_KEYS", "TILE_HEADERS", "render_tile"]
