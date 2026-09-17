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

console.log(JSON.stringify({
  missingFields,
  badOutput,
  renders,
  summary: {
    zones: payload.summary.data.length,
    daily: payload.daily.length,
    alerts: payload.alerts.data.length,
  },
}))
