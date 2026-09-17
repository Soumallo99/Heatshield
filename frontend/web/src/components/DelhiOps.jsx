import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { formatNumber, formatTemp, levelLabel, normaliseDemoPayload, text } from '../demo/contract.js'
import { DemoScreen } from '../demo/screens.js'

const DemoMap = lazy(() => import('../demo/DemoMap.jsx'))

const BASE_PATH = import.meta.env.BASE_URL || './'
const staticURL = (name) => `${BASE_PATH.replace(/\/?$/, '/')}static-api/${name}`

async function readJSON(url, signal) {
  const response = await fetch(url, { headers: { Accept: 'application/json' }, signal })
  if (!response.ok) throw new Error(`${url} returned ${response.status}`)
  return response.json()
}

/* Honesty first: the live advance-warning payload says whether it is a real
   forecast or the labelled synthetic outage exercise — the banner mirrors it. */
function disclaimerFor(doc) {
  return doc?.quality_state === 'live-forecast'
    ? 'Live model forecast for Delhi NCR — operational-style advance warning. Not an official IMD declaration; the health-impact indicator is parameterised, not a validated mortality forecast.'
    : 'Practice data (provider outage fallback) — not a live forecast or observation.'
}

/* /warnings/advance rows carry the SAME field contract as the demo warnings,
   so the demo normaliser + screens are reused verbatim on live data — one
   contract, two data sources, no duplicated rendering logic. */
function buildPayload(doc) {
  const zonesById = new Map()
  for (const row of Array.isArray(doc?.data) ? doc.data : []) {
    if (!zonesById.has(row.zone_id)) {
      zonesById.set(row.zone_id, {
        zone_id: row.zone_id,
        zone_name: row.zone_name,
        lat: row.lat,
        lon: row.lon,
        population: null,
        elderly_pct: null,
        outdoor_worker_pct: null,
        illiteracy_pct: null,
        cooling_centre_count: null,
        cooling_access_score: null,
        vulnerability_score: row.vulnerability_score,
        vulnerability_level: row.vulnerability_level,
        vulnerability_source: row.vulnerability_source,
        cooling_centres: [],
      })
    }
  }
  return normaliseDemoPayload({
    scenarios: { demo_disclaimer: disclaimerFor(doc), is_demo: false, scenarios: [] },
    zones: { data: [...zonesById.values()] },
    forecast: { daily: [], hourly: [] },
    thermal: { method: doc?.thermal_method || {}, wbgt_statement: '' },
    warnings: doc || {},
    notifications: { previews: [], rows: 0, dry_run: true },
  })
}

const VIEWS = [
  { id: 'zones', label: 'Zone table' },
  { id: 'outlook', label: 'Outlook' },
  { id: 'impact', label: 'Impact detail' },
]

/**
 * Delhi-NCR operations view: the live (or labelled-practice) advance-warning
 * engine rendered with the same GIS + table components as the Heat Risk Demo.
 * Kolkata keeps its ward-level console; this is the zone-level NCR sibling.
 */
export default function DelhiOps() {
  const [payload, setPayload] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  const [source, setSource] = useState('')
  const [view, setView] = useState('zones')
  const [leadDay, setLeadDay] = useState(3)
  const [layer, setLayer] = useState('level')
  const [zoneId, setZoneId] = useState('')
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setStatus('loading')
    setError('')
    const load = async () => {
      try {
        const doc = await readJSON('./api/warnings/advance', controller.signal)
        return { doc, via: 'live API' }
      } catch (liveError) {
        if (liveError?.name === 'AbortError') throw liveError
        try {
          const doc = await readJSON(staticURL('warnings-advance.json'), controller.signal)
          return { doc, via: `saved snapshot (${liveError.message})` }
        } catch (staticError) {
          if (staticError?.name === 'AbortError') throw staticError
          throw new Error(`${liveError.message}; no saved snapshot (${staticError.message})`)
        }
      }
    }
    load()
      .then(({ doc, via }) => {
        if (!active) return
        setPayload(buildPayload(doc))
        setSource(via)
        setStatus('ready')
      })
      .catch((loadError) => {
        if (!active || loadError?.name === 'AbortError') return
        setError(text(loadError.message, 'Unable to load Delhi NCR warnings.'))
        setStatus('error')
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [reloadToken])

  const zones = payload?.zones || []
  const dayRows = useMemo(
    () => (payload ? payload.warnings.rows.filter((row) => row.lead_days === leadDay) : []),
    [payload, leadDay],
  )
  const severeToday = useMemo(
    () => (payload ? payload.warnings.rows.filter((row) => row.alert_level === 'severe').length : 0),
    [payload],
  )

  if (status === 'error') {
    return (
      <div className="demo-panel" style={{ margin: '18px auto', maxWidth: 720 }}>
        <h2 className="demo-panel__title">Delhi NCR warnings could not load</h2>
        <p className="demo-note">{error}</p>
        <p className="demo-note">
          Start the API (<code>python -m uvicorn app.main:app --port 8000</code>) or regenerate snapshots
          (<code>HS_FORECAST_DAYS=5 python -m scripts.export_static</code>).
        </p>
        <button type="button" className="demo-btn" onClick={() => setReloadToken((token) => token + 1)}>Try again</button>
      </div>
    )
  }

  return (
    <div className="demo-app" style={{ paddingTop: 10 }}>
      <header className="demo-header">
        <div className="demo-header__titles">
          <p className="demo-kicker">DELHI NCR · ZONE-LEVEL ADVANCE WARNINGS</p>
          <h1>Delhi NCR operations — 8 zones, leads Day +0…+5</h1>
          {payload ? <p className="demo-disclaimer" role="status">{payload.disclaimer}</p> : null}
        </div>
      </header>

      {payload ? (
        <div className="demo-metric-grid" style={{ marginBottom: 14 }}>
          <div className="demo-metric">
            <span className="demo-metric__label">Issued</span>
            <strong className="demo-metric__value" style={{ fontSize: 15 }}>{text(payload.warnings.issued_at, '—')}</strong>
            <span className="demo-metric__hint">{source}</span>
          </div>
          <div className="demo-metric">
            <span className="demo-metric__label">Warning rows</span>
            <strong className="demo-metric__value">{formatNumber(payload.warnings.rows.length, 0)}</strong>
            <span className="demo-metric__hint">{formatNumber(zones.length, 0)} zones × leads 0–5</span>
          </div>
          <div className="demo-metric">
            <span className="demo-metric__label">Severe rows</span>
            <strong className="demo-metric__value">{formatNumber(severeToday, 0)}</strong>
            <span className="demo-metric__hint">across the whole window</span>
          </div>
          <div className="demo-metric">
            <span className="demo-metric__label">Quality state</span>
            <strong className="demo-metric__value" style={{ fontSize: 15 }}>{text(payload.warnings.rows[0]?.quality_state, 'unknown')}</strong>
            <span className="demo-metric__hint">{text(payload.warnings.rows[0]?.data_source, '')}</span>
          </div>
        </div>
      ) : (
        <p className="demo-empty" role="status">Loading Delhi NCR advance warnings…</p>
      )}

      {payload ? (
        <>
          <section className="demo-controls" aria-label="Delhi NCR view controls">
            <div className="demo-control">
              <span className="demo-control__label" id="delhi-view-label">Table view</span>
              <div className="demo-lead-row" role="group" aria-labelledby="delhi-view-label">
                {VIEWS.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    className={`demo-btn${entry.id === view ? ' is-active' : ''}`}
                    aria-pressed={entry.id === view}
                    onClick={() => setView(entry.id)}
                  >
                    {entry.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="demo-control">
              <span className="demo-control__label" id="delhi-lead-label">Lead day</span>
              <div className="demo-lead-row" role="group" aria-labelledby="delhi-lead-label">
                {[0, 1, 2, 3, 4, 5].map((day) => (
                  <button
                    key={day}
                    type="button"
                    className={`demo-btn${day === leadDay ? ' is-active' : ''}`}
                    aria-pressed={day === leadDay}
                    onClick={() => setLeadDay(day)}
                  >
                    Day +{day}
                  </button>
                ))}
              </div>
            </div>
            <div className="demo-control">
              <label className="demo-control__label" htmlFor="delhi-layer">Map layer</label>
              <select id="delhi-layer" className="demo-select" value={layer} onChange={(event) => setLayer(event.target.value)}>
                <option value="level">Alert level</option>
                <option value="thermal">Thermal stress (HTSI)</option>
                <option value="vulnerability">Vulnerability</option>
                <option value="outlook">Heatwave outlook</option>
              </select>
            </div>
            <div className="demo-control">
              <label className="demo-control__label" htmlFor="delhi-zone">Zone focus</label>
              <select
                id="delhi-zone"
                className="demo-select"
                value={zoneId}
                onChange={(event) => setZoneId(event.target.value)}
              >
                <option value="">Worst zone per day</option>
                {zones.map((zone) => (
                  <option key={zone.zone_id} value={zone.zone_id}>{zone.zone_name}</option>
                ))}
              </select>
            </div>
          </section>

          <div className="demo-body">
            <div className="demo-panel demo-panel--map">
              <h2 className="demo-panel__title">
                GIS view — Day +{leadDay}
                <span className="demo-panel__sub"> zone grid points, not street-level observations</span>
              </h2>
              <Suspense fallback={<div className="demo-map demo-map--empty" aria-busy="true">Loading map…</div>}>
                <DemoMap
                  rows={dayRows}
                  zones={zones}
                  layer={layer}
                  leadDay={leadDay}
                  selectedZoneId={zoneId}
                  showCooling={false}
                  onSelect={setZoneId}
                />
              </Suspense>
              <p className="demo-note">
                {text(payload.warnings.granularity_note, 'Zones are ~10 km model grid points.')}
                {' '}The zone table reproduces every layer in words and numbers.
              </p>
            </div>
            <div className="demo-panel demo-panel--screen">
              <DemoScreen screen={view} payload={payload} selectedZoneId={zoneId} leadDay={leadDay} />
            </div>
          </div>
        </>
      ) : null}

      <footer className="demo-footer">
        <p className="demo-note">
          Departures use the fixed 1991–2020 climatology; heatwave episodes require two consecutive
          qualifying days; the health-impact indicator is parameterised — never a validated mortality
          forecast. Notification sending stays dry-run unless both live locks are opened
          (<code>python -m scripts.dispatch_notifications --live</code>).
        </p>
      </footer>
    </div>
  )
}
