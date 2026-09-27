#!/usr/bin/env node
/**
 * Proves the `detectRetina` / `maxNativeZoom` interaction against the real
 * Leaflet build rather than against a reading of its source.
 *
 * Run: node scripts/check-tile-zoom.mjs
 *
 * Every provider in src/basemaps.js publishes a deepest zoom level and no
 * `@2x` variant. Leaflet's `maxNativeZoom` is supposed to keep requests inside
 * that level. `detectRetina` quietly breaks it: it sets `zoomOffset = 1`, and
 * `TileLayer._getZoomForUrl()` returns `_clampZoom(zoom) + zoomOffset` — the
 * offset is added *after* the clamp. So on a high-DPI screen the layer asks
 * for `maxNativeZoom + 1`.
 *
 * This script constructs a real TileLayer on a simulated retina display and
 * prints the zoom it would put in a URL, with the flag on and off.
 */
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><body></body>', {
  pretendToBeVisual: true,
  url: 'https://example.test/',
})
global.window = dom.window
global.document = dom.window.document
Object.defineProperty(global, 'navigator', {
  value: dom.window.navigator, configurable: true, writable: true,
})
global.HTMLElement = dom.window.HTMLElement
global.SVGElement = dom.window.SVGElement
global.Element = dom.window.Element
global.requestAnimationFrame = dom.window.requestAnimationFrame

// The whole point: a MacBook, a phone, most Windows laptops.
Object.defineProperty(dom.window, 'devicePixelRatio', { value: 2, configurable: true })

const L = (await import('leaflet')).default

// No L.map(): the layer is driven directly below, and building a map in jsdom
// would need a layout engine that does not exist here.

const cases = [
  ['Esri Dark Gray Canvas (deepest z16 in India)', 16],
  ['Esri World Street Map / Imagery (z19)', 19],
  ['OpenTopoMap (z17)', 17],
  ['OpenStreetMap fallback (z19)', 19],
]

/**
 * The zoom this layer would put in a tile URL at `mapZoom`.
 *
 * jsdom has no layout, so `map.setZoom()` never reaches `GridLayer._setView`.
 * Rather than fake a browser, this drives the two Leaflet methods that
 * `_setView` itself calls, in the same order — quoted from leaflet-src.js
 * 1.9.4 so the reproduction can be checked against the source:
 *
 *   _setView:  tileZoom = this._clampZoom(Math.round(zoom));  // line 11659
 *              this._tileZoom = tileZoom;                     // line 11666
 *   _getZoomForUrl: return zoom + zoomOffset;                 // line 12249
 *
 * `zoomOffset` is whatever `initialize` set from `detectRetina` (line 12122).
 * `undefined` is the "no tiles at all" answer Leaflet gives when the map zoom
 * is outside the layer's maxZoom.
 */
function urlZoomFor(maxNativeZoom, detectRetina, mapZoom) {
  const layer = L.tileLayer('https://example.test/{z}/{x}/{y}.png', {
    maxZoom: 20,
    maxNativeZoom,
    detectRetina,
  })
  const tileZoom =
    mapZoom > layer.options.maxZoom ? undefined : layer._clampZoom(Math.round(mapZoom))
  layer._tileZoom = tileZoom
  return tileZoom === undefined ? undefined : layer._getZoomForUrl()
}

let failures = 0
if (!L.Browser.retina) {
  console.error('setup: Browser.retina is false, the run would prove nothing')
  process.exit(1)
}
console.log(`devicePixelRatio = ${dom.window.devicePixelRatio} (Browser.retina = ${L.Browser.retina})\n`)
console.log('What the flag WOULD do, per provider — this is the documented reason it is off:\n')

for (const [label, deepest] of cases) {
  const zoom = deepest // the deepest zoom the operator can reach
  const withFlag = urlZoomFor(deepest, true, zoom)
  const without = urlZoomFor(deepest, false, zoom)
  const show = (z) => (z === undefined ? 'nothing at all (outside maxZoom)' : `z${z}`)
  const overrun = withFlag !== undefined && withFlag > deepest
  // The guard is on the shipped configuration, not on the counterfactual: the
  // flag-on column is evidence, the flag-off column is the assertion.
  if (without === undefined || without > deepest) failures += 1
  console.log(
    `${label}\n` +
    `  map zoom ${zoom} (the deepest level the provider has)\n` +
    `    detectRetina: true   -> requests ${show(withFlag)}` +
    `${overrun ? `  ← ${withFlag - deepest} past the cache, 404` : ''}\n` +
    `    detectRetina: false  -> requests ${show(without)}` +
    `${without !== undefined && without > deepest ? '  ← OVERRUN' : '  ok (shipped)'}\n`,
  )
}

/* Tie the arithmetic to the repo: the numbers above are only relevant if the
 * maps actually leave the flag off. */
const { readFileSync } = await import('node:fs')
for (const name of ['src/components/RiskMap.jsx', 'src/demo/DemoMap.jsx']) {
  const source = readFileSync(new URL(`../${name}`, import.meta.url), 'utf8')
  if (/^\s*detectRetina\s*$/m.test(source)) {
    console.error(`\n${name} passes detectRetina — every row above becomes reality`)
    failures += 1
  }
}

// On a 1x display `initialize` never applies the offset, which is why the bug
// survives review: it is invisible on the reviewer's monitor and only appears
// on the laptop and the phone.
console.log(
  'Note: on a 1x display Leaflet never sets zoomOffset, so all four rows read\n' +
  '"ok" there. That is why this script pins devicePixelRatio to 2.',
)

if (failures) {
  console.error(`\nFAIL: ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\nOK: shipped config requests no provider past its deepest zoom')
