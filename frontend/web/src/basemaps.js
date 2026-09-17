/**
 * Basemap registry.
 *
 * DESIGN RULE (same as the rest of HeatShield): the project must clone-and-run
 * with zero signups. Every basemap below therefore works with NO API KEY.
 *
 * ---------------------------------------------------------------------------
 * HISTORY — why CARTO is no longer the default
 * ---------------------------------------------------------------------------
 * This file originally used CARTO (dark_all / voyager). Around 28 Aug 2026
 * CARTO began requiring an API key for basemaps.cartocdn.com: keyless requests
 * still return HTTP 200 image/png, but the tile has a diagonal
 * "API KEY REQUIRED — carto.com/basemaps/apikey" watermark burned into it.
 * Nothing errors, no console warning, no failed request — the map just gets
 * defaced. (Same week it broke Home Assistant, Grafana Geomap, openHAB, etc.)
 *
 * So the defaults moved to providers that are genuinely keyless today:
 *   - Esri ArcGIS Online raster services (Dark Gray Canvas, World Street Map,
 *     World Imagery) — no key, no signup.
 *   - OpenStreetMap standard raster — no key, no signup.
 *   - OpenTopoMap — no key, no signup.
 *
 * CARTO is still available as an *opt-in* style: set VITE_CARTO_KEY and it
 * comes back, unwatermarked. Free key, no account, 5M tiles/month:
 * https://carto.com/basemaps/apikey
 *
 * ---------------------------------------------------------------------------
 * On "just use Google Maps"
 * ---------------------------------------------------------------------------
 * Pulling mt{n}.google.com/vt tiles violates the Google Maps ToS. The licensed
 * route is the Maps JavaScript API / Map Tiles API, which needs a
 * billing-enabled key. The Esri imagery below is the same Maxar source Google
 * licenses for its satellite layer, so the fidelity is comparable.
 *
 * ---------------------------------------------------------------------------
 * LESSON (please keep this in mind before adding a provider)
 * ---------------------------------------------------------------------------
 * A tile provider being keyless is a *current fact*, not a permanent property.
 * Verify a real tile renders clean before trusting it, and keep `attribution`
 * accurate per layer — several of these require visible credit as a condition
 * of the free tier.
 */

const CARTO_KEY = import.meta.env?.VITE_CARTO_KEY || ''
const MAPTILER_KEY = import.meta.env?.VITE_MAPTILER_KEY || ''
const THUNDERFOREST_KEY = import.meta.env?.VITE_THUNDERFOREST_KEY || ''

const OSM_ATTR = '© OpenStreetMap contributors'
const ESRI_BASE = 'https://server.arcgisonline.com/ArcGIS/rest/services'
// Esri's free tier is for non-revenue use with attribution kept visible.
const ESRI_ATTR = 'Tiles © Esri'
const ESRI_IMAGERY_ATTR = 'Imagery © Esri, Maxar, Earthstar Geographics'

/** Retina placeholder — only CARTO/MapTiler honour {r}; Esri and OSM ignore it. */
const R = '{r}'

/* ------------------------------------------------------------ keyless set */

const keyless = {
  dark: {
    id: 'dark',
    label: 'Dark',
    hint: 'Esri Dark Gray Canvas — muted, tuned for the risk choropleth',
    url: `${ESRI_BASE}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    maxZoom: 19,
    // Dark Gray Canvas is only rendered to z16; Leaflet upscales past that
    // rather than showing blank tiles.
    maxNativeZoom: 16,
    attribution: `${ESRI_ATTR} · ${OSM_ATTR}`,
    labels: {
      url: `${ESRI_BASE}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
      maxZoom: 19,
      maxNativeZoom: 16,
    },
    overlayOpacity: 0.34,
  },
  streets: {
    id: 'streets',
    label: 'Streets',
    hint: 'OpenStreetMap standard — the most detailed street map of Kolkata',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    maxZoom: 19,
    maxNativeZoom: 19,
    attribution: OSM_ATTR,
    light: true,
    overlayOpacity: 0.42,
  },
  satellite: {
    id: 'satellite',
    label: 'Satellite',
    hint: 'Esri World Imagery + street labels on top (the "hybrid" view)',
    url: `${ESRI_BASE}/World_Imagery/MapServer/tile/{z}/{y}/{x}`,
    maxZoom: 19,
    maxNativeZoom: 19,
    attribution: ESRI_IMAGERY_ATTR,
    labels: {
      url: `${ESRI_BASE}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`,
      maxZoom: 19,
      maxNativeZoom: 19,
    },
    overlayOpacity: 0.4,
  },
  terrain: {
    id: 'terrain',
    label: 'Terrain',
    hint: 'OpenTopoMap — relief + contours',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    subdomains: 'abc',
    maxZoom: 19,
    maxNativeZoom: 17,
    attribution: `${OSM_ATTR} · SRTM · © OpenTopoMap (CC-BY-SA)`,
    light: true,
    overlayOpacity: 0.45,
  },
}

/* ------------------------------------------------- optional keyed upgrades */

const keyed = {}

if (CARTO_KEY) {
  // Unwatermarked CARTO. The param is `key`, NOT `api_key` — CARTO silently
  // ignores the wrong name and you get the watermark back with no error.
  keyed.dark = {
    ...keyless.dark,
    hint: 'CARTO Dark Matter (API key detected)',
    url: `https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}${R}.png?key=${CARTO_KEY}`,
    subdomains: 'abcd',
    maxZoom: 20,
    maxNativeZoom: 20,
    labels: undefined,
    attribution: `${OSM_ATTR} · © CARTO`,
  }
  keyed.streets = {
    ...keyless.streets,
    hint: 'CARTO Voyager (API key detected)',
    url: `https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}${R}.png?key=${CARTO_KEY}`,
    subdomains: 'abcd',
    maxZoom: 20,
    maxNativeZoom: 20,
    attribution: `${OSM_ATTR} · © CARTO`,
  }
}

if (MAPTILER_KEY) {
  keyed.streets = {
    id: 'streets',
    label: 'Streets',
    hint: 'MapTiler Streets (API key detected)',
    url: `https://api.maptiler.com/maps/streets-v2/{z}/{x}/{y}${R}.png?key=${MAPTILER_KEY}`,
    maxZoom: 22,
    maxNativeZoom: 22,
    attribution: `© MapTiler · ${OSM_ATTR}`,
    light: true,
    overlayOpacity: 0.42,
  }
  keyed.satellite = {
    id: 'satellite',
    label: 'Satellite',
    hint: 'MapTiler Satellite + hybrid labels (API key detected)',
    url: `https://api.maptiler.com/tiles/satellite-v2/{z}/{x}/{y}.jpg?key=${MAPTILER_KEY}`,
    maxZoom: 22,
    maxNativeZoom: 20,
    attribution: `© MapTiler · ${OSM_ATTR}`,
    labels: {
      url: `https://api.maptiler.com/maps/hybrid/{z}/{x}/{y}${R}.png?key=${MAPTILER_KEY}`,
      maxZoom: 22,
    },
    overlayOpacity: 0.4,
  }
}

if (THUNDERFOREST_KEY) {
  keyed.atlas = {
    id: 'atlas',
    label: 'Atlas',
    hint: 'Thunderforest Atlas (API key detected)',
    url: `https://{s}.tile.thunderforest.com/atlas/{z}/{x}/{y}${R}.png?apikey=${THUNDERFOREST_KEY}`,
    subdomains: 'abc',
    maxZoom: 22,
    maxNativeZoom: 22,
    attribution: `${OSM_ATTR} · © Thunderforest`,
    light: true,
    overlayOpacity: 0.42,
  }
}

/** Ordered list shown in the map's layer switcher. */
export const BASEMAPS = ['dark', 'streets', 'satellite', 'terrain', 'atlas']
  .map((id) => keyed[id] || keyless[id])
  .filter(Boolean)

export const DEFAULT_BASEMAP = 'dark'

export const getBasemap = (id) => BASEMAPS.find((b) => b.id === id) || BASEMAPS[0]

/** True when a commercial key was supplied — surfaced in the UI so a reviewer
 *  can tell at a glance which tiles they're looking at. */
export const USING_KEYED_TILES = Boolean(CARTO_KEY || MAPTILER_KEY || THUNDERFOREST_KEY)

/** Hosts the service worker should cache tiles from. Kept here so the list has
 *  exactly one definition; sw.js can't import an ES module, so it mirrors this
 *  and tests/test_tile_hosts guards the two against drifting apart. */
export const TILE_HOSTS = [
  'server.arcgisonline.com',
  'tile.openstreetmap.org',
  'tile.opentopomap.org',
  'basemaps.cartocdn.com',
  'api.maptiler.com',
  'tile.thunderforest.com',
]
