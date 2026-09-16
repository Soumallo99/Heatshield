import { AnimatePresence, motion } from 'framer-motion'
import { bandColour, EASE, spring } from '../motion'

const DAYNAME = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function fmtDate(d) {
  const dt = typeof d === 'string' ? new Date(d + 'T00:00:00') : d
  if (Number.isNaN(dt.getTime())) return String(d)
  return `${DAYNAME[dt.getDay()]} ${dt.getDate()} ${dt.toLocaleString('en-IN', { month: 'short' })}`
}

/**
 * Alert planning panel.
 *
 * The whole point of the system is lead time, so lead time is the headline number.
 * Each row animates in on a stagger, and the lead badge pulses — it is the one
 * figure that says "there is still time to act".
 */
export default function AlertsPanel({ alerts, scenario, onScenario }) {
  const rows = alerts?.data || []
  const total = alerts?.total_events ?? 0
  const pending = alerts?.pending_after_dedupe ?? 0
  const lead = alerts?.min_lead_days ?? 1

  const soonest = rows.reduce((a, r) => (a == null || r.lead_days < a ? r.lead_days : a), null)

  return (
    <motion.section
      className="panel mt-5 p-6"
      initial={{ opacity: 0, y: 22 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.8, ease: EASE, delay: 0.14 }}
    >
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-white/[.07] pb-3">
        <div>
          <div className="eyebrow">sms / whatsapp · dry-run</div>
          <h2 className="display mt-1.5 text-[22px] leading-none">Early warning queue</h2>
          <p className="mt-2 text-[11px] text-white/35">
            alerts raised only when there is at least <span className="text-white/60">{lead} day</span> of lead time
          </p>
        </div>

        <div className="flex items-center gap-3">
          {total > 0 && (
            <motion.div
              className="flex items-baseline gap-1.5 rounded-full border border-orange-500/40 bg-orange-500/10 px-3 py-1"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={spring.snappy}
            >
              <span className="tnum text-[15px] font-bold text-orange-300">{total}</span>
              <span className="text-[10.5px] text-orange-200/70">wards queued</span>
            </motion.div>
          )}
          {total > 0 && (
            <span className="text-[10.5px] text-white/30">
              {pending === total
                ? 'all unsent · 12 h de-duplication'
                : `${pending} of ${total} unsent · rest sent <12 h ago`}
            </span>
          )}
        </div>
      </div>

      {alerts?.active_now > 0 && (
        <motion.div
          className="mb-3 rounded-xl border border-red-500/40 bg-red-500/10 p-3"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          transition={{ duration: 0.5, ease: EASE }}
        >
          <span className="text-[11.5px] font-semibold text-red-300">
            {alerts.active_now} ward(s) are already inside the event today
          </span>
          <span className="ml-1.5 text-[11px] text-white/55">
            — no lead time remains, so these are nowcasts, not warnings. Message shifts from
            "prepare" to "shelter now": {alerts.active_wards?.slice(0, 6).join(', ')}
            {alerts.active_now > 6 ? '…' : ''}
          </span>
        </motion.div>
      )}

      {rows.length === 0 ? (
        <motion.div
          className="rounded-xl border border-white/10 bg-white/[.02] p-6 text-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5 }}
        >
          <p className="text-[12.5px] text-white/45">
            No ward crosses the alert threshold with {lead}+ day of lead time.
          </p>
          <p className="mt-1.5 text-[11px] text-white/28">
            Every crossing inside the window is a nowcast, not a warning — there is nothing left to act on.
            Try a higher scenario to see the queue fill.
          </p>
        </motion.div>
      ) : (
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          <AnimatePresence mode="popLayout">
            {rows.slice(0, 9).map((r, i) => {
              const c = bandColour[r.risk_band] || '#f97316'
              return (
                <motion.div
                  key={`${r.ward_id}-${r.event_date}`}
                  layout
                  className="relative overflow-hidden rounded-xl border p-3"
                  style={{ borderColor: `${c}44`, background: `${c}0f` }}
                  initial={{ opacity: 0, y: 16, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ duration: 0.55, ease: EASE, delay: i * 0.045 }}
                  whileHover={{ y: -2, backgroundColor: `${c}1a` }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-[12.5px] font-medium text-white/85">{r.ward_name}</div>
                      <div className="mt-0.5 text-[10.5px] text-white/40">
                        {fmtDate(r.event_date)} · WBGT {r.wbgt_peak_c?.toFixed(1)}°
                      </div>
                    </div>

                    {/* lead time — the headline */}
                    <motion.div
                      className="shrink-0 rounded-lg px-2 py-1 text-center"
                      style={{ background: `${c}22`, border: `1px solid ${c}55` }}
                      animate={{ boxShadow: [`0 0 0 0 ${c}00`, `0 0 0 5px ${c}18`, `0 0 0 0 ${c}00`] }}
                      transition={{ duration: 2.6, repeat: Infinity, ease: 'easeInOut' }}
                    >
                      <div className="tnum text-[15px] font-bold leading-none" style={{ color: c }}>
                        {r.lead_days}
                      </div>
                      <div className="text-[8.5px] uppercase tracking-wider text-white/40">day lead</div>
                    </motion.div>
                  </div>

                  <div className="mt-2.5 flex items-center gap-2">
                    <span
                      className="rounded px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-wider"
                      style={{ background: c, color: '#07080d' }}
                    >
                      {r.risk_band}
                    </span>
                    <span className="tnum text-[10.5px] text-white/40">
                      risk {Math.round(r.risk_score)} · {r.exposed_population?.toLocaleString('en-IN')} exposed
                    </span>
                  </div>

                  {/* lead-time bar: how much warning remains, visually */}
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
                    <motion.div
                      className="h-full rounded-full"
                      style={{ background: c }}
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.min(100, (r.lead_days / 5) * 100)}%` }}
                      transition={{ duration: 0.9, ease: EASE, delay: 0.2 + i * 0.045 }}
                    />
                  </div>
                </motion.div>
              )
            })}
          </AnimatePresence>
        </div>
      )}

      {rows.length > 9 && (
        <p className="mt-3 text-[10.5px] text-white/30">
          + {rows.length - 9} more wards queued. Dry-run is the default — nothing is sent until
          credentials are configured and dispatch is invoked.
        </p>
      )}
    </motion.section>
  )
}
