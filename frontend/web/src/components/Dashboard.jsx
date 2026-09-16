import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
// Leaflet + react-leaflet are ~40 kB gzip and only the dashboard needs them.
// Loading them lazily keeps the landing page bundle small.
const RiskMap = lazy(() => import('./RiskMap'))
import AlertsPanel from './AlertsPanel'
import Gauge from './Gauge'
import HourlyChart from './HourlyChart'
import Odometer from './Odometer'
import StatsStrip from './StatsStrip'
import TopWardsTable from './TopWardsTable'
import { bandColour, bandText, EASE, spring } from '../motion'
import { ALERT_THRESHOLD, fetchAlerts, fetchGeo, fetchHourly, fetchRanking,
         fetchWardRisk } from '../api'

const SCENARIOS = [0, 2, 4, 6, 8]

function Clock() {
  const [t, setT] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setT(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return <span className="tnum text-[11.5px] text-white/40">{t.toLocaleTimeString('en-IN', { hour12: false })}</span>
}

function Driver({ label, value, unit, delay = 0 }) {
  return (
    <motion.div
      className="flex items-baseline justify-between border-b border-white/[.06] py-2 last:border-0"
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.5, ease: EASE, delay }}
    >
      <span className="text-[11.5px] text-white/40">{label}</span>
      <span className="tnum text-[13px] font-medium">
        {value}
        <span className="ml-0.5 text-[10px] text-white/35">{unit}</span>
      </span>
    </motion.div>
  )
}

/** Placeholder with the same footprint as the map, so nothing jumps on load. */
function MapSkeleton() {
  return (
    <div className="flex h-[420px] items-center justify-center rounded-xl border border-white/10 bg-white/[.02]">
      <motion.div
        className="h-1 w-40 overflow-hidden rounded-full bg-white/10"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
      >
        <motion.div
          className="h-full w-1/3 rounded-full bg-orange-400/70"
          animate={{ x: ['-100%', '300%'] }}
          transition={{ duration: 1.1, repeat: Infinity, ease: 'easeInOut' }}
        />
      </motion.div>
    </div>
  )
}

export default function Dashboard({ onExit }) {
  const [ranking, setRanking] = useState(null)
  const [hourly, setHourly] = useState([])
  const [ward, setWard] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [scenario, setScenario] = useState(0)
  const [loading, setLoading] = useState(true)
  const [geo, setGeo] = useState(null)
  const [alerts, setAlerts] = useState(null)

  // refetch when the scenario changes
  useEffect(() => {
    let alive = true
    setLoading(true)
    fetchRanking(scenario).then((d) => {
      if (!alive) return
      setRanking(d)
      setLoading(false)
    })
    return () => {
      alive = false
    }
  }, [scenario])

  // real ward boundaries, cached by the service worker for offline use
  useEffect(() => {
    fetchGeo().then(setGeo)
  }, [])

  const rows = ranking?.data || []

  // default-select the worst ward the first time data arrives
  useEffect(() => {
    if (rows.length && selectedId == null) setSelectedId(rows[0].ward_id)
  }, [rows, selectedId])

  const selected = useMemo(() => rows.find((r) => r.ward_id === selectedId) || rows[0], [rows, selectedId])

  useEffect(() => {
    if (!selected) return
    let alive = true
    fetchWardRisk(selected.ward_id).then((d) => alive && setWard(d))
    fetchHourly(selected.ward_id).then((d) => alive && setHourly(d?.data || []))
    return () => {
      alive = false
    }
  }, [selected])

  // alert queue follows the scenario too
  useEffect(() => {
    let alive = true
    fetchAlerts(ALERT_THRESHOLD, 1, scenario).then((d) => alive && setAlerts(d))
    return () => {
      alive = false
    }
  }, [scenario, ranking])

  const critical = rows.filter((r) => r.risk_band === 'Critical' || r.risk_band === 'Extreme')
  const danger = rows.filter((r) => r.risk_band === 'Danger')
  const colour = bandColour[selected?.risk_band] || '#22c55e'

  return (
    <div className="relative min-h-screen">
      {/* ---------------------------------------------------------- top bar */}
      <header
        className="sticky top-0 z-40 backdrop-blur-md"
        style={{ background: 'rgba(7,8,13,.72)', borderBottom: '1px solid rgba(255,255,255,.08)' }}
      >
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-4 px-6 py-3">
          <button onClick={onExit} className="flex items-center gap-2.5 transition hover:opacity-70">
            <div className="h-5 w-5 rounded-full" style={{ background: 'linear-gradient(135deg,#ff5f6d,#ffc371)' }} />
            <span className="display text-[18px]">HeatShield</span>
          </button>
          <span className="hidden text-[10px] uppercase tracking-[0.2em] text-white/30 sm:block">operations</span>

          <div className="flex-1" />

          {/* scenario control — the demo lever */}
          <div className="flex items-center gap-2">
            <span className="eyebrow hidden md:block">scenario</span>
            <div className="flex gap-1 rounded-full border border-white/10 bg-white/[.04] p-1">
              {SCENARIOS.map((s) => (
                <button
                  key={s}
                  onClick={() => setScenario(s)}
                  className="relative rounded-full px-2.5 py-1 text-[11px] transition"
                >
                  {selectedId === s && <span />}
                  {scenario === s && (
                    <motion.span
                      layoutId="scenarioPill"
                      className="absolute inset-0 rounded-full bg-white/[.14]"
                      transition={spring.layout}
                    />
                  )}
                  <span className="relative tnum">{s > 0 ? `+${s}°` : 'now'}</span>
                </button>
              ))}
            </div>
          </div>

          <Clock />
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 py-7">
        {/* -------------------------------------------------------- alert */}
        <AnimatePresence>
          {(critical.length > 0 || danger.length > 0) && (
            <motion.div
              className="relative mb-6 overflow-hidden rounded-2xl"
              style={{
                border: `1px solid ${critical.length ? 'rgba(239,68,68,.5)' : 'rgba(249,115,22,.45)'}`,
                background: critical.length ? 'rgba(239,68,68,.1)' : 'rgba(249,115,22,.09)',
              }}
              initial={{ opacity: 0, height: 0, marginBottom: 0 }}
              animate={{ opacity: 1, height: 'auto', marginBottom: 24 }}
              exit={{ opacity: 0, height: 0, marginBottom: 0 }}
              transition={{ duration: 0.55, ease: EASE }}
            >
              <div
                className="absolute inset-0"
                style={{
                  backgroundImage:
                    'repeating-linear-gradient(135deg, rgba(255,255,255,.05) 0 14px, transparent 14px 28px)',
                }}
              />
              <motion.div
                className="absolute inset-0"
                style={{
                  backgroundImage:
                    'repeating-linear-gradient(135deg, rgba(255,255,255,.05) 0 14px, transparent 14px 28px)',
                }}
                animate={{ backgroundPosition: ['0px 0px', '39.6px 0px'] }}
                transition={{ duration: 1.4, repeat: Infinity, ease: 'linear' }}
              />
              <div className="relative flex items-start gap-3 p-4">
                <motion.span
                  className="mt-0.5 text-base"
                  animate={{ scale: [1, 1.18, 1] }}
                  transition={{ duration: 1.6, repeat: Infinity }}
                >
                  🚨
                </motion.span>
                <div className="text-[13px] leading-relaxed">
                  <span className="font-semibold" style={{ color: critical.length ? '#ffb4b4' : '#fdba74' }}>
                    {critical.length
                      ? `CRITICAL — ${critical.length} ward${critical.length > 1 ? 's' : ''}`
                      : `HEAT ADVISORY — ${danger.length} ward${danger.length > 1 ? 's' : ''}`}
                  </span>
                  <span className="text-white/60">
                    {' '}
                    {critical.length
                      ? `${critical.map((c) => c.ward_name).join(', ')} exceed safe working limits. Suspend non-essential outdoor labour 12:00–15:00.`
                      : `${danger.map((c) => c.ward_name).join(', ')} in the danger band. Enforce hourly shaded breaks for outdoor workers.`}
                  </span>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ------------------------------------------------- summary strip */}
        <StatsStrip
          wards={rows}
          bandCounts={ranking?.band_counts || {}}
          mapDate={ranking?.date}
          alerts={alerts}
          threshold={ALERT_THRESHOLD}
        />

        {/* -------------------------------------------------------- alerts */}
        <AlertsPanel alerts={alerts} scenario={scenario} />

        {/* -------------------------------------------------------- grid */}
        <div className="grid gap-5 lg:grid-cols-[1.5fr_1fr] mt-5">
          {/* map */}
          <motion.section className="panel min-w-0 p-5" initial={{ opacity: 0, y: 22 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, ease: EASE }}>
            {/* flex-wrap + min-w-0: without them the title+legend force a
                min-content width wider than the column and overflow on mobile */}
            <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <h2 className="text-[14px] font-medium">Ward risk layer</h2>
                <p className="text-[11px] leading-snug text-white/35">
                  {ranking?.date || '—'} · {rows.length} KMC wards · OpenStreetMap basemap
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-white/40">
                {Object.entries(bandColour).slice(0, 4).map(([k, v]) => (
                  <span key={k} className="flex items-center gap-1.5">
                    <i className="inline-block h-2 w-2 rounded-sm" style={{ background: v }} />
                    {k}
                  </span>
                ))}
              </div>
            </div>

            {loading && !rows.length ? (
              <div className="flex h-[340px] items-center justify-center text-[12px] text-white/30">
                <motion.span animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1.4, repeat: Infinity }}>
                  fetching ward risk…
                </motion.span>
              </div>
            ) : (
              <Suspense fallback={<MapSkeleton />}>
                <RiskMap geo={geo} wards={rows} selectedId={selected?.ward_id}
                         onSelect={(w) => setSelectedId(w.ward_id)} />
              </Suspense>
            )}
          </motion.section>

          {/* gauge + detail */}
          <motion.section
            className="panel flex min-w-0 flex-col p-5"
            initial={{ opacity: 0, y: 22 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: EASE, delay: 0.08 }}
          >
            <div className="mb-1 flex items-center justify-between">
              <h2 className="text-[14px] font-medium">Risk index</h2>
              <span className="eyebrow">0 – 100</span>
            </div>

            <AnimatePresence mode="wait">
              <motion.div
                key={selected?.ward_id}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -14 }}
                transition={{ duration: 0.4, ease: EASE }}
              >
                <p className="mb-1 text-center text-[11px] text-white/35">{selected?.ward_name}</p>
                <Gauge
                  value={selected?.risk_score || 0}
                  band={selected?.risk_band || 'Normal'}
                  caption={bandText[selected?.risk_band] || ''}
                />
              </motion.div>
            </AnimatePresence>

            <div className="mt-5">
              <div className="eyebrow mb-1.5">drivers</div>
              <Driver label="Peak WBGT" value={ward?.drivers?.wbgt_peak_c?.toFixed(1) ?? '—'} unit="°C" delay={0.05} />
              <Driver label="Hazard score" value={ward?.drivers?.hazard_score?.toFixed(0) ?? '—'} unit="/100" delay={0.1} />
              <Driver label="Vulnerability" value={ward?.drivers?.vulnerability?.toFixed(0) ?? '—'} unit="/100" delay={0.15} />
              <Driver label="Urban heat island" value={`+${ward?.drivers?.uhi_delta_c?.toFixed(2) ?? '—'}`} unit="°C" delay={0.2} />
              <Driver label="Ward Tmax" value={ward?.drivers?.tmax_ward_c?.toFixed(1) ?? '—'} unit="°C" delay={0.25} />
            </div>

            <div className="mt-5 grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-white/10 bg-white/[.03] p-3">
                <div className="eyebrow">exposed</div>
                <div className="mt-1.5 flex items-baseline gap-1">
                  <Odometer value={(ward?.impact?.exposed_population || 0) / 1000} decimals={1} height={1.1} className="text-[20px] font-semibold" />
                  <span className="text-[10px] text-white/35">k people</span>
                </div>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/[.03] p-3">
                <div className="eyebrow">relative risk</div>
                <div className="mt-1.5 flex items-baseline gap-1">
                  <Odometer value={ward?.impact?.relative_risk || 1} decimals={2} height={1.1} className="text-[20px] font-semibold" />
                  <span className="text-[10px] text-white/35">× baseline</span>
                </div>
              </div>
            </div>
          </motion.section>
        </div>

        {/* -------------------------------------------------------- ward strip */}
        <motion.section
          className="mt-5 grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: EASE, delay: 0.16 }}
        >
          {rows.slice(0, 14).map((w, i) => {
            const isSel = w.ward_id === selected?.ward_id
            const c = bandColour[w.risk_band] || '#22c55e'
            return (
              <motion.button
                key={w.ward_id}
                onClick={() => setSelectedId(w.ward_id)}
                className="relative overflow-hidden rounded-xl border p-3 text-left"
                style={{
                  borderColor: isSel ? c : 'rgba(255,255,255,.09)',
                  background: isSel ? `${c}18` : 'rgba(255,255,255,.03)',
                }}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.55, ease: EASE, delay: i * 0.03 }}
                whileHover={{ y: -3, backgroundColor: `${c}22` }}
                whileTap={{ scale: 0.97 }}
              >
                {isSel && (
                  <motion.span
                    layoutId="wardHighlight"
                    className="absolute inset-0 rounded-xl"
                    style={{ border: `1px solid ${c}` }}
                    transition={spring.layout}
                  />
                )}
                <div className="relative truncate text-[11.5px] font-medium text-white/80">{w.ward_name}</div>
                <div className="relative mt-1 flex items-baseline gap-1">
                  <span className="tnum text-[19px] font-bold" style={{ color: c }}>
                    {Math.round(w.risk_score)}
                  </span>
                  <span className="text-[9px] uppercase tracking-wider text-white/30">{w.risk_band}</span>
                </div>
              </motion.button>
            )
          })}
        </motion.section>

        {/* -------------------------------------------------------- chart */}
        <motion.section
          className="panel mt-5 p-5"
          initial={{ opacity: 0, y: 22 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: EASE, delay: 0.22 }}
        >
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-[14px] font-medium">24-hour thermal stress</h2>
              <p className="text-[11px] text-white/35">{selected?.ward_name} · wet-bulb globe temperature, UHI-adjusted</p>
            </div>
            <motion.span
              className="rounded-full px-2.5 py-1 text-[10px] font-semibold"
              animate={{ backgroundColor: `${colour}22`, color: colour }}
              transition={{ duration: 0.4 }}
            >
              {selected?.risk_band}
            </motion.span>
          </div>
          <AnimatePresence mode="wait">
            <motion.div
              key={selected?.ward_id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
            >
              <HourlyChart data={hourly} metric="wbgt_adj_c" unit="°C WBGT" />
            </motion.div>
          </AnimatePresence>
        </motion.section>

        {/* ------------------------------------------------- ranked table */}
        <TopWardsTable
          wards={rows}
          selectedId={selected?.ward_id}
          onSelect={setSelectedId}
        />

        <motion.div
          className="panel mt-5 p-5"
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: EASE, delay: 0.26 }}
        >
          <div className="eyebrow">data provenance</div>
          <div className="mt-3 grid gap-3 text-[11px] leading-relaxed text-white/45 md:grid-cols-2">
            <div>
              <div className="text-white/70">Real</div>
              <ul className="mt-1.5 space-y-1">
                <li>· Weather — live Open-Meteo forecast (national weather-service models)</li>
                <li>· Ward boundaries — 141 KMC wards, OpenCity / ODbL</li>
                <li>· Population — Census 2011 via Wikidata (sums to 4,496,694, the official KMC total)</li>
                <li>· Literacy, household size, worker share — Census 2011 Primary Census Abstract,
                    ward level (official Government of India file)</li>
                <li>· Green cover, water, buildings — OpenStreetMap via Overpass</li>
                <li>· Physics — Stull wet-bulb, Rothfusz heat index, ISO 7243 WBGT</li>
              </ul>
            </div>
            <div>
              <div className="text-amber-300/80">Modelled or missing</div>
              <ul className="mt-1.5 space-y-1">
                <li>· UHI increment — modelled from measured density &amp; green cover, capped at 3.5 °C</li>
                <li>· Excess mortality — illustrative; baseline rate real, dose–response assumed</li>
                <li>· <span className="text-amber-200/90">Population aged 60+ is NOT included</span> —
                    the single strongest driver of heat mortality, and the one ward-level figure with no
                    machine-readable source. It is absent rather than invented, so the index measures
                    exposure, urban form and socioeconomic deprivation — not physiological frailty.</li>
                <li>· Slum-household share is NOT included — it sits in the Census slum tables, not the ward PCA.</li>
                <li>· OSM completeness varies by ward, so green/building figures partly reflect mapping
                    effort rather than ground truth.</li>
              </ul>
            </div>
          </div>
        </motion.div>
      </main>
    </div>
  )
}
