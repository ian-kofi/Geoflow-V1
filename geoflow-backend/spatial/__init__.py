"""GeoFlow's analysis nodes: loading data, terrain, raster and vector tools.

How the package fits together:
    nodes.py        one function per node type, listed in HANDLERS
    common.py       Context, which gives those functions their inputs and settings
    stac.py         satellite and elevation data from Microsoft Planetary Computer
    terrain.py      slope, aspect, hillshade, ruggedness and contours
    hydrology.py    river networks and height above the nearest river (HAND)
    raster_ops.py   raster calculator, spectral indices, reclassify, clip, zonal statistics
    vector_ops.py   buffer, spatial filter, dissolve
    raster_io.py    reading and saving rasters, and drawing their previews and legends
    vector_io.py    the same for vector data
    tiles.py        map tiles drawn on demand from saved rasters

main.py only needs what's imported here.
"""
from .common import Context, InputError
from .nodes import HANDLERS
from .tiles import CACHE_HEADERS as TILE_HEADERS, render_tile

# Form fields that are node settings rather than uploaded files. The names match the `key` of
# each setting in geoflow-project/src/nodes/spatialNodes.js.
PARAM_KEYS = {"collection", "startDate", "endDate", "maxCloud", "units", "zFactor", "azimuth", "altitude",
              "interval", "expression", "index", "method", "breaks", "classes", "labels", "crop", "band", "stat",
              "distance", "dissolve", "mode", "field", "colormap", "reverse", "stretch", "min", "max", "hillshade", "factor", "cellSize", "minArea", "terrainStreams", "resultName",
              *(f"{name}{key}" for name in ("weight", "risk", "range") for key in "ABCD")}

__all__ = ["Context", "InputError", "HANDLERS", "PARAM_KEYS", "TILE_HEADERS", "render_tile"]
