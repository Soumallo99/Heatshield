import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { EMPTY_PHONE_PAYLOAD, SCREEN_IDS, heatAlertFor, nearestZone } from './contract.js'
import { loadPhonePayload } from './data.js'
import { MobileScreen, screenLabel } from './screens.js'

const SWIPE_DISTANCE = 48

function nextIndex(current, direction) {
  return (current + direction + SCREEN_IDS.length) % SCREEN_IDS.length
}

/* Personal heat alerts are opt-in per device. The preference and a small
   de-duplication ledger live in localStorage; nothing is ever sent anywhere —
   these are local browser notifications built from the payload the app
   already loaded (and labelled Practice data when that payload is synthetic). */
const ALERT_PREF_KEY = 'heatshield.personalAlerts'
const ALERT_SENT_KEY = 'heatshield.personalAlerts.sent'

function readAlertPref() {
  try { return localStorage.getItem(ALERT_PREF_KEY) === 'on' } catch { return false }
}

function writeAlertPref(on) {
  try { localStorage.setItem(ALERT_PREF_KEY, on ? 'on' : 'off') } catch { /* private mode */ }
}

function readSentLedger() {
  try { return JSON.parse(localStorage.getItem(ALERT_SENT_KEY) || '{}') } catch { return {} }
}

function writeSentLedger(ledger) {
  try {
    const keys = Object.keys(ledger)
    if (keys.length > 40) for (const key of keys.slice(0, keys.length - 40)) delete ledger[key]
    localStorage.setItem(ALERT_SENT_KEY, JSON.stringify(ledger))
  } catch { /* private mode */ }
}

const notificationsSupported = typeof window !== 'undefined' && 'Notification' in window

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
  const [alertsOn, setAlertsOn] = useState(readAlertPref)
  const [notice, setNotice] = useState('')
  const [locating, setLocating] = useState(false)
  const [installPrompt, setInstallPrompt] = useState(null)
  const pointerStart = useRef(null)

  /* Capture the PWA install prompt so "Install" is one tap when the browser
     offers it (Chrome/Edge/Android). Where it is unavailable (iOS Safari),
     the About screen explains Add to Home Screen instead. */
  useEffect(() => {
    const onPrompt = (event) => {
      event.preventDefault()
      setInstallPrompt(event)
    }
    window.addEventListener('beforeinstallprompt', onPrompt)
    return () => window.removeEventListener('beforeinstallprompt', onPrompt)
  }, [])

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

  /* Fire the personal heat-risk notification for the selected locality —
     once per zone × timestamp × band × data-quality state. */
  useEffect(() => {
    if (!alertsOn || status !== 'ready' || !notificationsSupported) return
    if (Notification.permission !== 'granted' || !selected) return
    const alert = heatAlertFor(selected, { isSynthetic: payload.summary.is_synthetic })
    if (!alert) return
    const ledger = readSentLedger()
    if (ledger[alert.id]) return
    try {
      const notification = new Notification(alert.title, { body: alert.body, tag: alert.id, lang: 'en-IN' })
      notification.onclick = () => { window.focus(); notification.close() }
      ledger[alert.id] = new Date().toISOString()
      writeSentLedger(ledger)
    } catch { /* some Android webviews throw on construction — the in-app card still shows */ }
  }, [alertsOn, status, selected, payload])

  const locate = () => {
    if (!('geolocation' in navigator)) {
      setNotice('This browser has no geolocation — pick your locality from the strip instead.')
      return
    }
    setLocating(true)
    setNotice('Getting your location…')
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocating(false)
        const hit = nearestZone(zones, position.coords.latitude, position.coords.longitude)
        if (!hit) {
          setNotice('Zone coordinates are not loaded yet — pick your locality from the strip.')
          return
        }
        setSelectedZoneId(hit.zone_id)
        setNotice(`Nearest zone: ${hit.zone_name} (≈${Math.round(hit.km)} km from its centre — a ~10 km model grid point, not your street).`)
      },
      (error) => {
        setLocating(false)
        setNotice(error.code === error.PERMISSION_DENIED
          ? 'Location permission denied — pick your locality from the strip. No key or account is needed for this.'
          : 'Could not get a GPS fix right now — pick your locality from the strip.')
      },
      { timeout: 10000, maximumAge: 300000 },
    )
  }

  const toggleAlerts = async () => {
    if (alertsOn) {
      setAlertsOn(false)
      writeAlertPref(false)
      setNotice('Personal heat alerts turned off on this device.')
      return
    }
    if (!notificationsSupported) {
      setNotice('This browser does not support notifications — keep the app open and refresh for your heat risk.')
      return
    }
    try {
      const permission = Notification.permission === 'granted'
        ? 'granted'
        : await Notification.requestPermission()
      if (permission !== 'granted') {
        setNotice('Notification permission was not granted — allow it in your browser’s site settings to receive personal heat alerts.')
        return
      }
      setAlertsOn(true)
      writeAlertPref(true)
      setNotice('Personal heat alerts ON for your selected locality — unhealthy heat+air load triggers one labelled notification per update.')
    } catch {
      setNotice('Could not enable notifications in this browser.')
    }
  }

  const install = async () => {
    if (!installPrompt) return
    installPrompt.prompt()
    try {
      const choice = await installPrompt.userChoice
      setNotice(choice?.outcome === 'accepted'
        ? 'Installing HeatShield… find it on your home screen.'
        : 'Install dismissed — you can install any time from the browser menu → Install app.')
    } finally {
      setInstallPrompt(null)
    }
  }

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
            <button
              type="button"
              className="phone-icon-button"
              onClick={locate}
              aria-label="Find my nearest locality"
              title="Find my nearest locality (uses your GPS; no API key, nothing leaves the device)"
              disabled={locating || status === 'loading'}
            >
              <span aria-hidden="true">📍</span>
            </button>
            <button
              type="button"
              className="phone-icon-button"
              onClick={toggleAlerts}
              aria-label={alertsOn ? 'Turn off personal heat alerts' : 'Turn on personal heat alerts'}
              aria-pressed={alertsOn}
              title="Personal heat-risk notifications for your locality (opt-in, on this device)"
            >
              <span aria-hidden="true">{alertsOn ? '🔔' : '🔕'}</span>
            </button>
            {installPrompt ? (
              <button type="button" className="phone-text-button" onClick={install}>Install</button>
            ) : null}
            <button type="button" className="phone-icon-button" onClick={refresh} aria-label="Refresh heat and air data" disabled={status === 'loading'}>
              <span className={status === 'loading' ? 'phone-refreshing' : ''} aria-hidden="true">↻</span>
            </button>
            {onExit ? <button type="button" className="phone-text-button" onClick={onExit}>Ops</button> : null}
          </div>
        </header>

        {notice ? <p className="phone-notice" role="status">{notice}</p> : null}

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
