"""
Guards the basemap layer against the two ways it has already broken.

1. TILE_HOSTS is declared twice — once in src/basemaps.js (ES module, used by
   the app) and once in public/sw.js (a service worker, which cannot import an
   ES module). If they drift, tiles from the new provider silently stop being
   cached offline and nothing errors.

2. CARTO must not be a *default* basemap. Around 28 Aug 2026 CARTO began
   watermarking keyless tile requests with "API KEY REQUIRED". Crucially those
   requests still return HTTP 200 image/png, so no test that only checks for a
   failed request would ever catch it — the map just renders defaced. CARTO is
   allowed only inside a `if (CARTO_KEY)` branch.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASEMAPS = ROOT / "frontend" / "web" / "src" / "basemaps.js"
SW = ROOT / "frontend" / "web" / "public" / "sw.js"


def _tile_hosts(path: Path) -> set[str]:
    """Pull the string entries out of that file's TILE_HOSTS array."""
    src = path.read_text(encoding="utf-8")
    m = re.search(r"TILE_HOSTS\s*=\s*\[(.*?)\]", src, re.S)
    assert m, f"TILE_HOSTS array not found in {path.name}"
    return set(re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)))


def test_tile_host_lists_match() -> None:
    """The app and the service worker must agree on which hosts serve tiles."""
    app_hosts = _tile_hosts(BASEMAPS)
    sw_hosts = _tile_hosts(SW)
    assert app_hosts, "basemaps.js declares no tile hosts"
    assert app_hosts == sw_hosts, (
        "TILE_HOSTS drifted between basemaps.js and sw.js.\n"
        f"  only in basemaps.js: {sorted(app_hosts - sw_hosts)}\n"
        f"  only in sw.js:       {sorted(sw_hosts - app_hosts)}\n"
        "Tiles from a host missing in sw.js are never cached for offline use."
    )


def _strip_comments(src: str) -> str:
    """Drop /* */ and // comments so documentation prose can't trip a check."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def test_every_basemap_url_host_is_cached() -> None:
    """Any tile URL the registry can emit must be covered by TILE_HOSTS."""
    # Comments reference carto.com/basemaps/apikey, which is a signup page and
    # not a tile host — strip prose before scanning.
    src = _strip_comments(BASEMAPS.read_text(encoding="utf-8"))
    hosts = _tile_hosts(BASEMAPS)
    # Hosts appearing in template literals, ignoring the {s} subdomain slot.
    used = set(re.findall(r"https://(?:\{s\}\.)?([a-z0-9.-]+\.[a-z]{2,})/", src))
    # ESRI_BASE is built from a constant, so its host shows up here too.
    uncovered = {h for h in used if h not in hosts}
    assert not uncovered, (
        f"tile hosts used but not in TILE_HOSTS (so never cached): {sorted(uncovered)}"
    )


def test_carto_is_not_a_default_basemap() -> None:
    """
    CARTO watermarks keyless tiles. It may only be referenced behind a key
    check, never as a default layer.
    """
    code = _strip_comments(BASEMAPS.read_text(encoding="utf-8"))

    # The TILE_HOSTS array legitimately names cartocdn (so keyed CARTO tiles
    # are still cached offline); it builds no URL. Exclude it before scanning.
    code = re.sub(r"TILE_HOSTS\s*=\s*\[.*?\]", "TILE_HOSTS = []", code, flags=re.S)

    for line in code.splitlines():
        if "cartocdn.com" not in line:
            continue
        assert "CARTO_KEY" in line, (
            "A cartocdn.com tile URL is built without interpolating CARTO_KEY:\n"
            f"  {line.strip()}\n"
            "Keyless CARTO tiles return HTTP 200 with an 'API KEY REQUIRED' "
            "watermark burned in, so this fails silently in the browser."
        )

    # The keyless block must not define CARTO at all.
    keyless = re.search(r"const keyless\s*=\s*\{(.*?)\n\}", code, re.S)
    assert keyless, "could not locate the `keyless` basemap block"
    assert "cartocdn" not in keyless.group(1), (
        "CARTO appears in the `keyless` basemap set — it is not keyless anymore."
    )


@pytest.mark.parametrize("field", ["url", "attribution"])
def test_keyless_basemaps_declare_required_fields(field: str) -> None:
    """
    Every keyless style needs a URL and visible attribution: OSM (ODbL), Esri
    and OpenTopoMap all require credit as a condition of free use.
    """
    code = BASEMAPS.read_text(encoding="utf-8")
    keyless = re.search(r"const keyless\s*=\s*\{(.*?)\n\}", code, re.S)
    assert keyless
    body = keyless.group(1)
    # Four styles ship keyless: dark, streets, satellite, terrain.
    ids = re.findall(r"^\s{2}(\w+):\s*\{", body, re.M)
    assert set(ids) == {"dark", "streets", "satellite", "terrain"}, ids
    assert body.count(f"{field}:") >= len(ids), (
        f"not every keyless basemap declares `{field}`"
    )
