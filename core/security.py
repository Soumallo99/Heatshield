"""Security primitives for the HeatShield API.

Threat model, in one paragraph. HeatShield's API may be reachable from the open
internet, and it has no login system. Three things behind it matter:

1. **The subscriber registry** — phone numbers, names and roles of residents,
   ward officials and health workers. That is personal data (`/subscribers`,
   `/subscribers/for-ward/{id}` returned it to any anonymous request).
2. **The ability to silence a number** — `POST /subscribers/stop` opted any phone
   number out of a heat-warning system with no authentication. In a life-safety
   context that is the worst failure mode available: make the warning system
   quiet for whoever you name.
3. **The ability to trigger a send** — the dispatch routes are dry-run by default
   and live sending needs `HS_ALLOW_LIVE_SEND=1` plus Twilio credentials, but
   without a gate anyone can drive them, spend provider credit and (with
   `to_numbers`) aim messages at numbers they choose.

There is no account system and no session: the gate is a single bearer token from
the environment (`HS_ADMIN_TOKEN`), compared in constant time. **When no token is
configured those routes are disabled** — a deployment that forgets to set one
refuses the requests instead of trusting them. Local development is explicit:
`HS_ADMIN_TOKEN=dev python -m uvicorn app.main:app`.

The rest of the module is input hardening: registry fields are neutralised before
they reach a CSV (formula injection: `=cmd|…` in a name executes when an operator
opens the file in Excel), and a small in-process rate limiter keeps the
unauthenticated surface from being enumerated or hammered.
"""
from __future__ import annotations

import re
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from core import config

# --------------------------------------------------------------------------- #
# 1. admin gate
# --------------------------------------------------------------------------- #

_TOKEN_HEADERS = ("x-api-key", "x-heatshield-token")


def admin_token() -> str:
    """The configured admin token, or "" when the operator has not set one."""
    return (config.ADMIN_TOKEN or "").strip()


def presented_token(request: Request) -> str:
    """Token from `X-API-Key`/`X-HeatShield-Token`, else a Bearer header."""
    for header in _TOKEN_HEADERS:
        value = request.headers.get(header)
        if value:
            return value.strip()
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def is_admin(request: Request) -> bool:
    token = admin_token()
    if not token:
        return False
    # compare_digest: constant-time, so the token cannot be guessed byte by byte.
    return secrets.compare_digest(presented_token(request), token)


def require_admin(request: Request) -> None:
    """FastAPI dependency for every route that reads PII or can send/silence.

    503 (not 401) when no token is configured: the route is disabled, and telling
    the caller "configure HS_ADMIN_TOKEN" is the honest and actionable answer.
    401 when a token is configured and the caller did not present it correctly.
    """
    if not admin_token():
        raise HTTPException(
            status_code=503,
            detail=(
                "administrative endpoints are disabled: no HS_ADMIN_TOKEN is "
                "configured on this server"
            ),
        )
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="valid admin token required")


# --------------------------------------------------------------------------- #
# 2. personal-data redaction
# --------------------------------------------------------------------------- #

def redact_phone(phone: str) -> str:
    """`+919876543210` -> `+91••••••3210`: enough to audit, useless to harvest.

    Registry reads redact by default. Phone numbers were never needed in full by
    a browser: dispatch resolves recipients server-side.
    """
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) < 6:
        return "••••" if digits else ""
    # Same convention as subscribers.normalise_phone: a bare 10-digit number is
    # Indian, and 91-prefixed numbers keep their country code.
    if len(digits) in (10, 12) and (len(digits) == 10 or digits.startswith("91")):
        country, rest = "91", digits[-10:]
    else:
        country, rest = digits[:2], digits[2:]
    return f"+{country}••••••{rest[-4:]}"


# --------------------------------------------------------------------------- #
# 3. registry text hardening
# --------------------------------------------------------------------------- #

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitise_cell(value: str, *, max_length: int = 120) -> str:
    """Make a registry field safe to store in a CSV that a human will open.

    A leading `=`, `+`, `-` or `@` makes Excel and LibreOffice treat the cell as
    a formula (CWE-1236 — `=cmd|' /C calc'!A0` is the classic). Prefixing with an
    apostrophe keeps the text readable and inert. Control characters and
    newlines are dropped (they would break the CSV row structure), and length is
    capped so one request cannot fill the disk.
    """
    text = _CONTROL_CHARS.sub("", str(value or ""))
    text = text.replace("\n", " ").strip()
    if len(text) > max_length:
        text = text[:max_length]
    if text.startswith(_FORMULA_PREFIXES):
        text = "'" + text
    return text


def sanitise_phone_list(numbers: list[str] | None, *, limit: int = 50) -> list[str] | None:
    """Cap and normalise an explicit recipient list from a request body."""
    if numbers is None:
        return None
    from core.subscribers import normalise_phone  # local import: avoid a cycle

    cleaned: list[str] = []
    for raw in numbers[:limit]:
        phone = normalise_phone(raw)
        # Keep only plausible E.164 numbers, so a dispatch cannot be aimed at
        # arbitrary junk strings.
        if re.fullmatch(r"\+\d{8,15}", phone) and phone not in cleaned:
            cleaned.append(phone)
    return cleaned


# --------------------------------------------------------------------------- #
# 4. rate limiting
# --------------------------------------------------------------------------- #

class RateLimiter:
    """Fixed-window counter: `limit` requests per client per 60 seconds.

    Deliberately tiny and in-process — HeatShield is a single-process prototype
    (see the note on FastAPI being stateless), and this exists to stop
    enumeration and casual hammering, not to be an edge-grade limiter. A
    multi-worker deployment should put a real limiter in front (nginx, a cloud
    WAF, or `slowapi` backed by Redis) — the README says so.

    `limit <= 0` disables it, which is how the test suite runs.
    """

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, now: float | None = None) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        if self.limit <= 0:
            return True, 0
        moment = time.monotonic() if now is None else now
        hits = self._hits[key]
        cutoff = moment - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            retry_after = max(1, int(self.window - (moment - hits[0])) + 1)
            return False, retry_after
        hits.append(moment)
        # Cheap housekeeping: forget idle clients so the dict cannot grow forever.
        if len(self._hits) > 10_000:
            for stale in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
                self._hits.pop(stale, None)
        return True, 0


def client_key(request: Request) -> str:
    """Best-effort client identity for rate limiting.

    `X-Forwarded-For` is only trusted when the operator says the app sits behind
    a proxy (`HS_TRUST_PROXY=1`), because otherwise any client can spoof it and
    get a fresh bucket per request.
    """
    if config.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
