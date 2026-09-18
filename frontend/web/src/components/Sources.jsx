/* Where every number on this site comes from — and what is deliberately absent.
 *
 * This is a content component, not a decorative one. The project's claim is that
 * it does not invent data, and the only way a visitor can check that is to see
 * the sources named. It also carries the licence/attribution obligations we
 * actually have: OpenStreetMap (ODbL), OpenTopoMap (CC BY-SA), Esri imagery,
 * CesiumJS (Apache-2.0) and the vendored gods-eye-view code (MIT).
 *
 * Rendered on the landing page (for visitors and crawlers) and linked from the
 * dashboard footer.
 */

const SOURCES = [
  {
    id: 'weather',
    role: 'Weather, air quality, solar radiation',
    title: 'Open-Meteo',
    href: 'https://open-meteo.com',
    licence: 'Free, keyless — no API key is used anywhere in this project',
    detail:
      'Forecast and archive endpoints for temperature, humidity, wind, radiation and PM2.5 across the ward grid. Estimated human thermal stress (WBGT) is computed from these inputs; it is an estimate, not a measurement.',
  },
  {
    id: 'census',
    role: 'Population, ward geography',
    title: 'Census of India 2011 · Kolkata Municipal Corporation',
    href: 'https://censusindia.gov.in',
    licence: 'Government of India open data',
    detail:
      'Ward populations, household counts and KMC ward boundaries. Where a ward-level statistic does not exist in the census (physiological vulnerability, for example), the interface reports the gap instead of estimating it.',
  },
  {
    id: 'basemaps',
    role: 'Map tiles',
    title: 'Esri World Imagery · OpenStreetMap · OpenTopoMap',
    href: 'https://www.openstreetmap.org/copyright',
    licence: 'OSM data © OpenStreetMap contributors (ODbL) · OpenTopoMap (CC BY-SA) · Esri World Imagery',
    detail:
      'Dark, street, satellite and terrain basemaps, all keyless. If a tile provider is unreachable the map falls back to OpenStreetMap and says so on the map.',
  },
  {
    id: 'terrain',
    role: '3D terrain',
    title: 'Re:Earth / Mapterhorn quantized-mesh terrain',
    href: 'https://terrain.reearth.land',
    licence: 'CC BY 4.0',
    detail:
      'Elevation for the operations globe. If terrain cannot load, the globe degrades to a smooth ellipsoid and announces it rather than pretending the surface is flat ground.',
  },
  {
    id: 'live-tracking',
    role: 'Live tracking layers on the operations globe (optional)',
    title: 'adsb.lol · USGS · CelesTrak',
    href: 'https://celestrak.org/NORAD/documentation/gp-data-formats.php',
    licence: 'Public feeds, keyless — fetched by the HeatShield API, never by your browser',
    detail:
      'The 3D globe can overlay live aircraft (adsb.lol ADS-B), earthquakes (USGS) and satellite orbits (CelesTrak element sets, propagated in the browser with satellite.js). All three are off until you turn one on, none of them feeds a heat number, and an upstream that does not answer is reported as unavailable rather than filled in.',
  },
  {
    id: 'software',
    role: 'Software this site is built on',
    title: 'CesiumJS · Leaflet · React · gods-eye-view · satellite.js',
    href: 'https://github.com/Soumallo99/Heatshield/blob/main/THIRD-PARTY.md',
    licence: 'Apache-2.0 (CesiumJS) · BSD-2-Clause (Leaflet) · MIT (React) · MIT (gods-eye-view, pinned snapshot) · MIT (satellite.js)',
    detail:
      'The 3D globe’s provider architecture is adapted from gods-eye-view (MIT); the licence text, the pinned commit and the exact carve-outs are listed in THIRD-PARTY.md in the repository. Satellite orbits are propagated with satellite.js (MIT), whose WebAssembly build is deliberately not shipped.',
  },
]

export default function Sources() {
  return (
    <section id="sources" aria-labelledby="sources-heading" className="mx-auto mt-32 max-w-[1200px] px-6">
      <div className="eyebrow">sources &amp; licensing</div>
      <h2 id="sources-heading" className="display mt-2 text-[clamp(1.7rem,3.2vw,2.6rem)]">
        Every number here is attributable
      </h2>
      <p className="mt-4 max-w-[68ch] text-[13px] leading-relaxed text-white/50">
        HeatShield is a decision-support prototype. It is not an official warning service and it
        does not issue government advisories. Figures are forecast-derived estimates carrying the
        timestamp the interface shows; the synthetic demo is labelled as synthetic wherever it
        appears. Where a source does not publish a number, the interface says so rather than
        filling the gap.
      </p>

      <ul className="mt-10 grid gap-5 md:grid-cols-2">
        {SOURCES.map((source) => (
          <li key={source.id} className="panel p-6">
            <div className="eyebrow">{source.role}</div>
            <h3 className="mt-2 text-[16px] font-medium text-white/90">
              <a
                href={source.href}
                className="underline decoration-white/20 underline-offset-4 transition hover:decoration-white/60"
                rel="noopener noreferrer"
                target="_blank"
              >
                {source.title}
              </a>
            </h3>
            <p className="mt-2 text-[12px] leading-relaxed text-white/62">{source.detail}</p>
            <p className="mt-3 text-[11px] text-white/58">{source.licence}</p>
          </li>
        ))}
      </ul>

      <p className="mt-6 text-[11.5px] leading-relaxed text-white/59">
        Imagery and type: this site ships no photographs and no third-party fonts beyond Google
        Fonts’ open-licensed families, which have complete local fallbacks. The share card is drawn
        by a script in this repository (<code>scripts/make_social_card.py</code>), so it carries no
        licence obligation. Nothing here is licensed for commercial redistribution of the
        underlying datasets beyond the terms above.
      </p>
    </section>
  )
}
