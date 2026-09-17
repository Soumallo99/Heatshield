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
      data_source: text(summary.data_source, 'Source unavailable'),
      fallback_reason: text(summary.fallback_reason, ''),
      city: {
        timestamp_local: text(rawCity.timestamp_local, ''),
        zones: finiteNumber(rawCity.zones),
        hottest_temp_c: finiteNumber(rawCity.hottest_temp_c),
        highest_aqi: finiteNumber(rawCity.highest_aqi),
        highest_heat_aqi_load: finiteNumber(rawCity.highest_heat_aqi_load),
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
