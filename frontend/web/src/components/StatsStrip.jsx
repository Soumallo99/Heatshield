import { motion } from 'framer-motion'
import Odometer from './Odometer'
import { EASE, useMotionSafe } from '../motion'

/**
 * Summary strip — the seven numbers that describe the whole run at a glance.
 *
 * Deliberately numeric rather than decorative: every tile is a real output of
 * the model (ward count, band split, queue size, lead time), so the panel is
 * also the fastest way to sanity-check that a scenario change took effect.
 *
 * `raw` is used for values that aren't counts (a date, for instance) — the
 * odometer can only roll digits, so those render as plain text instead.
 */
function Stat({ label, value, hint, raw, decimals = 0, suffix = '', accent, index }) {
  const { reduced, t } = useMotionSafe()

  return (
    <motion.div
      className="relative border-t border-white/[.1] px-1 pt-3"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={t({ duration: 0.6, ease: EASE, delay: index * 0.045 })}
      whileHover={reduced ? undefined : { y: -2 }}
    >
      <div
        className="truncate text-[10px] uppercase tracking-[0.11em] text-white/59"
        title={label}
      >
        {label}
      </div>

      <div className="mt-1.5 flex items-baseline gap-1">
        {raw != null ? (
          <span className="tnum text-[16px] font-semibold" style={{ color: accent }}>
            {raw}
          </span>
        ) : (
          <>
            <Odometer
              value={value}
              decimals={decimals}
              height={1.15}
              className="text-[23px] font-semibold"
            />
            {suffix && (
              <span className="text-[10.5px] text-white/59">{suffix}</span>
            )}
          </>
        )}
      </div>

      <div className="mt-0.5 truncate text-[10px] text-white/56" title={hint}>
        {hint}
      </div>
    </motion.div>
  )
}

/**
 * @param wards       ranking rows for the current scenario
 * @param mapDate     the day being displayed
 * @param alerts      /alerts/plan payload (may be null while loading)
 * @param threshold   risk score an alert fires at
 */
export default function StatsStrip({ wards = [], bandCounts = {}, mapDate, alerts, threshold }) {
  const warned = alerts?.total_events ?? 0
  const activeNow = alerts?.active_now ?? 0
  const leadTimes = (alerts?.data || []).map((a) => a.lead_days).filter((n) => n != null)
  // Lead time is only meaningful if something is actually queued — otherwise
  // "0 days" reads as a broken forecast rather than an empty queue.
  const lead = leadTimes.length ? Math.max(...leadTimes) : null

  const stats = [
    { label: 'Wards modelled', value: wards.length, hint: 'real KMC wards' },
    { label: 'Map date', raw: mapDate || '—', hint: 'peak-risk day' },
    { label: 'Caution', value: bandCounts.Caution || 0, hint: 'risk 25–50', accent: '#eab308' },
    { label: 'Danger', value: bandCounts.Danger || 0, hint: 'risk 50–75', accent: '#f97316' },
    { label: 'Wards warned', value: warned, hint: `threshold ${threshold}`, accent: '#fdba74' },
    {
      label: 'Lead time',
      raw: lead == null ? '—' : `${lead} days`,
      hint: 'earliest warning',
      accent: lead == null ? undefined : '#fdba74',
    },
    {
      label: 'Active now',
      value: activeNow,
      hint: 'nowcasts, not warnings',
      accent: activeNow > 0 ? '#fca5a5' : undefined,
    },
  ]

  return (
    <motion.section
      aria-label="Run summary"
      className="mt-6 grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-4 lg:grid-cols-7"
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.8, ease: EASE, delay: 0.1 }}
    >
      {stats.map((s, i) => (
        <Stat key={s.label} index={i} {...s} />
      ))}
    </motion.section>
  )
}
