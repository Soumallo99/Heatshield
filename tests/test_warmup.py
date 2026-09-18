"""`scripts/warmup.py` must warm things that exist, and things worth warming.

Two failure modes are worth a test, because both are silent in production:

* a path that no longer exists — the script prints a 404 for an operator who may
  not be watching, and the deploy looks warmed when it is not;
* a path that is not cacheable — "warming" one achieves nothing, and whoever
  wrote it believed otherwise.

The script itself is then exercised against a port that cannot answer, to prove a
failure is *reported* rather than raised: it is meant to be the last step of a
deploy, so it has to survive a broken one and still say what happened.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("hs_warmup", ROOT / "scripts" / "warmup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


warmup = _load()


def test_every_warmed_path_is_a_real_route():
    from app.main import app

    known = {route.path for route in app.routes}
    for entry in warmup.PATHS:
        path = entry.split("?", 1)[0]
        assert path in known, f"warmup.py warms {path}, which the API does not serve"


def test_every_warmed_path_is_actually_cacheable():
    """Warming an uncached path is theatre; this is the assertion that says so."""
    from app.main import _cache_seconds, config

    for entry in warmup.PATHS:
        path = entry.split("?", 1)[0]
        assert _cache_seconds(path) > 0, f"{path} is not cached, so warming it does nothing"
    assert config.RESPONSE_CACHE_MAX_AGE > 0, "the cache is off, so warmup.py cannot help"


def test_the_heaviest_public_read_is_in_the_list():
    """The point of the script is the 9-second one; it must not be dropped."""
    assert any("/risk/ranking" in entry for entry in warmup.PATHS)


def test_a_dead_backend_is_reported_not_raised():
    ok, seconds, size, note = warmup.fetch("http://127.0.0.1:1", "/health", timeout=1.0)
    assert ok is False
    assert size == 0
    assert note, "a failed warm-up must say why"
    assert seconds >= 0


def test_a_reply_that_is_not_json_is_not_a_crash():
    """A proxy's HTML error page is the realistic version of this failure."""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — the name is the stdlib's
            self.send_response(503)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>upstream down</html>")

        def log_message(self, *args):  # silence the test run
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        ok, _, _, note = warmup.fetch(f"http://127.0.0.1:{server.server_port}", "/health", timeout=5.0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert ok is False
    assert "503" in note
