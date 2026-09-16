import { useEffect } from 'react'
import { motion, useSpring, useTransform } from 'framer-motion'
import Odometer from './Odometer'
import { bandColour, EASE } from '../motion'

const R = 78
const CX = 100
const CY = 104
const ARC = `M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`
const LEN = Math.PI * R

const TICKS = [0, 25, 50, 75, 100]

/**
 * Risk gauge.
 *
 * The needle is driven by a spring, not a tween, so interrupting it mid-swing
 * (clicking ward to ward) reads as physical inertia rather than a restart.
 * The arc, the number and the colour all derive from that ONE spring value —
 * they can never drift out of sync with each other.
 */
export default function Gauge({ value = 0, band = 'Normal', caption = '' }) {
  const spring = useSpring(0, { stiffness: 90, damping: 18, mass: 1.2 })

  useEffect(() => {
    spring.set(Math.max(0, Math.min(100, Number(value) || 0)))
  }, [value, spring])

  const offset = useTransform(spring, (v) => LEN - (v / 100) * LEN)
  const rotate = useTransform(spring, (v) => -90 + (v / 100) * 180)
  const colour = bandColour[band] || '#22c55e'

  return (
    <div className="relative flex flex-col items-center">
      <svg viewBox="0 0 200 132" className="w-full max-w-[300px]" role="img" aria-label={`Risk score ${value}`}>
        <defs>
          <linearGradient id="gaugeGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#22c55e" />
            <stop offset="38%" stopColor="#eab308" />
            <stop offset="70%" stopColor="#f97316" />
            <stop offset="100%" stopColor="#ef4444" />
          </linearGradient>
          <filter id="gaugeGlow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* track */}
        <path d={ARC} fill="none" stroke="rgba(255,255,255,.08)" strokeWidth="13" strokeLinecap="round" />

        {/* progress — driven by the spring */}
        <motion.path
          d={ARC}
          fill="none"
          stroke="url(#gaugeGrad)"
          strokeWidth="13"
          strokeLinecap="round"
          strokeDasharray={LEN}
          style={{ strokeDashoffset: offset, filter: 'url(#gaugeGlow)' }}
        />

        {/* ticks */}
        {TICKS.map((t, i) => {
          const a = Math.PI * (1 - t / 100)
          const x1 = CX + Math.cos(a) * (R - 11)
          const y1 = CY - Math.sin(a) * (R - 11)
          const x2 = CX + Math.cos(a) * (R - 17)
          const y2 = CY - Math.sin(a) * (R - 17)
          return (
            <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(255,255,255,.25)" strokeWidth="1.2" />
          )
        })}

        {/* needle */}
        <motion.line
          x1={CX}
          y1={CY}
          x2={CX}
          y2={CY - R + 14}
          stroke="#ffffff"
          strokeWidth="2.5"
          strokeLinecap="round"
          style={{ rotate, originX: `${CX}px`, originY: `${CY}px` }}
        />
        <circle cx={CX} cy={CY} r="5.5" fill="#fff" />
        <circle cx={CX} cy={CY} r="9" fill="none" stroke="rgba(255,255,255,.18)" strokeWidth="1.5" />
      </svg>

      {/* value sits inside the arc, so it inherits the gauge's motion rhythm */}
      <motion.div
        className="mt-[-38px] flex flex-col items-center"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: EASE, delay: 0.25 }}
      >
        <Odometer value={value} decimals={0} height={1} className="text-[44px] font-semibold" />
        <motion.span
          className="eyebrow mt-1.5"
          animate={{ color: colour }}
          transition={{ duration: 0.4 }}
          style={{ letterSpacing: '0.22em' }}
        >
          {band}
        </motion.span>
        {caption && <span className="mt-1 text-[11px] text-white/40">{caption}</span>}
      </motion.div>
    </div>
  )
}
