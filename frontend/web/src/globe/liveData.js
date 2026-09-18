/**
 * The globe's live tracking layers — the client half.
 *
 * Three layers, all optional, all off until an operator turns one on:
 * aircraft (adsb.lol), earthquakes (USGS) and satellites (CelesTrak). Every
 * one of them is fetched from *this* origin through `./api/live/*`, and the
 * FastAPI process does the upstream call (see core/live.py). The browser never
 * opens a connection to a tracking provider, which is what keeps the promise
 * in THIRD-PARTY.md true: the only third-party hosts this page talks to are
 * the map tile providers, and even those are named in the service worker.
 *
 * The rule the whole file is built around: **a layer that cannot be shown says
 * so, and a layer that can be shown is real.** There is no sample aircraft, no
 * "last known" position invented client-side, and a static deployment (GitHub
 * Pages, where there is no API process at all) is told it has no API rather
 * than being given something that looks like data.
 */
import { isStaticHost } from '../staticApi.js'

export class LiveLayerError extends Error {
  /**
   * @param message  what to show an operator
   * @param kind     'no-api' | 'unreachable' | 'http' | 'offline' | 'bad-json'
   * @param cause    the underlying error, when there is one
   * @param status   HTTP status, when there is one
   */
  constructor(message, kind = 'unreachable', cause = null, status = null) {
    super(message)
    this.name = 'LiveLayerError'
    this.kind = kind
    this.cause = cause
    this.status = status
  }
}

/**
 * The layers, in the order they appear on the globe.
 *
 * `refresh_ms` is how often the operator's globe asks again *while the layer
 * is on* — it follows how quickly each source actually changes, not how fast
 * we could poll. Asking CelesTrak every 20 seconds would be rude and pointless:
 * element sets are published a few times a day.
 */
export const LIVE_LAYERS = [
  {
    id: 'aircraft',
    label: 'Aircraft',
    title: 'Live ADS-B traffic — adsb.lol',
    refresh_ms: 20000,
    hint: 'Aircraft broadcasting ADS-B within the search radius. Volunteer receivers, so coverage follows where the feeders are.',
  },
  {
    id: 'earthquakes',
    label: 'Quakes',
    title: 'Earthquakes, past day — USGS',
    refresh_ms: 60000,
    hint: 'USGS events of magnitude 2.5 and above. Context, not a hazard product: this is not a warning system for shaking.',
  },
  {
    id: 'satellites',
    label: 'Satellites',
    title: 'Orbits from CelesTrak element sets',
    refresh_ms: 120000,
    hint: 'Positions propagated in this browser from CelesTrak GP element sets (SGP4, satellite.js). Satellites move; the element set does not.',
  },
]

const byId = (id) => LIVE_LAYERS.find((layer) => layer.id === id) || null

/** The refresh interval for a layer, in milliseconds. */
export const refreshIntervalFor = (id) => byId(id)?.refresh_ms ?? 60000

/**
 * The URL of one layer, relative to the document.
 *
 * Relative on purpose (`./api`, never `/api`): this app is served from a
 * repository subdirectory on GitHub Pages, where a root-relative path leaves
 * the app — and leaves the service worker's scope, so its network-first cache
 * for `api/` could never answer.
 */
export function liveURL(id, params = null) {
  const query = params
    ? Object.entries(params)
        .filter(([, value]) => value !== null && value !== undefined && value !== '')
        .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
        .join('&')
    : ''
  return query ? `./api/live/${id}?${query}` : `./api/live/${id}`
}

/**
 * Why the live layers cannot load here, or null when they can try.
 *
 * Asked *before* the first request rather than after a failure: on a static
 * host the answer is known (GitHub Pages serves files, not FastAPI), and a
 * request that is going to 404 on every press is a request the app should not
 * make. `fetchLiveLayer` checks this too, so a caller that forgets still gets
 * the honest reason instead of a network error.
 */
export function staticHostNotice() {
  if (typeof window === 'undefined' || !isStaticHost()) return null
  return 'This is the static site: there is no HeatShield API here, so the live layers cannot load. Everything else on this page is unaffected.'
}

/** Turn a failure into one sentence an operator can act on. */
export function describeLiveFailure(error) {
  if (!error) return null
  if (error instanceof LiveLayerError) {
    if (error.kind === 'no-api') {
      return 'The live layers need the HeatShield API, and this deployment has none. Nothing is shown rather than a guess.'
    }
    if (error.kind === 'offline') {
      return 'Offline: the last live answer is gone and there is no API to ask. Nothing is shown rather than a guess.'
    }
    return error.message
  }
  if (error?.name === 'AbortError') return null
  return error?.message ? String(error.message) : 'The live layer could not be loaded.'
}

/**
 * Fetch one layer.
 *
 * A 200 is not automatically data: the API answers `available: false` with a
 * notice when the upstream did not answer, and the service worker answers a
 * failed `/api` fetch with `{stale: true, error: 'offline'}`. Both are
 * returned/raised as what they are — an honest payload, or a failure — and the
 * caller shows the `notice` or the message. Neither is ever turned into rows.
 */
export async function fetchLiveLayer(id, { signal, params = null } = {}) {
  const staticNotice = staticHostNotice()
  if (staticNotice) throw new LiveLayerError(staticNotice, 'no-api')

  const url = liveURL(id, params)
  let response
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' }, signal })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new LiveLayerError(`cannot reach the HeatShield API (${url})`, 'unreachable', error)
  }
  if (!response.ok) {
    // 404 is the static-host case: no API process is listening. Saying "there
    // is no API here" is the truth; "the API failed" would send an operator
    // hunting for a bug in a service that was never deployed.
    throw new LiveLayerError(
      `${url} returned ${response.status}`,
      response.status === 404 ? 'no-api' : 'http',
      null,
      response.status,
    )
  }
  let payload
  try {
    payload = await response.json()
  } catch (error) {
    throw new LiveLayerError(`the HeatShield API returned invalid JSON (${url})`, 'bad-json', error)
  }
  if (payload && payload.stale === true && payload.error) {
    throw new LiveLayerError(`offline: ${payload.error} (${url})`, 'offline')
  }
  return payload
}

/* ------------------------------------------------------------------ orbits */

/**
 * A CelesTrak OMM object for satellite.js.
 *
 * The API serves HeatShield's own snake_case names (core/live.py renames
 * CelesTrak's SCREAMING_CASE fields), so this maps them back for the
 * propagator. Doing it here rather than passing the upstream JSON straight
 * through means a rename at CelesTrak is one line in the API, not a change in
 * every surface that reads it.
 */
export function ommForSatrec(row) {
  return {
    OBJECT_NAME: row?.name,
    OBJECT_ID: row?.object_id,
    NORAD_CAT_ID: row?.norad_id,
    EPOCH: row?.epoch,
    MEAN_MOTION: row?.mean_motion,
    ECCENTRICITY: row?.eccentricity,
    INCLINATION: row?.inclination,
    RA_OF_ASC_NODE: row?.ra_of_asc_node,
    ARG_OF_PERICENTER: row?.arg_of_pericenter,
    MEAN_ANOMALY: row?.mean_anomaly,
    BSTAR: row?.bstar,
    MEAN_MOTION_DOT: row?.mean_motion_dot,
    MEAN_MOTION_DDOT: row?.mean_motion_ddot,
    REV_AT_EPOCH: row?.rev_at_epoch,
  }
}

let propagator = null

/**
 * Load the SGP4 library once, and remember it.
 *
 * Injected (`load`) so the tests can drive this without a module registry;
 * the default is a dynamic import, which keeps satellite.js out of every
 * chunk except the globe's.
 */
export async function ensurePropagator(load = () => import('satellite.js')) {
  if (propagator) return propagator
  const library = await load()
  propagator = {
    json2satrec: library.json2satrec,
    propagate: library.propagate,
    gstime: library.gstime,
    eciToGeodetic: library.eciToGeodetic,
    radiansToDegrees: library.radiansToDegrees,
  }
  return propagator
}

/** Forget the loaded library (tests). */
export function resetPropagator() {
  propagator = null
}

const RADIANS_TO_DEGREES = 180 / Math.PI

/**
 * Element sets -> positions on the globe, for one instant.
 *
 * Objects whose element sets cannot be initialised, or whose propagation
 * returns no position (a decayed orbit, say), are *dropped* — a satellite
 * drawn at the wrong place is worse than one not drawn, because nothing on
 * screen tells the operator which is which.
 *
 * @returns rows carrying `lat`, `lon` (degrees) and `alt_km`
 */
export function propagateSatellites(rows, date = new Date(), library = propagator) {
  if (!library || !Array.isArray(rows)) return []
  const gmst = library.gstime(date)
  const toDegrees = library.radiansToDegrees || ((radians) => radians * RADIANS_TO_DEGREES)
  const out = []
  for (const row of rows) {
    let satrec
    try {
      satrec = library.json2satrec(ommForSatrec(row))
    } catch {
      continue
    }
    if (!satrec || satrec.error) continue
    let state
    try {
      state = library.propagate(satrec, date)
    } catch {
      continue
    }
    if (!state || !state.position || state.error) continue
    let geodetic
    try {
      geodetic = library.eciToGeodetic(state.position, gmst)
    } catch {
      continue
    }
    if (!geodetic || !Number.isFinite(geodetic.latitude) || !Number.isFinite(geodetic.longitude)) continue
    out.push({
      ...row,
      lat: Number(toDegrees(geodetic.latitude).toFixed(4)),
      lon: Number(toDegrees(geodetic.longitude).toFixed(4)),
      alt_km: Number.isFinite(geodetic.height) ? Number(geodetic.height.toFixed(1)) : null,
      propagated_at: date.toISOString(),
    })
  }
  return out
}

/**
 * Rows the globe can draw, whatever the layer.
 *
 * Aircraft and earthquake rows arrive with a position already; satellites
 * arrive as element sets and are propagated here. The distinction is invisible
 * to the component, which is the point: one code path draws all three.
 */
export async function positionsFor(layerId, rows, date = new Date()) {
  if (layerId !== 'satellites') return Array.isArray(rows) ? rows : []
  if (!rows?.length) return []
  const library = await ensurePropagator()
  return propagateSatellites(rows, date, library)
}
