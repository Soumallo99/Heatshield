/* Server-side render verifier for the phone screens.
 *
 * It deliberately imports the no-JSX render contract directly with Node. This
 * catches resident-visible bad data strings without needing a browser or a
 * brittle source grep.
 */
import { readFileSync } from 'node:fs'
import React from '../../frontend/web/node_modules/react/index.js'
import { renderToStaticMarkup } from '../../frontend/web/node_modules/react-dom/server.node.js'
import {
  EMPTY_PHONE_PAYLOAD,
  READS_BY_SCREEN,
  SCREEN_IDS,
  heatAlertFor,
  nearestZone,
  normalisePhonePayload,
} from '../../frontend/web/src/mobile/contract.js'
import { MobileScreen } from '../../frontend/web/src/mobile/screens.js'

const input = process.argv[2]
if (!input) throw new Error('usage: node render_mobile.mjs <citizen.json>')
const raw = JSON.parse(readFileSync(input, 'utf8'))
const payload = normalisePhonePayload(raw)

function valuesAtPath(value, path) {
  const pieces = path.split('.')
  let values = [value]
  for (const piece of pieces) {
    const isArray = piece.endsWith('[]')
    const key = isArray ? piece.slice(0, -2) : piece
    values = values.flatMap((item) => {
      if (!item || typeof item !== 'object' || !(key in item)) return []
      const next = item[key]
      return isArray ? (Array.isArray(next) ? next : []) : [next]
    })
  }
  return values
}

const missingFields = []
for (const [screen, paths] of Object.entries(READS_BY_SCREEN)) {
  for (const path of paths) {
    // Empty arrays are valid data states. The root collection itself must
    // exist, while fields inside no rows are checked by the rich export below.
    const root = path.split('.')[0].replace(/\[\]$/, '')
    if (!(root in raw)) missingFields.push(`${screen}: ${path}`)
    else if (!path.includes('[]') && !valuesAtPath(raw, path).length) missingFields.push(`${screen}: ${path}`)
  }
}

const renders = {}
for (const screen of SCREEN_IDS) {
  const rich = renderToStaticMarkup(React.createElement(MobileScreen, { screen, payload, selectedZoneId: payload.summary.data[0]?.zone_id || '' }))
  const empty = renderToStaticMarkup(React.createElement(MobileScreen, { screen, payload: EMPTY_PHONE_PAYLOAD, selectedZoneId: '' }))
  renders[screen] = { rich, empty }
}

const forbidden = /\b(?:NaN|undefined|Invalid Date)\b/i
const badOutput = Object.entries(renders)
  .flatMap(([screen, states]) => Object.entries(states)
    .filter(([, html]) => forbidden.test(html))
    .map(([state]) => `${screen}/${state}`))

/* Personal heat-alert helper checks — the same pure functions PhoneApp.jsx
 * uses for the opt-in 🔔 notifications and the 📍 nearest-locality button. */
const alertSamples = payload.summary.data
  .map((zone) => heatAlertFor(zone, { isSynthetic: payload.summary.is_synthetic }))
  .filter(Boolean)
const cleanProbe = heatAlertFor(
  { zone_id: 'probe', zone_name: 'Probe', heat_aqi_load_band: 'Good', temp_c: 29 },
  { isSynthetic: false },
)
const syntheticProbe = heatAlertFor(
  { zone_id: 'probe2', zone_name: 'Probe', heat_aqi_load_band: 'Severe', heat_aqi_load: 401, temp_c: 41.2, timestamp_local: '2026-05-19T19:00' },
  { isSynthetic: true },
)
const nearestCentral = nearestZone(payload.summary.data, 28.6139, 77.209)   // Central Delhi grid point
const nearestNoida = nearestZone(payload.summary.data, 28.5355, 77.391)     // Noida grid point
const personalAlerts = {
  risky: alertSamples.length,
  allLabelled: alertSamples.every((alert) => /Practice data|Live forecast/.test(alert.body)),
  cleanIsNull: cleanProbe === null,
  syntheticProbeLabelled: Boolean(syntheticProbe) && syntheticProbe.body.includes('Practice data'),
  nearestZoneId: nearestCentral ? nearestCentral.zone_id : '',
  nearestFarZoneId: nearestNoida ? nearestNoida.zone_id : '',
}

console.log(JSON.stringify({
  missingFields,
  badOutput,
  renders,
  personalAlerts,
  summary: {
    zones: payload.summary.data.length,
    daily: payload.daily.length,
    alerts: payload.alerts.data.length,
  },
}))
