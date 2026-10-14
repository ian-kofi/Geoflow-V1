"""The GeoFlow web server.

The frontend runs a workflow by sending each node to POST /upload, one request per node, in an
order that respects the connections between them. Each request carries the node's type, its
settings and the outputs of the nodes connected to it. This file works out which node it is,
calls the code that does the actual work and sends back what the node produced: file paths,
links to preview images and map tiles, legends and so on. The frontend then passes those
results on to the next nodes.

The older node types (Outline, Satellite Photo, Map Features, Combine Layers and a few others)
are handled directly in _run_node below. All the spatial analysis nodes (slope, HAND, NDVI,
reclassify and the rest) live in the spatial package and are looked up in spatial.HANDLERS.

Other endpoints:
    /geocode        place search for the Place node's dropdown
    /export/jpeg    turns a result into a finished map with title, scale bar and legend
    /raster-tiles   map tiles drawn on demand from an analysis result
    /tiles          satellite tiles cut to an outline
    /outputs and /files serve the images and data files the nodes create

Files are written to four folders next to this file: outputs (preview images), files (GeoJSON,
GeoTIFFs and styles), uploads (files people load in) and cache (downloads kept for reuse).
"""
import os
import json
import re
import time
import shutil
import asyncio
import mimetypes
import traceback
from contextlib import asynccontextmanager
from urllib.parse import quote, unquote

import matplotlib
matplotlib.use("Agg")  # draw without a screen; this has to happen before anything imports pyplot

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

def _env_number(name, default=0):
    """Reads a number from an environment variable, falling back to the default if it isn't one."""
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# The address people use to reach this server. Links to images and tiles are built from it.
# Render sets RENDER_EXTERNAL_URL for us (for example https://geoflow.onrender.com).
BASE_URL = (os.environ.get("GEOFLOW_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
            or "http://localhost:8000").rstrip("/")
# If set, the built frontend in this folder is served too, so the whole app lives at one address.
STATIC_DIR = os.environ.get("GEOFLOW_STATIC_DIR")
# Limits for a public server. They are all 0 (switched off) when you run GeoFlow on your own computer.
MAX_UPLOAD_MB = _env_number("GEOFLOW_MAX_UPLOAD_MB")
MAX_JOBS = int(_env_number("GEOFLOW_MAX_JOBS"))
RETENTION_HOURS = _env_number("GEOFLOW_RETENTION_HOURS")
DATA_FOLDERS = ("outputs", "files", "uploads", "cache")

# Form fields that are node settings rather than uploaded files.
PARAM_KEYS = {"nodeType", "nodeId", "locations", "parentOutputs", "satelliteZoom", "layerType",
              "boundarySource", "boundaryAdminLevel", "alpha", "dpi", "clipToBoundary"} | spatial.PARAM_KEYS
RASTER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

# StaticFiles won't mount a folder that doesn't exist yet, so make sure they all do.
for folder in ("outputs", "files", "uploads"):
    os.makedirs(folder, exist_ok=True)
mimetypes.add_type("application/geo+json", ".geojson")


def _delete_old_files(max_age_s):
    """Deletes results, uploads and cached downloads older than max_age_s seconds.

    Only used on a public server, so its disk doesn't slowly fill up.
    """
    cutoff = time.time() - max_age_s
    removed = 0
    for folder in DATA_FOLDERS:
        for root, _, names in os.walk(folder):
            for name in names:
                path = os.path.join(root, name)
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.remove(path)
                        removed += 1
                except OSError:
                    pass
    if removed:
        print(f"Removed {removed} file(s) older than {max_age_s / 3600:g} h")


async def _sweep_old_files():
    """Runs the clean up every half hour for as long as the server is up."""
    while True:
        await run_in_threadpool(_delete_old_files, RETENTION_HOURS * 3600)
        await asyncio.sleep(1800)


@asynccontextmanager
async def lifespan(_app):
    """Starts the clean up task when the server starts (if a retention time is set) and stops it on exit."""
    sweeper = asyncio.create_task(_sweep_old_files()) if RETENTION_HOURS > 0 else None
    yield
    if sweeper:
        sweeper.cancel()


app = FastAPI(title="GeoFlow", lifespan=lifespan)
# How many nodes may run at once. Anything beyond that waits its turn. None means no limit.
JOB_SLOTS = asyncio.Semaphore(MAX_JOBS) if MAX_JOBS > 0 else None

# The frontend's development server runs on a different port, so the browser needs permission to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   # Any extra addresses, separated by commas (for example if Vite picks another port)
                   *[o.strip() for o in os.environ.get("GEOFLOW_CORS_ORIGINS", "").split(",") if o.strip()]],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
# GeoJSON shrinks a lot when compressed. Images are already compressed, so only /files is gzipped.
app.mount("/files", GZipMiddleware(StaticFiles(directory="files"), minimum_size=1024), name="files")


class NodeError(Exception):
    """Something wrong with a node's inputs or settings. The message is shown to the user as it is."""


def _parse_json(value, default):
    """Parses a JSON form field, returning the default if it's missing or broken."""
    try:
        return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default


def _int(value, default, lo, hi):
    """Turns a form value into a whole number kept between lo and hi."""
    try:
        return max(lo, min(hi, int(float(value))))
    except (TypeError, ValueError):
        return default


def _bool(value, default):
    """Reads a true or false setting from a form value such as "true", "1" or "on"."""
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _clean_place(place):
    """Checks a place sent back by the browser before we use it.

    The Place node stores the result the user picked from /geocode and sends it with every
    request. Since it comes from the browser we can't trust it, so this keeps only the fields
    we expect, in the types we expect. Returns None if anything important is missing.
    """
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
    """Makes a short, filename safe tag from a node's id, used to name the files it creates.

    Node ids look like "slope_ab12c". The type is already part of each file name, so the
    "slope_" part is dropped to avoid names like slope_slope_ab12c.tif.
    """
    tag = re.sub(r"[^A-Za-z0-9_-]", "", str(node_id or ""))[:40]
    prefix = str(node_type or "").replace("Node", "").lower() + "_"
    return tag[len(prefix):] if tag.lower().startswith(prefix) and len(tag) > len(prefix) else tag


def _safe_relpath(name):
    """Cleans a relative path from the browser, removing any "..", so it can't point outside our folders."""
    parts = [p for p in str(name or "").replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return os.path.join(*parts) if parts else None


def _within(path, folder):
    """Returns the path only if it exists and is inside the given folder, otherwise None.

    Earlier results come back from the browser with their file paths, so every path is checked
    with this before we open it. That stops anyone asking the server to read other files.
    """
    if not path:
        return None
    full = os.path.abspath(path)
    root = os.path.abspath(folder)
    return path if os.path.commonpath([full, root]) == root and os.path.exists(full) else None


def _versioned_url(folder, path):
    """The public link to a file, with its modified time added so browsers fetch new versions."""
    rel = os.path.relpath(path, folder).replace(os.sep, "/")
    return f"{BASE_URL}/{folder}/{rel}?v={os.stat(path).st_mtime_ns}"


def _output_url(filename):
    """The public link to a file in the outputs folder."""
    return _versioned_url("outputs", os.path.join("outputs", filename))


def _url_to_output_path(url):
    """Turns a link to an image in outputs back into its local path (None if it isn't one of ours)."""
    if not url or "/outputs/" not in url:
        return None
    filename = os.path.basename(unquote(url.split("/outputs/")[-1].split("?")[0]))
    return _within(os.path.join("outputs", filename), "outputs")


def _save_upload(upload, save_path):
    """Writes an uploaded file to disk, in 1 MB pieces so big files don't fill the memory."""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    upload.file.seek(0)
    with open(save_path, "wb") as f:
        shutil.copyfileobj(upload.file, f, length=1 << 20)


@app.get("/health")
async def health():
    """Lets the frontend (and the hosting service) check that the server is up."""
    return {"status": "ok"}


@app.post("/export/jpeg")
async def export_map_jpeg(request: Request):
    """Turns a result into a finished JPEG map with a title, north arrow, scale bar and legend.

    The browser sends the link to the result's image plus its title, legend and extent. The
    scale bar is only drawn when the extent is known.
    """
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
    """Searches for places matching the text typed into a Place node, for its dropdown list."""
    try:
        return {"results": search_places(q[:200])}
    except Exception as e:
        return JSONResponse(status_code=502, content={"results": [], "detail": f"Place search failed: {e}"})


@app.get("/raster-tiles/{z}/{x}/{y}.png")
def raster_tile(z: int, x: int, y: int, style: str):
    """Draws one map tile of an analysis result when the map asks for it.

    `style` points to the JSON file saved alongside the result, which says which GeoTIFF to
    read and how to colour it. Drawing tiles on demand keeps results sharp at every zoom level.
    """
    rel = _safe_relpath(style)
    path = _within(os.path.join("files", rel), "files") if rel else None
    if not path or not path.endswith(".json") or not (0 <= z <= 22 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return Response(status_code=404)
    content = spatial.render_tile(path, z, x, y, safe_path=lambda p: _within(p, "files"))
    return Response(content=content, media_type="image/png", headers=spatial.TILE_HEADERS)


@app.get("/tiles/{z}/{x}/{y}.png")
def boundary_tile(z: int, x: int, y: int, boundary: str):
    """One satellite imagery tile with everything outside an outline made transparent.

    This is how the map shows a zoomable satellite photo cut to a place's shape. It's a normal
    (not async) function on purpose: FastAPI then runs it in a background thread, so a slow
    download from the imagery server doesn't hold up other requests.
    """
    rel = _safe_relpath(boundary)
    path = _within(os.path.join("files", rel), "files") if rel else None
    if not path or not (0 <= z <= 19 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return Response(status_code=404)
    content, media_type = clipped_tile(z, x, y, path)
    return Response(content=content, media_type=media_type, headers=TILE_CACHE_HEADERS)


@app.post("/upload")
async def upload_files(request: Request):
    """Runs one node of a workflow. The frontend calls this once for every node it runs.

    On a public server this first turns away requests that are too large and makes the node
    wait if too many others are already running. The work itself happens in _run_node.
    """
    if MAX_UPLOAD_MB > 0:
        try:
            size = int(request.headers.get("content-length") or 0)
        except ValueError:
            size = 0
        if size > MAX_UPLOAD_MB * 1024 * 1024:
            return JSONResponse(status_code=413, content={
                "status": "error", "detail": f"Files are limited to {MAX_UPLOAD_MB:g} MB on this demo server."})
    if JOB_SLOTS is None:
        return await _run_node(request)
    async with JOB_SLOTS:
        return await _run_node(request)


async def _run_node(request: Request):
    """Does the work for one node and returns its results.

    The request is a form with:
        nodeType, nodeId    which node this is
        parentOutputs       JSON list of the results of the nodes connected to it. If a parent
                            is plugged into a named input (like "mask"), its result has an
                            "_input" key saying which one.
        locations           the place typed into a Place node, if this is one
        anything else       the node's settings, or files the user chose to upload

    The reply is the same dictionary shape for every node type, with None for anything that
    doesn't apply. Analysis nodes add their own fields through spatial_outputs.
    """
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

    # The place name: this node's own value if it has one, otherwise the first parent that does
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
    # The exact place picked from the Place node's dropdown, if any. Names like "Tema" exist in
    # several countries, so this tells us which one the user meant.
    place = _clean_place(next((p["place"] for p in parent_outputs if isinstance(p.get("place"), dict)), None))
    if place and not location:
        location = place["name"]

    # Uploaded files. Files whose field name starts with "geo_" are a shapefile folder for the
    # Country Drawing node and go into files/. Anything else belongs to a Your Own File node.
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
                    # Choosing new files replaces this node's old ones. Uploads are kept in a
                    # folder per node so they can be used again after the page is reloaded,
                    # when the browser no longer has the original file.
                    await run_in_threadpool(shutil.rmtree, upload_dir, True)
                save_path = os.path.join(upload_dir, name)
                saved_uploads.append(save_path)
            await run_in_threadpool(_save_upload, upload, save_path)
            print(f"File saved: {save_path}")
            received_files += 1

    def first_parent(key):
        """The value of `key` from the first connected node that has it."""
        return next((p[key] for p in parent_outputs if p.get(key)), None)

    def require_location():
        if not location:
            raise NodeError(f"{node_type} needs a place. Connect a Place node before it.")

    try:
        # Outline: the border of the chosen place, saved as GeoJSON, plus a preview image
        if node_type == "BoundaryNode":
            require_location()
            boundary_source = form.get("boundarySource") or "geoboundaries"
            boundary_admin_level = _int(form.get("boundaryAdminLevel"), 0, 0, 5)
            if place and not place["isCountry"] and boundary_source != "city":
                # Country border datasets don't work for a town or district, so use its own outline.
                print(f"'{place['name']}' is a {place['kind']}, not a country, so using its OpenStreetMap boundary")
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

        # Satellite Photo: Esri imagery stitched into one picture, cut to the outline if one is connected
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

        # Map Features: roads, rivers, railways or buildings from OpenStreetMap
        elif node_type == "LayerNode":
            layer_type = form.get("layerType") or "roads"
            layer_bounds = first_parent("boundaryBounds") or (place and place["bbox"])
            clip_path = _within(first_parent("boundaryShpPath"), "files")
            if not location and not layer_bounds:
                require_location()
            output_filename, layer_geojson_path = await run_in_threadpool(
                fetch_layer, location or "selected area", layer_type, layer_bounds, clip_path, tag)
            output_url = _output_url(output_filename)

        # Country Drawing: a simple SVG outline of a country from Natural Earth
        elif node_type == "GeoFileNode":
            require_location()
            # Natural Earth only has countries, so if a town was picked we draw its country.
            country = (place["country"] or place["name"]) if place else location
            output_filename = await run_in_threadpool(plot_country, country, tag)
            svg_path = os.path.join("outputs", output_filename)
            output_url = _output_url(output_filename)

        # Drawing to Picture: turns the SVG from Country Drawing into a PNG. If it's given a
        # picture that's already a PNG or JPEG, it just passes it along.
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
                raise NodeError("Nothing to turn into a picture. Connect a Country Drawing node.")

        # Final Map: shows the picture of whatever is connected to it. Nothing new is made here.
        elif node_type == "OutputImageNode":
            source = next((p for p in parent_outputs if p.get("outputImageUrl")), None)
            if not source:
                raise NodeError("No image to display. Connect a node that makes an image.")
            output_url = source["outputImageUrl"]
            if source.get("legend"):
                spatial_outputs["legend"] = source["legend"]   # so the final map shows the same legend
            # Where the picture sits on the Earth, so the JPEG export can draw a scale bar.
            image_bounds = source.get("rasterBounds") or source.get("satelliteBounds") or source.get("imageBounds")
            if image_bounds:
                spatial_outputs["imageBounds"] = image_bounds

        # Combine Layers: draws the outline and any Map Features on top of a background picture.
        # The background is a satellite photo if one is connected, otherwise any analysis result.
        elif node_type == "CompositeNode":
            alpha = _int(float(form.get("alpha") or 0.6) * 100, 60, 0, 100) / 100
            base_geojson_path = None
            overlay_data = []
            background_image_path = None
            sat_bounds = None

            raster_background = None
            for parent_output in parent_outputs:
                if parent_output.get("boundaryShpPath") and base_geojson_path is None:
                    base_geojson_path = _within(parent_output["boundaryShpPath"], "files")

                image_url = parent_output.get("outputImageUrl") or ""
                is_satellite = parent_output.get("satelliteBounds") or "satellite" in image_url
                if is_satellite and background_image_path is None:
                    background_image_path = _url_to_output_path(image_url)
                    sat_bounds = parent_output.get("satelliteBounds")
                # An analysis result (flood classes, slope, NDVI and so on) works as a background
                # too, because its preview is a Web Mercator picture with known edges, just like
                # a satellite photo.
                elif parent_output.get("rasterBounds") and raster_background is None:
                    raster_background = parent_output

                layer_path = _within(parent_output.get("layerGeojsonPath"), "files")
                if layer_path:
                    overlay_data.append({"path": layer_path,
                                         "layer_type": parent_output.get("layerType", "default")})

            if background_image_path is None and raster_background is not None:
                background_image_path = _url_to_output_path(raster_background.get("outputImageUrl"))
                sat_bounds = raster_background["rasterBounds"]
                if raster_background.get("legend"):
                    spatial_outputs["legend"] = raster_background["legend"]   # keep its legend
            if not base_geojson_path:
                raise NodeError("Combine Layers needs an Outline connected.")
            output_filename = await run_in_threadpool(
                composite_geodata, base_geojson_path, overlay_data, alpha,
                background_image_path, sat_bounds, tag)
            output_url = _output_url(output_filename)

        # Every analysis node (slope, HAND, NDVI, reclassify and so on) is handled by the spatial package
        elif node_type in spatial.HANDLERS:
            context = spatial.Context(
                node_type=node_type, params={k: form.get(k) for k in spatial.PARAM_KEYS if k in form},
                parents=parent_outputs, tag=tag, location=location, place=place, uploads=saved_uploads,
                safe_path=lambda p: _within(p, "files"))
            spatial_outputs = await run_in_threadpool(spatial.HANDLERS[node_type], context)
            output_filename = spatial_outputs.pop("outputImage", None)
            output_url = _output_url(output_filename) if output_filename else None
            # A result made of polygons can be used as an outline by later nodes (Satellite Photo,
            # Map Features, Satellite and Elevation Data, Combine Layers), so it's passed on as one.
            boundary_shp_path = spatial_outputs.pop("boundaryShpPath", None)
            boundary_bounds = spatial_outputs.pop("boundaryBounds", None)
            for key, url_key in (("rasterPath", "rasterUrl"), ("vectorPath", "vectorGeoJsonUrl"),
                                 ("tablePath", "tableUrl")):
                if spatial_outputs.get(key):
                    spatial_outputs[url_key] = _versioned_url("files", spatial_outputs[key])
            style_path = spatial_outputs.pop("stylePath", None)
            if style_path:
                # A link the map uses to fetch tiles drawn from the GeoTIFF, so it stays sharp when zoomed in.
                rel = quote(os.path.relpath(style_path, "files").replace(os.sep, "/"))
                spatial_outputs["rasterTilesUrl"] = (f"{BASE_URL}/raster-tiles/{{z}}/{{x}}/{{y}}.png"
                                                     f"?style={rel}&v={os.stat(style_path).st_mtime_ns}")

    # Problems the user can fix get a 400 with a readable message. Anything unexpected is a 500,
    # and the full error goes to the server log.
    except (NodeError, spatial.InputError) as e:
        return JSONResponse(status_code=400, content={"status": "error", "nodeId": node_id, "detail": str(e)})
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "nodeId": node_id, "detail": str(e)})

    elapsed = round(time.perf_counter() - started, 2)
    print(f"Node {node_id} ({node_type}) done in {elapsed}s: {output_url}")

    return {
        "status": "ok",
        "nodeId": node_id,
        "elapsed": elapsed,
        "received": received_files,
        "location": location,
        "place": place,      # passed along so every later node knows exactly which place was picked
        "svgPath": svg_path,
        "outputImageUrl": output_url,
        "layerFile": output_filename if node_type == "LayerNode" else None,
        "boundaryShpPath": boundary_shp_path,
        "layerGeojsonPath": layer_geojson_path,
        "layerType": layer_type,
        "boundaryBounds": boundary_bounds,
        "satelliteBounds": actual_sat_bounds if node_type == "SatelliteNode" else None,
        # Link to zoomable satellite tiles cut to the outline (None when the photo isn't cut)
        "satelliteTilesUrl": satellite_tiles_url,
        "boundaryGeoJsonUrl": _versioned_url("files", boundary_shp_path) if boundary_shp_path else None,
        "layerGeoJsonUrl": _versioned_url("files", layer_geojson_path) if layer_geojson_path else None,
        # Extra fields from analysis nodes, such as rasterPath and rasterUrl, vectorPath and
        # vectorGeoJsonUrl, legend, stats and details
        **spatial_outputs,
    }


# When the server also hosts the frontend (as on Render), any address that isn't one of the API
# routes above gets the app's files. This is added last so the API routes are always checked first.
if STATIC_DIR and os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="app")
