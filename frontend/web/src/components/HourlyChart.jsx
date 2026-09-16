import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { bandColour, EASE } from '../motion'

const W = 620
const H = 150
const PAD = { t: 16, r: 12, b: 22, l: 30 }

/**
 * 24-hour thermal-stress curve.
 *
 * The line draws itself once (pathLength 0 -> 1) and re-draws on ward change —
 * a redraw is a legitimate "new data" signal, so unlike the gauge it should NOT
 * be sprung. Area fades in behind it, then the peak marker lands last.
 */
export default function HourlyChart({ data = [], metric = 'wbgt_adj_c', unit = '°C WBGT' }) {
  const model = useMemo(() => {
    const rows = (data || []).filter((d) => d && d[metric] != null).slice(-24)
    if (rows.length < 2) return null

    const vals = rows.map((d) => Number(d[metric]))
    const min = Math.min(...vals)
    const max = Math.max(...vals)
    const pad = (max - min) * 0.25 || 1
    const lo = min - pad
    const hi = max + pad

    const x = (i) => PAD.l + (i / (rows.length - 1)) * (W - PAD.l - PAD.r)
    const y = (v) => H - PAD.b - ((v - lo) / (hi - lo || 1)) * (H - PAD.t - PAD.b)

    const line = rows.map((d, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(Number(d[metric])).toFixed(1)}`).join(' ')
    const area = `${line} L${x(rows.length - 1).toFixed(1)} ${H - PAD.b} L${x(0).toFixed(1)} ${H - PAD.b} Z`

    const peakIdx = vals.indexOf(Math.max(...vals))
    const hourOf = (d) => {
      const t = String(d.timestamp_local || '')
      const m = t.match(/T(\d{2}):/)
      return m ? `${m[1]}:00` : t.slice(11, 16)   // RegExpMatchArray has no .group()
    }

    return { rows, vals, line, area, x, y, peakIdx, hourOf, lo, hi }
  }, [data, metric])

  if (!model) {
    return <div className="flex h-[150px] items-center justify-center text-xs text-white/35">loading curve…</div>
  }

  const { rows, vals, line, area, x, y, peakIdx, hourOf } = model
  const peakBand = rows[peakIdx]?.risk_band || rows[peakIdx]?.stress_band || 'Danger'
  const peakColour = bandColour[peakBand] || '#f97316'

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <defs>
          <linearGradient id="lineGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#22d3ee" />
            <stop offset="50%" stopColor="#f97316" />
            <stop offset="100%" stopColor="#ef4444" />
          </linearGradient>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f97316" stopOpacity="0.34" />
            <stop offset="100%" stopColor="#f97316" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* horizontal guides */}
        {[0, 0.5, 1].map((f) => {
          const gy = PAD.t + f * (H - PAD.t - PAD.b)
          return (
            <line key={f} x1={PAD.l} y1={gy} x2={W - PAD.r} y2={gy} stroke="rgba(255,255,255,.06)" strokeWidth="1" />
          )
        })}

        <motion.path d={area} fill="url(#areaGrad)" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.9, delay: 0.55 }} />

        <motion.path
          d={line}
          fill="none"
          stroke="url(#lineGrad)"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1.5, ease: EASE }}
          style={{ filter: 'drop-shadow(0 0 6px rgba(249,115,22,.5))' }}
        />

        {/* axis labels */}
        {rows.map((d, i) =>
          i % 4 === 0 ? (
            <text key={i} x={x(i)} y={H - 6} textAnchor="middle" className="tnum" style={{ fontSize: 8.5, fill: 'rgba(255,255,255,.32)' }}>
              {hourOf(d)}
            </text>
          ) : null
        )}

        {/* peak marker — lands after the line finishes drawing */}
        <motion.g
          initial={{ opacity: 0, scale: 0.4 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, ease: EASE, delay: 1.35 }}
          style={{ originX: `${x(peakIdx)}px`, originY: `${y(vals[peakIdx])}px` }}
        >
          {/* pulse via transform, not the `r` attribute: framer writes
              undefined to r mid-keyframe when animating SVG geometry directly */}
          <motion.g
            animate={{ scale: [1, 1.7, 1] }}
            transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
            style={{ originX: `${x(peakIdx)}px`, originY: `${y(vals[peakIdx])}px` }}
          >
            <circle cx={x(peakIdx)} cy={y(vals[peakIdx])} r="4" fill="#fff" stroke={peakColour} strokeWidth="2.5" />
          </motion.g>
          <text
            x={x(peakIdx)}
            y={y(vals[peakIdx]) - 11}
            textAnchor="middle"
            className="tnum"
            style={{ fontSize: 10, fill: peakColour, fontWeight: 700 }}
          >
            {vals[peakIdx].toFixed(1)}°
          </text>
        </motion.g>
      </svg>

      <div className="mt-1 flex items-center justify-between text-[10px] text-white/35">
        <span>{unit} · next 24 h</span>
        <span>
          peak {vals[peakIdx].toFixed(1)}° · {peakBand}
        </span>
      </div>
    </div>
  )
}
