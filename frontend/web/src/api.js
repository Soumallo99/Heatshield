/**
 * Data layer. All calls go to /api/*, which Vite proxies to FastAPI on :8000.
 * Browser code never references localhost — that's what keeps the phone/LAN path
 * (and the sandbox preview) working.
 *
 * LIVE-FIRST, NO DEMO DATA.
 * There used to be a MOCK_* fallback here: 14 invented wards, a hardcoded
 * 2026-09-05 date and synthetic hourly curves. It made a dead backend look
 * alive, which is the worst failure mode for a warning system — an operator
 * cannot tell a working pipeline from a screenshot. Every function below now
 * throws on failure and the UI renders an honest state instead
 * (see components/LiveStatus.jsx).
 *
 * Offline story: the service worker caches the app shell, and the API serves
 * the last computed run from data/processed/*.csv, so "offline" means
 * "last known data", clearly timestamped — never fabricated numbers.
 */
const BASE = '/api'

/** Thrown for any non-2xx or transport failure, with the status when known. */
class ApiError extends Error {
  constructor(message, status = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function getJSON(path, { signal } = {}) {
  let res
  try {
    res = await fetch(`${BASE}${path}`, { headers: { Accept: 'application/json' }, signal })
  } catch (err) {
    if (err?.name === 'AbortError') throw err
    // fetch rejects with a TypeError for connection refused / DNS / CORS.
    throw new ApiError(`cannot reach the HeatShield API (${path})`, null)
  }
  if (!res.ok) throw new ApiError(`HeatShield API returned ${res.status} (${path})`, res.status)

  const body = await res.json()
  // The service worker (public/sw.js) answers a failed /api fetch with HTTP 200
  // and this shape when it has nothing cached. Treating that as data would paint
  // an empty dashboard with a green "live" dot — the exact lie this file exists
  // to prevent. It is a failure, so it raises like one.
  if (body && body.stale === true && body.error) {
    throw new ApiError(`offline: ${body.error} (${path})`, 503)
  }
  return body
}

/* ------------------------------------------------------------------ api */

/** Ward league table for the peak day in the window (`date` = that day). */
export const fetchRanking = (scenario = 0) =>
  getJSON(`/risk/ranking?scenario_c=${scenario}`)

/** Single-ward drivers + impact. */
export const fetchWardRisk = (id, scenario = 0) =>
  getJSON(`/risk/ward/${id}?scenario_c=${scenario}`)

/** Ward registry (count must be 141). */
export const fetchZones = () => getJSON('/zones')

// /risk carries the UHI-adjusted series (wbgt_adj_c); /thermal carries the raw grid value.
export const fetchHourly = (wardId, scenario = 0) =>
  getJSON(`/risk?hours=24&ward_id=${wardId}&scenario_c=${scenario}`)

/** Ward boundary geometry — real KMC polygons, served statically so the
    service worker can cache them for offline use. A failure here degrades to
    "no boundaries" (the map still draws markers), so it resolves to null. */
export const fetchGeo = async () => {
  try {
    const r = await fetch('/data/kolkata_wards.geojson')
    if (!r.ok) throw new ApiError(`geojson ${r.status}`, r.status)
    return await r.json()
  } catch {
    return null
  }
}

/** Alert plan: who would be warned, with how many days of lead time.
    Threshold mirrors core.alerts.DEFAULT_RISK_THRESHOLD. */
export const ALERT_THRESHOLD = 60

export const fetchAlerts = (threshold = ALERT_THRESHOLD, lead = 1, scenario = 0) =>
  getJSON(`/alerts/plan?threshold=${threshold}&lead_days=${lead}&scenario_c=${scenario}`)
