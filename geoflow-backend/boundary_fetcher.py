import os
import re
import json
import time
import zipfile
import unicodedata
from functools import lru_cache

import requests
import geopandas as gpd
import osmnx as ox

from geocoder import enclosing_area
from plotting import (BOUNDARY_EDGE, BOUNDARY_FILL, atomic_write_bytes, is_fresh,
                      new_map_figure, plot_tolerance, save_figure)

HEADERS = {"User-Agent": "GeoFlowApp/1.0"}


COUNTRY_INDEX_URL = "https://www.geoboundaries.org/api/current/gbOpen/ALL/ADM0/"
COUNTRY_INDEX_PATH = os.path.join("files", "_geoboundaries_countries.json")
COUNTRY_INDEX_MAX_AGE = 30 * 24 * 3600

# geoBoundaries uses formal UN names; map common short names to ISO3.
COUNTRY_ALIASES = {
    "usa": "USA", "us": "USA", "united states": "USA", "america": "USA",
    "uk": "GBR", "britain": "GBR", "great britain": "GBR",
    "ivory coast": "CIV", "drc": "COD", "dr congo": "COD", "congo kinshasa": "COD",
    "congo brazzaville": "COG", "south korea": "KOR", "north korea": "PRK",
    "laos": "LAO", "turkey": "TUR", "czech republic": "CZE", "czechia": "CZE",
    "swaziland": "SWZ", "eswatini": "SWZ", "burma": "MMR", "cape verde": "CPV",
    "east timor": "TLS", "vatican": "VAT", "holland": "NLD",
}


def _normalize(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@lru_cache(maxsize=1)
def _country_index():
    """[(normalized name, ISO3)] from geoBoundaries, cached on disk for 30 days."""
    fresh = (os.path.exists(COUNTRY_INDEX_PATH)
             and time.time() - os.path.getmtime(COUNTRY_INDEX_PATH) < COUNTRY_INDEX_MAX_AGE)
    if not fresh:
        try:
            response = requests.get(COUNTRY_INDEX_URL, headers=HEADERS, timeout=60)
            response.raise_for_status()
            entries = [{"name": d["boundaryName"], "iso3": d["boundaryISO"]} for d in response.json()]
            atomic_write_bytes(COUNTRY_INDEX_PATH, json.dumps(entries).encode())
        except (requests.RequestException, ValueError, KeyError) as e:
            if not os.path.exists(COUNTRY_INDEX_PATH):
                raise ValueError(f"Country index unavailable: {e}")
    with open(COUNTRY_INDEX_PATH, encoding="utf-8") as f:
        return [(_normalize(e["name"]), e["iso3"]) for e in json.load(f)]


@lru_cache(maxsize=256)
def get_country_codes(country_name):
    """Returns (alpha2, alpha3); alpha2 is None (only ISO3 is used downstream).
    Exact matches win so that 'Niger' doesn't resolve to Nigeria or 'Guinea' to
    Papua New Guinea. Raises ValueError for non-countries such as city names."""
    wanted = _normalize(country_name)
    if wanted in COUNTRY_ALIASES:
        return None, COUNTRY_ALIASES[wanted]

    index = _country_index()
    compact = wanted.replace(" ", "")
    for name, iso3 in index:
        if wanted == name or wanted == iso3.lower() or compact == name.replace(" ", ""):
            return None, iso3

    # "Russia" → "Russian Federation", "Iran" → "Iran (Islamic Republic of)", "Tanzania" → "United Republic of Tanzania"
    # Word-prefix match only, so city names like "Mexico City" still fall through to OSM.
    candidates = [(name, iso3) for name, iso3 in index if f" {wanted}" in f" {name}"] if len(wanted) >= 4 else []
    if candidates:
        return None, min(candidates, key=lambda c: len(c[0]))[1]
    raise ValueError(f"Country '{country_name}' not found")


def _bounds_of(gdf):
    bounds = gdf.total_bounds
    return [float(bounds[1]), float(bounds[3]), float(bounds[0]), float(bounds[2])]


def _safe_name(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "place"


def plot_boundary(gdf, country_name, prefix, source_path=None):
    os.makedirs("outputs", exist_ok=True)
    output_filename = f"{prefix}_boundary.png"
    output_path = os.path.join("outputs", output_filename)

    # Plotting large admin datasets is the slow part; reuse the previous render if the data is unchanged.
    if source_path and is_fresh(output_path, source_path):
        print(f"Boundary plot reused: {output_path}")
        return output_filename

    bounds = gdf.total_bounds
    plot_gdf = gdf.copy()
    plot_gdf["geometry"] = gdf.geometry.simplify(plot_tolerance(bounds), preserve_topology=True)

    fig, ax = new_map_figure(bounds)
    edge_width = 1.2 if len(gdf) < 20 else 0.6 if len(gdf) < 300 else 0.3
    plot_gdf.plot(ax=ax, color=BOUNDARY_FILL, edgecolor=BOUNDARY_EDGE, linewidth=edge_width)
    save_figure(fig, output_path, dpi=150)
    print(f"Boundary plot saved: {output_path}")
    return output_filename


def _write_geojson(gdf, path):
    if os.path.exists(path):
        os.remove(path)
    gdf.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=6)


def fetch_geoboundaries(country_name, admin_level=0):
    print(f"Fetching GeoBoundaries for {country_name} at admin level {admin_level}...")
    try:
        alpha2, alpha3 = get_country_codes(country_name)
    except ValueError:
        print(f"'{country_name}' not a country — falling back to OSMnx")
        return fetch_city_boundary(country_name)

    os.makedirs("files", exist_ok=True)
    geojson_path = os.path.join("files", f"{alpha3}_ADM{admin_level}.geojson")

    if os.path.exists(geojson_path):
        print(f"Using cached GeoBoundaries file: {geojson_path}")
    else:
        url = f"https://www.geoboundaries.org/api/current/gbOpen/{alpha3}/ADM{admin_level}/"
        response = requests.get(url, headers=HEADERS, timeout=30)
        if response.status_code != 200:
            raise ValueError(f"GeoBoundaries has no ADM{admin_level} data for {country_name} "
                             f"(HTTP {response.status_code})")

        geojson_url = response.json().get("gjDownloadURL")
        if not geojson_url:
            raise ValueError("No GeoJSON URL found")

        geojson_response = requests.get(geojson_url, headers=HEADERS, timeout=120)
        geojson_response.raise_for_status()
        atomic_write_bytes(geojson_path, geojson_response.content)

    gdf = gpd.read_file(geojson_path).to_crs(epsg=4326)
    boundary_bounds = _bounds_of(gdf)
    output_filename = plot_boundary(gdf, country_name, f"geoboundaries_{alpha3}_ADM{admin_level}", geojson_path)
    return output_filename, geojson_path, boundary_bounds


def fetch_gadm(country_name, admin_level=0):
    print(f"Fetching GADM for {country_name} at admin level {admin_level}...")
    alpha2, alpha3 = get_country_codes(country_name)

    os.makedirs("files", exist_ok=True)
    extract_path = os.path.join("files", f"gadm_{alpha3}")
    # GeoJSON (rather than the raw .shp) so the frontend map can display it directly.
    geojson_path = os.path.join(extract_path, f"gadm41_{alpha3}_{admin_level}.geojson")

    if not os.path.exists(geojson_path):
        zip_path = os.path.join("files", f"gadm41_{alpha3}.zip")
        if not os.path.exists(zip_path):
            url = f"https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_{alpha3}_shp.zip"
            response = requests.get(url, headers=HEADERS, timeout=120, stream=True)
            if response.status_code != 200:
                raise ValueError(f"GADM returned {response.status_code}")
            part_path = zip_path + ".part"
            with open(part_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
            os.replace(part_path, zip_path)

        os.makedirs(extract_path, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_path)

        shp_files = sorted(f for f in os.listdir(extract_path) if f.endswith(".shp"))
        shp_file = next((f for f in shp_files if f.endswith(f"_{admin_level}.shp")), None)
        if not shp_file:
            levels = sorted(f.rsplit("_", 1)[-1][:-4] for f in shp_files)
            raise ValueError(f"No GADM shapefile for admin level {admin_level} "
                             f"(available levels: {', '.join(levels) or 'none'})")

        gdf = gpd.read_file(os.path.join(extract_path, shp_file)).to_crs(epsg=4326)
        _write_geojson(gdf, geojson_path)
    else:
        print(f"Using cached GADM file: {geojson_path}")
        gdf = gpd.read_file(geojson_path)

    boundary_bounds = _bounds_of(gdf)
    output_filename = plot_boundary(gdf, country_name, f"gadm_{alpha3}_{admin_level}", geojson_path)
    return output_filename, geojson_path, boundary_bounds


def _geocode_place(place):
    """Polygon for a place picked in the Location dropdown (exact OSM object, no name guessing)."""
    if place.get("osmType") in ("relation", "way"):
        return ox.geocode_to_gdf(place["id"], by_osmid=True)
    # Picked a point (many towns are mapped only as a centre node): use the
    # smallest city/district outline that contains it.
    area_id, area_name = enclosing_area(place["lat"], place["lon"])
    if not area_id:
        raise ValueError(f"OpenStreetMap has no boundary polygon around '{place['name']}'. "
                         "Pick a district or region entry from the Location list instead.")
    print(f"'{place['name']}' is a point in OpenStreetMap — using enclosing area: {area_name}")
    return ox.geocode_to_gdf(area_id, by_osmid=True)


def fetch_city_boundary(city_name, place=None):
    print(f"Fetching city boundary for {city_name}...")
    os.makedirs("files", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)
    # The OSM id keeps same-named places (e.g. two "Tema"s) from sharing a cache file.
    safe_name = _safe_name(city_name) + (f"_{place['id']}" if place else "")
    geojson_path = os.path.join("files", f"{safe_name}_boundary.geojson")

    if os.path.exists(geojson_path):
        print(f"Using cached city boundary: {geojson_path}")
        gdf = gpd.read_file(geojson_path)
    else:
        gdf = (_geocode_place(place) if place else ox.geocode_to_gdf(city_name)).to_crs(epsg=4326)
        gdf = gdf[["display_name", "geometry"]] if "display_name" in gdf.columns else gdf[["geometry"]]
        _write_geojson(gdf, geojson_path)

    boundary_bounds = _bounds_of(gdf)
    output_filename = plot_boundary(gdf, city_name, safe_name, geojson_path)
    return output_filename, geojson_path, boundary_bounds
