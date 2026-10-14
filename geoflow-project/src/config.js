// Settings shared across the app.

// Where the backend is. Set VITE_API_URL when building to change it. 'same-origin' means the
// backend also serves this app (as on the Render demo), so it's at the same address.
const configuredApi = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
export const API_URL = configuredApi === 'same-origin' ? window.location.origin : configuredApi;

// Names of the things saved in the browser between visits
export const STORAGE_KEY = 'geoflow:workflow:v1';
export const THEME_KEY = 'geoflow:theme';
export const SIDEBAR_KEY = 'geoflow:sidebar';
export const BASEMAP_KEY = 'geoflow:basemap';

// Colours for each kind of map feature. They match LAYER_COLORS in geoflow-backend/plotting.py,
// so the previews, Combine Layers and the map all agree.
export const LAYER_COLORS = {
  roads: '#facc15',
  highways: '#f97316',
  railways: '#3baaff',
  waterways: '#22c55e',
  rivers: '#0284c7',
  buildings: '#ef4444',
  default: '#ffffff',
};

export const BOUNDARY_COLOR = '#aa3bff';

// Most nodes sent to the backend at the same time when a workflow runs.
export const MAX_PARALLEL = 4;
