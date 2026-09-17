import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import {
  AttributionControl, GeoJSON, MapContainer, Marker, Pane, ScaleControl,
  TileLayer, Tooltip, useMap, useMapEvents,
} from 'react-leaflet'
import { bandColour } from '../motion'
import { BASEMAPS, DEFAULT_BASEMAP, getBasemap, USING_KEYED_TILES } from '../basemaps'

/**
 * Ward risk map.
 *
 * Geometry: 141 KMC ward polygons (datameet / OpenCity, ODbL) — real
 * administrative boundaries, not derived cells.
 *
 * Basemaps: see ../basemaps.js. Four keyless styles (Dark / Streets /
 * Satellite+labels / Terrain) at @2x where the provider offers it, so the map
 * reads as sharp and as complete as a consumer map app. Drop a
 * VITE_MAPTILER_KEY into .env and the same switcher silently upgrades to
 * higher-detail commercial tiles — no code change.
 *
 * Why not Google tiles directly? Pulling mt{n}.google.com/vt breaks the Maps
 * ToS. The licensed route (Maps JS API / Map Tiles API) needs a billing key;
 * everything here stays clone-and-run.
 *
 * Performance notes:
 *   - Polygons render into a dedicated SVG pane below markers, so restyling
 *     141 features never touches marker DOM.
 *   - Colour changes animate via a CSS transition on `fill`
 *     (.leaflet-interactive), keeping the main thread free.
 *   - Ward labels and pulses only mount above a zoom threshold / for hot wards.
 */
const KOLKATA_CENTER = [22.5726, 88.3639]
// Hard bounds: the data is Kolkata-only, so let people zoom out to see context
// but stop them drifting to the Atlantic.
const MAX_BOUNDS = L.latLngBounds([21.9, 87.6], [23.2, 89.2])

/* Emergency basemap: if the configured provider's tiles keep failing (invalid
   or expired API key, blocked CDN), the map degrades to keyless CARTO tiles
   instead of showing a field of "API key required" error tiles. */
const KEYLESS_FALLBACK = {
  url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  subdomains: 'abcd',
  maxZoom: 20,
  maxNativeZoom: 20,
  attribution: '© OpenStreetMap contributors · © CARTO',
}

// Mirrors core.risk band order (see bandColour in ../motion).
const LEGEND = ['Normal', 'Caution', 'Danger', 'Critical', 'Extreme']

/* ------------------------------------------------------------------ helpers */

function FitBounds({ geo }) {
  const map = useMap()
  const done = useRef(false)
  useEffect(() => {
    if (!geo || done.current) return
    const b = L.geoJSON(geo).getBounds()
    if (b.isValid()) {
      map.fitBounds(b, { padding: [16, 16] })
      done.current = true
    }
  }, [geo, map])
  return null
}

/** Smoothly fly to the selected ward without fighting the user's own panning. */
function FlyTo({ ward, layerRef }) {
  const map = useMap()
  const last = useRef(null)
  useEffect(() => {
    if (!ward || !layerRef.current) return
    if (last.current === ward.ward_id) return
    last.current = ward.ward_id
    let target = null
    layerRef.current.eachLayer((l) => {
      if (l.feature?.properties?.ward_id === ward.ward_id) target = l
    })
    if (target) {
      const b = target.getBounds()
      if (b.isValid()) map.flyToBounds(b, { padding: [60, 60], duration: 0.9, maxZoom: 15 })
    }
  }, [ward, layerRef, map])
  return null
}

/** Report zoom upward so labels/pulses can be density-managed. */
function ZoomWatch({ onZoom }) {
  const map = useMapEvents({ zoomend: () => onZoom(map.getZoom()) })
  useEffect(() => { onZoom(map.getZoom()) }, [map, onZoom])
  return null
}

/** Imperative handle for the custom control cluster. */
function MapHandle({ onReady }) {
  const map = useMap()
  useEffect(() => { onReady(map) }, [map, onReady])
  return null
}

const pulseIcon = (colour) =>
  L.divIcon({
    className: 'ward-pulse',
    html: `<span class="pulse-ring" style="--pc:${colour}"></span><span class="pulse-core" style="--pc:${colour}"></span>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  })

const labelIcon = (text, colour, score) =>
  L.divIcon({
    className: 'ward-label',
    html: `<span class="wl-dot" style="--pc:${colour}"></span><span class="wl-text">${text}</span><span class="wl-score" style="--pc:${colour}">${score}</span>`,
    iconSize: [0, 0],
    iconAnchor: [0, 0],
  })

const youAreHereIcon = L.divIcon({
  className: 'geo-dot',
  html: '<span class="geo-ring"></span><span class="geo-core"></span>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
})

/* ------------------------------------------------------------------ control */

function CtrlButton({ title, onClick, children, active }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className={`map-btn ${active ? 'map-btn-on' : ''}`}
    >
      {children}
    </button>
  )
}

/* -------------------------------------------------------------------- main */

export default function RiskMap({ geo, wards = [], selectedId, onSelect }) {
  const geoRef = useRef(null)
  const wrapRef = useRef(null)
  const [map, setMap] = useState(null)
  const [hover, setHover] = useState(null)
  const [zoom, setZoom] = useState(11)
  const [basemapId, setBasemapId] = useState(() => {
    try { return localStorage.getItem('hs.basemap') || DEFAULT_BASEMAP } catch { return DEFAULT_BASEMAP }
  })
  const [showChoropleth, setShowChoropleth] = useState(true)
  const [showLabels, setShowLabels] = useState(true)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [me, setMe] = useState(null)
  const [query, setQuery] = useState('')
  const [tileFailures, setTileFailures] = useState(0)

  const basemap = getBasemap(basemapId)
  const degraded = tileFailures > 6
  const effectiveBasemap = degraded
    ? { ...basemap, ...KEYLESS_FALLBACK, id: `${basemap.id}-keyless`, labels: undefined }
    : basemap
  useEffect(() => { setTileFailures(0) }, [basemapId])

  useEffect(() => {
    try { localStorage.setItem('hs.basemap', basemapId) } catch { /* private mode */ }
  }, [basemapId])

  const byId = useMemo(
    () => Object.fromEntries(wards.map((w) => [w.ward_id, w])),
    [wards]
  )

  /* ---- styling ---------------------------------------------------------- */
  const style = useCallback((feature) => {
    const id = feature?.properties?.ward_id
    const w = byId[id]
    const colour = bandColour[w?.risk_band] || w?.risk_colour || '#334155'
    const isSel = id === selectedId
    const isHover = id === hover
    const base = basemap.overlayOpacity ?? 0.34
    if (!showChoropleth) {
      return {
        color: isSel ? '#22d3ee' : colour,
        weight: isSel ? 2.6 : isHover ? 1.8 : 0.8,
        opacity: basemap.light ? 0.85 : 0.6,
        fillColor: colour,
        fillOpacity: isSel ? 0.25 : isHover ? 0.16 : 0,
      }
    }
    return {
      color: isSel ? '#22d3ee' : basemap.light ? 'rgba(15,23,42,.55)' : colour,
      weight: isSel ? 2.6 : isHover ? 1.8 : 0.6,
      opacity: isSel ? 1 : 0.8,
      fillColor: colour,
      fillOpacity: isSel ? base + 0.3 : isHover ? base + 0.18 : w ? base : 0.06,
    }
  }, [byId, selectedId, hover, showChoropleth, basemap])

  // restyle in place when risk data / view options change — CSS eases the colour
  useEffect(() => {
    const layer = geoRef.current
    if (!layer) return
    layer.eachLayer((l) => l.setStyle(style(l.feature)))
  }, [style])

  /* ---- derived marker sets --------------------------------------------- */
  const hot = useMemo(
    () => wards.filter((w) => w.risk_band === 'Critical' || w.risk_band === 'Extreme'),
    [wards]
  )

  // Labels are noise at city zoom: show the worst handful zoomed out, then
  // progressively reveal the rest as the user zooms in (classic map behaviour).
  const labelled = useMemo(() => {
    if (!showLabels) return []
    const ranked = [...wards].sort((a, b) => b.risk_score - a.risk_score)
    if (zoom >= 14) return ranked
    if (zoom >= 13) return ranked.slice(0, 60)
    if (zoom >= 12) return ranked.slice(0, 24)
    return ranked.slice(0, 8)
  }, [wards, zoom, showLabels])

  /* ---- controls --------------------------------------------------------- */
  const zoomIn = () => map?.zoomIn()
  const zoomOut = () => map?.zoomOut()
  const resetView = () => {
    if (!map || !geo) return
    const b = L.geoJSON(geo).getBounds()
    if (b.isValid()) map.flyToBounds(b, { padding: [16, 16], duration: 0.8 })
  }
  const locate = () => {
    if (!map || !navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (p) => {
        const ll = [p.coords.latitude, p.coords.longitude]
        setMe(ll)
        map.flyTo(ll, Math.max(map.getZoom(), 14), { duration: 0.9 })
      },
      () => setMe(null),
      { enableHighAccuracy: true, timeout: 8000 }
    )
  }
  const toggleFullscreen = () => {
    const el = wrapRef.current
    if (!el) return
    if (document.fullscreenElement) document.exitFullscreen?.()
    else el.requestFullscreen?.()
    setTimeout(() => map?.invalidateSize(), 250)
  }

  /* ---- ward search ------------------------------------------------------ */
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    return wards
      .filter((w) =>
        String(w.ward_id) === q ||
        w.ward_name?.toLowerCase().includes(q))
      .slice(0, 6)
  }, [query, wards])

  if (!geo) {
    return (
      <div className="flex h-[420px] items-center justify-center text-[12px] text-white/30">
        loading ward boundaries…
      </div>
    )
  }

  return (
    <div
      ref={wrapRef}
      className="relative min-w-0 overflow-hidden rounded-xl bg-[#0a0c14]"
      style={{ height: 420 }}
    >
      {degraded && (
        <div
          className="absolute left-3 top-3 z-[1000] max-w-[280px] rounded-lg border border-amber-300/40 bg-ink-950/90 px-3 py-2 text-[11px] leading-snug text-amber-200/90"
          role="status"
        >
          Basemap tiles from the configured provider kept failing (invalid/expired API key or a
          blocked CDN) — switched to keyless CARTO tiles so the risk map stays usable. Check
          <code> frontend/web/.env</code> if you set <code>VITE_MAPTILER_KEY</code>/<code>VITE_THUNDERFOREST_KEY</code>.
        </div>
      )}
      <MapContainer
        center={KOLKATA_CENTER}
        zoom={11}
        minZoom={9}
        maxZoom={basemap.maxZoom || 19}
        maxBounds={MAX_BOUNDS}
        maxBoundsViscosity={0.7}
        zoomControl={false}
        attributionControl={false}
        zoomSnap={0.25}
        wheelPxPerZoomLevel={90}
        preferCanvas={false}
        style={{ height: '100%', width: '100%', background: '#0a0c14' }}
      >
        <MapHandle onReady={setMap} />
        <ZoomWatch onZoom={setZoom} />

        {/* base tiles — keyed on id so switching does a clean swap, not a merge */}
        <TileLayer
          key={effectiveBasemap.id}
          url={effectiveBasemap.url}
          subdomains={effectiveBasemap.subdomains || 'abc'}
          maxZoom={effectiveBasemap.maxZoom || 19}
          maxNativeZoom={effectiveBasemap.maxNativeZoom}
          detectRetina
          updateWhenIdle={false}
          keepBuffer={3}
          attribution={effectiveBasemap.attribution}
          eventHandlers={{ tileerror: () => setTileFailures((n) => n + 1) }}
        />
        {/* hybrid label overlay for imagery styles */}
        {effectiveBasemap.labels && (
          <Pane name="hs-labels" style={{ zIndex: 450, pointerEvents: 'none' }}>
            <TileLayer
              key={`${effectiveBasemap.id}-labels`}
              url={effectiveBasemap.labels.url}
              subdomains={effectiveBasemap.labels.subdomains || 'abc'}
              maxZoom={effectiveBasemap.labels.maxZoom || 19}
              detectRetina
            />
          </Pane>
        )}

        <Pane name="hs-wards" style={{ zIndex: 400 }}>
          <GeoJSON
            ref={geoRef}
            data={geo}
            pane="hs-wards"
            style={style}
            onEachFeature={(feature, layer) => {
              layer.on({
                mouseover: () => setHover(feature.properties.ward_id),
                mouseout: () => setHover(null),
                click: () => {
                  const w = byId[feature.properties.ward_id]
                  if (w) onSelect?.(w)
                },
              })
            }}
          />
        </Pane>

        {/* ward labels: name + score, thinned by zoom */}
        {labelled.map((w) => (
          <Marker
            key={`l-${w.ward_id}`}
            position={[w.lat, w.lon]}
            icon={labelIcon(
              w.ward_name,
              bandColour[w.risk_band] || '#94a3b8',
              Math.round(w.risk_score)
            )}
            interactive={false}
            zIndexOffset={-500}
          />
        ))}

        {hot.map((w) => (
          <Marker
            key={w.ward_id}
            position={[w.lat, w.lon]}
            icon={pulseIcon(bandColour[w.risk_band] || '#ef4444')}
            eventHandlers={{ click: () => onSelect?.(w) }}
          >
            <Tooltip direction="top" offset={[0, -10]} opacity={0.96}>
              <b>{w.ward_name}</b> · risk {Math.round(w.risk_score)} · {w.risk_band}
            </Tooltip>
          </Marker>
        ))}

        {me && (
          <Marker position={me} icon={youAreHereIcon} interactive={false} />
        )}

        <ScaleControl position="bottomleft" imperial={false} />
        <AttributionControl position="bottomright" prefix={false} />
        <FitBounds geo={geo} />
        <FlyTo ward={byId[selectedId]} layerRef={geoRef} />
      </MapContainer>

      {/* ---------------------------------------------------- search box */}
      <div className="absolute left-2 top-2 z-[600] w-52">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search ward or number…"
          className="map-search"
          aria-label="Search ward"
        />
        {matches.length > 0 && (
          <ul className="map-search-list">
            {matches.map((w) => (
              <li key={w.ward_id}>
                <button
                  type="button"
                  onClick={() => { onSelect?.(w); setQuery('') }}
                >
                  <span>{w.ward_name}</span>
                  <span className="tnum" style={{ color: bandColour[w.risk_band] }}>
                    {Math.round(w.risk_score)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ------------------------------------------------- control cluster */}
      <div className="absolute right-2 top-2 z-[600] flex flex-col items-end gap-1.5">
        <div className="map-ctrl-group">
          <CtrlButton title="Zoom in" onClick={zoomIn}>＋</CtrlButton>
          <CtrlButton title="Zoom out" onClick={zoomOut}>−</CtrlButton>
        </div>
        <div className="map-ctrl-group">
          <CtrlButton title="Reset to Kolkata" onClick={resetView}>⌂</CtrlButton>
          <CtrlButton title="My location" onClick={locate} active={!!me}>◎</CtrlButton>
          <CtrlButton title="Fullscreen" onClick={toggleFullscreen}>⛶</CtrlButton>
        </div>
        <div className="map-ctrl-group">
          <CtrlButton
            title="Toggle risk shading"
            onClick={() => setShowChoropleth((v) => !v)}
            active={showChoropleth}
          >
            ▦
          </CtrlButton>
          <CtrlButton
            title="Toggle ward labels"
            onClick={() => setShowLabels((v) => !v)}
            active={showLabels}
          >
            A
          </CtrlButton>
        </div>

        {/* basemap picker */}
        <div className="relative">
          <button
            type="button"
            className="map-layers-btn"
            onClick={() => setPickerOpen((v) => !v)}
            aria-expanded={pickerOpen}
          >
            <span className="mr-1.5 opacity-60">◈</span>{basemap.label}
          </button>
          {pickerOpen && (
            <div className="map-layers-menu">
              {BASEMAPS.map((b) => (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => { setBasemapId(b.id); setPickerOpen(false) }}
                  className={b.id === basemap.id ? 'on' : ''}
                >
                  <span className="lbl">{b.label}</span>
                  <span className="hint">{b.hint}</span>
                </button>
              ))}
              <div className="note">
                {USING_KEYED_TILES
                  ? 'API key detected — high-detail tiles active.'
                  : 'Keyless tiles. Add VITE_MAPTILER_KEY to .env for higher detail.'}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ------------------------------------------------------- legend */}
      <div className="absolute bottom-7 right-2 z-[600] rounded-lg border border-white/10 bg-black/60 px-2.5 py-2 backdrop-blur">
        <div className="mb-1 text-[9px] uppercase tracking-wider text-white/40">
          Heat risk
        </div>
        <div className="flex flex-col gap-0.5">
          {LEGEND.map((k) => (
            <span key={k} className="flex items-center gap-1.5 text-[10px] text-white/70">
              <i
                className="inline-block h-2 w-3 rounded-[2px]"
                style={{ background: bandColour[k] || '#334155' }}
              />
              {k}
            </span>
          ))}
        </div>
      </div>

      {/* --------------------------------------------------- hover readout */}
      {hover && byId[hover] && (
        <div
          className="pointer-events-none absolute bottom-7 left-2 z-[600] rounded-lg px-2.5 py-1.5 text-[10.5px] backdrop-blur"
          style={{ background: 'rgba(10,12,20,.85)', border: '1px solid rgba(255,255,255,.12)' }}
        >
          <span className="font-medium text-white/85">{byId[hover].ward_name}</span>
          <span className="ml-2 tnum" style={{ color: bandColour[byId[hover].risk_band] }}>
            {Math.round(byId[hover].risk_score)} · {byId[hover].risk_band}
          </span>
          <span className="ml-2 text-white/35">
            {byId[hover].population?.toLocaleString('en-IN')} residents
          </span>
        </div>
      )}
    </div>
  )
}
