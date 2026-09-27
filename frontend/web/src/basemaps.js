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
 *
 * WHY NO LAYER MAY SET `detectRetina` (Leaflet ≥ 1.9, fixed 2026-09-27):
 * `detectRetina` sets `zoomOffset = 1`, and Leaflet computes the URL zoom as
 * `_clampZoom(zoom) + zoomOffset` — the offset is added *after* the
 * `maxNativeZoom` clamp, so on any high-DPI screen the layer requests
 * `maxNativeZoom + 1`. None of these providers publishes `@2x` tiles, so the
 * flag bought no sharpness and only bought 404s: on a retina laptop or phone,
 * zooming past ~z15 holes out the map with failed tiles, each one tripping the
 * tile-failure counter until the map silently swapped itself for the OSM
 * fallback. It is off everywhere, and a test keeps it off.
 *
 * THREE STAGES, AND THE LAST ONE CANNOT BE WATERMARKED:
 *  0 — the chosen provider
 *  1 — OpenStreetMap (different CDN) if stage 0 stops answering
 *  2 — `NO_BASEMAP`: no tile requests at all
 * Stage 2 is the guarantee behind "no watermark". A watermark can only appear
 * on a pixel somebody else served; with `url: null` the map draws its own ward
 * polygons on its own background and requests nothing, so there is no third
 * party in a position to stamp anything. It also means the map is the one view
 * in the app that works with the network switched off.
 */

/*
 * ATTRIBUTION IS A LICENCE TERM, NOT DECORATION — and it has to name the data
 * actually being drawn.
 *
 * Every string below is copied from the `copyrightText` field of the ArcGIS
 * service it is attached to (verified against
 * `.../<service>/MapServer?f=json`; Dark Gray Canvas and World Imagery
 * re-verified 2026-09-27, previous full pass 2026-09-18) or from the
 * provider's own licence page.
 * Do not tidy them up and do not share one string between two services: the
 * Dark Gray Canvas is HERE/Garmin/OSM data and the World Imagery is
 * Vantor/Earthstar satellite imagery, and crediting one for the other is both
 * wrong and a breach of the terms we are using the tiles under. The previous
 * version of this file did exactly that — the default basemap advertised
 * satellite imagery that appears nowhere in it.
 */
const OSM_ATTR = '© OpenStreetMap contributors'

/** Canvas/World_Dark_Gray_Base + its Reference labels overlay. */
const ESRI_DARK_ATTR =
  'Sources: Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community'

/** World_Street_Map — the long form is the service's own copyrightText. */
const ESRI_STREETS_ATTR =
  'Sources: Esri, HERE, Garmin, USGS, Intermap, INCREMENT P, NRCan, Esri Japan, METI, ' +
  'Esri China (Hong Kong), Esri Korea, Esri (Thailand), NGCC, © OpenStreetMap contributors, ' +
  'and the GIS User Community'

/** World_Imagery, drawn with Reference/World_Boundaries_and_Places on top.
 *
 *  The imagery line is the service's current `copyrightText` as of 2026-09-18:
 *  "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community".
 *  Esri renamed the imagery supplier (Maxar → Vantor) in the service metadata;
 *  if this string and the service disagree again, the service wins — check
 *  `.../World_Imagery/MapServer?f=json` before editing. */
const ESRI_IMAGERY_ATTR =
  'Imagery: Esri, Vantor, Earthstar Geographics, and the GIS User Community · ' +
  'Labels: Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community'

/** ArcGIS Server REST cached-map tile URL. Note `{z}/{y}/{x}` — ArcGIS
 *  addresses tiles row-first; Leaflet substitutes in any order, so the
 *  template stays a plain string with no extra shim. */
const ARCGIS = (service) =>
  `https://server.arcgisonline.com/ArcGIS/rest/services/${service}/MapServer/tile/{z}/{y}/{x}`

/** "Wards only" — the basemap that is not a basemap.
 *
 *  `url: null` is load-bearing, not a placeholder: with no template there is
 *  no tile request, therefore no provider, therefore no watermark, no key
 *  screen, no CDN outage and no third-party tracking pixel. Everything the
 *  operations map actually needs — 141 ward polygons, the risk choropleth,
 *  labels, hover and selection — is local vector data drawn by Leaflet from
 *  `public/data/kolkata_wards.geojson` — which the service worker already
 *  precaches on install (see public/sw.js), so this stage is genuinely
 *  offline-capable and not just "offline-tolerant". It is the one view that
 *  still answers on a phone with no signal, which is exactly the situation a
 *  heat officer is most likely to be standing in. */
export const NO_BASEMAP = {
  id: 'none',
  label: 'Wards only',
  hint: 'No basemap tiles — ward boundaries on a plain background. Offline-capable; nothing can watermark it',
  url: null,
  attribution: 'Boundaries: datameet / OpenCity (ODbL)',
  // The choropleth is the only thing on screen here, so let it carry more ink
  // than it does over a photographic basemap.
  overlayOpacity: 0.62,
  offline: true,
}

/** Ordered list shown in the map's layer switcher. */
export const BASEMAPS = [
  {
    id: 'dark',
    label: 'Dark',
    hint: 'Esri Dark Gray Canvas + place labels — the default, tuned for the risk choropleth',
    url: ARCGIS('Canvas/World_Dark_Gray_Base'),
    maxZoom: 20,
    maxNativeZoom: 16,
    attribution: ESRI_DARK_ATTR,
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
    attribution: ESRI_IMAGERY_ATTR,
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
    // Plain tiles only. OpenTopoMap documents exactly one URL
    // (`https://{a|b|c}.tile.opentopomap.org/{z}/{x}/{y}.png`) with no retina
    // variant — so the template must stay free of Leaflet's `{r}` token: on a
    // high-DPI screen Leaflet would substitute `@2x` (Browser.retina), the tile
    // would 404, trip the tile-failure counter, and silently swap a working
    // Terrain map for the OSM fallback.
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    subdomains: 'abc',
    maxZoom: 20,
    maxNativeZoom: 17,
    attribution: `Map data: ${OSM_ATTR}, SRTM · Map style: © OpenTopoMap (CC-BY-SA)`,
    light: true,
    overlayOpacity: 0.45,
  },
  // Last in the list because it is the odd one out: it draws no tiles. It is
  // offered as a first-class choice, not held back as an emergency — an
  // operator on a bad connection should be able to pick it deliberately
  // instead of waiting for the map to notice.
  NO_BASEMAP,
]

export const DEFAULT_BASEMAP = 'dark'

export const getBasemap = (id) => BASEMAPS.find((b) => b.id === id) || BASEMAPS[0]

/** Failed tiles tolerated before the map steps down a stage. Deliberately not
 *  1: a single 404 at the very edge of a provider's coverage is normal and
 *  must not throw away a working basemap. See `noteTileResult` in RiskMap. */
export const TILE_FAIL_LIMIT = 6

/**
 * The basemap to draw at a given degradation `stage` (0 / 1 / 2).
 *
 * The stage only ever goes up, so the map can never oscillate between two
 * providers while a flaky network flaps. Stage ids are suffixed rather than
 * reused so React/Leaflet tear the layer down and rebuild it instead of
 * merging options into a live layer.
 */
export function basemapFor(basemap, stage) {
  if (stage <= 0 || !basemap.url) return basemap
  const next = stage === 1 ? OSM_FALLBACK : NO_BASEMAP
  const suffix = stage === 1 ? 'osm' : 'none'
  // Keep the chosen style's own `light` / `overlayOpacity` so the choropleth
  // does not change colour when the tiles underneath it do; replace only what
  // the replacement provider owns, and drop the label overlay (it belongs to
  // the provider it was authored for).
  return { ...basemap, ...next, id: `${basemap.id}-${suffix}`, labels: undefined }
}

/** Human sentence for the on-map notice shown at stages 1 and 2. */
export function degradeNotice(basemap, stage) {
  if (stage <= 0) return ''
  if (stage === 1) return `${basemap.label} tiles are not loading — showing OpenStreetMap instead.`
  return 'Basemap tiles are unreachable — showing ward boundaries only. Risk data is unaffected.'
}

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
