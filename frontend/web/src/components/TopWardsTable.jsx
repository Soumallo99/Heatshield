import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { bandColour, EASE, spring, useMotionSafe } from '../motion'

/**
 * Ranked ward table with the drivers behind each score.
 *
 * The map says *where* the heat is; this says *why*. Risk alone is a black box —
 * showing WBGT, vulnerability, UHI delta and population next to it lets an
 * operator see that two wards sitting on the same score got there for different
 * reasons (one is physically hotter, the other is more exposed), which changes
 * what they do about it.
 *
 * Built from divs rather than a real <table>: framer-motion's `layout` reorder
 * animates transforms, and table rows don't take transforms reliably across
 * browsers. A CSS grid gives identical alignment with animation that works.
 */

const COLUMNS = [
  { key: 'rank',        label: '#',    sortKey: null,            align: 'left',  cls: 'w-7' },
  { key: 'ward_name',   label: 'Ward', sortKey: 'ward_name',     align: 'left',  cls: '' },
  { key: 'risk_score',  label: 'Risk', sortKey: 'risk_score',    align: 'right', cls: 'w-14' },
  { key: 'risk_band',   label: 'Band', sortKey: 'risk_band',     align: 'left',  cls: 'w-[74px]' },
  { key: 'wbgt_peak_c', label: 'WBGT', sortKey: 'wbgt_peak_c',   align: 'right', cls: 'w-12 hidden sm:block' },
  { key: 'vulnerability', label: 'Vuln', sortKey: 'vulnerability', align: 'right', cls: 'w-12 hidden sm:block' },
  { key: 'uhi_delta_c', label: 'UHI',  sortKey: 'uhi_delta_c',   align: 'right', cls: 'w-14 hidden lg:block' },
  { key: 'population',  label: 'Pop',  sortKey: 'population',    align: 'right', cls: 'w-16 hidden lg:block' },
]

const GRID =
  'grid grid-cols-[26px_1fr_50px_70px] sm:grid-cols-[26px_1fr_50px_70px_46px_44px] lg:grid-cols-[26px_1fr_52px_70px_46px_44px_52px_62px] items-center gap-x-2'

const fmt = (v, d = 1) => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(d))

export default function TopWardsTable({ wards = [], selectedId, onSelect, defaultLimit = 10 }) {
  const { reduced, t } = useMotionSafe()
  const [sort, setSort] = useState({ key: 'risk_score', dir: 'desc' })
  const [showAll, setShowAll] = useState(false)

  const sorted = useMemo(() => {
    const arr = [...wards]
    arr.sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (typeof av === 'string' || typeof bv === 'string') {
        return sort.dir === 'asc'
          ? String(av).localeCompare(String(bv))
          : String(bv).localeCompare(String(av))
      }
      return sort.dir === 'asc' ? av - bv : bv - av
    })
    return arr
  }, [wards, sort])

  const shown = showAll ? sorted : sorted.slice(0, defaultLimit)
  // Reordering 141 rows with layout animation costs more than it's worth;
  // only the short view gets the animated shuffle.
  const animateRows = !reduced && shown.length <= 25

  const toggleSort = (key) => {
    if (!key) return
    setSort((s) =>
      s.key === key ? { key, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key, dir: 'desc' }
    )
  }

  return (
    <motion.section
      className="panel mt-6 p-6"
      initial={{ opacity: 0, y: 22 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.8, ease: EASE, delay: 0.26 }}
    >
      <div className="mb-5 flex flex-wrap items-end justify-between gap-2 border-b border-white/[.07] pb-3">
        <div>
          <div className="eyebrow">why, not just where</div>
          <h2 className="display mt-1.5 text-[22px] leading-none">Risk drivers</h2>
          <p className="mt-2 text-[11px] leading-snug text-white/35">
            Sort any column · select a row to drive the map and gauge
          </p>
        </div>
        <button
          onClick={() => setShowAll((v) => !v)}
          className="rounded-full border border-white/12 bg-white/[.04] px-3 py-1 text-[10.5px] text-white/60 transition hover:border-white/30 hover:text-white/90"
        >
          {showAll ? `Top ${defaultLimit}` : `All ${wards.length}`}
        </button>
      </div>

      {/* header */}
      <div className={`${GRID} border-b border-white/[.08] pb-2`}>
        {COLUMNS.map((c) => {
          const active = sort.key === c.sortKey
          return (
            <button
              key={c.key}
              onClick={() => toggleSort(c.sortKey)}
              disabled={!c.sortKey}
              className={`${c.cls} text-[9.5px] uppercase tracking-[0.1em] transition ${
                c.align === 'right' ? 'text-right' : 'text-left'
              } ${c.sortKey ? 'cursor-pointer hover:text-white/70' : 'cursor-default'} ${
                active ? 'text-white/70' : 'text-white/30'
              }`}
              title={c.sortKey ? `Sort by ${c.label}` : undefined}
            >
              {c.label}
              {active && (
                <motion.span
                  className="ml-1 inline-block"
                  animate={{ rotate: sort.dir === 'desc' ? 0 : 180 }}
                  transition={t(spring.snappy)}
                >
                  ▾
                </motion.span>
              )}
            </button>
          )
        })}
      </div>

      {/* rows */}
      <div className="relative">
        <AnimatePresence initial={false}>
          {shown.map((w, i) => {
            const c = bandColour[w.risk_band] || '#22c55e'
            const isSel = w.ward_id === selectedId
            return (
              <motion.div
                key={w.ward_id}
                layout={animateRows}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={t({ duration: 0.45, ease: EASE, delay: animateRows ? i * 0.02 : 0 })}
                onClick={() => onSelect?.(w.ward_id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelect?.(w.ward_id)
                  }
                }}
                className={`${GRID} cursor-pointer rounded-lg px-1.5 py-2 transition-colors ${
                  isSel ? 'bg-white/[.07]' : 'hover:bg-white/[.04]'
                }`}
              >
                {isSel && (
                  <motion.span
                    layoutId="rowHighlight"
                    className="pointer-events-none absolute inset-x-0 rounded-lg"
                    style={{ border: `1px solid ${c}`, height: 36 }}
                    transition={t(spring.layout)}
                  />
                )}

                <span className="relative tnum text-[10.5px] text-white/30">{i + 1}</span>
                <span className="relative truncate text-[12px] text-white/85">{w.ward_name}</span>
                <span className="relative tnum text-right text-[12.5px] font-semibold" style={{ color: c }}>
                  {fmt(w.risk_score)}
                </span>
                <span className="relative">
                  <span
                    className="inline-block rounded-full px-1.5 py-[1px] text-[9px] font-semibold"
                    style={{ background: `${c}1f`, color: c, border: `1px solid ${c}44` }}
                  >
                    {w.risk_band}
                  </span>
                </span>
                <span className="relative tnum hidden text-right text-[11.5px] text-white/55 sm:block">
                  {fmt(w.wbgt_peak_c)}
                </span>
                <span className="relative tnum hidden text-right text-[11.5px] text-white/55 sm:block">
                  {fmt(w.vulnerability, 0)}
                </span>
                <span className="relative tnum hidden text-right text-[11.5px] text-white/55 lg:block">
                  +{fmt(w.uhi_delta_c, 2)}
                </span>
                <span className="relative tnum hidden text-right text-[11.5px] text-white/55 lg:block">
                  {Number(w.population || 0).toLocaleString('en-IN')}
                </span>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>

      {wards.length > defaultLimit && (
        <p className="mt-2.5 text-[10px] text-white/25">
          Showing {shown.length} of {wards.length} wards
        </p>
      )}
    </motion.section>
  )
}
