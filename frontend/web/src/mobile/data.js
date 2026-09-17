import { normalisePhonePayload } from './contract.js'
import { isStaticHost, readJSON as fetchJSON, staticURL } from '../staticApi.js'

export class PhoneDataError extends Error {
  constructor(message) {
    super(message)
    this.name = 'PhoneDataError'
  }
}

const readJSON = (url, signal) => fetchJSON(url, signal, PhoneDataError)

async function staticSnapshot(signal, city = 'delhi') {
  const file = city === 'kolkata' ? 'citizen-kolkata.json' : 'citizen.json'
  return normalisePhonePayload(await readJSON(staticURL(file), signal))
}

async function liveSnapshot(signal, city = 'delhi') {
  // All browser-facing live calls use a relative /api path. Vite proxies this
  // locally; a static host will 404 and then take the generated snapshot path.
  if (city === 'kolkata') {
    return normalisePhonePayload(await readJSON('./api/citizen/kolkata', signal))
  }
  const [summary, alerts, daily] = await Promise.all([
    readJSON('./api/ncr/summary', signal),
    readJSON('./api/ncr/alerts', signal),
    readJSON('./api/ncr/daily', signal),
  ])
  return normalisePhonePayload({ summary, alerts, daily: daily.data || [] })
}

export async function loadPhonePayload({ city = 'delhi', signal } = {}) {
  // GitHub Pages has no FastAPI proxy. Going straight to the generated file
  // prevents three deliberate 404s at every cold open.
  if (isStaticHost()) return staticSnapshot(signal, city)
  try {
    return await liveSnapshot(signal, city)
  } catch (liveError) {
    try {
      return await staticSnapshot(signal, city)
    } catch (staticError) {
      throw new PhoneDataError(`${liveError.message}; no saved phone snapshot (${staticError.message})`)
    }
  }
}
