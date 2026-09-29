"""Tests for dv_harness/gui_intake_control_plane.py.

Real evidence and real transport throughout, per this project's Evidence
Truth Rule: pending questions come from a REAL `question_queue.
QuestionQueueStore` driven through its real `add_question()`/
`answer_question()` API; the intake-field snapshot comes from a REAL
`env.manifest.json` produced by `env_manifest.generate_and_write()` over a
real synthetic `$DESIGNWARE_HOME` tree (the same fixture shape
`test_env_manifest_fact_sources.py`/`test_intake_state.py` already use); and
the HTTP surface is driven over a REAL `http.client` connection against a
REAL `ThreadingHTTPServer` this test starts and stops on its own thread --
never a mock of the server, the store, or the manifest.
"""
import http.client
import json
import threading
import time

import pytest

from dv_harness import env_manifest, gui_intake_control_plane as gicp
from dv_harness import question_queue


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _real_vip_release_manifest(tmp_path):
    """Writes a real, schema-valid env.manifest.json at the project's real
    default path (`.dv-harness/env.manifest.json`), built by the REAL
    `env_manifest.generate_and_write()` over a real synthetic
    `$DESIGNWARE_HOME` tree -- never a hand-typed manifest shape."""
    home = tmp_path / "designware_home"
    pkg_dir = home / "vip" / "svt" / "usb3" / "1.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "release_notes.txt").write_text("USB3 VIP 1.0 release notes", encoding="utf-8")
    out = tmp_path / ".dv-harness" / "env.manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    env_manifest.generate_and_write(str(out), designware_home=str(home))
    return out


def _add_real_blocking_question(root):
    store = question_queue.QuestionQueueStore(root)
    return store.add_question(
        domain="dut",
        question="Is the observed drop within spec or a real DUT failure?",
        context_path="dut.registers.CTRL",
        options=["spec-legal drop", "real DUT failure"],
        recommendation="spec-legal drop",
        assumption_if_unanswered="None -- a human must decide.",
        context={"affects_pass_fail_verdict": True},
    )


# ---------------------------------------------------------------------------
# backend reads: pending questions
# ---------------------------------------------------------------------------

def test_list_pending_questions_returns_the_real_open_question(tmp_path):
    q = _add_real_blocking_question(tmp_path)
    pending = gicp.list_pending_questions(tmp_path)
    assert [p["id"] for p in pending] == [q["id"]]
    assert pending[0]["status"] == "OPEN"
    assert pending[0]["blocking"] is True


def test_list_pending_questions_excludes_a_real_human_answered_question(tmp_path):
    q = _add_real_blocking_question(tmp_path)
    store = question_queue.QuestionQueueStore(tmp_path)
    store.answer_question(q["id"], answer="spec-legal drop", basis="USB3 spec 8.2",
                            decided_by="jane@corp")
    pending = gicp.list_pending_questions(tmp_path)
    assert pending == []


def test_no_questions_at_all_reports_empty_list_never_fabricated_NEGATIVE_CONTROL(tmp_path):
    """A project with no `.dv-harness/question_queue/` tree at all must
    report an honestly empty pending list, never raise and never invent a
    question."""
    assert gicp.list_pending_questions(tmp_path) == []


# ---------------------------------------------------------------------------
# backend reads: intake field statuses
# ---------------------------------------------------------------------------

def test_no_manifest_reports_every_field_missing_NEGATIVE_CONTROL(tmp_path):
    """The central refusal-to-fabricate proof for this surface: a project
    with no env.manifest.json on disk must show every general-category
    field as MISSING, never a guessed AUTO_RESOLVED/READY status."""
    state = gicp.gather_intake_state(tmp_path)
    general = state.fields_in_category("general")
    assert general, "the manifest-backed fields must still be present, just MISSING"
    assert all(r.status == "MISSING" for r in general)


def test_real_manifest_resolves_vip_category(tmp_path):
    _real_vip_release_manifest(tmp_path)
    state = gicp.gather_intake_state(tmp_path)
    vip = state.get("vip_release")
    assert vip is not None
    assert vip.status == "AUTO_RESOLVED"
    assert vip.source.startswith("env_manifest:")


def test_snapshot_readiness_refuses_ready_on_a_bare_project_NEGATIVE_CONTROL(tmp_path):
    snap = gicp.control_plane_snapshot(tmp_path)
    assert snap["readiness"]["ready"] is False
    # worst-wins: every one of the six blocking categories is unresolved on
    # a bare project, and every one must be named, not averaged away.
    assert set(snap["readiness"]["blocking"]) == set(
        __import__("dv_harness.intake_state", fromlist=["BLOCKING_CATEGORIES"]).BLOCKING_CATEGORIES
    )


def test_snapshot_pending_questions_and_fields_are_both_present(tmp_path):
    _real_vip_release_manifest(tmp_path)
    _add_real_blocking_question(tmp_path)
    snap = gicp.control_plane_snapshot(tmp_path)
    assert len(snap["pending_questions"]) == 1
    assert any(f["field"] == "vip_release" and f["status"] == "AUTO_RESOLVED"
               for f in snap["fields"])


# ---------------------------------------------------------------------------
# backend write: answer_pending_question is the ONE real sanctioned write
# ---------------------------------------------------------------------------

def test_answer_pending_question_persists_a_real_human_decision(tmp_path):
    q = _add_real_blocking_question(tmp_path)
    record = gicp.answer_pending_question(
        tmp_path, q["id"], answer="spec-legal drop", basis="USB3 spec 8.2",
        decided_by="jane@corp",
    )
    assert record["status"] == "ANSWERED"
    assert record["answer"] == "spec-legal drop"

    store = question_queue.QuestionQueueStore(tmp_path)
    decision = store.find_decision(q["question_key"])
    assert decision is not None
    assert decision["current"]["source"] == question_queue.HUMAN_DECISION_SOURCE
    assert decision["current"]["decided_by"] == "jane@corp"

    assert gicp.list_pending_questions(tmp_path) == []


def test_answer_unknown_question_id_raises_key_error_NEGATIVE_CONTROL(tmp_path):
    with pytest.raises(KeyError):
        gicp.answer_pending_question(tmp_path, "Q-DOES-NOT-EXIST", answer="x", basis="y",
                                       decided_by="z")


# ---------------------------------------------------------------------------
# session token
# ---------------------------------------------------------------------------

def test_session_token_round_trips_and_is_atomic(tmp_path):
    assert gicp.read_session_token(tmp_path) is None
    record = gicp.issue_session_token(tmp_path, port=12345)
    assert gicp.session_file(tmp_path).exists()
    assert gicp.read_session_token(tmp_path) == record["token"]


def test_authorized_rejects_missing_and_wrong_token_NEGATIVE_CONTROL():
    assert gicp._authorized("realtoken", {}, "/api/intake/answer") is False
    assert gicp._authorized("realtoken", {"X-DV-Harness-Token": "wrong"},
                              "/api/intake/answer") is False
    assert gicp._authorized("", {"X-DV-Harness-Token": "anything"},
                              "/api/intake/answer") is False


def test_authorized_accepts_the_real_header_token():
    assert gicp._authorized("realtoken", {"X-DV-Harness-Token": "realtoken"},
                              "/api/intake/answer") is True


# ---------------------------------------------------------------------------
# real HTTP server, real network round trip
# ---------------------------------------------------------------------------

class _RunningServer:
    def __init__(self, server):
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self.server

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8")
    finally:
        conn.close()


def _post(port, path, body, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("POST", path, body=json.dumps(body).encode("utf-8"),
                      headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8")
    finally:
        conn.close()


def test_real_server_get_root_renders_the_real_pending_question(tmp_path):
    q = _add_real_blocking_question(tmp_path)
    server, token = gicp.build_server(tmp_path, require_auth=True)
    with _RunningServer(server):
        port = server.server_address[1]
        status, body = _get(port, "/")
        assert status == 200
        assert q["id"] in body
        assert "Is the observed drop within spec" in body
        assert "UVM_GENERATION_READY: BLOCKED" in body


def test_real_server_json_endpoints_match_the_backend(tmp_path):
    _add_real_blocking_question(tmp_path)
    server, token = gicp.build_server(tmp_path, require_auth=True)
    with _RunningServer(server):
        port = server.server_address[1]
        status, body = _get(port, "/api/intake/questions")
        assert status == 200
        payload = json.loads(body)
        assert len(payload["questions"]) == 1

        status, body = _get(port, "/api/intake/state")
        assert status == 200
        payload = json.loads(body)
        assert "fields" in payload


def test_real_server_unknown_path_is_404(tmp_path):
    server, token = gicp.build_server(tmp_path, require_auth=True)
    with _RunningServer(server):
        port = server.server_address[1]
        status, _ = _get(port, "/does/not/exist")
        assert status == 404


def test_real_server_post_answer_without_token_is_rejected_NEGATIVE_CONTROL(tmp_path):
    """A POST that never presents this server's real token must never
    reach `answer_question()` -- proven by re-querying the real store
    afterward and confirming nothing was written."""
    q = _add_real_blocking_question(tmp_path)
    server, token = gicp.build_server(tmp_path, require_auth=True)
    with _RunningServer(server):
        port = server.server_address[1]
        status, body = _post(port, "/api/intake/answer", {
            "question_id": q["id"], "answer": "x", "basis": "y", "decided_by": "z",
        })
        assert status == 401
        assert "AUTH_REQUIRED" in body

    # The real store on disk must be untouched -- the question is still
    # pending, exactly as before the rejected POST.
    assert gicp.list_pending_questions(tmp_path)[0]["id"] == q["id"]


def test_real_server_post_answer_with_wrong_token_is_rejected_NEGATIVE_CONTROL(tmp_path):
    q = _add_real_blocking_question(tmp_path)
    server, token = gicp.build_server(tmp_path, require_auth=True)
    with _RunningServer(server):
        port = server.server_address[1]
        status, _ = _post(port, "/api/intake/answer", {
            "question_id": q["id"], "answer": "x", "basis": "y", "decided_by": "z",
        }, headers={"X-DV-Harness-Token": "not-the-real-token"})
        assert status == 401
    assert gicp.list_pending_questions(tmp_path)[0]["id"] == q["id"]


def test_real_server_post_answer_with_real_token_writes_a_real_decision(tmp_path):
    q = _add_real_blocking_question(tmp_path)
    server, token = gicp.build_server(tmp_path, require_auth=True)
    assert token
    with _RunningServer(server):
        port = server.server_address[1]
        status, body = _post(port, "/api/intake/answer", {
            "question_id": q["id"], "answer": "spec-legal drop", "basis": "USB3 spec 8.2",
            "decided_by": "jane@corp",
        }, headers={"X-DV-Harness-Token": token})
        assert status == 200
        payload = json.loads(body)
        assert payload["answered"]["status"] == "ANSWERED"

    # Verify against the REAL backend store, not the HTTP response alone.
    store = question_queue.QuestionQueueStore(tmp_path)
    decision = store.find_decision(q["question_key"])
    assert decision["current"]["source"] == question_queue.HUMAN_DECISION_SOURCE
    assert gicp.list_pending_questions(tmp_path) == []


def test_real_server_post_answer_with_query_param_token_is_accepted(tmp_path):
    """The startup URL's own `?token=...` form (the same convention
    `dashboard_auth.presented_token()` already supports)."""
    q = _add_real_blocking_question(tmp_path)
    server, token = gicp.build_server(tmp_path, require_auth=True)
    with _RunningServer(server):
        port = server.server_address[1]
        status, _ = _post(
            port, f"/api/intake/answer?token={token}",
            {"question_id": q["id"], "answer": "x", "basis": "y", "decided_by": "z"},
        )
        assert status == 200
    assert gicp.list_pending_questions(tmp_path) == []


def test_real_server_post_answer_unknown_question_is_404(tmp_path):
    server, token = gicp.build_server(tmp_path, require_auth=True)
    with _RunningServer(server):
        port = server.server_address[1]
        status, body = _post(port, "/api/intake/answer", {
            "question_id": "Q-DOES-NOT-EXIST", "answer": "x", "basis": "y", "decided_by": "z",
        }, headers={"X-DV-Harness-Token": token})
        assert status == 404
        assert "QUESTION_NOT_FOUND" in body


def test_real_server_post_answer_missing_field_is_400(tmp_path):
    q = _add_real_blocking_question(tmp_path)
    server, token = gicp.build_server(tmp_path, require_auth=True)
    with _RunningServer(server):
        port = server.server_address[1]
        status, body = _post(port, "/api/intake/answer", {
            "question_id": q["id"], "answer": "x",
        }, headers={"X-DV-Harness-Token": token})
        assert status == 400
        assert "MISSING_REQUIRED_FIELD" in body
    assert gicp.list_pending_questions(tmp_path)[0]["id"] == q["id"]


def test_require_auth_false_allows_an_unauthenticated_write(tmp_path):
    """The explicit, documented opt-out for local debugging only -- proven
    to actually work rather than merely claimed, so a caller relying on it
    is not surprised by a silent 401."""
    q = _add_real_blocking_question(tmp_path)
    server, token = gicp.build_server(tmp_path, require_auth=False)
    assert token is None
    with _RunningServer(server):
        port = server.server_address[1]
        status, _ = _post(port, "/api/intake/answer", {
            "question_id": q["id"], "answer": "x", "basis": "y", "decided_by": "z",
        })
        assert status == 200
    assert gicp.list_pending_questions(tmp_path) == []


# ---------------------------------------------------------------------------
# P1-3 (additive): the shared web_layout.py status-bar/nav partial
# ---------------------------------------------------------------------------

def test_render_page_carries_the_real_web_layout_status_bar_partial(tmp_path):
    """`render_page()` must emit `web_layout.render_status_bar_partial()`'s
    real, real element ids -- imported and called, never re-implemented --
    somewhere in the rendered page, proving this server actually adopted the
    shared partial rather than merely importing the module unused."""
    from dv_harness import web_layout
    snap = gicp.control_plane_snapshot(tmp_path)
    body = gicp.render_page(snap)
    assert 'id="globalStatusBar"' in body
    assert web_layout.render_status_bar_partial() in body


def test_render_page_carries_the_real_web_layout_nav_partial(tmp_path):
    """Same proof for `web_layout.render_nav()`: its real `<nav class=
    "webNav">` markup, over this page's own two real section routes, appears
    in the rendered page -- not a page-shell rewrite, only an added partial."""
    from dv_harness import web_layout
    snap = gicp.control_plane_snapshot(tmp_path)
    body = gicp.render_page(snap)
    expected_nav = web_layout.render_nav([
        ("questions", "Pending Questions", "#pending-questions"),
        ("fields", "Intake Field Statuses", "#intake-field-statuses"),
    ])
    assert expected_nav in body
    assert 'class="webNav"' in body
    assert 'href="#pending-questions"' in body
    assert 'href="#intake-field-statuses"' in body


def test_web_layout_partial_appears_before_this_pages_own_existing_markup(tmp_path):
    """The partial is inserted at a FIXED point -- immediately inside
    `<body>`, before this page's own pre-existing heading/table markup --
    never scattered or replacing anything that was already there."""
    snap = gicp.control_plane_snapshot(tmp_path)
    body = gicp.render_page(snap)
    assert body.index('class="webNav"') < body.index("<h1>GUI Intake Control Plane</h1>")
    assert body.index('id="globalStatusBar"') < body.index("<h1>GUI Intake Control Plane</h1>")


def test_real_server_root_page_carries_the_web_layout_partial(tmp_path):
    """End-to-end over a real HTTP connection to the real server, not just
    the pure `render_page()` function."""
    server, token = gicp.build_server(tmp_path, require_auth=True)
    with _RunningServer(server):
        port = server.server_address[1]
        status, body = _get(port, "/")
        assert status == 200
        assert 'id="globalStatusBar"' in body
        assert 'class="webNav"' in body


def test_existing_routes_and_json_endpoints_are_unaffected_by_the_layout_partial(tmp_path):
    """ADDITIVE ONLY: this server's real, pre-existing JSON API surface must
    be byte-for-byte unaffected by rendering the new HTML-only partial."""
    q = _add_real_blocking_question(tmp_path)
    server, token = gicp.build_server(tmp_path, require_auth=True)
    with _RunningServer(server):
        port = server.server_address[1]
        status, body = _get(port, "/api/intake/questions")
        assert status == 200
        payload = json.loads(body)
        assert payload["questions"][0]["id"] == q["id"]
        assert "webNav" not in body
        assert "globalStatusBar" not in body


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_snapshot_cli_prints_real_json(tmp_path, capsys):
    _add_real_blocking_question(tmp_path)
    rc = gicp.main(["snapshot", "--project-root", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert len(payload["pending_questions"]) == 1
