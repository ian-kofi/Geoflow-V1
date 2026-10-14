import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Icon from './Icon.jsx';
import { API_URL } from '../config.js';

// Wait this long after the last key press before searching, in milliseconds. It also keeps us
// under Nominatim's limit of one request a second.
const SEARCH_DELAY = 450;
const MIN_CHARS = 2;

/**
 * The part of a place's full name after the name itself, so for
 * "Tema, Tema Metropolitan District, Greater Accra Region, Ghana" it's everything after "Tema, ".
 */
function placeContext(place) {
  const prefix = `${place.name}, `;
  return place.displayName.startsWith(prefix) ? place.displayName.slice(prefix.length) : place.displayName;
}

export { placeContext };

/**
 * A place search box that shows matching places as you type.
 *
 * The typed text is passed to onTextChange and the chosen place (with its OpenStreetMap id)
 * to onPick. Later nodes use that exact place, rather than the first match for a name that
 * several places share. The list of matches is drawn on top of everything else, so other
 * nodes can't cover it.
 */
export default function PlaceField({ id, value, place, placeholder, onTextChange, onPick, onEnter, autoFocus = false }) {
  const inputRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState([]);
  const [status, setStatus] = useState('idle'); // idle | loading | empty | error
  const [active, setActive] = useState(0);
  const [rect, setRect] = useState(null);
  const listId = `${id}-listbox`;

  // Search while the user is typing.
  useEffect(() => {
    const query = (value ?? '').trim();
    if (!open || query.length < MIN_CHARS) {
      setResults([]);
      setStatus('idle');
      return undefined;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setStatus('loading');
      try {
        const response = await fetch(`${API_URL}/geocode?q=${encodeURIComponent(query)}`, { signal: controller.signal });
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail);
        setResults(body.results);
        setActive(0);
        setStatus(body.results.length ? 'idle' : 'empty');
      } catch (err) {
        if (err.name !== 'AbortError') setStatus('error');
      }
    }, SEARCH_DELAY);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [value, open]);

  // The list is drawn outside the node so other nodes can't cover it, which means it has to
  // follow the search box by hand while the canvas is moved or zoomed.
  useEffect(() => {
    if (!open) return undefined;
    let frame;
    const track = () => {
      const r = inputRef.current?.getBoundingClientRect();
      if (r) {
        setRect((prev) =>
          prev && prev.left === r.left && prev.bottom === r.bottom && prev.width === r.width
            ? prev
            : { left: r.left, bottom: r.bottom, width: r.width },
        );
      }
      frame = requestAnimationFrame(track);
    };
    track();
    return () => cancelAnimationFrame(frame);
  }, [open]);

  const pick = (candidate) => {
    onPick(candidate);
    setOpen(false);
  };

  const onChange = (e) => {
    onTextChange(e.target.value); // the caller forgets any earlier pick, since the text no longer matches it
    setOpen(true);
  };

  const onKeyDown = (e) => {
    const showing = open && results.length > 0;
    if (e.key === 'ArrowDown' && showing) {
      e.preventDefault();
      setActive((i) => (i + 1) % results.length);
    } else if (e.key === 'ArrowUp' && showing) {
      e.preventDefault();
      setActive((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (showing) pick(results[active]);
      else onEnter?.();
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  const showMenu = open && rect && (value ?? '').trim().length >= MIN_CHARS && (status !== 'idle' || results.length > 0);

  return (
    <div className="gf-place">
      <input
        ref={inputRef}
        id={id}
        className="gf-input nodrag"
        type="text"
        role="combobox"
        aria-expanded={Boolean(showMenu)}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showMenu && results[active] ? `${listId}-${active}` : undefined}
        autoComplete="off"
        spellCheck={false}
        autoFocus={autoFocus}
        value={value ?? ''}
        placeholder={placeholder}
        onChange={onChange}
        onKeyDown={onKeyDown}
        onFocus={() => !place && setOpen(true)}
        onBlur={() => setOpen(false)}
      />

      {place ? (
        <div className="gf-place__picked" title={place.displayName}>
          <Icon name="pin" size={12} />
          <span>
            {placeContext(place) || place.name}
            <span className="gf-place__kind"> · {place.kind}</span>
          </span>
        </div>
      ) : (
        (value ?? '').trim() && (
          <p className="gf-place__warn">Pick a place from the list so the right one is used.</p>
        )
      )}

      {showMenu &&
        createPortal(
          <ul
            id={listId}
            role="listbox"
            className="gf-place-menu"
            style={{ left: rect.left, top: rect.bottom + 4, width: Math.max(rect.width, 300) }}
          >
            {status === 'loading' && results.length === 0 && <li className="gf-place-menu__status">Searching…</li>}
            {status === 'empty' && <li className="gf-place-menu__status">No places found</li>}
            {status === 'error' && <li className="gf-place-menu__status">Place search isn't working. Is the backend running?</li>}
            {results.map((candidate, i) => (
              <li
                key={candidate.id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                className={i === active ? 'is-active' : ''}
                onMouseEnter={() => setActive(i)}
                // Picking on mouse down (and cancelling the default) stops the search box losing
                // focus first, which would close the list before the click registers
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(candidate);
                }}
              >
                <div className="gf-place-menu__name">
                  {candidate.name}
                  <span className="gf-place-menu__kind">{candidate.kind}</span>
                </div>
                <div className="gf-place-menu__detail">{placeContext(candidate)}</div>
              </li>
            ))}
          </ul>,
          document.body,
        )}
    </div>
  );
}
