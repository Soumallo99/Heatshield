/**
 * The globe's source catalogue and the wiring that turns it into source
 * records for the controller.
 *
 * Adapted from gods-eye-view `src/maps/catalog.js` + `src/maps/defaultSources.js`
 * (https://github.com/bilawalsidhu/gods-eye-view @ 0d41b6b, MIT — see
 * LICENSE-gods-eye-view).
 *
 * What was kept: the descriptor shape, the imagery/terrain factory split, and
 * the two-stage fallback contract (construction fallback + tile-failure
 * fallback) with its message travelling with the source.
 * What was dropped: the Google photoreal tileset and the Cesium-ion stacks.
 * Both require credentials; HeatShield's zero-key clone-and-run invariant is
 * more important than having a second imagery provider.
 *
 * The catalogue is therefore exactly two keyless stacks:
 *   esri-imagery (default) -> falls back to osm
 *   osm
 */
import {
  ESRI_ATTRIBUTION_HTML,
  OSM_ATTRIBUTION,
  createEsriImagery,
  createOsmImagery,
} from './imagery.js'
import { createKeylessTerrain } from './terrain.js'

/** Ordered list shown in the globe's source switcher. */
export const MAP_STACKS = [
  {
    id: 'esri-imagery',
    label: 'Satellite',
    hint: 'Esri World Imagery — keyless photorealistic imagery, no token',
    kind: 'esri-imagery',
  },
  {
    id: 'osm',
    label: 'OpenStreetMap',
    hint: 'OSM raster tiles — the keyless fallback on a different CDN',
    kind: 'osm',
  },
]

/** Build the source records consumed by GlobeSourceController. */
export function createGlobeSources({ onTerrainFallback } = {}) {
  const terrain = {
    id: 'keyless',
    create: (request) =>
      createKeylessTerrain({ ...request, onFallback: onTerrainFallback }),
  }
  return {
    defaultId: 'esri-imagery',
    unknownId: 'osm',
    recoveryId: 'osm',
    state: {},
    sources: MAP_STACKS.map((descriptor) => {
      const base = {
        descriptor,
        available: true,
        unavailableReason: null,
        terrain,
      }
      if (descriptor.id === 'esri-imagery') {
        return {
          ...base,
          imagery: createEsriImagery,
          credit: ESRI_ATTRIBUTION_HTML,
          // A construction failure (metadata fetch refused) and repeated tile
          // failures are different problems; both end at OSM, both say why.
          constructionFallback: {
            id: 'osm',
            message:
              'Esri World Imagery is unavailable — switched to OpenStreetMap tiles. ' +
              'Both are keyless; no API key is involved anywhere.',
          },
          tileFailureFallback: {
            id: 'osm',
            threshold: 2,
            message:
              'Esri World Imagery tiles keep failing — switched to OpenStreetMap tiles. ' +
              'Both are keyless; no API key is involved anywhere.',
          },
        }
      }
      return {
        ...base,
        imagery: createOsmImagery,
        credit: OSM_ATTRIBUTION,
      }
    }),
  }
}
