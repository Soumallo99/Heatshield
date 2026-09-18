"""Shared pytest fixtures.

`npm run build` is part of the test surface: the phone cold-open budget gate
measures real Vite output, and several assertions read what the build produced
(the service worker that ships, Cesium's runtime assets). Those assertions used
to depend on a *previous* build happening to exist — locally that is always true
and in CI it is never true, which is exactly how a green laptop run turns into a
red pipeline.

So the build happens once per session, here, and tests that need build output
ask for this fixture instead of reading `dist/` directly.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "web"


@pytest.fixture(scope="session")
def built_site() -> Path:
    """Run the real production build once and return `frontend/web/dist`.

    Always rebuilds: a stale `dist/` from a different commit would let these
    tests pass while the shipped artefact is wrong — the same class of mistake
    the service-worker cache-bump rule exists to prevent.
    """
    result = subprocess.run(
        ["npm", "run", "build"], cwd=WEB, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, f"npm run build failed\n{result.stdout}\n{result.stderr}"
    dist = WEB / "dist"
    assert (dist / "index.html").exists(), "vite reported success but dist/index.html is missing"
    return dist
