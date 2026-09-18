#!/usr/bin/env node
/*
 * Copy CesiumJS's static runtime assets into `public/cesium/`.
 *
 * The JS half of Cesium is bundled by Vite with the lazy globe chunk, but the
 * library resolves a handful of files by URL at runtime (web workers for
 * terrain/geometry, IAU2006 XYS data, approximate terrain heights, skybox
 * textures) through the global `CESIUM_BASE_URL`. Those files are not modules,
 * so no bundler can inline them.
 *
 * They are copied into the Vite public directory rather than committed:
 * ~7 MB of third-party build output does not belong in git, and the copy is
 * reproducible from the pinned `cesium` dependency. `public/cesium/` is
 * gitignored. Runs automatically before `npm run dev` / `npm run build`.
 *
 * Idempotent: a version stamp makes a repeat run a no-op.
 */
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const web = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = join(web, 'node_modules', 'cesium', 'Build', 'Cesium')
const dest = join(web, 'public', 'cesium')
const stamp = join(dest, '.cesium-version')

// Only what the runtime actually fetches. The minimised/IIFE bundles in
// Build/Cesium/*.js are NOT needed: the globe imports the ESM source.
const DIRECTORIES = ['Assets', 'ThirdParty', 'Workers', 'Widgets']

if (!existsSync(source)) {
  console.error(
    `[cesium] ${source} is missing — run "npm install" in frontend/web first.`,
  )
  process.exit(1)
}

const version = JSON.parse(readFileSync(join(web, 'node_modules', 'cesium', 'package.json'), 'utf8')).version

if (existsSync(stamp) && readFileSync(stamp, 'utf8').trim() === version) {
  console.log(`[cesium] runtime assets already in place (cesium@${version})`)
  process.exit(0)
}

rmSync(dest, { recursive: true, force: true })
mkdirSync(dest, { recursive: true })
for (const name of DIRECTORIES) {
  cpSync(join(source, name), join(dest, name), { recursive: true })
}
writeFileSync(stamp, `${version}\n`)
console.log(`[cesium] copied runtime assets (cesium@${version}) -> public/cesium/`)
