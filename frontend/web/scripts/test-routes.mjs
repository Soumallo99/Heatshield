#!/usr/bin/env node
/**
 * Frontend checks that need no browser and no test framework: routing, page
 * metadata, console hygiene, and the generated crawler files.
 *
 * Run with `npm test` (plain `node --test`). Deliberately dependency-free —
 * adding vitest to a project this size to assert six facts about a pure
 * function would cost more than the tests are worth.
 *
 * Why these four things:
 *   • the router is the only way a visitor reaches a page, and "unknown hash is
 *     a 404, not the landing page" has already regressed once;
 *   • every page must carry a unique title — duplicate titles are the classic
 *     SEO miss a checklist cannot see;
 *   • a stray `console.log` left in the production bundle is the difference
 *     between a clean console and a support ticket;
 *   • robots/sitemap/llms must keep agreeing with site-pages.json.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

import { ROUTES, resolveRoute } from '../src/routes.js'
import { DEFAULT_SITE_URL, INDEXABLE, PAGES, generate, siteUrl } from './gen-site-meta.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const WEB = join(HERE, '..')
const pages = JSON.parse(readFileSync(join(WEB, 'src', 'site-pages.json'), 'utf8'))

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return walk(path)
    return /\.(jsx?|css)$/.test(path) ? [path] : []
  })
}

/* ------------------------------------------------------------------- routes */

test('the landing page is the empty hash', () => {
  assert.equal(resolveRoute(''), 'landing')
  assert.equal(resolveRoute('#'), 'landing')
  assert.equal(resolveRoute('#/'), 'landing')
})

test('known routes resolve, and aliases agree', () => {
  assert.equal(resolveRoute('#/dashboard'), 'dashboard')
  assert.equal(resolveRoute('#/phone'), 'phone')
  assert.equal(resolveRoute('#/mobile'), 'phone')
  assert.equal(resolveRoute('#/demo'), 'demo')
  assert.equal(resolveRoute('#/privacy'), 'privacy')
  assert.equal(resolveRoute('#/terms'), 'terms')
})

test('a query string is not part of the route', () => {
  assert.equal(resolveRoute('#/phone?static'), 'phone')
  assert.equal(resolveRoute('#/dashboard?scenario=4'), 'dashboard')
})

test('an unknown hash is a 404, never a silent landing page', () => {
  for (const hash of ['#/nope', '#/privacy/extra', '#/landing', '#/../etc/passwd', '#/%20']) {
    assert.equal(resolveRoute(hash), 'notfound', `${hash} must not render the landing page`)
  }
})

test('every reachable page has metadata, and no two titles collide', () => {
  const titles = new Map()
  for (const route of [...new Set([...Object.values(ROUTES), 'notfound'])]) {
    const meta = pages[route]
    assert.ok(meta, `site-pages.json is missing an entry for "${route}"`)
    assert.ok(meta.title?.length > 10, `${route} needs a real title`)
    assert.ok(meta.description?.length > 40, `${route} needs a real meta description`)
    assert.ok(!titles.has(meta.title), `"${route}" shares its title with "${titles.get(meta.title)}"`)
    titles.set(meta.title, route)
  }
})

/* ----------------------------------------------------------- console hygiene */

test('only src/log.js may touch the console', () => {
  const offenders = []
  for (const file of walk(join(WEB, 'src'))) {
    if (file.endsWith('log.js')) continue
    const source = readFileSync(file, 'utf8')
    source.split('\n').forEach((line, index) => {
      // Comments explain the policy; they are not calls.
      if (/console\.(log|warn|error|info|debug|trace)\s*\(/.test(line) && !/^\s*(\*|\/\/)/.test(line)) {
        offenders.push(`${relative(WEB, file)}:${index + 1}`)
      }
    })
  }
  assert.deepEqual(offenders, [], 'route these through src/log.js — dev-gated, reportable, no console noise in production')
})

test('the production bundle carries no debug logging', () => {
  const dist = join(WEB, 'dist', 'assets')
  let files
  try {
    files = readdirSync(dist).filter((name) => name.endsWith('.js'))
  } catch {
    return // no build in this checkout — `npm run build` covers it in CI
  }
  // Vendor chunks are unmodified third-party bundles that ship their own
  // diagnostics (Cesium and Leaflet both log). The rule is about the code in
  // this repository, exactly as the external-host allow-list is.
  const VENDOR = /^(cesium|leaflet|react|motion|vite-helpers)-/
  const bad = []
  for (const name of files) {
    if (VENDOR.test(name)) continue
    const bundle = readFileSync(join(dist, name), 'utf8')
    // Any console call at all: every one of them must be DEV-gated, and the
    // minifier drops a dead `if (false)` branch, so none should survive.
    for (const call of bundle.match(/console\.[a-z]+\(/g) ?? []) {
      bad.push(`${name}: ${call}`)
    }
  }
  assert.deepEqual(bad, [], 'console calls survived the build — they must be DEV-gated and eliminated')
})

/* ------------------------------------------------------------ crawler files */

test('site URL defaults to the GitHub Pages project path and can be overridden', () => {
  assert.equal(siteUrl.call(null), process.env.VITE_SITE_URL || DEFAULT_SITE_URL)
  assert.ok(siteUrl().endsWith('/'), 'the site URL always ends in a slash')
})

test('the 404 page is never advertised to crawlers', () => {
  assert.ok(!INDEXABLE.some((page) => page.id === 'notfound'), 'sitemap/llms must exclude the 404')
  assert.equal(PAGES.length, INDEXABLE.length + 1)
})

test('generated crawler files list every indexable page once', () => {
  const { url } = generate()
  const sitemap = readFileSync(join(WEB, 'public', 'sitemap.xml'), 'utf8')
  const robots = readFileSync(join(WEB, 'public', 'robots.txt'), 'utf8')
  const llms = readFileSync(join(WEB, 'public', 'llms.txt'), 'utf8')

  assert.ok(robots.includes(`Sitemap: ${url}sitemap.xml`), 'robots.txt must point at the sitemap')
  assert.ok(robots.includes('Disallow: /api/subscribers'), 'admin routes stay out of the crawl')
  for (const page of INDEXABLE) {
    const loc = `${url}${page.path ? `#/${page.path}` : ''}`
    assert.ok(sitemap.includes(`<loc>${loc}</loc>`), `sitemap.xml is missing ${loc}`)
    assert.ok(llms.includes(`](${loc})`), `llms.txt is missing ${loc}`)
  }
  assert.ok(!sitemap.includes('notfound'), 'the 404 must not be in the sitemap')
})
