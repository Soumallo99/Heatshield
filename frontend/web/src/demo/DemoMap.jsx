import { useMemo } from 'react'
import { AttributionControl, CircleMarker, MapContainer, TileLayer, Tooltip } from 'react-leaflet'
import { bandColour, levelColour, levelLabel, formatNumber, formatTemp, text } from './contract.js'

/* Layer definitions: every value is paired with WORDS — colour is never the
   only channel (accessibility rule enforced by tests/test_demo_app.py). */
const LAYERS = {
  level: {
    id: 'level',
    label: 'Alert level',
    colour: (row) => levelColour(row.alert_level),
    value: (row) => levelLabel(row.alert_level),
    legend: [
      { colour: '#3fb950', label: 'Routine — monitor' },
      { colour: '#e3b341', label: 'Watch — prepare' },
      { colour: '#f0883e', label: 'Warning — activate heat actions' },
      { colour: '#f85149', label: 'Severe — emergency coordination' },
    ],
  },
  thermal: {
    id: 'thermal',
    label: 'Thermal stress (HTSI)',
    colour: (row) => bandColour(row.htsi_band),
    value: (row) => `${row.htsi_band} · HTSI ${formatNumber(row.htsi_score, 0)}`,
    legend: [
      { colour: '#3fb950', label: 'Normal' },
      { colour: '#e3b341', label: 'Watch' },
      { colour: '#f0883e', label: 'Warning' },
      { colour: '#f85149', label: 'Severe' },
      { colour: '#8b949e', label: 'Unavailable' },
    ],
  },
  vulnerability: {
    id: 'vulnerability',
    label: 'Vulnerability (synthetic profile)',
    colour: (row) => ({ Low: '#3fb950', Moderate: '#e3b341', High: '#f85149' })[row.vulnerability_level] || '#8b949e',
    value: (row) => `${row.vulnerability_level} · ${formatNumber(row.vulnerability_score, 0)}/100`,
    legend: [
      { colour: '#3fb950', label: 'Low vulnerability' },
      { colour: '#e3b341', label: 'Moderate vulnerability' },
      { colour: '#f85149', label: 'High vulnerability' },
    ],
  },
  outlook: {
    id: 'outlook',
    label: 'Heatwave status',
    colour: (row) => (row.is_severe_episode ? '#f85149'
      : row.is_heatwave_episode ? '#f0883e'
        : row.heatwave_candidate || row.heatwave_label === 'Watch' ? '#e3b341'
          : '#3fb950'),
    value: (row) => text(row.heatwave_label, 'None'),
    legend: [
      { colour: '#3fb950', label: 'No heatwave signal' },
      { colour: '#e3b341', label: 'Watch / single-day candidate (persistence rule not met)' },
      { colour: '#f0883e', label: 'Declared heatwave episode (≥2 days)' },
      { colour: '#f85149', label: 'Severe heatwave episode' },
    ],
  },
}

export const MAP_LAYER_IDS = Object.keys(LAYERS)

const DELHI_CENTRE = [28.58, 77.28]

/**
 * Colour-coded GIS view for the Heat Risk Demo.
 *
 * The map is a convenience, never the only path: ZonesScreen renders the
 * identical data as an accessible table, and every colour carries a text
 * label in tooltips, the legend and that table.
 */
export default function DemoMap({ rows, zones, layer = 'level', leadDay = 3, selectedZoneId = '', showCooling = false, onSelect }) {
  const layerDef = LAYERS[layer] || LAYERS.level
  const zoneById = useMemo(() => new Map(zones.map((zone) => [zone.zone_id, zone])), [zones])

  const markers = useMemo(
    () => rows
      .filter((row) => row.lat !== null && row.lon !== null)
      .map((row) => ({ row, zone: zoneById.get(row.zone_id) })),
    [rows, zoneById],
  )

  const cooling = useMemo(() => {
    if (!showCooling) return []
    return zones.flatMap((zone) => zone.cooling_centres
      .filter((centre) => centre.lat !== null && centre.lon !== null)
      .map((centre) => ({ ...centre, zone_id: zone.zone_id })))
  }, [zones, showCooling])

  if (!markers.length) {
    return (
      <div className="demo-map demo-map--empty" role="img" aria-label="Demo map unavailable">
        <p>No mapped rows for Day +{leadDay}. The zone table below carries the same data.</p>
      </div>
    )
  }

  return (
    <div className="demo-map-wrap">
      <MapContainer
        center={DELHI_CENTRE}
        zoom={10}
        minZoom={8}
        maxZoom={14}
        scrollWheelZoom={false}
        attributionControl={false}
        className="demo-map"
        aria-label={`Demo risk map, ${layerDef.label} layer, Day +${leadDay}`}
      >
        <AttributionControl position="bottomright" prefix={false} />
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          subdomains="abcd"
          maxZoom={20}
          attribution="© OpenStreetMap contributors · © CARTO"
        />
        {markers.map(({ row, zone }) => {
          const colour = layerDef.colour(row)
          const selected = row.zone_id === selectedZoneId
          return (
            <CircleMarker
              key={`${row.zone_id}-${row.target_date}`}
              center={[row.lat, row.lon]}
              radius={selected ? 15 : 11}
              pathOptions={{
                color: selected ? '#ffffff' : 'rgba(255,255,255,.55)',
                weight: selected ? 2.4 : 1.2,
                fillColor: colour,
                fillOpacity: 0.92,
              }}
              eventHandlers={{ click: () => onSelect?.(row.zone_id) }}
            >
              <Tooltip direction="top" offset={[0, -8]}>
                <span className="demo-map-tip">
                  <strong>{row.zone_name}</strong>
                  <span>{layerDef.label}: {layerDef.value(row)}</span>
                  <span>Tmax {formatTemp(row.tmax_c)} · WBGT est. {formatTemp(row.wbgt_est_peak_c)}</span>
                  {zone ? <span>Cooling centres: {formatNumber(zone.cooling_centre_count, 0)} (demo)</span> : null}
                </span>
              </Tooltip>
            </CircleMarker>
          )
        })}
        {cooling.map((centre) => (
          <CircleMarker
            key={`${centre.zone_id}-${centre.lat}-${centre.lon}`}
            center={[centre.lat, centre.lon]}
            radius={4}
            pathOptions={{ color: '#79c0ff', weight: 1, fillColor: '#79c0ff', fillOpacity: 0.95 }}
          >
            <Tooltip direction="top" offset={[0, -4]}>
              <span className="demo-map-tip"><strong>{centre.name}</strong></span>
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
      <ul className="demo-map-legend" aria-label={`${layerDef.label} legend`}>
        {layerDef.legend.map((entry) => (
          <li key={entry.label}>
            <span className="demo-legend__swatch" style={{ background: entry.colour }} aria-hidden="true" />
            {entry.label}
          </li>
        ))}
      </ul>
    </div>
  )
}
