import { LAYER_COLORS } from '../config.js';
import { SPATIAL_NODE_TYPES } from './spatialNodes.js';

// Plain-language group names; the GIS term is kept in each node's description.
export const CATEGORIES = {
  input: { label: 'Start here', color: '#38bdf8' },
  source: { label: 'Get map data', color: '#a78bfa' },
  terrain: { label: 'Hills & terrain', color: '#f97316' },
  raster: { label: 'Analyse images', color: '#22c55e' },
  vector: { label: 'Shape tools', color: '#ec4899' },
  process: { label: 'Style & combine', color: '#f59e0b' },
  output: { label: 'Result', color: '#34d399' },
};

const LAYER_OPTIONS = [
  ['roads', 'All roads'],
  ['highways', 'Main roads & highways'],
  ['railways', 'Railways'],
  ['waterways', 'Rivers & streams'],
  ['rivers', 'Main rivers & canals'],
  ['buildings', 'Buildings (towns & cities only)'],
];

const BOUNDARY_SOURCES = [
  ['geoboundaries', 'Official borders (recommended)'],
  ['gadm', 'Official borders, alternative set (GADM)'],
  ['city', 'Town or city outline'],
];

const DETAIL_LEVELS = [
  [0, 'Country'],
  [1, 'Regions'],
  [2, 'Districts'],
  [3, 'Sub-districts'],
];

const label = (options, value) => options.find(([v]) => String(v) === String(value))?.[1] ?? value;

/**
 * Every node type in one place. `params` keys are sent to the backend as form
 * fields with exactly these names, so they must match main.py.
 */
export const NODE_TYPES = {
  LocationNode: {
    label: 'Place',
    category: 'input',
    icon: 'pin',
    clientOnly: true,
    hasInput: false,
    description: 'Where your map is. Search for a country, region, city or town and pick the right one from the list.',
    defaults: { location: '', place: null },
    params: [{ key: 'location', label: 'Place', type: 'place', placeholder: 'Search e.g. Tema, Ghana, Nairobi' }],
    summary: (d) => (d.place ? `${d.place.name}${d.place.country && !d.place.isCountry ? `, ${d.place.country}` : ''}` : d.location || 'No place set'),
  },
  BoundaryNode: {
    label: 'Outline',
    category: 'source',
    icon: 'boundary',
    description:
      'The outline (border) of your place, optionally split into regions or districts. GIS term: administrative boundary (geoBoundaries / GADM / OpenStreetMap).',
    defaults: { boundarySource: 'geoboundaries', boundaryAdminLevel: 0 },
    params: [
      {
        key: 'boundarySource',
        label: 'Borders from',
        type: 'select',
        options: BOUNDARY_SOURCES,
        hint: 'For a town or city, it automatically uses the town outline.',
      },
      {
        key: 'boundaryAdminLevel',
        label: 'Split into',
        type: 'segmented',
        options: DETAIL_LEVELS,
        hidden: (d) => d.boundarySource === 'city',
        hint: 'Country = one outline. Regions/Districts = the country divided into its parts (GIS: ADM0–ADM3).',
      },
    ],
    summary: (d) =>
      d.boundarySource === 'city' ? 'Town or city outline' : `Borders · ${label(DETAIL_LEVELS, d.boundaryAdminLevel)}`,
  },
  SatelliteNode: {
    label: 'Satellite Photo',
    category: 'source',
    icon: 'satellite',
    description: 'A satellite photo of your area (Esri World Imagery). Connect an Outline to frame it exactly.',
    defaults: { satelliteZoom: 7, clipToBoundary: true },
    params: [
      {
        key: 'clipToBoundary',
        label: 'Only show inside the outline',
        type: 'toggle',
        hint: 'Hides everything outside a connected Outline.',
      },
      {
        key: 'satelliteZoom',
        label: 'Detail',
        type: 'slider',
        min: 3,
        max: 14,
        step: 1,
        hint: 'Higher is sharper but slower: about 7 for a country, 12 for a city, 14 for a neighbourhood.',
      },
    ],
    summary: (d) => `Detail ${d.satelliteZoom}${d.clipToBoundary ? ' · inside outline' : ''}`,
  },
  LayerNode: {
    label: 'Map Features',
    category: 'source',
    icon: 'layers',
    description: 'Roads, railways, rivers or buildings from OpenStreetMap, cut to a connected Outline.',
    defaults: { layerType: 'roads' },
    params: [{ key: 'layerType', label: 'Show', type: 'select', options: LAYER_OPTIONS }],
    summary: (d) => label(LAYER_OPTIONS, d.layerType).split(' (')[0],
    swatch: (d) => LAYER_COLORS[d.layerType],
  },
  GeoFileNode: {
    label: 'Country Drawing',
    category: 'source',
    icon: 'file',
    description:
      'A simple drawing of the country’s shape (vector SVG from Natural Earth). You can upload your own shapefile folder instead.',
    defaults: {},
    params: [{ key: 'geoFiles', label: 'Your own shapefile folder', type: 'folder' }],
    summary: () => 'Country shape drawing',
  },
  RasterizerNode: {
    label: 'Drawing to Picture',
    category: 'process',
    icon: 'grid',
    description: 'Turns a drawing (SVG) into a picture (PNG) at the chosen quality. GIS term: rasterize.',
    defaults: { dpi: 300 },
    params: [
      {
        key: 'dpi',
        label: 'Picture quality',
        type: 'segmented',
        options: [[72, 'Screen'], [150, 'Good'], [300, 'Print'], [600, 'Best']],
        hint: 'Print quality (300 DPI) is right for most documents.',
      },
    ],
    summary: (d) => `${d.dpi} DPI`,
  },
  CompositeNode: {
    label: 'Combine Layers',
    category: 'process',
    icon: 'composite',
    description:
      'Stacks the outline, satellite photo and map features (roads, rivers…) into one finished picture. Connect them all to this node.',
    defaults: { alpha: 0.6 },
    params: [{ key: 'alpha', label: 'How strongly features show', type: 'slider', min: 0, max: 1, step: 0.05, percent: true }],
    summary: (d) => `Features ${Math.round(d.alpha * 100)}%`,
  },
  OutputImageNode: {
    label: 'Final Map',
    category: 'output',
    icon: 'image',
    hasOutput: false,
    resizable: { width: 320, height: 380, minWidth: 220, minHeight: 200 },
    description: 'Shows your finished map. Download it as a JPEG with a title and colour key. Drag its corners to resize.',
    defaults: { title: '' },
    params: [{ key: 'title', label: 'Map title', type: 'text', placeholder: 'Optional, e.g. Steep slopes in Akosombo' }],
    summary: (d) => d.title || 'Your finished map',
  },
  ...SPATIAL_NODE_TYPES,
};

export const PARAM_KEYS = Object.fromEntries(
  Object.entries(NODE_TYPES).map(([type, def]) => [type, def.params.map((p) => p.key)]),
);

let counter = 0;
export function makeNodeId(type) {
  counter += 1;
  const short = type.replace('Node', '').toLowerCase();
  return `${short}_${Date.now().toString(36).slice(-4)}${counter.toString(36)}`;
}

export function createNode(type, position, data = {}) {
  const { resizable } = NODE_TYPES[type];
  return {
    id: makeNodeId(type),
    type,
    position,
    ...(resizable ? { width: resizable.width, height: resizable.height } : {}),
    data: { ...NODE_TYPES[type].defaults, ...data, status: 'idle' },
  };
}
