/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        display: ['"Instrument Serif"', 'Iowan Old Style', 'Palatino Linotype', 'Georgia', 'serif'],
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        ink: { 950: '#07080d', 900: '#0a0c14', 800: '#11141f', 700: '#1a1f2e' },
        risk: { normal: '#22c55e', caution: '#eab308', danger: '#f97316', critical: '#ef4444', extreme: '#a21caf' },
      },
      letterSpacing: { tightest: '-0.045em' },
    },
  },
  plugins: [],
}
