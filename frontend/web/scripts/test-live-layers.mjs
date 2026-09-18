#!/usr/bin/env node
/**
 * The globe's live tracking layers, from the browser's side.
 *
 * These are the checks that keep an *additive* layer from becoming a liar. The
 * layers are optional decoration on a warning system, and the failure mode
 * that matters is not "the aircraft did not draw" — it is "the aircraft drew,
 * and the numbers behind it were invented". So every test here is about the
 * difference between data and the honest absence of data, and none of them
 * touches the network: the upstreams are faked, exactly as the Python suite
 * fakes them.
 *
 * Run with `npm test` (plain `node --test`, no framework).
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  LIVE_LAYERS,
  LiveLayerError,
  describeLiveFailure,
  fetchLiveLayer,
  liveURL,
  ommForSatrec,
  positionsFor,
  propagateSatellites,
  resetPropagator,
  staticHostNotice,
} from '../src/globe/liveData.js'
import { liveLabel, liveHeight } from '../src/globe/heatLayers.js'
import { satelliteWasmStub } from '../plugins/satelliteWasmStub.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const WEB = join(HERE, '..')

/** Replace global fetch for one test, and always put it back. */
async function withFetch(implementation, body) {
  const original = globalThis.fetch
  globalThis.fetch = implementation
  try {
    return await body()
  } finally {
    globalThis.fetch = original
  }
}

/** Make the module believe it is running on a static host, then undo it. */
async function asStaticHost(body) {
  const original = globalThis.window
  globalThis.window = {
    location: { hostname: 'soumallo99.github.io', protocol: 'https:', search: '' },
  }
  try {
    return await body()
  } finally {
    if (original === undefined) delete globalThis.window
    else globalThis.window = original
  }
}

const jsonResponse = (value, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => value,
})

/**
 * A real CelesTrak element set for the ISS (OMM JSON, epoch 2026-09-18),
 * renamed into the snake_case shape the API serves. Kept as a fixture rather
 * than fetched: a test that needs CelesTrak to be up is a test that fails for
 * somebody else's reasons.
 */
const ISS = {
  name: 'ISS (ZARYA)',
  object_id: '1998-067A',
  norad_id: 25544,
  epoch: '2026-09-18T03:25:38.782272',
  mean_motion: 15.49160218,
  eccentricity: 0.00048228,
  inclination: 51.6307,
  ra_of_asc_node: 200.0361,
  arg_of_pericenter: 152.4527,
  mean_anomaly: 207.6718,
  bstar: 0.00011125122,
  mean_motion_dot: 5.718e-5,
  mean_motion_ddot: 0,
  group: 'stations',
}

/* ------------------------------------------------------------------- shapes */

test('every layer is asked for through this origin, never a third-party host', () => {
  for (const layer of LIVE_LAYERS) {
    const url = liveURL(layer.id, { lat: 22.5726, lon: 88.3639, radius_nm: 250 })
    // Relative, not '/api': on GitHub Pages this app lives under /Heatshield/,
    // where a root-relative path leaves the app (and the worker's scope).
    assert.match(url, /^\.\/api\/live\//, layer.id)
    assert.ok(!url.includes('http'), `${layer.id} must not name an absolute origin`)
    assert.ok(url.includes('lat=22.5726'), 'params ride along')
  }
  // Nothing in the shipped source may hold a remote URL at all: the point of
  // /api/live/* is that the API process does the fetching, so the browser has
  // no upstream to reach — and a static host has no upstream to reach either.
  const source = readFileSync(join(WEB, 'src', 'globe', 'liveData.js'), 'utf8')
  assert.ok(!/https?:\/\//.test(source), 'liveData.js must not name a remote host')
  assert.ok(!/fetch\(\s*[`'"]https?:\/\//.test(source))
})

test('a static host is told it has no API, and asks for nothing at all', async () => {
  await asStaticHost(async () => {
    const notice = staticHostNotice()
    assert.ok(notice, 'a static host must have a reason ready')
    assert.match(notice, /no HeatShield API/i)
    // The request is the thing that would 404 on every press; asking anyway
    // would be noise in the console and a lie in the network panel.
    let asked = false
    await withFetch(async () => {
      asked = true
      return jsonResponse({ available: true, data: [] })
    }, async () => {
      await assert.rejects(() => fetchLiveLayer('aircraft'), (error) => {
        assert.ok(error instanceof LiveLayerError)
        assert.equal(error.kind, 'no-api')
        return true
      })
    })
    assert.equal(asked, false, 'no request may be made from a static host')
  })
})

test('a 404 means "no API here", a transport failure means "cannot reach it"', async () => {
  await withFetch(async () => jsonResponse({}, 404), async () => {
    await assert.rejects(
      () => fetchLiveLayer('aircraft'),
      (error) => error instanceof LiveLayerError && error.kind === 'no-api',
      'a missing API is not the same failure as a broken one',
    )
  })
  await withFetch(async () => {
    throw new TypeError('Failed to fetch')
  }, async () => {
    await assert.rejects(
      () => fetchLiveLayer('earthquakes'),
      (error) => error instanceof LiveLayerError && error.kind === 'unreachable',
    )
  })
  // The operator-facing sentence for each is different on purpose: one sends
  // you to the deployment, the other to the API process.
  assert.match(describeLiveFailure(new LiveLayerError('x', 'no-api')), /this deployment has none/)
  assert.match(describeLiveFailure(new LiveLayerError('cannot reach the HeatShield API (./api/live/x)', 'unreachable')), /cannot reach/)
})

test("the service worker's offline answer is a failure, not an empty layer", async () => {
  // public/sw.js answers a failed /api fetch with HTTP 200 and this body. Read
  // as data it paints an empty globe with a green "live" dot.
  await withFetch(async () => jsonResponse({ stale: true, error: 'offline', data: [] }), async () => {
    await assert.rejects(
      () => fetchLiveLayer('aircraft'),
      (error) => error instanceof LiveLayerError && error.kind === 'offline',
    )
  })
  assert.match(describeLiveFailure(new LiveLayerError('offline: x', 'offline')), /Offline/)
})

test('an unavailable payload keeps its notice, and a bad body is a typed error', async () => {
  const degraded = {
    layer: 'aircraft',
    available: false,
    count: 0,
    data: [],
    notice: 'adsb.lol is unavailable right now — timeout. Nothing is shown rather than a guess.',
  }
  await withFetch(async () => jsonResponse(degraded), async () => {
    const payload = await fetchLiveLayer('aircraft')
    assert.equal(payload.available, false)
    assert.deepEqual(payload.data, [], 'no rows may appear next to "unavailable"')
    assert.match(payload.notice, /Nothing is shown rather than a guess/)
  })
  await withFetch(async () => ({ ok: true, status: 200, json: async () => { throw new Error('not json') } }), async () => {
    await assert.rejects(
      () => fetchLiveLayer('satellites'),
      (error) => error instanceof LiveLayerError && error.kind === 'bad-json',
    )
  })
})

test('the globe starts with every live layer off', () => {
  // Opt-in is a requirement, not a default: each layer is a request to
  // somebody else's free service, made only when an operator asks for it.
  const globe = readFileSync(join(WEB, 'src', 'globe', 'HeatGlobe.jsx'), 'utf8')
  assert.ok(/const \[liveId, setLiveId\] = useState\(''\)/.test(globe), 'no layer may be on at mount')
  assert.ok(/enabled: Boolean\(liveId\) && ready/.test(globe), 'nothing is fetched until a layer is chosen')
  // And the sources get no request either: the URLs are only built on demand.
  for (const layer of LIVE_LAYERS) {
    assert.ok(globe.includes(`key={layer.id}`), 'the chips come from the layer list')
    assert.equal(layer.refresh_ms >= 15000, true, `${layer.id} must not poll aggressively`)
  }
})

/* ------------------------------------------------------------------- orbits */

test('satellite element sets are turned into real positions in this browser', async (t) => {
  // A real ISS element set, propagated near its epoch. The point is not the
  // exact number — it is that the altitude comes out as low Earth orbit and
  // not as a plausible-looking invention.
  resetPropagator()
  const library = await import('satellite.js')
  resetPropagator()
  const rows = propagateSatellites([ISS], new Date('2026-09-18T03:25:38Z'), {
    json2satrec: library.json2satrec,
    propagate: library.propagate,
    gstime: library.gstime,
    eciToGeodetic: library.eciToGeodetic,
    radiansToDegrees: library.radiansToDegrees,
  })
  assert.equal(rows.length, 1)
  const [iss] = rows
  assert.ok(Number.isFinite(iss.lat) && Math.abs(iss.lat) <= 90, `latitude ${iss.lat}`)
  assert.ok(Number.isFinite(iss.lon) && Math.abs(iss.lon) <= 180, `longitude ${iss.lon}`)
  assert.ok(iss.alt_km > 330 && iss.alt_km < 500, `ISS altitude ${iss.alt_km} km is not low Earth orbit`)
  assert.equal(iss.name, 'ISS (ZARYA)', 'the row keeps everything the label needs')
  assert.equal(iss.propagated_at, new Date('2026-09-18T03:25:38Z').toISOString())

  // The same thing through the path the component uses (library loaded once).
  resetPropagator()
  const viaComponent = await positionsFor('satellites', [ISS], new Date('2026-09-18T03:25:38Z'))
  assert.equal(viaComponent.length, 1)
  assert.ok(Math.abs(viaComponent[0].alt_km - iss.alt_km) < 0.001)
  // Non-satellite rows already carry a position and pass straight through.
  const aircraft = [{ icao: '800446', callsign: 'BDA201', lat: 24.75, lon: 84.57, alt_m: 11582 }]
  assert.deepEqual(await positionsFor('aircraft', aircraft), aircraft)
})

test('a satellite that cannot be propagated is dropped, never drawn somewhere wrong', async () => {
  resetPropagator()
  const library = await import('satellite.js')
  resetPropagator()
  const broken = { ...ISS, name: 'BROKEN', norad_id: 1, mean_motion: 0, inclination: 0, eccentricity: 0 }
  const rows = propagateSatellites([ISS, broken, { name: 'NO ELEMENTS' }], new Date('2026-09-18T03:25:38Z'), {
    json2satrec: library.json2satrec,
    propagate: library.propagate,
    gstime: library.gstime,
    eciToGeodetic: library.eciToGeodetic,
    radiansToDegrees: library.radiansToDegrees,
  })
  assert.equal(rows.length, 1, 'an unpropagatable element set must not become a dot')
  assert.equal(rows[0].name, 'ISS (ZARYA)')
  // With nothing loaded at all, the honest answer is "no positions", not
  // "every satellite is at 0,0".
  resetPropagator()
  assert.deepEqual(propagateSatellites([ISS], new Date()), [])
  assert.deepEqual(await positionsFor('satellites', []), [])
})

test('what a live row says on the globe comes from the row, never from a guess', () => {
  assert.equal(liveLabel('aircraft', { callsign: 'BDA201', icao: '800446' }), 'BDA201')
  assert.equal(liveLabel('aircraft', { icao: '800446' }), '800446')
  assert.equal(liveLabel('earthquakes', { mag: 6.5, place: '169 km W of Nikolski, Alaska' }),
    'M 6.5 · 169 km W of Nikolski, Alaska')
  assert.equal(liveLabel('satellites', { name: 'ISS (ZARYA)' }), 'ISS (ZARYA)')
  // Height: satellites fly, aircraft cruise, earthquakes are in the ground.
  assert.equal(liveHeight('satellites', { alt_km: 422.8 }), 422800)
  assert.equal(liveHeight('aircraft', { alt_m: 11582.4 }), 11582.4)
  assert.equal(liveHeight('earthquakes', { lat: 1, lon: 2 }), 0)
})

test("satellite.js's WebAssembly build is stubbed out at build time", async () => {
  // The wasm runtime is 126 kB of Emscripten glue that nothing calls, reached
  // through a dynamic import the bundler would follow anyway. The plugin must
  // catch every id that leads to it (the package's own #wasm-* subpath
  // imports, the resolved glue files, and the barrel that re-exports them).
  const plugin = satelliteWasmStub()
  assert.equal(plugin.enforce, 'pre', 'it has to run before Vite resolves the real file')
  for (const id of [
    '#wasm-single-thread',
    '#wasm-multi-thread',
    'satellite.js/wasm-build/base-release/index.js',
    '/node_modules/satellite.js/dist/wasm/index.js',
    '/node_modules/satellite.js/dist/wasm/runtimes/index.js',
  ]) {
    assert.ok(plugin.resolveId(id), `the wasm entry ${id} must be stubbed`)
  }
  assert.equal(plugin.resolveId('/node_modules/satellite.js/dist/index.js'), null,
    'the pure-JavaScript entry must not be touched')

  const stub = plugin.load(plugin.resolveId('#wasm-single-thread'))
  assert.match(stub, /createSingleThreadRuntime/)
  assert.match(stub, /WebAssembly build is not shipped/)

  // Run the stub as the module it claims to be, rather than trusting the text:
  // it has to *reject* with that message, not quietly resolve to something the
  // caller would then propagate with.
  const path = join(mkdtempSync(join(tmpdir(), 'heatshield-wasm-')), 'stub.mjs')
  writeFileSync(path, stub)
  const loaded = await import(path)
  assert.equal(loaded.SATELLITE_WASM_STUBBED, true)
  await assert.rejects(
    () => loaded.createSingleThreadRuntime(),
    (error) => /WebAssembly build is not shipped/.test(error.message),
  )
  await assert.rejects(() => loaded.createMultiThreadRuntime(), /WebAssembly build is not shipped/)

  // And it is actually wired into the build, which is the only place it does
  // any good.
  const config = readFileSync(join(WEB, 'vite.config.js'), 'utf8')
  assert.match(config, /satelliteWasmStub\(\)/, 'the plugin must be registered in vite.config.js')
  assert.match(config, /'satellite\.js'/, 'and pre-bundled, or the dev server reloads mid-session')
  void ommForSatrec
})
