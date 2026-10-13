"""Vector algorithms: buffer, spatial filter / clip, dissolve."""
import geopandas as gpd
from shapely.ops import unary_union

from .common import InputError

FILTER_MODES = {
    "intersects": "Keep features that touch the mask",
    "within": "Keep features completely inside the mask",
    "outside": "Keep features that don't touch the mask",
    "clip": "Cut features to the mask outline",
    "erase": "Remove the masked area from features",
}


def _local_utm(gdf):
    """A metric CRS for the data (needed for distances in metres)."""
    try:
        return gdf.estimate_utm_crs()
    except Exception:
        return "EPSG:3857"


def buffer(gdf, distance_m, dissolve=False):
    if distance_m == 0:
        raise InputError("Buffer distance can't be 0.")
    metric = gdf.to_crs(_local_utm(gdf))
    buffered = metric.copy()
    buffered["geometry"] = metric.geometry.buffer(distance_m, resolution=16)
    buffered = buffered[~buffered.geometry.is_empty]
    if dissolve:
        buffered = gpd.GeoDataFrame({"distance_m": [distance_m]}, geometry=[unary_union(buffered.geometry)],
                                    crs=buffered.crs)
    else:
        buffered["distance_m"] = distance_m
    return buffered.to_crs(epsg=4326)


def spatial_filter(data, mask, mode):
    mask = mask.to_crs(data.crs)
    mask_shape = unary_union(mask.geometry.make_valid())
    if mask_shape.is_empty:
        raise InputError("The mask has no geometry.")
    geoms = data.geometry.make_valid()
    if mode == "intersects":
        result = data[geoms.intersects(mask_shape)]
    elif mode == "within":
        result = data[geoms.within(mask_shape)]
    elif mode == "outside":
        result = data[~geoms.intersects(mask_shape)]
    elif mode == "clip":
        result = gpd.clip(data.set_geometry(geoms), mask_shape)
    elif mode == "erase":
        result = data.set_geometry(geoms.difference(mask_shape))
        result = result[~result.geometry.is_empty]
    else:
        raise InputError(f"Unknown filter mode '{mode}'.")
    return result


def dissolve(gdf, field=""):
    if field:
        if field not in gdf.columns:
            columns = ", ".join(c for c in gdf.columns if c != gdf.geometry.name)
            raise InputError(f"No attribute named '{field}'. Available: {columns or 'none'}")
        result = gdf[[field, gdf.geometry.name]].dissolve(by=field, as_index=False)
    else:
        result = gpd.GeoDataFrame(geometry=[unary_union(gdf.geometry.make_valid())], crs=gdf.crs)
    if result.geometry.geom_type.str.contains("Polygon").all():
        result["area_km2"] = result.to_crs(_local_utm(result)).geometry.area / 1e6
    return result
