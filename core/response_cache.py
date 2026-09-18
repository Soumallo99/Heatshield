"""A small in-process cache for the public reads, with single-flight.

Why this exists: the heavy endpoints are pandas computations over the last
forecast run — a few hundred milliseconds each, on one worker, under the GIL.
Measured against a local server, twelve people opening the *same* page at the
same moment (which is exactly what a heat warning produces) took **p95 11.2 s**,
because every one of them recomputed the same answer from the same unchanged
CSV. Nothing about that is a database problem or a hardware problem: it is the
same answer being built forty-eight times.

Two mechanisms, deliberately separate:

* **TTL cache** — a repeat request for the same path and query within
  `HS_RESPONSE_CACHE_MAX_AGE` seconds is answered from memory. The data behind
  these endpoints changes at most once per forecast cycle, so a two-minute-old
  identical answer is the same answer.
* **Single flight** — while one request is computing a key, identical requests
  *wait for it* instead of piling on. Without this the first burst still pays
  N times; with it, the burst pays once and the rest return the same bytes.

What it deliberately does not do:

* it is per-process, like the rate limiter — N workers hold N caches (documented
  in the README next to the worker guidance);
* it never caches a request carrying a credential, anything under
  `/subscribers`, anything that is not a GET, or any response that is not 200 —
  the caller decides that, this module just stores what it is given;
* it never serves a response past its deadline, and it never returns a partial
  one: entries are stored whole or not at all.

Stdlib only, no background threads: an expired entry is dropped on the next
lookup, which is all a cache of this size needs.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode


@dataclass
class Entry:
    body: bytes
    media_type: str
    headers: dict[str, str]
    expires_at: float


@dataclass
class _Flight:
    """One in-progress computation, and the requests waiting on it."""

    event: threading.Event = field(default_factory=threading.Event)


class ResponseCache:
    """Keyed on (path, canonical query, Accept-Encoding). Thread-safe.

    `Accept-Encoding` is part of the key because the bytes cached are the bytes
    that go on the wire: a gzipped body must never be handed to a client that
    did not ask for one.
    """

    def __init__(self, ttl_seconds: int, max_entries: int = 128,
                 max_response_bytes: int = 512 * 1024) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        # A bound on the value as well as the number of keys: 128 entries of a
        # hostile query's choosing must not be able to hold the process's memory
        # hostage. Every public read here is tens of kB, so this never bites —
        # it is the difference between a cache and an amplification primitive.
        self.max_response_bytes = max_response_bytes
        self._entries: dict[str, Entry] = {}
        self._flights: dict[str, _Flight] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.coalesced = 0

    # ------------------------------------------------------------------ keys

    @staticmethod
    def key(path: str, query: str, accept_encoding: str = "", ttl: int = 0) -> str:
        """Canonical key: parameter order must not create a second copy."""
        pairs = sorted(parse_qsl(query, keep_blank_values=True))
        return f"{path}?{urlencode(pairs)}|{accept_encoding}|{ttl}"

    # --------------------------------------------------------------- storage

    def get(self, key: str) -> Entry | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            if entry.expires_at <= time.monotonic():
                del self._entries[key]
                self.misses += 1
                return None
            self.hits += 1
            return entry

    def set(self, key: str, body: bytes, media_type: str, headers: dict[str, str], ttl: int | None = None) -> None:
        ttl = self.ttl_seconds if ttl is None else ttl
        if ttl <= 0 or len(body) > self.max_response_bytes:
            return
        with self._lock:
            if len(self._entries) >= self.max_entries:
                # Oldest first: dict preserves insertion order, and every entry
                # here has the same TTL, so insertion order is expiry order.
                self._entries.pop(next(iter(self._entries)), None)
            self._entries[key] = Entry(body, media_type, headers, time.monotonic() + ttl)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = self.misses = self.coalesced = 0

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"entries": len(self._entries), "hits": self.hits, "misses": self.misses, "coalesced": self.coalesced}

    # ---------------------------------------------------------- single flight

    def claim(self, key: str) -> tuple[threading.Event, bool]:
        """Return (event, is_owner).

        The owner computes the response and must hand the same event back to
        `release` when it is done, whatever the outcome. Everybody else waits on
        that event and then reads the cache.
        """
        with self._lock:
            flight = self._flights.get(key)
            if flight is None:
                flight = _Flight()
                self._flights[key] = flight
                return flight.event, True
            self.coalesced += 1
            return flight.event, False

    def release(self, key: str, event: threading.Event | None = None) -> None:
        """Wake the waiters — but only for the flight that is still current.

        Passing the event matters: a request that took over after a timeout owns
        a *different* flight, and the original owner returning late must not clear
        the newer one, or its waiters would be left with nothing to read.
        """
        with self._lock:
            flight = self._flights.get(key)
            if flight is not None and (event is None or flight.event is event):
                del self._flights[key]
                current = flight
            else:
                current = None
        if current is not None:
            current.event.set()

    def takeover(self, key: str, event: threading.Event | None = None) -> threading.Event:
        """Become the owner after a wait that produced nothing.

        Called when the original owner failed or is wedged; without it one crash
        would leave every waiting request with no answer at all. The swap is only
        performed if the flight being replaced is the one the caller waited on,
        so a late finisher cannot cancel a takeover that already happened.
        """
        with self._lock:
            flight = self._flights.get(key)
            if flight is not None and event is not None and flight.event is not event:
                return flight.event
            fresh = _Flight()
            self._flights[key] = fresh
            return fresh.event
