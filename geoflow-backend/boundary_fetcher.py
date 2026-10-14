"""Outlines (borders) for the Outline node.

There are three sources:
    geoBoundaries   official country, region and district borders (the default for countries)
    GADM            a second set of country borders, used if someone prefers it
    OpenStreetMap   the outline of a town, city, district or national park

Every function returns the same three things: the name of a preview picture in outputs/, the
path of the GeoJSON file with the outline, and its extent as [south, north, west, east].
Downloads are saved in files/ and reused next time.
"""
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


# The list of every country geoBoundaries has, used to turn a country name into its code.
COUNTRY_INDEX_URL = "https://www.geoboundaries.org/api/current/gbOpen/ALL/ADM0/"
COUNTRY_INDEX_PATH = os.path.join("files", "_geoboundaries_countries.json")
COUNTRY_INDEX_MAX_AGE = 30 * 24 * 3600   # download it again after 30 days

# geoBoundaries uses the formal UN names, so common everyday names are looked up here first
# and turned into the three letter ISO code.
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
    """Lower case, no accents, no punctuation, so "Côte d'Ivoire" matches "cote d ivoire"."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@lru_cache(maxsize=1)
def _country_index():
    """Every country geoBoundaries knows, as a list of (simplified name, ISO3 code).

    The list is kept on disk for 30 days. If it can't be refreshed, the old copy is used.
    """
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
    """Finds the ISO code for a country name. Returns (None, ISO3).

    The first value used to be the two letter code. Nothing needs it any more, so it's always
    None. Exact matches are tried first, so "Niger" doesn't become Nigeria and "Guinea" doesn't
    become Papua New Guinea. Raises ValueError if the name isn't a country, for example a city.
    """
    wanted = _normalize(country_name)
    if wanted in COUNTRY_ALIASES:
        return None, COUNTRY_ALIASES[wanted]

    index = _country_index()
    compact = wanted.replace(" ", "")
    for name, iso3 in index:
        if wanted == name or wanted == iso3.lower() or compact == name.replace(" ", ""):
            return None, iso3

    # Next, look for the name as a whole word inside an official name. That's how "Russia" finds
    # "Russian Federation" and "Tanzania" finds "United Republic of Tanzania". It has to match from
    # the start of a word, so a city like "Mexico City" isn't mistaken for Mexico.
    candidates = [(name, iso3) for name, iso3 in index if f" {wanted}" in f" {name}"] if len(wanted) >= 4 else []
    if candidates:
        return None, min(candidates, key=lambda c: len(c[0]))[1]
    raise ValueError(f"Country '{country_name}' not found")


def _bounds_of(gdf):
    """The extent of the shapes as [south, north, west, east], the order the rest of the app uses."""
    bounds = gdf.total_bounds
    return [float(bounds[1]), float(bounds[3]), float(bounds[0]), float(bounds[2])]


def _safe_name(text):
    """A place name turned into something safe to use in a file name."""
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "place"


def plot_boundary(gdf, country_name, prefix, source_path=None):
    """Draws the outline as a PNG preview for the node and returns its file name."""
    os.makedirs("outputs", exist_ok=True)
    output_filename = f"{prefix}_boundary.png"
    output_path = os.path.join("outputs", output_filename)

    # Drawing a country split into hundreds of districts is slow, so if the picture already
    # exists and the data hasn't changed since, reuse it.
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
    """Saves shapes as GeoJSON, rounded to 6 decimal places (about 10 cm) to keep files small."""
    if os.path.exists(path):
        os.remove(path)
    gdf.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=6)


def fetch_geoboundaries(country_name, admin_level=0):
    """Country borders from geoBoundaries.

    admin_level 0 is the whole country, 1 its regions, 2 districts and so on. If the name turns
    out not to be a country, this falls back to the OpenStreetMap outline instead.
    """
    print(f"Fetching GeoBoundaries for {country_name} at admin level {admin_level}...")
    try:
        alpha2, alpha3 = get_country_codes(country_name)
    except ValueError:
        print(f"'{country_name}' is not a country, so trying OpenStreetMap instead")
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
    """Country borders from GADM 4.1.

    GADM sends a zip of shapefiles for all levels at once. The zip is downloaded once and the
    level we need is converted to GeoJSON.
    """
    print(f"Fetching GADM for {country_name} at admin level {admin_level}...")
    alpha2, alpha3 = get_country_codes(country_name)

    os.makedirs("files", exist_ok=True)
    extract_path = os.path.join("files", f"gadm_{alpha3}")
    # Converted to GeoJSON because that's what the map in the browser can show.
    geojson_path = os.path.join(extract_path, f"gadm41_{alpha3}_{admin_level}.geojson")

    if not os.path.exists(geojson_path):
        zip_path = os.path.join("files", f"gadm41_{alpha3}.zip")
        if not os.path.exists(zip_path):
            url = f"https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_{alpha3}_shp.zip"
            response = requests.get(url, headers=HEADERS, timeout=120, stream=True)
            if response.status_code != 200:
                raise ValueError(f"GADM returned {response.status_code}")
            # Download to a temporary name first, so a broken download never looks finished
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
    """The outline of a place picked from the Place node's list.

    We ask OpenStreetMap for that exact object by its id, rather than searching by name again.
    """
    if place.get("osmType") in ("relation", "way"):
        return ox.geocode_to_gdf(place["id"], by_osmid=True)
    # Many towns are only mapped as a single point in their centre, which has no outline.
    # In that case use the smallest town or district area that contains the point.
    area_id, area_name = enclosing_area(place["lat"], place["lon"])
    if not area_id:
        raise ValueError(f"OpenStreetMap has no boundary polygon around '{place['name']}'. "
                         "Pick a district or region from the Place list instead.")
    print(f"'{place['name']}' is a point in OpenStreetMap, so using the area around it: {area_name}")
    return ox.geocode_to_gdf(area_id, by_osmid=True)


def fetch_city_boundary(city_name, place=None):
    """The OpenStreetMap outline of a town, city, district, park or other named area.

    If `place` is given (the entry picked in the Place node), that exact place is used.
    Otherwise the name is searched for and the first match is used.
    """
    print(f"Fetching city boundary for {city_name}...")
    os.makedirs("files", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)
    # Adding the OpenStreetMap id to the file name stops two places with the same name (there
    # is more than one Tema, for example) from sharing a saved file.
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
