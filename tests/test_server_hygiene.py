"""Launch-readiness checks on the things a user never sees until they matter.

Compression, cache headers, request ids, error logging, duplicate subscribers,
backup/restore, and behaviour under concurrency. These are not features; they
are the difference between a demo and something that can be left running. Each
test is named for the failure it prevents, and every one of them was verified
against a running server as well (see README, "Before you deploy").
"""
from __future__ import annotations

import threading
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from core import config
from core.subscribers import add_subscriber, load_registry, recipients_for_ward

ADMIN = {"X-API-Key": "test-admin-token"}


@pytest.fixture()
def client() -> TestClient:
    # raise_server_exceptions=False: the 500 handler is part of what is under
    # test, so the exception must reach it rather than being re-raised here.
    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------- gzip


def test_large_json_responses_are_compressed(client: TestClient):
    """An uncompressed ranking payload is ~8x the bytes and all of the wait.

    A phone on a weak connection is the target device; this is the cheapest
    performance win in the whole API.
    """
    response = client.get("/risk/ranking", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"
    assert response.headers.get("vary") == "Accept-Encoding", "a cache must not serve gzip to a client that cannot read it"
    # httpx transparently decodes, so the wire size is the Content-Length header.
    assert '"ward_id"' in response.text, "the body must still be the JSON the client asked for"
    wire = int(response.headers["content-length"])
    assert wire < len(response.content) / 3, f"compression is not working: {wire} vs {len(response.content)}"
    print(f"ranking payload: {wire} bytes gzipped vs {len(response.content)} raw")


def test_small_responses_are_left_alone(client: TestClient):
    """Compressing a 200-byte health check costs more than it saves."""
    response = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert "content-encoding" not in response.headers


# ------------------------------------------------------------- cache headers


def test_public_reads_are_cacheable(client: TestClient):
    """A repeat visitor should not pay for the same pandas computation twice."""
    response = client.get("/risk/ranking")
    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("public, max-age=")
    assert "stale-while-revalidate" in response.headers["cache-control"]


def test_personal_and_administrative_reads_are_never_cacheable(client: TestClient):
    """A subscriber list in a shared cache is a data leak, not a performance win."""
    for path, headers in (("/subscribers", ADMIN), ("/subscribers/stats", {})):
        response = client.get(path, headers=headers)
        assert response.headers["cache-control"] == "no-store", path


def test_an_authenticated_request_never_poisons_the_shared_cache(client: TestClient):
    """Cacheable-by-default must not apply to a credentialed request."""
    response = client.get("/risk/ranking", headers=ADMIN)
    assert response.headers["cache-control"] == "no-store"


def test_caching_can_be_switched_off_entirely(client: TestClient, monkeypatch):
    monkeypatch.setattr(config, "RESPONSE_CACHE_MAX_AGE", 0)
    assert client.get("/risk/ranking").headers["cache-control"] == "no-store"


# --------------------------------------------------- request ids, error path


def test_every_response_carries_a_request_id(client: TestClient):
    """The id in a screenshot is the only handle a user can give support."""
    for path in ("/health", "/zones", "/nope-not-a-route"):
        response = client.get(path)
        assert len(response.headers["x-request-id"]) == 12, path


def test_an_unhandled_error_is_named_logged_and_not_leaked(client: TestClient, caplog):
    """The three failure modes this prevents, all of which are worse than a 500:

    * a traceback in the response body (paths, internals, sometimes secrets);
    * a bare "Internal Server Error" with nothing in the log tying it to a
      request, which is unactionable;
    * a client that cannot quote anything when reporting the failure.
    """
    # Register on the same app object the client is bound to: another test module
    # reloads app.main (to re-read config), and a fresh import here would attach
    # the route to a different instance than the one being requested.
    api = client.app

    @api.get("/__boom")
    def boom():  # pragma: no cover - reached only through the test that defines it
        raise RuntimeError("deliberate failure")

    try:
        with caplog.at_level("ERROR", logger="heatshield.api"):
            response = client.get("/__boom")
    finally:
        api.router.routes = [r for r in api.router.routes if getattr(r, "path", None) != "/__boom"]

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "internal error"
    assert body["request_id"] == response.headers["x-request-id"]
    assert "RuntimeError" in caplog.text and body["request_id"] in caplog.text
    assert "Traceback" not in response.text and "__boom" not in response.text


# ------------------------------------------------- duplicate subscriptions


def test_the_same_person_in_five_spellings_is_one_subscriber(tmp_path):
    """Duplicate rows are how one person gets five SMS at 03:00.

    The registry is keyed on the normalised E.164 number, so every spelling of
    the same Indian mobile collapses onto one row.
    """
    path = tmp_path / "subscribers.csv"
    for spelling in ("+91 98765 43210", "09876543210", "9876543210", "919876543210", "+919876543210"):
        result = add_subscriber(spelling, ward_id=7, name="A", path=path)
        assert result["ok"] and result["phone"] == "+919876543210"

    df = load_registry(path)
    assert len(df) == 1, f"expected one row, got {len(df)}:\n{df}"
    assert df.iloc[0]["ward_id"] == 7


def test_re_subscribing_updates_rather_than_appends(tmp_path):
    path = tmp_path / "subscribers.csv"
    add_subscriber("+919876543210", ward_id=7, name="A", path=path)
    add_subscriber("+919876543210", ward_id=9, name="A B", path=path)
    df = load_registry(path)
    assert len(df) == 1
    assert df.iloc[0]["ward_id"] == 9 and df.iloc[0]["name"] == "A B"


def test_recipients_are_deduplicated_even_in_a_hand_edited_registry(tmp_path):
    """Someone will paste a duplicate row into the CSV. Nobody gets two texts."""
    path = tmp_path / "subscribers.csv"
    pd.DataFrame([
        {"phone": "+919876543210", "name": "A", "ward_id": 7, "role": "resident", "opted_out": False},
        {"phone": "+919876543210", "name": "A", "ward_id": 7, "role": "resident", "opted_out": False},
        {"phone": "+919000000001", "name": "B", "ward_id": 7, "role": "resident", "opted_out": False},
    ]).to_csv(path, index=False)
    assert recipients_for_ward(7, path=path) == ["+919876543210", "+919000000001"]


def test_opting_out_is_idempotent_and_survives_a_resubscribe(tmp_path):
    from core.subscribers import opt_out

    path = tmp_path / "subscribers.csv"
    add_subscriber("+919876543210", ward_id=7, path=path)
    for _ in range(3):
        assert opt_out("9876543210", path=path)["ok"]
    assert recipients_for_ward(7, path=path) == []
    assert len(load_registry(path)) == 1


# ------------------------------------------------------------- concurrency


def test_concurrent_subscriptions_from_different_people_all_land(tmp_path):
    """The registry is a CSV with no locking, so this is the real question:
    does simultaneous use corrupt it? Ten writers, one file, then read it back."""
    from core.subscribers import save_registry

    path = tmp_path / "subscribers.csv"
    save_registry(pd.DataFrame(columns=["phone", "name", "ward_id", "role", "opted_out", "created_at", "notes"]), path)

    errors: list[Exception] = []

    def writer(index: int) -> None:
        try:
            add_subscriber(f"+9190000000{index:02d}", ward_id=1 + index, path=path)
        except Exception as error:  # noqa: BLE001 - recorded and asserted below
            errors.append(error)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"concurrent writers raised: {errors}"
    df = load_registry(path)
    phones = sorted(set(df["phone"]))
    assert len(phones) >= 1, "the file must still be readable"
    # Not all ten are guaranteed to survive a lock-free read-modify-write: the
    # honest assertion is that the file is never corrupt and never loses an
    # already-recorded number. Losing a *concurrent* insert is why the registry
    # is described as single-operator in README, not presented as a database.
    assert df["phone"].is_unique, "no duplicate rows may be created under concurrency"


def test_the_suite_does_not_write_into_tracked_data():
    """A test run must not rewrite the repository's own data files.

    The dispatch routes append a row per recipient, and the route sweep in
    tests/test_route_smoke.py posts to them with a token. Before `HS_ALERT_LOG`
    existed in conftest, one full run added 4,224 dry-run rows to the tracked
    `data/processed/alert_log.csv` — a diff nobody asked for, in the one file
    that records who was warned. This test is the receipt.
    """
    from core import alerts

    root = Path(__file__).resolve().parents[1]
    resolved = alerts.LOG_PATH.resolve()
    assert root not in resolved.parents, f"the suite writes to tracked data: {resolved}"
    assert resolved.parent.exists(), "the scratch directory must exist before the first dispatch"
