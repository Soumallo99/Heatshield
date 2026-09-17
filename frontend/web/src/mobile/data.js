import { normalisePhonePayload } from './contract.js'

// Vite's base is './' for the production bundle, so this remains inside a
// GitHub Pages project subdirectory instead of accidentally requesting
// https://<owner>.github.io/static-api/... at the domain root.
const BASE_PATH = import.meta.env.BASE_URL || './'
const staticURL = (name) => `${BASE_PATH.replace(/\/?$/, '/')}static-api/${name}`

export class PhoneDataError extends Error {
  constructor(message) {
    super(message)
    this.name = 'PhoneDataError'
  }
}

async function readJSON(url, signal) {
  let response
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' }, signal })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new PhoneDataError(`Unable to reach ${url}`)
  }
  if (!response.ok) throw new PhoneDataError(`${url} returned ${response.status}`)
  try {
    return await response.json()
  } catch {
    throw new PhoneDataError(`${url} returned invalid JSON`)
  }
}

function isStaticHost() {
  if (typeof window === 'undefined') return false
  const host = window.location.hostname
  return window.location.protocol === 'file:' || host.endsWith('.github.io') || new URLSearchParams(window.location.search).has('static')
}

async function staticSnapshot(signal) {
  return normalisePhonePayload(await readJSON(staticURL('citizen.json'), signal))
}

async function liveSnapshot(signal) {
  // All browser-facing live calls use a relative /api path. Vite proxies this
  // locally; a static host will 404 and then take the generated snapshot path.
  const [summary, alerts, daily] = await Promise.all([
    readJSON('./api/ncr/summary', signal),
    readJSON('./api/ncr/alerts', signal),
    readJSON('./api/ncr/daily', signal),
  ])
  return normalisePhonePayload({ summary, alerts, daily: daily.data || [] })
}

export async function loadPhonePayload({ signal } = {}) {
  // GitHub Pages has no FastAPI proxy. Going straight to the generated file
  // prevents three deliberate 404s at every cold open.
  if (isStaticHost()) return staticSnapshot(signal)
  try {
    return await liveSnapshot(signal)
  } catch (liveError) {
    try {
      return await staticSnapshot(signal)
    } catch (staticError) {
      throw new PhoneDataError(`${liveError.message}; no saved phone snapshot (${staticError.message})`)
    }
  }
}

export { staticURL }
