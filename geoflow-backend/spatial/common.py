"""Shared types for the spatial analysis nodes."""
from dataclasses import dataclass, field
from datetime import date
from typing import Callable


class InputError(ValueError):
    """A problem with a node's inputs or settings; shown to the user as-is."""


# Output keys whose value is a vector file usable by vector nodes, in priority order.
VECTOR_KEYS = ("vectorPath", "layerGeojsonPath", "boundaryShpPath")
# Output keys that describe an area as [south, north, west, east].
BOUNDS_KEYS = ("boundaryBounds", "vectorBounds", "rasterBounds", "satelliteBounds")


@dataclass
class Context:
    """Everything a spatial node handler needs from the request."""
    node_type: str
    params: dict
    parents: list
    tag: str
    location: str | None
    place: dict | None
    uploads: list = field(default_factory=list)
    safe_path: Callable[[str | None], str | None] = lambda p: p

    # ---- inputs -------------------------------------------------------
    def inputs(self, handle=None):
        """Parent outputs connected to a named input handle (all parents when None)."""
        if handle is None:
            return list(self.parents)
        return [p for p in self.parents if p.get("_input") == handle]

    def raster_input(self, handle=None, label="a raster"):
        from .raster_io import read_raster
        for parent in self.inputs(handle):
            path = self.safe_path(parent.get("rasterPath"))
            if path:
                return read_raster(path)
        where = f" to the {handle} input" if handle else ""
        raise InputError(f"Connect {label}{where} (e.g. STAC Search, Local File or another raster node).")

    def vector_input(self, handle=None, label="vector data"):
        from .vector_io import read_vector
        for parent in self.inputs(handle):
            for key in VECTOR_KEYS:
                path = self.safe_path(parent.get(key))
                if path:
                    return read_vector(path)
        where = f" to the {handle} input" if handle else ""
        raise InputError(f"Connect {label}{where} (e.g. Boundary, OSM Layer, Local File or another vector node).")

    def area_bounds(self):
        """[south, north, west, east] from the first upstream node that has an extent."""
        for parent in self.parents:
            for key in BOUNDS_KEYS:
                bounds = parent.get(key)
                if isinstance(bounds, list) and len(bounds) == 4:
                    return [float(v) for v in bounds]
        if self.place and self.place.get("bbox"):
            return self.place["bbox"]
        return None

    # ---- parameters ---------------------------------------------------
    def text(self, key, default=""):
        value = self.params.get(key)
        return str(value).strip() if value not in (None, "") else default

    def number(self, key, default, lo=None, hi=None):
        try:
            value = float(self.params.get(key))
        except (TypeError, ValueError):
            return default
        if value != value:  # NaN
            return default
        if lo is not None:
            value = max(lo, value)
        if hi is not None:
            value = min(hi, value)
        return value

    def choice(self, key, options, default):
        value = self.text(key, default)
        return value if value in options else default

    def flag(self, key, default=False):
        value = self.params.get(key)
        if value in (None, ""):
            return default
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def date(self, key, default):
        value = self.text(key)
        try:
            return date.fromisoformat(value) if value else default
        except ValueError:
            raise InputError(f"'{value}' is not a valid date (use YYYY-MM-DD).")
