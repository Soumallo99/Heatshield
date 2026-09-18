/**
 * Vendored from gods-eye-view `src/maps/credits.js`
 * (https://github.com/bilawalsidhu/gods-eye-view @ 0d41b6b, MIT — see
 * LICENSE-gods-eye-view). Unmodified except for this header.
 *
 * Static credits follow the source actually on screen, including fallback: the
 * credit line must never advertise Esri imagery while OSM tiles are the ones
 * being rendered.
 */
import * as Cesium from 'cesium'

export function createMapCredits(viewer) {
  let active = null
  let markup = null
  return {
    show(html) {
      if (html === markup) return
      const display = viewer?.scene?.frameState?.creditDisplay
      if (!display) return
      try {
        if (active) display.removeStaticCredit(active)
        active = html ? new Cesium.Credit(html, true) : null
        markup = html
        if (active) display.addStaticCredit(active)
      } catch {
        /* Switching remains usable on older credit displays. */
      }
    },
    destroy() {
      this.show(null)
    },
  }
}
