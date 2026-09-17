import React from 'react'
import { formatDate, formatNumber, SCREEN_LABELS, text } from './contract.js'

const h = React.createElement

function metric(label, value, unit = '', tone = '') {
  return h('div', { className: `phone-metric ${tone}`.trim(), key: label }, [
    h('span', { className: 'phone-metric__label', key: 'label' }, label),
    h('strong', { className: 'phone-metric__value', key: 'value' }, [value, unit ? h('small', { key: 'unit' }, unit) : null]),
  ])
}

function sourceBanner(summary, key = 'source') {
  if (summary.is_synthetic) {
    return h('p', { className: 'phone-source phone-source--practice', role: 'status', key },
      'Practice data — not a live forecast. Restore connectivity before acting on it.')
  }
  if (summary.static_snapshot) {
    return h('p', { className: 'phone-source', role: 'status', key },
      'Last exported snapshot. Connect to the live service for a fresh update.')
  }
  return h('p', { className: 'phone-source', role: 'status', key }, `Live source: ${text(summary.data_source, 'unavailable')}`)
}

function zoneOrEmpty(payload, selectedZoneId) {
  return payload.summary.data.find((zone) => zone.zone_id === selectedZoneId) || payload.summary.data[0] || null
}

function HomeScreen({ payload, selectedZoneId }) {
  const zone = zoneOrEmpty(payload, selectedZoneId)
  const city = payload.summary.city
  if (!zone) {
    return h('section', { className: 'phone-screen-content', 'aria-labelledby': 'phone-now-title' }, [
      h('p', { className: 'phone-kicker', key: 'kicker' }, 'HEAT + AIR'),
      h('h1', { id: 'phone-now-title', key: 'title' }, 'No locality selected'),
      h('p', { className: 'phone-empty', key: 'empty' }, 'We could not load a heat and air reading. Try again when a saved snapshot or live service is available.'),
      sourceBanner(payload.summary),
    ])
  }
  return h('section', { className: 'phone-screen-content', 'aria-labelledby': 'phone-now-title' }, [
    h('p', { className: 'phone-kicker', key: 'kicker' }, 'HEAT + AIR · NOW'),
    h('h1', { id: 'phone-now-title', key: 'title' }, zone.zone_name),
    h('p', { className: 'phone-time', key: 'time' }, zone.timestamp_local || city.timestamp_local || 'Update time unavailable'),
    h('div', { className: 'phone-load-card', key: 'load' }, [
      h('span', { className: 'phone-load-card__eyebrow', key: 'eyebrow' }, 'Combined heat + air load'),
      h('strong', { className: 'phone-load-card__value', key: 'value' }, [formatNumber(zone.heat_aqi_load), h('small', { key: 'max' }, ' / 500')]),
      h('span', { className: 'phone-pill', key: 'band' }, zone.heat_aqi_load_band),
    ]),
    h('div', { className: 'phone-metric-grid', key: 'metrics' }, [
      metric('Temperature', formatNumber(zone.temp_c, 1), '°C'),
      metric('AQI', formatNumber(zone.aqi_india), '', 'phone-metric--air'),
      metric('PM2.5', formatNumber(zone.pm25_ugm3, 0), ' µg/m³'),
      metric('Wind', formatNumber(zone.wind_kmh, 1), ' km/h'),
    ]),
    h('p', { className: 'phone-guidance', key: 'guidance' }, guidanceFor(zone)),
    sourceBanner(payload.summary),
  ])
}

function guidanceFor(zone) {
  const band = zone.heat_aqi_load_band
  if (band === 'Severe' || band === 'Very Poor') return 'Avoid strenuous outdoor activity. Use a clean indoor space and check on people at higher risk.'
  if (band === 'Poor' || band === 'Moderate') return 'Take shaded breaks, drink water, and reduce long outdoor exertion in the hottest hours.'
  return 'Keep water close, use shade, and check the outlook before planning time outside.'
}

function OutlookScreen({ payload, selectedZoneId }) {
  const days = payload.daily.filter((day) => !selectedZoneId || day.zone_id === selectedZoneId).slice(0, 6)
  return h('section', { className: 'phone-screen-content', 'aria-labelledby': 'phone-outlook-title' }, [
    h('p', { className: 'phone-kicker', key: 'kicker' }, 'PLAN AHEAD'),
    h('h1', { id: 'phone-outlook-title', key: 'title' }, '5-day outlook'),
    days.length
      ? h('ol', { className: 'phone-day-list', key: 'days' }, days.map((day) => h('li', { key: `${day.zone_id}-${day.date}` }, [
          h('span', { className: 'phone-day-list__date', key: 'date' }, formatDate(day.date)),
          h('span', { className: 'phone-day-list__temp', key: 'temp' }, `${formatNumber(day.tmax_c, 1)}°C`),
          h('span', { className: 'phone-day-list__aqi', key: 'aqi' }, `AQI ${formatNumber(day.aqi_peak)} · ${day.aqi_band}`),
          h('span', { className: 'phone-day-list__load', key: 'load' }, `Load ${formatNumber(day.heat_aqi_load_peak)}`),
        ])))
      : h('p', { className: 'phone-empty', key: 'empty' }, 'No daily forecast is available for this location yet.'),
    h('p', { className: 'phone-note', key: 'note' }, 'AQI is an indicative Indian PM2.5 sub-index from forecast concentrations, not a certified station reading.'),
  ])
}

function AlertScreen({ payload, selectedZoneId }) {
  const alerts = payload.alerts.data.filter((alert) => !selectedZoneId || alert.zone_id === selectedZoneId)
  const climatology = payload.alerts.climatology || {}
  return h('section', { className: 'phone-screen-content', 'aria-labelledby': 'phone-watch-title' }, [
    h('p', { className: 'phone-kicker', key: 'kicker' }, 'EARLY WARNING'),
    h('h1', { id: 'phone-watch-title', key: 'title' }, 'Heatwave watch'),
    climatology.available === false
      ? h('p', { className: 'phone-warning', key: 'normal-status' }, 'Historical normal unavailable: only an extreme-temperature watch can be shown.')
      : h('p', { className: 'phone-note', key: 'normal-status' }, `Compared with the ${text(climatology.reference_period, 'fixed historical')} Tmax normal.`),
    alerts.length
      ? h('ol', { className: 'phone-alert-list', key: 'alerts' }, alerts.map((alert) => h('li', { key: `${alert.zone_id}-${alert.date}` }, [
          h('strong', { key: 'label' }, `${alert.heatwave_label} · ${formatDate(alert.date)}`),
          h('span', { key: 'place' }, alert.zone_name),
          h('span', { key: 'detail' }, `Tmax ${formatNumber(alert.tmax_c, 1)}°C · normal ${formatNumber(alert.normal_tmax_c, 1)}°C · departure +${formatNumber(alert.departure_c, 1)}°C`),
          h('span', { key: 'air' }, `AQI peak ${formatNumber(alert.aqi_peak)} · heat + air load ${formatNumber(alert.heat_aqi_load_peak)}`),
        ])))
      : h('p', { className: 'phone-empty', key: 'empty' }, 'No heatwave watch is currently active for this location.'),
    h('p', { className: 'phone-note', key: 'method' }, 'A heatwave episode requires at least two consecutive qualifying days. An absolute 45°C reading remains a separate watch.'),
  ])
}

function SafetyScreen({ payload, selectedZoneId }) {
  const zone = zoneOrEmpty(payload, selectedZoneId)
  const airBand = zone ? zone.aqi_band : 'Unknown'
  const loadBand = zone ? zone.heat_aqi_load_band : 'Unknown'
  return h('section', { className: 'phone-screen-content', 'aria-labelledby': 'phone-safety-title' }, [
    h('p', { className: 'phone-kicker', key: 'kicker' }, 'DO THIS TODAY'),
    h('h1', { id: 'phone-safety-title', key: 'title' }, 'Stay safer outdoors'),
    h('p', { className: 'phone-safety-summary', key: 'summary' }, `Air is ${airBand}; combined heat + air load is ${loadBand}.`),
    h('ol', { className: 'phone-safety-list', key: 'list' }, [
      h('li', { key: 'water' }, [h('strong', { key: 'head' }, 'Carry water.'), ' Drink before you feel thirsty and refill when you can.']),
      h('li', { key: 'shade' }, [h('strong', { key: 'head' }, 'Move heavy activity.'), ' Prefer early morning or evening; take shaded breaks.']),
      h('li', { key: 'air' }, [h('strong', { key: 'head' }, 'Reduce smoke exposure.'), ' Close windows facing traffic and avoid burning waste.']),
      h('li', { key: 'check' }, [h('strong', { key: 'head' }, 'Check on others.'), ' Older adults, children, pregnant people, and outdoor workers need extra support.']),
    ]),
    h('p', { className: 'phone-emergency', key: 'emergency' }, 'Confusion, fainting, hot dry skin, or breathing difficulty: seek urgent medical help.'),
  ])
}

function AboutScreen({ payload }) {
  const summary = payload.summary
  return h('section', { className: 'phone-screen-content', 'aria-labelledby': 'phone-about-title' }, [
    h('p', { className: 'phone-kicker', key: 'kicker' }, 'KNOW THE LIMITS'),
    h('h1', { id: 'phone-about-title', key: 'title' }, 'Data & limits'),
    h('dl', { className: 'phone-facts', key: 'facts' }, [
      h('div', { key: 'delivery' }, [h('dt', { key: 'term' }, 'Delivery'), h('dd', { key: 'description' }, summary.static_snapshot ? 'Static snapshot available offline' : 'Live API when reachable')]),
      h('div', { key: 'source' }, [h('dt', { key: 'term' }, 'Source'), h('dd', { key: 'description' }, text(summary.data_source, 'Source unavailable'))]),
      h('div', { key: 'aqi' }, [h('dt', { key: 'term' }, 'AQI'), h('dd', { key: 'description' }, 'Indicative PM2.5 sub-index; not a certified station AQI')]),
      h('div', { key: 'combined' }, [h('dt', { key: 'term' }, 'Heat + air'), h('dd', { key: 'description' }, 'Parameterised communication load, not a calibrated health-outcome model')]),
    ]),
    summary.is_synthetic
      ? h('p', { className: 'phone-warning', key: 'synthetic' }, 'This screen is showing a synthetic outage exercise. Do not use its numbers for a real-world decision.')
      : null,
    payload.source_notice ? h('p', { className: 'phone-note', key: 'notice' }, payload.source_notice) : null,
  ])
}

export function MobileScreen({ screen = 'home', payload, selectedZoneId = '' }) {
  const safePayload = payload || { summary: { data: [], city: {} }, daily: [], alerts: { data: [], climatology: {} } }
  if (screen === 'outlook') return h(OutlookScreen, { payload: safePayload, selectedZoneId })
  if (screen === 'alerts') return h(AlertScreen, { payload: safePayload, selectedZoneId })
  if (screen === 'safety') return h(SafetyScreen, { payload: safePayload, selectedZoneId })
  if (screen === 'about') return h(AboutScreen, { payload: safePayload })
  return h(HomeScreen, { payload: safePayload, selectedZoneId })
}

export function screenLabel(id) {
  return SCREEN_LABELS[id] || SCREEN_LABELS.home
}
