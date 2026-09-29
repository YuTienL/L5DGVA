"""GET /api/events/stream -- the SSE push transport for live_event_model.py's
own eleven-name GUI_* live-event vocabulary (Web Control Plane theme,
sections 342-402).

live_event_model.py's own module docstring is explicit that its scope is
"data model + emit/read ONLY" and that "the actual push-to-browser transport
(a WebSocket/SSE server, a browser-side subscriber) is a separate, later item
and is deliberately not built here." This is that later item: a chunked
text/event-stream GET route added to dashboard.py's existing
http.server.ThreadingHTTPServer-based dispatch, built on the SAME plain
stdlib machinery every other route in that file already uses -- no new
dependency, and no second events.jsonl parser: the route polls
live_event_model.list_gui_live_events(), the one real reader that module
already ships, tested.

Every test here is driven over a REAL dv_harness.dashboard.serve() instance
on a free local port, reusing test_dashboard_interactive.py's own harness
helpers (the same cross-test import convention every other dashboard-card
test file in this directory already follows), and every pushed event is a
REAL live_event_model.emit() call through the SAME project root the server
is serving -- never a hand-written events.jsonl line and never a
dashboard-local re-derivation of what live_event_model.py itself already
computes.

The negative controls this file exists to prove, per the Evidence Truth
Rule: (1) a newly-opened connection never replays a backlog event recorded
BEFORE it connected -- only genuinely new events; (2) a project with no GUI
live events recorded at all keeps the connection open and sends nothing
fabricated, the honest empty state list_gui_live_events() itself already
reports (NO_GUI_LIVE_EVENTS_RECORDED), never a manufactured event.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.parse
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)


def _sse_connect(host: str, port: int, path: str, timeout: float = 5.0) -> socket.socket:
    """A raw socket GET against the SSE route -- deliberately not
    urllib.request.urlopen()/http.client, since both would block on .read()
    until the (never-closing) connection ends. A short per-recv timeout lets
    the caller poll for "nothing arrived yet", which IS the honest-empty-
    state assertion this file needs to make."""
    sock = socket.create_connection((host, port), timeout=timeout)
    req = f"GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n"
    sock.sendall(req.encode("utf-8"))
    sock.settimeout(0.3)
    return sock


def _read_for(sock: socket.socket, deadline_s: float) -> bytes:
    """Every byte the socket delivers within deadline_s wall-clock seconds,
    tolerating the real per-recv timeouts an idle SSE connection produces
    between polls -- never treated as an error."""
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
    return collected


def _wait_for(sock: socket.socket, needle: bytes, deadline_s: float) -> bytes:
    collected = b""
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        if chunk:
            collected += chunk
            if needle in collected:
                return collected
    return collected


def test_stream_headers_are_real_sse_and_backlog_is_never_replayed():
    """Connecting must return real SSE headers, and a GUI live event recorded
    BEFORE the connection opened must never be delivered on it -- only a
    genuinely new one, recorded through the same real live_event_model.emit()
    path, arrives."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_host, base_port = "127.0.0.1", port
        _start_dashboard(tmp)
        _wait_ready(f"http://{base_host}:{base_port}")

        from dv_harness import live_event_model
        from dv_harness.storage import StateStore

        store = StateStore(tmp)
        live_event_model.emit(store, "GUI_STAGE_STATUS_CHANGED",
                               source="backlog_before_connect",
                               marker="SHOULD_NEVER_APPEAR")
        time.sleep(0.3)  # real wall-clock separation from the connection's own since_ts

        sock = _sse_connect(base_host, base_port, "/api/events/stream")
        try:
            head = _read_for(sock, 1.5)
            assert b"200" in head.split(b"\r\n", 1)[0]
            assert b"text/event-stream" in head
            assert b"SHOULD_NEVER_APPEAR" not in head  # the negative control

            live_event_model.emit(store, "GUI_QUESTION_QUEUE_UPDATED",
                                   source="test", marker="REAL_NEW_EVENT")
            body = _wait_for(sock, b"REAL_NEW_EVENT", 6.0)
            assert b"REAL_NEW_EVENT" in body
            frame = json.loads(body.split(b"data: ", 1)[1].split(b"\n\n", 1)[0])
            assert frame["event"] == "GUI_QUESTION_QUEUE_UPDATED"
            assert frame["marker"] == "REAL_NEW_EVENT"
        finally:
            sock.close()
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_stream_since_param_replays_the_named_backlog():
    """An explicit ?since= (the real ISO ts of an already-recorded event) is
    the one deliberate way to ask for backlog -- a reconnecting client's own
    resume mechanism, proven against a REAL prior emit()."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_host, base_port = "127.0.0.1", port
        _start_dashboard(tmp)
        _wait_ready(f"http://{base_host}:{base_port}")

        from dv_harness import live_event_model
        from dv_harness.storage import StateStore

        store = StateStore(tmp)
        rec = live_event_model.emit(store, "GUI_STAGE_TRANSITIONED",
                                     source="test", marker="REPLAYED_ON_REQUEST")
        since = urllib.parse.quote(rec["ts"], safe="")

        sock = _sse_connect(base_host, base_port, f"/api/events/stream?since={since}")
        try:
            body = _wait_for(sock, b"REPLAYED_ON_REQUEST", 6.0)
            assert b"REPLAYED_ON_REQUEST" in body
        finally:
            sock.close()
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_stream_over_a_project_with_no_gui_live_events_ever_stays_open_and_sends_nothing():
    """The Evidence Truth Rule's negative control: a project that has never
    recorded a GUI live event at all (list_gui_live_events()'s own honest
    NO_GUI_LIVE_EVENTS_RECORDED case) must never have this route fabricate
    one -- the connection stays open, real SSE headers come back, and no
    `data:` frame is ever sent."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_host, base_port = "127.0.0.1", port
        _start_dashboard(tmp)
        _wait_ready(f"http://{base_host}:{base_port}")

        sock = _sse_connect(base_host, base_port, "/api/events/stream")
        try:
            collected = _read_for(sock, 2.5)
            assert b"200" in collected.split(b"\r\n", 1)[0]
            assert b"text/event-stream" in collected
            assert b"data:" not in collected  # honest empty state, never a fabricated event
        finally:
            sock.close()
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_stream_delivers_multiple_events_in_order():
    """Several real, distinct emit() calls are all delivered, oldest first --
    matching list_gui_live_events()'s own documented order."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_host, base_port = "127.0.0.1", port
        _start_dashboard(tmp)
        _wait_ready(f"http://{base_host}:{base_port}")

        from dv_harness import live_event_model
        from dv_harness.storage import StateStore

        store = StateStore(tmp)
        sock = _sse_connect(base_host, base_port, "/api/events/stream")
        try:
            time.sleep(0.2)
            live_event_model.emit(store, "GUI_APPROVAL_RECORDED", source="t", marker="ONE")
            live_event_model.emit(store, "GUI_COVERAGE_SAMPLE_INGESTED", source="t", marker="TWO")
            body = _wait_for(sock, b"TWO", 6.0)
            assert b"ONE" in body and b"TWO" in body
            assert body.index(b"ONE") < body.index(b"TWO")
        finally:
            sock.close()
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# --- Pure dedup-logic unit tests (deterministic, no HTTP/timing at all) -----
def test_new_gui_live_events_never_re_sends_or_drops_same_timestamp_events(monkeypatch):
    """live_event_model.list_gui_live_events()'s own since_ts bound is
    INCLUSIVE, so two poll cycles a moment apart can both legally include the
    same boundary event. _new_gui_live_events() must tell "already sent"
    apart from "genuinely new" among same-`ts` events without ever fabricating
    a duplicate delivery or silently dropping a real one."""
    from dv_harness import dashboard

    all_events = [
        {"ts": "T1", "event": "A"},
        {"ts": "T1", "event": "B"},
        {"ts": "T2", "event": "C"},
    ]

    def fake_list_gui_live_events(root, *, since_ts=None, **kwargs):
        picked = [e for e in all_events if since_ts is None or e["ts"] >= since_ts]
        return {"available": bool(picked), "events": picked}

    monkeypatch.setattr(
        "dv_harness.live_event_model.list_gui_live_events", fake_list_gui_live_events)

    root = Path("unused")  # never touched -- list_gui_live_events itself is faked

    # First poll: nothing sent yet -> everything is new.
    new, ts, seen = dashboard._new_gui_live_events(root, "", 0)
    assert [e["event"] for e in new] == ["A", "B", "C"]
    assert ts == "T2" and seen == 1

    # Simulate "only A (the first T1 event) already sent": since_ts=T1, seen=1.
    new, ts, seen = dashboard._new_gui_live_events(root, "T1", 1)
    assert [e["event"] for e in new] == ["B", "C"]  # A must not be re-sent

    # Simulate "both T1 events already sent": since_ts=T1, seen=2.
    new, ts, seen = dashboard._new_gui_live_events(root, "T1", 2)
    assert [e["event"] for e in new] == ["C"]

    # Simulate "everything through C already sent": since_ts=T2, seen=1.
    new, ts, seen = dashboard._new_gui_live_events(root, "T2", 1)
    assert new == []  # nothing new -- must never fabricate a repeat of C
    assert ts == "T2" and seen == 1


def test_new_gui_live_events_reports_nothing_when_nothing_recorded(monkeypatch):
    """The honest empty state: list_gui_live_events() reporting
    available=False/events=[] must produce no new events and must leave the
    watermark unchanged, never a fabricated one."""
    from dv_harness import dashboard

    def fake_list_gui_live_events(root, *, since_ts=None, **kwargs):
        return {"available": False, "events": [],
                "reason": "NO_GUI_LIVE_EVENTS_RECORDED: ..."}

    monkeypatch.setattr(
        "dv_harness.live_event_model.list_gui_live_events", fake_list_gui_live_events)

    new, ts, seen = dashboard._new_gui_live_events(Path("unused"), "2026-01-01T00:00:00+00:00", 3)
    assert new == []
    assert ts == "2026-01-01T00:00:00+00:00"  # unchanged
    assert seen == 3  # unchanged
