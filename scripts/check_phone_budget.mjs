#!/usr/bin/env node
/* Verify the phone route's actual cold-open budget after `npm run build`.
 *
 * The point is not a fashionable tiny bundle at any cost: React and the motion
 * runtime are worthwhile here. The guard prevents the operations map, Leaflet,
 * or a full API export from being accidentally pulled into the first phone
 * paint.  Limits are gzip bytes because that is what a network sees.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const web = resolve(process.cwd())
const dist = join(web, 'dist')
const assets = join(dist, 'assets')
const staticCitizen = join(web, 'public', 'static-api', 'citizen.json')
const MAX_COLD_OPEN_GZIP = 120 * 1024
const MAX_CITIZEN_JSON = 45 * 1024

function fail(message) {
  console.error(`phone budget failed: ${message}`)
  process.exitCode = 1
}

if (!existsSync(join(dist, 'index.html'))) {
  fail('missing dist/index.html — run npm run build first')
} else if (!existsSync(staticCitizen)) {
  fail('missing public/static-api/citizen.json — run python -m scripts.export_static first')
} else {
  const html = readFileSync(join(dist, 'index.html'), 'utf8')
  const referenced = [...html.matchAll(/(?:src|href)="\.\/assets\/([^"]+)"/g)].map((match) => match[1])
  const phoneChunk = readdirSync(assets).find((name) => /^PhoneApp-.*\.js$/.test(name))
  if (!phoneChunk) {
    fail('no lazy PhoneApp chunk found; the citizen route is no longer code-split')
  } else {
    // The entry HTML preloads React/motion and the PhoneApp chunk loads after
    // route selection. Count both; do not count Leaflet, which must stay lazy.
    const files = [...new Set([...referenced.filter((name) => /\.(?:js|css)$/.test(name)), phoneChunk])]
    const leafletsAtBoot = files.filter((name) => /leaflet/i.test(name))
    if (leafletsAtBoot.length) fail(`Leaflet entered phone cold-open: ${leafletsAtBoot.join(', ')}`)
    // The 3D globe must never enter the phone cold-open either — CesiumJS is
    // ~1.1 MB gzipped and its transitive deps (nosleep.js' base64 wake-lock
    // video, protobufjs) are worse than they look. Both have slipped into the
    // entry graph once already; the size total alone can hide them, so name
    // them explicitly.
    const globeAtBoot = files.filter((name) => /cesium|nosleep|protobuf|globe/i.test(name))
    if (globeAtBoot.length) fail(`3D globe code entered phone cold-open: ${globeAtBoot.join(', ')}`)
    const bytes = files.reduce((sum, name) => sum + gzipSync(readFileSync(join(assets, name))).length, 0)
    const citizenBytes = readFileSync(staticCitizen).length
    console.log(`phone cold-open: ${bytes.toLocaleString()} gzip bytes across ${files.map((name) => basename(name)).join(', ')}`)
    console.log(`static citizen payload: ${citizenBytes.toLocaleString()} bytes uncompressed`)
    if (bytes > MAX_COLD_OPEN_GZIP) fail(`${bytes} gzip bytes exceeds ${MAX_COLD_OPEN_GZIP}`)
    if (citizenBytes > MAX_CITIZEN_JSON) fail(`${citizenBytes} bytes exceeds ${MAX_CITIZEN_JSON}`)
  }
}

if (process.exitCode) process.exit(process.exitCode)
