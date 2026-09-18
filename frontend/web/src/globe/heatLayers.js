/**
 * HeatShield's own data layers on the globe: the Kolkata ward choropleth and
 * the Delhi NCR zone markers.
 *
 * This file is NOT vendored from gods-eye-view — it is the adapter that turns
 * HeatShield's payloads (the same shapes `RiskMap.jsx` and `DemoMap.jsx`
 * consume) into Cesium entities. The vendored provider/controller plumbing is
 * in the sibling modules.
 *
 * Truthfulness rules that shape the code below:
 *   - Colour is never the only channel: every marker carries a text label, the
 *     globe renders a text legend, and hovering/selecting shows the numbers in
 *     words (the same rule the 2D maps follow).
 *   - The ward extrusion (the "risk prism") is a STYLISED height, not a
 *     measurement. It is off by default and labelled as stylised wherever it
 *     can be switched on.
 */
import * as Cesium from 'cesium'
import { bandColour as BAND_COLOUR } from '../motion.js'
import { levelColour, levelLabel } from '../demo/contract.js'

/** Stylised prism height: risk score 0-100 -> 0-1000 m. NOT a measurement. */
export const PRISM_METRES_PER_POINT = 10
export const PRISM_NOTE = 'Prism height is a stylised risk cue, not a measurement.'

const NEUTRAL = '#64748b'
const OUTLINE = Cesium.Color.fromCssColorString('#0b0f19').withAlpha(0.55)
const SELECTED_OUTLINE = Cesium.Color.fromCssColorString('#22d3ee')

const colourFor = (colour, alpha) =>
  Cesium.Color.fromCssColorString(colour || NEUTRAL).withAlpha(alpha)

const positionsOf = (ring) => Cesium.Cartesian3.fromDegreesArray(ring.flat())

/** GeoJSON Polygon/MultiPolygon -> one polygon hierarchy per outer ring. */
function polygonsOf(geometry) {
  if (!geometry) return []
  if (geometry.type === 'Polygon') return [geometry.coordinates]
  if (geometry.type === 'MultiPolygon') return geometry.coordinates
  return []
}

const labelStyle = (colour) => ({
  font: '600 13px Inter, system-ui, sans-serif',
  fillColor: Cesium.Color.WHITE,
  outlineColor: Cesium.Color.fromCssColorString('#07080d'),
  outlineWidth: 4,
  style: Cesium.LabelStyle.FILL_AND_OUTLINE,
  pixelOffset: new Cesium.Cartesian2(0, -18),
  disableDepthTestDistance: Number.POSITIVE_INFINITY,
  distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 90000),
  scaleByDistance: new Cesium.NearFarScalar(1000, 1.0, 90000, 0.65),
  ...(colour ? { backgroundColor: colour } : {}),
})

/**
 * Kolkata ward polygons + risk choropleth.
 *
 * @returns {{ update: (next: object) => void, destroy: () => void, size: () => number }}
 */
export function addWardChoropleth(viewer, { geo, wards = [], selectedId, hoveredId, extrude = false } = {}) {
  const byWardId = new Map(wards.map((ward) => [String(ward.ward_id), ward]))
  const entities = []
  const byEntityId = new Map()
  const features = geo?.features || []

  for (const feature of features) {
    const wardId = String(feature?.properties?.ward_id ?? '')
    if (!byWardId.has(wardId) && !feature?.properties) continue
    const parts = polygonsOf(feature.geometry)
    parts.forEach((polygon, partIndex) => {
      const [outer, ...holes] = polygon
      if (!outer?.length) return
      const entityId = `ward-${wardId}${parts.length > 1 ? `-p${partIndex}` : ''}`
      const entity = viewer.entities.add({
        id: entityId,
        polygon: {
          hierarchy: new Cesium.PolygonHierarchy(positionsOf(outer), holes.map(positionsOf)),
          material: colourFor(NEUTRAL, 0.6),
          outline: true,
          outlineColor: OUTLINE,
          outlineWidth: 1,
          height: 0,
          perPositionHeight: false,
        },
      })
      entities.push(entity)
      byEntityId.set(entityId, { entity, wardId, ring: outer })
    })
  }

  function update({ wards: nextWards, selectedId: nextSelected, hoveredId: nextHovered, extrude: nextExtrude } = {}) {
    const rows = nextWards || wards
    const lookup = new Map(rows.map((row) => [String(row.ward_id), row]))
    const selected = nextSelected ?? selectedId
    const hovered = nextHovered ?? hoveredId
    const prism = nextExtrude ?? extrude
    for (const entry of byEntityId.values()) {
      const row = lookup.get(entry.wardId)
      const band = row?.risk_band
      const isSelected = String(selected ?? '') === entry.wardId
      const isHovered = String(hovered ?? '') === entry.wardId
      const score = Number(row?.risk_score)
      const alpha = isSelected ? 0.85 : isHovered ? 0.72 : 0.55
      entry.entity.polygon.material = colourFor(BAND_COLOUR[band], row ? alpha : 0.25)
      entry.entity.polygon.outlineColor = isSelected ? SELECTED_OUTLINE : OUTLINE
      entry.entity.polygon.outlineWidth = isSelected ? 3 : isHovered ? 2 : 1
      entry.entity.polygon.extrudedHeight =
        prism && row && Number.isFinite(score) ? Math.max(score, 0) * PRISM_METRES_PER_POINT : undefined
    }
  }

  update({ wards, selectedId, hoveredId, extrude })

  // Destructive for the picker: removes every ward entity from the scene.
  function destroy() {
    for (const entity of entities) viewer.entities.remove(entity)
    entities.length = 0
    byEntityId.clear()
  }

  return { update, destroy, size: () => entities.length }
}

/** Attach a text label to one ward (used for hotspots + the selected ward). */
export function addWardLabel(viewer, ward, { selected = false } = {}) {
  const colour = BAND_COLOUR[ward?.risk_band] || NEUTRAL
  const score = Number(ward?.risk_score)
  return viewer.entities.add({
    id: `ward-label-${ward?.ward_id}`,
    position: Cesium.Cartesian3.fromDegrees(Number(ward.lon), Number(ward.lat)),
    label: {
      text: `${ward.ward_name}\n${Number.isFinite(score) ? Math.round(score) : '—'} · ${ward.risk_band || 'no band'}`,
      ...labelStyle(),
      fillColor: selected ? Cesium.Color.fromCssColorString('#ffffff') : Cesium.Color.fromCssColorString(colour),
      pixelOffset: new Cesium.Cartesian2(0, selected ? -26 : -14),
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  })
}

/**
 * Delhi NCR zone markers (8 ~10 km model grid points).
 *
 * Each zone is a point + a text label that names the zone AND spells out its
 * alert level, so the colour is never the only channel.
 */
export function addZoneMarkers(viewer, { rows = [], selectedZoneId } = {}) {
  const entities = []
  const byEntityId = new Map()

  for (const row of rows) {
    const lat = Number(row?.lat)
    const lon = Number(row?.lon)
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue
    const colour = levelColour(row.alert_level)
    const selected = String(selectedZoneId ?? '') === String(row.zone_id)
    const entity = viewer.entities.add({
      id: `zone-${row.zone_id}`,
      position: Cesium.Cartesian3.fromDegrees(lon, lat),
      point: {
        pixelSize: selected ? 18 : 13,
        color: colourFor(colour, 0.92),
        outlineColor: selected ? Cesium.Color.WHITE : colourFor('#ffffff', 0.6),
        outlineWidth: selected ? 3 : 1.5,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: `${row.zone_name}\n${levelLabel(row.alert_level)}`,
        ...labelStyle(),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    })
    entities.push(entity)
    byEntityId.set(entity.id, row)
  }

  function update({ rows: nextRows, selectedZoneId: nextSelected } = {}) {
    const list = nextRows || rows
    const lookup = new Map(list.map((row) => [`zone-${row.zone_id}`, row]))
    const selected = nextSelected ?? selectedZoneId
    for (const entity of entities) {
      const row = lookup.get(entity.id) || byEntityId.get(entity.id)
      if (!row) continue
      const isSelected = String(selected ?? '') === String(row.zone_id)
      entity.point.color = colourFor(levelColour(row.alert_level), 0.92)
      entity.point.pixelSize = isSelected ? 18 : 13
      entity.point.outlineColor = isSelected ? Cesium.Color.WHITE : colourFor('#ffffff', 0.6)
      entity.point.outlineWidth = isSelected ? 3 : 1.5
      entity.label.text = `${row.zone_name}\n${levelLabel(row.alert_level)}`
    }
  }

  function destroy() {
    for (const entity of entities) viewer.entities.remove(entity)
    entities.length = 0
    byEntityId.clear()
  }

  return { update, destroy, size: () => entities.length }
}

/* -------------------------------------------------------------------------- */
/* Live tracking layers (opt-in; see ../globe/liveData.js)                    */
/* -------------------------------------------------------------------------- */

/**
 * One colour and one label rule per live layer.
 *
 * Every point also carries a text label, for the same reason the choropleth
 * does: colour alone is not information. Which is doubly true here, because an
 * unlabelled dot over the ocean could be anything.
 */
export const LIVE_LAYER_STYLE = {
  aircraft: { colour: '#7dd3fc', pixelSize: 7, outline: 1.5 },
  earthquakes: { colour: '#fb923c', pixelSize: 8, outline: 1.5 },
  satellites: { colour: '#c4b5fd', pixelSize: 6, outline: 1 },
}

/** What a live row says about itself on the globe. */
export function liveLabel(layerId, row) {
  if (layerId === 'aircraft') {
    return row?.callsign || row?.registration || row?.icao || 'unknown aircraft'
  }
  if (layerId === 'earthquakes') {
    const mag = Number(row?.mag)
    return `${Number.isFinite(mag) ? `M ${mag.toFixed(1)}` : 'M ?'} · ${row?.place || 'unknown location'}`
  }
  if (layerId === 'satellites') {
    return row?.name || 'unknown object'
  }
  return row?.name || ''
}

/** Metres above the ellipsoid for a live row — satellites are the only high ones. */
export function liveHeight(layerId, row) {
  if (layerId === 'satellites') {
    const km = Number(row?.alt_km)
    return Number.isFinite(km) ? km * 1000 : 0
  }
  if (layerId === 'aircraft') {
    const metres = Number(row?.alt_m)
    return Number.isFinite(metres) ? metres : 0
  }
  return 0
}

/**
 * Draw one live layer.
 *
 * Points are drawn with the depth test disabled so an aircraft at 11 km or a
 * satellite at 420 km is visible from the surface instead of disappearing
 * behind terrain — the alternative (a camera that has to be above 420 km to
 * see the layer it just switched on) reads as a broken layer.
 *
 * @returns {{ update: (next: object) => void, destroy: () => void, size: () => number }}
 */
export function addLivePoints(viewer, { layerId, rows = [] } = {}) {
  const style = LIVE_LAYER_STYLE[layerId] || LIVE_LAYER_STYLE.aircraft
  const entities = []

  const add = (row, index) => {
    const lat = Number(row?.lat)
    const lon = Number(row?.lon)
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return
    const magnitude = Number(row?.mag)
    const pixelSize = layerId === 'earthquakes' && Number.isFinite(magnitude)
      ? Math.min(26, style.pixelSize + Math.max(0, magnitude) * 2)
      : style.pixelSize
    entities.push(
      viewer.entities.add({
        id: `live-${layerId}-${index}`,
        position: Cesium.Cartesian3.fromDegrees(lon, lat, liveHeight(layerId, row)),
        point: {
          pixelSize,
          color: colourFor(style.colour, 0.95),
          outlineColor: colourFor('#07080d', 0.9),
          outlineWidth: style.outline,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: {
          text: liveLabel(layerId, row),
          ...labelStyle(),
          // The ward-label distance window (0–90 km) would hide these: a
          // satellite is 420 km up and an earthquake can be on the far side of
          // the planet, so the live labels have no distance cut-off at all.
          distanceDisplayCondition: undefined,
          // No background either: with a hundred aircraft the boxes merge into
          // a wall of colour, and the outline already carries the text.
          backgroundColor: undefined,
          scaleByDistance: new Cesium.NearFarScalar(200000, 0.9, 25000000, 0.55),
        },
      }),
    )
  }

  rows.forEach(add)

  function update({ rows: nextRows = rows } = {}) {
    destroy()
    ;(nextRows || []).forEach(add)
  }

  function destroy() {
    for (const entity of entities) viewer.entities.remove(entity)
    entities.length = 0
  }

  return { update, destroy, size: () => entities.length }
}

/**
 * Hover + click picking for whatever entities are on screen.
 * Returns a teardown function; the handler is owned by the caller's scene.
 */
export function bindPicking(viewer, { ids, onHover, onSelect }) {
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas)
  const readId = (movement) => {
    const picked = viewer.scene.pick(movement.endPosition || movement.position)
    const entity = picked?.id
    const entityId = entity?.id
    return typeof entityId === 'string' && ids.some((prefix) => entityId.startsWith(prefix))
      ? entityId
      : null
  }
  handler.setInputAction((movement) => {
    onHover?.(readId(movement), movement.endPosition)
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE)
  handler.setInputAction((movement) => {
    const entityId = readId({ position: movement.position })
    if (entityId) onSelect?.(entityId)
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK)
  return () => handler.isDestroyed?.() !== true && handler.destroy()
}
