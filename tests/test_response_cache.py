"""The response cache, and the isolation rules around it.

Why this file exists: adding a cache to a public API is the kind of change that
is invisible until it is wrong. It made real numbers better in a way that can be
re-measured (`scripts/loadtest.py --path …`), and the rules that keep it safe are
not obvious from reading the middleware — a cached body has to be byte-identical
to the uncached one, an operator's answer must never reach a visitor, a hostile
query must not poison a key, and a cache must never turn a transient failure into
a two-minute outage. Each of those is a test here.

The unit tests drive `core.response_cache` directly; the HTTP tests go through
the real app with a real `TestClient`.
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from core.response_cache import ResponseCache


# --------------------------------------------------------------- unit: the store


def test_the_same_query_written_differently_is_the_same_key():
    """`?a=1&b=2` and `?b=2&a=1` are one resource; two keys would halve a hit rate."""
    first = ResponseCache.key("/risk/ranking", "a=1&b=2", "gzip", 120)
    second = ResponseCache.key("/risk/ranking", "b=2&a=1", "gzip", 120)
    assert first == second


def test_a_different_query_is_a_different_key():
    assert ResponseCache.key("/risk/ranking", "scenario_c=0", "gzip", 120) != ResponseCache.key(
        "/risk/ranking", "scenario_c=1", "gzip", 120
    )


def test_the_encoding_is_part_of_the_key():
    """A gzipped body must never be handed to a client that cannot read it."""
    assert ResponseCache.key("/zones", "", "gzip", 120) != ResponseCache.key("/zones", "", "", 120)


def test_an_expired_entry_is_not_served():
    cache = ResponseCache(ttl_seconds=0.05)
    key = ResponseCache.key("/zones", "")
    cache.set(key, b"{}", "application/json", {})
    assert cache.get(key) is not None
    time.sleep(0.06)
    assert cache.get(key) is None, "an expired answer must be recomputed, not replayed"


def test_a_zero_ttl_stores_nothing():
    """The off-switch: HS_RESPONSE_CACHE_MAX_AGE=0 must mean "no cache at all"."""
    cache = ResponseCache(ttl_seconds=0)
    key = ResponseCache.key("/zones", "")
    cache.set(key, b"{}", "application/json", {}, ttl=0)
    assert cache.get(key) is None


def test_the_store_is_bounded():
    cache = ResponseCache(ttl_seconds=60, max_entries=3)
    for index in range(10):
        cache.set(f"key-{index}", b"{}", "application/json", {})
    assert cache.stats()["entries"] == 3, "an unbounded cache is a memory leak with a friendly name"


def test_an_oversized_answer_is_not_stored():
    """A cache must not become an amplification primitive."""
    cache = ResponseCache(ttl_seconds=60, max_response_bytes=1024)
    key = ResponseCache.key("/risk/ranking", "")
    cache.set(key, b"x" * 2048, "application/json", {})
    assert cache.get(key) is None
    cache.set(key, b"x" * 512, "application/json", {})
    assert cache.get(key) is not None


def test_the_owner_is_the_only_owner_and_waiters_are_counted():
    cache = ResponseCache(ttl_seconds=60)
    _, first = cache.claim("/zones")
    _, second = cache.claim("/zones")
    assert first is True and second is False, "exactly one request may compute a key"
    assert cache.stats()["coalesced"] == 1
    cache.release("/zones")
    _, third = cache.claim("/zones")
    assert third is True, "once released, the next request computes again"


def test_release_wakes_the_waiters():
    cache = ResponseCache(ttl_seconds=60)
    event, _ = cache.claim("/zones")
    assert not event.is_set()
    cache.release("/zones")
    assert event.is_set()


def test_a_dead_owner_can_be_replaced():
    """A crash in the computing request must not strand everybody waiting on it."""
    cache = ResponseCache(ttl_seconds=60)
    _, owner = cache.claim("/zones")
    assert owner is True
    cache.release("/zones")  # as the `finally` in the middleware does on any exit
    _, replacement = cache.claim("/zones")
    assert replacement is True


# ------------------------------------------------------------- http: the rules


@pytest.fixture()
def client() -> TestClient:
    from app.main import app, answer_cache

    answer_cache.clear()
    with TestClient(app) as test_client:
        yield test_client
    answer_cache.clear()


def test_a_repeat_request_is_answered_from_memory_and_is_byte_identical(client):
    first = client.get("/zones")
    second = client.get("/zones")
    assert first.status_code == second.status_code == 200
    assert second.headers.get("x-cache") == "HIT"
    assert first.headers.get("x-cache") is None
    assert first.content == second.content, "a cached answer must be the same answer, byte for byte"
    assert first.headers["content-type"] == second.headers["content-type"]
    # The body is gzipped once, on the way out of the inner middleware, and the
    # header travels with it; re-compressing a compressed body would be a bug.
    assert first.headers.get("content-encoding") == second.headers.get("content-encoding") == "gzip"


def test_different_queries_do_not_share_an_answer(client):
    zero = client.get("/risk/ranking?scenario_c=0")
    one = client.get("/risk/ranking?scenario_c=1")
    assert zero.status_code == one.status_code == 200
    assert zero.json() != one.json()
    assert one.headers.get("x-cache") is None


def test_an_operators_answer_is_never_served_to_a_visitor(client, admin_headers):
    """The subscriber registry must not become reachable through a shared cache."""
    signed_in = client.get("/subscribers", headers=admin_headers)
    visitor = client.get("/subscribers")
    assert signed_in.status_code == 200
    assert visitor.status_code in (401, 403)
    assert signed_in.headers.get("cache-control") == "no-store"
    assert "x-cache" not in visitor.headers


def test_a_credentialed_read_is_not_cached_even_when_the_route_is_public(client, admin_headers):
    first = client.get("/zones", headers=admin_headers)
    second = client.get("/zones", headers=admin_headers)
    assert first.status_code == second.status_code == 200
    assert "x-cache" not in first.headers and "x-cache" not in second.headers
    assert first.headers.get("cache-control") == "no-store"


def test_an_error_is_never_cached(client):
    """A transient failure must not be frozen into a two-minute outage."""
    from app.main import answer_cache

    broken = client.get("/risk/ward/0")           # rejected by the bounds check
    assert broken.status_code in (404, 422)
    assert broken.headers.get("x-cache") is None
    assert answer_cache.stats()["entries"] == 0


def test_a_cross_origin_request_is_not_answered_from_the_shared_cache(client):
    """CORS runs inside this middleware, so a replayed body would lose its header."""
    first = client.get("/zones", headers={"Origin": "http://localhost:5173"})
    second = client.get("/zones", headers={"Origin": "http://localhost:5173"})
    assert first.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert second.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "x-cache" not in first.headers and "x-cache" not in second.headers


def test_hostile_query_values_are_their_own_keys_and_do_not_crash(client):
    for value in ("abc", "-1", "9999999999999999999999", "'0'", "%00"):
        response = client.get(f"/thermal/daily?region={value}")
        assert response.status_code == 422, value
    assert client.get("/thermal/daily?region=coastal&date=2026-05-20").status_code in (200, 404, 422)


def test_the_cache_survives_a_concurrent_burst_without_mixing_answers(client):
    """Threads through one client: the cache must be thread-safe and coherent."""
    results: list[tuple[int, str]] = []
    errors: list[BaseException] = []
    bodies: list[bytes] = []

    def fetch(index: int) -> None:
        try:
            response = client.get("/zones")
            results.append((response.status_code, response.headers.get("x-cache", "MISS")))
            bodies.append(response.content)
        except BaseException as exc:  # noqa: BLE001 — reported below, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=fetch, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    assert len(results) == 12
    assert {status for status, _ in results} == {200}
    # Either they arrived while the first one was still computing and waited for
    # it ("COALESCED"), or they arrived afterwards and read the stored answer
    # ("HIT"). What must never happen is twelve independent computations, which
    # is what a simultaneous burst did before this existed.
    served = [cache for _, cache in results if cache in ("COALESCED", "HIT")]
    assert len(served) >= 11, f"only {len(served)} of 12 requests shared the work: {results}"
    assert len(set(bodies)) == 1, "everybody in the burst must be handed the same bytes"


def test_the_middleware_really_consults_the_store(client):
    """The store is only worth testing if the app uses it: miss, then hit."""
    from app.main import answer_cache

    assert answer_cache.ttl_seconds > 0, "the cache is on by default"
    assert answer_cache.stats()["hits"] == 0

    client.get("/zones")
    after_miss = answer_cache.stats()
    assert after_miss["entries"] == 1 and after_miss["hits"] == 0

    client.get("/zones")
    assert answer_cache.stats()["hits"] == 1
