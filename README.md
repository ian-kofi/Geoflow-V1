# GeoFlow

**A node-based geospatial workflow app.** Drag nodes onto a canvas and connect them to fetch data, run
spatial analysis and produce a finished map, with no GIS software needed. For beginners, a **Make a map**
assistant builds a ready-made workflow from a template, which you can then open up, tune and extend.

![Making a flood susceptibility map with the "Make a map" assistant](docs/make-a-map.gif)

*Above: the **Make a map** assistant, a shortcut that builds a ready-made workflow from a template. GeoFlow is
mainly a drag-and-drop node editor: you connect nodes in any combination to build your own analyses
([see below](#build-your-own-workflow)).*

**United Kingdom**

| Flood susceptibility · York | Steep slopes · Lake District | Hills & valleys · Eryri (Snowdonia) |
|---|---|---|
| ![Flood susceptibility map of York](docs/flood-york.jpg) | ![Slope classes map of the Lake District National Park](docs/slopes-lake-district.jpg) | ![Shaded terrain map of Eryri National Park](docs/terrain-eryri.jpg) |

**Ghana**

| Flood susceptibility · Accra | Hills & valleys · Akosombo | Steep slopes · Akosombo |
|---|---|---|
| ![Flood susceptibility map of Accra](docs/flood-accra.jpg) | ![Shaded terrain map of Akosombo](docs/terrain-akosombo.jpg) | ![Slope classes map of Akosombo](docs/slopes-akosombo.jpg) |

Every map above was made with the same few clicks in the **Make a map** assistant; the same workflows run
anywhere in the world.

## What it does

- **Visual workflow editor:** about 30 nodes you drag onto a canvas and connect in any combination, with
  independent branches run in parallel and unchanged steps cached.
- **Make a map assistant (templates):** search a place, choose *Satellite photo, Hills & valleys, Steep slopes,
  Flood risk, How green it is, Roads, Rivers & streams, Contour lines* or *Regions & borders*, and get a
  finished, editable workflow.
- **Real data, fetched live:** administrative boundaries, Sentinel-2 / Landsat imagery, the Copernicus 30 m DEM,
  JRC Global Surface Water (1984–2021) and OpenStreetMap features.
- **Spatial analysis:** slope, aspect, ruggedness, hillshade, contours, Height Above Nearest Drainage (HAND),
  NDVI and other spectral indices, a raster calculator, reclassification, weighted overlay, zonal statistics,
  resampling and rasterization, buffers, spatial filters, dissolve and distance analysis.
- **Interactive map:** every result as a zoomable layer (rendered as tiles on demand, sharp at any zoom),
  with Map/Satellite basemaps.
- **Export:** a print-ready JPEG with title, north arrow, scale bar and colour key, plus GeoTIFF, GeoJSON and CSV downloads.

### Build your own workflow

Templates are only a starting point. Every analysis is a chain of nodes you drag onto the canvas and
connect, and different combinations give different results. Here a workflow is built from an empty canvas
to map which way the slopes face across the Cairngorms. Then one node is swapped to map terrain ruggedness
instead. On the second run the place, outline and elevation data come from cache.

![Building a workflow from scratch by dragging and connecting nodes, then swapping one node](docs/build-workflow.gif)

### Modular by design

Every map is a workflow you can extend. Here the Flood risk workflow gets a roads overlay in under a minute:
drag in a **Map Features** node, connect it to the outline, and stack it on the flood map with **Combine Layers**.
Only the new steps run; everything else comes from cache.

![Adding a roads overlay to the flood risk workflow by dragging and connecting two nodes](docs/add-roads.gif)

![Flood susceptibility map of Accra with roads overlaid](docs/flood-roads-accra.jpg)

![The workflow canvas with the Flood risk workflow and its result](docs/canvas.png)

![Flood susceptibility classes for York over satellite imagery on the expanded map](docs/map-york.png)

## How the flood analysis works

The **Flood risk** workflow is a terrain-based susceptibility screening (not a regulatory flood zone
determination, which requires hydraulic modelling):

1. **Height Above Nearest Drainage (HAND).** The DEM is conditioned with priority-flood depression filling
   (Barnes et al. 2014), flow is routed with D8, and every cell's height above the river it drains to is
   computed. Cells a few metres above their river flood first.
2. **River network.** Mapped rivers and canals from OpenStreetMap are burned into the DEM, so large rivers
   whose catchment lies outside the area still count (York's Ouse drains about 3,300 km² upstream, which a
   DEM clipped to the city cannot see). In areas with enough relief (Accra), streams traced from flow
   accumulation are added. In low-lying areas (York, under 40 m of relief), streams traced from a 30 m surface
   model follow hedges and buildings rather than channels, so only mapped rivers are used.
3. **Slope.** Flat ground holds water (Horn's method, as in ArcGIS/GDAL).
4. **Water history.** How often each 30 m cell was observed underwater since 1984 (JRC Global Surface Water).
5. **Weighted overlay.** Each factor is rescaled to 0–1 risk and combined (HAND 50%, water history 30%,
   slope 20%), then classed into Low / Moderate / High.

In York the High class picks out the River Foss corridor, the Ouse washlands and the Derwent Ings, while the
York moraine, the glacial ridge the city grew on, comes out Low.

**Validation.** Against the Environment Agency's official Flood Zones, the workflow ranks flood-zone land with
a ROC AUC of **0.92 in Sheffield** and **0.77 in York** (0.5 = chance). In Sheffield, three quarters of the
High class lies in Flood Zones 2 or 3, which cover just 5.5% of the city. Adding mapped rivers raised York from
0.62 to 0.77. See [VALIDATION.md](VALIDATION.md) for the method, maps and limitations.

The same building blocks support other analyses, for example slope-stability classes, vegetation health from a
cloud-free Sentinel-2 median composite, or district-level summaries with zonal statistics.

## Tech stack

- **Frontend:** React 19, Vite, React Flow (`@xyflow/react`), MapLibre GL via `react-map-gl`
  ([`geoflow-project/`](geoflow-project/))
- **Backend:** Python, FastAPI, GeoPandas, Rasterio/GDAL, NumPy/SciPy, OSMnx, Matplotlib, Pillow
  ([`geoflow-backend/`](geoflow-backend/))
- **Data access:** STAC search on Microsoft Planetary Computer, reading only the needed parts of Cloud Optimized
  GeoTIFFs; Overpass with mirror fail-over; Nominatim geocoding.

## Run it locally

Requirements: Python 3.11+ and Node.js 20.19+.

```bash
# Backend (from geoflow-backend/)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt      # Windows
#   source .venv/bin/activate && pip install -r requirements.txt   (macOS/Linux)
.venv\Scripts\python.exe -m uvicorn main:app --reload             # http://localhost:8000

# Frontend (from geoflow-project/)
npm install
npm run dev                                                       # http://localhost:5173
```

On Windows you can instead double-click `start-geoflow.cmd` once both are installed.
See [`geoflow-project/README.md`](geoflow-project/README.md) for the full node reference.

### Run it with Docker

The [`Dockerfile`](Dockerfile) builds one container in which the backend also serves the app:

```bash
docker build -t geoflow .
docker run -p 7860:7860 -e GEOFLOW_BASE_URL=http://localhost:7860 geoflow   # http://localhost:7860
```

The container turns on limits suited to a public server: uploads up to 50 MB, at most 3 heavy steps at
once, and results deleted after 6 hours. Change them with `GEOFLOW_MAX_UPLOAD_MB`, `GEOFLOW_MAX_JOBS` and
`GEOFLOW_RETENTION_HOURS`, or set them to `0` to turn them off. `GEOFLOW_LOW_MEMORY=1` processes large areas at
lower detail so maps fit in about 400 MB of memory.

The public demo runs on Render's free plan, configured by [`render.yaml`](render.yaml): on render.com choose
**New → Blueprint** and pick this repository.

## Data sources and limitations

geoBoundaries, GADM, OpenStreetMap (Nominatim, Overpass), Esri World Imagery, Microsoft Planetary Computer
(Sentinel-2, Landsat, Copernicus DEM, JRC Global Surface Water) and Natural Earth. Please respect each provider's
terms and attribution; the public OpenStreetMap services are not meant for heavy automated use.

Terrain analyses use the 30 m Copernicus DEM, so features narrower than about 30 m (urban drains, embankments)
are not resolved. Flood results are susceptibility screening for planning and prioritisation, not flood zone
designations.

## Project status

GeoFlow is an active work in progress. The aim is to show what spatial analysis can look like for
people who need simple answers, like where floods are likely or how steep the ground is, but don't
have the time to learn a full GIS package such as ArcGIS. The analyses are deliberately kept simple
and are meant for exploration and screening, not professional or regulatory decisions.

Planned next steps:
- ~~Validate flood susceptibility against official flood maps~~ Done for York and Sheffield
  ([VALIDATION.md](VALIDATION.md)). Next: more sites, and test giving HAND more weight
- Support higher-resolution elevation data where available (e.g. UK LiDAR)
- Deploy a public demo

## License

[MIT](LICENSE)
