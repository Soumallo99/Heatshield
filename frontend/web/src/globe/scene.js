/**
 * The globe scene: viewer + keyless source controller + HeatShield layers.
 *
 * The `CESIUM_BASE_URL` step matters. CesiumJS fetches its workers and asset
 * files by URL at runtime (see frontend/web/scripts/copy-cesium-assets.mjs);
 * when the library is bundled, its own base-URL detection would point at the
 * hashed chunk directory and every worker would 404. Setting the global before
 * the first Cesium call is the supported override, and doing it here keeps it
 * scope-relative so a GitHub Pages subdirectory deployment still resolves.
 */
import * as Cesium from 'cesium'
import { GlobeSourceController } from './controller.js'
import { createGlobeSources } from './sources.js'
import { createGlobeViewer } from './viewer.js'

/** Where the copied CesiumJS runtime assets live (public/cesium/). */
function configureCesiumBaseUrl() {
  if (typeof window === 'undefined') return ''
  if (window.CESIUM_BASE_URL) return window.CESIUM_BASE_URL
  const base = new URL('cesium/', document.baseURI).href
  window.CESIUM_BASE_URL = base
  return base
}

/** Camera presets: the two cities this platform covers. */
const AREA_VIEWS = {
  kolkata: { longitude: 88.3639, latitude: 22.5726, height: 42000, pitch: -62 },
  delhi: { longitude: 77.28, latitude: 28.58, height: 62000, pitch: -58 },
}

export function flyToArea(viewer, area, { duration = 0 } = {}) {
  const view = AREA_VIEWS[area] || AREA_VIEWS.kolkata
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(view.longitude, view.latitude, view.height),
    orientation: {
      heading: 0,
      pitch: Cesium.Math.toRadians(view.pitch),
      roll: 0,
    },
    duration,
  })
}

export function createGlobeScene({
  container,
  creditContainer,
  initialStack = 'esri-imagery',
  onChange,
  onError,
} = {}) {
  configureCesiumBaseUrl()
  const viewer = createGlobeViewer({ container, creditContainer })
  const registry = createGlobeSources({ onTerrainFallback: (message) => onError?.(message) })
  const controller = new GlobeSourceController(viewer, {
    registry,
    initialStack,
    onChange,
    onError,
  })
  return {
    viewer,
    controller,
    setStack: (id) => controller.setStack(id),
    flyToArea: (area, options) => flyToArea(viewer, area, options),
    requestRender: () => viewer.scene.requestRender(),
    destroy: () => {
      controller.destroy()
      if (!viewer.isDestroyed()) viewer.destroy()
    },
  }
}
