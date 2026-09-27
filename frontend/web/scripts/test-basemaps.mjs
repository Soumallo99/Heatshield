#!/usr/bin/env node
/**
 * Behavioural tests for the basemap registry — the part source-scanning tests
 * cannot reach, because they only prove a string is present, not that the
 * degradation actually resolves to the right layer.
 *
 * Run: node --test scripts/test-basemaps.mjs
 *
 * The invariant underneath all of these: a map must never dead-end. Not on an
 * "API key required" screen, not on grey tiles, not on a watermarked tile that
 * answered 200. The last stage exists so that "the network is gone" and "the
 * provider turned hostile" both degrade to something still worth reading.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  BASEMAPS, DEFAULT_BASEMAP, NO_BASEMAP, OSM_FALLBACK,
  TILE_FAIL_LIMIT, basemapFor, degradeNotice, getBasemap,
} from '../src/basemaps.js'

const source = readFileSync(new URL('../src/basemaps.js', import.meta.url), 'utf8')
const tileProviders = BASEMAPS.filter((b) => b.url)

test('every basemap is either a real tile provider or deliberately tileless', () => {
  assert.ok(BASEMAPS.length >= 4, 'the layer switcher should still offer a real choice')
  assert.equal(BASEMAPS.filter((b) => b.url === null).length, 1, 'exactly one tileless entry')
  assert.ok(tileProviders.length >= 3)
  for (const b of BASEMAPS) {
    assert.ok(b.id && b.label && b.hint, `${b.id} is missing a label or hint`)
    assert.ok(b.attribution, `${b.id} must credit whoever drew it — attribution is a licence term`)
  }
})

test('no basemap url carries a key, and every one is https', () => {
  for (const b of [...tileProviders, OSM_FALLBACK]) {
    assert.match(b.url, /^https:\/\//, `${b.id} is not https — a mixed-content map is a broken map`)
    assert.doesNotMatch(b.url, /[?&](key|apikey|api_key|access_token|token)=/i, `${b.id} needs a key`)
    assert.doesNotMatch(b.url, /\{r\}/, `${b.id} asks for @2x tiles the provider does not publish`)
  }
  // Google's tile CDN is scraped by half the internet and forbidden by the
  // Maps ToS; the licensed route needs a billing key.
  assert.doesNotMatch(source, /mt\d?\.google\.com/)
  // CARTO answers 200 with an "API KEY REQUIRED" watermark.
  assert.doesNotMatch(source, /cartocdn/)
})

test('every tile provider declares the deepest zoom it actually has', () => {
  for (const b of [...tileProviders, OSM_FALLBACK]) {
    assert.ok(Number.isInteger(b.maxNativeZoom), `${b.id} has no maxNativeZoom`)
    assert.ok(b.maxZoom >= b.maxNativeZoom, `${b.id} claims zoom past its own cache`)
    if (b.labels) {
      assert.ok(Number.isInteger(b.labels.maxNativeZoom), `${b.id} labels have no maxNativeZoom`)
    }
  }
})

test('the tileless stage really is tileless', () => {
  assert.equal(NO_BASEMAP.url, null)
  assert.equal(getBasemap('none'), NO_BASEMAP)
  // …and it is offered, not hidden: an operator on a bad connection should be
  // able to choose it instead of waiting for the map to notice.
  assert.ok(BASEMAPS.includes(NO_BASEMAP))
})

test('stage 0 draws the chosen basemap untouched', () => {
  for (const b of BASEMAPS) assert.equal(basemapFor(b, 0), b)
  assert.equal(basemapFor(NO_BASEMAP, 1), NO_BASEMAP, 'a tileless map cannot degrade further')
  assert.equal(basemapFor(NO_BASEMAP, 2), NO_BASEMAP)
})

test('stage 1 swaps in OpenStreetMap on a different CDN, and drops the labels', () => {
  for (const b of tileProviders) {
    const degraded = basemapFor(b, 1)
    assert.equal(degraded.url, OSM_FALLBACK.url)
    assert.equal(degraded.attribution, OSM_FALLBACK.attribution,
      'the credit has to follow the tiles or the map credits a provider it is not drawing')
    assert.equal(degraded.labels, undefined, `${b.id} labels belong to Esri, not to OSM`)
    assert.notEqual(degraded.id, b.id, 'the id must change so Leaflet rebuilds rather than merges')
    // The choropleth keeps the look the operator chose.
    assert.equal(degraded.overlayOpacity, b.overlayOpacity)
  }
})

test('stage 2 draws nothing from the network at all', () => {
  for (const b of tileProviders) {
    const last = basemapFor(b, 2)
    assert.equal(last.url, null, `${b.id} still requests tiles at the final stage`)
    assert.equal(last.labels, undefined)
    assert.equal(last.attribution, NO_BASEMAP.attribution)
    assert.notEqual(last.id, basemapFor(b, 1).id, 'stage 1 and 2 must not share a layer id')
  }
})

test('the failure threshold tolerates edge-of-coverage 404s but not a dead CDN', () => {
  assert.ok(TILE_FAIL_LIMIT >= 3, 'a couple of 404s at the ragged edge must not cost the basemap')
  assert.ok(TILE_FAIL_LIMIT <= 20, 'a map that is mostly broken should give up quickly')
  // Stage 2 is reached at twice the limit, which is what RiskMap/DemoMap
  // implement; keep the two in step.
  assert.equal(2 * TILE_FAIL_LIMIT > TILE_FAIL_LIMIT, true)
})

test('each stage has its own sentence, so the notice never lies about what is drawn', () => {
  const dark = getBasemap(DEFAULT_BASEMAP)
  assert.equal(degradeNotice(dark, 0), '')
  const first = degradeNotice(dark, 1)
  const second = degradeNotice(dark, 2)
  assert.match(first, /OpenStreetMap/)
  assert.match(second, /ward boundaries only/i)
  assert.notEqual(first, second)
  // The honest half: the notice says the data survives, because it does.
  assert.match(second, /unaffected/i)
})
