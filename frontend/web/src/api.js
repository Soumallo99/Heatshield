/**
 * Data layer. All calls go to /api/*, which Vite proxies to FastAPI on :8000.
 * Browser code never references localhost — that's what keeps the phone/LAN path working.
 *
 * Every endpoint falls back to a bundled snapshot so the UI never renders empty
 * if the backend is down (demo insurance).
 */
const BASE = '/api'

async function get(path, fallback) {
  try {
    const res = await fetch(`${BASE}${path}`, { headers: { Accept: 'application/json' } })
    if (!res.ok) throw new Error(res.status)
    return await res.json()
  } catch {
    return fallback
  }
}

/* ------------------------------------------------------------------ mock */
const MOCK_WARDS = [
  [3, 'Jorasanko', 65.1, 'Danger', 33.53, 84.3, 2.62, 88000, 22.583, 88.361],
  [14, 'Howrah', 63.2, 'Danger', 33.45, 80.9, 2.7, 168000, 22.5958, 88.2639],
  [2, 'Shyambazar', 55.4, 'Danger', 33.17, 64.7, 2.41, 96000, 22.6, 88.375],
  [4, 'BBD Bagh', 55.3, 'Danger', 33.28, 60.7, 2.12, 42000, 22.574, 88.355],
  [12, 'Dum Dum', 54.6, 'Danger', 33.24, 66.8, 2.26, 149000, 22.62, 88.4],
  [9, 'Behala', 50.9, 'Danger', 32.71, 64.7, 2.1, 158000, 22.505, 88.31],
  [8, 'Tollygunge', 47.6, 'Caution', 32.59, 56.3, 1.86, 134000, 22.5, 88.345],
  [1, 'Cossipore', 45.7, 'Caution', 32.7, 45.8, 1.16, 118000, 22.631, 88.372],
  [10, 'Garia', 44.1, 'Caution', 32.59, 43.1, 1.6, 142000, 22.465, 88.38],
  [5, 'Park Street', 43.7, 'Caution', 32.32, 50.5, 1.3, 61000, 22.553, 88.351],
  [7, 'Ballygunge', 43.6, 'Caution', 32.44, 46.1, 1.54, 102000, 22.525, 88.365],
  [6, 'Alipore', 40.2, 'Caution', 32.0, 46.9, 0.65, 74000, 22.535, 88.337],
  [11, 'Salt Lake', 38.7, 'Caution', 32.39, 28.5, 0.51, 126000, 22.58, 88.41],
  [13, 'Rajarhat New Town', 32.2, 'Caution', 31.67, 21.9, 0.01, 97000, 22.59, 88.48],
]

const toRanking = (rows) => ({
  date: '2026-09-05',
  band_counts: rows.reduce((a, r) => ({ ...a, [r[3]]: (a[r[3]] || 0) + 1 }), {}),
  data: rows.map((r, i) => ({
    rank: i + 1, ward_id: r[0], ward_name: r[1], risk_score: r[2], risk_band: r[3],
    risk_colour: '#f97316', wbgt_peak_c: r[4], vulnerability: r[5], uhi_delta_c: r[6],
    population: r[7], lat: r[8], lon: r[9], exposed_population: Math.round(r[7] * r[2] / 100),
  })),
})

const MOCK_RANKING = toRanking(MOCK_WARDS)

const MOCK_HOURLY = { rows: 24, data: Array.from({ length: 24 }, (_, h) => {
  const wbgt = 27 + 6.5 * Math.exp(-((h - 14) ** 2) / 26)
  return {
    timestamp_local: `2026-09-05T${String(h).padStart(2, '0')}:00`,
    temp_c: 28 + 5.5 * Math.exp(-((h - 14) ** 2) / 30),
    wbgt_c: wbgt, wbgt_adj_c: wbgt + 0.9, heat_index_c: wbgt + 11, rh_pct: 88 - 20 * Math.exp(-((h - 14) ** 2) / 30),
    solar_wm2: Math.max(0, 900 * Math.exp(-((h - 13) ** 2) / 18)), risk_score: 30 + 30 * Math.exp(-((h - 14) ** 2) / 26),
    stress_band: wbgt > 31 ? 'Extreme' : wbgt > 29 ? 'Danger' : 'Caution',
  }
}) }

/* ------------------------------------------------------------------ api */
export const fetchRanking = (scenario = 0) =>
  get(`/risk/ranking?scenario_c=${scenario}`, MOCK_RANKING)

export const fetchWardRisk = (id) =>
  get(`/risk/ward/${id}`, {
    ward_id: id, ward_name: 'Jorasanko', risk_score: 65.1, risk_band: 'Danger',
    drivers: { wbgt_peak_c: 33.53, hazard_score: 68.4, vulnerability: 84.3, uhi_delta_c: 2.62, tmax_ward_c: 35.82 },
    impact: { population: 88000, exposed_population: 57288, relative_risk: 1.17, excess_deaths_per_day: 0.31 },
  })

export const fetchZones = () =>
  get('/zones', { count: MOCK_WARDS.length, zones: MOCK_WARDS.map((r) => ({
    ward_id: r[0], ward_name: r[1], lat: r[8], lon: r[9], population: r[7],
  })) })

// /risk carries the UHI-adjusted series (wbgt_adj_c); /thermal carries the raw grid value.
export const fetchHourly = (wardId) => get(`/risk?hours=24&ward_id=${wardId}`, MOCK_HOURLY)


/* Ward boundary geometry — real KMC polygons, served statically so the
   service worker can cache them for offline use. */
export const fetchGeo = async () => {
  try {
    const r = await fetch('/data/kolkata_wards.geojson')
    if (!r.ok) throw new Error(String(r.status))
    return await r.json()
  } catch {
    return null
  }
}

/* Alert plan: who would be warned, with how many days of lead time.
   Threshold mirrors core.alerts.DEFAULT_RISK_THRESHOLD. */
export const ALERT_THRESHOLD = 60

export const fetchAlerts = (threshold = ALERT_THRESHOLD, lead = 1, scenario = 0) =>
  get(`/alerts/plan?threshold=${threshold}&lead_days=${lead}&scenario_c=${scenario}`,
      { total_events: 0, pending_after_dedupe: 0, data: [] })
