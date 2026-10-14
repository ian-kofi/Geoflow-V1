"""Checks GeoFlow's Flood risk map against the Environment Agency's official flood zones.

For a place in England, this runs the same node code the app uses, connected exactly like the
Flood risk template. It then downloads the Environment Agency's Flood Zones 2 and 3 for the same
area and compares the two, cell by cell, on the same 30 m grid.

What it measures:
    ROC AUC     how well GeoFlow's score ranks flood zone land above dry land. 0.5 is no better
                than guessing and 1.0 is perfect. It doesn't depend on where the class breaks are.
    classes     how the Low, Moderate and High classes line up with the flood zones
    comparisons the same numbers for the method from before mapped rivers were added, for
                height above river on its own, and for a simple "lowest ground floods first" rule

The results go into a JSON file and two pictures (an agreement map and the ranking curves).

Usage (from geoflow-backend/):
    .venv/Scripts/python.exe -m validation.ea_flood_zones --place York --country GB \
        --match "York and North Yorkshire" --out ../docs/validation
"""
import argparse
import glob
import json
import os
import re

import geopandas as gpd
import numpy as np
import requests
from matplotlib.colors import ListedColormap
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from rasterio.features import rasterize
from scipy.stats import rankdata

from boundary_fetcher import fetch_city_boundary
from geocoder import search_places
from layer_fetcher import fetch_layer
from main import _clean_place
from spatial import HANDLERS, Context
from spatial.raster_io import read_raster

EA_ITEMS = ("https://environment.data.gov.uk/spatialdata/flood-map-for-planning-flood-zones/ogc/features/v1/"
            "collections/Flood_Zones_2_3_Rivers_and_Sea/items")
TAG = "eaval"                       # every file this script writes has this in its name, and is deleted at the end
CLASS_NAMES = {1: "Low", 2: "Moderate", 3: "High"}

# The Flood risk template's settings (from geoflow-project/src/workflow/recipes.js), and the
# settings from before mapped rivers were added.
VARIANTS = {
    "current": {"label": "GeoFlow (current)", "rivers": True,
                "hand": {"minArea": "1", "terrainStreams": "auto"}, "rangeA": "0, 10"},
    "before": {"label": "Before mapped rivers", "rivers": False,
               "hand": {"minArea": "1"}, "rangeA": "0, 15"},
}
OVERLAY = {"resultName": "Flood susceptibility", "weightA": "5", "riskA": "low", "weightB": "2", "riskB": "low",
           "rangeB": "0, 8", "weightC": "3", "riskC": "high", "rangeC": "0, 25", "weightD": "0"}
CLASSES = {"method": "manual", "breaks": "0.4, 0.65", "labels": "Low, Moderate, High"}


def run(node_type, tag, parents=(), **params):
    """Runs one node the same way main.py does. `parents` are the results of earlier nodes."""
    ctx = Context(node_type=node_type, params=params, parents=list(parents), tag=f"{TAG}{tag}",
                  location=PLACE["name"], place=PLACE)
    return HANDLERS[node_type](ctx)


def into(output, handle):
    """A result marked as plugged into a named input, such as "mask" or "A"."""
    return {**output, "_input": handle}


def ea_flood_zones(bounds):
    """The Environment Agency's Flood Zone 2 and 3 shapes inside [south, north, west, east].

    The service sends 100 shapes at a time, so this follows its "next" links until it has them all.
    """
    south, north, west, east = bounds
    url = f"{EA_ITEMS}?f=json&limit=100&bbox={west},{south},{east},{north}"
    features = []
    while url:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        page = response.json()
        features += page["features"]
        url = next((link["href"] for link in page.get("links", []) if link["rel"] == "next"), None)
    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def burn(gdf, raster):
    """True for the raster's cells whose centre is inside any of the shapes."""
    if gdf.empty:
        return np.zeros(raster.data.shape[1:], dtype=bool)
    shapes = ((geom, 1) for geom in gdf.to_crs(raster.crs).geometry if geom is not None and not geom.is_empty)
    return rasterize(shapes, out_shape=raster.data.shape[1:], transform=raster.transform, fill=0,
                     dtype="uint8").astype(bool)


def auc(score, truth):
    """The chance that a random flood zone cell scores higher than a random dry cell (ROC AUC).

    Worked out from the ranks of the scores (the Mann-Whitney method). Equal scores count as half.
    """
    ranks = rankdata(score)
    positives = int(truth.sum())
    negatives = truth.size - positives
    return float((ranks[truth].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def roc_curve(score, truth, points=200):
    """Points for the ROC chart: as more cells are flagged, highest score first, the share of
    dry land flagged (false alarms) against the share of flood zone land flagged (hits)."""
    order = np.argsort(-score, kind="stable")
    hits = np.cumsum(truth[order]) / truth.sum()
    false_alarms = np.cumsum(~truth[order]) / (~truth).sum()
    pick = np.linspace(0, score.size - 1, points).astype(int)
    return np.r_[0, false_alarms[pick]], np.r_[0, hits[pick]]


def main():
    """Runs the check for one place and writes its results and pictures to --out."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--place", default="York")
    parser.add_argument("--country", default="GB")
    parser.add_argument("--match", default="York and North Yorkshire", help="text in the place's full name")
    parser.add_argument("--out", default=os.path.join("..", "docs", "validation"))
    args = parser.parse_args()

    global PLACE
    PLACE = _clean_place(next(p for p in search_places(args.place)
                              if p["countryCode"] == args.country and args.match in p["displayName"]))
    print(f"Place: {PLACE['displayName']}")
    _, outline_path, bounds = fetch_city_boundary(PLACE["name"], PLACE)
    outline = {"boundaryShpPath": outline_path, "boundaryBounds": bounds}
    slug = re.sub(r"[^a-z0-9]+", "-", PLACE["name"].lower()).strip("-")

    try:
        # GeoFlow: inputs shared by both versions of the method
        dem = run("StacNode", "dem", [outline], collection="cop-dem-glo-30")
        water = run("StacNode", "jrc", [outline], collection="jrc-gsw")
        slope = run("SlopeNode", "slope", [dem])
        _, rivers_path = fetch_layer(PLACE["name"], "rivers", bounds, outline_path, f"{TAG}rivers")
        rivers = {"layerGeojsonPath": rivers_path}

        results = {}
        for key, variant in VARIANTS.items():
            hand_parents = [into(dem, "dem")] + ([into(rivers, "rivers")] if variant["rivers"] else [])
            hand = run("HandNode", f"hand{key}", hand_parents, **variant["hand"])
            hand_cut = run("ClipRasterNode", f"handcut{key}", [into(hand, "raster"), into(outline, "mask")])
            score = run("WeightedOverlayNode", f"overlay{key}",
                        [into(hand_cut, "A"), into(slope, "B"), into(water, "C")], rangeA=variant["rangeA"], **OVERLAY)
            classes = run("ReclassifyNode", f"classes{key}", [score], **CLASSES)
            results[key] = {"score": read_raster(score["rasterPath"]), "classes": read_raster(classes["rasterPath"]),
                            "hand": read_raster(hand_cut["rasterPath"]), "details": hand["details"]}
        ground = read_raster(run("ClipRasterNode", "demcut", [into(dem, "raster"), into(outline, "mask")])["rasterPath"])

        # The Environment Agency's flood zones, on the same 30 m grid
        grid = results["current"]["score"]
        zones = ea_flood_zones(bounds)
        print(f"EA Flood Zones: {len(zones)} polygons ({zones['flood_zone'].value_counts().to_dict()})")
        fz3 = burn(zones[zones["flood_zone"] == "FZ3"], grid)
        fz23 = fz3 | burn(zones[zones["flood_zone"] == "FZ2"], grid)
        hand = results["current"]["hand"].data[0]
        inside = np.isfinite(grid.data[0]) & np.isfinite(ground.data[0]) & np.isfinite(hand)
        cell_km2 = abs(grid.transform.a * grid.transform.e) / 1e6

        # The measurements
        report = {"place": PLACE["displayName"], "cells": int(inside.sum()), "cell_km2": cell_km2,
                  "area_km2": float(inside.sum() * cell_km2),
                  "fz3_share": float(fz3[inside].mean()), "fz23_share": float(fz23[inside].mean()),
                  "methods": {}}
        scores = {key: results[key]["score"].data[0][inside] for key in VARIANTS}
        scores["hand"] = -hand[inside]                             # HAND factor on its own (current rivers)
        scores["ground"] = -ground.data[0][inside]                 # naive: lower ground = higher score
        labels = {**{k: v["label"] for k, v in VARIANTS.items()}, "hand": "Height above river (HAND) only",
                  "ground": "Ground height only"}
        for key, values in scores.items():
            entry = {"label": labels[key], "auc_fz3": auc(values, fz3[inside]), "auc_fz23": auc(values, fz23[inside])}
            if key in results:
                codes = np.round(results[key]["classes"].data[0][inside]).astype(int)
                entry["classes"] = {}
                for code, name in CLASS_NAMES.items():
                    cls = codes == code
                    entry["classes"][name] = {
                        "share_of_area": float(cls.mean()),
                        "in_fz3": float(fz3[inside][cls].mean()) if cls.any() else 0.0,
                        "in_fz23": float(fz23[inside][cls].mean()) if cls.any() else 0.0,
                        "of_fz3": float((cls & fz3[inside]).sum() / fz3[inside].sum()),
                        "of_fz23": float((cls & fz23[inside]).sum() / fz23[inside].sum()),
                    }
            report["methods"][key] = entry

        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, f"{slug}-results.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        figures(args.out, slug, PLACE["name"], grid, inside, fz3, fz23, results, scores, labels, report)
        print_summary(report)
    finally:
        cleanup()


def figures(out, slug, name, grid, inside, fz3, fz23, results, scores, labels, report):
    """Draws the agreement map (GeoFlow's Moderate and High against Flood Zones 2 and 3) and the ROC chart."""
    codes = np.round(np.nan_to_num(results["current"]["classes"].data[0], nan=0)).astype(int)
    flagged = codes >= 2
    agreement = np.full(codes.shape, 0)                         # 0 = outside the area
    agreement[inside & ~flagged & ~fz23] = 1                    # both: not at risk
    agreement[inside & flagged & fz23] = 2                      # both: at risk
    agreement[inside & ~flagged & fz23] = 3                     # EA only (missed)
    agreement[inside & flagged & ~fz23] = 4                     # GeoFlow only
    agreement[inside & (codes == 3) & fz3] = 5                  # GeoFlow High inside EA Flood Zone 3
    colours = ["#ffffff", "#ececec", "#7fb3d5", "#e4572e", "#f2c14e", "#1b4f72"]
    names = ["", "Neither", "Both: Moderate/High and Zone 2/3", "EA Zone 2/3 only (missed)",
             "GeoFlow Moderate/High only", "Both: High and Zone 3"]

    fig = Figure(figsize=(8.6, 8.4), dpi=130)
    ax = fig.add_axes([0.02, 0.2, 0.96, 0.72])
    ax.imshow(agreement, cmap=ListedColormap(colours), vmin=0, vmax=5, interpolation="nearest")
    ax.set_axis_off()
    fig.text(0.03, 0.955, f"GeoFlow flood susceptibility vs Environment Agency Flood Zones · {name}",
             fontsize=12.5, weight="bold")
    current = report["methods"]["current"]
    fig.text(0.03, 0.928, f"ROC AUC {current['auc_fz3']:.2f} against Flood Zone 3, {current['auc_fz23']:.2f} against "
             f"Flood Zones 2+3 · 30 m grid", fontsize=10, color="#444")
    fig.legend(handles=[Patch(color=c, label=n) for c, n in zip(colours[1:], names[1:])], loc="lower center",
               ncol=2, frameon=False, fontsize=9.5, bbox_to_anchor=(0.5, 0.06))
    fig.text(0.03, 0.02, "Flood Zones: Environment Agency Flood Map for Planning (rivers and sea), "
             "© Environment Agency, Open Government Licence.", fontsize=7.5, color="#666")
    fig.savefig(os.path.join(out, f"{slug}-agreement.png"), facecolor="white")

    fig = Figure(figsize=(6.2, 5.6), dpi=130)
    ax = fig.add_subplot(111)
    styles = {"current": ("#1b4f72", "-"), "before": ("#e4572e", "--"), "hand": ("#2e9e6b", "-."),
              "ground": ("#888888", ":")}
    for key, values in scores.items():
        x, y = roc_curve(values, fz3[inside])
        colour, line = styles[key]
        ax.plot(x, y, line, color=colour, lw=2, label=f"{labels[key]} (AUC {report['methods'][key]['auc_fz3']:.2f})")
    ax.plot([0, 1], [0, 1], color="#cccccc", lw=1, label="Chance (AUC 0.50)")
    ax.set_xlabel("Share of land outside Flood Zone 3 flagged (false alarms)")
    ax.set_ylabel("Share of Flood Zone 3 flagged (hits)")
    ax.set_title(f"Ranking flood-zone land · {name}", fontsize=11, weight="bold")
    ax.legend(loc="lower right", fontsize=8.5, frameon=False)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(os.path.join(out, f"{slug}-roc.png"), facecolor="white")


def print_summary(report):
    """Prints the results as Markdown tables, ready to paste into VALIDATION.md."""
    print(f"\n{report['place']}: {report['area_km2']:.0f} km², Flood Zone 3 = {100 * report['fz3_share']:.1f}%, "
          f"Zones 2+3 = {100 * report['fz23_share']:.1f}% of the area")
    print("| Method | AUC vs FZ3 | AUC vs FZ2+3 |\n|---|---|---|")
    for entry in report["methods"].values():
        print(f"| {entry['label']} | {entry['auc_fz3']:.3f} | {entry['auc_fz23']:.3f} |")
    for key in VARIANTS:
        entry = report["methods"][key]
        print(f"\n{entry['label']}\n| Class | Share of area | In FZ3 | In FZ2+3 | Share of FZ3 | Share of FZ2+3 |")
        print("|---|---|---|---|---|---|")
        for name, c in entry["classes"].items():
            print(f"| {name} | {100 * c['share_of_area']:.1f}% | {100 * c['in_fz3']:.1f}% | {100 * c['in_fz23']:.1f}% "
                  f"| {100 * c['of_fz3']:.1f}% | {100 * c['of_fz23']:.1f}% |")


def cleanup():
    """Deletes the rasters, previews and styles this script made along the way (they all have TAG in their names)."""
    for folder in ("files", "outputs"):
        for path in glob.glob(os.path.join(folder, "**", f"*_{TAG}*"), recursive=True):
            if os.path.isfile(path):
                os.remove(path)


PLACE = None

if __name__ == "__main__":
    main()
