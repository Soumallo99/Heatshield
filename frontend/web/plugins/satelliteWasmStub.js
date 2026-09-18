/* Stub out satellite.js's WebAssembly build.
 *
 * satellite.js ships two implementations of SGP4: a pure-JavaScript one
 * (`dist/propagation.js`, the code this library has used for a decade) and a
 * newer Emscripten/WebAssembly one reachable through `dist/wasm/index.js`,
 * which dynamically imports ~126 kB of Emscripten glue with the wasm inlined
 * as base64 (`-sSINGLE_FILE`), and a second pthreads build that spawns Workers.
 *
 * HeatShield uses the pure-JavaScript path, and this plugin makes that a build
 * fact rather than a hope. Three reasons, in order of how much they would hurt:
 *
 *   1. The wasm runtime is reached only through a *dynamic* import, so a
 *      bundler follows it anyway: the globe's lazy chunk would carry 126 kB of
 *      Emscripten glue plus an inlined wasm binary for code nobody calls.
 *   2. The pthreads build spawns `new Worker(...)` from a URL derived at
 *      runtime, which is exactly the kind of asset that goes missing when the
 *      app is served from a repository subdirectory on GitHub Pages
 *      (/Heatshield/). A worker that 404s fails silently and takes the layer
 *      with it.
 *   3. Emscripten glue resolves its own assets relative to `import.meta.url`
 *      and reaches for `fetch`/`WebAssembly` at instantiation time. None of
 *      that touches a third-party host today, but it is a moving part in the
 *      one part of this project that must be able to answer "which hosts does
 *      this page talk to?" — and the answer has to stay "ours, and the map
 *      tile providers".
 *
 * So the wasm entry is replaced with a module whose runtime factories reject
 * with a message that says which build is missing and why. Nothing in
 * HeatShield calls them: propagation goes through `propagate()`/`sgp4()`,
 * which are pure JavaScript. If someone later reaches for the wasm runtime,
 * they get that message instead of a silent fallback to a different algorithm.
 *
 * This is also why the plugin matches three ids rather than one: Vite may hand
 * us the package's `#wasm-single-thread` subpath import, the resolved
 * `wasm-build/...` file, or the barrel that re-exports the whole wasm tree.
 */

const STUB_ID = '\0heatshield:satellite-wasm-stub'

const MESSAGE =
  "satellite.js's WebAssembly build is not shipped with HeatShield: the app " +
  'propagates orbits with the pure-JavaScript SGP4 implementation instead ' +
  '(see frontend/web/plugins/satelliteWasmStub.js).'

/**
 * The stub module itself: runtime factories that reject with `MESSAGE`.
 *
 * Rejecting, not resolving to `null`: a caller that reaches for the wasm
 * runtime should hear why it is not here, rather than be handed a value that
 * silently changes which implementation it is using.
 */
export const SATELLITE_WASM_STUB = [
  'export const SATELLITE_WASM_STUBBED = true',
  `export function createSingleThreadRuntime() { return Promise.reject(new Error(${JSON.stringify(MESSAGE)})) }`,
  `export function createMultiThreadRuntime() { return Promise.reject(new Error(${JSON.stringify(MESSAGE)})) }`,
  `export default function () { throw new Error(${JSON.stringify(MESSAGE)}) }`,
].join('\n')

/** Ids that lead to the Emscripten build rather than to plain JavaScript. */
export function isWasmEntry(id) {
  if (typeof id !== 'string') return false
  if (id === '#wasm-single-thread' || id === '#wasm-multi-thread') return true
  if (id.includes('satellite.js/wasm-build/')) return true
  const normalised = id.replace(/\\/g, '/')
  return (
    normalised.includes('satellite.js/dist/wasm/index.js') ||
    normalised.includes('satellite.js/dist/wasm/runtimes/')
  )
}

export function satelliteWasmStub() {
  return {
    name: 'heatshield:satellite-wasm-stub',
    // Before Vite's own resolver: the `#wasm-*` subpath imports belong to
    // satellite.js's package `imports` map, and letting the default resolver
    // try first would pull the real glue file in before we can say no.
    enforce: 'pre',
    resolveId(id) {
      return isWasmEntry(id) ? STUB_ID : null
    },
    load(id) {
      return id === STUB_ID ? SATELLITE_WASM_STUB : null
    },
  }
}

export default satelliteWasmStub
