import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Map, { Layer, NavigationControl, ScaleControl, Source } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import Icon from './Icon.jsx';
import { BASEMAP_KEY } from '../config.js';

// Two hostnames for the same Esri service; MapLibre spreads tile requests across them.
const ESRI_IMAGERY = ['server', 'services'].map(
  (host) => `https://${host}.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`,
);
const ESRI_ATTRIBUTION = 'Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community';

const VECTOR_STYLES = {
  light: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
  dark: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
};

const IMAGERY_STYLE = {
  version: 8,
  sources: {
    imagery: { type: 'raster', tiles: ESRI_IMAGERY, tileSize: 256, maxzoom: 19, attribution: ESRI_ATTRIBUTION },
  },
  layers: [{ id: 'imagery', type: 'raster', source: 'imagery' }],
};

const BASEMAPS = [
  ['map', 'Map'],
  ['satellite', 'Satellite'],
];

function basemapStyle(basemap, theme) {
  if (basemap === 'satellite') return IMAGERY_STYLE;
  return VECTOR_STYLES[theme] ?? VECTOR_STYLES.light;
}

function savedBasemap() {
  try {
    const value = localStorage.getItem(BASEMAP_KEY);
    return BASEMAPS.some(([v]) => v === value) ? value : 'map';
  } catch {
    return 'map';
  }
}

const KIND_ORDER = { imagery: 0, raster: 1, boundary: 2, layer: 3, vector: 4 };

const POLYGON = ['match', ['geometry-type'], ['Polygon', 'MultiPolygon'], true, false];
const LINE = ['match', ['geometry-type'], ['LineString', 'MultiLineString'], true, false];
const POINT = ['match', ['geometry-type'], ['Point', 'MultiPoint'], true, false];

/** Layer ids that react to hover, per map layer. */
function hoverIds(layer) {
  if (layer.kind === 'imagery' || layer.kind === 'raster') return [];
  if (layer.kind === 'vector') return [`${layer.id}-fill`, `${layer.id}-line`, `${layer.id}-circle`];
  return [`${layer.id}-${layer.layerType === 'buildings' || layer.kind === 'boundary' ? 'fill' : 'line'}`];
}

/** [south, north, west, east] list → [[west, south], [east, north]] for fitBounds. */
function toLngLatBounds(list) {
  const all = list.filter((b) => Array.isArray(b) && b.length === 4);
  if (!all.length) return null;
  const [s, n, w, e] = all.reduce(
    (acc, b) => [Math.min(acc[0], b[0]), Math.max(acc[1], b[1]), Math.min(acc[2], b[2]), Math.max(acc[3], b[3])],
    [90, -90, 180, -180],
  );
  return [
    [Math.max(w, -180), Math.max(s, -85)],
    [Math.min(e, 180), Math.min(n, 85)],
  ];
}

function MapLayer({ layer, visible }) {
  const visibility = visible ? 'visible' : 'none';
  if (layer.kind === 'imagery') {
    // Live, zoomable imagery limited to the Satellite node's area (instead of the fixed JPEG mosaic).
    const [s, n, w, e] = layer.bounds;
    return (
      <Source
        id={layer.id}
        type="raster"
        tiles={layer.tiles ? [layer.tiles] : ESRI_IMAGERY}
        tileSize={256}
        maxzoom={19}
        bounds={[w, s, e, n]}
        attribution={ESRI_ATTRIBUTION}
      >
        <Layer id={`${layer.id}-raster`} type="raster" layout={{ visibility }} />
      </Source>
    );
  }
  if (layer.kind === 'raster') {
    const [s, n, w, e] = layer.bounds;
    if (layer.tiles) {
      // Rendered from the GeoTIFF per tile, so it stays sharp at every zoom level.
      return (
        <Source id={layer.id} type="raster" tiles={[layer.tiles]} tileSize={256} maxzoom={18} bounds={[w, s, e, n]}>
          <Layer id={`${layer.id}-raster`} type="raster" layout={{ visibility }} paint={{ 'raster-opacity': 0.85, 'raster-fade-duration': 0 }} />
        </Source>
      );
    }
    // Older results without tiles: the single preview image, stretched over its corners (Web Mercator).
    return (
      <Source id={layer.id} type="image" url={layer.url} coordinates={[[w, n], [e, n], [e, s], [w, s]]}>
        <Layer id={`${layer.id}-raster`} type="raster" layout={{ visibility }} paint={{ 'raster-opacity': 0.85, 'raster-fade-duration': 0 }} />
      </Source>
    );
  }
  if (layer.kind === 'vector') {
    return (
      <Source id={layer.id} type="geojson" data={layer.url}>
        <Layer id={`${layer.id}-fill`} type="fill" filter={POLYGON} layout={{ visibility }} paint={{ 'fill-color': layer.color, 'fill-opacity': 0.25 }} />
        <Layer
          id={`${layer.id}-line`}
          type="line"
          filter={['any', POLYGON, LINE]}
          layout={{ visibility, 'line-join': 'round' }}
          paint={{ 'line-color': layer.color, 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 1, 12, 2] }}
        />
        <Layer
          id={`${layer.id}-circle`}
          type="circle"
          filter={POINT}
          layout={{ visibility }}
          paint={{ 'circle-color': layer.color, 'circle-radius': 4, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 }}
        />
      </Source>
    );
  }
  if (layer.kind === 'boundary') {
    return (
      <Source id={layer.id} type="geojson" data={layer.url}>
        <Layer id={`${layer.id}-fill`} type="fill" layout={{ visibility }} paint={{ 'fill-color': layer.color, 'fill-opacity': 0.08 }} />
        <Layer
          id={`${layer.id}-line`}
          type="line"
          layout={{ visibility, 'line-join': 'round' }}
          paint={{ 'line-color': layer.color, 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 1, 10, 2.5] }}
        />
      </Source>
    );
  }
  if (layer.layerType === 'buildings') {
    return (
      <Source id={layer.id} type="geojson" data={layer.url}>
        <Layer id={`${layer.id}-fill`} type="fill" layout={{ visibility }} paint={{ 'fill-color': layer.color, 'fill-opacity': 0.75 }} />
      </Source>
    );
  }
  return (
    <Source id={layer.id} type="geojson" data={layer.url}>
      <Layer
        id={`${layer.id}-line`}
        type="line"
        layout={{ visibility, 'line-join': 'round', 'line-cap': 'round' }}
        paint={{
          'line-color': layer.color,
          'line-opacity': 0.9,
          'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.6, 10, 1.5, 15, 3],
        }}
      />
    </Source>
  );
}

export default function MapPreview({ layers, theme = 'light', focus, expanded = false, onToggleExpand }) {
  const mapRef = useRef(null);
  const [hidden, setHidden] = useState({});
  const [hover, setHover] = useState(null);
  const [basemap, setBasemap] = useState(savedBasemap);

  useEffect(() => {
    try {
      localStorage.setItem(BASEMAP_KEY, basemap);
    } catch {
      /* storage unavailable — the choice just won't persist */
    }
  }, [basemap]);

  const ordered = useMemo(() => [...layers].sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind]), [layers]);
  // Remount sources when the set changes so the stacking order (imagery at the bottom) is always correct.
  const layersKey = ordered.map((l) => `${l.id}@${l.url}`).join('|');
  const bounds = useMemo(() => toLngLatBounds(ordered.map((l) => l.bounds)), [layersKey]);
  const focusBounds = useMemo(() => (focus ? toLngLatBounds([focus.bounds]) : null), [focus]);
  const interactiveIds = useMemo(
    () => ordered.flatMap(hoverIds),
    [layersKey],
  );

  const fitTo = useCallback((target, duration = 700) => {
    if (target && mapRef.current) mapRef.current.fitBounds(target, { padding: 36, duration, maxZoom: 15 });
  }, []);
  const fit = useCallback((duration) => fitTo(bounds, duration), [fitTo, bounds]);

  // A "View on map" request takes priority over fitting everything.
  useEffect(() => {
    if (focusBounds) fitTo(focusBounds);
    else fit();
  }, [focusBounds, fit, fitTo]);

  const onMouseMove = useCallback((e) => {
    const feature = e.features?.[0];
    if (!feature) return setHover(null);
    const p = feature.properties ?? {};
    const name = p.shapeName || p.NAME_3 || p.NAME_2 || p.NAME_1 || p.COUNTRY || p.name || p.display_name;
    const measure =
      p.elevation != null ? `${p.elevation} m` : p.mean != null && p.mean !== 'NaN' ? `mean ${Number(p.mean).toFixed(3)}` : null;
    const kind = p.highway || p.railway || p.waterway || (p.building ? 'building' : null) || measure;
    if (!name && !kind) return setHover(null);
    setHover({ x: e.point.x, y: e.point.y, name, kind });
  }, []);

  return (
    <div className="gf-map">
      {/* Remount when the base style changes: swapping a style in place drops the data layers added on top of it. */}
      <Map
        key={`${basemap}-${theme}`}
        ref={mapRef}
        initialViewState={{ longitude: 0, latitude: 15, zoom: 1.3 }}
        mapStyle={basemapStyle(basemap, theme)}
        maxZoom={19}
        onLoad={() => fitTo(focusBounds ?? bounds, 0)}
        interactiveLayerIds={interactiveIds}
        onMouseMove={onMouseMove}
        onMouseLeave={() => setHover(null)}
        attributionControl={{ compact: true }}
        style={{ width: '100%', height: '100%' }}
      >
        <NavigationControl position="top-right" showCompass={false} />
        <ScaleControl position="bottom-left" />
        <Fragment key={layersKey}>
          {ordered.map((layer) => (
            <MapLayer key={layer.id} layer={layer} visible={!hidden[layer.id]} />
          ))}
        </Fragment>
      </Map>

      {onToggleExpand && (
        <button
          type="button"
          className="gf-map__expand"
          onClick={onToggleExpand}
          title={expanded ? 'Move the map back to the side panel' : 'Expand the map onto the canvas'}
          aria-label={expanded ? 'Move the map back to the side panel' : 'Expand the map onto the canvas'}
        >
          <Icon name={expanded ? 'shrink' : 'expand'} size={15} />
        </button>
      )}

      <div className="gf-map__basemap gf-segmented" role="radiogroup" aria-label="Base map">
        {BASEMAPS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={basemap === value}
            className={basemap === value ? 'is-active' : ''}
            onClick={() => setBasemap(value)}
          >
            {label}
          </button>
        ))}
      </div>

      {hover && (
        <div className="gf-map__tooltip" style={{ left: hover.x + 12, top: hover.y + 12 }}>
          {hover.name && <strong>{hover.name}</strong>}
          {hover.kind && <span>{hover.kind}</span>}
        </div>
      )}

      <div className="gf-map__legend">
        <div className="gf-map__legend-head">
          <span>Layers</span>
          <button type="button" className="gf-icon-btn gf-icon-btn--small" onClick={() => fit()} disabled={!bounds} title="Zoom to data">
            <Icon name="fit" size={13} />
          </button>
        </div>
        {ordered.length === 0 && <p className="gf-hint">Run Boundary, Satellite or Layer nodes to see them here.</p>}
        {[...ordered].reverse().map((layer) => (
          <label key={layer.id} className="gf-map__legend-item">
            <input
              type="checkbox"
              checked={!hidden[layer.id]}
              onChange={() => setHidden((h) => ({ ...h, [layer.id]: !h[layer.id] }))}
            />
            <span className={`gf-swatch gf-swatch--${layer.kind}`} style={{ '--swatch': layer.color }} />
            <span className="gf-map__legend-label">{layer.label}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
