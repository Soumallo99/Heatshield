# Third-party code, data and services

HeatShield is MIT-licensed (see `LICENSE`). This file records the third-party
material that ships *inside* this repository or is fetched at runtime, with its
licence and what we do about attribution. It exists because the 3D globe
introduced vendored code and one NonCommercial-licensed upstream repository
that we deliberately did **not** take anything from.

Rule of thumb used here: **code is vendored, data is not.** Datasets with
NonCommercial or unclear terms are never copied into this repo; the app fetches
keyless services at runtime instead, and every one of them is credited below
and in the UI.

---

## Vendored code

### gods-eye-view — MIT

- Upstream: <https://github.com/bilawalsidhu/gods-eye-view>
- Vendored snapshot commit: **`0d41b6be5490db1f10a171f238be75db4d4ec3b4`**
- Licence text: [`frontend/web/src/globe/LICENSE-gods-eye-view`](frontend/web/src/globe/LICENSE-gods-eye-view)
  (MIT © 2026 Bilawal Sidhu — retained in full, as the licence requires).
- Where: `frontend/web/src/globe/`
- What was taken (adapted, not copied wholesale):
  - `imagery.js` ← upstream `src/maps/imagery.js` (provider factories + credits)
  - `terrain.js` ← upstream `src/maps/terrain.js` (keyless terrain + fallback)
  - `registry.js` ← upstream `src/maps/registry.js` (source-graph validation, verbatim)
  - `credits.js` ← upstream `src/maps/credits.js` (static credit following the active source, verbatim)
  - `controller.js` ← upstream `src/maps/controller.js` (source lifetime, switch generations, two-stage fallback)
  - `viewer.js` ← upstream `src/app/viewer.js` (widget-less viewer bootstrap)
  - `sources.js` ← upstream `src/maps/catalog.js` + `src/maps/defaultSources.js` (reduced)
  - Each file carries a header naming the upstream file and the snapshot commit.
- What was **explicitly not taken** (licence carve-outs):
  - `src/data/local_data/**` — TeleGeography submarine cables (**CC BY-NC-SA**) and
    Bhote Koshi (**CC BY-NC**). NonCommercial: incompatible with this project's MIT
    distribution, so the directory is not vendored and nothing from it is used.
  - `public/models/**` — bundled 3D models with per-model licences.
  - The Google Photorealistic 3D Tiles / Cesium ion code paths — both require
    credentials, and HeatShield's zero-key clone-and-run invariant wins over
    having a second imagery provider.
  - Any bundled dataset from that repository. The globe's only runtime sources
    are the keyless services listed below.

### CesiumJS — Apache-2.0

- Upstream: <https://github.com/CesiumGS/cesium> · <https://cesium.com>
- Dependency: `cesium` in `frontend/web/package.json` (pinned range `^1.145.0`),
  bundled into the lazy `cesium-*.js` chunk.
- Its runtime assets (`Workers/`, `Assets/`, `ThirdParty/`, `Widgets/`) are
  copied from `node_modules` into `frontend/web/public/cesium/` at build time by
  `frontend/web/scripts/copy-cesium-assets.mjs`; that directory is gitignored, so
  no third-party build output is committed.
- Attribution requirement: CesiumJS renders its own credit line. HeatShield
  keeps it visible — `#cesium-credits` (`.globe-credits`) is part of the globe UI
  and is never hidden behind the other overlays.

### Leaflet + react-leaflet — BSD-2-Clause / MIT

The 2D map (`leaflet`, `react-leaflet`, `@types/leaflet`) keeps its own
attribution control on screen; every basemap entry in
`frontend/web/src/basemaps.js` carries its provider's credit string.

---

### UTCI polynomial coefficient table — Apache-2.0 (reference implementation)

- Method: Bröde, P.; Fiala, D.; Błażejczyk, K.; Holmér, I.; Jendritzky, G.;
  Kampmann, B.; Tinz, B.; Havenith, G. (2012), *Deriving the operational
  procedure for the Universal Thermal Climate Index (UTCI)*, International
  Journal of Biometeorology 56(3):481–494, doi:10.1007/s00484-011-0454-1.
  The coefficients are the published table in that paper's Electronic
  Supplementary Material 3 (open access).
- Where: `core/utci.py` → `UTCI_POLYNOMIAL` (210 terms, total degree 6).
- How the table was produced: transcribed from the Apache-2.0 reference
  implementation **ECMWF [thermofeel](https://github.com/ecmwf-projects/thermofeel)**
  (`calculate_utci_polynomial`), extracted programmatically with an AST walk so
  no coefficient was retyped by hand.
- Verification: the vendored table agrees with `thermofeel` to **~1e-12 °C**
  across 4,000 random points spanning the published validity envelope, and
  `tests/test_utci.py` pins five reference values plus the index's defining
  property (UTCI equals air temperature at the reference condition).
- `thermofeel` is **not** a dependency of HeatShield. The table is vendored
  (Apache-2.0 permits it, with attribution here) so that `pip install -r
  requirements.txt` remains the only setup step — the same reason every other
  constant in the pipeline is in-repo.
- Licence text: Apache License 2.0 — <https://www.apache.org/licenses/LICENSE-2.0>.
  The ECMWF copyright notice is retained above the table in `core/utci.py`.

### ISO 7726 globe → mean radiant temperature

- Standard: ISO 7726:1998, *Ergonomics of the thermal environment — Instruments
  for measuring physical quantities* (black-globe thermometer conversion).
- Where: `core/utci.py` → `mean_radiant_temperature()`. A standard formula, not
  vendored code; recorded here so the provenance of the UTCI radiant input is
  as citable as the polynomial itself.

## Runtime services (fetched, never bundled)

| Service | Used for | Terms | Attribution shown in-app |
|---|---|---|---|
| **Esri ArcGIS World Imagery** (`services.arcgisonline.com`, keyless) | 3D globe imagery + 2D "Satellite" | Esri Terms of Use; public World Imagery service, no key required at this endpoint — review terms before running at scale | "Powered by Esri — Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community" (the service's own `copyrightText` as of 2026-09-18; the imagery supplier was renamed Maxar → Vantor) (Cesium credit line + globe footer) |
| **Esri Canvas / Street / Reference services** (`server.arcgisonline.com`, keyless) | 2D "Dark", "Streets", label overlays | as above | the service's own `copyrightText`, rendered visibly on the map (verified against each `MapServer?f=json` on 2026-09-18): Dark Canvas + its labels → "Sources: Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community"; Streets → the long form naming USGS, Intermap, INCREMENT P, NRCan, Esri Japan, METI, Esri China (Hong Kong), Esri Korea, Esri (Thailand) and NGCC |
| **OpenStreetMap tiles** (`tile.openstreetmap.org`, keyless) | automatic fallback when Esri or another CDN fails | ODbL 1.0 + tile usage policy | "© OpenStreetMap contributors" |
| **OpenTopoMap** (keyless) | 2D "Terrain" basemap | CC-BY-SA 3.0 | "Map data: © OpenStreetMap contributors, SRTM · Map style: © OpenTopoMap (CC-BY-SA)" — the wording OpenTopoMap's own page asks for. Only the plain tile URL is used: the provider publishes no retina (`@2x`) variant, and requesting one would 404 on a high-DPI screen and silently degrade the layer |
| **Re:Earth / Mapterhorn quantized-mesh terrain** (`terrain.reearth.land`, keyless) | 3D globe terrain | CC BY 4.0 | globe footer; falls back to the WGS84 ellipsoid on failure |
| **Open-Meteo** | the forecast this whole platform is built on | CC-BY-4.0 (attribution + link) | cited on the dashboard and in `DATA.md` |
| **KMC ward boundaries** (OpenCity / datameet) | the 141 ward polygons | ODbL 1.0 | globe ward legend + `DATA.md` |
| **Census of India 2011 PCA** | populations, literacy, workers | Open Government Data | `DATA.md` |
| **data.gov.in / api.data.gov.in** (`core/datagov.py`) | optional — the demographic gaps `DATA.md` lists as absent, and observed weather for forecast verification | Open Government Data (requires an API key) | **Optional and never on the critical path.** With no `HS_DATAGOV_API_KEY` the adapter raises `NotConfiguredError` and the pipeline is unchanged. No dataset is wired by default and no resource id is fabricated — see `core/datagov.CATALOGUE`. |

Attribution is drawn, not implied: the 2D maps render the credit of the layer
actually on screen (bottom-right), and it follows the tiles when they degrade to
the OpenStreetMap fallback — the map never credits a provider it is not drawing.
The 3D globe uses Cesium's credit display for the same reason.

**Removed providers.** CARTO is no longer used anywhere. Since ~2026-08-28 its
keyless raster endpoints answer HTTP 200 with a watermark PNG reading "API KEY
REQUIRED" rather than failing, which is undetectable client-side (`tileerror`
never fires). All map layers now come from Esri + OpenTopoMap, with OSM as the
fallback. See `frontend/web/src/basemaps.js` for the full reasoning.

**No API key is required, or possible, anywhere in this project** — 2D or 3D.
There is no key slot to misconfigure: the globe's source catalogue contains only
keyless providers, and the viewer boots with `baseLayer: false` so Cesium's
default ion-hosted imagery (which *would* demand a token) is never requested.
