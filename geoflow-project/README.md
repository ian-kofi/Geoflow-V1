# GeoFlow frontend

The node editor, built with React and Vite. It talks to the FastAPI backend in
[`../geoflow-backend`](../geoflow-backend).

## Run it

```bash
# Backend (from geoflow-backend/)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt      # Windows
.venv/bin/pip install -r requirements.txt                         # macOS or Linux
.venv\Scripts\python.exe -m uvicorn main:app --reload             # http://localhost:8000

# Frontend (from geoflow-project/)
npm install
npm run dev                                                       # http://localhost:5173
```

If the backend isn't at `http://localhost:8000`, set `VITE_API_URL` to its address.

## Using it

- Drag nodes from the sidebar onto the canvas (or click them), then connect one node's output on the right
  to another's input on the left.
- The **Place** node runs in the browser and passes the chosen place on to the nodes after it.
- **Run workflow** (`Ctrl+Enter`) runs every node in the right order. Separate branches run at the same time,
  and nodes whose settings and inputs haven't changed aren't run again. Shift+click, or `Ctrl+Shift+Enter`,
  runs everything again. `Esc` stops a run.
- **Run** on a node runs that node plus anything it depends on.
- The **Map** tab shows every result on an interactive map.
- The workflow is saved in your browser as you go. You can also export it to a JSON file and import it
  again with the buttons at the bottom of the sidebar.

## Code layout

| Folder or file | What's in it |
|---|---|
| `src/App.jsx` | The editor: sidebar, canvas, toolbar and right hand panel |
| `src/nodes/registry.js`, `src/nodes/spatialNodes.js` | Every node type: its name, help text, settings and inputs |
| `src/nodes/GeoNode.jsx` | How a node looks on the canvas |
| `src/workflow/` | Running workflows, following connections, templates and Make a map recipes |
| `src/components/` | The Inspector, map, settings controls, dialogs and other parts of the screen |
| `src/config.js` | The backend address and other shared settings |

## Nodes

Rasters (grids of values) are passed between nodes as GeoTIFFs and vector data (points, lines and shapes)
as GeoJSON. Both can be downloaded from the Inspector. Any result made of shapes can also be used as an
outline by later nodes.

### Start here and get map data

| Node | Needs | Makes |
|---|---|---|
| Place | nothing | the chosen place |
| Outline | Place | the place's border as GeoJSON, with its extent and a preview |
| Satellite Photo | Place or Outline | an Esri satellite photo of the area, cut to the outline if you like |
| Map Features | Place or Outline | roads, main roads, railways, rivers and streams, main rivers and canals, or buildings from OpenStreetMap |
| Country Drawing | Place | a simple SVG drawing of the country from Natural Earth |
| Satellite and Elevation Data | Place, Outline or other shapes | Sentinel-2 or Landsat photos (cloud free), Copernicus ground height, or JRC water history, from Microsoft Planetary Computer |
| Your Own File | nothing | your GeoTIFF, GeoJSON, GeoPackage, KML or shapefile |

### Hills and terrain

| Node | Needs | Makes |
|---|---|---|
| Steepness (Slope), Slope Direction (Aspect), Ruggedness, Shaded Relief | ground height | terrain rasters, worked out with Horn's method like ArcGIS and GDAL |
| Contour Lines | ground height | lines of equal height |
| Height Above River (HAND) | ground height, and optionally mapped rivers | how many metres each place sits above the river it drains into |

### Analyse images

| Node | Needs | Makes |
|---|---|---|
| Combine Factors | rasters on A to D | one 0 to 1 score from several factors (weighted overlay) |
| Raster Calculator | rasters on A to D | any formula, like `where(A > 30, 1, 0)` or `(A.nir - A.red) / (A.nir + A.red)` |
| Vegetation and Water Index | a satellite photo | NDVI, SAVI, EVI, NDWI, MNDWI, NDBI or NBR |
| Group into Classes | a raster | named classes from your own cut-off values, equal ranges or equal counts |
| Change Resolution | a raster or shapes | a raster with a new cell size, or shapes turned into a raster |
| Cut to Outline | Raster and Mask | the raster inside the outline only |
| Average per Area | Raster and Zones | the average, lowest, highest, spread or total in each area, as a map and a CSV table |

### Shape tools

| Node | Needs | Makes |
|---|---|---|
| Zone Around (Buffer) | shapes | the area within a set distance of each feature |
| Distance to Features | Features, and optionally an Area | distance in metres to the nearest feature |
| Select by Location | Data and Mask | features kept, cut or removed depending on where they are compared with the mask |
| Merge Shapes | shapes | shapes merged into one, or one per value of a field |

### Style and combine, and the result

| Node | Needs | Makes |
|---|---|---|
| Colour Map | a raster result | the same result with different colours, optionally with shaded relief |
| Combine Layers | Outline, plus a photo or result and any Map Features | one finished picture with everything on it |
| Drawing to Picture | Country Drawing | a PNG of the drawing at the chosen quality |
| Final Map | any node with a picture | the finished map, with its legend and a JPEG download |

The **Slope stability** and **Vegetation (NDVI)** templates in the sidebar show complete analysis workflows.
