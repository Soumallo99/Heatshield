#!/usr/bin/env node
/**
 * The app, clicked. Mounts the real `App` in a DOM and presses its controls.
 *
 * WHY THIS EXISTS
 *
 * The Citizen-tab report — "when I press on the Citizens tab I have to reload the
 * page unless it won't open" — was a *behaviour* claim, and the fix for it was
 * three separate pieces of wiring (a preload on the press, no exit-animation
 * gate, and a network-first navigation document). Source assertions can show the
 * wiring is present; only running the thing shows the tab opens.
 *
 * There is no browser in the environments this runs in, so this mounts the real
 * components in jsdom instead: esbuild bundles `src/App.jsx`, the bundle runs
 * against a stubbed DOM, and the nav buttons get real click events. Everything
 * asserted here is something a person would do with a finger:
 *
 *   * the Citizen tab opens on the press, without a reload, from a cold start;
 *   * leaving the phone page works through its own control;
 *   * every route renders content and logs nothing to the console;
 *   * nothing anywhere throws.
 *
 * Not covered on purpose: anything that needs a real layout or WebGL engine
 * (Leaflet tiles, the Cesium globe). Those are checked by their own tests and,
 * for tile metadata, against the providers themselves.
 */
import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { build, stop as stopEsbuild } from 'esbuild'
import { JSDOM, VirtualConsole } from 'jsdom'

// esbuild keeps a service process alive between builds; without this the test
// process never exits and CI sits at the timeout instead of reporting.
after(async () => {
  await stopEsbuild()
})

// The test's own waiting must use a *ref'd* timer: the app's timers are
// deliberately unref'd below so the process can exit, and an unref'd sleep lets
// the event loop drain mid-test ("Promise resolution is still pending but the
// event loop has already resolved").
const nativeSetTimeout = globalThis.setTimeout
const nativeSetInterval = globalThis.setInterval

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..')
const SHELL = path.join(HERE, 'fixtures', 'app-shell.html')

/** jsdom has no layout engine and no observers; the app only needs them to exist. */
function stubEnvironment(window) {
  globalThis.window = window
  globalThis.document = window.document
  Object.defineProperty(globalThis, 'navigator', { value: window.navigator, configurable: true })
  globalThis.requestAnimationFrame = window.requestAnimationFrame.bind(window)
  globalThis.cancelAnimationFrame = window.cancelAnimationFrame.bind(window)
  globalThis.getComputedStyle = window.getComputedStyle.bind(window)
  // React and the animation library reach for DOM constructors by name
  // (SVGElement for an icon, HTMLDivElement for a motion node). Copy the
  // window's own uppercase constructors across rather than guessing the list,
  // which is what left `SVGElement is not defined` in an earlier version of
  // this file. Anything Node already defines (Response, URL, Blob) is kept.
  for (const name of Object.getOwnPropertyNames(window)) {
    if (!/^[A-Z]/.test(name) || name in globalThis) continue
    const value = window[name]
    if (typeof value !== 'function') continue
    try {
      globalThis[name] = value
    } catch {
      /* non-writable global — the app does not need every one of them */
    }
  }
  for (const target of [globalThis, window]) {
    target.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
    target.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} }
  }
  // Timers and the scheduler are the reason a suite like this hangs after its
  // assertions pass: React's scheduler holds a MessageChannel port open and the
  // app's refresh intervals are Node timers, so the event loop stays alive for
  // as long as they tick. Unref'd timers still fire while the tests run but never
  // keep the process up, and removing MessageChannel sends the scheduler down its
  // setTimeout path instead.
  const unref = (handle) => {
    if (handle && typeof handle.unref === 'function') handle.unref()
    return handle
  }
  globalThis.setTimeout = window.setTimeout = (...args) => unref(nativeSetTimeout(...args))
  globalThis.setInterval = window.setInterval = (...args) => unref(nativeSetInterval(...args))
  globalThis.requestAnimationFrame = (callback) => globalThis.setTimeout(() => callback(Date.now()), 16)
  globalThis.cancelAnimationFrame = (handle) => globalThis.clearTimeout(handle)

  const media = () => ({
    matches: false,
    media: '',
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })
  delete globalThis.MessageChannel
  globalThis.matchMedia = window.matchMedia = media
  // No API is running here: every request answers with an empty object, which is
  // the "everything is unreachable" case the UI is supposed to survive.
  const fetchStub = async () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
  window.fetch = fetchStub
  globalThis.fetch = fetchStub
  window.scrollTo = () => {}   // jsdom throws "Not implemented" otherwise
}

async function mountApp() {
  const dir = await mkdtemp(path.join(tmpdir(), 'hs-shell-'))
  const outfile = path.join(dir, 'bundle.js')
  const entry = path.join(dir, 'entry.jsx')
  await import('node:fs').then(({ writeFileSync }) =>
    writeFileSync(
      entry,
      [
        "import React from 'react'",
        "import { createRoot } from 'react-dom/client'",
        `import App from ${JSON.stringify(path.join(ROOT, 'src', 'App.jsx'))}`,
        "createRoot(document.getElementById('root')).render(React.createElement(App))",
        '',
      ].join('\n'),
      'utf8',
    ),
  )

  await build({
    entryPoints: [entry],
    bundle: true,
    outfile,
    format: 'iife',
    jsx: 'automatic',
    loader: { '.css': 'text', '.png': 'dataurl', '.json': 'json' },
    define: {
      'import.meta.env.PROD': 'true',
      'import.meta.env.DEV': 'false',
      'import.meta.env.BASE_URL': '"/"',
      'process.env.NODE_ENV': '"production"',
    },
    alias: {
      react: path.join(ROOT, 'node_modules', 'react'),
      'react-dom': path.join(ROOT, 'node_modules', 'react-dom'),
    },
    logLevel: 'error',
  })

  // jsdom has no navigation, so a `location.reload()` shows up as a
  // "Not implemented: navigation" error on the virtual console. Counting those
  // is how this suite proves the Citizen tab did *not* need a reload — the
  // location object itself cannot be replaced.
  const reloadAttempts = []
  const virtualConsole = new VirtualConsole()
  virtualConsole.on('jsdomError', (error) => {
    const message = String(error?.message ?? error)
    if (/Not implemented: navigation/.test(message)) reloadAttempts.push(message)
  })

  const dom = new JSDOM(readFileSync(SHELL, 'utf8'), {
    url: 'http://localhost:4173/',
    pretendToBeVisual: true,
    runScripts: 'outside-only',
    virtualConsole,
  })
  stubEnvironment(dom.window)

  const pageErrors = []
  const consoleNoise = []
  dom.window.addEventListener('error', (event) => pageErrors.push(String(event.error || event.message)))
  dom.window.addEventListener('unhandledrejection', (event) => pageErrors.push(`unhandled: ${event.reason}`))
  for (const level of ['error', 'warn']) {
    const original = dom.window.console[level].bind(dom.window.console)
    dom.window.console[level] = (...args) => {
      consoleNoise.push(`${level}: ${args.map(String).join(' ')}`)
      return original(...args)
    }
  }

  await import(pathToFileURL(outfile).href)

  return {
    window: dom.window,
    // A reload is a *failure* signal here: the tab opening, and every route,
    // must work in the page the visitor is already on.
    reloads: () => reloadAttempts.length,
    pageErrors,
    consoleNoise,
    // Close the window as well as deleting the bundle: jsdom keeps timers and
    // event listeners alive, and a suite that never exits hangs CI.
    cleanup: async () => {
      dom.window.close()
      await rm(dir, { recursive: true, force: true })
    },
  }
}

const sleep = (ms) => new Promise((resolve) => nativeSetTimeout(resolve, ms))

async function waitFor(predicate, timeoutMs = 6000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (predicate()) return true
    await sleep(50)
  }
  return predicate()
}

const text = (window) => window.document.body.textContent || ''
const phoneShell = (window) => Boolean(window.document.querySelector('.phone-shell'))
const navButtons = (window) => [...window.document.querySelectorAll('button')]
const clickByText = (window, needle) => {
  const button = navButtons(window).find((b) => (b.textContent || '').includes(needle))
  if (!button) return false
  button.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
  return true
}

test('the Citizen tab opens on the press, from a cold start, with no reload', async (t) => {
  const app = await mountApp()
  t.after(() => app.cleanup())

  const mounted = await waitFor(() => navButtons(app.window).length >= 4)
  assert.ok(mounted, `the shell never mounted (${text(app.window).slice(0, 120)})`)
  assert.equal(app.reloads(), 0, 'nothing has failed yet, so nothing should have reloaded')

  const started = Date.now()
  assert.ok(clickByText(app.window, 'Citizen'), 'the Citizen tab is not on screen')
  const opened = await waitFor(() => phoneShell(app.window), 4000)

  assert.ok(opened, `the Citizen page never appeared: "${text(app.window).slice(0, 200)}"`)
  assert.ok(Date.now() - started < 4000, 'the Citizen page took longer than a person would wait')
  assert.equal(app.reloads(), 0, 'the Citizen tab needed a reload — that is the reported bug')
  assert.deepEqual(app.pageErrors, [])
})

test('the phone page can be left through its own control', async (t) => {
  const app = await mountApp()
  t.after(() => app.cleanup())
  await waitFor(() => navButtons(app.window).length >= 4)

  clickByText(app.window, 'Citizen')
  assert.ok(await waitFor(() => phoneShell(app.window)), 'the Citizen page did not open')

  const left = clickByText(app.window, 'Ops') || clickByText(app.window, 'Back')
  assert.ok(left, 'the phone page has no way back')
  assert.ok(await waitFor(() => !phoneShell(app.window)), 'the phone page stayed on screen after leaving')
  assert.equal(app.reloads(), 0)
})

test('every route renders content and says nothing in the console', async (t) => {
  const app = await mountApp()
  t.after(() => app.cleanup())
  await waitFor(() => navButtons(app.window).length >= 4)

  const problems = []
  for (const route of ['', 'dashboard', 'phone', 'demo', 'privacy', 'terms', 'nope']) {
    const before = app.consoleNoise.length
    app.window.location.hash = `#/${route}`
    await waitFor(() => text(app.window).length > 100, 6000)
    const rendered = text(app.window).length
    const noise = app.consoleNoise.slice(before)
    if (rendered <= 100) problems.push(`#/${route || '(landing)'} rendered ${rendered} characters`)
    if (noise.length) problems.push(`#/${route || '(landing)'} logged ${noise[0]}`)
  }

  assert.deepEqual(problems, [])
  assert.deepEqual(app.pageErrors, [])
  assert.equal(app.reloads(), 0, 'no route needed a reload')
})
