#!/usr/bin/env node
/**
 * Deadline behaviour of the shared fetch layer (`src/staticApi.js`).
 *
 * Every request in this app carries a 15-second deadline, and the whole point of
 * that is the case nobody tests by hand: a server that answers *slowly*, or
 * stops mid-body. These tests drive the helper with a fake `fetch` so the slow
 * paths run in milliseconds instead of a real quarter-minute each.
 *
 * Written after finding that the timer used to be cleared as soon as the
 * response headers arrived: a server that sent headers and then trickled the
 * body hung the UI forever, which is exactly the failure the deadline exists to
 * prevent.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { readJSON, REQUEST_TIMEOUT_MS, withTimeout } from '../src/staticApi.js'

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

const jsonResponse = (value) => ({
  ok: true,
  status: 200,
  json: async () => value,
})

test('a normal response is parsed and returned', async () => {
  const data = await withFetch(async () => jsonResponse({ ward_id: 7 }), () => readJSON('./x.json'))
  assert.deepEqual(data, { ward_id: 7 })
})

/** A fetch that never answers, but honours an abort — as a real one does. */
const neverAnswers = (url, options) =>
  new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => {
      const error = new Error('the operation was aborted')
      error.name = 'AbortError'
      reject(error)
    })
  })

/** Headers arrive at once; the body stalls until the signal aborts. */
const stallsMidBody = (url, options) => {
  const body = () =>
    new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        const error = new Error('the operation was aborted')
        error.name = 'AbortError'
        reject(error)
      })
    })
  return Promise.resolve({ ok: true, status: 200, json: body })
}

test('a response that never finishes its body hits the deadline', async () => {
  // Headers arrive immediately; the body never resolves. Before the fix this
  // promise never settled and the phone showed a spinner until the user gave up.
  const slow = () =>
    withFetch(stallsMidBody, () => readJSON('./x.json', undefined, Error, { timeoutMs: 40 }))
  await assert.rejects(slow, /did not finish answering within/)
})

test('a connection that is never answered hits the deadline', async () => {
  const hanging = () =>
    withFetch(neverAnswers, () => readJSON('./x.json', undefined, Error, { timeoutMs: 40 }))
  await assert.rejects(hanging, /did not answer within/)
})

test('a caller abort still surfaces as AbortError, not as a timeout', async () => {
  // Unmounts and scenario switches abort in-flight requests; callers ignore
  // AbortError, so it must not be dressed up as a failure the UI reports.
  const controller = new AbortController()
  const aborting = () =>
    withFetch(
      (url, options) =>
        new Promise((resolve, reject) => {
          options.signal.addEventListener('abort', () => {
            const error = new Error('aborted')
            error.name = 'AbortError'
            reject(error)
          })
          setTimeout(() => controller.abort(), 10)
        }),
      () => readJSON('./x.json', controller.signal),
    )
  await assert.rejects(aborting, (error) => error.name === 'AbortError')
})

test('a non-2xx response is an error, with the status attached', async () => {
  await assert.rejects(
    () => withFetch(async () => ({ ok: false, status: 503, json: async () => ({}) }), () => readJSON('./x.json')),
    /503/,
  )
})

test('withTimeout reports its own deadline and cleans up after itself', async () => {
  const guard = withTimeout(undefined, 20)
  assert.equal(guard.timedOut(), false)
  await new Promise((resolve) => setTimeout(resolve, 40))
  assert.equal(guard.timedOut(), true, 'the guard must know the abort was its own')
  guard.cleanup()

  // A guard that is cleaned up must not fire later.
  const quiet = withTimeout(undefined, 20)
  quiet.cleanup()
  await new Promise((resolve) => setTimeout(resolve, 40))
  assert.equal(quiet.timedOut(), false)
  assert.equal(REQUEST_TIMEOUT_MS, 15000, 'the default deadline is part of the contract')
})
