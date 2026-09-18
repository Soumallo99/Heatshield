#!/usr/bin/env node
/**
 * Route chunk loading: the policy that makes a tab press work.
 *
 * The bug this covers was reported from the outside — "when I press on the
 * Citizen tab I have to reload the page before it opens". Two things were wrong:
 * the fetch did not start until the outgoing page finished animating, and a
 * failed fetch (the normal consequence of a deploy whose chunk hashes changed)
 * was a dead end. Both are policy, so both are testable without a browser:
 *
 *   * retried once, then recovered by a reload that happens exactly once;
 *   * one fetch shared by the preload and by React.lazy;
 *   * a rejection is never remembered, or the second attempt would fail from
 *     the cache instead of trying the network;
 *   * every route in routes.js has a chunk, and every chunk has an importer.
 *
 * The reload is injected, so these tests never reload anything.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  CHUNK_NAMES,
  loadChunk,
  recoverOnce,
  RELOAD_FLAG,
  resetChunkCache,
  ROUTE_CHUNK,
} from '../src/lazyRoute.js'
import { ROUTES, routeForTarget } from '../src/routes.js'

/** A sessionStorage stand-in. */
function fakeStorage(initial = {}) {
  const map = new Map(Object.entries(initial))
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
    dump: () => Object.fromEntries(map),
  }
}

const noSleep = async () => {}

test('a chunk loads, and the second request reuses the same fetch', async () => {
  resetChunkCache()
  let calls = 0
  const importer = async () => {
    calls += 1
    return { default: () => null }
  }
  const [first, second] = await Promise.all([
    loadChunk('landing', importer, { sleep: noSleep }),
    loadChunk('landing', importer, { sleep: noSleep }),
  ])
  assert.equal(calls, 1, 'a preload and a render must share one network request')
  assert.equal(first, second)
})

test('a flaky fetch is retried once and then succeeds', async () => {
  resetChunkCache()
  let calls = 0
  const importer = async () => {
    calls += 1
    if (calls === 1) throw new TypeError('Failed to fetch dynamically imported module')
    return { default: 'route' }
  }
  const module = await loadChunk('phone', importer, { sleep: noSleep })
  assert.equal(calls, 2, 'one retry, not a loop')
  assert.equal(module.default, 'route')
})

test('a chunk that is really gone is recovered once, and then reports itself', async () => {
  resetChunkCache()
  const storage = fakeStorage()
  const reloads = []
  const importer = async () => {
    throw new TypeError('Failed to fetch dynamically imported module')
  }

  await assert.rejects(
    loadChunk('phone', importer, {
      sleep: noSleep,
      onFailure: (error) => {
        recoverOnce('phone', { storage, reload: () => reloads.push('reload') })
        throw error
      },
    }),
    /dynamically imported/,
  )
  assert.deepEqual(reloads, ['reload'], 'the stale-deploy case self-heals with one reload')
  assert.equal(storage.dump()[RELOAD_FLAG], 'phone')

  // A second failure of the same chunk in the same session must NOT reload
  // again: if a reload did not fix it, the problem is not stale caching.
  resetChunkCache()
  await assert.rejects(
    loadChunk('phone', importer, {
      sleep: noSleep,
      onFailure: (error) => {
        recoverOnce('phone', { storage, reload: () => reloads.push('reload') })
        throw error
      },
    }),
  )
  assert.deepEqual(reloads, ['reload'], 'no reload loop, ever')
})

test('one bad chunk does not stop the next one from self-healing', async () => {
  const storage = fakeStorage({ [RELOAD_FLAG]: 'phone' })
  const reloads = []
  assert.equal(recoverOnce('dashboard', { storage, reload: () => reloads.push('dashboard') }), true)
  assert.deepEqual(reloads, ['dashboard'])
  assert.equal(storage.dump()[RELOAD_FLAG], 'dashboard')
})

test('with storage unavailable there is no reload at all', () => {
  // Without somewhere to remember the attempt, a reload cannot be bounded — and
  // an unbounded refresh loop is worse than an error message.
  assert.equal(recoverOnce('phone', { storage: null, reload: () => assert.fail('must not reload') }), false)
})

test('a rejection is not cached: the next attempt tries the network again', async () => {
  resetChunkCache()
  let calls = 0
  const importer = async () => {
    calls += 1
    if (calls === 1) throw new Error('offline')
    return { default: 'route' }
  }
  await assert.rejects(loadChunk('demo', importer, { attempts: 1, sleep: noSleep }), /offline/)
  const module = await loadChunk('demo', importer, { sleep: noSleep })
  assert.equal(module.default, 'route')
  assert.equal(calls, 2)
})

test('a successful load re-arms the guard for a future deploy', async () => {
  resetChunkCache()
  const storage = fakeStorage({ [RELOAD_FLAG]: 'phone' })
  await loadChunk('phone', async () => ({ default: 'route' }), { storage, sleep: noSleep })
  assert.equal(storage.dump()[RELOAD_FLAG], undefined, 'the next deploy gets its own chance')
})

test('every target a button can navigate to resolves to a real chunk', () => {
  // The nav handlers pass hash keys, not page names: the Overview button goes to
  // '' and the phone button to 'phone'. If the preload does not resolve those the
  // head start is silently skipped — which is how it behaved before this test.
  for (const target of ['', 'dashboard', 'phone', 'mobile', 'demo', 'privacy', 'terms', 'nope']) {
    const name = ROUTE_CHUNK[routeForTarget(target)]
    assert.ok(CHUNK_NAMES.includes(name), `${target || "(empty)"} -> ${name}`)
  }
})

test('every route has a chunk, and every chunk is declared', () => {
  for (const route of Object.values(ROUTES)) {
    assert.ok(ROUTE_CHUNK[route], `route "${route}" has no chunk`)
  }
  assert.ok(ROUTE_CHUNK.notfound, 'the 404 page needs a chunk too')
  for (const chunk of Object.values(ROUTE_CHUNK)) {
    assert.ok(CHUNK_NAMES.includes(chunk), `"${chunk}" is mapped but not declared in CHUNK_NAMES`)
  }
  for (const chunk of CHUNK_NAMES) {
    assert.ok(Object.values(ROUTE_CHUNK).includes(chunk), `"${chunk}" is declared but no route reaches it`)
  }
})
