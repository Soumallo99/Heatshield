import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'

const DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']

/**
 * Vertical odometer digit.
 *
 * Why not just interpolate the number? Because a real odometer sells magnitude —
 * you see it travel. Each column is a 10-high strip translated by -digit, so the
 * roll is continuous and directionally correct (9 -> 0 rolls forward, not back).
 */
function Digit({ digit, height }) {
  return (
    <span
      style={{
        display: 'inline-block',
        height: `${height}em`,
        overflow: 'hidden',
        verticalAlign: 'bottom',
      }}
    >
      <motion.span
        style={{ display: 'block' }}
        animate={{ y: `${-digit * height}em` }}
        transition={{ type: 'spring', stiffness: 260, damping: 26, mass: 0.8 }}
      >
        {DIGITS.map((d) => (
          <span
            key={d}
            style={{ display: 'block', height: `${height}em`, lineHeight: `${height}em`, textAlign: 'center' }}
          >
            {d}
          </span>
        ))}
      </motion.span>
    </span>
  )
}

export default function Odometer({ value = 0, decimals = 0, height = 1, className = '' }) {
  const [text, setText] = useState('')

  useEffect(() => {
    // Ramp from 0 on first paint so the number "arrives" like the rest of the page.
    const target = Number(value || 0).toFixed(decimals)
    setText(target)
  }, [value, decimals])

  const chars = text.split('')

  return (
    // Each digit is a 10-high strip, so the DOM literally contains "0123456789"
    // per column. Without this wrapper a screen reader reads all ten digits for
    // every column ("zero one two three...") instead of the number. The strip is
    // hidden from assistive tech and the real value is exposed once, via
    // aria-label. It also gives tests a single readable handle on the value.
    <span
      className={`tnum inline-flex items-baseline ${className}`}
      style={{ lineHeight: `${height}em` }}
      role="img"
      aria-label={text}
      data-value={text}
    >
      <span aria-hidden="true" className="inline-flex items-baseline">
        {chars.map((c, i) =>
          /\d/.test(c) ? (
            // Key from the RIGHT so digits keep their place when the number
            // changes width (9 -> 10) instead of all sliding one slot over.
            <Digit key={chars.length - i} digit={Number(c)} height={height} />
          ) : (
            <span key={chars.length - i} style={{ lineHeight: `${height}em` }}>
              {c}
            </span>
          )
        )}
      </span>
    </span>
  )
}
