"""Context, the object every analysis node receives, and the error type nodes raise."""
from dataclasses import dataclass, field
from datetime import date
from typing import Callable


class InputError(ValueError):
    """Something wrong with a node's inputs or settings. The message is shown to the user as it is,
    so it should say plainly what to change."""


# Result fields that point to a vector file, in the order they're checked.
VECTOR_KEYS = ("vectorPath", "layerGeojsonPath", "boundaryShpPath")
# Result fields that give an area as [south, north, west, east].
BOUNDS_KEYS = ("boundaryBounds", "vectorBounds", "rasterBounds", "satelliteBounds")


@dataclass
class Context:
    """Everything a node needs from the request: its settings and the results connected to it.

    node_type   for example "SlopeNode"
    params      the node's settings, as text straight from the form
    parents     the results of the connected nodes. One plugged into a named input has an
                "_input" key with that input's name.
    tag         a short id added to the names of files this node writes
    location    the place name, and place the full place picked in the Place node
    uploads     paths of files uploaded through this node
    safe_path   checks a path that came from the browser; returns None if it isn't allowed
    """
    node_type: str
    params: dict
    parents: list
    tag: str
    location: str | None
    place: dict | None
    uploads: list = field(default_factory=list)
    safe_path: Callable[[str | None], str | None] = lambda p: p

    # Inputs

    def inputs(self, handle=None):
        """The connected results plugged into a named input, or all of them if handle is None."""
        if handle is None:
            return list(self.parents)
        return [p for p in self.parents if p.get("_input") == handle]

    def raster_input(self, handle=None, label="a raster"):
        """Reads the first raster connected (to `handle`, if given). Raises InputError if there isn't one."""
        from .raster_io import read_raster
        for parent in self.inputs(handle):
            path = self.safe_path(parent.get("rasterPath"))
            if path:
                return read_raster(path)
        where = f" to the {handle} input" if handle else ""
        raise InputError(f"Connect {label}{where}, for example Satellite and Elevation Data, Your Own File "
                         "or another raster node.")

    def vector_input(self, handle=None, label="vector data"):
        """Reads the first set of shapes connected (to `handle`, if given). Raises InputError if there isn't one."""
        from .vector_io import read_vector
        for parent in self.inputs(handle):
            for key in VECTOR_KEYS:
                path = self.safe_path(parent.get(key))
                if path:
                    return read_vector(path)
        where = f" to the {handle} input" if handle else ""
        raise InputError(f"Connect {label}{where}, for example Outline, Map Features, Your Own File "
                         "or another shape node.")

    def area_bounds(self):
        """The area to work on, as [south, north, west, east].

        Taken from the first connected result that has an extent. If none do, the box of the
        place picked in the Place node is used. Returns None if there's nothing to go on.
        """
        for parent in self.parents:
            for key in BOUNDS_KEYS:
                bounds = parent.get(key)
                if isinstance(bounds, list) and len(bounds) == 4:
                    return [float(v) for v in bounds]
        if self.place and self.place.get("bbox"):
            return self.place["bbox"]
        return None

    # Settings. They all arrive as text from the form, so these read them as the right type
    # and fall back to the default when a setting is missing or doesn't make sense.

    def text(self, key, default=""):
        """A text setting, trimmed."""
        value = self.params.get(key)
        return str(value).strip() if value not in (None, "") else default

    def number(self, key, default, lo=None, hi=None):
        """A number setting, kept between lo and hi."""
        try:
            value = float(self.params.get(key))
        except (TypeError, ValueError):
            return default
        if value != value:  # "not a number" is the only value that isn't equal to itself
            return default
        if lo is not None:
            value = max(lo, value)
        if hi is not None:
            value = min(hi, value)
        return value

    def choice(self, key, options, default):
        """A setting that must be one of `options`."""
        value = self.text(key, default)
        return value if value in options else default

    def flag(self, key, default=False):
        """An on or off setting."""
        value = self.params.get(key)
        if value in (None, ""):
            return default
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def date(self, key, default):
        """A date setting written as YYYY-MM-DD."""
        value = self.text(key)
        try:
            return date.fromisoformat(value) if value else default
        except ValueError:
            raise InputError(f"'{value}' is not a valid date (use YYYY-MM-DD).")
