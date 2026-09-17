/**
 * Basemap registry — keyless by construction.
 *
 * DESIGN RULE (same as the rest of HeatShield): the project must clone-and-run
 * with zero signups, and a map must NEVER dead-end on an "API key required"
 * error tile. The registry therefore ships only keyless providers; the old
 * optional keyed-commercial-tile code path was deliberately removed so there
 * is no key slot left to misconfigure. If you genuinely need a commercial
 * provider, add an entry here yourself (README → "Maps are keyless") and keep
 * the automatic OSM_FALLBACK behaviour in RiskMap/DemoMap intact.
 *
 * We deliberately do NOT scrape `mt{n}.google.com/vt` tiles: it violates the
 * Google Maps ToS. Google's licensed route (Maps JavaScript API / Map Tiles
 * API) needs a billing-enabled key — see README "Using Google tiles" for the
 * honest options.
 *
 * Every entry is a plain object consumed by <TileLayer/>, plus an optional
 * `labels` overlay URL (drawn on top of imagery so street names stay readable).
 */

const OSM_ATTR = '© OpenStreetMap contributors'
const CARTO_ATTR = `${OSM_ATTR} · © CARTO`
const ESRI_ATTR = 'Imagery © Esri, Maxar, Earthstar Geographics'

/** Retina (@2x) tiles where the provider supports them — this is most of what
 *  makes a Leaflet map look as sharp as a commercial map on a modern display. */
const R = '{r}'

/** Ordered list shown in the map's layer switcher. */
export const BASEMAPS = [
  {
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
  {
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
  {
    id: 'satellite',
    label: 'Satellite',
    hint: 'Esri World Imagery + street labels on top (the "hybrid" look)',
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
  {
    id: 'terrain',
    label: 'Terrain',
    hint: 'OpenTopoMap — relief + contours',
    url: `https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png`,
    subdomains: 'abc',
    maxZoom: 20,
    maxNativeZoom: 17,
    attribution: `${OSM_ATTR} · SRTM · © OpenTopoMap (CC-BY-SA)`,
    light: true,
    overlayOpacity: 0.45,
  },
]

export const DEFAULT_BASEMAP = 'dark'

export const getBasemap = (id) => BASEMAPS.find((b) => b.id === id) || BASEMAPS[0]

/** Last-resort tiles on a DIFFERENT CDN than every basemap above: if the
 *  selected provider's tiles keep failing (blocked CDN, hostile proxy), the
 *  maps degrade to plain OpenStreetMap instead of showing broken tiles —
 *  still keyless, still no "API key required" screen. */
export const OSM_FALLBACK = {
  id: 'osm-fallback',
  url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  subdomains: 'abc',
  maxZoom: 19,
  maxNativeZoom: 19,
  attribution: OSM_ATTR,
}
