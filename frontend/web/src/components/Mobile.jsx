import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import Odometer from './Odometer'
import Gauge from './Gauge'
import HourlyChart from './HourlyChart'
import { bandColour, bandText, EASE, spring } from '../motion'
import { fetchHourly, fetchRanking, fetchWardRisk } from '../api'

const WORK_REST = {
  Normal: 'No restriction. Maintain hydration.',
  Caution: '45 min work : 15 min rest each hour',
  Danger: '30 min work : 30 min rest each hour',
  Critical: 'No work 12:00–15:00. Shaded breaks hourly.',
  Extreme: 'Suspend all outdoor activity.',
}

/**
 * Citizen / mobile view — what the SMS link opens.
 *
 * Design constraint: one number, one colour, one instruction. Everything else is
 * supporting detail. Presented in a device frame so it reads as a phone screen
 * on desktop without needing a real device.
 */
export default function Mobile({ onExit }) {
  const [rows, setRows] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [ward, setWard] = useState(null)
  const [hourly, setHourly] = useState([])
  const [installable, setInstallable] = useState(false)
  const [prompt, setPrompt] = useState(null)

  useEffect(() => {
    fetchRanking().then((d) => {
      const r = d?.data || []
      setRows(r)
      if (r.length) setSelectedId(r[0].ward_id)
    })
    const onBeforeInstall = (e) => {
      e.preventDefault()
      setPrompt(e)
      setInstallable(true)
    }
    window.addEventListener('beforeinstallprompt', onBeforeInstall)
    return () => window.removeEventListener('beforeinstallprompt', onBeforeInstall)
  }, [])

  const selected = rows.find((r) => r.ward_id === selectedId) || rows[0]

  useEffect(() => {
    if (!selected) return
    fetchWardRisk(selected.ward_id).then(setWard)
    fetchHourly(selected.ward_id).then((d) => setHourly(d?.data || []))
  }, [selected])

  const colour = bandColour[selected?.risk_band] || '#22c55e'

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-10">
      <div className="mb-7 flex items-center justify-between">
        <div>
          <h1 className="display text-[26px]">Citizen view</h1>
          <p className="mt-1 text-[12px] text-white/40">The screen an alert link opens. Installable, works offline.</p>
        </div>
        <div className="flex items-center gap-3">
          {installable && (
            <motion.button
              className="rounded-full border border-white/20 bg-white/[.06] px-4 py-2 text-[12px]"
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.97 }}
              transition={spring.snappy}
              onClick={async () => {
                prompt?.prompt()
                await prompt?.userChoice
                setInstallable(false)
              }}
            >
              Install app
            </motion.button>
          )}
          <button onClick={onExit} className="text-[12px] text-white/40 transition hover:text-white/80">
            ← Back to dashboard
          </button>
        </div>
      </div>

      <div className="flex flex-col items-center gap-8 lg:flex-row lg:items-start lg:gap-14">
        {/* ------------------------------------------------- device frame */}
        <motion.div
          className="relative w-[320px] shrink-0 rounded-[42px] border border-white/12 p-3"
          style={{ background: 'linear-gradient(165deg,rgba(255,255,255,.07),rgba(255,255,255,.02))', boxShadow: '0 40px 90px -20px rgba(0,0,0,.85)' }}
          initial={{ opacity: 0, y: 40, rotateX: 8 }}
          animate={{ opacity: 1, y: 0, rotateX: 0 }}
          transition={{ duration: 1, ease: EASE }}
        >
          <div className="relative overflow-hidden rounded-[34px] bg-ink-950" style={{ height: 620 }}>
            {/* status bar */}
            <div className="flex items-center justify-between px-5 pb-1 pt-3 text-[10px] text-white/40">
              <span className="tnum">09:41</span>
              <span className="h-4 w-16 rounded-full bg-white/10" />
              <span className="flex gap-1">
                <i className="h-1.5 w-1.5 rounded-full bg-white/30" />
                <i className="h-1.5 w-1.5 rounded-full bg-white/30" />
              </span>
            </div>

            <div className="px-5 pt-3">
              <div className="eyebrow">your ward</div>
              <div className="mt-0.5 text-[17px] font-medium">{selected?.ward_name || '—'}</div>
            </div>

            {/* risk hero */}
            <motion.div
              className="mx-4 mt-4 overflow-hidden rounded-3xl p-5"
              animate={{ backgroundColor: `${colour}1f`, borderColor: `${colour}55` }}
              transition={{ duration: 0.5 }}
              style={{ border: '1px solid transparent' }}
            >
              <div className="flex items-end justify-between">
                <div>
                  <div className="eyebrow" style={{ color: colour }}>
                    heat risk
                  </div>
                  <div className="mt-1 flex items-baseline">
                    <Odometer value={selected?.risk_score || 0} decimals={0} height={1.05} className="text-[54px] font-bold" />
                    <span className="ml-1 text-[14px] text-white/35">/100</span>
                  </div>
                </div>
                <motion.div
                  className="rounded-full px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider"
                  animate={{ backgroundColor: colour, color: '#07080d' }}
                  transition={{ duration: 0.4 }}
                >
                  {selected?.risk_band}
                </motion.div>
              </div>
              <p className="mt-3 text-[11.5px] leading-relaxed text-white/60">
                {bandText[selected?.risk_band]}
              </p>
            </motion.div>

            {/* guidance */}
            <motion.div
              className="mx-4 mt-3 rounded-2xl border border-white/10 bg-white/[.03] p-4"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, ease: EASE, delay: 0.25 }}
            >
              <div className="eyebrow">work &amp; rest</div>
              <div className="mt-1.5 text-[13px] font-medium">{WORK_REST[selected?.risk_band] || '—'}</div>
            </motion.div>

            {/* gauge */}
            <div className="mt-1 px-2">
              <Gauge value={selected?.risk_score || 0} band={selected?.risk_band} />
            </div>

            {/* drivers */}
            <div className="grid grid-cols-3 gap-2 px-4">
              {[
                ['WBGT', ward?.drivers?.wbgt_peak_c?.toFixed(1) ?? '—', '°C'],
                ['UHI', `+${ward?.drivers?.uhi_delta_c?.toFixed(1) ?? '—'}`, '°C'],
                ['Vuln', ward?.drivers?.vulnerability?.toFixed(0) ?? '—', ''],
              ].map(([k, v, u], i) => (
                <motion.div
                  key={k}
                  className="rounded-xl border border-white/10 bg-white/[.03] px-2 py-2.5 text-center"
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.55, ease: EASE, delay: 0.32 + i * 0.06 }}
                >
                  <div className="eyebrow" style={{ fontSize: 9 }}>{k}</div>
                  <div className="tnum mt-1 text-[15px] font-semibold">
                    {v}
                    <span className="ml-0.5 text-[9px] text-white/35">{u}</span>
                  </div>
                </motion.div>
              ))}
            </div>

            <div className="mt-3 px-3">
              <HourlyChart data={hourly} metric="wbgt_adj_c" unit="next 24 h" />
            </div>
          </div>
        </motion.div>

        {/* ------------------------------------------------- ward switcher */}
        <div className="w-full max-w-[520px]">
          <div className="eyebrow mb-3">switch ward</div>
          <div className="grid grid-cols-2 gap-2">
            {rows.map((w, i) => {
              const c = bandColour[w.risk_band] || '#22c55e'
              const isSel = w.ward_id === selected?.ward_id
              return (
                <motion.button
                  key={w.ward_id}
                  onClick={() => setSelectedId(w.ward_id)}
                  className="flex items-center justify-between rounded-xl border px-3.5 py-2.5 text-left"
                  style={{
                    borderColor: isSel ? c : 'rgba(255,255,255,.09)',
                    background: isSel ? `${c}16` : 'rgba(255,255,255,.03)',
                  }}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, ease: EASE, delay: i * 0.03 }}
                  whileHover={{ y: -2 }}
                  whileTap={{ scale: 0.98 }}
                >
                  <span className="truncate text-[12px] text-white/75">{w.ward_name}</span>
                  <span className="tnum ml-2 text-[14px] font-bold" style={{ color: c }}>
                    {Math.round(w.risk_score)}
                  </span>
                </motion.button>
              )
            })}
          </div>

          <div className="panel mt-5 p-5">
            <div className="eyebrow">how this reaches people</div>
            <p className="mt-2.5 text-[12.5px] leading-relaxed text-white/50">
              When a ward crosses <span className="text-white/80">Critical</span>, the alert service
              dispatches an SMS or WhatsApp message containing a deep link to this screen for that
              ward. The service worker caches the last known risk, so the page still opens with no
              signal — which is exactly when a heat emergency is hardest to communicate.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
