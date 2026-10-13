import { memo, useEffect, useState } from 'react';
import { Handle, NodeResizer, Position, useReactFlow } from '@xyflow/react';
import Icon from '../components/Icon.jsx';
import Legend from '../components/Legend.jsx';
import ParamFields from '../components/ParamFields.jsx';
import { CATEGORIES, NODE_TYPES } from './registry.js';
import { useWorkflow } from '../workflow/WorkflowContext.jsx';
import { exportJpeg, jpegOptions } from '../utils.js';
import { useUi } from '../uiContext.js';

const STATUS_LABEL = {
  idle: 'Ready',
  queued: 'Queued',
  running: 'Running',
  done: 'Done',
  stale: 'Outdated',
  error: 'Error',
  skipped: 'Skipped',
};

function Timer({ since }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, []);
  return <span className="gf-mono">{((now - since) / 1000).toFixed(1)}s</span>;
}

function Preview({ type, result }) {
  const [loaded, setLoaded] = useState(false);
  const url = result?.outputImageUrl;
  useEffect(() => setLoaded(false), [url]);
  if (!url) return null;
  return (
    <a
      className={`gf-preview nodrag ${type === 'OutputImageNode' ? 'gf-preview--large' : ''} ${loaded ? 'is-loaded' : ''}`}
      href={url}
      target="_blank"
      rel="noreferrer"
      title="Open full size"
    >
      <img src={url} alt="" loading="lazy" decoding="async" draggable={false} onLoad={() => setLoaded(true)} />
    </a>
  );
}

function GeoNode({ id, type, data, selected }) {
  const def = NODE_TYPES[type];
  const category = CATEGORIES[def.category];
  const { runNode, running, deleteNode, log } = useWorkflow();
  const { updateNodeData, updateNode } = useReactFlow();
  const { showOnMap } = useUi();
  const status = data.status ?? 'idle';
  const result = data.result;
  const swatch = def.swatch?.(data);
  const subtitle = def.summary?.(data);
  const collapsed = Boolean(data.collapsed);
  const resizable = def.resizable && !collapsed;
  const mapBounds = result?.rasterBounds || result?.vectorBounds || (type === 'SatelliteNode' && result?.satelliteBounds);

  // Not a setting: updates the node directly so it doesn't mark it as outdated. A resizable
  // node remembers its height so collapsing shrinks it and expanding restores the size.
  const toggleCollapsed = () => {
    if (!def.resizable) return updateNodeData(id, { collapsed: !collapsed });
    updateNode(id, (node) =>
      collapsed
        ? { height: node.data.expandedHeight ?? def.resizable.height, data: { ...node.data, collapsed: false } }
        : { height: undefined, data: { ...node.data, collapsed: true, expandedHeight: node.height ?? node.measured?.height } },
    );
  };

  return (
    <div
      className={`gf-node is-${status} ${selected ? 'is-selected' : ''} ${collapsed ? 'is-collapsed' : ''} ${resizable ? 'gf-node--resizable' : ''}`}
      style={{ '--accent': swatch ?? category.color }}
    >
      {resizable && (
        <NodeResizer
          isVisible={selected}
          minWidth={def.resizable.minWidth}
          minHeight={def.resizable.minHeight}
          lineClassName="gf-resize-line"
          handleClassName="gf-resize-handle"
        />
      )}

      {def.hasInput !== false &&
        (def.inputs ? (
          // Named inputs, spaced down the left edge, each with its label outside the node.
          def.inputs.map((input, i) => (
            <Handle
              key={input.id}
              id={input.id}
              type="target"
              position={Position.Left}
              className="gf-handle"
              style={{ top: `${((i + 1) / (def.inputs.length + 1)) * 100}%` }}
              title={`${input.label} input`}
            >
              <span className="gf-handle__label">{input.label}</span>
            </Handle>
          ))
        ) : (
          <Handle type="target" position={Position.Left} className="gf-handle" />
        ))}

      <header className="gf-node__header" onDoubleClick={toggleCollapsed}>
        <button
          type="button"
          className="gf-icon-btn gf-icon-btn--small gf-node__collapse nodrag"
          onClick={toggleCollapsed}
          onDoubleClick={(e) => e.stopPropagation()}
          aria-expanded={!collapsed}
          aria-label={collapsed ? `Expand ${def.label} node` : `Collapse ${def.label} node`}
          title={collapsed ? 'Expand' : 'Collapse'}
        >
          <Icon name="chevron" size={14} />
        </button>
        <span className="gf-node__icon">
          <Icon name={def.icon} size={15} />
        </span>
        <div className="gf-node__titles">
          <div className="gf-node__title">{def.label}</div>
          <div className="gf-node__subtitle">{subtitle}</div>
        </div>
        <span
          className={`gf-status gf-status--${status}`}
          // When collapsed the error box is hidden, so surface the message on hover.
          title={collapsed && data.error ? `${STATUS_LABEL[status]}: ${data.error}` : STATUS_LABEL[status]}
        >
          <span className="gf-status__dot" />
          {STATUS_LABEL[status]}
        </span>
      </header>

      {!collapsed && (
        <>
          <div className="gf-node__body">
            {type !== 'OutputImageNode' && <ParamFields nodeId={id} def={def} data={data} compact />}

            {type === 'LocationNode' && result?.location && status === 'done' && (
              <div className="gf-chip">
                <Icon name="check" size={12} /> Sending “{result.location}” downstream
              </div>
            )}

            <Preview type={type} result={result} />
            {result?.legend && <Legend legend={result.legend} compact />}

            {type === 'OutputImageNode' && !result?.outputImageUrl && (
              <div className="gf-empty">
                <Icon name="image" size={22} />
                Connect a node that produces an image, then run.
              </div>
            )}

            {data.error && (status === 'error' || status === 'skipped') && (
              <div className={`gf-alert ${status === 'skipped' ? 'gf-alert--muted' : ''}`}>
                <Icon name="alert" size={13} />
                <span>{data.error}</span>
              </div>
            )}
          </div>

          <footer className="gf-node__footer">
            <button
              type="button"
              className="gf-btn gf-btn--small nodrag"
              disabled={running}
              onClick={(e) => runNode(id, { force: e.shiftKey })}
              title="Run this node and anything it depends on (Shift+click to force)"
            >
              <Icon name="play" size={11} /> Run
            </button>
            <span className="gf-node__meta">
              {status === 'running' && data.startedAt ? (
                <Timer since={data.startedAt} />
              ) : data.elapsed != null && status !== 'idle' ? (
                <span className="gf-mono">{data.elapsed.toFixed(1)}s</span>
              ) : null}
            </span>
            {mapBounds && (
              <button
                type="button"
                className="gf-icon-btn nodrag"
                onClick={() => showOnMap(mapBounds)}
                title={type === 'SatelliteNode' ? 'Explore zoomable imagery on the map' : 'Show on the map'}
              >
                <Icon name="map" size={14} />
              </button>
            )}
            {type === 'OutputImageNode' && result?.outputImageUrl && (
              <button
                type="button"
                className="gf-btn gf-btn--small nodrag"
                onClick={() => exportJpeg(jpegOptions({ data }, def)).catch((err) => log('error', err.message))}
                title="Download a finished JPEG with title, north arrow and colour key"
              >
                <Icon name="download" size={12} /> JPEG
              </button>
            )}
            <button type="button" className="gf-icon-btn gf-icon-btn--danger nodrag" onClick={() => deleteNode(id)} title="Delete node">
              <Icon name="trash" size={13} />
            </button>
          </footer>
        </>
      )}

      {def.hasOutput !== false && <Handle type="source" position={Position.Right} className="gf-handle" />}
    </div>
  );
}

export default memo(GeoNode);
