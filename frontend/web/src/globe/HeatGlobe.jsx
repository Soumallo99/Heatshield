/**
 * HeatGlobe — the lazy 3D view of the Operations dashboard.
 *
 * Two modes, one globe:
 *   mode="wards"  Kolkata — 141 KMC ward polygons as a risk choropleth
 *   mode="zones"  Delhi NCR — the 8 advance-warning zone markers
 *
 * Design constraints this component exists to satisfy:
 *   - LAZY. It is imported only through `lazy(() => import('../globe/HeatGlobe'))`
 *     in Dashboard/DelhiOps, so CesiumJS (~1 MB gzip) and its runtime assets
 *     never reach the citizen phone route or the landing page. The 2D Leaflet
 *     map remains the instant, default, low-end/offline view; this is opt-in.
 *   - KEYLESS. Sources come from ../globe/sources.js: Esri World Imagery with
 *     an automatic OpenStreetMap fallback, plus keyless terrain that degrades
 *     to the ellipsoid. Every failure surfaces as an on-map notice — a
 *     downgrade is announced, never silent.
 *   - HONEST. Every colour carries a word (labels + legend), and the ward
 *     prism height is labelled stylised on the control that turns it on.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { bandColour } from '../motion.js'
import { levelColour, levelLabel, formatNumber, formatTemp, text } from '../demo/contract.js'
import {
  addWardChoropleth, addWardLabel, addZoneMarkers, bindPicking,
  PRISM_METRES_PER_POINT, PRISM_NOTE,
} from './heatLayers.js'
// Cesium's own stylesheet. Required, not optional: `.cesium-widget canvas`
// (100% width/height) and the credit-display layout come from here, so without
// it the canvas collapses. It is bundled with the globe chunk's CSS, which is
// lazy — the phone cold-open never sees it.
import 'cesium/Build/Cesium/Widgets/widgets.css'
import './globe.css'

const BAND_LEGEND = ['Normal', 'Caution', 'Danger', 'Critical', 'Extreme']
const ALERT_LEGEND = ['routine', 'watch', 'warning', 'severe']

/** Hovered/selected entity -> the tooltip the operator sees. */
function tooltipFor(entityId, { wards, rows }) {
  if (entityId?.startsWith('ward-')) {
    const wardId = entityId.replace(/^ward-/, '').replace(/-p\d+$/, '')
    const ward = wards.find((row) => String(row.ward_id) === wardId)
    if (!ward) return null
    return {
      title: `${ward.ward_name} · ward ${ward.ward_id}`,
      lines: [
        `Risk ${formatNumber(ward.risk_score, 0)}/100 · ${text(ward.risk_band, 'no band')}`,
        ward.population != null ? `${formatNumber(ward.population, 0)} residents` : null,
      ].filter(Boolean),
    }
  }
  if (entityId?.startsWith('zone-')) {
    const zoneId = entityId.replace(/^zone-/, '')
    const row = rows.find((entry) => String(entry.zone_id) === zoneId)
    if (!row) return null
    return {
      title: `${row.zone_name} · zone ${row.zone_id}`,
      lines: [
        `Alert level ${levelLabel(row.alert_level)}`,
        `Tmax ${formatTemp(row.tmax_c)} · WBGT est. ${formatTemp(row.wbgt_est_peak_c)}`,
        row.htsi_band ? `HTSI ${formatNumber(row.htsi_score, 0)} (${row.htsi_band})` : null,
      ].filter(Boolean),
    }
  }
  return null
}

export default function HeatGlobe({
  mode = 'wards',
  area = 'kolkata',
  geo = null,
  wards = [],
  rows = [],
  selectedId = '',
  onSelect,
  title = 'Ward risk — 3D globe',
  subtitle = '',
}) {
  const containerRef = useRef(null)
  const creditRef = useRef(null)
  const sceneRef = useRef(null)
  const choroplethRef = useRef(null)
  const markersRef = useRef(null)
  const labelsRef = useRef([])
  const [status, setStatus] = useState('loading')
  const [stacks, setStacks] = useState([])
  const [activeStack, setActiveStack] = useState('esri-imagery')
  const [notice, setNotice] = useState(null)
  const [hover, setHover] = useState(null)
  const [extrude, setExtrude] = useState(false)
  const [ready, setReady] = useState(false)

  const onError = useCallback((message) => setNotice(message), [])

  /* ---- boot once -------------------------------------------------------- */
  useEffect(() => {
    let cancelled = false
    let teardown = null
    ;(async () => {
      try {
        const [{ createGlobeScene }, { supportsWebgl }] = await Promise.all([
          import('./scene.js'),
          import('./viewer.js'),
        ])
        if (cancelled) return
        if (!supportsWebgl()) {
          setStatus('unsupported')
          return
        }
        const scene = createGlobeScene({
          container: containerRef.current,
          creditContainer: creditRef.current,
          initialStack: 'esri-imagery',
          onChange: (state) => {
            if (cancelled) return
            setStacks(state.stacks || [])
            setActiveStack(state.activeId)
          },
          onError,
        })
        sceneRef.current = scene
        scene.flyToArea(area, { duration: 0 })
        await scene.setStack('esri-imagery')
        if (cancelled) return
        setStacks(scene.controller.getStacks())
        setActiveStack(scene.controller.getActiveId())
        setReady(true)
        setStatus('ready')
        teardown = () => {
          scene.destroy()
          sceneRef.current = null
        }
      } catch (error) {
        console.error('[HeatShield globe] failed to start:', error)
        if (!cancelled) {
          setNotice(
            `The 3D globe could not start on this device (${error?.message || error}). ` +
              'The 2D map remains fully usable.',
          )
          setStatus('error')
        }
      }
    })()
    return () => {
      cancelled = true
      teardown?.()
    }
    // Boot once: later prop changes are applied by the update effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /* ---- layers ----------------------------------------------------------- */
  /* Build effect: creates and destroys entities, so it runs only when the
     *structure* changes (mode, geometry, scene readiness). It deliberately does
     not depend on wards/rows/selectedId/extrude — those are read at build time
     and kept current by the update effect below. Depending on them here would
     tear down every Cesium entity on each ward click, and drop the picking
     bindings with them. */
  useEffect(() => {
    const scene = sceneRef.current
    if (!scene || !ready) return
    const viewer = scene.viewer
    choroplethRef.current?.destroy()
    markersRef.current?.destroy()
    for (const label of labelsRef.current) viewer.entities.remove(label)
    labelsRef.current = []
    choroplethRef.current = null
    markersRef.current = null

    if (mode === 'wards' && geo?.features?.length) {
      choroplethRef.current = addWardChoropleth(viewer, { geo, wards, selectedId, extrude })
    } else if (mode === 'zones') {
      markersRef.current = addZoneMarkers(viewer, { rows, selectedZoneId: selectedId })
    }
    scene.requestRender()
  }, [mode, geo, ready])

  /* Update effect: data-first or data-later. Runs on mount (right after the
     build effect, since `ready` just flipped) and on every selection, scenario
     or data change — so a choropleth built while the ranking was still loading
     is coloured the moment the rows arrive. */
  useEffect(() => {
    const scene = sceneRef.current
    if (!scene || !ready) return
    if (mode === 'wards') {
      choroplethRef.current?.update({ wards, selectedId, extrude })
      // Label the hottest handful (plus the selected ward) — 141 permanent
      // labels would be noise, and the same "thin by importance" rule the 2D
      // map uses.
      const viewer = scene.viewer
      for (const label of labelsRef.current) viewer.entities.remove(label)
      labelsRef.current = []
      const ranked = [...wards].sort((a, b) => (b.risk_score || 0) - (a.risk_score || 0))
      const hotspots = ranked.filter((row) => row.risk_band === 'Critical' || row.risk_band === 'Extreme').slice(0, 12)
      const selected = wards.find((row) => String(row.ward_id) === String(selectedId))
      const labelled = [selected, ...hotspots]
        .filter(Boolean)
        .filter((row, index, list) => list.findIndex((other) => other.ward_id === row.ward_id) === index)
      labelsRef.current = labelled
        .filter((row) => row.lat != null && row.lon != null)
        .map((row) => addWardLabel(viewer, row, { selected: String(row.ward_id) === String(selectedId) }))
    } else {
      markersRef.current?.update({ rows, selectedZoneId: selectedId })
    }
    scene.requestRender()
  }, [wards, rows, selectedId, extrude, mode, ready])

  /* ---- picking ---------------------------------------------------------- */
  useEffect(() => {
    const scene = sceneRef.current
    if (!scene || !ready) return
    const ids = mode === 'wards' ? ['ward-'] : ['zone-']
    const unbind = bindPicking(scene.viewer, {
      ids,
      onHover: (entityId, position) => {
        setHover(
          entityId ? { ...tooltipFor(entityId, { wards, rows }), x: position?.x ?? 0, y: position?.y ?? 0 } : null,
        )
      },
      onSelect: (entityId) => {
        if (!onSelect) return
        const id = entityId.replace(/^ward-/, '').replace(/^zone-/, '').replace(/-p\d+$/, '')
        // Hand back the payload's own id value (usually a number), not the
        // stringified entity id: the 2D map and the tables share this state.
        const matched = mode === 'wards'
          ? wards.find((row) => String(row.ward_id) === id)
          : rows.find((row) => String(row.zone_id) === id)
        if (matched) onSelect(mode === 'wards' ? matched.ward_id : matched.zone_id)
      },
    })
    return unbind
  }, [mode, wards, rows, onSelect, ready])

  const chooseStack = useCallback(async (id) => {
    const scene = sceneRef.current
    if (!scene) return
    await scene.setStack(id)
    setActiveStack(scene.controller.getActiveId())
  }, [])

  const flyHome = useCallback(() => sceneRef.current?.flyToArea(area, { duration: 1.2 }), [area])

  const legend = useMemo(() => (
    mode === 'wards'
      ? BAND_LEGEND.map((band) => ({ colour: bandColour[band], label: band }))
      : ALERT_LEGEND.map((level) => ({ colour: levelColour(level), label: levelLabel(level) }))
  ), [mode])

  const unavailable = status === 'unsupported' || status === 'error'

  return (
    <div className="globe-wrap">
      <div ref={containerRef} className="globe-canvas" role="img" aria-label={`${title}. ${subtitle}`} />

      {!unavailable && (
        <div className="globe-hud globe-hud--left">
          <div className="globe-title">
            <span className="globe-eyebrow">3D globe · CesiumJS</span>
            <strong>{title}</strong>
            {subtitle && <span className="globe-sub">{subtitle}</span>}
          </div>
          {notice && (
            <p className="globe-notice" role="status">{notice}</p>
          )}
        </div>
      )}

      {!unavailable && (
        <div className="globe-hud globe-hud--right">
          <div className="globe-chips" role="group" aria-label="Globe imagery source">
            {stacks.map((stack) => (
              <button
                key={stack.id}
                type="button"
                className={`globe-chip${stack.id === activeStack ? ' is-on' : ''}`}
                aria-pressed={stack.id === activeStack}
                title={stack.available === false ? stack.unavailableReason : stack.hint}
                disabled={stack.available === false}
                onClick={() => chooseStack(stack.id)}
              >
                {stack.label}
              </button>
            ))}
          </div>
          <div className="globe-chips">
            <button type="button" className="globe-chip" onClick={flyHome} title="Re-centre the camera">
              ⌂ Recentre
            </button>
            {mode === 'wards' && (
              <button
                type="button"
                className={`globe-chip${extrude ? ' is-on' : ''}`}
                aria-pressed={extrude}
                title={`${PRISM_NOTE} Score 0–100 → 0–${100 * PRISM_METRES_PER_POINT} m.`}
                onClick={() => setExtrude((value) => !value)}
              >
                ▮ Risk prisms
              </button>
            )}
          </div>
        </div>
      )}

      {unavailable && (
        <div className="globe-fallback" role="alert">
          <strong>The 3D globe is unavailable on this device.</strong>
          <span>
            {status === 'unsupported'
              ? 'This browser cannot create a WebGL context. '
              : 'It failed to start. '}
            The 2D map toggle above still shows every ward, zone and layer — the globe is
            an extra view, never the only one.
          </span>
        </div>
      )}

      {hover && (
        <div className="globe-tip" style={{ left: hover.x + 14, top: hover.y + 12 }}>
          <strong>{hover.title}</strong>
          {hover.lines.map((line) => (
            <span key={line}>{line}</span>
          ))}
        </div>
      )}

      <div className="globe-legend" aria-label="Globe layer legend">
        <span className="globe-legend__title">{mode === 'wards' ? 'Heat risk band' : 'Alert level'}</span>
        <ul>
          {legend.map((entry) => (
            <li key={entry.label}>
              <i style={{ background: entry.colour }} aria-hidden="true" />
              {entry.label}
            </li>
          ))}
        </ul>
        {mode === 'wards' && (
          <span className="globe-legend__note">
            {geo?.features?.length ? `${geo.features.length} ward polygons` : 'ward boundaries unavailable'} ·
            ward shape geometry: OpenCity/datameet (ODbL)
          </span>
        )}
      </div>

      <div className="globe-foot">
        <p className="globe-attribution">
          Imagery © Esri, Maxar, Earthstar Geographics (keyless) · OSM fallback © OpenStreetMap
          contributors · Terrain: Re:Earth / Mapterhorn quantized mesh (CC BY 4.0), ellipsoid on
          failure · Globe: CesiumJS (Apache-2.0) · globe bootstrap derived from gods-eye-view (MIT)
          — see THIRD-PARTY.md. No API key is used or required anywhere on this map.
        </p>
        {/* Cesium's own credit line renders here; provider attribution is a licence term. */}
        <div ref={creditRef} className="globe-credits" />
      </div>
    </div>
  )
}
