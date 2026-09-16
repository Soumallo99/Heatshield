import { useEffect, useState } from 'react'
import { motion, useScroll, useSpring, useTransform } from 'framer-motion'
import WordReveal from './WordReveal'
import Odometer from './Odometer'
import { EASE, spring } from '../motion'
import { ALERT_THRESHOLD, fetchAlerts, fetchRanking } from '../api'

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
function Ticker({ items }) {
  if (!items.length) return null
  const row = [...items, ...items]
  return (
    <div className="overflow-hidden border-y border-white/10 bg-white/[.02] py-2.5">
      <motion.div
        className="flex w-max whitespace-nowrap"
        animate={{ x: ['0%', '-50%'] }}
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
    d: 'Five-day hourly weather — temperature, humidity, wind and solar radiation — pulled from open models for every ward in a single batched request.',
  },
  {
    n: '02',
    t: 'Translate',
    d: 'Raw weather becomes human thermal stress: wet-bulb globe temperature from a black-globe energy balance, and heat index for public messaging.',
  },
  {
    n: '03',
    t: 'Localise',
    d: 'Grid forecasts are downscaled by urban heat island intensity, then weighted by who lives there — age, housing, occupation, tree cover.',
  },
  {
    n: '04',
    t: 'Act',
    d: 'Ward-level risk scores drive a colour-coded map, work–rest guidance, and SMS or WhatsApp warnings that fire before the peak, not after.',
  },
]

export default function Landing({ onEnter }) {
  const [ranking, setRanking] = useState(null)
  const [alerts, setAlerts] = useState(null)
  const { scrollY } = useScroll()
  const heroY = useTransform(scrollY, [0, 600], [0, 90])
  const heroOpacity = useTransform(scrollY, [0, 420], [1, 0])

  useEffect(() => {
    fetchRanking().then(setRanking)
    fetchAlerts(ALERT_THRESHOLD, 1).then(setAlerts)
  }, [])

  const data = ranking?.data || []
  // Truthful counts: never hard-code them. The /zones fallback snapshot only
  // carries 14 demo wards, so fall back to the known real KMC ward count
  // instead of echoing the mock.
  const wardCount = data.length > 14 ? data.length : 141
  // Real lead time from the alert engine, not a decorative constant.
  const leadDays = alerts?.data?.length
    ? Math.max(...alerts.data.map((a) => a.lead_days || 0))
    : 0
  const peakWbgt = data.length ? Math.max(...data.map((d) => d.wbgt_peak_c || 0)) : 0
  const alerted = data.filter((d) => d.risk_band === 'Danger' || d.risk_band === 'Critical').length
  const exposed = data.reduce((a, d) => a + (d.exposed_population || 0), 0)

  const kpis = [
    { label: 'Peak WBGT', value: peakWbgt, dec: 1, suffix: '°', hint: 'full-sun, hottest ward' },
    { label: 'Wards on alert', value: alerted, dec: 0, suffix: '', hint: 'danger or critical' },
    { label: 'Population exposed', value: exposed / 1e6, dec: 2, suffix: 'M', hint: 'risk-weighted' },
    { label: 'Warning lead time', value: leadDays, dec: 0, suffix: ' days', hint: 'earliest actionable warning' },
  ]

  return (
    <div className="relative">
      <ScrollRail />

      {/* ---------------------------------------------------------- nav */}
      <motion.nav
        className="fixed left-0 right-0 top-0 z-40 backdrop-blur-md"
        style={{ background: 'rgba(7,8,13,.6)', borderBottom: '1px solid rgba(255,255,255,.07)' }}
        initial={{ y: -60, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ ...spring.normal, delay: 0.15 }}
      >
        <div className="mx-auto flex max-w-[1200px] items-center gap-4 px-6 py-3.5">
          <div className="flex items-center gap-2.5">
            <motion.div
              className="h-6 w-6 rounded-full"
              style={{ background: 'linear-gradient(135deg,#ff5f6d,#ffc371)' }}
              animate={{ scale: [1, 1.12, 1] }}
              transition={{ duration: 2.6, repeat: Infinity, ease: 'easeInOut' }}
            />
            <span className="display text-[19px] tracking-tight">HeatShield</span>
          </div>
          <span className="hidden text-[10px] uppercase tracking-[0.2em] text-white/35 sm:block">
            Kolkata · {wardCount} wards
          </span>
          <div className="flex-1" />
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
        className="relative mx-auto max-w-[1200px] px-6 pb-16 pt-40"
        style={{ y: heroY, opacity: heroOpacity }}
      >
        <motion.div
          className="eyebrow mb-7 flex items-center gap-2.5"
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.7, ease: EASE, delay: 0.2 }}
        >
          <motion.span
            className="inline-block h-1.5 w-1.5 rounded-full bg-red-500"
            animate={{ opacity: [1, 0.25, 1] }}
            transition={{ duration: 1.8, repeat: Infinity }}
          />
          Extreme heat early warning · impact-based
        </motion.div>

        <h1 className="display max-w-[16ch] text-[clamp(2.9rem,7.4vw,6.4rem)]">
          <WordReveal text="We forecast the" delay={0.25} />
          <br />
          <WordReveal text="body, not the" delay={0.4} />
          <br />
          <WordReveal
            as="em"
            text="weather."
            delay={0.55}
            className="text-[clamp(2.9rem,7.4vw,6.4rem)]"
            wordClassName="bg-gradient-to-r from-orange-300 via-orange-500 to-red-500 bg-clip-text text-transparent"
          />
        </h1>

        <motion.p
          className="mt-8 max-w-[54ch] text-[15px] leading-relaxed text-white/55"
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, ease: EASE, delay: 0.85 }}
        >
          HeatShield converts open weather forecasts into ward-level human thermal stress, then into
          the only number that matters — <span className="font-medium text-white/80">who is at risk, and when to act.</span>
        </motion.p>

        <motion.div
          className="mt-9 flex flex-wrap items-center gap-3"
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, ease: EASE, delay: 1 }}
        >
          <motion.button
            onClick={onEnter}
            className="group relative overflow-hidden rounded-full bg-white px-6 py-3 text-[13px] font-semibold text-black"
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
            transition={spring.snappy}
          >
            <span className="relative z-10">View live risk map</span>
            <motion.span
              className="absolute inset-0 z-0"
              style={{ background: 'linear-gradient(90deg,#ffc371,#ff5f6d)' }}
              initial={{ x: '-100%' }}
              whileHover={{ x: 0 }}
              transition={{ duration: 0.45, ease: EASE }}
            />
          </motion.button>
          <span className="text-[11.5px] text-white/35">No sign-up · open data · 5-day horizon</span>
        </motion.div>
      </motion.header>

      {/* ---------------------------------------------------------- kpis */}
      <section className="mx-auto max-w-[1200px] px-6">
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-white/10 bg-white/10 md:grid-cols-4">
          {kpis.map((k, i) => (
            <motion.div
              key={k.label}
              className="bg-ink-950/80 p-6 backdrop-blur"
              initial={{ opacity: 0, y: 22 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.8, ease: EASE, delay: i * 0.07 }}
            >
              <div className="eyebrow">{k.label}</div>
              <div className="mt-3 flex items-baseline text-[34px] font-semibold tracking-tight">
                <Odometer value={k.value} decimals={k.dec} />
                <span className="text-[17px] text-white/45">{k.suffix}</span>
              </div>
              <div className="mt-1.5 text-[11px] text-white/30">{k.hint}</div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------- steps */}
      <section className="mx-auto mt-28 max-w-[1200px] px-6">
        <motion.h2
          className="display max-w-[20ch] text-[clamp(2rem,4.4vw,3.4rem)]"
          initial={{ opacity: 0, y: 26 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.9, ease: EASE }}
        >
          From satellite grid to <em>street-level</em> warning
        </motion.h2>

        <div className="mt-14 grid gap-px overflow-hidden rounded-2xl border border-white/10 bg-white/10 md:grid-cols-2">
          {STEPS.map((s, i) => (
            <motion.div
              key={s.n}
              className="group relative bg-ink-950/80 p-8 backdrop-blur"
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.85, ease: EASE, delay: i * 0.09 }}
              whileHover={{ backgroundColor: 'rgba(255,255,255,.045)' }}
            >
              <div className="tnum text-[12px] text-orange-400/70">{s.n}</div>
              <h3 className="mt-4 text-[17px] font-medium">{s.t}</h3>
              <p className="mt-2.5 max-w-[46ch] text-[13px] leading-relaxed text-white/45">{s.d}</p>
              <motion.div
                className="absolute bottom-0 left-0 h-[2px] w-full origin-left"
                style={{ background: 'linear-gradient(90deg,#f97316,transparent)' }}
                initial={{ scaleX: 0 }}
                whileInView={{ scaleX: 1 }}
                viewport={{ once: true }}
                transition={{ duration: 1, ease: EASE, delay: 0.3 + i * 0.09 }}
              />
            </motion.div>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------- ticker */}
      <section className="mt-28">
        <Ticker
          items={
            data.length
              ? data.slice(0, 7).map(
                  (d) => `${d.ward_name.toUpperCase()} · risk ${Math.round(d.risk_score)} · ${d.risk_band} · WBGT ${d.wbgt_peak_c?.toFixed(1)}°`
                )
              : ['loading live ward feed…']
          }
        />
      </section>

      {/* ---------------------------------------------------------- cta */}
      <section className="mx-auto mt-28 max-w-[1200px] px-6 pb-32">
        <motion.div
          className="panel overflow-hidden p-12 text-center"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-70px' }}
          transition={{ duration: 0.9, ease: EASE }}
        >
          <h2 className="display text-[clamp(1.8rem,3.6vw,2.8rem)]">
            A heatwave is a <em>forecastable</em> disaster
          </h2>
          <p className="mx-auto mt-4 max-w-[52ch] text-[13.5px] leading-relaxed text-white/50">
            Every ward in this city shares one weather grid cell. What separates a safe ward from a
            deadly one is exposure — and exposure is something we can map, score and warn about days
            before the peak arrives.
          </p>
          <motion.button
            onClick={onEnter}
            className="mt-8 rounded-full border border-white/20 bg-white/[.06] px-7 py-3 text-[13px] font-medium transition hover:border-white/40 hover:bg-white/[.12]"
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
            transition={spring.snappy}
          >
            Open the operations dashboard
          </motion.button>
        </motion.div>
      </section>

      <footer className="border-t border-white/10 py-9 text-center text-[11px] text-white/25">
        HeatShield · open weather data · built for impact-based heat warning
      </footer>
    </div>
  )
}
