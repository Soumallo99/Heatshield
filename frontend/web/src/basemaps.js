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
 * WHY THERE IS NO CARTO ENTRY ANY MORE (removed 2026-09, do not re-add):
 * since ~2026-08-28 CARTO's keyless raster endpoints answer HTTP 200 with a
 * watermark PNG that reads "API KEY REQUIRED" instead of failing. A failed
 * request is detectable (`tileerror`, the OSM fallback); a *successful*
 * response carrying a watermark is not — the map would have looked "loaded"
 * while every tile shouted for a key. Only providers whose keyless tiles are
 * genuinely keyless belong in this file. Esri's classic ArcGIS World/Canvas
 * services and OpenTopoMap are keyless; that is the whole registry.
 *
 * We deliberately do NOT scrape `mt{n}.google.com/vt` tiles: it violates the
 * Google Maps ToS. Google's licensed route (Maps JavaScript API / Map Tiles
 * API) needs a billing-enabled key — see README "Using Google tiles" for the
 * honest options.
 *
 * Every entry is a plain object consumed by <TileLayer/>, plus an optional
 * `labels` overlay URL (drawn on top of imagery so street names stay readable).
 * `maxNativeZoom` is the deepest level the provider actually has cached:
 * beyond it Leaflet upscales the last real tile instead of requesting a 404
 * and leaving a grey hole.
 */

const OSM_ATTR = '© OpenStreetMap contributors'
const ESRI_ATTR = 'Imagery © Esri, Maxar, Earthstar Geographics'
const ESRI_STREETS_ATTR =
  '© Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS user community'

/** ArcGIS Server REST cached-map tile URL. Note `{z}/{y}/{x}` — ArcGIS
 *  addresses tiles row-first; Leaflet substitutes in any order, so the
 *  template stays a plain string with no extra shim. */
const ARCGIS = (service) =>
  `https://server.arcgisonline.com/ArcGIS/rest/services/${service}/MapServer/tile/{z}/{y}/{x}`

/** Retina (@2x) tiles where the provider supports them — this is most of what
 *  makes a Leaflet map look as sharp as a commercial map on a modern display. */
const R = '{r}'

/** Ordered list shown in the map's layer switcher. */
export const BASEMAPS = [
  {
    id: 'dark',
    label: 'Dark',
    hint: 'Esri Dark Gray Canvas + place labels — the default, tuned for the risk choropleth',
    url: ARCGIS('Canvas/World_Dark_Gray_Base'),
    maxZoom: 20,
    maxNativeZoom: 16,
    attribution: ESRI_ATTR,
    labels: {
      url: ARCGIS('Canvas/World_Dark_Gray_Reference'),
      maxZoom: 20,
      maxNativeZoom: 16,
    },
    overlayOpacity: 0.34,
  },
  {
    id: 'streets',
    label: 'Streets',
    hint: 'Esri World Street Map — full street names, POIs, transit',
    url: ARCGIS('World_Street_Map'),
    maxZoom: 20,
    maxNativeZoom: 19,
    attribution: ESRI_STREETS_ATTR,
    light: true,
    overlayOpacity: 0.42,
  },
  {
    id: 'satellite',
    label: 'Satellite',
    hint: 'Esri World Imagery + place labels on top (the "hybrid" look)',
    url: ARCGIS('World_Imagery'),
    maxZoom: 20,
    maxNativeZoom: 19,
    attribution: ESRI_ATTR,
    labels: {
      // Reference overlay: real place/boundary labels out to z12 only, the way
      // the Esri hybrid map uses it. Past z12 Leaflet upscales the last label
      // tile, and the "Streets" basemap carries the high-zoom cartography.
      url: ARCGIS('Reference/World_Boundaries_and_Places'),
      maxZoom: 20,
      maxNativeZoom: 12,
    },
    overlayOpacity: 0.4,
  },
  {
    id: 'terrain',
    label: 'Terrain',
    hint: 'OpenTopoMap — relief + contours',
    url: `https://{s}.tile.opentopomap.org/{z}/{x}/{y}${R}.png`,
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
