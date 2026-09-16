/**
 * Motion language — one place, used everywhere.
 *
 * The rules that make motion feel authored rather than defaulted:
 *   1. ENTRANCES are eased (expo-out) — they have a definite start and end.
 *   2. INTERACTIONS are sprung — they respond to input and may be interrupted mid-flight.
 *   3. BIG elements move slower and longer; small elements snap. Mass matters.
 *   4. Nothing animates two properties with the same timing unless it's deliberate.
 */
import { useReducedMotion } from 'framer-motion'

/** Expo-out. Fast commitment, long settle — the "expensive" curve. */
export const EASE = [0.16, 1, 0.3, 1]
/** Expo-in-out, for elements that travel a long distance. */
export const EASE_IO = [0.83, 0, 0.17, 1]

export const spring = {
  /** large surfaces, background layers: slow, heavy, unhurried */
  glide: { type: 'spring', stiffness: 70, damping: 22, mass: 1.6 },
  /** default UI: settles in ~350ms with a faint overshoot */
  normal: { type: 'spring', stiffness: 260, damping: 28, mass: 0.9 },
  /** buttons, hovers: immediate */
  snappy: { type: 'spring', stiffness: 420, damping: 30, mass: 0.6 },
  /** gauges, numbers: heavy needle with real inertia, no bounce */
  gauge: { type: 'spring', stiffness: 90, damping: 18, mass: 1.2 },
  /** layout moves (shared element transitions) */
  layout: { type: 'spring', stiffness: 200, damping: 26, mass: 1 },
}

/** Staggered entrance for a list. */
export const rise = (i = 0, delay = 0, distance = 22) => ({
  initial: { opacity: 0, y: distance },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.85, ease: EASE, delay: delay + i * 0.055 },
})

/** Respect the OS setting — return a no-op transition when reduced motion is on. */
export function useMotionSafe() {
  const reduced = useReducedMotion()
  return {
    reduced,
    t: (transition) => (reduced ? { duration: 0 } : transition),
    /** ambient/looping animation: disable entirely under reduced motion */
    loop: (animation) => (reduced ? {} : animation),
  }
}

export const bandColour = {
  Normal: '#22c55e',
  Caution: '#eab308',
  Danger: '#f97316',
  Critical: '#ef4444',
  Extreme: '#a21caf',
}

export const bandText = {
  Caution: 'Caution — vulnerable groups at risk',
  Danger: 'Danger — outdoor labour restriction advised',
  Critical: 'CRITICAL — suspend non-essential outdoor work',
  Extreme: 'EXTREME — life-threatening heat stress',
  Normal: 'Normal — no restriction',
}
