/**
 * The only place in the app allowed to touch `console`.
 *
 * Two jobs, both of which the earlier scattered `console.error(...)` calls did
 * badly:
 *
 *  1. **No debug logging in a production bundle.** A citizen opening this on a
 *     phone should see a clean console; advisory chatter in the console of a
 *     public-warning site reads as breakage. Verbose output is therefore gated
 *     on `import.meta.env.DEV`, which Vite replaces with `false` at build time
 *     so the call and its arguments are dropped by the minifier.
 *
 *  2. **A real place for errors to go.** Something does eventually fail on a
 *     user's phone, and "nothing was logged anywhere" is not an answer. Set
 *     `VITE_ERROR_REPORT_URL` at build time and every reported error is sent
 *     there as JSON (beacon first, so a page that is being closed still gets the
 *     report out); leave it unset and reports are kept in a small in-memory ring
 *     buffer that is readable in the console as `__HS_ERRORS__` on the device
 *     showing the problem. Both paths are failures of a network call, never a
 *     throw — reporting must not be able to break the app it reports on.
 *
 * Nothing here writes cookies or storage, so it adds no consent surface. The
 * payload is deliberately small and contains no personal data: message, stack,
 * route, and the build's own version string.
 */

const REPORT_URL = import.meta.env?.VITE_ERROR_REPORT_URL || ''
const KEEP = 25

/** Ring buffer of what went wrong on this device, newest first. */
export const errorLog = []

function entry(scope, error, extra) {
  return {
    at: new Date().toISOString(),
    scope,
    message: String(error?.message ?? error ?? 'unknown error'),
    stack: typeof error?.stack === 'string' ? error.stack.split('\n').slice(0, 6).join('\n') : null,
    route: typeof window === 'undefined' ? null : window.location.hash || '/',
    ...extra,
  }
}

/**
 * Dev-only diagnostic line.
 *
 * `import.meta.env.DEV` is substituted with the literal `false` by Vite at
 * build time, so this whole branch is dead code in a production bundle — the
 * minifier removes the call and its arguments rather than leaving a `console`
 * reference behind. (Wrapping the flag in a `const` first defeats that: the
 * minifier folds `if (false)`, not `if (FLAG)`.)
 */
export function warn(message, ...rest) {
  if (import.meta.env.DEV) console.warn(`[HeatShield] ${message}`, ...rest)
}

/**
 * Record a failure. Never throws, never blocks, safe to call from a render
 * error boundary or a WebGL context-loss handler.
 *
 * @param {string} scope  short subsystem tag: 'ui' | 'globe' | 'terrain' | 'sw'
 * @param {unknown} error the thrown value (Error preferred)
 * @param {object} [extra] small, non-personal context (component stack, url)
 */
export function reportError(scope, error, extra = {}) {
  const record = entry(scope, error, extra)

  errorLog.unshift(record)
  if (errorLog.length > KEEP) errorLog.pop()

  if (import.meta.env.DEV) {
    console.error(`[HeatShield ${scope}]`, error, extra)
  } else if (typeof window !== 'undefined') {
    // Handle for on-device inspection: open the console on the phone that is
    // misbehaving and read `__HS_ERRORS__`. Cheap, and needs no server.
    try {
      window.__HS_ERRORS__ = errorLog
    } catch {
      /* frozen window object — ignore */
    }
  }

  if (!REPORT_URL || typeof navigator === 'undefined') return
  try {
    const body = JSON.stringify(record)
    if (typeof navigator.sendBeacon === 'function') {
      navigator.sendBeacon(REPORT_URL, new Blob([body], { type: 'application/json' }))
    } else {
      fetch(REPORT_URL, { method: 'POST', body, headers: { 'Content-Type': 'application/json' }, keepalive: true })
        .catch(() => {})
    }
  } catch {
    /* reporting is best-effort by definition */
  }
}
