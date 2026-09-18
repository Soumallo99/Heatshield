# `src/globe/` — the 3D globe view

The operations dashboard's photorealistic globe, built on CesiumJS. It is
**lazy**, **keyless** and **optional**: the 2D Leaflet map stays the default and
the instant view, and the citizen phone app never loads any of this.

## Provenance

The provider/source architecture is adapted from
[gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view) (MIT © 2026
Bilawal Sidhu), snapshotted at commit **`0d41b6be5490db1f10a171f238be75db4d4ec3b4`**.

- Licence text is kept verbatim in [`LICENSE-gods-eye-view`](./LICENSE-gods-eye-view).
- Every derived file carries a header naming its upstream file.
- Repository-level attribution lives in [`THIRD-PARTY.md`](../../../../THIRD-PARTY.md).
- **Only code was taken.** The upstream `src/data/local_data/` directory
  (TeleGeography CC BY-NC-SA, Bhote Koshi CC BY-NC) and `public/models/` are not
  vendored, and nothing here reads them. HeatShield's runtime sources are the
  keyless ones listed in the file headers: Esri World Imagery, OSM tiles,
  Re:Earth/Mapterhorn terrain.

## Files

| File | Role |
|---|---|
| `HeatGlobe.jsx` | the React component (HUD, legend, notices, picking) |
| `scene.js` | viewer + controller + `CESIUM_BASE_URL` wiring, camera presets |
| `viewer.js` | widget-less keyless viewer bootstrap (`baseLayer: false`) + WebGL probe |
| `controller.js` | `GlobeSourceController`: source lifetime, switch generations, two-stage fallback |
| `sources.js` / `imagery.js` / `terrain.js` | the keyless catalogue and provider factories |
| `registry.js` / `credits.js` | source-graph validation; credit line that follows the on-screen source |
| `heatLayers.js` | HeatShield's own layers: ward choropleth, zone markers, picking |
| `globe.css` | globe chrome (imported lazily with the chunk) |

## The three guarantees

1. **Keyless.** `sources.js` contains exactly two stacks, both credential-free.
   The viewer boots with `baseLayer: false`, so Cesium's token-hungry default
   imagery is never constructed. There is no key slot anywhere in this
   directory — enforced by `tests/test_globe_view.py` (and the repo-wide
   no-`key=`/`apikey` scan in `tests/test_demo_app.py`).
2. **Degrading loudly, never silently.** Esri failure → OSM tiles with an
   on-map notice. Terrain failure → smooth ellipsoid with an on-map notice.
   No WebGL → the component says so and the 2D map is still there.
3. **Never in the phone cold-open.** CesiumJS is ~1.1 MB gzipped. It lives in
   its own chunk, reached only through `lazy(() => import('../globe/HeatGlobe'))`
   in `Dashboard.jsx` / `DelhiOps.jsx`, and `scripts/check_phone_budget.mjs`
   fails the build if `cesium`/`nosleep`/`protobuf` ever appear in the citizen
   boot set. The `citizen phone app stays 2D` rule is a gate, not a promise.

## Runtime assets

Every runtime asset path named by the built chunk is checked against the copied
directory (`tests/test_globe_view.py::test_built_globe_runtime_assets_resolve`),
because a missing worker is silent in a browser: terrain simply never loads.

`public/cesium/` (Workers, Assets, ThirdParty, Widgets) is copied out of
`node_modules/cesium` by `frontend/web/scripts/copy-cesium-assets.mjs`, wired to
`npm run predev` / `npm run prebuild`. It is gitignored: ~7 MB of third-party
build output, reproducible from the pinned dependency. `scene.js` points
CesiumJS at it with a scope-relative `window.CESIUM_BASE_URL`, so a GitHub Pages
subdirectory deployment (`/Heatshield/`) resolves it correctly.
