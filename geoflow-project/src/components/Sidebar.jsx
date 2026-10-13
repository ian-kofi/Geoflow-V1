import { useRef } from 'react';
import Icon from './Icon.jsx';
import { CATEGORIES, NODE_TYPES } from '../nodes/registry.js';
import { TEMPLATES } from '../workflow/templates.js';

export const DRAG_MIME = 'application/geoflow-node';

export default function Sidebar({ collapsed, onToggleCollapsed, onMakeMap, onAdd, onTemplate, onExport, onImport, onClear }) {
  const importRef = useRef(null);
  const groups = Object.entries(CATEGORIES).map(([key, cat]) => ({
    key,
    ...cat,
    types: Object.entries(NODE_TYPES).filter(([, def]) => def.category === key),
  }));

  return (
    <aside className="gf-sidebar">
      <div className="gf-brand">
        <span className="gf-brand__mark">
          <Icon name="globe" size={18} />
        </span>
        <div className="gf-brand__text">
          <div className="gf-brand__name">GeoFlow</div>
          <div className="gf-brand__tag">Geospatial workflows</div>
        </div>
        <button
          type="button"
          className="gf-icon-btn gf-sidebar__toggle"
          onClick={onToggleCollapsed}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
        >
          <Icon name={collapsed ? 'sidebarOpen' : 'sidebarClose'} size={15} />
        </button>
      </div>

      <button type="button" className="gf-btn gf-btn--primary gf-make-map" onClick={onMakeMap} title="Make a map in two steps, no GIS knowledge needed">
        <Icon name="map" size={15} />
        <span className="gf-make-map__text">Make a map</span>
      </button>

      <div className="gf-sidebar__scroll">
        {groups.map((group) => (
          <section key={group.key} className="gf-palette">
            <h3 className="gf-section-title">
              <span className="gf-dot" style={{ background: group.color }} />
              {group.label}
            </h3>
            {group.types.map(([type, def]) => (
              <button
                key={type}
                type="button"
                className="gf-palette__item"
                style={{ '--accent': group.color }}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData(DRAG_MIME, type);
                  e.dataTransfer.effectAllowed = 'move';
                }}
                onClick={() => onAdd(type)}
                title={`${def.label}: ${def.description}\n\nDrag onto the canvas or click to add.`}
                aria-label={`Add ${def.label} node`}
              >
                <span className="gf-palette__icon">
                  <Icon name={def.icon} size={15} />
                </span>
                <span className="gf-palette__text">
                  <span className="gf-palette__label">{def.label}</span>
                  <span className="gf-palette__desc">{def.description}</span>
                </span>
              </button>
            ))}
          </section>
        ))}

        <section className="gf-palette gf-palette--templates">
          <h3 className="gf-section-title">
            <Icon name="sparkles" size={12} />
            Templates
          </h3>
          {TEMPLATES.map((t) => (
            <button key={t.id} type="button" className="gf-template" onClick={() => onTemplate(t)}>
              <span className="gf-palette__label">{t.name}</span>
              <span className="gf-palette__desc">{t.description}</span>
            </button>
          ))}
        </section>
      </div>

      <div className="gf-sidebar__footer">
        <button type="button" className="gf-icon-btn" onClick={onExport} title="Export workflow as JSON">
          <Icon name="download" size={15} />
        </button>
        <button type="button" className="gf-icon-btn" onClick={() => importRef.current?.click()} title="Import workflow JSON">
          <Icon name="upload" size={15} />
        </button>
        <button type="button" className="gf-icon-btn gf-icon-btn--danger" onClick={onClear} title="Clear canvas">
          <Icon name="trash" size={15} />
        </button>
        <input
          ref={importRef}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onImport(file);
            e.target.value = '';
          }}
        />
      </div>
    </aside>
  );
}
