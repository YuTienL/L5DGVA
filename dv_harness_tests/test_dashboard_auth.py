"""GUI-19 -- the dashboard's mutating POST endpoints really refuse an
unauthenticated caller (2026-09-05 GUI completeness audit).

Before this, `dashboard.serve()`'s do_GET/do_POST had no authentication and no
permission check anywhere, while POST already exposed control-plane APPROVE /
COSIGN / TAKEOVER, waiver authoring, signoff-bundle export, policy writes,
uploads and harness start. Binding to 127.0.0.1 limits NETWORK reach; it is
not access control -- any local process could mint a real `APPROVAL` in this
project's control.json and a real approve event in its audit trail.

These tests are deliberately written to have DETECTION POWER rather than to
observe that a code path exists:

  - the negative cases assert the real SIDE EFFECT is absent afterward
    (ControlPlane.get_approval() is still None, no waiver file, no export
    directory), read straight off disk through the real modules -- a 403 that
    still performed the write would fail here;
  - each is paired with the SAME request carrying the real token, proving the
    action is genuinely reachable and that the negative case failed on
    authorization and not on some unrelated malformedness;
  - a wrong-token case sits beside the no-token case, so an implementation
    that merely required the header to be PRESENT would fail;
  - the token this suite presents is read out of
    .dv-harness/dashboard_session.json -- the same file the startup banner
    points a human at -- never handed over from inside the server process.

The real server is started for real on a free local port and driven over real
HTTP, reusing test_dashboard_interactive.py's own harness helpers rather than
standing up a second one (same cross-test convention as
test_dashboard_amba_card.py).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _post,
    _start_dashboard,
    _token_for,
    _wait_ready,
)

# Sent as the caller-supplied token where a request is meant to carry NONE.
# _post() treats "" as "send no credential at all".
NO_TOKEN = ""


def _up(dashboard_overrides: dict | None = None):
    port = _free_port()
    tmp = _mk_dashboard_project(port, dashboard_overrides=dashboard_overrides)
    base = f"http://127.0.0.1:{port}"
    _start_dashboard(tmp)
    _wait_ready(base)
    return tmp, base


def _approval(tmp: Path, stage: str = "SIGNOFF"):
    from dv_harness.control_plane import ControlPlane
    return ControlPlane(tmp).get_approval(stage)


# ---- the core proof: an unauthenticated APPROVE is genuinely refused -------

def test_unauthenticated_approve_is_rejected_and_writes_no_approval():
    tmp, base = _up()
    body = {"command": "APPROVE", "stage": "SIGNOFF", "note": "unauthenticated",
            "reviewer_id": "attacker", "reviewer_confidence": "HIGH"}

    status, data = _post(base, "/api/control", body, token=NO_TOKEN)
    assert status == 403, (status, data)
    assert data["error"] == "AUTH_REQUIRED", data
    assert data["reason"] == "MISSING_TOKEN", data

    # The real side effect must be absent -- this is the assertion that gives
    # the test its power. A 403 returned AFTER the write would fail here.
    assert _approval(tmp) is None, "an unauthenticated POST minted a real approval"


def test_same_approve_with_the_real_session_token_succeeds():
    """Pairs with the test above: proves the refusal was about authorization,
    not about the request being malformed in some other way."""
    tmp, base = _up()
    body = {"command": "APPROVE", "stage": "SIGNOFF", "note": "authorized",
            "reviewer_id": "dv-lead", "reviewer_confidence": "HIGH"}

    status, data = _post(base, "/api/control", body)  # token=None -> the real one
    assert status == 200, (status, data)

    entry = _approval(tmp)
    assert entry is not None
    assert entry["reviewer_id"] == "dv-lead"
    assert entry["note"] == "authorized"


def test_wrong_token_is_rejected_not_merely_a_present_header():
    """An implementation that only checked the header EXISTS would pass the
    no-token test above and fail this one."""
    tmp, base = _up()
    body = {"command": "APPROVE", "stage": "SIGNOFF", "note": "wrong token",
            "reviewer_id": "attacker", "reviewer_confidence": "HIGH"}

    status, data = _post(base, "/api/control", body, token="not-the-real-token")
    assert status == 403, (status, data)
    assert data["reason"] == "INVALID_TOKEN", data
    assert _approval(tmp) is None


def test_one_dashboards_token_does_not_authorize_another():
    """Tokens are per-process, not a shared secret: a token minted for one
    project/dashboard must not act on a different one."""
    tmp_a, base_a = _up()
    tmp_b, base_b = _up()
    token_a = _token_for(base_a)
    assert token_a and token_a != _token_for(base_b)

    status, data = _post(base_b, "/api/control",
                         {"command": "APPROVE", "stage": "SIGNOFF", "note": "cross",
                          "reviewer_id": "x", "reviewer_confidence": "HIGH"},
                         token=token_a)
    assert status == 403, (status, data)
    assert data["reason"] == "INVALID_TOKEN", data
    assert _approval(tmp_b) is None


# ---- the gate is deny-by-default across the whole POST surface ------------

def test_every_mutating_post_endpoint_refuses_an_unauthenticated_caller():
    """Enumerates the real do_POST branches. The check runs BEFORE path
    dispatch, so an unknown POST path is refused too (403, not 404) -- that is
    the property that makes a POST endpoint added later gated by existing."""
    tmp, base = _up()
    endpoints = [
        ("/api/setup", {"db_path": "/tmp/db", "working_path": "/tmp/w"}),
        ("/api/start", {"goal": "verify usb", "loop": False}),
        ("/api/control", {"command": "PAUSE", "reason": "x"}),
        ("/api/config", {"key": "require_dv_review_cosign", "value": True}),
        ("/api/session/save", {"name": "snap"}),
        ("/api/session/restore", {"name": "snap"}),
        ("/api/upload", {"category": "spec", "filename": "a.txt", "content_b64": "aGk="}),
        ("/api/signoff-export", {}),
        ("/api/waiver", {"gate_id": "g", "item_id": "i", "approved": True, "evidence": "e"}),
        ("/api/not-a-real-endpoint", {}),
    ]
    for path, body in endpoints:
        status, data = _post(base, path, body, token=NO_TOKEN)
        assert status == 403, f"{path} was not refused: {status} {data}"
        assert data["error"] == "AUTH_REQUIRED", (path, data)

    # None of them performed its write.
    assert not (tmp / ".dv-harness" / "project_meta.json").exists()
    assert not (tmp / ".dv-harness" / "waivers").exists()
    assert not (tmp / ".dv-harness" / "uploads").exists()
    assert not (tmp / ".dv-harness" / "signoff-export").exists()
    cfg = json.loads((tmp / ".dv-harness" / "config.json").read_text(encoding="utf-8"))
    assert "require_dv_review_cosign" not in cfg.get("policy", {})


def test_unauthenticated_waiver_and_signoff_export_write_nothing():
    tmp, base = _up()
    status, _ = _post(base, "/api/waiver",
                      {"gate_id": "assertion_placeholder_closure_gate",
                       "item_id": "ITEM-1", "approved": True, "evidence": "none"},
                      token=NO_TOKEN)
    assert status == 403
    from dv_harness import waiver_store
    assert waiver_store.read_waivers(tmp) == []

    # ...and the same request with the real token really does land, so the
    # refusal above is a refusal and not a broken endpoint.
    status, data = _post(base, "/api/waiver",
                         {"gate_id": "assertion_placeholder_closure_gate",
                          "item_id": "ITEM-1", "approved": True, "evidence": "log line 42"})
    assert status == 200, (status, data)
    assert len(waiver_store.read_waivers(tmp)) == 1


# ---- token transport: header, bearer, query --------------------------------

def test_token_is_accepted_via_bearer_header_and_via_query_string():
    tmp, base = _up()
    token = _token_for(base)

    # Authorization: Bearer -- an ordinary HTTP client with no custom header.
    req = urllib.request.Request(
        base + "/api/control",
        data=json.dumps({"command": "PAUSE", "reason": "bearer"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 200

    # ?token=... -- the form the startup URL carries.
    status, data = _post(base, "/api/control?token=" + token,
                         {"command": "RESUME"}, token=NO_TOKEN)
    assert status == 200, (status, data)


# ---- read-only GETs stay open; the page never leaks the token -------------

def test_read_only_get_endpoints_are_not_gated():
    tmp, base = _up()
    for path in ("/api/state", "/api/stats", "/api/audit?limit=5", "/api/memory"):
        status, _ = _get(base, path)
        assert status == 200, path


def test_served_html_does_not_contain_the_session_token():
    """The page is served to anyone who can reach the port. If the token were
    embedded in it, the whole gate would be decorative -- a rogue local
    process would just GET / and read it."""
    tmp, base = _up()
    with urllib.request.urlopen(base + "/", timeout=10) as resp:
        html = resp.read().decode("utf-8")
    token = _token_for(base)
    assert token and token not in html


def test_session_file_carries_the_live_token_and_is_freshly_minted():
    from dv_harness import dashboard_auth
    tmp, base = _up()
    rec = dashboard_auth.read_session_record(tmp)
    assert rec is not None
    assert isinstance(rec["token"], str) and len(rec["token"]) >= 32
    assert rec["pid"] and rec["issued_at"]
    assert dashboard_auth.session_file(tmp).name == dashboard_auth.SESSION_FILENAME


def test_denial_is_recorded_on_the_real_audit_trail():
    tmp, base = _up()
    _post(base, "/api/control", {"command": "APPROVE", "stage": "SIGNOFF",
                                  "reviewer_id": "x", "reviewer_confidence": "HIGH"},
          token=NO_TOKEN)
    events = [json.loads(l) for l in
              (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    denials = [e for e in events if e.get("event") == "DASHBOARD_AUTH_DENIED"]
    assert denials, events
    assert denials[-1]["path"] == "/api/control"
    assert denials[-1]["reason"] == "MISSING_TOKEN"


# ---- the config escape hatch, and the fail-closed default ------------------

def test_require_auth_false_opens_posts_and_is_an_explicit_opt_in():
    tmp, base = _up(dashboard_overrides={"require_auth": False})
    status, data = _post(base, "/api/control",
                         {"command": "APPROVE", "stage": "SIGNOFF", "note": "kiosk",
                          "reviewer_id": "kiosk", "reviewer_confidence": "HIGH"},
                         token=NO_TOKEN)
    assert status == 200, (status, data)
    assert _approval(tmp) is not None


def test_require_auth_defaults_to_true_in_the_shipped_config():
    from dv_harness.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["dashboard"]["require_auth"] is True


def test_authorize_fails_closed_when_no_token_was_ever_issued():
    """A server with no credential in existence must REFUSE, never fall
    through to 'nothing to compare, so allow'."""
    from dv_harness import dashboard_auth
    allowed, reason = dashboard_auth.authorize("", {}, "/api/control", method="POST")
    assert allowed is False
    assert reason == "NO_SESSION_TOKEN_ISSUED"


def test_authorize_does_not_gate_read_only_methods():
    from dv_harness import dashboard_auth
    allowed, reason = dashboard_auth.authorize("tok", {}, "/api/state", method="GET")
    assert allowed is True
    assert reason == "METHOD_NOT_GATED"
    assert set(dashboard_auth.GATED_METHODS) >= {"POST", "PUT", "PATCH", "DELETE"}
