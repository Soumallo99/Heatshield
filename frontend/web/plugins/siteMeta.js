/* Site metadata plugin: canonical URL, Open Graph, structured data, crawler files.
 *
 * Everything here is derived from ONE value — the site URL — because a custom
 * domain has to change in exactly one place:
 *
 *   VITE_SITE_URL=https://heatshield.example/ npm run build
 *
 * Without VITE_SITE_URL the default is this repository's GitHub Pages project
 * URL, which is what the committed build produces. With it, the canonical tag,
 * og:url, og:image, the JSON-LD @id/url, robots.txt, sitemap.xml and llms.txt
 * all move together.
 *
 * The tags are injected at build time rather than written into index.html so
 * that (a) the dev server never claims to be the production origin, and (b) the
 * crawler files and the HTML cannot drift apart.
 */
import { createHash } from 'node:crypto'

import { generate, siteUrl } from '../scripts/gen-site-meta.mjs'

export const SITE_NAME = 'HeatShield'
export const SITE_DESCRIPTION =
  'Ward-level extreme heat early warning and human thermal stress (WBGT) mapping ' +
  'for Kolkata (141 KMC wards) and Delhi NCR. Keyless open data, no API keys.'

/**
 * CSP hash for the one inline block in the document.
 *
 * `script-src 'self'` is deliberately tight — no `unsafe-inline`, no `eval`.
 * The structured-data block is `<script type="application/ld+json">`, which per
 * the HTML spec is a *data block*, not a script, so script-src should not apply
 * to it at all. "Should not" is not a guarantee across browsers and CSP
 * implementations, and a heat-warning page that logs a violation on every load
 * is both alarming and, if enforced, missing its structured data. So the build
 * computes the sha256 of exactly this block and lists it in the policy: the
 * strictest possible allowance for one known, build-generated payload, with no
 * `unsafe-inline` and no nonce to leak.
 */
export function cspHash(text) {
  return `'sha256-${createHash('sha256').update(text, 'utf8').digest('base64')}'`
}

function tags(url) {
  const image = `${url}social-card.png`
  const structuredData = {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'WebApplication',
        '@id': `${url}#application`,
        name: SITE_NAME,
        url,
        applicationCategory: 'HealthApplication',
        operatingSystem: 'Any (web, installable PWA)',
        description: SITE_DESCRIPTION,
        inLanguage: 'en-IN',
        isAccessibleForFree: true,
        offers: { '@type': 'Offer', price: '0', priceCurrency: 'INR' },
        // Named because the project's whole claim is that the numbers are
        // traceable — and because a heat tool that hides its sources is
        // indistinguishable from one that invents them.
        citation: [
          { '@type': 'CreativeWork', name: 'Open-Meteo weather and air-quality API', url: 'https://open-meteo.com' },
          { '@type': 'CreativeWork', name: 'Census of India 2011 ward demographics', url: 'https://censusindia.gov.in' },
          { '@type': 'CreativeWork', name: 'Kolkata Municipal Corporation ward boundaries', url: 'https://www.kmcgov.in' },
          { '@type': 'CreativeWork', name: 'OpenStreetMap contributors', url: 'https://www.openstreetmap.org/copyright' },
        ],
      },
      {
        '@type': 'SoftwareSourceCode',
        '@id': `${url}#source`,
        name: SITE_NAME,
        codeRepository: 'https://github.com/Soumallo99/Heatshield',
        programmingLanguage: ['Python', 'JavaScript'],
        license: 'https://github.com/Soumallo99/Heatshield/blob/main/LICENSE',
      },
    ],
  }

  // Serialised once: the tag content, the CSP hash and the tests all read this
  // same string, so the policy cannot drift from the payload.
  const structuredDataJson = JSON.stringify(structuredData)

  return [
    { tag: 'link', attrs: { rel: 'canonical', href: url } },
    { tag: 'meta', attrs: { property: 'og:type', content: 'website' } },
    { tag: 'meta', attrs: { property: 'og:site_name', content: SITE_NAME } },
    { tag: 'meta', attrs: { property: 'og:locale', content: 'en_IN' } },
    { tag: 'meta', attrs: { property: 'og:url', content: url } },
    {
      tag: 'meta',
      attrs: {
        property: 'og:title',
        content: 'HeatShield — ward-level extreme heat early warning',
      },
    },
    { tag: 'meta', attrs: { property: 'og:description', content: SITE_DESCRIPTION } },
    { tag: 'meta', attrs: { property: 'og:image', content: image } },
    { tag: 'meta', attrs: { property: 'og:image:width', content: '1200' } },
    { tag: 'meta', attrs: { property: 'og:image:height', content: '630' } },
    {
      tag: 'meta',
      attrs: {
        property: 'og:image:alt',
        content:
          'HeatShield share card: “141 wards. One honest number per neighbourhood.”',
      },
    },
    { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
    { tag: 'meta', attrs: { name: 'twitter:title', content: 'HeatShield — extreme heat early warning' } },
    { tag: 'meta', attrs: { name: 'twitter:description', content: SITE_DESCRIPTION } },
    { tag: 'meta', attrs: { name: 'twitter:image', content: image } },
    { tag: 'link', attrs: { rel: 'sitemap', type: 'application/xml', href: `${url}sitemap.xml` } },
    {
      tag: 'script',
      attrs: { type: 'application/ld+json' },
      children: structuredDataJson,
      injectTo: 'head',
    },
  ]
}

/**
 * Add the structured-data hash to the CSP meta tag.
 *
 * Only `script-src` is touched, and only to append one hash-source; every other
 * directive is left exactly as authored. If the tag or the directive is missing
 * the HTML is returned untouched — a build must not invent a policy, and
 * tests/test_security.py fails loudly if the policy is ever absent.
 */
export function withCspHash(html, hash) {
  // The tag is authored across several lines in index.html, so the whitespace
  // between attributes is \s+, not a single space.
  const meta = /(<meta\s+http-equiv="Content-Security-Policy"\s+content=")([^"]+)(")/.exec(html)
  if (!meta || meta[2].includes(hash)) return html
  const policy = meta[2].replace(/script-src 'self'/, `script-src 'self' ${hash}`)
  return html.slice(0, meta.index) + meta[1] + policy + meta[3] + html.slice(meta.index + meta[0].length)
}

export function siteMeta() {
  const url = siteUrl()
  return {
    name: 'heatshield-site-meta',
    config() {
      return {
        // One full build per site URL; changing VITE_SITE_URL must invalidate the
        // HTML rather than silently keeping the previous canonical tag.
        define: { __HS_SITE_URL__: JSON.stringify(url) },
        build: {
          // Explicit, not inherited: source maps in a shipped bundle hand an
          // attacker the original source and every internal URL. There is no
          // error-reporting service that needs them here.
          sourcemap: false,
        },
      }
    },
    transformIndexHtml: {
      order: 'pre',
      handler(html) {
        const injected = tags(url)
        const block = injected.find((entry) => entry.attrs?.type === 'application/ld+json')
        return { html: withCspHash(html, cspHash(block.children)), tags: injected }
      },
    },
    // The crawler files are written on every build (and on `vite dev`, so the
    // dev server serves the same robots.txt as production).
    buildStart() {
      const { files } = generate({ url })
      this.info?.(`site meta for ${url} (${files.join(', ')})`)
    },
  }
}

export default siteMeta
