import React from 'react'
import {
  ALERT_LEVEL_ORDER,
  DEMO_DISCLAIMER,
  bandColour,
  formatDate,
  formatHour,
  formatNumber,
  formatTemp,
  levelColour,
  levelLabel,
  text,
} from './contract.js'

const h = React.createElement

/* --------------------------------------------------------------- fragments */

function demoBanner(payload, key = 'demo-banner') {
  // The banner renders the PAYLOAD's own disclaimer: demo envelopes carry the
  // canonical demo string; the live Delhi-NCR ops view reuses these screens
  // with an honest live/practice label instead.
  return h('p', { className: 'demo-disclaimer', role: 'status', key }, text(payload?.disclaimer, DEMO_DISCLAIMER))
}

function chip(label, colour, extraClass = '') {
  return h('span', {
    className: `demo-chip ${extraClass}`.trim(),
    style: { borderColor: colour, color: colour },
    key: `chip-${label}`,
  }, [
    h('span', { className: 'demo-chip__dot', style: { background: colour }, 'aria-hidden': 'true', key: 'dot' }),
    label,
  ])
}

function levelChip(level) {
  return chip(levelLabel(level), levelColour(level), 'demo-chip--level')
}

function bandChip(band) {
  return chip(band || 'Unavailable', bandColour(band))
}

function metric(label, value, unit = '', hint = '') {
  return h('div', { className: 'demo-metric', key: label }, [
    h('span', { className: 'demo-metric__label', key: 'label' }, label),
    h('strong', { className: 'demo-metric__value', key: 'value' }, [
      value, unit ? h('small', { key: 'unit' }, unit) : null,
    ]),
    hint ? h('span', { className: 'demo-metric__hint', key: 'hint' }, hint) : null,
  ])
}

function sectionTitle(id, title, note) {
  return h('div', { className: 'demo-section-head', key: 'head' }, [
    h('h2', { id, key: 'title' }, title),
    note ? h('p', { className: 'demo-note', key: 'note' }, note) : null,
  ])
}

function zoneRows(payload) {
  return payload.warnings.rows
}

function pickZone(payload, selectedZoneId) {
  const zones = payload.zones
  return zones.find((zone) => zone.zone_id === selectedZoneId) || zones[0] || null
}

function pickRow(payload, selectedZoneId, leadDay) {
  const zone = pickZone(payload, selectedZoneId)
  const zoneId = zone ? zone.zone_id : selectedZoneId
  const rows = zoneRows(payload).filter((row) => !zoneId || row.zone_id === zoneId)
  if (!rows.length) return null
  if (leadDay !== null && leadDay !== undefined) {
    const exact = rows.find((row) => row.lead_days === leadDay)
    if (exact) return exact
  }
  return rows.reduce((worst, row) => (
    ALERT_LEVEL_ORDER.indexOf(row.alert_level) > ALERT_LEVEL_ORDER.indexOf(worst.alert_level) ? row : worst
  ), rows[0])
}

function hourlyForZone(payload, zoneId, source) {
  const rows = source === 'thermal' ? payload.thermal.hourly : payload.forecast.hourly
  return rows.filter((row) => !zoneId || row.zone_id === zoneId)
}

/* --------------------------------------------------------------- Now screen */

const NOW_HOURS = ['06:00', '09:00', '12:00', '15:00', '18:00', '21:00']

function NowScreen({ payload, selectedZoneId }) {
  const zone = pickZone(payload, selectedZoneId)
  const row = pickRow(payload, selectedZoneId, 0)
  const thermalHours = hourlyForZone(payload, zone ? zone.zone_id : '', 'thermal')
  const forecastHours = hourlyForZone(payload, zone ? zone.zone_id : '', 'forecast')
  const atIssue = (rows) => rows.find((entry) => entry.timestamp_local.endsWith('T06:00')) || rows[0] || null
  const currentThermal = atIssue(thermalHours)
  const currentWeather = atIssue(forecastHours)

  if (!zone || !row) {
    return h('section', { className: 'demo-screen', 'aria-labelledby': 'demo-now-title' }, [
      h('p', { className: 'demo-kicker', key: 'kicker' }, 'HEAT RISK DEMO · NOW'),
      h('h1', { id: 'demo-now-title', key: 'title' }, 'No scenario loaded'),
      h('p', { className: 'demo-empty', key: 'empty' }, 'Pick a scenario above to see current synthetic conditions, the 3–5 day outlook, impact indicators and alert previews.'),
      demoBanner(payload),
    ])
  }

  const tableRows = NOW_HOURS
    .map((hour) => thermalHours.find((entry) => entry.timestamp_local.includes(`T${hour}`)))
    .filter((entry) => entry)

  return h('section', { className: 'demo-screen', 'aria-labelledby': 'demo-now-title' }, [
    h('p', { className: 'demo-kicker', key: 'kicker' }, 'HEAT RISK DEMO · CURRENT CONDITIONS'),
    h('h1', { id: 'demo-now-title', key: 'title' }, `${zone.zone_name} — Day +0`),
    h('p', { className: 'demo-note', key: 'issued' }, [
      'Scenario issued ', h('strong', { key: 'at' }, text(payload.warnings.issued_at, payload.scenario.issued_at_local)),
      ' IST · fixed demo clock · ', text(payload.scenario.label, ''),
    ]),
    h('div', { className: 'demo-chip-row', key: 'chips' }, [
      levelChip(row.alert_level), bandChip(row.htsi_band),
      row.heatwave_label !== 'None' ? chip(row.heatwave_label, '#f0883e') : null,
    ]),
    h('div', { className: 'demo-metric-grid', key: 'metrics' }, [
      metric('Temperature', formatTemp(currentWeather ? currentWeather.temp_c : row.tmax_c), '', 'at 06:00 issue time'),
      metric('Humidity', currentWeather ? formatNumber(currentWeather.rh_pct, 0) : '—', ' %', 'relative'),
      metric('Wind', currentWeather ? formatNumber(currentWeather.wind_kmh, 1) : '—', ' km/h', '10 m'),
      metric('Solar radiation', currentWeather ? formatNumber(currentWeather.solar_wm2, 0) : '—', ' W/m²', 'shortwave'),
      metric('Estimated WBGT', currentThermal ? formatTemp(currentThermal.wbgt_est_c) : '—', '', currentThermal ? `quality: ${currentThermal.wbgt_quality}` : ''),
      metric('Heat Index', currentThermal ? formatTemp(currentThermal.heat_index_c) : '—', '', 'NWS, shade-assumed'),
      metric('Day peak Tmax', formatTemp(row.tmax_c), '', `normal ${formatTemp(row.normal_tmax_c)}`),
      metric('PM2.5 peak', formatNumber(row.aqi_peak === null ? null : row.aqi_peak, 0), '', `AQI band ${row.aqi_band}`),
    ]),
    tableRows.length
      ? h('table', { className: 'demo-table', key: 'hours' }, [
          h('caption', { key: 'caption' }, `Issue-day hourly detail — ${zone.zone_name} (synthetic)`),
          h('thead', { key: 'thead' }, h('tr', { key: 'tr' }, [
            h('th', { scope: 'col', key: 't' }, 'Time'),
            h('th', { scope: 'col', key: 'temp' }, 'Temp'),
            h('th', { scope: 'col', key: 'rh' }, 'RH'),
            h('th', { scope: 'col', key: 'wind' }, 'Wind'),
            h('th', { scope: 'col', key: 'solar' }, 'Solar'),
            h('th', { scope: 'col', key: 'wbgt' }, 'WBGT est.'),
            h('th', { scope: 'col', key: 'hi' }, 'Heat Index'),
            h('th', { scope: 'col', key: 'band' }, 'HTSI band'),
          ])),
          h('tbody', { key: 'tbody' }, tableRows.map((entry) => h('tr', { key: entry.timestamp_local }, [
            h('th', { scope: 'row', key: 't' }, formatHour(entry.timestamp_local)),
            h('td', { key: 'temp' }, formatTemp(entry.temp_c)),
            h('td', { key: 'rh' }, `${formatNumber(entry.rh_pct, 0)} %`),
            h('td', { key: 'wind' }, `${formatNumber(entry.wind_kmh, 1)} km/h`),
            h('td', { key: 'solar' }, `${formatNumber(entry.solar_wm2, 0)} W/m²`),
            h('td', { key: 'wbgt' }, formatTemp(entry.wbgt_est_c)),
            h('td', { key: 'hi' }, formatTemp(entry.heat_index_c)),
            h('td', { key: 'band' }, bandChip(entry.htsi_band)),
          ]))),
        ])
      : h('p', { className: 'demo-empty', key: 'no-hours' }, 'Hourly issue-day detail is unavailable in this payload.'),
    h('p', { className: 'demo-note', key: 'reason' }, [h('strong', { key: 'w' }, 'Why this level: '), row.reason]),
    demoBanner(payload),
  ])
}

/* ----------------------------------------------------------- Outlook screen */

function OutlookScreen({ payload, selectedZoneId }) {
  const zone = pickZone(payload, selectedZoneId)
  const rows = zoneRows(payload).filter((row) => !zone || row.zone_id === zone.zone_id)
  const outlook = rows.filter((row) => row.lead_days >= 1).slice(0, 5)
  const referencePeriod = text(payload.warnings.climatology.reference_period, 'fixed historical')

  const worstByLead = [3, 4, 5].map((lead) => {
    const dayRows = zoneRows(payload).filter((row) => row.lead_days === lead)
    if (!dayRows.length) return null
    return dayRows.reduce((worst, row) => (
      ALERT_LEVEL_ORDER.indexOf(row.alert_level) > ALERT_LEVEL_ORDER.indexOf(worst.alert_level)
        || (row.alert_level === worst.alert_level
            && (row.health_impact_index || 0) > (worst.health_impact_index || 0))
        ? row : worst
    ), dayRows[0])
  }).filter((row) => row)

  return h('section', { className: 'demo-screen', 'aria-labelledby': 'demo-outlook-title' }, [
    h('p', { className: 'demo-kicker', key: 'kicker' }, 'HEAT RISK DEMO · 3–5 DAY EARLY WARNING'),
    h('h1', { id: 'demo-outlook-title', key: 'title' }, zone ? `Outlook — ${zone.zone_name}` : '5-day outlook'),
    h('p', { className: 'demo-note', key: 'normal-note' }, `Departures compare with the fixed ${referencePeriod} climate normal — never a forecast-window average.`),
    worstByLead.length
      ? h('div', { className: 'demo-lead-grid', key: 'leads' }, worstByLead.map((row) => h('article', {
          className: 'demo-lead-card', key: `lead-${row.lead_days}`,
          style: { borderColor: levelColour(row.alert_level) },
        }, [
          h('p', { className: 'demo-lead-card__day', key: 'day' }, row.target_day_label || `Day +${row.lead_days}`),
          h('p', { className: 'demo-lead-card__date', key: 'date' }, formatDate(row.target_date)),
          levelChip(row.alert_level),
          h('p', { className: 'demo-lead-card__zone', key: 'zone' }, row.zone_name),
          h('p', { className: 'demo-lead-card__metric', key: 'metric' }, `Tmax ${formatTemp(row.tmax_c)} · WBGT est. ${formatTemp(row.wbgt_est_peak_c)} · HTSI ${formatNumber(row.htsi_score, 0)}`),
          h('p', { className: 'demo-lead-card__lead', key: 'lead' }, `Lead ${formatNumber(row.lead_days, 0)} days (${formatNumber(row.lead_hours, 0)} h to peak)`),
          h('p', { className: 'demo-lead-card__hw', key: 'hw' }, row.is_heatwave_episode
            ? `${row.heatwave_label} · day ${formatNumber(row.episode_day, 0)}/${formatNumber(row.episode_length, 0)}`
            : `Heatwave status: ${row.heatwave_label}`),
        ])))
      : null,
    outlook.length
      ? h('table', { className: 'demo-table', key: 'table' }, [
          h('caption', { key: 'caption' }, zone ? `Day-by-day warning rows for ${zone.zone_name}` : 'Day-by-day warning rows'),
          h('thead', { key: 'thead' }, h('tr', { key: 'tr' }, [
            h('th', { scope: 'col', key: 'lead' }, 'Lead'),
            h('th', { scope: 'col', key: 'date' }, 'Target date'),
            h('th', { scope: 'col', key: 'tmax' }, 'Tmax'),
            h('th', { scope: 'col', key: 'normal' }, 'Normal'),
            h('th', { scope: 'col', key: 'dep' }, 'Departure'),
            h('th', { scope: 'col', key: 'wbgt' }, 'WBGT est.'),
            h('th', { scope: 'col', key: 'hi' }, 'Heat Index'),
            h('th', { scope: 'col', key: 'htsi' }, 'HTSI'),
            h('th', { scope: 'col', key: 'hw' }, 'Heatwave'),
            h('th', { scope: 'col', key: 'level' }, 'Action level'),
          ])),
          h('tbody', { key: 'tbody' }, outlook.map((row) => h('tr', { key: `${row.zone_id}-${row.target_date}` }, [
            h('th', { scope: 'row', key: 'lead' }, `${row.target_day_label} · ${formatNumber(row.lead_hours, 0)} h`),
            h('td', { key: 'date' }, formatDate(row.target_date)),
            h('td', { key: 'tmax' }, formatTemp(row.tmax_c)),
            h('td', { key: 'normal' }, formatTemp(row.normal_tmax_c)),
            h('td', { key: 'dep' }, row.departure_c === null ? '—' : `${row.departure_c > 0 ? '+' : ''}${formatNumber(row.departure_c, 1)} °C`),
            h('td', { key: 'wbgt' }, formatTemp(row.wbgt_est_peak_c)),
            h('td', { key: 'hi' }, formatTemp(row.hi_peak_c)),
            h('td', { key: 'htsi' }, `${formatNumber(row.htsi_score, 0)} ${row.htsi_band}`),
            h('td', { key: 'hw' }, row.heatwave_label),
            h('td', { key: 'level' }, levelChip(row.alert_level)),
          ]))),
        ])
      : h('p', { className: 'demo-empty', key: 'empty' }, 'No outlook rows are available for this scenario.'),
    h('p', { className: 'demo-note', key: 'persistence' }, text(payload.warnings.persistence_rule, '')),
    demoBanner(payload),
  ])
}

/* ------------------------------------------------------------ Zones screen */

function ZonesScreen({ payload, selectedZoneId, leadDay = 3 }) {
  const rows = zoneRows(payload).filter((row) => row.lead_days === leadDay)
  const zoneInfo = new Map(payload.zones.map((zone) => [zone.zone_id, zone]))

  return h('section', { className: 'demo-screen', 'aria-labelledby': 'demo-zones-title' }, [
    h('p', { className: 'demo-kicker', key: 'kicker' }, 'HEAT RISK DEMO · ALL ZONES'),
    h('h1', { id: 'demo-zones-title', key: 'title' }, `Zone table — Day +${leadDay}`),
    h('p', { className: 'demo-note', key: 'map-note' }, 'This table is the accessible alternative to the colour-coded map — the same data, in words and numbers.'),
    h('ul', { className: 'demo-legend', key: 'legend', 'aria-label': 'Legend' }, [
      ['Normal', 'Watch', 'Warning', 'Severe'].map((band) => h('li', { key: band }, [
        h('span', { className: 'demo-legend__swatch', style: { background: bandColour(band) }, 'aria-hidden': 'true', key: 'sw' }),
        `${band}`,
      ])),
    ][0]),
    rows.length
      ? h('table', { className: 'demo-table', key: 'table' }, [
          h('caption', { key: 'caption' }, `All demo zones for Day +${leadDay} (synthetic scenario data)`),
          h('thead', { key: 'thead' }, h('tr', { key: 'tr' }, [
            h('th', { scope: 'col', key: 'zone' }, 'Zone'),
            h('th', { scope: 'col', key: 'level' }, 'Action level'),
            h('th', { scope: 'col', key: 'band' }, 'Thermal band'),
            h('th', { scope: 'col', key: 'tmax' }, 'Tmax'),
            h('th', { scope: 'col', key: 'wbgt' }, 'WBGT est.'),
            h('th', { scope: 'col', key: 'vuln' }, 'Vulnerability'),
            h('th', { scope: 'col', key: 'impact' }, 'Health impact'),
            h('th', { scope: 'col', key: 'cooling' }, 'Cooling centres'),
            h('th', { scope: 'col', key: 'hw' }, 'Heatwave'),
          ])),
          h('tbody', { key: 'tbody' }, rows.map((row) => {
            const info = zoneInfo.get(row.zone_id)
            return h('tr', {
              key: row.zone_id,
              className: row.zone_id === selectedZoneId ? 'is-selected' : '',
            }, [
              h('th', { scope: 'row', key: 'zone' }, row.zone_name),
              h('td', { key: 'level' }, levelChip(row.alert_level)),
              h('td', { key: 'band' }, bandChip(row.htsi_band)),
              h('td', { key: 'tmax' }, formatTemp(row.tmax_c)),
              h('td', { key: 'wbgt' }, formatTemp(row.wbgt_est_peak_c)),
              h('td', { key: 'vuln' }, `${formatNumber(row.vulnerability_score, 0)} · ${row.vulnerability_level}`),
              h('td', { key: 'impact' }, `${row.health_impact_band} (${formatNumber(row.health_impact_index, 0)})`),
              h('td', { key: 'cooling' }, info ? formatNumber(info.cooling_centre_count, 0) : '—'),
              h('td', { key: 'hw' }, row.heatwave_label),
            ])
          })),
        ])
      : h('p', { className: 'demo-empty', key: 'empty' }, `No zone rows for Day +${leadDay} in this scenario.`),
    h('p', { className: 'demo-note', key: 'granularity' }, text(payload.warnings.granularity_note, payload.zonesGranularityNote)),
    demoBanner(payload),
  ])
}

/* ------------------------------------------------------------ Impact screen */

function ImpactScreen({ payload, selectedZoneId, leadDay = 3 }) {
  const zone = pickZone(payload, selectedZoneId)
  const row = pickRow(payload, selectedZoneId, leadDay)
  if (!zone || !row) {
    return h('section', { className: 'demo-screen', 'aria-labelledby': 'demo-impact-title' }, [
      h('p', { className: 'demo-kicker', key: 'kicker' }, 'HEAT RISK DEMO · IMPACT'),
      h('h1', { id: 'demo-impact-title', key: 'title' }, 'No zone selected'),
      h('p', { className: 'demo-empty', key: 'empty' }, 'Select a scenario and zone to see the stress, vulnerability and impact breakdown.'),
      demoBanner(payload),
    ])
  }

  const actions = payload.warnings.action_matrix[row.recommended_action_level] || {}
  const municipal = Array.isArray(actions.municipal_actions) ? actions.municipal_actions : []
  const advice = Array.isArray(actions.resident_advice) ? actions.resident_advice : []
  const statusIsDemo = row.health_impact_status === 'synthetic_demo'

  return h('section', { className: 'demo-screen', 'aria-labelledby': 'demo-impact-title' }, [
    h('p', { className: 'demo-kicker', key: 'kicker' }, 'HEAT RISK DEMO · IMPACT BREAKDOWN'),
    h('h1', { id: 'demo-impact-title', key: 'title' }, `${zone.zone_name} — ${row.target_day_label || `Day +${row.lead_days}`}`),
    h('p', { className: 'demo-note', key: 'date' }, `${formatDate(row.target_date)} · lead ${formatNumber(row.lead_days, 0)} days (${formatNumber(row.lead_hours, 0)} h to peak)`),

    sectionTitle('demo-impact-htsi', '1 · Meteorological thermal stress (HTSI)', 'Weather only — no demographics in this score.'),
    h('div', { className: 'demo-metric-grid', key: 'htsi-metrics' }, [
      metric('HTSI score', formatNumber(row.htsi_score, 0), ' /100', row.htsi_band),
      metric('Estimated WBGT', formatTemp(row.wbgt_est_peak_c), '', `quality: ${row.wbgt_peak_quality}`),
      metric('Heat Index peak', formatTemp(row.hi_peak_c), '', 'shade-assumed'),
      metric('Tmax departure', row.departure_c === null ? '—' : `${row.departure_c > 0 ? '+' : ''}${formatNumber(row.departure_c, 1)} °C`, '', `vs ${formatTemp(row.normal_tmax_c)} normal`),
    ]),
    h('p', { className: 'demo-note', key: 'inputs' }, `WBGT inputs available: ${text(row.wbgt_peak_inputs, 'none listed')} — an estimated WBGT from model inputs, never a measured globe reading.`),
    h('p', { className: 'demo-note', key: 'wbgt-statement' }, text(payload.thermal.wbgt_statement, '')),

    sectionTitle('demo-impact-vuln', '2 · Vulnerability (kept separate from weather)', zone.vulnerability_source),
    h('div', { className: 'demo-metric-grid', key: 'vuln-metrics' }, [
      metric('Vulnerability score', formatNumber(zone.vulnerability_score, 0), ' /100', zone.vulnerability_level),
      metric('Population', zone.population === null ? '—' : new Intl.NumberFormat('en-IN').format(zone.population), '', 'synthetic profile'),
      metric('Elderly share', formatNumber(zone.elderly_pct, 1), ' %', 'synthetic profile'),
      metric('Outdoor workers', formatNumber(zone.outdoor_worker_pct, 0), ' %', 'synthetic profile'),
      metric('Cooling access', formatNumber(zone.cooling_access_score, 0), ' /100', `${formatNumber(zone.cooling_centre_count, 0)} centres (demo placeholders)`),
      metric('Illiteracy share', formatNumber(zone.illiteracy_pct, 0), ' %', 'deprivation proxy'),
    ]),

    sectionTitle('demo-impact-health', '3 · Health-impact / mortality-risk indicator', 'Parameterised — not a body count.'),
    h('div', { className: 'demo-chip-row', key: 'impact-chips' }, [
      chip(row.health_impact_band, levelColour(row.alert_level)),
      chip(row.health_impact_status, statusIsDemo ? '#a371f7' : '#58a6ff'),
      h('span', { className: 'demo-metric__value', key: 'index' }, `${formatNumber(row.health_impact_index, 0)}/100`),
    ]),
    h('p', { className: 'demo-note', key: 'impact-meaning' }, text(row.health_impact_status_meaning, '')),
    h('p', { className: 'demo-warning', key: 'impact-boundary' }, statusIsDemo
      ? 'This is a synthetic_demo indicator: it shows how the finished product will phrase heat-health pressure. It is NOT a validated mortality forecast, and no death or admission counts are predicted here.'
      : 'Parameterised indicator — not a validated mortality or hospitalisation forecast.'),

    sectionTitle('demo-impact-actions', `4 · Recommended action — ${levelLabel(row.recommended_action_level)} level`, text(row.action_summary, '')),
    municipal.length
      ? h('div', { className: 'demo-action-columns', key: 'actions' }, [
          h('div', { key: 'municipal' }, [
            h('h3', { key: 'h' }, 'Municipal / public-health actions'),
            h('ul', { className: 'demo-action-list', key: 'list' }, municipal.map((action) => h('li', { key: action }, action))),
          ]),
          h('div', { key: 'resident' }, [
            h('h3', { key: 'h' }, 'Resident safety advice'),
            h('ul', { className: 'demo-action-list', key: 'list' }, advice.map((item) => h('li', { key: item }, item))),
          ]),
        ])
      : h('p', { className: 'demo-empty', key: 'no-actions' }, 'No action matrix entry for this level.'),
    demoBanner(payload),
  ])
}

/* ------------------------------------------------------------ Notify screen */

function NotifyScreen({ payload, selectedZoneId }) {
  const notifications = payload.notifications
  const allPreviews = notifications.previews
  const zone = pickZone(payload, selectedZoneId)
  const previews = (zone ? allPreviews.filter((preview) => preview.zone_id === zone.zone_id) : allPreviews)
  const shown = (previews.length ? previews : allPreviews).slice(0, 8)
  const policy = notifications.dispatch_policy

  return h('section', { className: 'demo-screen', 'aria-labelledby': 'demo-notify-title' }, [
    h('p', { className: 'demo-kicker', key: 'kicker' }, 'HEAT RISK DEMO · NOTIFICATIONS'),
    h('h1', { id: 'demo-notify-title', key: 'title' }, 'Notification previews — dry run'),
    h('p', { className: 'demo-note', key: 'policy' }, [
      text(policy.default, 'dry run by default'), ' · ', text(policy.demo_guard, ''),
    ]),
    h('p', { className: 'demo-note', key: 'locks' }, `Live-send locks: ${(Array.isArray(policy.live_send_locks) ? policy.live_send_locks : []).join(' + ') || 'HS_ALLOW_LIVE_SEND + Twilio credentials'}`),
    shown.length
      ? h('div', { className: 'demo-preview-grid', key: 'previews' }, shown.map((preview) => h('article', {
          className: 'demo-preview-card', key: preview.preview_id,
          'aria-label': `${preview.audience_label} ${preview.channel} preview for ${preview.zone_name}`,
        }, [
          h('header', { className: 'demo-preview-card__head', key: 'head' }, [
            levelChip(preview.severity),
            h('span', { className: 'demo-preview-card__channel', key: 'channel' }, preview.channel.toUpperCase()),
            h('span', { className: 'demo-preview-card__dry', key: 'dry' }, preview.status === 'preview' ? 'PREVIEW · DRY RUN' : preview.status),
          ]),
          h('h2', { className: 'demo-preview-card__audience', key: 'audience' }, preview.audience_label),
          h('p', { className: 'demo-preview-card__meta', key: 'meta' }, [
            `${preview.zone_name} · ${formatDate(preview.target_date)} (${preview.target_day_label})`,
            h('br', { key: 'br' }),
            `Lead ${formatNumber(preview.lead_days, 0)} days / ${formatNumber(preview.lead_hours, 0)} h · quality: ${preview.data_quality_state}`,
          ]),
          h('p', { className: 'demo-preview-card__reason', key: 'reason' }, preview.reason),
          h('p', { className: 'demo-preview-card__action', key: 'action' }, [h('strong', { key: 's' }, 'Action: '), preview.recommended_action]),
          h('pre', { className: 'demo-preview-card__message', key: 'message' }, preview.message),
          h('p', { className: 'demo-note', key: 'lock-note' }, preview.live_send),
        ])))
      : h('p', { className: 'demo-empty', key: 'empty' }, 'No alert in this scenario is severe enough to plan a notification. Try “Dry extreme heatwave” or “Severe heat + pollution”.'),
    demoBanner(payload),
  ])
}

/* ------------------------------------------------------------- About screen */

function AboutScreen({ payload }) {
  const scenario = payload.scenario
  const climatology = payload.warnings.climatology
  const method = payload.thermal.method || {}
  return h('section', { className: 'demo-screen', 'aria-labelledby': 'demo-about-title' }, [
    h('p', { className: 'demo-kicker', key: 'kicker' }, 'HEAT RISK DEMO · METHOD & LIMITS'),
    h('h1', { id: 'demo-about-title', key: 'title' }, 'What is real, what is synthetic, what is assumed'),
    h('dl', { className: 'demo-facts', key: 'facts' }, [
      h('div', { key: 'scenario' }, [
        h('dt', { key: 't' }, 'Scenario'),
        h('dd', { key: 'd' }, `${text(scenario.label, 'none loaded')} — ${text(scenario.summary, '')}`),
      ]),
      h('div', { key: 'clock' }, [
        h('dt', { key: 't' }, 'Fixed clock'),
        h('dd', { key: 'd' }, text(scenario.issued_at_note, 'The demo clock never moves.')),
      ]),
      h('div', { key: 'normals' }, [
        h('dt', { key: 't' }, 'Climate normals'),
        h('dd', { key: 'd' }, `Real fixed ${text(climatology.reference_period, '1991–2020')} Tmax normals — never replaced by forecast-window averages.`),
      ]),
      h('div', { key: 'htsi' }, [
        h('dt', { key: 't' }, 'HTSI'),
        h('dd', { key: 'd' }, text(method.score_formula, 'Documented in /demo/thermal method metadata.')),
      ]),
      h('div', { key: 'separation' }, [
        h('dt', { key: 't' }, 'Separation rule'),
        h('dd', { key: 'd' }, text(method.separation_rule, 'Meteorological stress, vulnerability and health impact stay separate.')),
      ]),
      h('div', { key: 'wbgt' }, [
        h('dt', { key: 't' }, 'WBGT'),
        h('dd', { key: 'd' }, text(payload.thermal.wbgt_statement, 'Estimated WBGT — not measured.')),
      ]),
      h('div', { key: 'vuln' }, [
        h('dt', { key: 't' }, 'Vulnerability profile'),
        h('dd', { key: 'd' }, `${text(payload.zonesVulnerabilitySource, 'synthetic')} — ${text(payload.zonesVulnerabilityFormula, '')}`),
      ]),
      h('div', { key: 'impact' }, [
        h('dt', { key: 't' }, 'Health-impact status'),
        h('dd', { key: 'd' }, 'Every demo row is labelled synthetic_demo. Validated mortality forecasting would require observed outcome data (ward-level death/admission counts) plus a committed evaluation report — neither ships in this repo.'),
      ]),
      h('div', { key: 'granularity' }, [
        h('dt', { key: 't' }, 'Granularity'),
        h('dd', { key: 'd' }, text(payload.warnings.granularity_note, 'Zone-level grid values, not street-level observations.')),
      ]),
    ]),
    Array.isArray(scenario.teaching_points) && scenario.teaching_points.length
      ? h('div', { key: 'teaching' }, [
          h('h2', { key: 'h' }, 'What this scenario teaches'),
          h('ul', { className: 'demo-action-list', key: 'list' }, scenario.teaching_points.map((point) => h('li', { key: point }, point))),
        ])
      : null,
    h('p', { className: 'demo-note', key: 'how' }, text(payload.scenarios.how_to_read, '')),
    demoBanner(payload),
  ])
}

/* ------------------------------------------------------------------ router */

export function DemoScreen({ screen = 'now', payload, selectedZoneId = '', leadDay = 3 }) {
  const safe = payload && payload.warnings ? payload : null
  if (!safe) {
    return h('section', { className: 'demo-screen' }, [
      h('h1', { key: 't' }, 'Demo payload unavailable'),
      h('p', { className: 'demo-empty', key: 'e' }, 'Load a scenario to see the demo.'),
      demoBanner(payload),
    ])
  }
  if (screen === 'outlook') return h(OutlookScreen, { payload: safe, selectedZoneId })
  if (screen === 'zones') return h(ZonesScreen, { payload: safe, selectedZoneId, leadDay })
  if (screen === 'impact') return h(ImpactScreen, { payload: safe, selectedZoneId, leadDay })
  if (screen === 'notify') return h(NotifyScreen, { payload: safe, selectedZoneId })
  if (screen === 'about') return h(AboutScreen, { payload: safe })
  return h(NowScreen, { payload: safe, selectedZoneId })
}
