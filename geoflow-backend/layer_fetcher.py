"""Roads, railways, rivers and buildings from OpenStreetMap, for the Map Features node.

The features are downloaded with overpass.py, kept to the ones that touch the outline (if one
is connected) and saved as GeoJSON in files/. A preview picture is drawn in outputs/.
"""
import os

import geopandas as gpd
import osmnx as ox
from shapely.ops import unary_union

from overpass import fetch_features
from plotting import BOUNDARY_EDGE, LAYER_COLORS, new_map_figure, save_figure
from satellite_fetcher import get_country_bounds

ox.settings.use_cache = True
ox.settings.log_console = False

# OpenStreetMap road types, from biggest to smallest
MAJOR_ROADS = ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"]
MEDIUM_ROADS = ["secondary", "secondary_link"]
MINOR_ROADS = ["tertiary", "tertiary_link", "unclassified", "residential"]

# Each option in the Map Features node and the OpenStreetMap tags it asks for.
# True means any value of that tag, so "buildings" gets everything tagged as a building.
LAYER_TAGS = {
    "roads": {"highway": MAJOR_ROADS + MEDIUM_ROADS + MINOR_ROADS},
    "highways": {"highway": MAJOR_ROADS},
    "railways": {"railway": ["rail", "subway", "tram", "light_rail", "narrow_gauge"]},
    "waterways": {"waterway": ["river", "stream", "canal"]},
    "rivers": {"waterway": ["river", "canal"]},
    "buildings": {"building": True},
}
POLYGON_LAYERS = {"buildings"}   # these are areas; everything else is lines

# Area sizes below are in square degrees. One square degree is roughly 12,300 km² at the
# equator and less further north (about 7,000 km² in the UK).
LARGE_AREA_DEG2 = 4.0        # above this, small roads and streams are left out
BUILDINGS_MAX_DEG2 = 0.5     # every building in a whole country would take Overpass hours

KEEP_COLUMNS = ("name", "highway", "railway", "waterway", "building")   # attributes we keep


def _tags_for(layer_type, area_deg2):
    """The tags to ask for. For big areas the smallest roads and streams are dropped, otherwise
    the download would be huge and the map too busy to read."""
    if area_deg2 > LARGE_AREA_DEG2:
        if layer_type == "roads":
            print(f"Large area ({area_deg2:.1f} deg²), so fetching major and secondary roads only")
            return {"highway": MAJOR_ROADS + MEDIUM_ROADS}
        if layer_type == "waterways":
            print(f"Large area ({area_deg2:.1f} deg²), so fetching rivers and canals only")
            return {"waterway": ["river", "canal"]}
    return LAYER_TAGS[layer_type]


def _resolve_area(location, bounds, clip_path):
    """Works out where to search.

    Returns the box to search, as (south, north, west, east), and the outline to cut the
    results to (or None). The outline file wins if there is one, then a box passed in, then
    a search for the place name.
    """
    boundary = None
    if clip_path and os.path.exists(clip_path):
        boundary = gpd.read_file(clip_path).to_crs(epsg=4326)
    elif bounds is None and location:
        # Look the place up the same way osmnx would, so the results stay inside the place.
        try:
            boundary = ox.geocode_to_gdf(location).to_crs(epsg=4326)
        except Exception as e:
            print(f"Place polygon lookup failed ({e}); using bounding box")

    if bounds is not None:
        return tuple(float(v) for v in bounds), boundary
    if boundary is not None:
        minx, miny, maxx, maxy = boundary.total_bounds
        return (miny, maxy, minx, maxx), boundary
    return get_country_bounds(location), None


def _clip(gdf, boundary):
    """Keeps the features that touch the outline. Roads crossing the edge are kept whole."""
    area = unary_union(boundary.geometry.simplify(0.001))
    idx = gdf.sindex.query(area, predicate="intersects")
    return gdf.iloc[sorted(idx)]


def fetch_layer(location, layer_type="roads", bounds=None, clip_path=None, tag=""):
    """Downloads one kind of feature for an area and draws a preview.

    location    place name, used if there's no outline or box to go on
    layer_type  one of the keys of LAYER_TAGS
    bounds      the box to search, as [south, north, west, east]
    clip_path   an outline GeoJSON to cut the results to
    tag         added to the file names so each node keeps its own files

    Returns the preview's file name and the path of the GeoJSON with the features.
    """
    if layer_type not in LAYER_TAGS:
        raise ValueError(f"Unknown layer type '{layer_type}'")
    print(f"Fetching {layer_type} for {location}...")
    os.makedirs("outputs", exist_ok=True)
    os.makedirs("files", exist_ok=True)

    suffix = f"{layer_type}_{tag}" if tag else layer_type
    output_image = f"layer_{suffix}.png"
    output_image_path = os.path.join("outputs", output_image)
    geojson_path = os.path.join("files", f"layer_{suffix}.geojson")

    (south, north, west, east), boundary = _resolve_area(location, bounds, clip_path)
    area_deg2 = abs(north - south) * abs(east - west)
    if layer_type == "buildings" and area_deg2 > BUILDINGS_MAX_DEG2:
        raise ValueError(f"Area is too large for a buildings layer ({area_deg2:.2f} deg²). "
                         "Pick a town or city instead of a whole country.")

    gdf = fetch_features(_tags_for(layer_type, area_deg2), south, north, west, east,
                         polygons=layer_type in POLYGON_LAYERS, keep=KEEP_COLUMNS)
    if boundary is not None and not gdf.empty:
        gdf = _clip(gdf, boundary)
    if gdf.empty:
        raise ValueError(f"No {layer_type} found in OpenStreetMap for {location}")

    if os.path.exists(geojson_path):
        os.remove(geojson_path)
    gdf.to_file(geojson_path, driver="GeoJSON", COORDINATE_PRECISION=6)
    print(f"{len(gdf)} {layer_type} features saved: {geojson_path}")

    # Preview: the outline in purple with the features on top. Big roads are drawn thicker.
    extent = boundary.total_bounds if boundary is not None else gdf.total_bounds
    fig, ax = new_map_figure(extent)
    color = LAYER_COLORS.get(layer_type, LAYER_COLORS["default"])

    if boundary is not None:
        boundary.boundary.plot(ax=ax, color=BOUNDARY_EDGE, linewidth=0.8, alpha=0.7)

    if layer_type == "buildings":
        gdf.plot(ax=ax, color=color, linewidth=0, alpha=0.9)
    elif layer_type == "roads":
        is_major = gdf["highway"].isin(MAJOR_ROADS)
        if (~is_major).any():
            gdf[~is_major].plot(ax=ax, color=color, linewidth=0.3, alpha=0.6)
        if is_major.any():
            gdf[is_major].plot(ax=ax, color=color, linewidth=1.0, alpha=0.95)
    else:
        gdf.plot(ax=ax, color=color, linewidth=0.7, alpha=0.9)

    ax.set_xlim(extent[0], extent[2])
    ax.set_ylim(extent[1], extent[3])
    save_figure(fig, output_image_path, dpi=200)
    print(f"Layer image saved: {output_image_path}")
    return output_image, geojson_path
