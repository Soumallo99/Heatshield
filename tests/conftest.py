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

import atexit
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "web"

# The API is configured from the environment at import time, and two of those
# settings decide how the suite behaves:
#
#   * HS_ADMIN_TOKEN — the administrative routes (registry, dispatch) are
#     disabled without one. The suite configures the token the way an operator
#     would, and the security tests assert what happens when it is missing.
#   * HS_RATE_LIMIT_PER_MIN=0 — a limiter that counts every request would turn
#     the suite's own request volume into 429s. The limiter itself is exercised
#     directly (tests/test_security.py) rather than by accident here.
#   * HS_ALERT_LOG — the dispatch routes append every send to this file, and the
#     sweep in tests/test_route_smoke.py posts to them. Pointing it at a
#     throwaway directory is the difference between a test run and a test run
#     that quietly rewrites `data/processed/alert_log.csv`, which is exactly what
#     happened before this line existed.
ADMIN_TOKEN = "test-admin-token"
os.environ.setdefault("HS_ADMIN_TOKEN", ADMIN_TOKEN)
os.environ.setdefault("HS_RATE_LIMIT_PER_MIN", "0")

_TEST_SCRATCH = Path(tempfile.mkdtemp(prefix="heatshield-tests-"))
os.environ.setdefault("HS_ALERT_LOG", str(_TEST_SCRATCH / "alert_log.csv"))
atexit.register(shutil.rmtree, _TEST_SCRATCH, ignore_errors=True)


@pytest.fixture(scope="session")
def admin_headers() -> dict[str, str]:
    """Headers a real operator would send to the administrative routes."""
    return {"X-API-Key": ADMIN_TOKEN}


def _build() -> subprocess.CompletedProcess[str]:
    """`npm run build`, with headroom and one retry.

    CesiumJS makes this a ~4 MB bundle from a ~23 MB dependency tree; on a
    memory-constrained runner that is the step that fails, and it fails
    intermittently. A retry is honest here — a systematic failure fails both
    attempts and the full output is reported.
    """
    environment = {**os.environ, "NODE_OPTIONS": "--max-old-space-size=4096"}
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in (1, 2):
        last = subprocess.run(
            ["npm", "run", "build"], cwd=WEB, text=True, capture_output=True,
            check=False, env=environment,
        )
        if last.returncode == 0:
            if attempt == 2:
                print("npm run build succeeded on the second attempt (first was flaky)")
            return last
        print(f"npm run build failed (attempt {attempt}/2):\n{last.stdout}\n{last.stderr}")
    assert last is not None
    return last


@pytest.fixture(scope="session")
def built_site() -> Path:
    """`frontend/web/dist` from a build of the current sources.

    Normally the fixture builds. CI builds in its own step instead
    (`HS_TEST_SKIP_BUILD=1`) so a build failure is a clearly-named failing step
    rather than an error inside a test — and so the build happens once. Either
    way the tests read output produced from *these* sources: a stale `dist/`
    from a different commit would let them pass while the shipped artefact is
    wrong, which is the same class of mistake the service-worker cache-bump rule
    exists to prevent.
    """
    dist = WEB / "dist"
    if os.environ.get("HS_TEST_SKIP_BUILD") and (dist / "index.html").exists():
        return dist
    result = _build()
    assert result.returncode == 0, f"npm run build failed\n{result.stdout}\n{result.stderr}"
    assert (dist / "index.html").exists(), "vite reported success but dist/index.html is missing"
    return dist
