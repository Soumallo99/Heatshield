import { normaliseDemoPayload } from './contract.js'
import { isStaticHost, readJSON as fetchJSON, staticURL } from '../staticApi.js'

export class DemoDataError extends Error {
  constructor(message) {
    super(message)
    this.name = 'DemoDataError'
  }
}

const readJSON = (url, signal) => fetchJSON(url, signal, DemoDataError)

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
