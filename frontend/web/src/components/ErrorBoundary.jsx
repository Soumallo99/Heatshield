import { Component } from 'react'
import { motion } from 'framer-motion'
import { EASE } from '../motion'
import { reportError } from '../log'

/**
 * Without this, one thrown error anywhere in the tree unmounts the whole app and
 * leaves a black page — the worst possible failure mode during a live demo.
 * Catches render errors, shows the message, and offers a reload.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidMount() {
    // A healthy mount re-arms the one-shot auto-reload below.
    try {
      sessionStorage.removeItem('hs-autoreload')
    } catch {
      /* storage unavailable — fine */
    }
  }

  componentDidCatch(error, info) {
    // One seam for every client failure: dev console, on-device ring buffer,
    // or the operator's VITE_ERROR_REPORT_URL. See src/log.js.
    reportError('ui', error, { componentStack: info?.componentStack?.split('\n').slice(0, 4).join('\n') })

    // A page left open across a dev-server restart can end up with two React
    // copies in one tab; hooks then run through a dispatcher that was never
    // attached and throw "Cannot read properties of null (reading 'useState')".
    // The only cure is a reload, so do it once, unattended, instead of making
    // the user stare at a runtime card. The sessionStorage flag keeps a truly
    // broken build from reload-looping.
    if (error && /Cannot read properties of null \(reading 'use\w+'\)/.test(String(error.message))) {
      try {
        if (!sessionStorage.getItem('hs-autoreload')) {
          sessionStorage.setItem('hs-autoreload', '1')
          window.location.reload()
        }
      } catch {
        /* ignore */
      }
    }
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="flex min-h-screen items-center justify-center p-8">
        <motion.div
          className="panel max-w-[520px] p-8"
          initial={{ opacity: 0, y: 20, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.6, ease: EASE }}
        >
          <div className="eyebrow text-red-400">runtime error</div>
          <h1 className="display mt-3 text-[28px]">Something stopped rendering</h1>
          <pre className="mt-4 overflow-auto rounded-lg border border-white/10 bg-black/40 p-3 text-[11px] leading-relaxed text-white/60">
            {String(this.state.error?.message || this.state.error)}
          </pre>
          <button
            onClick={() => window.location.reload()}
            className="mt-5 rounded-full border border-white/20 bg-white/[.06] px-5 py-2 text-[12px] transition hover:border-white/40"
          >
            Reload
          </button>
        </motion.div>
      </div>
    )
  }
}
