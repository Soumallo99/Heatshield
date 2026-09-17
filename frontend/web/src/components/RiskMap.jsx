import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { GeoJSON, MapContainer, Marker, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { bandColour } from '../motion'

/**
 * Real ward choropleth.
 *
 * Geometry: 141 KMC ward polygons (datameet / OpenCity, ODbL) — real administrative
 * boundaries, not derived cells. Basemap: CARTO dark tiles built on OpenStreetMap.
 *
 * Motion approach: Leaflet renders SVG, so colour changes are animated with a CSS
 * transition on `fill` (.leaflet-interactive) rather than in JS — that keeps the
 * main thread free when 141 polygons restyle at once. Critical wards get an HTML
 * divIcon pulse, because CSS keyframes on HTML are far cheaper than animating SVG.
 */
const KOlkATA_CENTER = [22.5726, 88.3639]

function FitBounds({ geo }) {
  const map = useMap()
  useEffect(() => {
    if (!geo) return
    const b = L.geoJSON(geo).getBounds()
    if (b.isValid()) map.fitBounds(b, { padding: [12, 12] })
  }, [geo, map])
  return null
}

/** Smoothly fly to the selected ward without fighting the user's own panning. */
function FlyTo({ ward, geo }) {
  const map = useMap()
  const last = useRef(null)
  const hasSkippedInitialSelection = useRef(false)
  useEffect(() => {
    if (!ward || !geo) return
    if (last.current === ward.ward_id) return
    last.current = ward.ward_id
    // Dashboard data auto-selects the highest-risk ward on first load. Let
    // FitBounds establish the city-wide view; only user selections should
    // zoom the map into an individual ward.
    if (!hasSkippedInitialSelection.current) {
      hasSkippedInitialSelection.current = true
      return
    }
    const layer = L.geoJSON(geo)
    let target = null
    layer.eachLayer((l) => {
      if (l.feature?.properties?.ward_id === ward.ward_id) target = l
    })
    if (target) {
      const b = target.getBounds()
      if (b.isValid()) map.flyToBounds(b, { padding: [60, 60], duration: 0.9, maxZoom: 14 })
    }
  }, [ward, geo, map])
  return null
}

const pulseIcon = (colour) =>
  L.divIcon({
    className: 'ward-pulse',
    html: `<span class="pulse-ring" style="--pc:${colour}"></span><span class="pulse-core" style="--pc:${colour}"></span>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  })

export default function RiskMap({ geo, wards = [], selectedId, onSelect }) {
  const geoRef = useRef(null)
  const [hover, setHover] = useState(null)
  const [tilesFailed, setTilesFailed] = useState(false)
  const cartoKey = import.meta.env.VITE_CARTO_KEY?.trim()
  const tileUrl = cartoKey
    ? `https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?api_key=${cartoKey}`
    : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'

  const byId = useMemo(
    () => Object.fromEntries(wards.map((w) => [w.ward_id, w])),
    [wards]
  )

  const style = (feature) => {
    const id = feature?.properties?.ward_id
    const w = byId[id]
    const colour = bandColour[w?.risk_band] || w?.risk_colour || '#334155'
    const isSel = id === selectedId
    const isHover = id === hover
    return {
      color: isSel ? '#22d3ee' : colour,
      weight: isSel ? 2.4 : isHover ? 1.6 : 0.6,
      opacity: isSel ? 1 : 0.75,
      fillColor: colour,
      fillOpacity: isSel ? 0.62 : isHover ? 0.5 : w ? 0.3 : 0.08,
    }
  }

  // restyle in place when risk data changes — CSS transitions the colour
  useEffect(() => {
    const layer = geoRef.current
    if (!layer) return
    layer.eachLayer((l) => l.setStyle(style(l.feature)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [byId, selectedId, hover])

  const hot = useMemo(
    () => wards.filter((w) => w.risk_band === 'Critical' || w.risk_band === 'Extreme'),
    [wards]
  )

  if (!geo) {
    return (
      <div className="flex h-[420px] items-center justify-center text-[12px] text-white/30">
        loading ward boundaries…
      </div>
    )
  }

  return (
    <div className="risk-map relative min-w-0 overflow-hidden rounded-xl" style={{ height: 420 }}>
      <MapContainer
        center={KOlkATA_CENTER}
        zoom={11}
        zoomControl={false}
        attributionControl={false}
        style={{ height: '100%', width: '100%', background: '#0a0c14' }}
      >
        {!tilesFailed && (
          <TileLayer
            url={tileUrl}
            subdomains={cartoKey ? ['a', 'b', 'c', 'd'] : ['a', 'b', 'c']}
            maxZoom={19}
            eventHandlers={{ tileerror: () => setTilesFailed(true) }}
          />
        )}

        <GeoJSON
          ref={geoRef}
          data={geo}
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

        {hot.map((w) => (
          <Marker
            key={w.ward_id}
            position={[w.lat, w.lon]}
            icon={pulseIcon(bandColour[w.risk_band] || '#ef4444')}
            interactive={false}
          >
            <Tooltip direction="top" offset={[0, -10]} opacity={0.95}>
              {w.ward_name} · risk {Math.round(w.risk_score)} · {w.risk_band}
            </Tooltip>
          </Marker>
        ))}

        <FitBounds geo={geo} />
        <FlyTo ward={byId[selectedId]} geo={geo} />
      </MapContainer>
      <div className="radar-sweep pointer-events-none absolute inset-0 z-[450]" aria-hidden="true" />
      {selectedId && <div className="selected-ward-aura pointer-events-none absolute inset-0 z-[451]" aria-hidden="true" />}

      {/* attribution rendered manually so it can't be hidden by the panel styling */}
      {tilesFailed && (
        <div className="vector-grid pointer-events-none absolute inset-0 z-[300] flex items-end justify-center pb-8">
          <span className="rounded-full bg-black/65 px-3 py-1 text-[10px] text-white/55">
            basemap unavailable · vector ward grid retained
          </span>
        </div>
      )}
      <div className="pointer-events-none absolute bottom-1 right-2 z-[500] rounded bg-black/45 px-1.5 py-0.5 text-[9px] text-white/45">
        © OpenStreetMap contributors · wards: OpenCity/ODbL{cartoKey ? ' · © CARTO' : ''}
      </div>

      {/* hover readout */}
      {hover && byId[hover] && (
        <div
          className="pointer-events-none absolute left-2 top-2 z-[500] rounded-lg px-2.5 py-1.5 text-[10.5px] backdrop-blur"
          style={{ background: 'rgba(10,12,20,.82)', border: '1px solid rgba(255,255,255,.1)' }}
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
