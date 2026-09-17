# HeatShield UI Spec (decided 2026-09-01)

Locked decisions — do not relitigate at Phase 4, build to this.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Framework | **Vite + React 18** | Fast HMR, no SSR overhead we'd pay for |
| Animation | **Framer Motion** | Spring physics, `AnimatePresence` exits, layout animations |
| Styling | **Tailwind CSS** | Rapid, no CSS-file drift during a hackathon |
| Map | **react-leaflet, 4 switchable keyless basemaps** (CARTO Dark/Voyager, Esri imagery + labels, OpenTopoMap) | Real ward polygons at z9–z20 with @2x tiles, ward search, geolocation, scale bar and fullscreen; Folium is Python-only and can't animate. Optional `VITE_MAPTILER_KEY` upgrades tile detail with no code change |
| Charts | **Recharts** (or hand-rolled SVG for the hero curve) | Recharts for standard, custom SVG where we animate path-draw |
| Backend | **FastAPI, unchanged** | Already serves clean JSON — it is the contract |

**Streamlit/Gradio dropped.** Streamlit re-runs the whole script per interaction and gives no DOM
control; heavy animation is exactly its weak spot. No backend rework is required by this swap.

## Routes

1. `/` — **Landing / impact page**
   - Animated heat-field background (3 blurred blobs, `mix-blend-mode:screen`)
   - Shimmer gradient headline, staggered `riseIn` entrance
   - Count-up KPIs (peak WBGT, population at risk, wards on alert)
   - Scroll-triggered "how it works" timeline, scroll-linked progress rail
   - Live global ticker of current alerts
2. `/dashboard` — **Ops console** (the main deliverable)
   - Ward risk map (choropleth by risk score, pulsing halos on Critical)
   - Radar sweep overlay
   - Risk gauge with spring needle + animated arc
   - 24 h WBGT/HI curve with path-draw animation
   - Ward strip (click to select → all panels animate to that ward)
   - Alert panel with marching-stripes banner + dispatched-SMS log
3. `/mobile/:wardId` — **Citizen view** (the link an SMS opens)
   - Single risk number, colour, plain-language guidance, work/rest rule

## Code-source data contracts (all live)

```
GET /zones                       ward registry + demographics
GET /thermal?hours=&ward_id=     hourly WBGT / HI / band
GET /thermal/daily               daily peaks + IMD heatwave flags
GET /thermal/ward/{id}           ward summary: peak, band, guidance, work/rest
GET /forecast/daily              daily Tmax/Tmin/RH
```
Colours come from the API (`stress_colour`), so bands can never drift out of sync
between backend and UI.

## Animation inventory

| Effect | Technique |
|---|---|
| Heat-field background | blurred blobs, 26/32/38 s drift loops |
| Radar sweep | rotating `conic-gradient`, masked |
| Risk halos | SVG `r` + opacity, staggered |
| KPI count-ups | `rAF` cubic-ease, 90 ms stagger |
| Gauge | `stroke-dashoffset` + spring needle |
| Charts | `stroke-dasharray` path draw + area fade |
| Panels | `AnimatePresence` cross-fade on ward select |
| Alert banner | marching 135° stripes |
| Cards | hover lift + sheen sweep |

Reference implementation of every effect above: `frontend/prototype.html`
(self-contained, no build, ~25 KB — open it to see the intended motion language).

## Non-negotiables

- **Accessibility:** honour `prefers-reduced-motion` — kill all animation, keep state changes.
- **Perf budget:** max 3 simultaneously blurred elements (blur is the #1 fps killer);
  target 60 fps on a mid-range laptop; animate `transform`/`opacity` only, never `top`/`left`.
- **Sandbox constraint:** the in-app preview iframe has no network, so the dev server must bind
  `0.0.0.0` and the app must call FastAPI via **relative URLs** proxied by Vite
  (`server.proxy: { '/api': 'http://localhost:8000' }`) — never `localhost` from browser code.
- Colour-blind safety: bands carry an icon/text label, not colour alone.
