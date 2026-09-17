/*
 * Heat Risk Demo data contract.
 *
 * Same discipline as the citizen phone contract: normalisation happens once,
 * at the boundary, so every screen reads guaranteed shapes and a missing or
 * malformed field becomes an em dash — never NaN, undefined, or Invalid Date.
 *
 * The demo is synthetic BY DESIGN and says so on every screen: the canonical
 * disclaimer string below must appear verbatim in payloads and UI.
 */
export const DEMO_DISCLAIMER = 'Demo / synthetic scenario — not a live forecast or observation.'

export const DEMO_SCREEN_IDS = ['now', 'outlook', 'zones', 'impact', 'notify', 'about']

export const DEMO_SCREEN_LABELS = {
  now: 'Now',
  outlook: 'Outlook',
  zones: 'Zones',
  impact: 'Impact',
  notify: 'Alerts',
  about: 'Method',
}

export const ALERT_LEVEL_ORDER = ['routine', 'watch', 'warning', 'severe']

// Consumed by tests/demo/render_demo.mjs (mirrors the tests/mobile pattern):
// the exact NORMALISED payload paths each server-rendered screen reads. The
// harness proves every path resolves against the real exported static bundle
// and that the empty state renders honestly.
export const READS_BY_SCREEN = {
  now: [
    'scenario.label', 'scenario.id', 'warnings.issued_at',
    'warnings.rows[].zone_id', 'warnings.rows[].lead_days', 'warnings.rows[].tmax_c',
    'warnings.rows[].wbgt_est_peak_c', 'warnings.rows[].hi_peak_c', 'warnings.rows[].htsi_band',
    'warnings.rows[].alert_level',
    'forecast.hourly[].zone_id', 'forecast.hourly[].timestamp_local', 'forecast.hourly[].temp_c',
    'forecast.hourly[].rh_pct', 'forecast.hourly[].wind_kmh', 'forecast.hourly[].solar_wm2',
    'thermal.hourly[].zone_id', 'thermal.hourly[].timestamp_local', 'thermal.hourly[].wbgt_est_c',
    'thermal.hourly[].heat_index_c', 'thermal.hourly[].htsi_band', 'thermal.hourly[].wbgt_quality',
  ],
  outlook: [
    'warnings.rows[].zone_id', 'warnings.rows[].zone_name', 'warnings.rows[].target_date',
    'warnings.rows[].target_day_label', 'warnings.rows[].lead_days', 'warnings.rows[].lead_hours',
    'warnings.rows[].tmax_c', 'warnings.rows[].normal_tmax_c', 'warnings.rows[].departure_c',
    'warnings.rows[].wbgt_est_peak_c', 'warnings.rows[].hi_peak_c', 'warnings.rows[].htsi_score',
    'warnings.rows[].htsi_band', 'warnings.rows[].heatwave_label', 'warnings.rows[].is_heatwave_episode',
    'warnings.rows[].alert_level', 'warnings.rows[].aqi_peak', 'warnings.rows[].heat_aqi_load_peak',
    'warnings.climatology.reference_period', 'warnings.persistence_rule',
  ],
  zones: [
    'zones[].zone_id', 'zones[].zone_name', 'zones[].vulnerability_score', 'zones[].vulnerability_level',
    'zones[].cooling_centre_count', 'zones[].cooling_access_score',
    'warnings.rows[].zone_id', 'warnings.rows[].zone_name', 'warnings.rows[].lead_days',
    'warnings.rows[].alert_level', 'warnings.rows[].htsi_band', 'warnings.rows[].tmax_c',
    'warnings.rows[].wbgt_est_peak_c', 'warnings.rows[].vulnerability_level',
    'warnings.rows[].health_impact_band', 'warnings.rows[].heatwave_label',
  ],
  impact: [
    'zones[].zone_id', 'zones[].zone_name', 'zones[].population', 'zones[].elderly_pct',
    'zones[].outdoor_worker_pct', 'zones[].illiteracy_pct', 'zones[].cooling_centre_count',
    'zones[].cooling_access_score', 'zones[].vulnerability_score', 'zones[].vulnerability_level',
    'zones[].vulnerability_source',
    'warnings.rows[].zone_id', 'warnings.rows[].htsi_score', 'warnings.rows[].htsi_band',
    'warnings.rows[].wbgt_est_peak_c', 'warnings.rows[].wbgt_peak_quality', 'warnings.rows[].wbgt_peak_inputs',
    'warnings.rows[].hi_peak_c', 'warnings.rows[].vulnerability_score', 'warnings.rows[].vulnerability_level',
    'warnings.rows[].health_impact_index', 'warnings.rows[].health_impact_band',
    'warnings.rows[].health_impact_status', 'warnings.rows[].health_impact_status_meaning',
    'warnings.rows[].alert_level', 'warnings.rows[].recommended_action_level',
    'warnings.action_matrix', 'thermal.method.score_formula', 'thermal.wbgt_statement',
  ],
  notify: [
    'notifications.rows', 'notifications.dry_run', 'notifications.dispatch_policy.default',
    'notifications.dispatch_policy.demo_guard',
    'notifications.previews[].preview_id', 'notifications.previews[].audience',
    'notifications.previews[].audience_label', 'notifications.previews[].channel',
    'notifications.previews[].zone_name', 'notifications.previews[].severity',
    'notifications.previews[].severity_label', 'notifications.previews[].target_date',
    'notifications.previews[].lead_days', 'notifications.previews[].lead_hours',
    'notifications.previews[].reason', 'notifications.previews[].recommended_action',
    'notifications.previews[].data_quality_state', 'notifications.previews[].message',
    'notifications.previews[].status', 'notifications.previews[].live_send',
    'notifications.previews[].demo_disclaimer',
  ],
  about: [
    'scenario.label', 'scenario.summary', 'scenario.issued_at_note', 'scenario.teaching_points',
    'scenarios.how_to_read', 'warnings.climatology.reference_period', 'warnings.granularity_note',
    'thermal.method.score_formula', 'thermal.method.separation_rule',
    'zonesVulnerabilityFormula', 'zonesVulnerabilitySource',
  ],
}

/* ------------------------------------------------------------------ guards */

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

export function formatTemp(value) {
  const number = finiteNumber(value)
  return number === null ? '—' : `${number.toFixed(1)} °C`
}

export function formatDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(value)) return 'Date unavailable'
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return 'Date unavailable'
  return new Intl.DateTimeFormat('en-IN', { weekday: 'short', day: 'numeric', month: 'short' }).format(parsed)
}

export function formatHour(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return '—'
  return value.slice(11, 16)
}

/* ------------------------------------------------------------- normalisers */

function normaliseScenarioMeta(raw) {
  const scenario = asObject(raw)
  return {
    id: text(scenario.id, ''),
    label: text(scenario.label, 'Scenario unavailable'),
    tagline: text(scenario.tagline, ''),
    summary: text(scenario.summary, ''),
    issued_at_local: text(scenario.issued_at_local, ''),
    issued_at_note: text(scenario.issued_at_note, ''),
    timezone: text(scenario.timezone, 'Asia/Kolkata'),
    forecast_days: finiteNumber(scenario.forecast_days),
    teaching_points: asArray(scenario.teaching_points).map((point) => text(point)).filter((point) => point !== '—'),
    expected: asObject(scenario.expected),
    data_source: text(scenario.data_source, 'synthetic demo scenario'),
    demo_disclaimer: text(scenario.demo_disclaimer, DEMO_DISCLAIMER),
  }
}

function normaliseZone(raw) {
  const zone = asObject(raw)
  return {
    zone_id: text(zone.zone_id, ''),
    zone_name: text(zone.zone_name, 'Zone unavailable'),
    lat: finiteNumber(zone.lat),
    lon: finiteNumber(zone.lon),
    population: finiteNumber(zone.population),
    pop_density_km2: finiteNumber(zone.pop_density_km2),
    elderly_pct: finiteNumber(zone.elderly_pct),
    outdoor_worker_pct: finiteNumber(zone.outdoor_worker_pct),
    illiteracy_pct: finiteNumber(zone.illiteracy_pct),
    cooling_centre_count: finiteNumber(zone.cooling_centre_count),
    cooling_access_score: finiteNumber(zone.cooling_access_score),
    vulnerability_score: finiteNumber(zone.vulnerability_score),
    vulnerability_level: text(zone.vulnerability_level, 'Unavailable'),
    vulnerability_source: text(zone.vulnerability_source, 'unavailable'),
    cooling_centres: asArray(zone.cooling_centres).map((centre) => ({
      name: text(asObject(centre).name, 'Cooling centre'),
      lat: finiteNumber(asObject(centre).lat),
      lon: finiteNumber(asObject(centre).lon),
    })),
  }
}

function normaliseWarningRow(raw) {
  const row = asObject(raw)
  return {
    zone_id: text(row.zone_id, ''),
    zone_name: text(row.zone_name, 'Zone unavailable'),
    lat: finiteNumber(row.lat),
    lon: finiteNumber(row.lon),
    issued_at: text(row.issued_at, ''),
    target_date: text(row.target_date, ''),
    target_day_label: text(row.target_day_label, ''),
    lead_days: finiteNumber(row.lead_days),
    lead_hours: finiteNumber(row.lead_hours),
    tmax_c: finiteNumber(row.tmax_c),
    normal_tmax_c: finiteNumber(row.normal_tmax_c),
    departure_c: finiteNumber(row.departure_c),
    heatwave_candidate: row.heatwave_candidate === true,
    is_heatwave_episode: row.is_heatwave_episode === true,
    is_severe_episode: row.is_severe_episode === true,
    episode_day: finiteNumber(row.episode_day),
    episode_length: finiteNumber(row.episode_length),
    heatwave_label: text(row.heatwave_label, 'None'),
    hi_peak_c: finiteNumber(row.hi_peak_c),
    wbgt_est_peak_c: finiteNumber(row.wbgt_est_peak_c),
    wbgt_peak_quality: text(row.wbgt_peak_quality, 'unavailable'),
    wbgt_peak_inputs: text(row.wbgt_peak_inputs, ''),
    htsi_score: finiteNumber(row.htsi_score),
    htsi_band: text(row.htsi_band, 'Unavailable'),
    thermal_stress_level: text(row.thermal_stress_level, 'Unavailable'),
    vulnerability_score: finiteNumber(row.vulnerability_score),
    vulnerability_level: text(row.vulnerability_level, 'Unavailable'),
    vulnerability_source: text(row.vulnerability_source, 'unavailable'),
    health_impact_index: finiteNumber(row.health_impact_index),
    health_impact_band: text(row.health_impact_band, 'Unavailable'),
    health_impact_status: text(row.health_impact_status, 'parameterised_health_risk_indicator'),
    health_impact_status_meaning: text(row.health_impact_status_meaning, ''),
    aqi_peak: finiteNumber(row.aqi_peak),
    aqi_band: text(row.aqi_band, 'Unknown'),
    heat_aqi_load_peak: finiteNumber(row.heat_aqi_load_peak),
    heat_aqi_load_band: text(row.heat_aqi_load_band, 'Unknown'),
    alert_level: text(row.alert_level, 'routine'),
    recommended_action_level: text(row.recommended_action_level, 'routine'),
    reason: text(row.reason, ''),
    action_summary: text(row.action_summary, ''),
    data_source: text(row.data_source, ''),
    quality_state: text(row.quality_state, 'unknown'),
    confidence: text(row.confidence, ''),
  }
}

function normaliseHourRow(raw) {
  const row = asObject(raw)
  return {
    zone_id: text(row.zone_id, ''),
    timestamp_local: text(row.timestamp_local, ''),
    temp_c: finiteNumber(row.temp_c),
    rh_pct: finiteNumber(row.rh_pct),
    wind_kmh: finiteNumber(row.wind_kmh),
    solar_wm2: finiteNumber(row.solar_wm2),
    precip_mm: finiteNumber(row.precip_mm),
    pm25_ugm3: finiteNumber(row.pm25_ugm3),
    aqi_india: finiteNumber(row.aqi_india),
    heat_aqi_load: finiteNumber(row.heat_aqi_load),
    wet_bulb_c: finiteNumber(row.wet_bulb_c),
    globe_c: finiteNumber(row.globe_c),
    heat_index_c: finiteNumber(row.heat_index_c),
    wbgt_est_c: finiteNumber(row.wbgt_est_c),
    wbgt_quality: text(row.wbgt_quality, 'unavailable'),
    htsi_score: finiteNumber(row.htsi_score),
    htsi_band: text(row.htsi_band, 'Unavailable'),
  }
}

function normalisePreview(raw) {
  const preview = asObject(raw)
  return {
    preview_id: text(preview.preview_id, ''),
    template: text(preview.template, ''),
    audience: text(preview.audience, ''),
    audience_label: text(preview.audience_label, 'Audience'),
    channel: text(preview.channel, 'sms'),
    zone_id: text(preview.zone_id, ''),
    zone_name: text(preview.zone_name, 'Zone unavailable'),
    severity: text(preview.severity, 'watch'),
    severity_label: text(preview.severity_label, 'WATCH'),
    target_date: text(preview.target_date, ''),
    target_day_label: text(preview.target_day_label, ''),
    lead_days: finiteNumber(preview.lead_days),
    lead_hours: finiteNumber(preview.lead_hours),
    reason: text(preview.reason, ''),
    recommended_action: text(preview.recommended_action, ''),
    data_quality_state: text(preview.data_quality_state, 'unknown'),
    message: text(preview.message, ''),
    message_chars: finiteNumber(preview.message_chars),
    status: text(preview.status, 'preview'),
    dry_run: preview.dry_run !== false,
    live_send: text(preview.live_send, ''),
    demo_disclaimer: text(preview.demo_disclaimer, ''),
  }
}

export function normaliseDemoPayload(raw) {
  const bundle = asObject(raw)
  const scenariosEnvelope = asObject(bundle.scenarios)
  const zonesEnvelope = asObject(bundle.zones)
  const forecastEnvelope = asObject(bundle.forecast)
  const thermalEnvelope = asObject(bundle.thermal)
  const warningsEnvelope = asObject(bundle.warnings)
  const notificationsEnvelope = asObject(bundle.notifications)

  const scenarioList = asArray(scenariosEnvelope.scenarios).map(normaliseScenarioMeta).filter((entry) => entry.id)
  const selectedScenario = normaliseScenarioMeta(warningsEnvelope.scenario || forecastEnvelope.scenario || {})
  const zones = asArray(zonesEnvelope.data).map(normaliseZone).filter((zone) => zone.zone_id)
  const warningsRows = asArray(warningsEnvelope.data).map(normaliseWarningRow).filter((row) => row.zone_id)
  const previews = asArray(notificationsEnvelope.previews).map(normalisePreview).filter((preview) => preview.preview_id)

  return {
    disclaimer: text(scenariosEnvelope.demo_disclaimer, DEMO_DISCLAIMER),
    is_demo: scenariosEnvelope.is_demo !== false,
    scenarios: {
      list: scenarioList,
      how_to_read: text(scenariosEnvelope.how_to_read, ''),
      issued_at_local: text(scenariosEnvelope.issued_at_local, ''),
      lead_days_available: asArray(scenariosEnvelope.lead_days_available).map(finiteNumber).filter((v) => v !== null),
      band_vocabulary: asArray(scenariosEnvelope.band_vocabulary).map((entry) => ({
        band: text(asObject(entry).band, ''),
        colour: text(asObject(entry).colour, '#8b949e'),
        meaning: text(asObject(entry).meaning, ''),
      })),
    },
    scenario: selectedScenario,
    zones,
    zonesVulnerabilityFormula: text(zonesEnvelope.vulnerability_formula, ''),
    zonesVulnerabilitySource: text(zonesEnvelope.vulnerability_source, ''),
    zonesGranularityNote: text(zonesEnvelope.granularity_note, ''),
    zonesCoolingNote: text(zonesEnvelope.cooling_centre_note, ''),
    forecast: {
      daily: asArray(forecastEnvelope.daily).map((row) => ({
        zone_id: text(asObject(row).zone_id, ''),
        zone_name: text(asObject(row).zone_name, ''),
        date: text(asObject(row).date, ''),
        target_day_label: text(asObject(row).target_day_label, ''),
        lead_days: finiteNumber(asObject(row).lead_days),
        tmax_c: finiteNumber(asObject(row).tmax_c),
        tmin_c: finiteNumber(asObject(row).tmin_c),
        rh_min_pct: finiteNumber(asObject(row).rh_min_pct),
        wind_mean_kmh: finiteNumber(asObject(row).wind_mean_kmh),
        solar_max_wm2: finiteNumber(asObject(row).solar_max_wm2),
        precip_mm: finiteNumber(asObject(row).precip_mm),
        pm25_mean_ugm3: finiteNumber(asObject(row).pm25_mean_ugm3),
        aqi_peak: finiteNumber(asObject(row).aqi_peak),
        aqi_band: text(asObject(row).aqi_band, 'Unknown'),
        heat_aqi_load_peak: finiteNumber(asObject(row).heat_aqi_load_peak),
        heat_aqi_load_band: text(asObject(row).heat_aqi_load_band, 'Unknown'),
        normal_tmax_c: finiteNumber(asObject(row).normal_tmax_c),
        departure_c: finiteNumber(asObject(row).departure_c),
      })).filter((row) => row.zone_id),
      hourly: asArray(forecastEnvelope.hourly).map(normaliseHourRow).filter((row) => row.zone_id),
      hourly_scope: text(forecastEnvelope.hourly_scope, ''),
    },
    thermal: {
      method: asObject(thermalEnvelope.method),
      wbgt_statement: text(thermalEnvelope.wbgt_statement, ''),
      hourly: asArray(thermalEnvelope.hourly).map(normaliseHourRow).filter((row) => row.zone_id),
    },
    warnings: {
      issued_at: text(warningsEnvelope.issued_at, ''),
      issued_at_utc: text(warningsEnvelope.issued_at_utc, ''),
      climatology: asObject(warningsEnvelope.climatology),
      persistence_rule: text(warningsEnvelope.persistence_rule, ''),
      granularity_note: text(warningsEnvelope.granularity_note, ''),
      action_matrix: asObject(warningsEnvelope.action_matrix),
      alert_levels: asArray(warningsEnvelope.alert_levels).map((entry) => ({
        level: text(asObject(entry).level, ''),
        colour: text(asObject(entry).colour, '#8b949e'),
        summary: text(asObject(entry).summary, ''),
      })),
      lead_day_counts: asObject(warningsEnvelope.lead_day_counts),
      alert_level_counts: asObject(warningsEnvelope.alert_level_counts),
      rows: warningsRows,
    },
    notifications: {
      rows: finiteNumber(notificationsEnvelope.rows),
      dry_run: notificationsEnvelope.dry_run !== false,
      dispatch_policy: asObject(notificationsEnvelope.dispatch_policy),
      audiences: asArray(notificationsEnvelope.audiences).map((entry) => ({
        id: text(asObject(entry).id, ''),
        label: text(asObject(entry).label, 'Audience'),
        focus: text(asObject(entry).focus, ''),
        channels: asArray(asObject(entry).channels).map((channel) => text(channel, '')),
      })),
      previews,
    },
  }
}

/* Convenience aliases used by screens + render contract paths. */
export function warningsRowsOf(payload) {
  return payload?.warnings?.rows || []
}

export const EMPTY_DEMO_PAYLOAD = normaliseDemoPayload({
  scenarios: { demo_disclaimer: DEMO_DISCLAIMER, scenarios: [] },
  zones: { data: [] },
  forecast: { daily: [], hourly: [] },
  thermal: { method: {}, hourly: [] },
  warnings: { data: [], scenario: { id: '', label: 'No scenario loaded' } },
  notifications: { previews: [], rows: 0, dry_run: true },
})

/* ------------------------------------------------------- presentational maps */

export const BAND_COLOURS = {
  Normal: '#3fb950',
  Watch: '#e3b341',
  Warning: '#f0883e',
  Severe: '#f85149',
  Unavailable: '#8b949e',
}

export const LEVEL_COLOURS = {
  routine: '#3fb950',
  watch: '#e3b341',
  warning: '#f0883e',
  severe: '#f85149',
}

export const LEVEL_LABELS = {
  routine: 'Routine',
  watch: 'Watch',
  warning: 'Warning',
  severe: 'Severe',
}

export function bandColour(band) {
  return BAND_COLOURS[band] || BAND_COLOURS.Unavailable
}

export function levelColour(level) {
  return LEVEL_COLOURS[level] || LEVEL_COLOURS.routine
}

export function levelLabel(level) {
  return LEVEL_LABELS[level] || level || 'routine'
}
