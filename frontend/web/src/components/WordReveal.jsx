import { motion } from 'framer-motion'
import { EASE } from '../motion'

/**
 * Per-word masked reveal.
 *
 * Each word sits in its own overflow-hidden box and rises from below the baseline.
 * This is the single highest-leverage "designed" detail on a landing page — text
 * that assembles itself instead of fading in.
 *
 * `as="em"` renders the whole line in the display italic for accent lines.
 */
export default function WordReveal({
  text,
  className = '',
  wordClassName = '',
  delay = 0,
  step = 0.055,
  duration = 0.9,
  as: Tag = 'span',
}) {
  const words = String(text).split(' ')
  return (
    <Tag className={className} style={{ display: 'inline' }}>
      {words.map((w, i) => (
        <span
          key={`${w}-${i}`}
          style={{ display: 'inline-block', overflow: 'hidden', verticalAlign: 'bottom', paddingBottom: '0.14em' }}
        >
          <motion.span
            className={wordClassName}
            style={{ display: 'inline-block' }}
            initial={{ y: '115%', opacity: 0 }}
            animate={{ y: '0%', opacity: 1 }}
            transition={{ duration, ease: EASE, delay: delay + i * step }}
          >
            {w}
            {i < words.length - 1 ? ' ' : ''}
          </motion.span>
        </span>
      ))}
    </Tag>
  )
}
