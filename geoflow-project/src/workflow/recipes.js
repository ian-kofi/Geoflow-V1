import { createNode } from '../nodes/registry.js';

/**
 * Ready-made analyses for the "Make a map" assistant: each builds a small,
 * normal workflow (so people can open it up and learn from it) for a picked place.
 */

function edge(source, target, targetHandle) {
  return {
    id: `e_${source.id}_${target.id}${targetHandle ? `_${targetHandle}` : ''}`,
    source: source.id,
    target: target.id,
    ...(targetHandle ? { targetHandle } : {}),
  };
}

const COL = 330;

/** Outline settings that suit the place: country borders, or the town's own outline. */
function outlineFor(place, detail = 0) {
  return place.isCountry ? { boundarySource: 'geoboundaries', boundaryAdminLevel: detail } : { boundarySource: 'city' };
}

/** Satellite detail level (map zoom) that gives a sharp picture of the place without taking forever. */
function zoomFor(place) {
  const [s, n, w, e] = place.bbox ?? [0, 1, 0, 1];
  const span = Math.max(n - s, e - w, 0.005);
  return Math.min(15, Math.max(5, Math.round(Math.log2(360 / span)) + 2));
}

/** Common start: Place → Outline. */
function start(place, detail = 0) {
  const location = createNode('LocationNode', { x: 0, y: 120 }, { location: place.name, place });
  const outline = createNode('BoundaryNode', { x: COL, y: 120 }, outlineFor(place, detail));
  return { location, outline };
}

function finish(nodes, edges, last, title) {
  const output = createNode('OutputImageNode', { x: last.position.x + COL, y: 60 }, { title });
  return { nodes: [...nodes, output], edges: [...edges, edge(last, output)], outputId: output.id };
}

function featuresOnPhoto(place, layerType, title) {
  const { location, outline } = start(place);
  const photo = createNode('SatelliteNode', { x: COL * 2, y: -60 }, { satelliteZoom: zoomFor(place), clipToBoundary: true });
  const features = createNode('LayerNode', { x: COL * 2, y: 280 }, { layerType });
  const combined = createNode('CompositeNode', { x: COL * 3, y: 80 }, { alpha: 0.85 });
  return finish(
    [location, outline, photo, features, combined],
    [edge(location, outline), edge(outline, photo), edge(outline, features), edge(outline, combined), edge(photo, combined), edge(features, combined)],
    combined,
    title,
  );
}

function elevation(place, location, outline) {
  const dem = createNode('StacNode', { x: COL * 2, y: 120 }, { collection: 'cop-dem-glo-30' });
  return { dem, edges: [edge(location, outline), edge(outline, dem)] };
}

export const RECIPES = [
  {
    id: 'photo',
    title: 'Satellite photo',
    description: 'A clear photo from above, framed to your place.',
    icon: 'satellite',
    time: 'about 10 seconds',
    build: (place) => {
      const { location, outline } = start(place);
      const photo = createNode('SatelliteNode', { x: COL * 2, y: 120 }, { satelliteZoom: zoomFor(place), clipToBoundary: true });
      return finish([location, outline, photo], [edge(location, outline), edge(outline, photo)], photo, `Satellite photo · ${place.name}`);
    },
  },
  {
    id: 'terrain',
    title: 'Hills & valleys',
    description: 'Ground height in colour with shaded hills, like a relief map.',
    icon: 'mountain',
    time: 'about 15 seconds',
    build: (place) => {
      const { location, outline } = start(place);
      const { dem, edges } = elevation(place, location, outline);
      const cut = createNode('ClipRasterNode', { x: COL * 3, y: 120 });
      const colours = createNode('ColourMapNode', { x: COL * 4, y: 120 }, { colormap: 'terrain', hillshade: true, stretch: 'minmax' });
      return finish(
        [location, outline, dem, cut, colours],
        [...edges, edge(dem, cut, 'raster'), edge(outline, cut, 'mask'), edge(cut, colours)],
        colours,
        `Hills & valleys · ${place.name}`,
      );
    },
  },
  {
    id: 'slopes',
    title: 'Steep slopes',
    description: 'Flat, gentle and steep ground, e.g. for landslide or building risk.',
    icon: 'activity',
    time: 'about 20 seconds',
    build: (place) => {
      const { location, outline } = start(place);
      const { dem, edges } = elevation(place, location, outline);
      const slope = createNode('SlopeNode', { x: COL * 3, y: 120 });
      const cut = createNode('ClipRasterNode', { x: COL * 4, y: 120 });
      const groups = createNode('ReclassifyNode', { x: COL * 5, y: 120 }, { breaks: '5, 15, 30', labels: 'Flat, Gentle, Steep, Very steep' });
      return finish(
        [location, outline, dem, slope, cut, groups],
        [...edges, edge(dem, slope), edge(slope, cut, 'raster'), edge(outline, cut, 'mask'), edge(cut, groups)],
        groups,
        `Steep slopes · ${place.name}`,
      );
    },
  },
  {
    id: 'flood',
    title: 'Flood risk',
    description: 'Low, Moderate and High flood susceptibility from terrain, rivers and past flooding.',
    icon: 'droplet',
    time: 'about 30 seconds for a town or district',
    build: (place) => {
      const { location, outline } = start(place);
      const { dem, edges } = elevation(place, location, outline);
      // HAND is computed on the full rectangle (fewer edge effects), then cut to the outline.
      const hand = createNode('HandNode', { x: COL * 3, y: -40 }, { minArea: 1 });
      const handCut = createNode('ClipRasterNode', { x: COL * 4, y: -40 });
      const slope = createNode('SlopeNode', { x: COL * 3, y: 300 });
      const water = createNode('StacNode', { x: COL * 2, y: 480 }, { collection: 'jrc-gsw' });
      const overlay = createNode('WeightedOverlayNode', { x: COL * 5, y: 120 }, {
        resultName: 'Flood susceptibility',
        weightA: 5, riskA: 'low', rangeA: '0, 15',    // 0 m above the river = full risk, 15 m+ = none
        weightB: 2, riskB: 'low', rangeB: '0, 8',     // flat ground holds water
        weightC: 3, riskC: 'high', rangeC: '0, 25',   // underwater in ≥25% of observations since 1984 = full
        weightD: 0,
      });
      const zones = createNode('ReclassifyNode', { x: COL * 6, y: 120 }, {
        method: 'manual', breaks: '0.4, 0.65', labels: 'Low, Moderate, High',
      });
      // Flood maps conventionally use blues: pale = low, dark = high.
      const colours = createNode('ColourMapNode', { x: COL * 7, y: 120 }, { colormap: 'YlGnBu' });
      return finish(
        [location, outline, dem, hand, handCut, slope, water, overlay, zones, colours],
        [
          ...edges,
          edge(dem, hand),
          edge(hand, handCut, 'raster'),
          edge(outline, handCut, 'mask'),
          edge(dem, slope),
          edge(outline, water),
          edge(handCut, overlay, 'A'),
          edge(slope, overlay, 'B'),
          edge(water, overlay, 'C'),
          edge(overlay, zones),
          edge(zones, colours),
        ],
        colours,
        `Flood susceptibility · ${place.name}`,
      );
    },
  },
  {
    id: 'green',
    title: 'How green it is',
    description: 'Plant health from recent satellite photos: green = lush, red = bare or built-up.',
    icon: 'leaf',
    time: '1–3 minutes for a town or district, around 5 minutes for a whole country',
    build: (place) => {
      const { location, outline } = start(place);
      const photos = createNode('StacNode', { x: COL * 2, y: 120 }, { collection: 'sentinel-2-l2a' });
      const green = createNode('SpectralIndexNode', { x: COL * 3, y: 120 }, { index: 'ndvi' });
      const cut = createNode('ClipRasterNode', { x: COL * 4, y: 120 });
      return finish(
        [location, outline, photos, green, cut],
        [edge(location, outline), edge(outline, photos), edge(photos, green), edge(green, cut, 'raster'), edge(outline, cut, 'mask')],
        cut,
        `How green is ${place.name}?`,
      );
    },
  },
  {
    id: 'roads',
    title: 'Roads',
    description: 'Roads drawn over a satellite photo.',
    icon: 'layers',
    time: '1–3 minutes',
    build: (place) => featuresOnPhoto(place, place.isCountry ? 'highways' : 'roads', `Roads · ${place.name}`),
  },
  {
    id: 'rivers',
    title: 'Rivers & streams',
    description: 'Rivers and streams drawn over a satellite photo.',
    icon: 'waves',
    time: '1–3 minutes',
    build: (place) => featuresOnPhoto(place, 'waterways', `Rivers & streams · ${place.name}`),
  },
  {
    id: 'contours',
    title: 'Contour lines',
    description: 'Lines of equal height, like a hiking map.',
    icon: 'hillshade',
    time: 'about 20 seconds',
    build: (place) => {
      const { location, outline } = start(place);
      const { dem, edges } = elevation(place, location, outline);
      const lines = createNode('ContourNode', { x: COL * 3, y: 120 }, { interval: place.isCountry ? 100 : 10 });
      const inside = createNode('SpatialFilterNode', { x: COL * 4, y: 120 }, { mode: 'clip' });
      return finish(
        [location, outline, dem, lines, inside],
        [...edges, edge(dem, lines), edge(lines, inside, 'data'), edge(outline, inside, 'mask')],
        inside,
        `Contour lines · ${place.name}`,
      );
    },
  },
  {
    id: 'borders',
    title: 'Regions & borders',
    description: 'The outline of your place, divided into its regions (for countries).',
    icon: 'boundary',
    time: 'about 5 seconds',
    build: (place) => {
      const { location, outline } = start(place, place.isCountry ? 1 : 0);
      return finish([location, outline], [edge(location, outline)], outline, `${place.isCountry ? 'Regions of' : 'Outline of'} ${place.name}`);
    },
  },
];
