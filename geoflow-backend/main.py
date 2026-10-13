import os
import json
import re
import time
import shutil
import mimetypes
import traceback
from urllib.parse import quote, unquote

import matplotlib
matplotlib.use("Agg")  # headless backend; must be set before any plotting module is imported

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.gzip import GZipMiddleware

from shape_test import plot_country
from rasterizer import svgToRaster
from layer_fetcher import fetch_layer
from satellite_fetcher import fetch_satellite
from boundary_fetcher import fetch_geoboundaries, fetch_gadm, fetch_city_boundary
from compositor import composite_geodata
from clipper import TILE_CACHE_HEADERS, clip_satellite, clipped_tile
from geocoder import search_places
from exporter import export_jpeg
import spatial

BASE_URL = os.environ.get("GEOFLOW_BASE_URL", "http://localhost:8000")
PARAM_KEYS = {"nodeType", "nodeId", "locations", "parentOutputs", "satelliteZoom", "layerType",
              "boundarySource", "boundaryAdminLevel", "alpha", "dpi", "clipToBoundary"} | spatial.PARAM_KEYS
RASTER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

# StaticFiles refuses to mount a missing directory, so create them up front.
for folder in ("outputs", "files", "uploads"):
    os.makedirs(folder, exist_ok=True)
mimetypes.add_type("application/geo+json", ".geojson")

app = FastAPI(title="GeoFlow")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   # Extra origins, comma-separated (e.g. if the frontend runs on another port)
                   *[o.strip() for o in os.environ.get("GEOFLOW_CORS_ORIGINS", "").split(",") if o.strip()]],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
# GeoJSON compresses ~5-10x; images are already compressed so only /files is gzipped.
app.mount("/files", GZipMiddleware(StaticFiles(directory="files"), minimum_size=1024), name="files")


class NodeError(Exception):
    """A problem with the node's inputs, reported to the user as-is."""


def _parse_json(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default


def _int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(float(value))))
    except (TypeError, ValueError):
        return default


def _bool(value, default):
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _clean_place(place):
    """Validates a place object sent back by the client (from /geocode) before it is used."""
    if not isinstance(place, dict):
        return None
    try:
        osm_id = str(place["id"])
        osm_type = str(place["osmType"])
        if not re.fullmatch(r"[NWR]\d{1,12}", osm_id) or osm_type not in ("node", "way", "relation"):
            return None
        bbox = place.get("bbox")
        bbox = [float(v) for v in bbox] if isinstance(bbox, list) and len(bbox) == 4 else None
        text = lambda key, limit=300: str(place.get(key) or "").strip()[:limit] or None
        return {
            "id": osm_id,
            "osmType": osm_type,
            "name": text("name", 120) or osm_id,
            "displayName": text("displayName") or text("name", 120) or osm_id,
            "kind": text("kind", 40) or "place",
            "isCountry": bool(place.get("isCountry")),
            "country": text("country", 120),
            "countryCode": text("countryCode", 3),
            "bbox": bbox,
            "lat": float(place["lat"]),
            "lon": float(place["lon"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _safe_tag(node_id, node_type):
    """Per-node filename suffix; drops the 'satellite_' style prefix so names don't repeat it."""
    tag = re.sub(r"[^A-Za-z0-9_-]", "", str(node_id or ""))[:40]
    prefix = str(node_type or "").replace("Node", "").lower() + "_"
    return tag[len(prefix):] if tag.lower().startswith(prefix) and len(tag) > len(prefix) else tag


def _safe_relpath(name):
    parts = [p for p in str(name or "").replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return os.path.join(*parts) if parts else None


def _within(path, folder):
    """Paths come back from the client, so only accept ones inside our data folders."""
    if not path:
        return None
    full = os.path.abspath(path)
    root = os.path.abspath(folder)
    return path if os.path.commonpath([full, root]) == root and os.path.exists(full) else None


def _versioned_url(folder, path):
    rel = os.path.relpath(path, folder).replace(os.sep, "/")
    return f"{BASE_URL}/{folder}/{rel}?v={os.stat(path).st_mtime_ns}"


def _output_url(filename):
    return _versioned_url("outputs", os.path.join("outputs", filename))


def _url_to_output_path(url):
    if not url or "/outputs/" not in url:
        return None
    filename = os.path.basename(unquote(url.split("/outputs/")[-1].split("?")[0]))
    return _within(os.path.join("outputs", filename), "outputs")


def _save_upload(upload, save_path):
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    upload.file.seek(0)
    with open(save_path, "wb") as f:
        shutil.copyfileobj(upload.file, f, length=1 << 20)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/export/jpeg")
async def export_map_jpeg(request: Request):
    """A finished JPEG of a result: title, picture, north arrow, scale bar (when known) and colour key."""
    body = await request.json()
    image_path = _url_to_output_path(body.get("imageUrl"))
    if not image_path:
        return JSONResponse(status_code=400, content={"detail": "Run the node first: there is no picture to export yet."})
    title = str(body.get("title") or "GeoFlow map").strip()[:120]
    subtitle = str(body.get("subtitle") or "").strip()[:200]
    legend = body.get("legend") if isinstance(body.get("legend"), dict) else None
    bounds = body.get("bounds") if isinstance(body.get("bounds"), list) else None
    content = await run_in_threadpool(export_jpeg, image_path, title, subtitle, legend, bounds)
    filename = re.sub(r"[^A-Za-z0-9 _-]+", "", title).strip().replace(" ", "_") or "geoflow_map"
    return Response(content=content, media_type="image/jpeg",
                    headers={"Content-Disposition": f'attachment; filename="{filename}.jpg"'})


@app.get("/geocode")
def geocode(q: str = ""):
    """Candidate places for the Location node's dropdown."""
    try:
        return {"results": search_places(q[:200])}
    except Exception as e:
        return JSONResponse(status_code=502, content={"results": [], "detail": f"Place search failed: {e}"})


@app.get("/raster-tiles/{z}/{x}/{y}.png")
def raster_tile(z: int, x: int, y: int, style: str):
    """Map tile of a raster result, rendered on demand from its GeoTIFF + saved style."""
    rel = _safe_relpath(style)
    path = _within(os.path.join("files", rel), "files") if rel else None
    if not path or not path.endswith(".json") or not (0 <= z <= 22 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return Response(status_code=404)
    content = spatial.render_tile(path, z, x, y, safe_path=lambda p: _within(p, "files"))
    return Response(content=content, media_type="image/png", headers=spatial.TILE_HEADERS)


@app.get("/tiles/{z}/{x}/{y}.png")
def boundary_tile(z: int, x: int, y: int, boundary: str):
    """Esri imagery tile masked to a boundary file, for zoomable clipped imagery on the map.
    Sync on purpose: FastAPI runs it in the thread pool, so slow tile downloads don't block."""
    rel = _safe_relpath(boundary)
    path = _within(os.path.join("files", rel), "files") if rel else None
    if not path or not (0 <= z <= 19 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return Response(status_code=404)
    content, media_type = clipped_tile(z, x, y, path)
    return Response(content=content, media_type=media_type, headers=TILE_CACHE_HEADERS)


@app.post("/upload")
async def upload_files(request: Request):
    started = time.perf_counter()
    form = await request.form()

    node_type = form.get("nodeType")
    node_id = form.get("nodeId")
    tag = _safe_tag(node_id, node_type)
    parent_outputs = _parse_json(form.get("parentOutputs"), [])
    parent_outputs = [p for p in parent_outputs if isinstance(p, dict)] if isinstance(parent_outputs, list) else []

    print(f"Processing node: {node_id} ({node_type}) with {len(parent_outputs)} parent output(s)")

    received_files = 0
    location = None
    svg_path = None
    boundary_shp_path = None
    boundary_bounds = None
    output_url = None
    output_filename = None
    layer_geojson_path = None
    layer_type = None
    actual_sat_bounds = None
    satellite_tiles_url = None
    spatial_outputs = {}

    # Location: this node's own value first, then the first parent that has one
    if "locations" in form:
        locations_data = _parse_json(form.get("locations"), None)
        if isinstance(locations_data, dict):
            location = next((v for v in locations_data.values() if v), None)
        elif isinstance(locations_data, list):
            location = next((v for v in locations_data if v), None)
        elif isinstance(locations_data, str):
            location = locations_data
    if not location:
        location = next((p["location"] for p in parent_outputs if p.get("location")), None)
    location = str(location).strip() or None if location else None
    # The exact place picked in the Location dropdown, if any (disambiguates names like "Tema")
    place = _clean_place(next((p["place"] for p in parent_outputs if isinstance(p.get("place"), dict)), None))
    if place and not location:
        location = place["name"]

    # Uploaded files
    upload_dir = os.path.join("uploads", tag) if tag else "uploads"
    saved_uploads = []
    for key in form.keys():
        if key in PARAM_KEYS:
            continue
        for upload in form.getlist(key):
            if not hasattr(upload, "file"):
                continue
            if key.startswith("geo_"):
                rel = _safe_relpath(upload.filename) or _safe_relpath(key[4:])
                if not rel:
                    continue
                save_path = os.path.join("files", rel)
            else:
                name = os.path.basename(_safe_relpath(upload.filename) or "")
                if not name:
                    continue
                if not saved_uploads and tag and os.path.isdir(upload_dir):
                    # A new selection replaces this node's previous upload (kept per node so it
                    # can be reused after a page reload, when the browser no longer has the file).
                    await run_in_threadpool(shutil.rmtree, upload_dir, True)
                save_path = os.path.join(upload_dir, name)
                saved_uploads.append(save_path)
            await run_in_threadpool(_save_upload, upload, save_path)
            print(f"File saved: {save_path}")
            received_files += 1

    def first_parent(key):
        return next((p[key] for p in parent_outputs if p.get(key)), None)

    def require_location():
        if not location:
            raise NodeError(f"{node_type} needs a location — connect a Location node upstream.")

    try:
        if node_type == "BoundaryNode":
            require_location()
            boundary_source = form.get("boundarySource") or "geoboundaries"
            boundary_admin_level = _int(form.get("boundaryAdminLevel"), 0, 0, 5)
            if place and not place["isCountry"] and boundary_source != "city":
                # Country admin datasets don't apply to a picked city/district; use its own outline.
                print(f"'{place['name']}' is a {place['kind']}, not a country — using its OpenStreetMap boundary")
                boundary_source = "city"
            country = place["name"] if place and place["isCountry"] else location
            if boundary_source == "geoboundaries":
                result = await run_in_threadpool(fetch_geoboundaries, country, admin_level=boundary_admin_level)
            elif boundary_source == "gadm":
                result = await run_in_threadpool(fetch_gadm, country, admin_level=boundary_admin_level)
            elif boundary_source == "city":
                result = await run_in_threadpool(fetch_city_boundary, location, place)
            else:
                raise NodeError(f"Unknown boundary source '{boundary_source}'")
            output_filename, boundary_shp_path, boundary_bounds = result
            output_url = _output_url(output_filename)

        elif node_type == "SatelliteNode":
            satellite_zoom = _int(form.get("satelliteZoom"), 7, 0, 19)
            sat_bounds = first_parent("boundaryBounds") or (place and place["bbox"])
            if not location and not sat_bounds:
                require_location()
            output_filename, actual_sat_bounds = await run_in_threadpool(
                fetch_satellite, location or "selected area", satellite_zoom, sat_bounds, tag)

            clip_path = _within(first_parent("boundaryShpPath"), "files")
            if clip_path and _bool(form.get("clipToBoundary"), True):
                mosaic_path = os.path.join("outputs", output_filename)
                output_filename, actual_sat_bounds = await run_in_threadpool(
                    clip_satellite, mosaic_path, actual_sat_bounds, clip_path, tag)
                boundary_rel = quote(os.path.relpath(clip_path, "files").replace(os.sep, "/"))
                satellite_tiles_url = f"{BASE_URL}/tiles/{{z}}/{{x}}/{{y}}.png?boundary={boundary_rel}"
            output_url = _output_url(output_filename)

        elif node_type == "LayerNode":
            layer_type = form.get("layerType") or "roads"
            layer_bounds = first_parent("boundaryBounds") or (place and place["bbox"])
            clip_path = _within(first_parent("boundaryShpPath"), "files")
            if not location and not layer_bounds:
                require_location()
            output_filename, layer_geojson_path = await run_in_threadpool(
                fetch_layer, location or "selected area", layer_type, layer_bounds, clip_path, tag)
            output_url = _output_url(output_filename)

        elif node_type == "GeoFileNode":
            require_location()
            # Natural Earth is country-level, so a picked city plots its country.
            country = (place["country"] or place["name"]) if place else location
            output_filename = await run_in_threadpool(plot_country, country, tag)
            svg_path = os.path.join("outputs", output_filename)
            output_url = _output_url(output_filename)

        elif node_type == "RasterizerNode":
            dpi_selection = _int(form.get("dpi"), 300, 36, 1200)
            for parent_output in parent_outputs:
                parent_svg = _within(parent_output.get("svgPath"), "outputs")
                parent_file = _url_to_output_path(parent_output.get("outputImageUrl"))
                if parent_svg:
                    svg_path = parent_svg
                    break
                if parent_file and parent_file.lower().endswith(".svg"):
                    svg_path = parent_file
                    break
                if parent_file and parent_file.lower().endswith(RASTER_EXTENSIONS):
                    output_filename = os.path.basename(parent_file)
                    output_url = parent_output["outputImageUrl"]
                    print(f"Parent is already raster, passing through: {output_url}")
                    break

            if svg_path:
                output_filename = await run_in_threadpool(svgToRaster, svg_path, dpi_selection, tag)
                output_url = _output_url(output_filename)
            elif not output_url:
                raise NodeError("Nothing to rasterize — connect a Country Shape (SVG) node.")

        elif node_type == "OutputImageNode":
            source = next((p for p in parent_outputs if p.get("outputImageUrl")), None)
            if not source:
                raise NodeError("No image to display — connect a node that produces an image.")
            output_url = source["outputImageUrl"]
            if source.get("legend"):
                spatial_outputs["legend"] = source["legend"]   # so the output shows its colour key
            # Exact extent of the picture (raster previews and satellite photos), for the JPEG scale bar.
            image_bounds = source.get("rasterBounds") or source.get("satelliteBounds") or source.get("imageBounds")
            if image_bounds:
                spatial_outputs["imageBounds"] = image_bounds

        elif node_type == "CompositeNode":
            alpha = _int(float(form.get("alpha") or 0.6) * 100, 60, 0, 100) / 100
            base_geojson_path = None
            overlay_data = []
            background_image_path = None
            sat_bounds = None

            for parent_output in parent_outputs:
                if parent_output.get("boundaryShpPath") and base_geojson_path is None:
                    base_geojson_path = _within(parent_output["boundaryShpPath"], "files")

                image_url = parent_output.get("outputImageUrl") or ""
                is_satellite = parent_output.get("satelliteBounds") or "satellite" in image_url
                if is_satellite and background_image_path is None:
                    background_image_path = _url_to_output_path(image_url)
                    sat_bounds = parent_output.get("satelliteBounds")

                layer_path = _within(parent_output.get("layerGeojsonPath"), "files")
                if layer_path:
                    overlay_data.append({"path": layer_path,
                                         "layer_type": parent_output.get("layerType", "default")})

            if not base_geojson_path:
                raise NodeError("Composite needs a Boundary node as input.")
            output_filename = await run_in_threadpool(
                composite_geodata, base_geojson_path, overlay_data, alpha,
                background_image_path, sat_bounds, tag)
            output_url = _output_url(output_filename)

        elif node_type in spatial.HANDLERS:
            context = spatial.Context(
                node_type=node_type, params={k: form.get(k) for k in spatial.PARAM_KEYS if k in form},
                parents=parent_outputs, tag=tag, location=location, place=place, uploads=saved_uploads,
                safe_path=lambda p: _within(p, "files"))
            spatial_outputs = await run_in_threadpool(spatial.HANDLERS[node_type], context)
            output_filename = spatial_outputs.pop("outputImage", None)
            output_url = _output_url(output_filename) if output_filename else None
            # Polygon results double as boundaries for Satellite, OSM Layer, STAC and Composite nodes.
            boundary_shp_path = spatial_outputs.pop("boundaryShpPath", None)
            boundary_bounds = spatial_outputs.pop("boundaryBounds", None)
            for key, url_key in (("rasterPath", "rasterUrl"), ("vectorPath", "vectorGeoJsonUrl"),
                                 ("tablePath", "tableUrl")):
                if spatial_outputs.get(key):
                    spatial_outputs[url_key] = _versioned_url("files", spatial_outputs[key])
            style_path = spatial_outputs.pop("stylePath", None)
            if style_path:
                # Zoomable map tiles rendered from the GeoTIFF (sharp at every zoom level).
                rel = quote(os.path.relpath(style_path, "files").replace(os.sep, "/"))
                spatial_outputs["rasterTilesUrl"] = (f"{BASE_URL}/raster-tiles/{{z}}/{{x}}/{{y}}.png"
                                                     f"?style={rel}&v={os.stat(style_path).st_mtime_ns}")

    except (NodeError, spatial.InputError) as e:
        return JSONResponse(status_code=400, content={"status": "error", "nodeId": node_id, "detail": str(e)})
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "nodeId": node_id, "detail": str(e)})

    elapsed = round(time.perf_counter() - started, 2)
    print(f"Node {node_id} ({node_type}) done in {elapsed}s → {output_url}")

    return {
        "status": "ok",
        "nodeId": node_id,
        "elapsed": elapsed,
        "received": received_files,
        "location": location,
        "place": place,      # passed along so nodes further downstream keep the exact place
        "svgPath": svg_path,
        "outputImageUrl": output_url,
        "layerFile": output_filename if node_type == "LayerNode" else None,
        "boundaryShpPath": boundary_shp_path,
        "layerGeojsonPath": layer_geojson_path,
        "layerType": layer_type,
        "boundaryBounds": boundary_bounds,
        "satelliteBounds": actual_sat_bounds if node_type == "SatelliteNode" else None,
        # Zoomable imagery tiles masked to the boundary (None when the image isn't clipped)
        "satelliteTilesUrl": satellite_tiles_url,
        "boundaryGeoJsonUrl": _versioned_url("files", boundary_shp_path) if boundary_shp_path else None,
        "layerGeoJsonUrl": _versioned_url("files", layer_geojson_path) if layer_geojson_path else None,
        # Spatial analysis nodes: rasterPath/rasterUrl, vectorPath/vectorGeoJsonUrl, legend, stats, details…
        **spatial_outputs,
    }
