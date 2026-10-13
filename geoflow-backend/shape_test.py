import os
import zipfile
from functools import lru_cache
from io import BytesIO

import requests
import geopandas as gpd

from plotting import BOUNDARY_EDGE, new_map_figure, save_figure

NE_DIR = os.path.join("files", "ne_10m_admin_0_countries")
NE_SHP = os.path.join(NE_DIR, "ne_10m_admin_0_countries.shp")
NE_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"


def _ensure_countries_file():
    """Downloads Natural Earth countries once if the user has not uploaded them."""
    if os.path.exists(NE_SHP):
        return
    print("Natural Earth countries not found — downloading...")
    response = requests.get(NE_URL, headers={"User-Agent": "GeoFlowApp/1.0"}, timeout=120)
    response.raise_for_status()
    os.makedirs(NE_DIR, exist_ok=True)
    with zipfile.ZipFile(BytesIO(response.content)) as z:
        z.extractall(NE_DIR)


@lru_cache(maxsize=1)
def _load_countries(mtime):
    # Keyed on mtime so an uploaded replacement is picked up.
    return gpd.read_file(NE_SHP)


def _match(df, location):
    wanted = location.strip().lower()
    for col in ("ADMIN", "NAME", "NAME_LONG", "SOVEREIGNT"):
        if col in df.columns:
            exact = df[df[col].str.lower() == wanted]
            if not exact.empty:
                return exact
    return df[df["SOVEREIGNT"].str.contains(location, case=False, na=False, regex=False)]


def plot_country(location, tag=""):
    _ensure_countries_file()
    df = _match(_load_countries(os.path.getmtime(NE_SHP)), location)
    if df.empty:
        raise ValueError(f"No country matching '{location}' in Natural Earth")

    fig, ax = new_map_figure(df.total_bounds, transparent=True)
    df.plot(ax=ax, color="#6d4aff", edgecolor=BOUNDARY_EDGE, linewidth=0.8)

    output_filename = f"result_{tag}.svg" if tag else "result.svg"
    output_path = os.path.join("outputs", output_filename)
    save_figure(fig, output_path, transparent=True, fmt="svg")
    return output_filename
