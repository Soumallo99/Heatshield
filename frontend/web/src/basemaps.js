/**
 * Basemap registry — "Google-Maps-grade" tiles without a mandatory API key.
 *
 * DESIGN RULE (same as the rest of HeatShield): the project must clone-and-run
 * with zero signups. So every basemap below works keyless out of the box.
 * If you *do* have a key, drop it in `.env` and the registry silently upgrades
 * to the higher-detail commercial tiles:
 *
 *   VITE_MAPTILER_KEY=...   -> MapTiler Streets / Satellite / Hybrid labels
 *                              (vector-derived raster, the closest keyless-ish
 *                               match to Google's cartography + POIs)
 *   VITE_THUNDERFOREST_KEY= -> Thunderforest Atlas (optional extra street style)
 *
 * We deliberately do NOT scrape `mt{n}.google.com/vt` tiles: it violates the
 * Google Maps ToS and would get a demo disqualified. Google's licensed route is
 * the Maps JavaScript API / Map Tiles API, which needs a billing-enabled key —
 * if you have one, see README "Using Google tiles" for the drop-in swap.
 *
 * Every entry is a plain object consumed by <TileLayer/>, plus an optional
 * `labels` overlay URL (drawn on top of imagery so street names stay readable).
 */

const MAPTILER_KEY = import.meta.env?.VITE_MAPTILER_KEY || ''
const THUNDERFOREST_KEY = import.meta.env?.VITE_THUNDERFOREST_KEY || ''

const OSM_ATTR = '© OpenStreetMap contributors'
const CARTO_ATTR = `${OSM_ATTR} · © CARTO`
const ESRI_ATTR = 'Imagery © Esri, Maxar, Earthstar Geographics'
const MAPTILER_ATTR = `© MapTiler · ${OSM_ATTR}`

/** Retina (@2x) tiles where the provider supports them — this is most of what
 *  makes a Leaflet map look "as sharp as Google Maps" on a modern display. */
const R = '{r}'

const keyless = {
  dark: {
    id: 'dark',
    label: 'Dark',
    hint: 'CARTO Dark Matter — the default, tuned for the risk choropleth',
    url: `https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}${R}.png`,
    subdomains: 'abcd',
    maxZoom: 20,
    maxNativeZoom: 20,
    attribution: CARTO_ATTR,
    overlayOpacity: 0.34,
  },
  streets: {
    id: 'streets',
    label: 'Streets',
    hint: 'CARTO Voyager — full street names, POIs, transit',
    url: `https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}${R}.png`,
    subdomains: 'abcd',
    maxZoom: 20,
    maxNativeZoom: 20,
    attribution: CARTO_ATTR,
    light: true,
    overlayOpacity: 0.42,
  },
  satellite: {
    id: 'satellite',
    label: 'Satellite',
    hint: 'Esri World Imagery + street labels on top (Google "Hybrid" look)',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    maxZoom: 20,
    maxNativeZoom: 19,
    attribution: ESRI_ATTR,
    labels: {
      url: `https://{s}.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}${R}.png`,
      subdomains: 'abcd',
      maxZoom: 20,
    },
    overlayOpacity: 0.4,
  },
  terrain: {
    id: 'terrain',
    label: 'Terrain',
    hint: 'OpenTopoMap — relief + contours',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    subdomains: 'abc',
    maxZoom: 20,
    maxNativeZoom: 17,
    attribution: `${OSM_ATTR} · SRTM · © OpenTopoMap (CC-BY-SA)`,
    light: true,
    overlayOpacity: 0.45,
  },
}

const keyed = {}

if (MAPTILER_KEY) {
  keyed.streets = {
    id: 'streets',
    label: 'Streets',
    hint: 'MapTiler Streets (API key detected)',
    url: `https://api.maptiler.com/maps/streets-v2/{z}/{x}/{y}${R}.png?key=${MAPTILER_KEY}`,
    maxZoom: 22,
    maxNativeZoom: 22,
    attribution: MAPTILER_ATTR,
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
    attribution: MAPTILER_ATTR,
    labels: {
      url: `https://api.maptiler.com/maps/hybrid/{z}/{x}/{y}${R}.png?key=${MAPTILER_KEY}`,
      maxZoom: 22,
    },
    overlayOpacity: 0.4,
  }
  keyed.dark = {
    ...keyless.dark,
    hint: 'MapTiler Dark (API key detected)',
    url: `https://api.maptiler.com/maps/dataviz-dark/{z}/{x}/{y}${R}.png?key=${MAPTILER_KEY}`,
    subdomains: undefined,
    maxZoom: 22,
    maxNativeZoom: 22,
    attribution: MAPTILER_ATTR,
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

export const getBasemap = (id) =>
  BASEMAPS.find((b) => b.id === id) || BASEMAPS[0]

/** True when a commercial key was supplied — surfaced in the UI so a reviewer
 *  can tell at a glance which tiles they're looking at. */
export const USING_KEYED_TILES = Boolean(MAPTILER_KEY || THUNDERFOREST_KEY)
