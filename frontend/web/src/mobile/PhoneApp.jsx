import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { EMPTY_PHONE_PAYLOAD, SCREEN_IDS } from './contract.js'
import { loadPhonePayload } from './data.js'
import { MobileScreen, screenLabel } from './screens.js'

const SWIPE_DISTANCE = 48

function nextIndex(current, direction) {
  return (current + direction + SCREEN_IDS.length) % SCREEN_IDS.length
}

/**
 * The installed, thumb-first HeatShield experience.
 *
 * Five short screens fit a phone's attention span. A horizontal swipe advances
 * between them; visible tabs and keyboard-operable buttons provide an equally
 * complete non-gesture path. Motion is transform/opacity only so it stays cheap
 * on lower-end Android devices.
 */
export default function PhoneApp({ onExit, initialZoneId = '' }) {
  const reduceMotion = useReducedMotion()
  const [payload, setPayload] = useState(EMPTY_PHONE_PAYLOAD)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  const [screenIndex, setScreenIndex] = useState(0)
  const [direction, setDirection] = useState(1)
  const [selectedZoneId, setSelectedZoneId] = useState(initialZoneId)
  const pointerStart = useRef(null)

  const refresh = useCallback(async () => {
    const controller = new AbortController()
    setStatus('loading')
    setError('')
    try {
      const next = await loadPhonePayload({ signal: controller.signal })
      setPayload(next)
      setSelectedZoneId((selected) => next.summary.data.some((zone) => zone.zone_id === selected)
        ? selected
        : (next.summary.data[0]?.zone_id || ''))
      setStatus('ready')
    } catch (fetchError) {
      if (fetchError?.name === 'AbortError') return
      setStatus('error')
      setError(fetchError?.message || 'Unable to load HeatShield data.')
    }
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setStatus('loading')
    loadPhonePayload({ signal: controller.signal })
      .then((next) => {
        if (!active) return
        setPayload(next)
        setSelectedZoneId((selected) => next.summary.data.some((zone) => zone.zone_id === selected)
          ? selected
          : (next.summary.data[0]?.zone_id || ''))
        setStatus('ready')
      })
      .catch((fetchError) => {
        if (!active || fetchError?.name === 'AbortError') return
        setStatus('error')
        setError(fetchError?.message || 'Unable to load HeatShield data.')
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [])

  const activeScreen = SCREEN_IDS[screenIndex]
  const zones = payload.summary.data
  const selected = useMemo(
    () => zones.find((zone) => zone.zone_id === selectedZoneId) || zones[0],
    [zones, selectedZoneId],
  )

  const chooseScreen = (index) => {
    setDirection(index >= screenIndex ? 1 : -1)
    setScreenIndex(index)
  }

  const moveScreen = (move) => {
    setDirection(move)
    setScreenIndex((current) => nextIndex(current, move))
  }

  const onPointerDown = (event) => {
    pointerStart.current = { x: event.clientX, y: event.clientY, id: event.pointerId }
  }

  const onPointerUp = (event) => {
    const start = pointerStart.current
    pointerStart.current = null
    if (!start || start.id !== event.pointerId) return
    const deltaX = event.clientX - start.x
    const deltaY = event.clientY - start.y
    if (Math.abs(deltaX) < SWIPE_DISTANCE || Math.abs(deltaX) <= Math.abs(deltaY)) return
    moveScreen(deltaX < 0 ? 1 : -1)
  }

  const transition = reduceMotion
    ? { duration: 0 }
    : { type: 'spring', stiffness: 340, damping: 34, mass: 0.72 }

  return (
    <main className="phone-page">
      <section className="phone-shell" aria-label="HeatShield citizen phone app">
        <header className="phone-header">
          <button type="button" className="phone-brand" onClick={() => chooseScreen(0)} aria-label="HeatShield home">
            <span className="phone-brand__mark" aria-hidden="true">H</span>
            <span>HeatShield</span>
          </button>
          <div className="phone-header__actions">
            <button type="button" className="phone-icon-button" onClick={refresh} aria-label="Refresh heat and air data" disabled={status === 'loading'}>
              <span className={status === 'loading' ? 'phone-refreshing' : ''} aria-hidden="true">↻</span>
            </button>
            {onExit ? <button type="button" className="phone-text-button" onClick={onExit}>Ops</button> : null}
          </div>
        </header>

        {zones.length > 1 ? (
          <div className="phone-zone-strip" aria-label="Choose locality">
            {zones.map((zone) => (
              <button
                type="button"
                key={zone.zone_id}
                className={zone.zone_id === selected?.zone_id ? 'is-active' : ''}
                aria-pressed={zone.zone_id === selected?.zone_id}
                onClick={() => setSelectedZoneId(zone.zone_id)}
              >
                {zone.zone_name}
              </button>
            ))}
          </div>
        ) : null}

        <div
          className="phone-stage"
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
          onPointerCancel={() => { pointerStart.current = null }}
        >
          <AnimatePresence initial={false} mode="wait" custom={direction}>
            <motion.div
              key={activeScreen}
              className="phone-slide"
              custom={direction}
              initial={reduceMotion ? false : { opacity: 0, x: direction * 28 }}
              animate={{ opacity: 1, x: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, x: direction * -22 }}
              transition={transition}
            >
              {status === 'loading' && !zones.length ? (
                <section className="phone-screen-content" aria-live="polite">
                  <p className="phone-kicker">HEAT + AIR</p>
                  <h1>Preparing your local brief</h1>
                  <p className="phone-empty">Loading the latest saved or live heat and air data…</p>
                </section>
              ) : status === 'error' && !zones.length ? (
                <section className="phone-screen-content" aria-live="assertive">
                  <p className="phone-kicker">CONNECTION</p>
                  <h1>Brief unavailable</h1>
                  <p className="phone-empty">{error}</p>
                  <button type="button" className="phone-retry" onClick={refresh}>Try again</button>
                </section>
              ) : (
                <MobileScreen screen={activeScreen} payload={payload} selectedZoneId={selected?.zone_id || ''} />
              )}
            </motion.div>
          </AnimatePresence>
        </div>

        <div className="phone-swipe-hint" aria-hidden="true">
          <span>Swipe for the next card</span>
          <span>← →</span>
        </div>

        <nav className="phone-tabs" aria-label="Phone app sections">
          {SCREEN_IDS.map((screen, index) => (
            <button
              type="button"
              key={screen}
              className={screen === activeScreen ? 'is-active' : ''}
              aria-current={screen === activeScreen ? 'page' : undefined}
              onClick={() => chooseScreen(index)}
            >
              <span className="phone-tabs__dot" aria-hidden="true" />
              {screenLabel(screen)}
            </button>
          ))}
        </nav>
        <motion.div
          className="phone-progress"
          aria-hidden="true"
          animate={{ scaleX: (screenIndex + 1) / SCREEN_IDS.length }}
          transition={transition}
        />
      </section>
    </main>
  )
}
