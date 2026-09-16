import { motion } from 'framer-motion'
import { useMotionSafe } from '../motion'

/**
 * Ambient background: three slow heat blooms, a drifting measurement grid, one
 * scan sweep, and a film-grain overlay.
 *
 * Rules it obeys so it reads as atmosphere rather than decoration:
 *   - very long, prime-ish durations (23/29/37s) so the layers never re-sync
 *   - massive blur, low opacity — you feel it, you don't watch it
 *   - one directional sweep, slow enough to be subliminal
 *   - entirely disabled under prefers-reduced-motion
 */
const BLOBS = [
  { c: '#ff4d4d', size: 52, left: '-12vw', top: '-14vw', dur: 23, path: { x: [0, 90, -30, 0], y: [0, 60, 110, 0] } },
  { c: '#ff9f43', size: 46, right: '-10vw', top: '6vh', dur: 29, path: { x: [0, -110, 40, 0], y: [0, 120, 40, 0] } },
  { c: '#7c3aed', size: 40, left: '24vw', bottom: '-16vw', dur: 37, path: { x: [0, 120, -60, 0], y: [0, -90, 20, 0] } },
]

export default function HeatField() {
  const { reduced } = useMotionSafe()

  return (
    <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden" aria-hidden="true">
      {!reduced &&
        BLOBS.map((b, i) => (
          <motion.div
            key={i}
            className="absolute rounded-full"
            style={{
              width: `${b.size}vw`,
              height: `${b.size}vw`,
              left: b.left,
              right: b.right,
              top: b.top,
              bottom: b.bottom,
              background: `radial-gradient(circle, ${b.c}, transparent 65%)`,
              filter: 'blur(90px)',
              opacity: 0.28,
              mixBlendMode: 'screen',
            }}
            animate={b.path}
            transition={{ duration: b.dur, repeat: Infinity, ease: 'easeInOut' }}
          />
        ))}

      {/* measurement grid */}
      <motion.div
        className="absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.04) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse at 50% 28%, #000 25%, transparent 76%)',
          WebkitMaskImage: 'radial-gradient(ellipse at 50% 28%, #000 25%, transparent 76%)',
          opacity: 0.5,
        }}
        animate={reduced ? {} : { backgroundPosition: ['0px 0px', '48px 48px'] }}
        transition={{ duration: 24, repeat: Infinity, ease: 'linear' }}
      />

      {/* scan sweep */}
      {!reduced && (
        <motion.div
          className="absolute left-0 right-0"
          style={{
            height: 180,
            background: 'linear-gradient(180deg, transparent, rgba(34,211,238,.05), transparent)',
          }}
          animate={{ top: ['-180px', '100%'] }}
          transition={{ duration: 9, repeat: Infinity, ease: 'linear' }}
        />
      )}

      {/* vignette keeps text legible over the blooms */}
      <div
        className="absolute inset-0"
        style={{ background: 'radial-gradient(ellipse at 50% 40%, transparent 40%, rgba(7,8,13,.72) 100%)' }}
      />
    </div>
  )
}
