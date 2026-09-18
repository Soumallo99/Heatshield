import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { EASE, spring, useMotionSafe } from '../motion'
import { formatAge, formatClock } from '../live'

/**
 * The "is this real, and how fresh is it?" affordance.
 *
 * Three honest states, never a fourth:
 *   live      — last fetch succeeded (dot breathes, timestamp ticks)
 *   stale     — last fetch failed, older data still on screen
 *   down      — no data at all; the screen says so and offers a retry
 *
 * Everything animates transform/opacity only.
 */

const DOT = {
  live: '#22d3ee',
  stale: '#eab308',
  down: '#ef4444',
}

function RefreshIcon({ spinning, reduced }) {
  return (
    <motion.svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      animate={reduced || !spinning ? { rotate: 0 } : { rotate: 360 }}
      transition={
        reduced || !spinning
          ? { duration: 0 }
          : { duration: 0.9, repeat: Infinity, ease: 'linear' }
      }
    >
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 3v6h-6" />
    </motion.svg>
  )
}

/**
 * @param onRefresh  () => void
 * @param busy       refetch in flight
 * @param lastUpdated Date | null
 * @param error      Error | null
 * @param compact    tighter variant for the mobile/citizen view
 */
export function RefreshButton({ onRefresh, busy = false, lastUpdated = null, error = null, compact = false }) {
  const { reduced } = useMotionSafe()
  const [tick, setTick] = useState(0)

  // Re-render once a second so "12 s ago" stays true without a store.
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  const state = error ? (lastUpdated ? 'stale' : 'down') : 'live'
  const colour = DOT[state]

  return (
    <div className="flex items-center gap-2.5">
      <div className="hidden items-center gap-2 sm:flex">
        <motion.span
          className="block h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ background: colour, boxShadow: `0 0 8px ${colour}` }}
          animate={reduced ? {} : { opacity: [1, 0.35, 1], scale: [1, 1.35, 1] }}
          transition={{ duration: state === 'live' ? 2.6 : 1.4, repeat: Infinity, ease: 'easeInOut' }}
        />
        {/* `tick` keeps "12 s ago" honest; it renders nothing itself. */}
        <span className="tnum text-[10.5px] leading-tight text-white/62" data-tick={tick}>
          {busy ? (
            'refreshing…'
          ) : state === 'down' ? (
            <span className="text-red-300/80">no data — API unreachable</span>
          ) : (
            <>
              {state === 'stale' ? 'last known ' : 'updated '}
              <span className="text-white/70">{formatClock(lastUpdated)}</span>
              <span className="ml-1.5 text-white/56">{formatAge(lastUpdated)}</span>
            </>
          )}
        </span>
      </div>

      <motion.button
        onClick={onRefresh}
        disabled={busy}
        aria-label="Refresh live data (keyboard shortcut R)"
        title="Refresh live data · shortcut R"
        className={`flex items-center gap-1.5 rounded-full border transition-colors ${
          compact ? 'px-2.5 py-1 text-[10.5px]' : 'px-3 py-1.5 text-[11px]'
        } ${
          error
            ? 'border-red-500/45 bg-red-500/10 text-red-200 hover:border-red-400'
            : 'border-white/15 bg-white/[.05] text-white/70 hover:border-white/35 hover:text-white'
        } disabled:cursor-wait disabled:opacity-60`}
        whileHover={reduced ? undefined : { scale: 1.035 }}
        whileTap={reduced ? undefined : { scale: 0.955 }}
        transition={spring.snappy}
      >
        <RefreshIcon spinning={busy} reduced={reduced} />
        <span className={compact ? 'hidden sm:inline' : ''}>Refresh</span>
      </motion.button>
    </div>
  )
}

/**
 * Honest failure notice. Replaces the old behaviour of quietly substituting
 * invented wards when the backend was down.
 */
/**
 * The fourth honest state: a real forecast run that is not live.
 *
 * On a static host (GitHub Pages) there is no FastAPI, so the ward ranking comes
 * from the exported snapshot in `public/static-api/`. That data is computed, not
 * invented — but it is frozen at the export date, and an operator has to be able
 * to tell the difference between "the pipeline is running" and "this is the last
 * run we shipped". Silence here would be the same lie as a mock fallback.
 */
export function SnapshotNotice({ snapshot, onRetry }) {
  const { reduced } = useMotionSafe()
  if (!snapshot) return null
  const date = snapshot.date || "the last exported run"
  const scenario =
    Number(snapshot.scenario_c) > 0
      ? `+${snapshot.scenario_c} °C scenario`
      : 'present-day conditions'
  const wards = Array.isArray(snapshot.data) ? snapshot.data.length : null

  return (
    <motion.div
      role="status"
      className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border px-4 py-3"
      style={{
        borderColor: 'rgba(56,189,248,.35)',
        background: 'rgba(56,189,248,.06)',
      }}
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={reduced ? { duration: 0 } : { duration: 0.5, ease: EASE }}
    >
      <span
        className="block h-2 w-2 shrink-0 rounded-full"
        style={{ background: DOT.live }}
      />
      <div className="min-w-0 flex-1 text-[11.5px] leading-relaxed">
        <span className="font-semibold" style={{ color: '#bae6fd' }}>
          Saved forecast run — this deployment has no live API
        </span>
        <span className="text-white/55">
          {' '}
          The map and league table show the exported run for {date} ({scenario}
          {wards != null ? `, ${wards} wards` : ''}), shipped with this build. The numbers are real and
          unchanged, but refreshing cannot update them here.
        </span>{' '}
        <span className="text-white/60">
          For live data run the API and open the dev server:
        </span>
        <code className="tnum ml-1.5 rounded bg-black/40 px-1.5 py-0.5 text-[10.5px] text-white/60">
          python -m uvicorn app.main:app --port 8000
        </code>
      </div>
      <motion.button
        onClick={onRetry}
        className="rounded-full border border-white/20 bg-white/[.06] px-3 py-1 text-[11px] text-white/80 transition hover:border-white/40"
        whileTap={reduced ? undefined : { scale: 0.96 }}
      >
        Check for live API
      </motion.button>
    </motion.div>
  )
}

export function ConnectionNotice({ error, lastUpdated, onRetry, busy = false }) {
  const { reduced } = useMotionSafe()
  if (!error) return null

  const haveData = lastUpdated != null

  return (
    <motion.div
      role="status"
      className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border px-4 py-3"
      style={{
        borderColor: haveData ? 'rgba(234,179,8,.4)' : 'rgba(239,68,68,.45)',
        background: haveData ? 'rgba(234,179,8,.07)' : 'rgba(239,68,68,.08)',
      }}
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={reduced ? { duration: 0 } : { duration: 0.5, ease: EASE }}
    >
      <span
        className="block h-2 w-2 shrink-0 rounded-full"
        style={{ background: haveData ? DOT.stale : DOT.down }}
      />
      <div className="min-w-0 flex-1 text-[11.5px] leading-relaxed">
        <span className="font-semibold" style={{ color: haveData ? '#fde68a' : '#fca5a5' }}>
          {haveData ? 'API unreachable — showing last known data' : 'API unreachable — no data to show'}
        </span>
        <span className="text-white/55">
          {' '}
          {haveData
            ? `Last successful fetch ${formatClock(lastUpdated)}. Nothing on this screen is simulated.`
            : 'HeatShield never renders placeholder wards. Start the API and refresh:'}
        </span>
        {!haveData && (
          <code className="tnum ml-1.5 rounded bg-black/40 px-1.5 py-0.5 text-[10.5px] text-white/60">
            python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
          </code>
        )}
        {' '}
        <span className="text-white/60">
          Retrying automatically every few seconds — this clears itself the moment the API answers
          (R retries now).
        </span>
      </div>
      <motion.button
        onClick={onRetry}
        disabled={busy}
        className="rounded-full border border-white/20 bg-white/[.06] px-3 py-1 text-[11px] text-white/80 transition hover:border-white/40 disabled:opacity-50"
        whileTap={reduced ? undefined : { scale: 0.96 }}
      >
        {busy ? 'Retrying…' : 'Retry'}
      </motion.button>
    </motion.div>
  )
}
