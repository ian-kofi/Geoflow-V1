/**
 * The panel on the right. The Inspector tab shows the selected node's settings, result,
 * legend, details and download buttons. The Map tab shows every result on an interactive map.
 */
import { lazy, Suspense, useMemo } from 'react';
import Icon from './Icon.jsx';
import ParamFields from './ParamFields.jsx';
import { CATEGORIES, NODE_TYPES } from '../nodes/registry.js';
import { BOUNDARY_COLOR, LAYER_COLORS } from '../config.js';
import { useWorkflow } from '../workflow/WorkflowContext.jsx';
import { downloadFile, exportJpeg, fileNameFromUrl, formatBounds, jpegOptions } from '../utils.js';
import { useUi } from '../uiContext.js';
import Legend, { formatValue } from './Legend.jsx';

// The map library is about 800 KB, so it's only loaded when a map is first opened.
export const MapPreview = lazy(() => import('./MapPreview.jsx'));

/** A link without its "?v=..." version part, so two versions of the same file count as the same. */
const stripVersion = (url) => url?.split('?')[0];

/**
 * Every result on the canvas that can go on the map, as a list of map layers: satellite photos,
 * outlines, map features, analysis results and other shapes.
 */
export function collectMapLayers(nodes) {
  const layers = [];
  const seen = new Set();
  let vectorIndex = 0;
  for (const node of nodes) {
    const r = node.data.result;
    if (!r) continue;
    const def = NODE_TYPES[node.type];
    if (r.satelliteBounds && r.outputImageUrl) {
      layers.push({
        id: `sat-${node.id}`,
        kind: 'imagery',
        // Tiles cut to the outline come from the backend. Otherwise the map uses ordinary Esri
        // tiles, limited to the photo's area.
        tiles: r.satelliteTilesUrl ?? null,
        url: r.outputImageUrl,
        bounds: r.satelliteBounds,
        color: '#94a3b8',
        label: `Satellite imagery${r.satelliteTilesUrl ? ' (clipped)' : ''} · ${r.location ?? node.id}`,
      });
    }
    // Shape results from analysis nodes are also passed on as outlines. Show each file only once,
    // and show analysis shapes as shapes rather than as outlines.
    if (r.boundaryGeoJsonUrl && !r.vectorGeoJsonUrl && !seen.has(stripVersion(r.boundaryGeoJsonUrl))) {
      seen.add(stripVersion(r.boundaryGeoJsonUrl));
      layers.push({ id: `bnd-${node.id}`, kind: 'boundary', url: r.boundaryGeoJsonUrl, bounds: r.boundaryBounds, color: BOUNDARY_COLOR, label: `${r.location ?? 'Boundary'} · ${def.summary(node.data)}` });
    }
    if (r.layerGeoJsonUrl) {
      layers.push({ id: `lyr-${node.id}`, kind: 'layer', layerType: r.layerType, url: r.layerGeoJsonUrl, color: LAYER_COLORS[r.layerType] ?? LAYER_COLORS.default, label: `${def.summary(node.data)} · ${r.location ?? ''}` });
    }
    if (r.rasterBounds && r.outputImageUrl && node.type !== 'OutputImageNode') {
      // Tiles drawn by the backend stay sharp when you zoom in. The preview picture is used if
      // there are no tiles.
      layers.push({ id: `ras-${node.id}`, kind: 'raster', url: r.rasterTilesUrl ?? r.outputImageUrl, tiles: r.rasterTilesUrl ?? null, bounds: r.rasterBounds, color: r.legend?.colors?.[4] ?? '#94a3b8', label: `${def.label} · ${def.summary(node.data)}` });
    }
    if (r.vectorGeoJsonUrl) {
      layers.push({ id: `vec-${node.id}`, kind: 'vector', url: r.vectorGeoJsonUrl, bounds: r.vectorBounds, color: VECTOR_COLORS[vectorIndex++ % VECTOR_COLORS.length], label: `${def.label} · ${def.summary(node.data)}` });
    }
  }
  return layers;
}

// Colours for shape results on the map, used in turn
const VECTOR_COLORS = ['#ec4899', '#38bdf8', '#f59e0b', '#22c55e', '#a78bfa', '#ef4444'];

/** A raster result's lowest, highest, average and spread, and how much of it has data. */
function Stats({ stats }) {
  return (
    <div className="gf-stats">
      {[
        ['Min', stats.min],
        ['Max', stats.max],
        ['Mean', stats.mean],
        ['Std dev', stats.std],
      ].map(([label, value]) => (
        <div key={label}>
          <span>{label}</span>
          <strong className="gf-mono">{formatValue(value)}</strong>
        </div>
      ))}
      <div>
        <span>Valid</span>
        <strong className="gf-mono">{stats.validPercent}%</strong>
      </div>
    </div>
  );
}

function DetailRow({ label, children }) {
  return (
    <div className="gf-detail">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** Everything about the selected node: description, settings, result, downloads and details. */
function NodeDetails({ node }) {
  const { runNode, running, log } = useWorkflow();
  const { showOnMap } = useUi();
  const def = NODE_TYPES[node.type];
  const category = CATEGORIES[def.category];
  const r = node.data.result;
  const imageUrl = r?.outputImageUrl;

  return (
    <div className="gf-inspector__content" style={{ '--accent': category.color }}>
      <div className="gf-inspector__head">
        <span className="gf-node__icon gf-node__icon--lg">
          <Icon name={def.icon} size={18} />
        </span>
        <div>
          <div className="gf-inspector__title">{def.label}</div>
          <div className="gf-inspector__sub">
            {category.label} · <span className="gf-mono">{node.id}</span>
          </div>
        </div>
      </div>
      <p className="gf-inspector__desc">{def.description}</p>

      {def.params.length > 0 && (
        <section className="gf-card">
          <h4 className="gf-card__title">
            <Icon name="sliders" size={13} /> Settings
          </h4>
          <ParamFields nodeId={node.id} def={def} data={node.data} />
        </section>
      )}

      <div className="gf-inspector__actions">
        <button type="button" className="gf-btn gf-btn--primary" disabled={running} onClick={() => runNode(node.id)}>
          <Icon name="play" size={11} /> Run node
        </button>
        <button type="button" className="gf-btn gf-btn--ghost" disabled={running} onClick={() => runNode(node.id, { force: true })}>
          <Icon name="refresh" size={13} /> Force re-run
        </button>
      </div>

      {node.data.error && (
        <div className="gf-alert">
          <Icon name="alert" size={13} />
          <span>{node.data.error}</span>
        </div>
      )}

      {imageUrl && (
        <section className="gf-card">
          <h4 className="gf-card__title">
            <Icon name="image" size={13} /> Output
          </h4>
          <a className="gf-inspector__image" href={imageUrl} target="_blank" rel="noreferrer">
            <img src={imageUrl} alt={`${def.label} output`} decoding="async" />
          </a>
          <div className="gf-inspector__actions">
            <button
              type="button"
              className="gf-btn gf-btn--primary gf-btn--small"
              onClick={() => exportJpeg(jpegOptions(node, def)).catch((err) => log('error', err.message))}
              title="A finished map picture with a title, north arrow, scale bar and legend"
            >
              <Icon name="download" size={13} /> Download JPEG map
            </button>
            <button
              type="button"
              className="gf-btn gf-btn--ghost gf-btn--small"
              onClick={() => downloadFile(imageUrl)}
              title="Just the picture, without the title or legend"
            >
              <Icon name="download" size={13} /> Picture only
            </button>
            <a className="gf-btn gf-btn--ghost gf-btn--small" href={imageUrl} target="_blank" rel="noreferrer">
              <Icon name="external" size={13} /> Open
            </a>
            {(r.satelliteBounds || r.rasterBounds || r.vectorBounds || r.boundaryBounds) && (
              <button
                type="button"
                className="gf-btn gf-btn--ghost gf-btn--small"
                onClick={() => showOnMap(r.satelliteBounds || r.rasterBounds || r.vectorBounds || r.boundaryBounds)}
              >
                <Icon name="map" size={13} /> {r.satelliteBounds ? 'Explore imagery on map' : 'View on map'}
              </button>
            )}
          </div>
          {r.legend && <Legend legend={r.legend} />}
        </section>
      )}

      {r && (r.stats || r.details || r.rasterUrl || r.vectorGeoJsonUrl) && (
        <section className="gf-card">
          <h4 className="gf-card__title">
            <Icon name="table" size={13} /> Analysis
          </h4>
          {r.stats && <Stats stats={r.stats} />}
          {r.details && (
            <dl className="gf-details">
              {Object.entries(r.details).map(([label, value]) => (
                <DetailRow key={label} label={label}>
                  {value}
                </DetailRow>
              ))}
            </dl>
          )}
          <div className="gf-inspector__actions">
            {r.rasterUrl && (
              <button type="button" className="gf-btn gf-btn--ghost gf-btn--small" onClick={() => downloadFile(r.rasterUrl)}>
                <Icon name="download" size={13} /> GeoTIFF
              </button>
            )}
            {r.vectorGeoJsonUrl && (
              <button type="button" className="gf-btn gf-btn--ghost gf-btn--small" onClick={() => downloadFile(r.vectorGeoJsonUrl)}>
                <Icon name="download" size={13} /> GeoJSON
              </button>
            )}
            {r.tableUrl && (
              <button type="button" className="gf-btn gf-btn--ghost gf-btn--small" onClick={() => downloadFile(r.tableUrl)}>
                <Icon name="download" size={13} /> CSV table
              </button>
            )}
          </div>
        </section>
      )}

      {r && (
        <section className="gf-card">
          <h4 className="gf-card__title">
            <Icon name="map" size={13} /> Result
          </h4>
          <dl className="gf-details">
            {r.location && <DetailRow label="Location">{r.location}</DetailRow>}
            {r.boundaryBounds && <DetailRow label="Extent">{formatBounds(r.boundaryBounds)}</DetailRow>}
            {r.satelliteBounds && <DetailRow label="Imagery extent">{formatBounds(r.satelliteBounds)}</DetailRow>}
            {r.layerType && <DetailRow label="Layer">{r.layerType}</DetailRow>}
            {node.data.elapsed != null && <DetailRow label="Run time">{node.data.elapsed.toFixed(1)}s</DetailRow>}
            {r.boundaryGeoJsonUrl && !r.vectorGeoJsonUrl && (
              <DetailRow label="Boundary">
                <button type="button" className="gf-link" onClick={() => downloadFile(r.boundaryGeoJsonUrl)}>
                  {fileNameFromUrl(r.boundaryGeoJsonUrl)}
                </button>
              </DetailRow>
            )}
            {r.layerGeoJsonUrl && (
              <DetailRow label="GeoJSON">
                <button type="button" className="gf-link" onClick={() => downloadFile(r.layerGeoJsonUrl)}>
                  {fileNameFromUrl(r.layerGeoJsonUrl)}
                </button>
              </DetailRow>
            )}
          </dl>
          <details className="gf-raw">
            <summary>Raw response</summary>
            <pre className="gf-mono">{JSON.stringify(r, null, 2)}</pre>
          </details>
        </section>
      )}
    </div>
  );
}

/** Shown when no node is selected: keyboard shortcuts and a count of nodes. */
function EmptyState({ counts }) {
  return (
    <div className="gf-inspector__content gf-inspector__empty">
      <Icon name="sliders" size={28} />
      <h3>Nothing selected</h3>
      <p>Select a node to edit its settings and inspect its output.</p>
      <dl className="gf-details gf-shortcuts">
        <DetailRow label="Run workflow">
          <kbd>Ctrl</kbd> + <kbd>Enter</kbd>
        </DetailRow>
        <DetailRow label="Re-run everything">
          <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>Enter</kbd>
        </DetailRow>
        <DetailRow label="Stop">
          <kbd>Esc</kbd>
        </DetailRow>
        <DetailRow label="Delete selection">
          <kbd>Del</kbd>
        </DetailRow>
      </dl>
      <p className="gf-hint">
        {counts.total} nodes · {counts.done} up to date. Unchanged nodes are cached and skipped on the next run.
      </p>
    </div>
  );
}

/**
 * The right hand panel with its two tabs. When the map has been expanded over the canvas, the
 * Map tab shows a note with a button to bring it back.
 */
export default function Inspector({
  tab,
  onTabChange,
  selectedNode,
  nodes,
  counts,
  theme,
  mapFocus,
  mapExpanded,
  onToggleMapExpanded,
  onClose,
}) {
  const mapLayers = useMemo(() => (tab === 'map' && !mapExpanded ? collectMapLayers(nodes) : []), [tab, nodes, mapExpanded]);

  return (
    <aside className="gf-inspector">
      <div className="gf-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'node'} className={tab === 'node' ? 'is-active' : ''} onClick={() => onTabChange('node')}>
          <Icon name="sliders" size={13} /> Inspector
        </button>
        <button type="button" role="tab" aria-selected={tab === 'map'} className={tab === 'map' ? 'is-active' : ''} onClick={() => onTabChange('map')}>
          <Icon name="map" size={13} /> Map
        </button>
        <button type="button" className="gf-icon-btn gf-tabs__close" onClick={onClose} title="Close panel">
          <Icon name="x" size={14} />
        </button>
      </div>
      {tab === 'node' ? (
        selectedNode ? (
          <NodeDetails node={selectedNode} />
        ) : (
          <EmptyState counts={counts} />
        )
      ) : mapExpanded ? (
        <div className="gf-inspector__content gf-inspector__empty">
          <Icon name="expand" size={26} />
          <h3>The map is on the canvas</h3>
          <p>It’s expanded over the node canvas. Your workflow is still there underneath.</p>
          <button type="button" className="gf-btn gf-btn--ghost" onClick={onToggleMapExpanded}>
            <Icon name="shrink" size={13} /> Move map back here
          </button>
        </div>
      ) : (
        <Suspense fallback={<div className="gf-map gf-map--loading">Loading map…</div>}>
          <MapPreview layers={mapLayers} theme={theme} focus={mapFocus} onToggleExpand={onToggleMapExpanded} />
        </Suspense>
      )}
    </aside>
  );
}
