/**
 * Every node type and how it appears in the app.
 *
 * Each entry describes one node type:
 *   label, description   the name and help text shown in the sidebar and Inspector
 *   category             which sidebar group it's listed under (see CATEGORIES)
 *   icon                 an icon name from components/Icon.jsx
 *   defaults             the settings a new node starts with
 *   params               the settings shown on the node. Each `key` is sent to the backend as a
 *                        form field of that name, so it has to match what the backend reads.
 *   summary              a one line description of the current settings, shown under the title
 *   inputs               named inputs, for nodes that need to tell their inputs apart
 *   clientOnly           the node runs in the browser without asking the backend (Place)
 *   hasInput, hasOutput  set to false to hide the node's input or output connector
 *   resizable            the node can be resized, with its starting and smallest sizes
 *
 * The analysis nodes are defined in spatialNodes.js and added at the end.
 */
import { LAYER_COLORS } from '../config.js';
import { SPATIAL_NODE_TYPES } from './spatialNodes.js';

// Sidebar groups, named in plain language. The GIS term for each node is in its description.
export const CATEGORIES = {
  input: { label: 'Start here', color: '#38bdf8' },
  source: { label: 'Get map data', color: '#a78bfa' },
  terrain: { label: 'Hills and terrain', color: '#f97316' },
  raster: { label: 'Analyse images', color: '#22c55e' },
  vector: { label: 'Shape tools', color: '#ec4899' },
  process: { label: 'Style and combine', color: '#f59e0b' },
  output: { label: 'Result', color: '#34d399' },
};

// The Map Features options, as [value sent to the backend, label]
const LAYER_OPTIONS = [
  ['roads', 'All roads'],
  ['highways', 'Main roads and highways'],
  ['railways', 'Railways'],
  ['waterways', 'Rivers and streams'],
  ['rivers', 'Main rivers and canals'],
  ['buildings', 'Buildings (towns and cities only)'],
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

/** The label for a value in a list of [value, label] options. */
const label = (options, value) => options.find(([v]) => String(v) === String(value))?.[1] ?? value;

export const NODE_TYPES = {
  LocationNode: {
    label: 'Place',
    category: 'input',
    icon: 'pin',
    clientOnly: true,
    hasInput: false,
    description: 'Where your map is. Search for a country, region, city or town and pick the right one from the list.',
    defaults: { location: '', place: null },
    params: [{ key: 'location', label: 'Place', type: 'place', placeholder: 'Search, for example Tema, Ghana or Nairobi' }],
    summary: (d) => (d.place ? `${d.place.name}${d.place.country && !d.place.isCountry ? `, ${d.place.country}` : ''}` : d.location || 'No place set'),
  },
  BoundaryNode: {
    label: 'Outline',
    category: 'source',
    icon: 'boundary',
    description:
      'The outline (border) of your place, which can be split into regions or districts. GIS term: administrative boundary, from geoBoundaries, GADM or OpenStreetMap.',
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
        hint: 'Country gives one outline. Regions and Districts divide the country into its parts (GIS levels ADM0 to ADM3).',
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
      'A simple drawing of the country’s shape (a vector SVG from Natural Earth). You can upload your own shapefile folder instead.',
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
      'Puts the outline, a satellite photo or analysis result, and map features such as roads or rivers together in one finished picture. Connect them all to this node.',
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
    description: 'Shows your finished map. Download it as a JPEG with a title and legend. Drag its corners to resize.',
    defaults: { title: '' },
    params: [{ key: 'title', label: 'Map title', type: 'text', placeholder: 'Optional, for example Steep slopes in Akosombo' }],
    summary: (d) => d.title || 'Your finished map',
  },
  ...SPATIAL_NODE_TYPES,
};

/** The setting names of each node type. */
export const PARAM_KEYS = Object.fromEntries(
  Object.entries(NODE_TYPES).map(([type, def]) => [type, def.params.map((p) => p.key)]),
);

let counter = 0;
/**
 * A new id for a node, like "slope_ab12c": the type, then part of the current time and a
 * counter, so ids don't repeat even when several nodes are made at once.
 */
export function makeNodeId(type) {
  counter += 1;
  const short = type.replace('Node', '').toLowerCase();
  return `${short}_${Date.now().toString(36).slice(-4)}${counter.toString(36)}`;
}

/** A new node of the given type at `position`, with its default settings plus any in `data`. */
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
