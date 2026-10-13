export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export const STORAGE_KEY = 'geoflow:workflow:v1';
export const THEME_KEY = 'geoflow:theme';
export const SIDEBAR_KEY = 'geoflow:sidebar';
export const BASEMAP_KEY = 'geoflow:basemap';

// Same palette the backend uses for layer previews and composites.
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

// Max number of nodes executing on the backend at the same time.
export const MAX_PARALLEL = 4;
