/** Small helpers for downloading files and formatting values. */
import { API_URL } from './config.js';

/** The file name at the end of a link, or the fallback if there isn't one. */
export function fileNameFromUrl(url, fallback = 'geoflow-output') {
  try {
    return decodeURIComponent(new URL(url).pathname.split('/').pop()) || fallback;
  } catch {
    return fallback;
  }
}

/**
 * Downloads a file from a link. Browsers ignore the `download` attribute for files on another
 * address (the backend), so the file is fetched first and saved from memory. If that fails,
 * it's opened in a new tab instead.
 */
export async function downloadFile(url, filename = fileNameFromUrl(url)) {
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(response.statusText);
    const blobUrl = URL.createObjectURL(await response.blob());
    const a = Object.assign(document.createElement('a'), { href: blobUrl, download: filename });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  } catch {
    window.open(url, '_blank', 'noopener');
  }
}

/** A map title made from a result, like "Steepness · Akosombo". */
export function autoTitle(result, fallback = 'Map') {
  const what = result?.legend?.label;
  const where = result?.place?.name ?? result?.location;
  return [what, where].filter(Boolean).join(' · ') || fallback;
}

/**
 * Asks the backend to build a finished JPEG map (title, picture, north arrow, scale bar and
 * legend) and downloads it.
 */
export async function exportJpeg({ imageUrl, title, subtitle = '', legend = null, bounds = null }) {
  const response = await fetch(`${API_URL}/export/jpeg`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ imageUrl, title, subtitle, legend, bounds }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Export failed (HTTP ${response.status})`);
  }
  const blobUrl = URL.createObjectURL(await response.blob());
  const name = `${title.replace(/[^\w -]+/g, '').trim().replace(/\s+/g, '_') || 'geoflow_map'}.jpg`;
  const a = Object.assign(document.createElement('a'), { href: blobUrl, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}

/** What to send to exportJpeg for a node. A title typed into a Final Map node is used if there is one. */
export function jpegOptions(node, def) {
  const r = node.data.result ?? {};
  return {
    imageUrl: r.outputImageUrl,
    title: node.data.title?.trim() || autoTitle(r, def.label),
    legend: r.legend ?? null,
    bounds: r.imageBounds ?? r.rasterBounds ?? r.satelliteBounds ?? null,
  };
}

/** Saves data as a .json file (used to export a workflow). */
export function downloadJson(data, filename) {
  const blobUrl = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const a = Object.assign(document.createElement('a'), { href: blobUrl, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}

/** An area given as [south, north, west, east], written for people, like "5.50°N to 5.70°N, 0.30°W to 0.10°W". */
export function formatBounds(b) {
  if (!Array.isArray(b) || b.length !== 4) return 'n/a';
  const [s, n, w, e] = b.map(Number);
  const lat = (v) => `${Math.abs(v).toFixed(2)}°${v >= 0 ? 'N' : 'S'}`;
  const lon = (v) => `${Math.abs(v).toFixed(2)}°${v >= 0 ? 'E' : 'W'}`;
  return `${lat(s)} to ${lat(n)}, ${lon(w)} to ${lon(e)}`;
}
