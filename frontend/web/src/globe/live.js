/**
 * The React half of the globe's live layers: `useLiveLayer`.
 *
 * Everything here is opt-in. A layer is fetched only while it is switched on,
 * stops the moment it is switched off, and is never fetched at all on a static
 * host (where the answer is known in advance: there is no API process). The
 * hook keeps no synthetic data — a failed refresh leaves the previous *real*
 * rows on screen and says how old they are, or shows the reason when there are
 * none.
 *
 * Polling is deliberately slow and deliberately back-off-y: these upstreams
 * are somebody else's free service, and an operator who walks away from an
 * open globe with the API stopped should not leave a six-second poll running
 * all afternoon.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { reportError } from '../log.js'
import { describeLiveFailure, fetchLiveLayer, refreshIntervalFor, staticHostNotice } from './liveData.js'

/** Consecutive failures before the retry slows down. */
const FAST_FAILURES = 3
/** …and how slow it gets. Long enough to notice a recovery, short enough to see one. */
const SLOW_RETRY_MS = 60000

/**
 * @param id       a layer id from `LIVE_LAYERS`, or null/'' for "off"
 * @param options  { enabled, params, intervalMs }
 *
 * @returns {{ status, payload, rows, notice, error, lastUpdated, refresh, unavailable }}
 *   status       'off' | 'loading' | 'ready' | 'unavailable'
 *   rows         the layer's rows, exactly as the API served them (satellites
 *                are still element sets — positions are a rendering concern,
 *                see `positionsFor` in ./liveData.js)
 */
export function useLiveLayer(id, { enabled = true, params = null, intervalMs = null } = {}) {
  const [status, setStatus] = useState('off')
  const [payload, setPayload] = useState(null)
  const [rows, setRows] = useState([])
  const [notice, setNotice] = useState(null)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [token, setToken] = useState(0)

  const paramsRef = useRef(params)
  paramsRef.current = params
  // A stable key for the params object: the effect must re-run when the value
  // changes, but not every time a caller rebuilds an identical object.
  const paramsKey = params ? JSON.stringify(params) : ''

  useEffect(() => {
    if (!id || !enabled) {
      setStatus('off')
      setPayload(null)
      setRows([])
      setNotice(null)
      setError(null)
      return undefined
    }

    // Asked before the first request, not after a failure: on GitHub Pages
    // there is no API, and a request that is going to 404 on every press is a
    // request this app should not make.
    const staticNotice = staticHostNotice()
    if (staticNotice) {
      setStatus('unavailable')
      setPayload(null)
      setRows([])
      setNotice(staticNotice)
      return undefined
    }

    let cancelled = false
    let timer = null
    let failures = 0

    const schedule = (ms) => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(run, ms)
    }

    async function run() {
      setStatus((current) => (current === 'ready' ? 'ready' : 'loading'))
      try {
        const next = await fetchLiveLayer(id, { params: paramsRef.current })
        if (cancelled) return
        setPayload(next)
        setNotice(next?.notice || null)
        if (next?.available === true) {
          setRows(Array.isArray(next.data) ? next.data : [])
          setError(null)
          setLastUpdated(new Date())
          setStatus('ready')
        } else {
          // The API answered and told us the upstream did not. Rows are
          // cleared: keeping the previous aircraft on screen while saying
          // "unavailable" is a contradiction the operator cannot resolve.
          setRows([])
          setStatus('unavailable')
        }
        failures = 0
      } catch (err) {
        if (cancelled || err?.name === 'AbortError') return
        reportError('globe-live-layer', err)
        setError(err)
        setRows([])
        setNotice(describeLiveFailure(err))
        setStatus('unavailable')
        failures += 1
      }
      if (cancelled) return
      schedule(failures >= FAST_FAILURES ? SLOW_RETRY_MS : (intervalMs ?? refreshIntervalFor(id)))
    }

    run()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
    // `paramsKey` stands in for `params`; `token` is the manual-refresh lever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, enabled, paramsKey, token, intervalMs])

  const refresh = useCallback(() => setToken((value) => value + 1), [])

  return {
    status,
    payload,
    rows,
    notice,
    error,
    lastUpdated,
    refresh,
    /** true when the layer is on but nothing real can be drawn */
    unavailable: status === 'unavailable',
    loading: status === 'loading',
  }
}
