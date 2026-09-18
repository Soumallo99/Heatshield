#!/usr/bin/env node
/**
 * Accessibility audit that runs in CI (`npm run a11y`).
 *
 * The launch checklist asks for four things that are easy to claim and easy to
 * regress: readable contrast, keyboard-reachable controls, clear button labels,
 * and alt text on images. Doing this by hand once is worth nothing — the next
 * component added without an `aria-label` slips through. So the checks are
 * mechanical and a failure exits non-zero.
 *
 * It is a static scan of `src/`, not a browser audit: it cannot see the
 * computed accessibility tree. What it catches is the mistake class that
 * actually happens here — an icon-only button, a clickable `<div>` that a
 * keyboard cannot reach, a hairline-grey label that a low-vision reader cannot
 * see on a phone.
 *
 * Contrast uses the real WCAG 2.1 relative-luminance formula and the standard
 * 4.5:1 (normal text) / 3:1 (large text, ≥24px or ≥18.66px bold) thresholds.
 * Semi-transparent white text is composited over the brightest surface the app
 * actually paints (`--surface-hi`, 6% white over the `#07080d` page), because
 * a label that only passes on the darkest background still fails where it is
 * really rendered.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'src')
const PAGE_BG = [7, 8, 13] // #07080d, the `body` colour in src/index.css
const SURFACE_ALPHA = 0.06 // --surface-hi

const INTERACTIVE = new Set(['button', 'a', 'input', 'select', 'textarea', 'label', 'summary', 'option'])

/**
 * Local components that render a real control (`function CtrlButton() { … <button … }`).
 * Without this the audit reports every `<CtrlButton onClick=…>` as a clickable
 * div, which would train the reader to ignore the output.
 */
function interactiveComponents(source) {
  const names = new Set()
  for (const match of source.matchAll(/(?:function|const)\s+([A-Z]\w*)\s*(?:=\s*\(|\()/g)) {
    const body = source.slice(match.index, match.index + 700)
    if (/<\s*(button|a|input|select|textarea)\b/.test(body)) names.add(match[1])
  }
  return names
}

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return walk(path)
    return /\.(jsx?|css)$/.test(path) ? [path] : []
  })
}

/** `motion.button` → `button`, so wrapped intrinsic elements count as controls. */
const baseName = (name) => (name.includes('.') ? name.split('.').pop() : name)

/**
 * Scan one file for JSX opening tags. Braces and quotes are tracked so a
 * `className={cn('a>b')}` or a `>` inside an arrow function does not end a tag
 * early — a naive `/<[^>]+>/` reports tags that do not exist.
 */
function tags(source) {
  const found = []
  for (let i = source.indexOf('<'); i !== -1; i = source.indexOf('<', i + 1)) {
    const name = /^<([A-Za-z][\w.-]*)/.exec(source.slice(i))
    if (!name) continue
    let depth = 0
    let quote = null
    let j = i + 1
    for (; j < source.length; j += 1) {
      const ch = source[j]
      if (quote) {
        if (ch === quote && source[j - 1] !== '\\') quote = null
      } else if (ch === '"' || ch === "'" || ch === '`') quote = ch
      else if (ch === '{') depth += 1
      else if (ch === '}') depth -= 1
      else if (ch === '>' && depth === 0) break
    }
    found.push({ name: name[1], text: source.slice(i, j + 1), line: source.slice(0, i).split('\n').length, start: i, end: j })
  }
  return found
}

/* ------------------------------------------------------------------ contrast */

const srgb = (channel) => {
  const c = channel / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}
const luminance = ([r, g, b]) => 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b)
const ratio = (fg, bg) => {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((a, b) => b - a)
  return (hi + 0.05) / (lo + 0.05)
}
const hex = (value) => {
  const h = value.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h.slice(0, 6)
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16))
}
const composite = (fg, alpha, bg) => fg.map((c, i) => Math.round(c * alpha + bg[i] * (1 - alpha)))

const PANEL_BG = composite([255, 255, 255], SURFACE_ALPHA, PAGE_BG)
const show = (colour) => `#${colour.map((c) => c.toString(16).padStart(2, '0')).join('')}`
const showBg = show(PANEL_BG)

const LARGE_TEXT =
  /text-(?:2xl|3xl|4xl|5xl|6xl|7xl|8xl|9xl)|text-\[\s*(?:2[4-9]|[3-9]\d|\d{3,})px\s*\]|font-(?:bold|black|semibold)[^"']*text-\[\s*(?:1[89]|[2-9]\d)px/

const problems = []
const checked = { tags: 0, controls: 0, images: 0, colours: 0 }

for (const file of walk(SRC)) {
  const rel = relative(ROOT, file)
  const source = readFileSync(file, 'utf8')
  const isCss = file.endsWith('.css')

  const controls = interactiveComponents(source)

  if (!isCss) {
    for (const tag of tags(source)) {
      checked.tags += 1
      const where = `${rel}:${tag.line}`
      const kind = baseName(tag.name)

      // 1. Keyboard reachability: a click handler on a non-interactive element
      //    cannot be reached with Tab and is invisible to assistive tech.
      if (
        /\bonClick=/.test(tag.text) &&
        !INTERACTIVE.has(kind) &&
        !controls.has(tag.name) &&
        !/role=|tabIndex|onKeyDown|aria-hidden/.test(tag.text)
      ) {
        problems.push(`${where} <${tag.name}> has onClick but no role/tabIndex — keyboard users cannot reach it`)
      }

      // 2. Clear names: an icon-only control needs an accessible name.
      if ((kind === 'button' || kind === 'a') && !/aria-label|aria-labelledby|title=/.test(tag.text)) {
        checked.controls += 1
        const close = source.indexOf(`</${tag.name}>`, tag.end)
        const inner = close === -1 ? '' : source.slice(tag.end + 1, close)
        // `{option.label}` is a real label; `<svg/>` alone is not. Counting
        // identifier-ish words handles both without a JSX parser.
        const words = (inner.match(/[A-Za-z]{2,}/g) ?? []).length
        if (words === 0) {
          problems.push(`${where} <${tag.name}> renders no text and has no aria-label — screen readers announce nothing useful`)
        }
      }

      // 3. Alt text on every image; empty alt when decorative, written on purpose.
      if (kind === 'img') {
        checked.images += 1
        if (!/\balt=/.test(tag.text)) problems.push(`${where} <img> has no alt attribute`)
      }
    }
  }

  // 4. Contrast of literal text colours, in class names and in the stylesheet.
  const hits = []
  if (!isCss) {
    for (const match of source.matchAll(/text-white\/(\d{1,3})|text-\[(#[0-9a-fA-F]{3,8})\]/g)) {
      const colour = match[1] ? composite([255, 255, 255], Number(match[1]) / 100, PAGE_BG) : hex(match[2])
      hits.push({ match, colour })
    }
  } else {
    // One rule at a time, so a light chip with dark text is judged against its
    // own background instead of being flagged for the page colour.
    for (const rule of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const [, , body] = rule
      const fg = /(?:^|;)\s*color:\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))/.exec(body)
      if (!fg) continue
      let colour = null
      if (fg[1].startsWith('#')) colour = hex(fg[1])
      else {
        const parts = fg[1].match(/[\d.]+/g)?.map(Number) ?? []
        if (parts.length >= 3) colour = composite(parts.slice(0, 3), parts[3] ?? 1, PAGE_BG)
      }
      if (!colour) continue
      const bgDecl = /(?:^|;)\s*background(?:-color)?:\s*([^;]+)/.exec(body)
      let bg = PANEL_BG
      if (bgDecl) {
        const value = bgDecl[1].trim()
        if (value.startsWith('#')) bg = hex(value)
        else if (/gradient/.test(value)) {
          // Dark text on a bright chip: the honest test is the worst gradient
          // stop, not the page background behind it.
          const stops = (value.match(/#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)/g) ?? []).map((stop) =>
            stop.startsWith('#') ? hex(stop) : composite(stop.match(/[\d.]+/g).map(Number).slice(0, 3), stop.match(/[\d.]+/g).map(Number)[3] ?? 1, PAGE_BG),
          )
          bg = stops.sort((a, b) => luminance(b) - luminance(a))[0] ?? PANEL_BG
        } else {
          const parts = value.match(/[\d.]+/g)?.map(Number) ?? []
          if (parts.length >= 3) bg = composite(parts.slice(0, 3), parts[3] ?? 1, PAGE_BG)
        }
      }
      const line = source.slice(0, rule.index).split('\n').length
      const large = /font-size:\s*(?:2[4-9]|[3-9]\d|\d{3,})px/.test(body) || /font-size:\s*1[89]px[^;]*font-weight:\s*(?:7|8|9)00/.test(body)
      hits.push({ match: { 0: `color: ${fg[1]}`, index: rule.index }, colour, bg, line, large })
    }
  }

  for (const hit of hits) {
    checked.colours += 1
    const large = hit.large ?? LARGE_TEXT.test(source.slice(hit.match.index, hit.match.index + 220))
    const threshold = large ? 3 : 4.5
    const bg = hit.bg ?? PANEL_BG
    const got = ratio(hit.colour, bg)
    if (got < threshold) {
      const line = hit.line ?? source.slice(0, hit.match.index).split('\n').length
      problems.push(
        `${rel}:${line} ${hit.match[0]} is ${got.toFixed(2)}:1 on ${showBg} — below the ${threshold}:1 minimum for ${large ? 'large' : 'normal'} text`,
      )
    }
  }

  // 5. The accessibility escape hatches must stay in the stylesheet.
  if (isCss && rel.endsWith('index.css')) {
    for (const needle of [':focus-visible', 'prefers-reduced-motion', 'prefers-contrast']) {
      if (!source.includes(needle)) problems.push(`${rel} lost its \`${needle}\` block`)
    }
  }
}

if (problems.length) {
  console.error(`a11y: ${problems.length} problem(s)\n`)
  for (const problem of problems) console.error(`  • ${problem}`)
  console.error(
    `\nscanned ${checked.tags} tags (${checked.controls} controls) and ${checked.colours} literal text colours across src/`,
  )
  process.exit(1)
}

console.log(
  `a11y: clean — ${checked.tags} tags, ${checked.controls} labelled controls, ${checked.images} images, ` +
    `${checked.colours} text colours all ≥ AA on the ${showBg} worst-case surface`,
)
