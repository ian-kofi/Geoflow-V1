import { useEffect, useRef, useState } from 'react';
import Icon from './Icon.jsx';
import { COLORMAP_GROUPS, COLORMAPS } from '../colormaps.js';

const gradient = (stops, reverse) => `linear-gradient(to right, ${(reverse ? [...stops].reverse() : stops).join(', ')})`;

/** Dropdown of colour maps, each shown as its real gradient. */
export default function ColormapPicker({ id, value, reverse = false, onChange }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const current = COLORMAPS[value] ? value : 'viridis';

  // Close when clicking elsewhere or pressing Escape.
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (e) => !rootRef.current?.contains(e.target) && setOpen(false);
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="gf-cmap" ref={rootRef}>
      <button
        id={id}
        type="button"
        className="gf-cmap__current nodrag"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="gf-cmap__bar" style={{ background: gradient(COLORMAPS[current], reverse) }} />
        <span className="gf-cmap__name">{current}</span>
        <Icon name="chevron" size={12} />
      </button>
      {open && (
        <div className="gf-cmap__list nodrag nowheel" role="listbox" aria-label="Colour maps">
          {COLORMAP_GROUPS.map((group) => (
            <div key={group.label} role="group" aria-label={group.label}>
              <div className="gf-cmap__group">{group.label}</div>
              {group.maps.map((map) => (
                <button
                  key={map.id}
                  type="button"
                  role="option"
                  aria-selected={map.id === current}
                  className={`gf-cmap__option ${map.id === current ? 'is-active' : ''}`}
                  onClick={() => {
                    onChange(map.id);
                    setOpen(false);
                  }}
                >
                  <span className="gf-cmap__bar" style={{ background: gradient(map.stops, reverse) }} />
                  <span className="gf-cmap__name">{map.id}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
