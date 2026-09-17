import { useState } from 'react'
import { motion, useScroll, useSpring, useTransform } from 'framer-motion'
import WordReveal from './WordReveal'
import Odometer from './Odometer'
import { RefreshButton } from './LiveStatus'
import { EASE, spring, useMotionSafe } from '../motion'
import { useLive, useRefreshShortcut } from '../live'
import { ALERT_THRESHOLD, fetchAlerts, fetchRanking, fetchZones } from '../api'

/* ----------------------------------------------------------- scroll progress */
function ScrollRail() {
  const { scrollYProgress } = useScroll()
  const scaleX = useSpring(scrollYProgress, { stiffness: 120, damping: 28, restDelta: 0.001 })
  return (
    <motion.div
      className="fixed left-0 top-0 z-50 h-[2px] w-full origin-left"
      style={{
        scaleX,
        background: 'linear-gradient(90deg,#22d3ee,#f97316,#ef4444)',
      }}
    />
  )
}

/* ----------------------------------------------------------- ticker */
function Ticker({ items, note }) {
  const { reduced } = useMotionSafe()
  if (!items.length) {
    return (
      <div className="border-y border-white/10 bg-white/[.02] py-2.5 text-center text-[12px] text-white/35">
        {note || 'waiting for the live ward feed…'}
      </div>
    )
  }
  const row = [...items, ...items]
  return (
    <div className="overflow-hidden border-y border-white/10 bg-white/[.02] py-2.5">
      <motion.div
        className="flex w-max whitespace-nowrap"
        animate={reduced ? {} : { x: ['0%', '-50%'] }}
        transition={{ duration: 42, repeat: Infinity, ease: 'linear' }}
      >
        {row.map((s, i) => (
          <span key={i} className="px-8 text-[12px] text-white/45">
            <span className="mr-2 text-orange-400/70">◉</span>
            {s}
          </span>
        ))}
      </motion.div>
    </div>
  )
}

/* ----------------------------------------------------------- step card */
const STEPS = [
  {
    n: '01',
    t: 'Forecast',
    d: 'Six days of hourly weather — temperature, humidity, wind and solar radiation — pulled from open models for every ward in four batched, keyless requests.',
  },
  {
    n: '02',
    t: 'Translate',
    d: 'Raw weather becomes human thermal stress: wet-bulb globe temperature from a black-globe energy balance, and heat index for public messaging.',
  },
  {
    n: '03',
    t: 'Localise',
    d: 'Grid forecasts are downscaled by urban heat island intensity, then weighted by who lives there — housing, literacy, occupation, tree cover.',
  },
  {
    n: '04',
    t: 'Act',
    d: 'Ward-level risk scores drive a colour-coded map, work–rest guidance, and SMS or WhatsApp warnings that fire before the peak, not after.',
  },
]

/** Big serif figure + micro label. Renders an em dash rather than a fake zero
    when there is no data — a KPI that reads "0" during an outage is a lie. */
function Figure({ label, value, decimals = 0, suffix = '', hint, index, ready }) {
  const { reduced, t } = useMotionSafe()
  return (
    <motion.div
      className="px-6 py-7 first:pl-0"
      initial={{ opacity: 0, y: 22 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-60px' }}
      transition={reduced ? { duration: 0 } : t({ duration: 0.8, ease: EASE, delay: index * 0.07 })}
    >
      <div className="eyebrow">{label}</div>
      <div className="mt-3 flex items-baseline gap-1">
        {ready ? (
          <>
            <Odometer value={value} decimals={decimals} height={1.02} className="figure text-[clamp(2.4rem,5vw,3.6rem)]" />
            <span className="text-[16px] text-white/40">{suffix}</span>
          </>
        ) : (
          <span className="figure text-[clamp(2.4rem,5vw,3.6rem)] text-white/20">—</span>
        )}
      </div>
      <div className="mt-2 text-[11px] leading-snug text-white/30">{hint}</div>
    </motion.div>
  )
}

export default function Landing({ onEnter, onDemo }) {
  const { reduced } = useMotionSafe()
  const { scrollY } = useScroll()
  const heroY = useTransform(scrollY, [0, 600], [0, 90])
  const heroOpacity = useTransform(scrollY, [0, 420], [1, 0])

  const [epoch, setEpoch] = useState(0)
  const refreshAll = () => setEpoch((e) => e + 1)
  useRefreshShortcut(refreshAll)

  const ranking = useLive(() => fetchRanking(0), [epoch])
  const alerts = useLive(() => fetchAlerts(ALERT_THRESHOLD, 1, 0), [epoch])
  const zones = useLive(() => fetchZones(), [epoch])

  const data = ranking.data?.data || []
  const hasData = data.length > 0

  // Every figure below is derived from the live payload. When the API is
  // unreachable there is nothing to show, so the tiles render an em dash —
  // never a hard-coded stand-in.
  const wardCount = zones.data?.count ?? (hasData ? data.length : null)
  const leadDays = alerts.data?.data?.length
    ? Math.max(...alerts.data.data.map((a) => a.lead_days || 0))
    : null
  const peakWbgt = hasData ? Math.max(...data.map((d) => d.wbgt_peak_c || 0)) : null
  const alerted = hasData
    ? data.filter((d) => d.risk_band === 'Danger' || d.risk_band === 'Critical').length
    : null
  const exposed = hasData ? data.reduce((a, d) => a + (d.exposed_population || 0), 0) : null

  const kpis = [
    { label: 'Peak WBGT', value: peakWbgt, dec: 1, suffix: '°C', hint: 'full-sun, hottest ward' },
    { label: 'Wards on alert', value: alerted, dec: 0, suffix: '', hint: 'danger or critical band' },
    {
      label: 'Population exposed',
      value: exposed == null ? null : exposed / 1e6,
      dec: 2,
      suffix: 'M',
      hint: 'risk-weighted, peak day',
    },
    { label: 'Warning lead time', value: leadDays, dec: 0, suffix: ' days', hint: 'earliest actionable warning' },
  ]

  return (
    <div className="relative">
      <ScrollRail />

      {/* ---------------------------------------------------------- nav */}
      <motion.nav
        className="fixed left-0 right-0 top-0 z-40 backdrop-blur-md"
        style={{ background: 'rgba(7,8,13,.62)', borderBottom: '1px solid rgba(255,255,255,.07)' }}
        initial={{ y: -60, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ ...(reduced ? { duration: 0 } : spring.normal), delay: reduced ? 0 : 0.15 }}
      >
        <div className="mx-auto flex max-w-[1200px] items-center gap-4 px-6 py-3.5">
          <div className="flex items-center gap-2.5">
            <motion.div
              className="h-6 w-6 rounded-full"
              style={{ background: 'linear-gradient(135deg,#ff5f6d,#ffc371)' }}
              animate={reduced ? {} : { scale: [1, 1.12, 1] }}
              transition={{ duration: 2.6, repeat: Infinity, ease: 'easeInOut' }}
            />
            <span className="display text-[19px] tracking-tight">HeatShield</span>
          </div>
          <span className="hidden text-[10px] uppercase tracking-[0.2em] text-white/35 sm:block">
            {wardCount == null ? 'Kolkata · live data pending' : `Kolkata · ${wardCount} wards`}
          </span>
          <div className="flex-1" />
          <RefreshButton
            compact
            onRefresh={refreshAll}
            busy={ranking.refreshing}
            lastUpdated={ranking.lastUpdated}
            error={ranking.error}
          />
          {onDemo && (
            <button
              onClick={onDemo}
              className="rounded-full border border-amber-300/35 bg-amber-300/[.08] px-4 py-1.5 text-[12px] font-medium text-amber-200/90 transition hover:border-amber-300/60 hover:bg-amber-300/[.14]"
            >
              Heat Risk Demo
            </button>
          )}
          <button
            onClick={onEnter}
            className="rounded-full border border-white/15 bg-white/[.05] px-4 py-1.5 text-[12px] font-medium transition hover:border-white/30 hover:bg-white/[.1]"
          >
            Open dashboard
          </button>
        </div>
      </motion.nav>

      {/* ---------------------------------------------------------- hero */}
      <motion.header
        className="relative mx-auto max-w-[1200px] px-6 pb-20 pt-44"
        style={{ y: heroY, opacity: heroOpacity }}
      >
        <motion.div
          className="eyebrow mb-8 flex items-center gap-2.5"
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.7, ease: EASE, delay: 0.2 }}
        >
          <motion.span
            className="inline-block h-1.5 w-1.5 rounded-full bg-red-500"
            animate={reduced ? {} : { opacity: [1, 0.25, 1] }}
            transition={{ duration: 1.8, repeat: Infinity }}
          />
          Extreme heat early warning · impact-based
        </motion.div>

        <h1 className="display max-w-[15ch] text-[clamp(3.2rem,8.2vw,7.2rem)]">
          <WordReveal text="We forecast the" delay={0.25} />
          <br />
          <WordReveal text="body, not the" delay={0.4} />
          <br />
          <WordReveal
            as="em"
            text="weather."
            delay={0.55}
            className="text-[clamp(3.2rem,8.2vw,7.2rem)]"
            wordClassName="bg-gradient-to-r from-orange-300 via-orange-500 to-red-500 bg-clip-text text-transparent"
          />
        </h1>

        <motion.p
          className="mt-10 max-w-[52ch] text-[15.5px] leading-relaxed text-white/55"
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, ease: EASE, delay: 0.85 }}
        >
          HeatShield converts open weather forecasts into ward-level human thermal stress, then into
          the only number that matters — <span className="font-medium text-white/80">who is at risk, and when to act.</span>
        </motion.p>

        <motion.div
          className="mt-10 flex flex-wrap items-center gap-4"
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, ease: EASE, delay: 1 }}
        >
          <motion.button
            onClick={onEnter}
            className="group relative overflow-hidden rounded-full bg-white px-7 py-3.5 text-[13px] font-semibold text-black"
            whileHover={reduced ? undefined : { scale: 1.03 }}
            whileTap={reduced ? undefined : { scale: 0.97 }}
            transition={spring.snappy}
          >
            <span className="relative z-10">View live risk map</span>
            <motion.span
              className="absolute inset-0 z-0"
              style={{ background: 'linear-gradient(90deg,#ffc371,#ff5f6d)' }}
              initial={{ x: '-100%' }}
              whileHover={{ x: 0 }}
              transition={reduced ? { duration: 0 } : { duration: 0.45, ease: EASE }}
            />
          </motion.button>
          {onDemo && (
            <motion.button
              onClick={onDemo}
              className="rounded-full border border-amber-300/40 bg-amber-300/[.07] px-7 py-3.5 text-[13px] font-semibold text-amber-100/90 transition hover:border-amber-300/70 hover:bg-amber-300/[.12]"
              whileHover={reduced ? undefined : { scale: 1.03 }}
              whileTap={reduced ? undefined : { scale: 0.97 }}
              transition={spring.snappy}
            >
              Open the Heat Risk Demo
              <span className="ml-2 text-[11px] font-normal text-amber-100/50">synthetic scenarios · offline · no sign-up</span>
            </motion.button>
          )}
          <span className="text-[11.5px] text-white/35">
            No sign-up · open data · {hasData ? `${data.length} wards scored` : 'keyless forecast'}
          </span>
        </motion.div>
      </motion.header>

      {/* ---------------------------------------------------------- kpis */}
      <section className="mx-auto max-w-[1200px] px-6">
        {ranking.error && !hasData && (
          <p className="mb-4 text-[11.5px] text-red-300/70">
            Live API unreachable — the figures below stay blank rather than showing sample data.
          </p>
        )}
        <div className="grid grid-cols-2 border-t border-white/[.1] md:grid-cols-4 md:divide-x md:divide-white/[.08]">
          {kpis.map((k, i) => (
            <Figure
              key={k.label}
              index={i}
              label={k.label}
              value={k.value}
              decimals={k.dec}
              suffix={k.suffix}
              hint={k.hint}
              ready={k.value != null}
            />
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------- steps */}
      <section className="mx-auto mt-32 max-w-[1200px] px-6">
        <motion.h2
          className="display max-w-[20ch] text-[clamp(2.2rem,4.8vw,3.8rem)]"
          initial={{ opacity: 0, y: 26 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={reduced ? { duration: 0 } : { duration: 0.9, ease: EASE }}
        >
          From satellite grid to <em>street-level</em> warning
        </motion.h2>

        <div className="mt-16 grid gap-x-10 gap-y-12 md:grid-cols-2">
          {STEPS.map((s, i) => (
            <motion.div
              key={s.n}
              className="group relative border-t border-white/[.1] pt-6"
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={reduced ? { duration: 0 } : { duration: 0.85, ease: EASE, delay: i * 0.09 }}
            >
              <div className="tnum text-[11px] tracking-[0.2em] text-orange-400/70">{s.n}</div>
              <h3 className="display mt-4 text-[26px] leading-none">{s.t}</h3>
              <p className="mt-3 max-w-[44ch] text-[13px] leading-relaxed text-white/45">{s.d}</p>
              <motion.div
                className="absolute left-0 top-0 h-px w-full origin-left"
                style={{ background: 'linear-gradient(90deg,#f97316,transparent)' }}
                initial={{ scaleX: 0 }}
                whileInView={{ scaleX: 1 }}
                viewport={{ once: true }}
                transition={reduced ? { duration: 0 } : { duration: 1, ease: EASE, delay: 0.3 + i * 0.09 }}
              />
            </motion.div>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------- ticker */}
      <section className="mt-32">
        <Ticker
          note={
            ranking.error && !hasData
              ? 'API unreachable — no live ward feed. Start the API and press R to retry.'
              : 'waiting for the live ward feed…'
          }
          items={
            hasData
              ? data.slice(0, 7).map(
                  (d) => `${d.ward_name.toUpperCase()} · risk ${Math.round(d.risk_score)} · ${d.risk_band} · WBGT ${d.wbgt_peak_c?.toFixed(1)}°`
                )
              : []
          }
        />
      </section>

      {/* ---------------------------------------------------------- cta */}
      <section className="mx-auto mt-32 max-w-[1200px] px-6 pb-36">
        <motion.div
          className="panel overflow-hidden px-8 py-16 text-center"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-70px' }}
          transition={reduced ? { duration: 0 } : { duration: 0.9, ease: EASE }}
        >
          <h2 className="display text-[clamp(2rem,4vw,3.2rem)]">
            A heatwave is a <em>forecastable</em> disaster
          </h2>
          <p className="mx-auto mt-5 max-w-[52ch] text-[13.5px] leading-relaxed text-white/50">
            Every ward in this city shares one weather grid cell. What separates a safe ward from a
            deadly one is exposure — and exposure is something we can map, score and warn about days
            before the peak arrives.
          </p>
          <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
            <motion.button
              onClick={onEnter}
              className="rounded-full border border-white/20 bg-white/[.06] px-8 py-3.5 text-[13px] font-medium transition hover:border-white/40 hover:bg-white/[.12]"
              whileHover={reduced ? undefined : { scale: 1.03 }}
              whileTap={reduced ? undefined : { scale: 0.97 }}
              transition={spring.snappy}
            >
              Open the operations dashboard
            </motion.button>
            {onDemo && (
              <motion.button
                onClick={onDemo}
                className="rounded-full border border-amber-300/40 bg-amber-300/[.07] px-8 py-3.5 text-[13px] font-medium text-amber-100/90 transition hover:border-amber-300/70 hover:bg-amber-300/[.12]"
                whileHover={reduced ? undefined : { scale: 1.03 }}
                whileTap={reduced ? undefined : { scale: 0.97 }}
                transition={spring.snappy}
              >
                Try the Heat Risk Demo (synthetic, offline)
              </motion.button>
            )}
          </div>
        </motion.div>
      </section>

      <footer className="border-t border-white/10 py-9 text-center text-[11px] text-white/25">
        HeatShield · open weather data · built for impact-based heat warning
      </footer>
    </div>
  )
}
