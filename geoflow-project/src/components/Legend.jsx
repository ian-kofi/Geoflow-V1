function formatValue(value) {
  if (value == null || Number.isNaN(value)) return '–';
  const abs = Math.abs(value);
  if (abs !== 0 && (abs < 0.01 || abs >= 100000)) return value.toExponential(1);
  return Number(value.toFixed(abs < 1 ? 2 : abs < 100 ? 1 : 0)).toLocaleString();
}

/** Colour key for a raster/vector result: gradient bar, class swatches or a true-colour note. */
export default function Legend({ legend, compact = false }) {
  if (!legend) return null;
  const unit = legend.unit ? ` ${legend.unit}` : '';

  if (legend.type === 'continuous') {
    return (
      <div className={`gf-legend ${compact ? 'gf-legend--compact' : ''}`}>
        {legend.label && !compact && <div className="gf-legend__title">{legend.label}</div>}
        <div className="gf-legend__bar" style={{ background: `linear-gradient(to right, ${legend.colors.join(', ')})` }} />
        <div className="gf-legend__scale">
          <span>
            {formatValue(legend.min)}
            {unit}
          </span>
          {compact && legend.label && <span className="gf-legend__mid">{legend.label}</span>}
          <span>
            {formatValue(legend.max)}
            {unit}
          </span>
        </div>
      </div>
    );
  }

  if (legend.type === 'categorical') {
    return (
      <ul className={`gf-legend gf-legend--classes ${compact ? 'gf-legend--compact' : ''}`}>
        {legend.classes.map((c) => (
          <li key={c.value}>
            <span className="gf-legend__swatch" style={{ background: c.color }} />
            <span className="gf-legend__label">{c.label}</span>
            {c.percent != null && <span className="gf-legend__pct">{c.percent}%</span>}
          </li>
        ))}
      </ul>
    );
  }

  return legend.label && !compact ? <div className="gf-legend gf-legend__title">{legend.label}</div> : null;
}

export { formatValue };
