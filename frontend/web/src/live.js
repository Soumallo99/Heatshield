/**
 * Live-data plumbing shared by every route.
 *
 * One rule drives all of it: the UI shows real data or it says so. `useLive`
 * therefore keeps the last good payload when a refresh fails (so the screen
 * stays useful) but always exposes the error, and the caller renders
 * "showing last known data from HH:MM:SS" rather than inventing a fill-in.
 *
 * No auto-polling — refreshing is a deliberate act (button or the `R` key),
 * per the project's "real time = live on load + manual refresh" decision.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * @param load  async () => payload. Re-created on every render is fine; it is
 *              read through a ref so only `deps` + the refresh token re-run it.
 * @param deps  values that should trigger a refetch (scenario, ward id, …).
 */
export function useLive(load, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [token, setToken] = useState(0)

  const loadRef = useRef(load)
  loadRef.current = load
  const reqId = useRef(0)

  useEffect(() => {
    const id = ++reqId.current
    let cancelled = false
    setLoading(true)

    Promise.resolve()
      .then(() => loadRef.current())
      .then((payload) => {
        if (cancelled || reqId.current !== id) return
        setData(payload)
        setError(null)
        setLastUpdated(new Date())
      })
      .catch((err) => {
        if (cancelled || reqId.current !== id) return
        if (err?.name === 'AbortError') return
        setError(err)
      })
      .finally(() => {
        if (!cancelled && reqId.current === id) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, token])

  const refresh = useCallback(() => setToken((t) => t + 1), [])

  return {
    data,
    error,
    loading,
    /** true when a refetch is in flight on top of data we already have */
    refreshing: loading && data != null,
    /** true when the payload on screen predates a failed refetch */
    stale: error != null && data != null,
    lastUpdated,
    refresh,
    token,
  }
}

/**
 * `R` refreshes the current view.
 * Ignored while typing, and ignored with modifiers so ⌘R keeps reloading the
 * page — surprising a user by hijacking their browser reload is worse than the
 * shortcut is worth.
 */
export function useRefreshShortcut(handler, enabled = true) {
  const ref = useRef(handler)
  ref.current = handler

  useEffect(() => {
    if (!enabled) return undefined
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const t = e.target
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      if (e.key === 'r' || e.key === 'R') {
        e.preventDefault()
        ref.current?.()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled])
}

/** 24 h clock, seconds included — the "last updated" affordance. */
export function formatClock(d) {
  if (!d) return '—'
  const dt = d instanceof Date ? d : new Date(d)
  if (Number.isNaN(dt.getTime())) return '—'
  const p = (n) => String(n).padStart(2, '0')
  return `${p(dt.getHours())}:${p(dt.getMinutes())}:${p(dt.getSeconds())}`
}

/** "12 s ago" / "4 min ago" — how old the data on screen is. */
export function formatAge(d, now = Date.now()) {
  if (!d) return ''
  const dt = d instanceof Date ? d : new Date(d)
  const s = Math.max(0, Math.round((now - dt.getTime()) / 1000))
  if (s < 5) return 'just now'
  if (s < 60) return `${s} s ago`
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  return `${Math.round(m / 60)} h ago`
}
