# GeoFlow

Node-based geospatial workflow editor. React + Vite frontend, FastAPI backend (`../geoflow-backend`).

## Run

```bash
# backend (from geoflow-backend/)
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
uvicorn main:app --reload        # http://localhost:8000

# frontend (from geoflow-project/)
npm install
npm run dev                      # http://localhost:5173
```

Set `VITE_API_URL` if the backend is not on `http://localhost:8000`.

## Using it

- Drag nodes from the left palette (or click them) and connect outputs → inputs.
- **Location** nodes are evaluated in the browser and pass their place name downstream.
- **Run workflow** (`Ctrl+Enter`) runs every node in dependency order. Independent branches
  run in parallel, and nodes whose settings and inputs haven't changed are skipped (cached).
  Shift+click or `Ctrl+Shift+Enter` forces a full re-run. `Esc` stops.
- **Run** on a node runs it plus anything upstream it needs.
- The **Map** tab shows every boundary, layer and satellite result on an interactive map.
- The workflow autosaves to localStorage; export/import JSON from the sidebar footer.

## Node reference

| Node | Needs | Produces |
| --- | --- | --- |
| Location | – | `location` |
| Boundary | location | boundary GeoJSON, bounds, preview PNG |
| Satellite | location or Boundary | Esri imagery mosaic + exact tile bounds |
| OSM Layer | location or Boundary | roads / highways / railways / waterways / rivers (main rivers & canals) / buildings GeoJSON + preview |
| Country Shape | location | Natural Earth SVG (shapefile auto-downloaded or uploaded as a folder) |
| Rasterizer | Country Shape (SVG) | PNG at chosen DPI (rasters pass through) |
| Composite | Boundary (+ Satellite, Layers) | aligned composite PNG |
| Output | any image node | final image + legend + download (resizable) |

### Spatial analysis nodes

Rasters travel between nodes as GeoTIFFs, vectors as GeoJSON (both downloadable from the
inspector). Polygon results also act as boundaries for Satellite / OSM Layer / STAC / Composite.

| Node | Inputs | Produces |
| --- | --- | --- |
| STAC Search | area (Location / Boundary / vector) | Sentinel-2, Landsat 8/9 or Copernicus DEM from Planetary Computer; cloud-free median composite |
| Local File | – | your GeoTIFF / GeoJSON / GeoPackage / KML / shapefile |
| Slope, Aspect, Ruggedness (TRI), Hillshade | DEM | terrain rasters (Horn method, as in ArcGIS/GDAL) |
| Contours | DEM | contour lines |
| Raster Calculator | rasters on A–D | map algebra, e.g. `where(A > 30, 1, 0)`, `(A.nir - A.red) / (A.nir + A.red)` |
| Spectral Index | multispectral raster | NDVI, SAVI, EVI, NDWI, MNDWI, NDBI, NBR |
| Reclassify | raster | classes from manual / equal-interval / quantile breaks |
| Clip Raster | Raster + Mask | raster limited to a polygon |
| Zonal Statistics | Raster + Zones | per-polygon mean/min/max/std/sum + CSV |
| Buffer | vector | buffer polygons (metres) |
| Spatial Filter / Clip | Data + Mask | intersects / within / outside / clip / erase |
| Dissolve | vector | merged features (optionally by attribute) |

Templates **Slope stability** and **Vegetation (NDVI)** show complete analysis chains.
