import { normaliseDemoPayload } from './contract.js'

// Vite's base is './' in production, so the demo keeps working inside a
// GitHub Pages project subdirectory. Browser code only ever uses relative
// paths — the static host serves both the app and its snapshots.
const BASE_PATH = import.meta.env.BASE_URL || './'
const staticURL = (name) => `${BASE_PATH.replace(/\/?$/, '/')}static-api/${name}`

export class DemoDataError extends Error {
  constructor(message) {
    super(message)
    this.name = 'DemoDataError'
  }
}

async function readJSON(url, signal) {
  let response
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' }, signal })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new DemoDataError(`Unable to reach ${url}`)
  }
  if (!response.ok) throw new DemoDataError(`${url} returned ${response.status}`)
  try {
    return await response.json()
  } catch {
    throw new DemoDataError(`${url} returned invalid JSON`)
  }
}

function isStaticHost() {
  if (typeof window === 'undefined') return false
  const host = window.location.hostname
  return window.location.protocol === 'file:'
    || host.endsWith('.github.io')
    || new URLSearchParams(window.location.search).has('static')
}

async function staticBundle(scenarioId, signal) {
  const [scenarios, zones, forecast, thermal, warnings, notifications] = await Promise.all([
    readJSON(staticURL('demo-scenarios.json'), signal),
    readJSON(staticURL('demo-zones.json'), signal),
    readJSON(staticURL(`demo-forecast-${scenarioId}.json`), signal),
    readJSON(staticURL(`demo-thermal-${scenarioId}.json`), signal),
    readJSON(staticURL(`demo-warnings-${scenarioId}.json`), signal),
    readJSON(staticURL(`demo-notifications-${scenarioId}.json`), signal),
  ])
  return { scenarios, zones, forecast, thermal, warnings, notifications }
}

async function liveBundle(scenarioId, signal) {
  const [scenarios, zones, forecast, thermal, warnings, notifications] = await Promise.all([
    readJSON('./api/demo/scenarios', signal),
    readJSON('./api/demo/zones', signal),
    readJSON(`./api/demo/forecast?scenario=${encodeURIComponent(scenarioId)}`, signal),
    readJSON(`./api/demo/thermal?scenario=${encodeURIComponent(scenarioId)}`, signal),
    readJSON(`./api/demo/warnings?scenario=${encodeURIComponent(scenarioId)}`, signal),
    readJSON(`./api/demo/notifications?scenario=${encodeURIComponent(scenarioId)}`, signal),
  ])
  return { scenarios, zones, forecast, thermal, warnings, notifications }
}

export async function loadDemoPayload(scenarioId, { signal } = {}) {
  // On GitHub Pages there is no FastAPI proxy: go straight to the generated
  // snapshots instead of staging six deliberate 404s on every scenario switch.
  if (isStaticHost()) {
    return normaliseDemoPayload(await staticBundle(scenarioId, signal))
  }
  try {
    return normaliseDemoPayload(await liveBundle(scenarioId, signal))
  } catch (liveError) {
    if (liveError?.name === 'AbortError') throw liveError
    try {
      return normaliseDemoPayload(await staticBundle(scenarioId, signal))
    } catch (staticError) {
      if (staticError?.name === 'AbortError') throw staticError
      throw new DemoDataError(`${liveError.message}; no saved demo snapshot (${staticError.message})`)
    }
  }
}

export { staticURL }
