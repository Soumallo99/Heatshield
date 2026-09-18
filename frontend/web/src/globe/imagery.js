/**
 * Keyless imagery providers for the 3D globe.
 *
 * Adapted from gods-eye-view `src/maps/imagery.js`
 * (https://github.com/bilawalsidhu/gods-eye-view @ 0d41b6b, MIT — see
 * LICENSE-gods-eye-view). Adapted, not copied wholesale: the ion/Bing branches
 * are gone.
 *
 * HEATSHIELD RULE: both providers here are keyless. There is no token
 * parameter, no `accessToken`, no key slot — Cesium's ion route
 * (`IonImageryProvider`) is deliberately NOT vendored, so a globe cannot be
 * configured into an "API key required" state. When Esri fails, the controller
 * falls back to OpenStreetMap tiles and says so on the map.
 */
import * as Cesium from 'cesium'

export const ESRI_ATTRIBUTION_HTML =
  '<a href="https://www.esri.com" target="_blank" rel="noopener">Powered by Esri</a> — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'

export const OSM_ATTRIBUTION = '© OpenStreetMap contributors'

/** Keyless ArcGIS World Imagery (Maxar / Earthstar Geographics). */
const ESRI_WORLD_IMAGERY_URL =
  'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer'

/** Keyless OpenStreetMap raster tiles — the fallback CDN. */
const OSM_TILE_URL = 'https://tile.openstreetmap.org/'

export function createOsmImagery() {
  return new Cesium.OpenStreetMapImageryProvider({
    url: OSM_TILE_URL,
    credit: OSM_ATTRIBUTION,
  })
}

export function createEsriImagery() {
  return Cesium.ArcGisMapServerImageryProvider.fromUrl(ESRI_WORLD_IMAGERY_URL, {
    credit: ESRI_ATTRIBUTION_HTML,
    enablePickFeatures: false,
  })
}
