/**
 * The keyless globe bootstrap.
 *
 * Adapted from gods-eye-view `src/app/viewer.js`
 * (https://github.com/bilawalsidhu/gods-eye-view @ 0d41b6b, MIT — see
 * LICENSE-gods-eye-view). Same construction contract — every built-in Cesium
 * widget off, no base layer, caller-owned credit container — with two
 * HeatShield-specific additions:
 *
 *   1. `baseLayer: false` is not a style choice, it is the guarantee. Cesium's
 *      default base layer is the ion-hosted Bing imagery, which is exactly the
 *      "tile that demands a key" the rest of this project exists to avoid.
 *      The globe starts with NO imagery and the controller adds a keyless one.
 *   2. A WebGL capability probe, so a device that cannot render a globe gets
 *      an honest message and the 2D map instead of a black rectangle.
 *
 * CesiumJS itself is Apache-2.0; see THIRD-PARTY.md.
 */
import * as Cesium from 'cesium'

/** True when this browser can actually render a Cesium scene. */
export function supportsWebgl() {
  if (typeof document === 'undefined') return false
  try {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl')
    if (!gl) return false
    // Release the probe context immediately — browsers cap live WebGL contexts.
    gl.getExtension('WEBGL_lose_context')?.loseContext()
    return true
  } catch {
    return false
  }
}

/** Create the standard globe viewer in caller-owned, visible containers. */
export function createGlobeViewer({ container, creditContainer }) {
  if (!container || !creditContainer) {
    throw new TypeError('Viewer and credit containers are required')
  }
  const viewer = new Cesium.Viewer(container, {
    timeline: false,
    animation: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    vrButton: false,
    selectionIndicator: false,
    infoBox: false,
    // No base layer at all: the controller installs a keyless one. With
    // baseLayerPicker off and this false, Cesium never contacts ion for
    // imagery, so nothing here can render an "API key required" tile.
    baseLayer: false,
    creditContainer,
    msaaSamples: 4,
    // Render on demand: a static globe costs no battery. The governor is
    // driven by the few interactions that change the scene.
    requestRenderMode: true,
    maximumRenderTimeChange: Infinity,
  })
  try {
    viewer.targetFrameRate = 60
    viewer.scene.globe.show = true
    // Sun lighting makes half the wards unreadable at night; the choropleth is
    // the point of this globe, so the imagery stays evenly lit.
    viewer.scene.globe.enableLighting = false
    viewer.scene.globe.showGroundAtmosphere = false
    viewer.scene.skyAtmosphere.show = true
    viewer.scene.skyAtmosphere.atmosphereLightIntensity = 18
    viewer.scene.skyAtmosphere.saturationShift = -0.12
    viewer.scene.skyAtmosphere.brightnessShift = -0.08
    return viewer
  } catch (error) {
    viewer.destroy()
    throw error
  }
}
