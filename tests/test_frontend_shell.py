"""User-visible contracts of the frontend shell, checked in CI.

Three of these are regressions with a user report behind them:

* **The Citizen tab needed a reload before it would open.** Two causes, both
  checked here: the router did not mount the incoming page until the outgoing
  one had finished animating (`AnimatePresence mode="wait"`), and a failed chunk
  fetch had no retry and no recovery. The loader's own policy is unit-tested in
  `frontend/web/scripts/test-route-loading.mjs`, which runs in `npm test`; these
  assertions pin the wiring that makes the policy reachable from a tab press.
* **The service worker served `index.html` cache-first.** Every deploy changes
  the hashed chunk names, so a cached document kept asking for files that no
  longer exist — the same unopenable tab, from a different direction.
* **The 2D maps credited the wrong provider.** Each basemap string is the
  `copyrightText` of the service it names (checked against
  `<service>/MapServer?f=json` on 2026-09-18). The default basemap used to
  advertise Maxar/Earthstar imagery that appears nowhere in the Dark Gray Canvas,
  and the map's own attribution control was switched off with nothing drawn in
  its place — a licence term, not a cosmetic detail.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "web"


# ------------------------------------------------ the Citizen tab, and its causes


def test_route_chunks_are_loaded_through_the_retrying_loader():
    app = (WEB / "src" / "App.jsx").read_text(encoding="utf-8")
    assert app.count("loadChunk(") >= 6, "every route chunk must go through the loader"
    assert "ROUTE_CHUNK" in app, "the route→chunk map is what lets a press preload"


def test_a_tab_press_starts_the_download_before_the_route_changes():
    app = (WEB / "src" / "App.jsx").read_text(encoding="utf-8")
    assert "startRouteChunk(r)" in app
    # Order matters: the fetch overlaps the re-render instead of following it.
    assert app.index("startRouteChunk(r)") < app.index("window.location.hash = `#/${r}`")


def test_the_page_swap_does_not_wait_for_an_exit_animation():
    app = (WEB / "src" / "App.jsx").read_text(encoding="utf-8")
    assert "<AnimatePresence" not in app, (
        "mode=\"wait\" does not mount the next page until the last one has animated away, "
        "which delays the chunk request by the length of the animation"
    )


def test_the_loader_retries_and_recovers_once():
    """The JS policy is unit-tested in npm test; this proves the defaults exist."""
    source = (WEB / "src" / "lazyRoute.js").read_text(encoding="utf-8")
    assert "DEFAULT_ATTEMPTS = 2" in source
    assert "RELOAD_FLAG" in source and "recoverOnce" in source
    assert "hs-chunk-reload" in source
    # A reload loop is worse than an error card: the guard must refuse a second.
    assert "if (storage.getItem(RELOAD_FLAG) === name) return false" in source


def test_the_service_worker_serves_navigations_network_first():
    worker = (WEB / "public" / "sw.js").read_text(encoding="utf-8")
    assert "request.mode === 'navigate'" in worker, (
        "a cache-first index.html keeps pointing at chunk names the last deploy deleted"
    )
    # The shell strategy changed, so the cache name must have changed with it, or
    # an installed app keeps the old worker's caches.
    assert "heatshield-phone-v6" in worker
    assert "heatshield-phone-v5" not in worker


def _shipped_assets(index_html: str) -> list[str]:
    """`assets/<file>` paths named by the built document."""
    out = []
    for piece in index_html.split("assets/")[1:]:
        name = piece.split('"', 1)[0].split("'", 1)[0].strip()
        if name and "/" not in name:
            out.append("assets/" + name)
    return out


def _precached_shell(worker_js: str) -> list[str]:
    """`./name` entries in the worker's app-shell list."""
    out = []
    for piece in worker_js.split("'./")[1:]:
        name = piece.split("'", 1)[0].strip()
        if name and not name.endswith("/"):
            out.append("./" + name)
    return out


def _missing_build_refs(index_html: str, worker_js: str, dist: Path) -> list[str]:
    """Every path a deployed build points at but did not ship.

    Two documents do the pointing: `index.html` (the hashed chunks of one build)
    and `sw.js` (the app shell it precaches by name). A name that does not exist
    beside them is the failure the Citizen report came from — the page loads, and
    the tab that needs the missing file cannot open.
    """
    missing = [ref for ref in _shipped_assets(index_html) if not (dist / ref).exists()]
    missing += [name for name in _precached_shell(worker_js) if not (dist / name[2:]).exists()]
    return missing


def test_a_deployed_build_never_references_a_file_it_did_not_ship():
    """Run against the build CI would publish: it builds before it tests."""
    dist = WEB / "dist"
    if not (dist / "index.html").exists():
        pytest.skip("no build output in this checkout")

    index = (dist / "index.html").read_text(encoding="utf-8")
    worker = (dist / "sw.js").read_text(encoding="utf-8")

    # These counts keep the test from passing by finding nothing, which is how a
    # check silently stops checking.
    assert len(_shipped_assets(index)) >= 4, "index.html names no built assets"
    assert len(_precached_shell(worker)) >= 3, "sw.js precaches no app shell"

    assert _missing_build_refs(index, worker, dist) == []

    # Nothing dev-only may reach a browser: no Vite client, no React refresh.
    for asset in (dist / "assets").glob("*.js"):
        text = asset.read_text(encoding="utf-8", errors="ignore")
        assert "@vite/client" not in text and "react-refresh" not in text, asset.name
        assert "127.0.0.1" not in text and "localhost:" not in text, f"{asset.name} hardcodes a dev host"


def test_the_deploy_integrity_check_catches_a_missing_file():
    """Negative control: a check that cannot fail is not a check."""
    dist = WEB / "dist"
    if not dist.exists():
        pytest.skip("no build output in this checkout")
    # Names that cannot collide with a real build: this test must not touch one.
    index = '<script src="./assets/gone-abc123.js"></script><link href="./assets/present-xyz789.js">'
    worker = "const APP_SHELL = ['./present-xyz789.html', './deleted-abc123.html']"
    (dist / "assets" / "present-xyz789.js").write_text("ok", encoding="utf-8")
    (dist / "present-xyz789.html").write_text("ok", encoding="utf-8")
    try:
        missing = _missing_build_refs(index, worker, dist)
    finally:
        (dist / "assets" / "present-xyz789.js").unlink()
        (dist / "present-xyz789.html").unlink()
    assert "assets/gone-abc123.js" in missing
    assert "./deleted-abc123.html" in missing
    assert "assets/present-xyz789.js" not in missing
    assert "./present-xyz789.html" not in missing

def test_the_npm_test_script_runs_the_loader_tests():
    package = (WEB / "package.json").read_text(encoding="utf-8")
    assert "scripts/test-route-loading.mjs" in package


# ------------------------------------------------------------- map attribution


def test_each_basemap_credits_the_provider_it_actually_draws():
    source = (WEB / "src" / "basemaps.js").read_text(encoding="utf-8")

    # Canvas/World_Dark_Gray_Base + its Reference labels overlay.
    assert "Sources: Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community" in source
    # World_Street_Map: the service's own long copyrightText.
    for name in ("USGS", "Intermap", "INCREMENT P", "NRCan", "Esri Japan", "METI",
                 "Esri China (Hong Kong)", "Esri Korea", "Esri (Thailand)", "NGCC"):
        assert name in source, f"{name} is part of the World Street Map credit"
    # World_Imagery, and the labels drawn over it.
    assert "Imagery: Esri, Maxar, Earthstar Geographics, and the GIS User Community" in source
    assert "Labels: Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community" in source
    # OpenTopoMap requires both its own credit and OpenStreetMap's, in the
    # wording its page specifies ("Map data: © OpenStreetMap contributors, SRTM
    # | Map style: © OpenTopoMap (CC-BY-SA)").
    assert "Map data: ${OSM_ATTR}, SRTM · Map style: © OpenTopoMap (CC-BY-SA)" in source

    # …and only the plain tile URL: the provider publishes no retina variant, so
    # a `@2x` request (which Leaflet builds from `{r}` on a high-DPI screen) would
    # 404, trip the tile-failure counter and silently degrade the layer.
    terrain_url = next(
        line for line in source.split("id: 'terrain'", 1)[1].splitlines() if "url:" in line
    )
    assert "@2x" not in terrain_url and "{r}" not in terrain_url

    # The wrong-credit regression, stated directly: the default basemap must not
    # advertise imagery it does not contain.
    dark_block = source.split("id: 'dark'", 1)[1].split("id: 'streets'", 1)[0]
    assert "Maxar" not in dark_block, "the dark canvas draws no Maxar imagery"


def test_the_map_shows_the_credit_of_the_layer_on_screen():
    risk_map = (WEB / "src" / "components" / "RiskMap.jsx").read_text(encoding="utf-8")
    # Leaflet's control is off here (attributionControl={false}), so the credit
    # is rendered by the app and follows the effective — possibly degraded — layer.
    assert 'role="note"' in risk_map
    assert "{effectiveBasemap.attribution}" in risk_map
    assert "OSM_FALLBACK" in risk_map, "the fallback's own credit must reach the same element"

    demo_map = (WEB / "src" / "demo" / "DemoMap.jsx").read_text(encoding="utf-8")
    assert "<AttributionControl" in demo_map
    assert "tilesDegraded ? OSM_FALLBACK.attribution : dark.attribution" in demo_map


def test_the_worker_caches_the_same_tile_hosts_the_maps_request():
    """Drift guard: a tile host the app uses but the worker does not cache means
    every visit re-downloads it, and one the worker caches but nobody requests is
    dead weight. The 3D globe's host was missing from the worker's list."""
    registry = (WEB / "src" / "basemaps.js").read_text(encoding="utf-8") + (
        WEB / "src" / "globe" / "imagery.js"
    ).read_text(encoding="utf-8")
    worker = (WEB / "public" / "sw.js").read_text(encoding="utf-8")
    listed = re.findall(r"'([a-z0-9.\-]+)'", worker.split("const TILE_HOSTS = [", 1)[1].split("]", 1)[0])

    # Every host the two registries can build a URL for, including Leaflet's
    # '{s}.' subdomain form, has to be in the worker's list. This is the check
    # that catches a host going missing; the length floor below keeps the scan
    # itself from going vacuous.
    used = set(re.findall(r"https://(?:\{s\}\.)?([a-z0-9.\-]+)/", registry))
    used = {host for host in used if host not in {"www.esri.com", "github.com"}}
    assert used, "no tile hosts found in the registries — the check would be vacuous"
    for host in sorted(used):
        assert host in listed, f"{host} is requested by the app but never cached on the device"

    assert len(listed) >= 4, f"TILE_HOSTS looks truncated: {listed}"
    for host in listed:
        assert host in registry, f"{host} is cached by the worker but nothing requests it"


@pytest.mark.parametrize("provider", ["cartocdn", "maptiler", "thunderforest", "?key=", "apikey"])
def test_no_keyed_or_watermarking_tile_provider_returns(provider):
    """The CARTO lesson: a tile that answers 200 with a watermark is undetectable."""
    for name in ("src/basemaps.js", "src/components/RiskMap.jsx", "src/demo/DemoMap.jsx"):
        assert provider not in (WEB / name).read_text(encoding="utf-8").lower(), name


# ---------------------------------------------- service worker upgrade path


def test_a_waiting_worker_is_promoted_and_the_page_refreshes_once():
    main = (WEB / "src" / "main.jsx").read_text(encoding="utf-8")
    assert "updatefound" in main, "a worker that installs after load must not sit waiting forever"
    assert "SKIP_WAITING" in main
    assert "controllerchange" in main
    # A first visit has no controller; clients.claim() fires controllerchange
    # then, and reloading on it would bounce every new visitor's first page.
    assert "wasControlled" in main
    # One refresh per page load, never a loop.
    assert "if (refreshed || !wasControlled) return" in main
