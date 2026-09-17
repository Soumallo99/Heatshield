/* Server-side render verifier for the Heat Risk Demo screens.
 *
 * Mirrors tests/mobile/render_mobile.mjs: it imports the no-JSX demo contract
 * and screens directly with Node, renders every screen against the REAL
 * exported static payloads (rich + empty states), and fails on any
 * resident-visible NaN / undefined / Invalid Date, any missing contract path,
 * or any render that drops the demo disclaimer.
 *
 * usage: node render_demo.mjs <static-api-dir> [scenarioId]
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import React from '../../frontend/web/node_modules/react/index.js'
import { renderToStaticMarkup } from '../../frontend/web/node_modules/react-dom/server.node.js'
import {
  DEMO_DISCLAIMER,
  DEMO_SCREEN_IDS,
  EMPTY_DEMO_PAYLOAD,
  READS_BY_SCREEN,
  normaliseDemoPayload,
} from '../../frontend/web/src/demo/contract.js'
import { DemoScreen } from '../../frontend/web/src/demo/screens.js'

const staticDir = process.argv[2]
const scenarioId = process.argv[3] || 'dry-extreme'
if (!staticDir) throw new Error('usage: node render_demo.mjs <static-api-dir> [scenarioId]')

const readJSON = (name) => JSON.parse(readFileSync(join(staticDir, name), 'utf8'))

// Same six-file bundle the browser loads from static hosting (demo/data.js).
const bundle = {
  scenarios: readJSON('demo-scenarios.json'),
  zones: readJSON('demo-zones.json'),
  forecast: readJSON(`demo-forecast-${scenarioId}.json`),
  thermal: readJSON(`demo-thermal-${scenarioId}.json`),
  warnings: readJSON(`demo-warnings-${scenarioId}.json`),
  notifications: readJSON(`demo-notifications-${scenarioId}.json`),
}
const payload = normaliseDemoPayload(bundle)

function valuesAtPath(value, path) {
  const pieces = path.split('.')
  let values = [value]
  for (const piece of pieces) {
    const isArray = piece.endsWith('[]')
    const key = isArray ? piece.slice(0, -2) : piece
    values = values.flatMap((item) => {
      if (!item || typeof item !== 'object' || !(key in item)) return []
      const next = item[key]
      return isArray ? (Array.isArray(next) ? next : [next]) : [next]
    })
  }
  return values
}

/* Contract check runs against the NORMALISED payload: this proves the
 * normaliser preserves every field the screens read from the real API
 * envelopes — a renamed or dropped field shows up here, not in production. */
const missingFields = []
for (const [screen, paths] of Object.entries(READS_BY_SCREEN)) {
  for (const path of paths) {
    const root = path.split('.')[0].replace(/\[\]$/, '')
    if (!(root in payload)) {
      missingFields.push(`${screen}: ${path} (missing root)`)
      continue
    }
    const values = valuesAtPath(payload, path)
    if (path.includes('[]')) {
      // An empty collection is a valid data state (e.g. monsoon-break has no
      // notification previews); a NON-empty one must carry the field in every
      // element.
      const collection = valuesAtPath(payload, path.split('.[].')[0] + '[]')
      if (collection.length && !values.length) missingFields.push(`${screen}: ${path}`)
    } else if (!values.length) {
      missingFields.push(`${screen}: ${path}`)
    }
  }
}

const selectedZoneId = payload.zones[0]?.zone_id || ''
const renders = {}
for (const screen of DEMO_SCREEN_IDS) {
  renders[screen] = {
    rich: renderToStaticMarkup(React.createElement(DemoScreen, { screen, payload, selectedZoneId, leadDay: 3 })),
    empty: renderToStaticMarkup(React.createElement(DemoScreen, { screen, payload: EMPTY_DEMO_PAYLOAD, selectedZoneId: '', leadDay: 3 })),
  }
}

const forbidden = /\b(?:NaN|undefined|Invalid Date)\b/i
const badOutput = Object.entries(renders)
  .flatMap(([screen, states]) => Object.entries(states)
    .filter(([, html]) => forbidden.test(html))
    .map(([state]) => `${screen}/${state}`))

const missingDisclaimer = Object.entries(renders)
  .flatMap(([screen, states]) => Object.entries(states)
    .filter(([, html]) => !html.includes(DEMO_DISCLAIMER))
    .map(([state]) => `${screen}/${state}`))

console.log(JSON.stringify({
  scenarioId,
  missingFields,
  badOutput,
  missingDisclaimer,
  renders,
  summary: {
    scenarios: payload.scenarios.list.length,
    zones: payload.zones.length,
    warningRows: payload.warnings.rows.length,
    leadDays: [...new Set(payload.warnings.rows.map((row) => row.lead_days))].sort(),
    alertLevels: [...new Set(payload.warnings.rows.map((row) => row.alert_level))].sort(),
    previews: payload.notifications.previews.length,
    dryRun: payload.notifications.dry_run,
    issuedAt: payload.warnings.issued_at,
    referencePeriod: payload.warnings.climatology?.reference_period || null,
  },
}))
