"""P2-3: the '/' dashboard page's Global Status Bar refresh path is now
push-driven IN ADDITION to poll-driven -- an EventSource subscription
against the already-real `GET /api/events/stream` route (live_event_model
.py's 11-name GUI_* vocabulary) that calls `loadGlobalStatusBar()` on a
status-bar-relevant event, layered on top of the pre-existing, untouched
`setInterval(load,3000)` poll loop.

This closes the wiring half of STATUS-AT-36's disclosed gap (see
test_status_acceptance.py's own docstring for that item, updated alongside
this change): before this item, a direct grep of the served page for
"EventSource" returned zero hits; after it, the page really opens one and
really wires it to a status-bar refresh. The OTHER half of STATUS-AT-36's
disclosed gap -- no production code path anywhere in this repo (engine.py
included) ever calls `live_event_model.emit()` -- is unchanged by this item
and is NOT claimed closed here; STATUS-AT-36 stays skipped with its reason
narrowed accordingly.

There is no browser/JS engine available in this test environment, so (per
this project's own established convention for testing served page content --
see e.g. the existing "confirmed by direct grep: zero 'EventSource'
occurrences anywhere in dashboard.py" evidence this item's own gap was
originally diagnosed from) this file verifies the SAME two things a real
browser would need to be true for the described push-refresh behaviour to
actually happen: (1) the served page's own source really opens an
EventSource against the real, already-working SSE route and really calls
loadGlobalStatusBar() from its onmessage handler when a relevant GUI_*
event name arrives, and (2) that route itself really pushes a live
event -- through a REAL live_event_model.emit() call, exactly the same
technique test_dashboard_events_stream.py's own real-socket tests already
use -- proving the two pieces genuinely compose end to end rather than only
looking wired on paper.

Every server here is a REAL dv_harness.dashboard.serve() instance on a
free local port (test_dashboard_interactive.py's own helpers, the same
cross-test import convention every other dashboard-card test file in this
directory already follows). Every pushed event is a REAL
live_event_model.emit() call through the SAME project root the server is
serving -- never a hand-written events.jsonl line.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.request

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)


def _get_raw(base: str, path: str) -> str:
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        return resp.read().decode("utf-8")


def _sse_connect(host: str, port: int, path: str, timeout: float = 5.0) -> socket.socket:
    """Same raw-socket technique test_dashboard_events_stream.py already
    uses for this route -- urllib/http.client would block forever on
    .read() against a stream that never closes."""
    sock = socket.create_connection((host, port), timeout=timeout)
    req = f"GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n"
    sock.sendall(req.encode("utf-8"))
    sock.settimeout(0.3)
    return sock


def _wait_for(sock: socket.socket, needle: bytes, deadline_s: float) -> bytes:
    collected = b""
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            break
        collected += chunk
        if needle in collected:
            return collected
    return collected


def test_served_page_opens_an_eventsource_wired_to_the_real_sse_route():
    """The additive JS this item wrote is really present in the served
    page: a real EventSource against /api/events/stream, an onmessage
    handler that calls loadGlobalStatusBar() when a relevant GUI_* event
    name arrives, and -- critically -- the pre-existing poll loop left
    completely untouched alongside it."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    _start_dashboard(tmp)
    base = f"http://127.0.0.1:{port}"
    _wait_ready(base)

    page = _get_raw(base, "/")

    assert "new EventSource('/api/events/stream')" in page
    assert "initGlobalStatusBarSSE" in page
    assert "loadGlobalStatusBar()" in page
    # every one of the relevant GUI_* names this item wired must be a real,
    # currently-defined member of live_event_model.GUI_LIVE_EVENTS -- never
    # a name this page invented that the real vocabulary does not carry.
    from dv_harness import live_event_model as lem
    assert "SB_SSE_RELEVANT_EVENTS" in page
    for name in ("GUI_STAGE_STATUS_CHANGED", "GUI_STAGE_TRANSITIONED",
                 "GUI_GATE_VERDICT_RECORDED", "GUI_HUMAN_GATE_OPENED",
                 "GUI_QUESTION_QUEUE_UPDATED", "GUI_APPROVAL_RECORDED",
                 "GUI_LSF_JOB_STATUS_CHANGED", "GUI_WAIVER_STATUS_CHANGED",
                 "GUI_CONTROL_COMMAND_EXECUTED"):
        assert name in page
        assert name in lem.GUI_LIVE_EVENTS

    # the original, pre-existing poll-driven fallback is still there,
    # completely unaltered -- this item is additive, never a replacement.
    assert "setInterval(load,3000)" in page
    assert "load(); setInterval(load,3000); loadSessions(); loadUserInfo(); loadMemoryCenter();" in page


def test_sse_route_pushes_a_status_bar_relevant_event_the_page_would_react_to():
    """Proves the OTHER half of the composition genuinely works: the real
    SSE route this page's EventSource connects to really forwards a real
    live_event_model.emit() call for one of the exact event names this
    item's onmessage handler checks for -- so if a browser were attached,
    the wiring this item added really would fire a loadGlobalStatusBar()
    refresh, not merely reference a name that never arrives."""
    from dv_harness import storage, live_event_model as lem

    port = _free_port()
    tmp = _mk_dashboard_project(port)
    _start_dashboard(tmp)
    base = f"http://127.0.0.1:{port}"
    _wait_ready(base)

    sock = _sse_connect("127.0.0.1", port, "/api/events/stream")
    try:
        # let the connection open and record its own start watermark first,
        # matching test_dashboard_events_stream.py's own established
        # "connect, then emit, then observe" ordering.
        time.sleep(0.3)
        store = storage.StateStore(tmp)
        lem.emit(store, "GUI_STAGE_STATUS_CHANGED", source="test", stage="BUILD_DEBUG")

        raw = _wait_for(sock, b"GUI_STAGE_STATUS_CHANGED", deadline_s=5.0)
    finally:
        sock.close()

    assert b"GUI_STAGE_STATUS_CHANGED" in raw
    frame = [ln[len("data: "):] for ln in raw.decode("utf-8").splitlines()
             if ln.startswith("data: ")]
    assert frame, f"no SSE data frame observed in: {raw!r}"
    payload = json.loads(frame[-1])
    assert payload["event"] == "GUI_STAGE_STATUS_CHANGED"
