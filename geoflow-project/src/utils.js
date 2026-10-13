import { API_URL } from './config.js';

export function fileNameFromUrl(url, fallback = 'geoflow-output') {
  try {
    return decodeURIComponent(new URL(url).pathname.split('/').pop()) || fallback;
  } catch {
    return fallback;
  }
}

/** The `download` attribute is ignored cross-origin, so fetch the file as a blob first. */
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

/** A sensible map title from a node result, e.g. "Steepness · Akosombo". */
export function autoTitle(result, fallback = 'Map') {
  const what = result?.legend?.label;
  const where = result?.place?.name ?? result?.location;
  return [what, where].filter(Boolean).join(' · ') || fallback;
}

/** Downloads a finished JPEG (title, picture, north arrow, scale bar, colour key) made by the backend. */
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

/** The JPEG export settings for a node's result (Final Map title wins if set). */
export function jpegOptions(node, def) {
  const r = node.data.result ?? {};
  return {
    imageUrl: r.outputImageUrl,
    title: node.data.title?.trim() || autoTitle(r, def.label),
    legend: r.legend ?? null,
    bounds: r.imageBounds ?? r.rasterBounds ?? r.satelliteBounds ?? null,
  };
}

export function downloadJson(data, filename) {
  const blobUrl = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const a = Object.assign(document.createElement('a'), { href: blobUrl, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}

/** [south, north, west, east] → readable string */
export function formatBounds(b) {
  if (!Array.isArray(b) || b.length !== 4) return '—';
  const [s, n, w, e] = b.map(Number);
  const lat = (v) => `${Math.abs(v).toFixed(2)}°${v >= 0 ? 'N' : 'S'}`;
  const lon = (v) => `${Math.abs(v).toFixed(2)}°${v >= 0 ? 'E' : 'W'}`;
  return `${lat(s)} – ${lat(n)}, ${lon(w)} – ${lon(e)}`;
}
