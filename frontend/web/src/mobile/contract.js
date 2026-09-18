/*
 * Phone-app data contract.
 *
 * Keep normalisation at the boundary: individual screens only consume this
 * shape, so an optional missing provider field becomes an em dash rather than
 * NaN, undefined, or Invalid Date in a resident-facing alert.
 */
export const SCREEN_IDS = ['home', 'outlook', 'alerts', 'safety', 'about']

export const SCREEN_LABELS = {
  home: 'Now',
  outlook: 'Outlook',
  alerts: 'Watch',
  safety: 'Safety',
  about: 'About',
}

// This is consumed by tests/test_mobile_app.py. It records every API field the
// server-rendered screen is permitted to read, making the rendered contract a
// real compatibility check instead of a grep over JSX.
export const READS_BY_SCREEN = {
  home: [
    'summary.city.timestamp_local', 'summary.city.zones', 'summary.city.hottest_temp_c',
    'summary.city.highest_aqi', 'summary.city.highest_heat_aqi_load',
    'summary.data[].zone_id', 'summary.data[].zone_name', 'summary.data[].temp_c',
    'summary.data[].rh_pct', 'summary.data[].wind_kmh', 'summary.data[].pm25_ugm3',
    'summary.data[].aqi_india', 'summary.data[].aqi_band', 'summary.data[].heat_multiplier',
    'summary.data[].heat_aqi_load', 'summary.data[].heat_aqi_load_band',
    'summary.is_synthetic', 'summary.data_source',
  ],
  outlook: [
    'daily[].zone_id', 'daily[].zone_name', 'daily[].date', 'daily[].tmax_c',
    'daily[].pm25_mean_ugm3', 'daily[].aqi_peak', 'daily[].aqi_band',
    'daily[].heat_aqi_load_peak', 'daily[].heat_aqi_load_band',
  ],
  alerts: [
    'alerts.rows', 'alerts.climatology.available', 'alerts.climatology.reference_period',
    'alerts.data[].zone_id', 'alerts.data[].zone_name', 'alerts.data[].date',
    'alerts.data[].tmax_c', 'alerts.data[].normal_tmax_c', 'alerts.data[].departure_c',
    'alerts.data[].heatwave_label', 'alerts.data[].is_heatwave_episode',
    'alerts.data[].is_severe_episode', 'alerts.data[].extreme_temperature_watch',
    'alerts.data[].aqi_peak', 'alerts.data[].heat_aqi_load_peak',
  ],
  safety: ['summary.data[].aqi_band', 'summary.data[].heat_aqi_load_band'],
  about: ['summary.static_snapshot', 'summary.is_synthetic', 'summary.data_source', 'source_notice'],
}

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value)
const asObject = (value) => (isObject(value) ? value : {})
const asArray = (value) => (Array.isArray(value) ? value : [])

export function finiteNumber(value) {
  // Number(null) is 0 — a silent lie for absent values. Null-ish inputs must
  // stay null so screens render an honest em dash instead of a fake zero.
  if (value === null || value === undefined || value === '') return null
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function text(value, fallback = '—') {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

export function formatNumber(value, decimals = 0) {
  const number = finiteNumber(value)
  return number === null ? '—' : number.toFixed(decimals)
}

export function formatDate(value) {
  // Never let Date stringify an invalid input as "Invalid Date". Date-only
  // values are parsed at noon UTC to avoid a timezone shift on the phone.
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(value)) return 'Date unavailable'
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return 'Date unavailable'
  return new Intl.DateTimeFormat('en-IN', { weekday: 'short', day: 'numeric', month: 'short' }).format(parsed)
}

function normaliseZone(row) {
  const raw = asObject(row)
  return {
    zone_id: text(raw.zone_id, ''),
    zone_name: text(raw.zone_name, 'Location unavailable'),
    lat: finiteNumber(raw.lat),
    lon: finiteNumber(raw.lon),
    timestamp_local: text(raw.timestamp_local, ''),
    temp_c: finiteNumber(raw.temp_c),
    rh_pct: finiteNumber(raw.rh_pct),
    wind_kmh: finiteNumber(raw.wind_kmh),
    pm25_ugm3: finiteNumber(raw.pm25_ugm3),
    aqi_india: finiteNumber(raw.aqi_india),
    aqi_band: text(raw.aqi_band, 'Unknown'),
    heat_multiplier: finiteNumber(raw.heat_multiplier),
    heat_aqi_load: finiteNumber(raw.heat_aqi_load),
    heat_aqi_load_band: text(raw.heat_aqi_load_band, 'Unknown'),
    wbgt_c: finiteNumber(raw.wbgt_c),
    heat_index_c: finiteNumber(raw.heat_index_c),
    stress_band: text(raw.stress_band, ''),
    is_synthetic: raw.is_synthetic === true,
  }
}

function normaliseDay(row) {
  const raw = asObject(row)
  return {
    zone_id: text(raw.zone_id, ''),
    zone_name: text(raw.zone_name, 'Location unavailable'),
    date: text(raw.date, ''),
    tmax_c: finiteNumber(raw.tmax_c),
    pm25_mean_ugm3: finiteNumber(raw.pm25_mean_ugm3),
    aqi_peak: finiteNumber(raw.aqi_peak),
    aqi_band: text(raw.aqi_band, 'Unknown'),
    heat_aqi_load_peak: finiteNumber(raw.heat_aqi_load_peak),
    heat_aqi_load_band: text(raw.heat_aqi_load_band, 'Unknown'),
    wbgt_peak_c: finiteNumber(raw.wbgt_peak_c),
    stress_band: text(raw.stress_band, ''),
    heatwave_label: text(raw.heatwave_label, ''),
    risk_score: finiteNumber(raw.risk_score),
    risk_band: text(raw.risk_band, ''),
    normal_tmax_c: finiteNumber(raw.normal_tmax_c),
    departure_c: finiteNumber(raw.departure_c),
  }
}

function normaliseAlert(row) {
  const raw = asObject(row)
  return {
    zone_id: text(raw.zone_id, ''),
    zone_name: text(raw.zone_name, 'Location unavailable'),
    date: text(raw.date, ''),
    tmax_c: finiteNumber(raw.tmax_c),
    normal_tmax_c: finiteNumber(raw.normal_tmax_c),
    departure_c: finiteNumber(raw.departure_c),
    heatwave_label: text(raw.heatwave_label, 'Watch'),
    is_heatwave_episode: raw.is_heatwave_episode === true,
    is_severe_episode: raw.is_severe_episode === true,
    extreme_temperature_watch: raw.extreme_temperature_watch === true,
    aqi_peak: finiteNumber(raw.aqi_peak),
    heat_aqi_load_peak: finiteNumber(raw.heat_aqi_load_peak),
    wbgt_peak_c: finiteNumber(raw.wbgt_peak_c),
    stress_band: text(raw.stress_band, ''),
  }
}

export function normalisePhonePayload(value) {
  const raw = asObject(value)
  // Static citizen.json nests the live summary. A direct live summary remains
  // accepted to keep local API development friction-free.
  const summary = asObject(raw.summary || raw)
  const alertEnvelope = asObject(raw.alerts)
  const rawCity = asObject(summary.city)
  const zones = asArray(summary.data).map(normaliseZone).filter((zone) => zone.zone_id)
  const daily = asArray(raw.daily).map(normaliseDay).filter((day) => day.zone_id)
  const alerts = asArray(alertEnvelope.data).map(normaliseAlert).filter((alert) => alert.zone_id)

  return {
    schema_version: finiteNumber(raw.schema_version) || 1,
    source_notice: text(raw.source_notice, ''),
    summary: {
      static_snapshot: summary.static_snapshot === true || raw.static_snapshot === true,
      is_synthetic: summary.is_synthetic === true,
      city_profile: text(summary.city_profile, 'ncr') === 'kolkata' ? 'kolkata' : 'ncr',
      data_source: text(summary.data_source, 'Source unavailable'),
      fallback_reason: text(summary.fallback_reason, ''),
      city: {
        timestamp_local: text(rawCity.timestamp_local, ''),
        zones: finiteNumber(rawCity.zones),
        hottest_temp_c: finiteNumber(rawCity.hottest_temp_c),
        highest_aqi: finiteNumber(rawCity.highest_aqi),
        highest_heat_aqi_load: finiteNumber(rawCity.highest_heat_aqi_load),
        peak_wbgt_c: finiteNumber(rawCity.peak_wbgt_c),
        wards_in_alert: finiteNumber(rawCity.wards_in_alert),
      },
      data: zones,
    },
    daily,
    alerts: {
      rows: finiteNumber(alertEnvelope.rows) || alerts.length,
      climatology: asObject(alertEnvelope.climatology),
      data: alerts,
    },
  }
}

export const EMPTY_PHONE_PAYLOAD = normalisePhonePayload({
  summary: { data: [], city: {}, data_source: 'No data loaded' },
  alerts: { rows: 0, data: [], climatology: {} },
  daily: [],
})

/* ------------------------------------------------- personal heat-risk alerts */

/* Advice wording mirrors the Safety screen — one clear instruction per band,
   never colour-only, never implying a medical diagnosis. */
const PERSONAL_ALERT_ADVICE = {
  Severe: 'Stay in the coolest room you can. Confusion, fainting or hot dry skin is an emergency — seek medical help now.',
  'Very Poor': 'Avoid the sun 12:00–15:00. Drink water every hour; use a cooling centre if your home is unbearable.',
  Poor: 'Plan outdoor work for morning or evening. Carry water and check on elderly neighbours.',
}

/* Notify from this load band upward, or on absolute heat regardless of band. */
const PERSONAL_ALERT_TRIGGER_TEMP_C = 40

/* Kolkata briefs carry WBGT stress bands instead of an air-quality load
   (no AQ source is bundled for Kolkata — the payload says so). */
const STRESS_ALERT_ADVICE = {
  Extreme: 'WBGT is extreme — life-threatening heat stress. Stay indoors with cooling; confusion, fainting or hot dry skin is an emergency.',
  Critical: 'WBGT is critical — suspend non-essential outdoor work, stay in the coolest room you can, drink water every hour.',
}

/**
 * Build ONE honest personal heat-risk notification for a zone, or null when
 * conditions do not warrant interrupting the resident. Synthetic payloads are
 * labelled inside the message body — a practice alert must never read like a
 * live one.
 */
export function heatAlertFor(zone, meta = {}) {
  if (!zone || typeof zone !== 'object') return null
  const band = typeof zone.heat_aqi_load_band === 'string' ? zone.heat_aqi_load_band : ''
  const stress = typeof zone.stress_band === 'string' ? zone.stress_band : ''
  const advice = PERSONAL_ALERT_ADVICE[band] || STRESS_ALERT_ADVICE[stress]
  const temp = finiteNumber(zone.temp_c)
  const hot = temp !== null && temp >= PERSONAL_ALERT_TRIGGER_TEMP_C
  if (!advice && !hot) return null
  const synthetic = meta.isSynthetic === true || zone.is_synthetic === true
  const label = synthetic
    ? 'Practice data (provider outage or snapshot) — not a live forecast'
    : 'Live forecast'
  const tempText = temp === null ? '—' : `${temp.toFixed(1)} °C`
  const name = text(zone.zone_name, 'your locality')
  const wbgt = finiteNumber(zone.wbgt_c)
  const measure = finiteNumber(zone.heat_aqi_load) !== null
    ? `combined heat+air load ${formatNumber(zone.heat_aqi_load, 0)} (${band || 'Unknown'})`
    : wbgt !== null
      ? `estimated WBGT ${wbgt.toFixed(1)} °C (${stress || 'band unavailable'})`
      : `heat band ${band || stress || 'unavailable'}`
  return {
    kind: 'danger',
    id: `${text(zone.zone_id, 'zone')}|${text(zone.timestamp_local, '')}|${band}|${stress}|${synthetic ? 'syn' : 'live'}`,
    title: `HeatShield · ${name}`,
    body: `${label} — ${measure} · ${tempText}. `
      + (advice || 'Heat is high today: hydrate hourly, stay in shade during peak sun, and check on neighbours.'),
  }
}

/**
 * The unified personal notification: a DANGER alert when the zone is in a
 * heatwave/stress danger state, otherwise a calm informational update with
 * the plain facts (temperature, humidity, wind — plus WBGT on the Kolkata
 * profile). Returns null only when there is nothing honest to say.
 */
export function personalNotificationFor(zone, meta = {}) {
  const danger = heatAlertFor(zone, meta)
  if (danger) return danger
  if (!zone || typeof zone !== 'object') return null
  const temp = finiteNumber(zone.temp_c)
  if (temp === null) return null
  const synthetic = meta.isSynthetic === true || zone.is_synthetic === true
  const label = synthetic ? 'Practice data — not a live forecast' : 'Live'
  const facts = [`${temp.toFixed(1)} °C`]
  const rh = finiteNumber(zone.rh_pct)
  if (rh !== null) facts.push(`humidity ${rh.toFixed(0)}%`)
  const wind = finiteNumber(zone.wind_kmh)
  if (wind !== null) facts.push(`wind ${wind.toFixed(1)} km/h`)
  const wbgt = finiteNumber(zone.wbgt_c)
  if (wbgt !== null) facts.push(`est. WBGT ${wbgt.toFixed(1)} °C`)
  const name = text(zone.zone_name, 'your locality')
  return {
    kind: 'info',
    id: `info|${text(zone.zone_id, 'zone')}|${text(zone.timestamp_local, '')}|${synthetic ? 'syn' : 'live'}`,
    title: `HeatShield · ${name}`,
    body: `${label} — no heat danger right now: ${facts.join(' · ')}.`,
  }
}

/** Great-circle distance in km — used only to pick the nearest zone label. */
function haversineKm(lat1, lon1, lat2, lon2) {
  const toRad = (deg) => (deg * Math.PI) / 180
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

/**
 * Nearest zone to a GPS fix, from the payload's own coordinates (the same
 * Delhi-NCR zone registry the demo map uses — no geocoding API key needed).
 * Returns null when nothing has coordinates yet.
 */
export function nearestZone(zones, lat, lon) {
  const fromLat = finiteNumber(lat)
  const fromLon = finiteNumber(lon)
  if (fromLat === null || fromLon === null) return null
  let best = null
  for (const zone of asArray(zones)) {
    const zoneLat = finiteNumber(zone.lat)
    const zoneLon = finiteNumber(zone.lon)
    if (zoneLat === null || zoneLon === null) continue
    const km = haversineKm(fromLat, fromLon, zoneLat, zoneLon)
    if (!best || km < best.km) best = { zone_id: zone.zone_id, zone_name: zone.zone_name, km }
  }
  return best
}
