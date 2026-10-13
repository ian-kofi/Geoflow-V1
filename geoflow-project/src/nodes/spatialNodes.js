/**
 * Spatial analysis node types (backend: geoflow-backend/spatial/nodes.py).
 *
 * `inputs` gives a node several named input handles; the handle id travels to
 * the backend as `_input` on each parent output so it knows which is which.
 */

import { compassDirection } from '../components/AngleDials.jsx';

const isoDate =(daysAgo = 0) => new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);

const COLLECTIONS = [
  ['sentinel-2-l2a', 'Satellite photo · sharp (Sentinel-2, 10 m)'],
  ['landsat-c2-l2', 'Satellite photo · wider history (Landsat, 30 m)'],
  ['cop-dem-glo-30', 'Ground height / terrain (DEM, 30 m)'],
  ['jrc-gsw', 'Past flooding & water, 1984–2021 (JRC, 30 m)'],
];
// These datasets are not tied to a date or cloud cover.
const isDem = (d) => d.collection === 'cop-dem-glo-30' || d.collection === 'jrc-gsw';

const INDICES = [
  ['ndvi', 'How green / plant health (NDVI)'],
  ['savi', 'Plant health on dry, sparse land (SAVI)'],
  ['evi', 'Plant health in dense forest (EVI)'],
  ['ndwi', 'Open water (NDWI)'],
  ['mndwi', 'Water in towns (MNDWI)'],
  ['ndbi', 'Built-up areas (NDBI)'],
  ['nbr', 'Burned areas (NBR)'],
];

const FILTER_MODES = [
  ['intersects', 'Keep features touching the mask'],
  ['within', 'Keep features inside the mask'],
  ['outside', 'Keep features outside the mask'],
  ['clip', 'Clip features to the mask'],
  ['erase', 'Erase the mask from features'],
];

const STATS = [
  ['mean', 'Average'],
  ['min', 'Lowest'],
  ['max', 'Highest'],
  ['std', 'How much it varies'],
  ['sum', 'Total'],
  ['count', 'Number of pixels'],
];

const label = (options, value) => options.find(([v]) => v === value)?.[1] ?? value;

export const SPATIAL_NODE_TYPES = {
  // ---- Ingestion ----------------------------------------------------------
  StacNode: {
    label: 'Satellite & Elevation Data',
    category: 'source',
    icon: 'cloudDown',
    description:
      'Fresh satellite photos (with a cloud-free mix of the clearest days) or ground height for your area, from Microsoft Planetary Computer. GIS term: STAC search.',
    // Getter so each new node gets "the last 3 months" relative to today.
    get defaults() {
      return { collection: 'sentinel-2-l2a', startDate: isoDate(90), endDate: isoDate(0), maxCloud: 20 };
    },
    params: [
      {
        key: 'collection',
        label: 'What to get',
        type: 'select',
        options: COLLECTIONS,
        hint: 'Photos combine the clearest days in the date range; large areas and long ranges take a few minutes.',
      },
      { key: 'startDate', label: 'From', type: 'date', hidden: isDem },
      { key: 'endDate', label: 'To', type: 'date', hidden: isDem },
      { key: 'maxCloud', label: 'Skip photos cloudier than', type: 'slider', min: 0, max: 100, step: 5, suffix: '%', hidden: isDem },
    ],
    summary: (d) =>
      d.collection === 'jrc-gsw' ? 'Water history 1984–2021' : isDem(d) ? 'Ground height (30 m)' : `${label(COLLECTIONS, d.collection).split(' ·')[0]} · ${d.startDate} → ${d.endDate}`,
  },
  LocalFileNode: {
    label: 'Your Own File',
    category: 'source',
    icon: 'upload',
    hasInput: false,
    description: 'Use a map file you already have: GeoTIFF, GeoJSON, GeoPackage, KML or shapefile (pick all its parts, or a .zip).',
    defaults: {},
    params: [
      {
        key: 'localFiles',
        label: 'File',
        type: 'file',
        accept: '.tif,.tiff,.geojson,.json,.gpkg,.kml,.fgb,.zip,.shp,.shx,.dbf,.prj,.cpg',
      },
    ],
    summary: (d) => d.localFiles?.root || 'No file chosen',
  },

  // ---- Terrain ------------------------------------------------------------
  SlopeNode: {
    label: 'Steepness (Slope)',
    category: 'terrain',
    icon: 'mountain',
    description: 'How steep the ground is everywhere, from Ground height data. Useful for landslide or erosion risk. GIS term: slope (Horn method).',
    defaults: { units: 'degrees', zFactor: 1 },
    params: [
      { key: 'units', label: 'Units', type: 'segmented', options: [['degrees', 'Degrees'], ['percent', 'Percent']] },
      { key: 'zFactor', label: 'Height exaggeration', type: 'number', min: 1, step: 1, hint: 'Leave at 1 for normal results.' },
    ],
    summary: (d) => `Steepness in ${d.units}`,
  },
  AspectNode: {
    label: 'Slope Direction (Aspect)',
    category: 'terrain',
    icon: 'compass',
    description: 'Which compass direction each slope faces (north, east, south, west), e.g. for sunlight or farming. GIS term: aspect.',
    defaults: {},
    params: [],
    summary: () => 'Facing direction',
  },
  RuggednessNode: {
    label: 'Ruggedness',
    category: 'terrain',
    icon: 'activity',
    description: 'How bumpy or rough the ground is. GIS term: Terrain Ruggedness Index (TRI).',
    defaults: {},
    params: [],
    summary: () => 'How rough the ground is',
  },
  HillshadeNode: {
    label: 'Shaded Relief',
    category: 'terrain',
    icon: 'hillshade',
    description: 'Shows hills and valleys as if lit by the sun, from Ground height data. GIS term: hillshade.',
    defaults: { azimuth: 315, altitude: 45, zFactor: 1 },
    params: [
      { key: 'azimuth', label: 'Sun direction', type: 'compass', step: 5 },
      { key: 'altitude', label: 'Sun height', type: 'elevation', min: 1, max: 90, step: 1 },
      { key: 'zFactor', label: 'Vertical exaggeration', type: 'number', min: 1, step: 1 },
    ],
    summary: (d) => `Sun from the ${compassDirection(d.azimuth)}, ${d.altitude}° high`,
  },
  ContourNode: {
    label: 'Contour Lines',
    category: 'terrain',
    icon: 'waves',
    description: 'Lines joining places of equal height, like on a hiking map.',
    defaults: { interval: 20 },
    params: [{ key: 'interval', label: 'Height between lines (m)', type: 'number', min: 0.1, step: 5 }],
    summary: (d) => `Every ${d.interval} m`,
  },

  HandNode: {
    label: 'Height Above River (HAND)',
    category: 'terrain',
    icon: 'droplet',
    description:
      'How many metres each place sits above the river it drains into. Places only a few metres above their river flood first, so this is the key terrain input for flood mapping. Works out rivers from Ground height data, and adds any rivers you connect to Rivers (important for flat land and big rivers that start outside your area). GIS term: HAND, with stream burning.',
    inputs: [
      { id: 'dem', label: 'Ground height' },
      { id: 'rivers', label: 'Rivers (optional)' },
    ],
    defaults: { minArea: 1, terrainStreams: 'auto' },
    params: [
      {
        key: 'minArea',
        label: 'Smallest river (km² draining into it)',
        type: 'number',
        min: 0.1,
        step: 0.5,
        hint: 'About 1 includes small streams; 10–50 keeps only larger rivers.',
      },
      {
        key: 'terrainStreams',
        label: 'Work out streams from the terrain',
        type: 'segmented',
        options: [['auto', 'Auto'], ['yes', 'Yes'], ['no', 'No']],
        hint: 'Auto: when Rivers are connected and the land is flat (under 40 m from low to high), only the connected rivers are used, because streams traced on flat ground are unreliable.',
      },
    ],
    summary: (d) => `Rivers from ${d.minArea} km²`,
  },

  // ---- Raster algorithms --------------------------------------------------
  WeightedOverlayNode: {
    label: 'Combine Factors',
    category: 'raster',
    icon: 'scale',
    description:
      'Turns up to four factors into one 0–1 risk score: each is rescaled to 0–1, flipped if lower values mean more risk, and averaged using your weights. GIS term: weighted overlay / multi-criteria analysis.',
    inputs: [
      { id: 'A', label: 'A' },
      { id: 'B', label: 'B' },
      { id: 'C', label: 'C' },
      { id: 'D', label: 'D' },
    ],
    defaults: {
      resultName: 'Combined score',
      weightA: 1, riskA: 'high', rangeA: '',
      weightB: 1, riskB: 'high', rangeB: '',
      weightC: 1, riskC: 'high', rangeC: '',
      weightD: 1, riskD: 'high', rangeD: '',
    },
    params: [
      { key: 'resultName', label: 'Result name', type: 'text', placeholder: 'e.g. Flood susceptibility' },
      ...['A', 'B', 'C', 'D'].flatMap((key) => [
      { key: `weight${key}`, label: `${key}: importance (weight)`, type: 'number', min: 0, step: 1 },
      {
        key: `risk${key}`,
        label: `${key}: which way is risky?`,
        type: 'select',
        options: [['high', 'Higher values = more risk'], ['low', 'Lower values = more risk']],
      },
      {
        key: `range${key}`,
        label: `${key}: from no risk to full risk`,
        type: 'text',
        placeholder: 'Automatic, or e.g. 0, 15',
        hint: key === 'A' ? 'Two values: where risk starts and where it is complete. Leave empty to use the data’s own range.' : undefined,
      },
      ]),
    ],
    summary: (d) =>
      ['A', 'B', 'C', 'D']
        .filter((k) => Number(d[`weight${k}`]) > 0)
        .map((k) => `${k}×${d[`weight${k}`]}`)
        .join(' + '),
  },
  RasterCalcNode: {
    label: 'Raster Calculator',
    category: 'raster',
    icon: 'calculator',
    description: 'Advanced: do maths with up to four images, cell by cell (GIS term: map algebra / raster calculator).',
    inputs: [
      { id: 'A', label: 'A' },
      { id: 'B', label: 'B' },
      { id: 'C', label: 'C' },
      { id: 'D', label: 'D' },
    ],
    defaults: { expression: 'A - B' },
    params: [
      {
        key: 'expression',
        label: 'Expression',
        type: 'text',
        mono: true,
        placeholder: 'e.g. (A.nir - A.red) / (A.nir + A.red)',
        hint: 'A–D are the inputs (band 1); A2 is band 2; A.nir a named band. Operators + − * / ** > < == and/or. Functions: sqrt abs log exp min max where clip round.',
      },
    ],
    summary: (d) => d.expression || 'No expression',
  },
  SpectralIndexNode: {
    label: 'Vegetation & Water Index',
    category: 'raster',
    icon: 'leaf',
    description: 'Measures how green (healthy plants), wet or built-up each place is, from a satellite photo. GIS term: spectral index (NDVI…).',
    defaults: { index: 'ndvi' },
    params: [{ key: 'index', label: 'Measure', type: 'select', options: INDICES }],
    summary: (d) => label(INDICES, d.index),
  },
  ReclassifyNode: {
    label: 'Group into Classes',
    category: 'raster',
    icon: 'classify',
    description: 'Sorts values into a few named groups, e.g. steepness into Low / Medium / High risk. GIS term: reclassify.',
    defaults: { method: 'manual', breaks: '15, 30', classes: 3, labels: 'Low, Medium, High' },
    params: [
      {
        key: 'method',
        label: 'Method',
        type: 'select',
        options: [['manual', 'I’ll choose the cut-off values'], ['equal', 'Equal-sized ranges'], ['quantile', 'Equal number of places in each']],
      },
      { key: 'breaks', label: 'Cut-off values', type: 'text', placeholder: '15, 30', hidden: (d) => d.method !== 'manual', hint: 'Smallest first, separated by commas. Two values make three groups.' },
      { key: 'classes', label: 'Number of groups', type: 'number', min: 2, max: 12, step: 1, hidden: (d) => d.method === 'manual' },
      { key: 'labels', label: 'Group names', type: 'text', placeholder: 'Low, Medium, High' },
    ],
    summary: (d) => (d.method === 'manual' ? `Breaks ${d.breaks}` : `${d.classes} ${d.method} classes`),
  },
  UpscaleNode: {
    label: 'Change Resolution',
    category: 'raster',
    icon: 'grid',
    description:
      'Sets the cell size of a raster, finer or coarser (GIS: Resample). Connect vector shapes instead and it turns them into a raster at that cell size (GIS: Feature to Raster). Finer cells are interpolated, so they look smoother but hold no extra real detail.',
    defaults: { cellSize: 10, method: 'cubic', field: '' },
    params: [
      {
        key: 'cellSize',
        label: 'Output cell size (m)',
        type: 'number',
        min: 0.1,
        step: 5,
        hint: 'Smaller = finer. Ground height and slope data start at 30 m; satellite photos at 10 m.',
      },
      {
        key: 'method',
        label: 'Resampling technique',
        type: 'select',
        options: [
          ['cubic', 'Cubic convolution · smooth (continuous data)'],
          ['bilinear', 'Bilinear · smooth, fast'],
          ['lanczos', 'Lanczos · sharpest edges'],
          ['nearest', 'Nearest · keeps exact values (classes)'],
          ['mode', 'Majority · for classes, when making cells bigger'],
          ['average', 'Average · when making cells bigger'],
        ],
        hint: 'Classified rasters always use Nearest or Majority, so no new classes are invented.',
      },
      {
        key: 'field',
        label: 'Cell values from (vector input only)',
        type: 'text',
        placeholder: 'Optional attribute, e.g. shapeName',
        hint: 'Leave empty to mark every cell inside the shapes as 1.',
      },
    ],
    summary: (d) => `${d.cellSize ?? 10} m cells · ${d.method === 'bicubic' ? 'cubic' : d.method}`,
  },
  ClipRasterNode: {
    label: 'Cut to Outline',
    category: 'raster',
    icon: 'crop',
    description: 'Keeps only the part of an image inside an outline (connect it to Mask). GIS term: clip raster.',
    inputs: [
      { id: 'raster', label: 'Raster' },
      { id: 'mask', label: 'Mask' },
    ],
    defaults: { crop: true },
    params: [{ key: 'crop', label: 'Trim away the empty edges', type: 'toggle' }],
    summary: () => 'Image inside the outline',
  },
  ZonalStatsNode: {
    label: 'Average per Area',
    category: 'raster',
    icon: 'table',
    description: 'Works out the average (or highest, lowest…) value inside each area, e.g. greenness per district. Makes a map and a spreadsheet table (CSV). GIS term: zonal statistics.',
    inputs: [
      { id: 'raster', label: 'Raster' },
      { id: 'zones', label: 'Zones' },
    ],
    defaults: { stat: 'mean', band: 1 },
    params: [
      { key: 'stat', label: 'Show', type: 'select', options: STATS },
      { key: 'band', label: 'Band', type: 'number', min: 1, step: 1 },
    ],
    summary: (d) => `${label(STATS, d.stat)} of band ${d.band}`,
  },

  // ---- Cartography --------------------------------------------------------
  ColourMapNode: {
    label: 'Colour Map',
    category: 'process',
    icon: 'palette',
    description: 'Changes the colours of an image result, e.g. green-to-brown "terrain" colours for ground height. The data itself is unchanged.',
    defaults: { colormap: 'terrain', reverse: false, stretch: 'auto', min: '', max: '', band: 1, hillshade: false },
    params: [
      { key: 'colormap', label: 'Colour map', type: 'colormap' },
      { key: 'reverse', label: 'Reverse colours', type: 'toggle' },
      {
        key: 'stretch',
        label: 'Value range',
        type: 'select',
        options: [['auto', 'Automatic (ignores outliers)'], ['minmax', 'Full min – max'], ['custom', 'Custom']],
      },
      { key: 'min', label: 'Min value', type: 'number', hidden: (d) => d.stretch !== 'custom' },
      { key: 'max', label: 'Max value', type: 'number', hidden: (d) => d.stretch !== 'custom' },
      { key: 'band', label: 'Band', type: 'number', min: 1, step: 1, hint: 'For multi-band rasters, e.g. 4 = NIR in a Sentinel-2 search.' },
      {
        key: 'hillshade',
        label: 'Add hillshade relief',
        type: 'toggle',
        hint: 'Shades the colours with the terrain’s shadows — best for elevation data.',
      },
    ],
    summary: (d) => `${d.colormap}${d.reverse ? ' (reversed)' : ''}${d.hillshade ? ' · with relief' : ''}`,
  },

  // ---- Vector algorithms --------------------------------------------------
  BufferNode: {
    label: 'Zone Around (Buffer)',
    category: 'vector',
    icon: 'buffer',
    description: 'Draws a zone a set distance around shapes, e.g. 500 m either side of a river. Negative distances shrink areas. GIS term: buffer.',
    defaults: { distance: 1000, dissolve: false },
    params: [
      { key: 'distance', label: 'Distance (m)', type: 'number', step: 100 },
      { key: 'dissolve', label: 'Merge overlapping zones', type: 'toggle' },
    ],
    summary: (d) => `${Number(d.distance).toLocaleString()} m${d.dissolve ? ' · merged' : ''}`,
  },
  DistanceNode: {
    label: 'Distance to Features',
    category: 'vector',
    icon: 'ruler',
    description:
      'Distance in metres from every place to the nearest feature, e.g. to the nearest river or road. Connect an Outline or an image to Area to set the extent. GIS term: Euclidean distance.',
    inputs: [
      { id: 'features', label: 'Features' },
      { id: 'extent', label: 'Area' },
    ],
    defaults: {},
    params: [],
    summary: () => 'Metres to the nearest feature',
  },
  SpatialFilterNode: {
    label: 'Select by Location',
    category: 'vector',
    icon: 'filter',
    description: 'Keeps (or cuts away) the shapes in Data depending on where they are compared with Mask, e.g. roads inside a district. GIS term: spatial filter / clip.',
    inputs: [
      { id: 'data', label: 'Data' },
      { id: 'mask', label: 'Mask' },
    ],
    defaults: { mode: 'intersects' },
    params: [{ key: 'mode', label: 'Operation', type: 'select', options: FILTER_MODES }],
    summary: (d) => label(FILTER_MODES, d.mode),
  },
  DissolveNode: {
    label: 'Merge Shapes',
    category: 'vector',
    icon: 'merge',
    description: 'Joins shapes into one (or one per group), e.g. districts into regions. GIS term: dissolve.',
    defaults: { field: '' },
    params: [{ key: 'field', label: 'Group by (optional)', type: 'text', placeholder: 'optional, e.g. shapeName' }],
    summary: (d) => (d.field ? `By ${d.field}` : 'Merge all'),
  },
};
