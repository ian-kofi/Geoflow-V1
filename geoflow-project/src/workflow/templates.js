/**
 * Example workflows listed under Templates in the sidebar. Each `build` returns a set of nodes
 * and connections that replace whatever is on the canvas. The place can be changed afterwards
 * in the Place node.
 *
 * These are for people who want to see a full workflow. The Make a map assistant uses
 * recipes.js instead.
 */
import { createNode } from '../nodes/registry.js';

/** A connection between two nodes, optionally into a named input such as "mask". */
function edge(source, target, targetHandle) {
  return {
    id: `e_${source.id}_${target.id}${targetHandle ? `_${targetHandle}` : ''}`,
    source: source.id,
    target: target.id,
    ...(targetHandle ? { targetHandle } : {}),
  };
}

export const TEMPLATES = [
  {
    id: 'slope-risk',
    name: 'Slope stability',
    description: 'Ground height turned into steepness, grouped into Low, Medium and High risk, with shaded relief and contours.',
    build: (place = 'Akosombo') => {
      const location = createNode('LocationNode', { x: 0, y: 160 }, { location: place });
      const boundary = createNode('BoundaryNode', { x: 320, y: 140 }, { boundarySource: 'city' });
      const dem = createNode('StacNode', { x: 640, y: 120 }, { collection: 'cop-dem-glo-30' });
      const slope = createNode('SlopeNode', { x: 960, y: -60 });
      const classes = createNode('ReclassifyNode', { x: 1280, y: -60 }, { breaks: '10, 25', labels: 'Low, Medium, High' });
      const hillshade = createNode('HillshadeNode', { x: 960, y: 300 });
      const contours = createNode('ContourNode', { x: 1280, y: 360 }, { interval: 25 });
      const colours = createNode('ColourMapNode', { x: 960, y: 620 }, { colormap: 'terrain', hillshade: true });
      const output = createNode('OutputImageNode', { x: 1600, y: -40 });
      return {
        nodes: [location, boundary, dem, slope, classes, hillshade, contours, colours, output],
        edges: [
          edge(location, boundary),
          edge(boundary, dem),
          edge(dem, colours),
          edge(dem, slope),
          edge(slope, classes),
          edge(dem, hillshade),
          edge(dem, contours),
          edge(classes, output),
        ],
      };
    },
  },
  {
    id: 'vegetation',
    name: 'Vegetation (NDVI)',
    description: 'Plant health (NDVI) from Sentinel-2, cut to the outline, with an average for each district.',
    build: (place = 'Accra') => {
      const location = createNode('LocationNode', { x: 0, y: 160 }, { location: place });
      const boundary = createNode('BoundaryNode', { x: 320, y: 140 }, { boundarySource: 'city' });
      const s2 = createNode('StacNode', { x: 640, y: 0 }, { collection: 'sentinel-2-l2a' });
      const ndvi = createNode('SpectralIndexNode', { x: 960, y: 0 });
      const clip = createNode('ClipRasterNode', { x: 1280, y: 0 });
      const zonal = createNode('ZonalStatsNode', { x: 1280, y: 340 });
      const output = createNode('OutputImageNode', { x: 1600, y: 0 });
      return {
        nodes: [location, boundary, s2, ndvi, clip, zonal, output],
        edges: [
          edge(location, boundary),
          edge(boundary, s2),
          edge(s2, ndvi),
          edge(ndvi, clip, 'raster'),
          edge(boundary, clip, 'mask'),
          edge(ndvi, zonal, 'raster'),
          edge(boundary, zonal, 'zones'),
          edge(clip, output),
        ],
      };
    },
  },
  {
    id: 'composite',
    name: 'Satellite composite',
    description: 'An outline, a satellite photo and main roads combined into one map.',
    build: (place = 'Ghana') => {
      const location = createNode('LocationNode', { x: 0, y: 200 }, { location: place });
      const boundary = createNode('BoundaryNode', { x: 340, y: 40 }, { boundaryAdminLevel: 1 });
      const satellite = createNode('SatelliteNode', { x: 700, y: -120 }, { satelliteZoom: 8 });
      const layer = createNode('LayerNode', { x: 700, y: 260 }, { layerType: 'highways' });
      const composite = createNode('CompositeNode', { x: 1060, y: 60 });
      const output = createNode('OutputImageNode', { x: 1400, y: 60 });
      return {
        nodes: [location, boundary, satellite, layer, composite, output],
        edges: [
          edge(location, boundary),
          edge(boundary, satellite),
          edge(boundary, layer),
          edge(boundary, composite),
          edge(satellite, composite),
          edge(layer, composite),
          edge(composite, output),
        ],
      };
    },
  },
  {
    id: 'vector',
    name: 'Country to PNG',
    description: 'Draw a country as an SVG and turn it into a high resolution picture.',
    build: (place = 'Ghana') => {
      const location = createNode('LocationNode', { x: 0, y: 80 }, { location: place });
      const shape = createNode('GeoFileNode', { x: 340, y: 40 });
      const raster = createNode('RasterizerNode', { x: 700, y: 60 });
      const output = createNode('OutputImageNode', { x: 1040, y: 60 });
      return {
        nodes: [location, shape, raster, output],
        edges: [edge(location, shape), edge(shape, raster), edge(raster, output)],
      };
    },
  },
  {
    id: 'city',
    name: 'City streets',
    description: 'A city outline with its roads and rivers over a satellite photo.',
    build: (place = 'Accra') => {
      const location = createNode('LocationNode', { x: 0, y: 160 }, { location: place });
      const boundary = createNode('BoundaryNode', { x: 340, y: 120 }, { boundarySource: 'city' });
      const satellite = createNode('SatelliteNode', { x: 700, y: -140 }, { satelliteZoom: 12 });
      const roads = createNode('LayerNode', { x: 700, y: 170 }, { layerType: 'roads' });
      const water = createNode('LayerNode', { x: 700, y: 400 }, { layerType: 'waterways' });
      const composite = createNode('CompositeNode', { x: 1060, y: 120 }, { alpha: 0.75 });
      const output = createNode('OutputImageNode', { x: 1400, y: 120 });
      return {
        nodes: [location, boundary, satellite, roads, water, composite, output],
        edges: [
          edge(location, boundary),
          edge(boundary, satellite),
          edge(boundary, roads),
          edge(boundary, water),
          edge(boundary, composite),
          edge(satellite, composite),
          edge(roads, composite),
          edge(water, composite),
          edge(composite, output),
        ],
      };
    },
  },
];
