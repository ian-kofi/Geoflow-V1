import { useEffect, useState } from 'react';
import Icon from './Icon.jsx';
import PlaceField, { placeContext } from './PlaceField.jsx';
import { RECIPES } from '../workflow/recipes.js';

/**
 * "Make a map" assistant: pick a place and what to see; GeoFlow builds and
 * runs the workflow. No GIS knowledge needed.
 */
export default function QuickMapDialog({ onClose, onCreate }) {
  const [text, setText] = useState('');
  const [place, setPlace] = useState(null);
  const [recipeId, setRecipeId] = useState('photo');
  const recipe = RECIPES.find((r) => r.id === recipeId);
  const ready = Boolean(place && recipe);

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const create = () => ready && onCreate(recipe, place);

  return (
    <div className="gf-dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="gf-dialog" role="dialog" aria-modal="true" aria-labelledby="quickmap-title">
        <header className="gf-dialog__head">
          <div>
            <h2 id="quickmap-title">Make a map</h2>
            <p>Choose a place and what you want to see. GeoFlow does the rest.</p>
          </div>
          <button type="button" className="gf-icon-btn" onClick={onClose} aria-label="Close">
            <Icon name="x" size={16} />
          </button>
        </header>

        <section className="gf-dialog__step">
          <h3>
            <span className="gf-dialog__num">1</span> Where?
          </h3>
          <PlaceField
            id="quickmap-place"
            value={text}
            place={place}
            autoFocus
            placeholder="Type a country, region, city or town, e.g. Akosombo"
            onTextChange={(value) => {
              setText(value);
              setPlace(null);
            }}
            onPick={(candidate) => {
              setText(candidate.name);
              setPlace(candidate);
            }}
            onEnter={create}
          />
          {place && (
            <p className="gf-dialog__picked">
              {place.isCountry ? 'The whole country' : `${place.name}, ${placeContext(place)}`}
            </p>
          )}
        </section>

        <section className="gf-dialog__step">
          <h3>
            <span className="gf-dialog__num">2</span> What do you want to see?
          </h3>
          <div className="gf-recipes" role="radiogroup" aria-label="What to show">
            {RECIPES.map((r) => (
              <button
                key={r.id}
                type="button"
                role="radio"
                aria-checked={r.id === recipeId}
                className={`gf-recipe ${r.id === recipeId ? 'is-active' : ''}`}
                onClick={() => setRecipeId(r.id)}
                onDoubleClick={() => place && onCreate(r, place)}
              >
                <Icon name={r.icon} size={18} />
                <span className="gf-recipe__title">{r.title}</span>
                <span className="gf-recipe__desc">{r.description}</span>
              </button>
            ))}
          </div>
        </section>

        <footer className="gf-dialog__foot">
          <span className="gf-hint">
            {!place
              ? text.trim()
                ? 'Pick your place from the list that appears.'
                : 'Start by typing a place name.'
              : `Takes ${recipe.time}. You can download the result as a JPEG.`}
          </span>
          <button type="button" className="gf-btn gf-btn--primary" disabled={!ready} onClick={create}>
            <Icon name="play" size={11} /> Make my map
          </button>
        </footer>
      </div>
    </div>
  );
}
