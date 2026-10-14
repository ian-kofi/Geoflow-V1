/**
 * The settings controls for a node, built from its `params` list in the registry. Each
 * setting's `type` picks the control: text, number, date, select, segmented (a row of buttons),
 * slider, toggle, file, folder, colormap, compass, elevation or place.
 *
 * Used both on the node itself (compact, without hints) and in the Inspector.
 */
import { useRef } from 'react';
import Icon from './Icon.jsx';
import PlaceField from './PlaceField.jsx';
import { CompassDial, ElevationDial } from './AngleDials.jsx';
import ColormapPicker from './ColormapPicker.jsx';
import { describeFiles } from '../workflow/fileStore.js';
import { useWorkflow } from '../workflow/WorkflowContext.jsx';

/** A file size written for people, like 512 B, 40 KB or 2.5 MB. */
function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

/**
 * A button to choose a folder (type 'folder') or files (type 'file'). The files themselves are
 * kept in fileStore, and the node only stores a short description of them.
 */
function FileField({ nodeId, param, value }) {
  const { setFiles } = useWorkflow();
  const inputRef = useRef(null);
  const folder = param.type === 'folder';
  const pickerProps = folder ? { webkitdirectory: '', directory: '' } : { accept: param.accept };
  const label = folder
    ? value?.count ? 'Change folder' : 'Upload folder (optional)'
    : value?.count ? 'Choose a different file' : 'Choose file…';
  return (
    <div className="gf-folder">
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        {...pickerProps}
        onChange={(e) => {
          const files = [...e.target.files];
          if (files.length) setFiles(nodeId, param.key, files, describeFiles(files));
          e.target.value = '';
        }}
      />
      <button type="button" className="gf-btn gf-btn--ghost gf-btn--block nodrag" onClick={() => inputRef.current?.click()}>
        <Icon name={folder ? 'folder' : 'upload'} size={14} />
        {label}
      </button>
      {value?.count > 0 && (
        <div className="gf-folder__meta">
          <span className="gf-mono">{value.root}</span>
          <span>
            {value.count > 1 ? `${value.count} files · ` : ''}
            {formatBytes(value.bytes)}
          </span>
        </div>
      )}
    </div>
  );
}

/** All of a node's settings that aren't hidden by its current choices. */
export default function ParamFields({ nodeId, def, data, compact = false }) {
  const { updateParam, runNode, running } = useWorkflow();
  const visible = def.params.filter((p) => !p.hidden?.(data));
  if (!visible.length) return null;

  return (
    <div className={`gf-fields ${compact ? 'gf-fields--compact' : ''}`}>
      {visible.map((param) => {
        const value = data[param.key];
        const set = (v) => updateParam(nodeId, param.key, v);
        const id = `${nodeId}-${param.key}`;

        let control;
        switch (param.type) {
          case 'text':
            control = (
              <input
                id={id}
                className={`gf-input nodrag ${param.mono ? 'gf-mono' : ''}`}
                type="text"
                value={value ?? ''}
                placeholder={param.placeholder}
                spellCheck={false}
                onChange={(e) => set(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !running) runNode(nodeId);
                }}
              />
            );
            break;
          case 'number':
            control = (
              <input
                id={id}
                className="gf-input nodrag nowheel"
                type="number"
                value={value ?? ''}
                min={param.min}
                max={param.max}
                step={param.step ?? 'any'}
                onChange={(e) => set(e.target.value === '' ? '' : Number(e.target.value))}
              />
            );
            break;
          case 'date':
            control = (
              <input id={id} className="gf-input nodrag" type="date" value={value ?? ''} onChange={(e) => set(e.target.value)} />
            );
            break;
          case 'select':
            control = (
              <select id={id} className="gf-input gf-select nodrag nowheel" value={value} onChange={(e) => set(e.target.value)}>
                {param.options.map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </select>
            );
            break;
          case 'segmented':
            control = (
              <div className="gf-segmented nodrag" role="radiogroup" aria-labelledby={`${id}-label`}>
                {param.options.map(([v, label]) => (
                  <button
                    key={v}
                    type="button"
                    role="radio"
                    aria-checked={String(value) === String(v)}
                    className={String(value) === String(v) ? 'is-active' : ''}
                    onClick={() => set(v)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            );
            break;
          case 'slider':
            control = (
              <div className="gf-slider">
                <input
                  id={id}
                  className="nodrag nowheel"
                  type="range"
                  min={param.min}
                  max={param.max}
                  step={param.step}
                  value={value}
                  style={{ '--fill': `${((value - param.min) / (param.max - param.min)) * 100}%` }}
                  onChange={(e) => set(Number(e.target.value))}
                />
                <output htmlFor={id} className="gf-mono">
                  {param.percent ? `${Math.round(value * 100)}%` : value}
                </output>
              </div>
            );
            break;
          case 'folder':
          case 'file':
            control = <FileField nodeId={nodeId} param={param} value={value} />;
            break;
          case 'colormap':
            control = <ColormapPicker id={id} value={value} reverse={Boolean(data.reverse)} onChange={set} />;
            break;
          case 'compass':
            control = <CompassDial id={id} value={value} step={param.step} onChange={set} />;
            break;
          case 'elevation':
            control = <ElevationDial id={id} value={value} min={param.min} max={param.max} step={param.step} onChange={set} />;
            break;
          case 'place':
            control = (
              <PlaceField
                id={id}
                value={value}
                place={data.place}
                placeholder={param.placeholder}
                onTextChange={(text) => {
                  // Typing again means the earlier pick no longer matches, so forget it
                  set(text);
                  if (data.place) updateParam(nodeId, 'place', null);
                }}
                onPick={(candidate) => {
                  set(candidate.name);
                  updateParam(nodeId, 'place', candidate);
                }}
                onEnter={() => !running && runNode(nodeId)}
              />
            );
            break;
          case 'toggle':
            return (
              <div className="gf-field" key={param.key}>
                <label htmlFor={id} className="gf-toggle nodrag">
                  <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => set(e.target.checked)} />
                  {param.label}
                </label>
                {!compact && param.hint && <p className="gf-hint">{param.hint}</p>}
              </div>
            );
          default:
            control = null;
        }

        return (
          <div className="gf-field" key={param.key}>
            <label id={`${id}-label`} htmlFor={id} className="gf-label">
              {param.label}
              {param.suffix && <span className="gf-label__suffix">{param.suffix}</span>}
            </label>
            {control}
            {!compact && param.hint && <p className="gf-hint">{param.hint}</p>}
          </div>
        );
      })}
    </div>
  );
}
