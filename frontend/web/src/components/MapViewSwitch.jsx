/**
 * 2D / 3D switch for the operations map panel, shared by the Kolkata ward
 * console and the Delhi NCR zone console.
 *
 * The 2D Leaflet map is the default on purpose: it is the instantly-available
 * view (no WebGL, no CesiumJS download, works offline and on low-end devices).
 * The 3D globe is opt-in and lazy — choosing it is what triggers the globe
 * chunk. The tooltips state that trade-off rather than just naming the views.
 */
export default function MapViewSwitch({ value, onChange, disabled = false, note = '' }) {
  const options = [
    ['2d', '2D map', 'Instant Leaflet map — offline-capable, no WebGL or extra download'],
    ['3d', '3D globe', 'Photorealistic CesiumJS globe — lazy-loaded when you pick it, keyless imagery'],
  ]
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div
        className="flex gap-1 rounded-full border border-white/10 bg-white/[.04] p-1"
        role="group"
        aria-label="Map view"
      >
        {options.map(([id, label, title]) => (
          <button
            key={id}
            type="button"
            onClick={() => onChange(id)}
            aria-pressed={value === id}
            disabled={disabled && id === '3d'}
            title={disabled && id === '3d' ? 'Waiting for ward boundaries…' : title}
            className={`relative rounded-full px-3 py-1 text-[11px] transition ${
              value === id ? 'bg-white/[.14] text-white' : 'text-white/45 hover:text-white/80'
            } ${disabled && id === '3d' ? 'cursor-not-allowed opacity-40' : ''}`}
          >
            {label}
          </button>
        ))}
      </div>
      {note && <span className="text-[10px] text-white/35">{note}</span>}
    </div>
  )
}
