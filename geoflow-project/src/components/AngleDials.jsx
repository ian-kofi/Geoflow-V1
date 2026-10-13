import { useRef } from 'react';

const DIRECTIONS = [
  'north', 'north-northeast', 'northeast', 'east-northeast', 'east', 'east-southeast', 'southeast', 'south-southeast',
  'south', 'south-southwest', 'southwest', 'west-southwest', 'west', 'west-northwest', 'northwest', 'north-northwest',
];

export function compassDirection(degrees) {
  return DIRECTIONS[Math.round((((degrees % 360) + 360) % 360) / 22.5) % 16];
}

function altitudeEffect(altitude) {
  if (altitude < 25) return 'Low sun: long shadows, strong relief';
  if (altitude < 55) return 'Mid-height sun: balanced relief';
  return 'High sun: short shadows, subtle relief';
}

const rad = (deg) => (deg * Math.PI) / 180;

/** Pointer position in SVG viewBox units. */
function svgPoint(svg, event, viewWidth, viewHeight) {
  const rect = svg.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * viewWidth,
    y: ((event.clientY - rect.top) / rect.height) * viewHeight,
  };
}

/** Shared pointer + keyboard handling: drag anywhere on the dial to set the angle. */
function useDial({ value, min, max, step, onChange, angleFromPoint, viewWidth, viewHeight, wrap }) {
  const svgRef = useRef(null);
  const snap = (v) => {
    let next = Math.round(v / step) * step;
    if (wrap) next = ((next % 360) + 360) % 360;
    return Math.min(max, Math.max(min, next));
  };
  const update = (event) => {
    const angle = angleFromPoint(svgPoint(svgRef.current, event, viewWidth, viewHeight));
    const next = snap(angle);
    if (next !== value) onChange(next);
  };
  return {
    svgRef,
    handlers: {
      onPointerDown: (e) => {
        e.stopPropagation(); // don't start dragging the node
        e.currentTarget.setPointerCapture(e.pointerId);
        update(e);
      },
      onPointerMove: (e) => {
        if (e.currentTarget.hasPointerCapture(e.pointerId)) update(e);
      },
      onKeyDown: (e) => {
        const big = step * 3;
        const delta = { ArrowUp: step, ArrowRight: step, ArrowDown: -step, ArrowLeft: -step, PageUp: big, PageDown: -big }[e.key];
        if (delta == null) return;
        e.preventDefault();
        onChange(snap(Number(value) + delta));
      },
    },
  };
}

/** Compass dial for the sun's azimuth (0° = north, clockwise). */
export function CompassDial({ id, value = 315, min = 0, max = 360, step = 5, onChange }) {
  const size = 120;
  const c = size / 2;
  const ring = 42;
  const angle = Number(value) % 360;
  const { svgRef, handlers } = useDial({
    value: angle,
    min,
    max: 355,
    step,
    onChange,
    wrap: true,
    viewWidth: size,
    viewHeight: size,
    angleFromPoint: ({ x, y }) => (Math.atan2(x - c, -(y - c)) * 180) / Math.PI,
  });
  const sun = { x: c + ring * Math.sin(rad(angle)), y: c - ring * Math.cos(rad(angle)) };
  const shadow = { x: c - 26 * Math.sin(rad(angle)), y: c + 26 * Math.cos(rad(angle)) };
  const from = compassDirection(angle);
  const to = compassDirection(angle + 180);

  return (
    <div className="gf-dial">
      <svg
        ref={svgRef}
        id={id}
        className="gf-dial__svg gf-dial__svg--compass nodrag nowheel"
        viewBox={`0 0 ${size} ${size}`}
        role="slider"
        tabIndex={0}
        aria-valuemin={0}
        aria-valuemax={359}
        aria-valuenow={angle}
        aria-valuetext={`${angle} degrees, sun in the ${from}`}
        {...handlers}
      >
        <circle className="gf-dial__face" cx={c} cy={c} r={ring} />
        {Array.from({ length: 24 }, (_, i) => {
          const a = rad(i * 15);
          const inner = i % 6 === 0 ? ring - 7 : ring - 3.5;
          return (
            <line
              key={i}
              className="gf-dial__tick"
              x1={c + inner * Math.sin(a)}
              y1={c - inner * Math.cos(a)}
              x2={c + ring * Math.sin(a)}
              y2={c - ring * Math.cos(a)}
            />
          );
        })}
        {[['N', 0], ['E', 90], ['S', 180], ['W', 270]].map(([letter, deg]) => (
          <text
            key={letter}
            className={`gf-dial__letter ${letter === 'N' ? 'is-north' : ''}`}
            x={c + (ring - 15) * Math.sin(rad(deg))}
            y={c - (ring - 15) * Math.cos(rad(deg))}
          >
            {letter}
          </text>
        ))}
        {/* light falls from the sun across the terrain; the shadow points the other way */}
        <line className="gf-dial__shadow" x1={c} y1={c} x2={shadow.x} y2={shadow.y} />
        <line className="gf-dial__ray" x1={sun.x} y1={sun.y} x2={c} y2={c} />
        <path className="gf-dial__hill" d={`M${c - 7} ${c + 4} L${c} ${c - 5} L${c + 7} ${c + 4} Z`} />
        <circle className="gf-dial__sun-glow" cx={sun.x} cy={sun.y} r={11} />
        <circle className="gf-dial__sun" cx={sun.x} cy={sun.y} r={7} />
      </svg>
      <div className="gf-dial__caption">
        <strong>Sun in the {from}</strong>
        <span>
          Shadows fall to the {to} · <span className="gf-mono">{angle}°</span>
        </span>
      </div>
    </div>
  );
}

/** Quarter-circle dial for the sun's height above the horizon (0° horizon → 90° overhead). */
export function ElevationDial({ id, value = 45, min = 1, max = 90, step = 1, onChange }) {
  const width = 120;
  const height = 92;
  const origin = { x: 16, y: 80 };
  const radius = 64;
  const angle = Number(value);
  const { svgRef, handlers } = useDial({
    value: angle,
    min,
    max,
    step,
    onChange,
    viewWidth: width,
    viewHeight: height,
    angleFromPoint: ({ x, y }) => (Math.atan2(origin.y - y, Math.max(x - origin.x, 0.0001)) * 180) / Math.PI,
  });
  const point = (deg, r = radius) => ({ x: origin.x + r * Math.cos(rad(deg)), y: origin.y - r * Math.sin(rad(deg)) });
  const sun = point(angle);
  const arcEnd = point(90);
  // Filled wedge between the horizon and the sun shows the selected angle.
  const wedgeR = 22;
  const wedgeEnd = point(angle, wedgeR);

  return (
    <div className="gf-dial">
      <svg
        ref={svgRef}
        id={id}
        className="gf-dial__svg gf-dial__svg--elevation nodrag nowheel"
        viewBox={`0 0 ${width} ${height}`}
        role="slider"
        tabIndex={0}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={angle}
        aria-valuetext={`${angle} degrees above the horizon`}
        {...handlers}
      >
        <path
          className="gf-dial__face"
          d={`M${origin.x} ${origin.y} L${origin.x + radius} ${origin.y} A${radius} ${radius} 0 0 0 ${arcEnd.x} ${arcEnd.y} Z`}
        />
        {[0, 15, 30, 45, 60, 75, 90].map((deg) => {
          const a = point(deg, radius - (deg % 45 === 0 ? 7 : 4));
          const b = point(deg);
          return <line key={deg} className="gf-dial__tick" x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
        })}
        {[[0, 'Horizon'], [90, 'Overhead']].map(([deg, text]) => {
          const p = point(deg, radius + 4);
          return (
            <text key={deg} className={`gf-dial__small gf-dial__small--${deg}`} x={p.x} y={p.y}>
              {text}
            </text>
          );
        })}
        <path
          className="gf-dial__wedge"
          d={`M${origin.x} ${origin.y} L${origin.x + wedgeR} ${origin.y} A${wedgeR} ${wedgeR} 0 0 0 ${wedgeEnd.x} ${wedgeEnd.y} Z`}
        />
        <line className="gf-dial__ground" x1={2} y1={origin.y} x2={width - 2} y2={origin.y} />
        <line className="gf-dial__ray" x1={sun.x} y1={sun.y} x2={origin.x} y2={origin.y} />
        <path className="gf-dial__hill" d={`M${origin.x - 9} ${origin.y} L${origin.x} ${origin.y - 9} L${origin.x + 9} ${origin.y} Z`} />
        <circle className="gf-dial__sun-glow" cx={sun.x} cy={sun.y} r={11} />
        <circle className="gf-dial__sun" cx={sun.x} cy={sun.y} r={7} />
      </svg>
      <div className="gf-dial__caption">
        <strong>
          <span className="gf-mono">{angle}°</span> above the horizon
        </strong>
        <span>{altitudeEffect(angle)}</span>
      </div>
    </div>
  );
}
