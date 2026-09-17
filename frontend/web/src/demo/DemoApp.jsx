import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { DEMO_DISCLAIMER, DEMO_SCREEN_IDS, DEMO_SCREEN_LABELS, EMPTY_DEMO_PAYLOAD, finiteNumber, text } from './contract.js'
import { loadDemoPayload } from './data.js'
import { DemoScreen } from './screens.js'
import { useMotionSafe, spring } from '../motion.js'

const DemoMap = lazy(() => import('./DemoMap.jsx'))

const LEAD_DAYS = [0, 1, 2, 3, 4, 5]

export default function DemoApp({ onExit }) {
  const { reduced, t } = useMotionSafe()
  const [scenarioId, setScenarioId] = useState('dry-extreme')
  const [screen, setScreen] = useState('now')
  const [leadDay, setLeadDay] = useState(3)
  const [selectedZoneId, setSelectedZoneId] = useState('central-delhi')
  const [mapLayer, setMapLayer] = useState('level')
  const [showCooling, setShowCooling] = useState(false)
  const [payload, setPayload] = useState(EMPTY_DEMO_PAYLOAD)
  const [status, setStatus] = useState('loading') // loading | ready | error
  const [error, setError] = useState('')
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    setStatus('loading')
    loadDemoPayload(scenarioId, { signal: controller.signal })
      .then((next) => {
        if (cancelled) return
        setPayload(next)
        setStatus('ready')
        if (next.zones.length && !next.zones.some((zone) => zone.zone_id === selectedZoneId)) {
          setSelectedZoneId(next.zones[0].zone_id)
        }
      })
      .catch((err) => {
        if (cancelled || err?.name === 'AbortError') return
        setError(text(err.message, 'Unknown error'))
        setStatus('error')
      })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [scenarioId, reloadToken]) // eslint-disable-line react-hooks/exhaustive-deps

  const scenarioOptions = payload.scenarios.list
  const zones = payload.zones

  const dayRows = useMemo(
    () => payload.warnings.rows.filter((row) => row.lead_days === leadDay),
    [payload, leadDay],
  )

  const hasData = payload.warnings.rows.length > 0 || payload.scenarios.list.length > 0

  return (
    <div className="demo-app" data-testid="demo-app">
      <header className="demo-header">
        <div className="demo-header__titles">
          <p className="demo-kicker">HEATSHIELD · HEAT RISK DEMO</p>
          <h1>Impact-based early-warning demo — synthetic scenario data</h1>
          <p className="demo-disclaimer" role="status">{DEMO_DISCLAIMER}</p>
        </div>
        <div className="demo-header__actions">
          {onExit
            ? <button type="button" className="demo-btn demo-btn--ghost" onClick={onExit}>Exit demo</button>
            : null}
        </div>
      </header>

      <section className="demo-controls" aria-label="Demo controls">
        <div className="demo-control" data-testid="scenario-controls">
          <span className="demo-control__label" id="demo-scenario-label">Scenario</span>
          <div className="demo-scenario-row" role="group" aria-labelledby="demo-scenario-label">
            {(scenarioOptions.length ? scenarioOptions : [{ id: scenarioId, label: scenarioId }]).map((option) => (
              <button
                key={option.id}
                type="button"
                className={`demo-btn demo-btn--scenario${option.id === scenarioId ? ' is-active' : ''}`}
                aria-pressed={option.id === scenarioId}
                onClick={() => setScenarioId(option.id)}
                title={text(option.tagline, '')}
              >
                {text(option.label, option.id)}
              </button>
            ))}
          </div>
        </div>

        <div className="demo-control">
          <label className="demo-control__label" htmlFor="demo-zone-select">Zone</label>
          <select
            id="demo-zone-select"
            className="demo-select"
            value={selectedZoneId}
            onChange={(event) => setSelectedZoneId(event.target.value)}
          >
            {(zones.length ? zones : [{ zone_id: selectedZoneId, zone_name: 'No zones loaded' }]).map((zone) => (
              <option key={zone.zone_id} value={zone.zone_id}>{zone.zone_name}</option>
            ))}
          </select>
        </div>

        <div className="demo-control">
          <span className="demo-control__label" id="demo-lead-label">Lead day</span>
          <div className="demo-lead-row" role="group" aria-labelledby="demo-lead-label">
            {LEAD_DAYS.map((day) => (
              <button
                key={day}
                type="button"
                className={`demo-btn demo-btn--lead${day === leadDay ? ' is-active' : ''}`}
                aria-pressed={day === leadDay}
                onClick={() => setLeadDay(day)}
              >
                Day +{day}
              </button>
            ))}
          </div>
        </div>

        <div className="demo-control">
          <label className="demo-control__label" htmlFor="demo-layer-select">Map layer</label>
          <select
            id="demo-layer-select"
            className="demo-select"
            value={mapLayer}
            onChange={(event) => setMapLayer(event.target.value)}
          >
            <option value="level">Alert level</option>
            <option value="thermal">Thermal stress (HTSI)</option>
            <option value="vulnerability">Vulnerability</option>
            <option value="outlook">Heatwave outlook</option>
          </select>
          <label className="demo-check">
            <input
              type="checkbox"
              checked={showCooling}
              onChange={(event) => setShowCooling(event.target.checked)}
            />
            Show cooling centres (demo)
          </label>
        </div>
      </section>

      <nav className="demo-tabs" aria-label="Demo views">
        {DEMO_SCREEN_IDS.map((id) => (
          <button
            key={id}
            type="button"
            className={`demo-btn demo-btn--tab${id === screen ? ' is-active' : ''}`}
            aria-current={id === screen ? 'true' : undefined}
            onClick={() => setScreen(id)}
          >
            {DEMO_SCREEN_LABELS[id]}
          </button>
        ))}
      </nav>

      <div className="demo-body">
        <div className="demo-panel demo-panel--map">
          <h2 className="demo-panel__title">
            GIS view — {text(payload.scenario.label, scenarioId)} · Day +{leadDay}
            <span className="demo-panel__sub"> synthetic zone values</span>
          </h2>
          <Suspense fallback={<div className="demo-map demo-map--empty" aria-busy="true">Loading map…</div>}>
            <DemoMap
              rows={dayRows}
              zones={zones}
              layer={mapLayer}
              leadDay={leadDay}
              selectedZoneId={selectedZoneId}
              showCooling={showCooling}
              onSelect={setSelectedZoneId}
            />
          </Suspense>
          <p className="demo-note">
            Map unavailable or not to hand? Every layer is reproduced, in words and numbers, on the Zones and Impact tabs — and the whole demo works offline from bundled snapshots.
          </p>
        </div>

        <div className="demo-panel demo-panel--screen">
          {status === 'error'
            ? (
              <div className="demo-error" role="alert">
                <h2>Demo payload could not load</h2>
                <p>{error}</p>
                <p className="demo-note">
                  The demo never needs credentials or live APIs: if this appears, the app was started without its bundled snapshots
                  (run <code>HS_FORECAST_DAYS=5 python -m scripts.export_static</code> and rebuild the frontend).
                </p>
                <button type="button" className="demo-btn" onClick={() => setReloadToken((token) => token + 1)}>Try again</button>
              </div>
            )
            : (
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={`${scenarioId}-${screen}-${leadDay}-${status}`}
                  className="demo-screen-slot"
                  initial={reduced ? { opacity: 1 } : { opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reduced ? { opacity: 1 } : { opacity: 0, y: -6 }}
                  transition={t(spring.normal)}
                  aria-busy={status === 'loading'}
                >
                  {status === 'loading' && !hasData
                    ? <p className="demo-empty" role="status">Loading demo scenario “{scenarioId}”…</p>
                    : null}
                  {status === 'loading' && hasData
                    ? <p className="demo-note" role="status">Switching scenario…</p>
                    : null}
                  {status !== 'error'
                    ? (
                      <DemoScreen
                        screen={screen}
                        payload={payload}
                        selectedZoneId={selectedZoneId}
                        leadDay={finiteNumber(leadDay, 3)}
                      />
                    )
                    : null}
                </motion.div>
              </AnimatePresence>
            )}
        </div>
      </div>

      <footer className="demo-footer">
        <p>{DEMO_DISCLAIMER}</p>
        <p className="demo-note">
          Fixed demo clock · deterministic synthetic scenarios · normals from the real fixed climatology reference ·
          health-impact rows are parameterised indicators, never validated mortality forecasts.
        </p>
      </footer>
    </div>
  )
}
