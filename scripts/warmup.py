#!/usr/bin/env python3
"""Warm the public reads so the first visitor after a deploy never waits.

The heavy endpoints are pandas computations: on one worker a cold
`/risk/ranking?scenario_c=0` takes ~9 s. After that the answer is cached for
`HS_RESPONSE_CACHE_MAX_AGE` seconds (120 by default) and every later reader gets
it in milliseconds. So the only expensive request is the *first* one — and the
first one is currently whoever happens to open the site after a restart, usually
during the weather that makes the site worth opening.

Run this once after `scripts/refresh.py`, after a deploy, or any time the process
has just started:

    python scripts/warmup.py --url http://127.0.0.1:8000

It is safe to run at any time and safe to run twice: it only issues GETs, and it
prints how long each one took and how big it was. Exit code is non-zero if any
path failed, so it can be the last step of a deploy.

Note what this does *not* do: it does not hide a broken deployment. A 503 from an
upstream provider fails here too, loudly, which is the point of running it as part
of a release.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

# The paths a citizen's first screen actually needs, in the order it needs them.
# Scenario 0 is the current-conditions ranking; the scenarios an operator clicks
# through are deliberately left to on-demand caching rather than precomputed.
PATHS: tuple[str, ...] = (
    "/health",
    "/zones",
    "/risk/ranking?scenario_c=0",
    "/thermal/daily?region=coastal",
    "/ncr/summary",
    "/warnings/advance",
    "/alerts/plan",
)


def fetch(url: str, path: str, timeout: float) -> tuple[bool, float, int, str]:
    """One GET. Returns (ok, seconds, bytes, note)."""
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}{path}", timeout=timeout) as response:
            body = response.read()
        return True, time.perf_counter() - started, len(body), ""
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read()).get("detail", "")
        except Exception:  # noqa: BLE001 — a diagnostic, never a reason to crash
            pass
        return False, time.perf_counter() - started, 0, f"HTTP {exc.code} {detail}".strip()
    except Exception as exc:  # noqa: BLE001 — the point is to report it, not raise it
        return False, time.perf_counter() - started, 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds per request")
    args = parser.parse_args()

    print(f"warming {args.url}")
    failures = 0
    slowest = 0.0
    for path in PATHS:
        ok, seconds, size, note = fetch(args.url, path, args.timeout)
        slowest = max(slowest, seconds)
        mark = "ok  " if ok else "FAIL"
        print(f"  {mark} {seconds:6.2f}s  {size:>8,} bytes  {path}{'  — ' + note if note else ''}")
        failures += 0 if ok else 1

    print(f"\n{len(PATHS) - failures}/{len(PATHS)} paths warm; slowest {slowest:.2f}s")
    if failures:
        print("a path that will not warm is a deployment that is not ready — see the errors above")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
