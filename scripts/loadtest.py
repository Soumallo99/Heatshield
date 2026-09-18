#!/usr/bin/env python3
"""Concurrent-user check: does the API hold up when more than one person opens it?

The checklist item is "test with simultaneous users". For this project the
interesting question is not throughput — it is whether a second and third
request can turn a correct answer into a wrong one, because the heavy endpoints
are pure functions over a cached CSV frame and the process is a single uvicorn
worker. Two things can go wrong that a single-user click-through never shows:

  * a shared cache returning another request's numbers (a scenario-8 page
    showing scenario-0 data would be a wrong warning, not a slow one);
  * a write path (the subscriber registry) losing or duplicating a row.

So this tool fires N concurrent clients across the public reads, checks that
every response is well-formed and that scenario-specific payloads keep their own
scenario, and reports latency. Any 5xx or any mismatch is a failure, and the
process exits non-zero.

    python scripts/loadtest.py --url http://127.0.0.1:8000 --users 12 --per-user 4

Stdlib only (threads + urllib): it must run on a laptop with nothing installed.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

# (path, predicate) — the predicate parses the payload and returns True when the
# response is self-consistent. This is the part that makes the tool a *test*
# rather than a benchmark.
CHECKS = [
    ("/health", None),
    ("/risk/ranking?scenario_c=0", lambda body: body.get("scenario_c") in (0, 0.0)),
    ("/risk/ranking?scenario_c=4", lambda body: body.get("scenario_c") in (4, 4.0)),
    ("/alerts/plan", None),
    ("/ncr/summary", None),
    ("/warnings/advance", None),
    ("/subscribers/stats", None),
]


class Result:
    __slots__ = ("path", "status", "seconds", "error", "problem")

    def __init__(self, path: str) -> None:
        self.path = path
        self.status = 0
        self.seconds = 0.0
        self.error: str | None = None
        self.problem: str | None = None


def one_request(url: str, path: str, predicate) -> Result:
    result = Result(path)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(f"{url}{path}", timeout=30) as response:
            result.status = response.status
            payload = response.read()
    except urllib.error.HTTPError as error:          # 4xx/5xx are data, not crashes
        result.status = error.code
        payload = error.read()
    except Exception as error:                        # noqa: BLE001 - reported verbatim
        result.error = f"{type(error).__name__}: {error}"
        result.seconds = time.perf_counter() - started
        return result
    result.seconds = time.perf_counter() - started

    if result.status != 200:
        result.problem = f"HTTP {result.status}"
        return result
    try:
        body = json.loads(payload)
    except json.JSONDecodeError:
        result.problem = "response was not JSON"
        return result
    if predicate and not predicate(body):
        result.problem = "payload contradicts the request (cross-request contamination?)"
    return result


def run(url: str, users: int, per_user: int, pinned: str | None = None) -> list[Result]:
    results: list[Result] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        for round_number in range(per_user):
            if pinned:
                path, predicate = pinned, None
            else:
                path, predicate = CHECKS[(index + round_number) % len(CHECKS)]
            outcome = one_request(url, path, predicate)
            with lock:
                results.append(outcome)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(users)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def report(results: list[Result]) -> int:
    failures = [r for r in results if r.problem or r.error]
    latencies = sorted(r.seconds for r in results)

    print(f"{len(results)} requests from concurrent clients")
    if latencies:
        def pct(p: float) -> float:
            return latencies[min(len(latencies) - 1, int(len(latencies) * p))] * 1000

        print(f"  latency ms: p50 {pct(.50):.0f}  p90 {pct(.90):.0f}  p95 {pct(.95):.0f}  max {latencies[-1]*1000:.0f}")
        print(f"  mean {statistics.fmean(latencies)*1000:.0f} ms")

    by_path: dict[str, list[float]] = {}
    for result in results:
        by_path.setdefault(result.path, []).append(result.seconds)
    for path, times in sorted(by_path.items(), key=lambda item: -statistics.fmean(item[1])):
        print(f"  {statistics.fmean(times)*1000:7.0f} ms  x{len(times):<3} {path}")

    if failures:
        print(f"\n{len(failures)} failure(s):", file=sys.stderr)
        for failure in failures[:15]:
            detail = failure.problem or failure.error
            print(f"  {failure.path}: {detail}", file=sys.stderr)
        if len(failures) > 15:
            print(f"  … and {len(failures) - 15} more", file=sys.stderr)
        return 1

    server_errors = [r for r in results if r.status >= 500]
    if server_errors:
        print(f"\n{len(server_errors)} server error(s) — a concurrent read must not 500", file=sys.stderr)
        return 1
    print("\nno errors, no contradictory payloads, no 5xx")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--users", type=int, default=12, help="concurrent clients")
    parser.add_argument("--per-user", type=int, default=4, help="requests per client")
    parser.add_argument(
        "--path",
        default=None,
        help="pin every request to one path, to measure the same-page crowd (e.g. /risk/ranking?scenario_c=0)",
    )
    args = parser.parse_args(argv)

    print(f"{args.users} concurrent clients x {args.per_user} requests against {args.url}\n")
    return report(run(args.url, args.users, args.per_user, pinned=args.path))


if __name__ == "__main__":
    raise SystemExit(main())
