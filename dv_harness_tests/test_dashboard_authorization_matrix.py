"""PC-6 -- the dashboard has a per-ACTION per-ROLE authorization matrix, and a
VIEWER token really cannot do what an APPROVER token can (2026-09-06).

GUI-19 (test_dashboard_auth.py, commit 08a61df) closed authentication: a
mutating POST must carry this dashboard process's session token. It could not
close AUTHORIZATION, because there was exactly ONE token and it authorized
every mutating endpoint equally -- whoever could watch the run could also mint
a real APPROVAL in control.json, author a waiver, flip a policy gate and export
a signoff bundle. These tests prove the role split is real, not decorative:

  - every negative case asserts the real SIDE EFFECT is absent afterward
    (ControlPlane.get_approval() still None, waiver_store still empty, no
    project_meta.json, config.json unchanged), read off disk through the real
    modules -- a 403 that still performed the write would fail here;
  - every negative case is PAIRED with the identical request carrying a
    higher-role token, which really lands -- so the refusal is provably about
    the role and not about the request being malformed in some other way;
  - the tokens are read out of .dv-harness/dashboard_session.json, the same
    file GUI-19's startup banner points a human at, never handed over from
    inside the server process;
  - the matrix is held against dashboard.py's REAL dispatch (both the do_POST
    endpoint branches and _dispatch_control's commands), so an action added
    later cannot quietly sit outside it.

The real server is started for real on a free local port and driven over real
HTTP, reusing test_dashboard_interactive.py's harness helpers rather than
standing up a second one -- the same cross-test convention
test_dashboard_auth.py already follows.
"""
from __future__ import annotations

import json
from pathlib import Path

from dv_harness import dashboard_auth
from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _post,
    _start_dashboard,
    _wait_ready,
    _PROJECT_ROOT_BY_PORT,
)

VIEWER = dashboard_auth.VIEWER
OPERATOR = dashboard_auth.OPERATOR
APPROVER = dashboard_auth.APPROVER


def _up(dashboard_overrides: dict | None = None):
    port = _free_port()
    tmp = _mk_dashboard_project(port, dashboard_overrides=dashboard_overrides)
    base = f"http://127.0.0.1:{port}"
    _start_dashboard(tmp)
    _wait_ready(base)
    return tmp, base


def _role_token(base: str, role: str) -> str:
    """This server's real token for `role`, read off disk exactly as the human
    who was handed it would."""
    root = _PROJECT_ROOT_BY_PORT[int(base.rsplit(":", 1)[1])]
    tok = dashboard_auth.read_role_tokens(root)[role]
    assert tok
    return tok


def _approval(tmp: Path, stage: str = "SIGNOFF"):
    from dv_harness.control_plane import ControlPlane
    return ControlPlane(tmp).get_approval(stage)


def _approve_body(note: str, reviewer: str):
    return {"command": "APPROVE", "stage": "SIGNOFF", "note": note,
            "reviewer_id": reviewer, "reviewer_confidence": "HIGH"}


# ---- the headline proof: VIEWER refused, APPROVER accepted, same request ---

def test_viewer_token_cannot_approve_and_mints_no_approval():
    """The gap PC-6 closes, stated as one test: a token that is legitimately
    authenticated for this dashboard is still refused the one action that
    writes a human decision into this project's audit trail."""
    tmp, base = _up()

    status, data = _post(base, "/api/control", _approve_body("viewer tried", "viewer"),
                         token=_role_token(base, VIEWER))
    assert status == 403, (status, data)
    assert data["error"] == "ROLE_NOT_PERMITTED", data
    assert data["reason"] == dashboard_auth.ROLE_DENIED_REASON, data
    assert data["role"] == VIEWER and data["required_role"] == APPROVER, data
    assert data["action"] == "POST /api/control APPROVE", data

    # The assertion with the detection power: the write did NOT happen.
    assert _approval(tmp) is None, "a VIEWER token minted a real approval"


def test_the_same_approve_with_the_approver_token_really_lands():
    """Pairs with the test above -- proves the refusal was about the ROLE, not
    about the request being malformed or the endpoint being broken."""
    tmp, base = _up()

    status, data = _post(base, "/api/control", _approve_body("approved", "dv-lead"),
                         token=_role_token(base, APPROVER))
    assert status == 200, (status, data)

    entry = _approval(tmp)
    assert entry is not None
    assert entry["reviewer_id"] == "dv-lead"
    assert entry["note"] == "approved"


def test_operator_token_cannot_approve_either():
    """OPERATOR is not a weaker APPROVER: running the harness and signing off
    on it are different authorities, which is the whole point of three roles
    rather than authenticated/not."""
    tmp, base = _up()
    status, data = _post(base, "/api/control", _approve_body("operator tried", "operator"),
                         token=_role_token(base, OPERATOR))
    assert status == 403, (status, data)
    assert data["role"] == OPERATOR and data["required_role"] == APPROVER, data
    assert _approval(tmp) is None


def test_operator_may_pause_the_run_on_the_same_endpoint():
    """The matrix is per-ACTION, not per-endpoint: /api/control carries both
    'pause the run' (OPERATOR) and 'approve SIGNOFF' (APPROVER), and the same
    OPERATOR token is accepted for one and refused for the other."""
    tmp, base = _up()
    token = _role_token(base, OPERATOR)

    status, data = _post(base, "/api/control", {"command": "PAUSE", "reason": "coffee"},
                         token=token)
    assert status == 200, (status, data)

    from dv_harness.control_plane import ControlPlane
    assert ControlPlane(tmp).is_paused() is True

    # ...and the identical token still cannot approve.
    status, data = _post(base, "/api/control", _approve_body("nope", "operator"), token=token)
    assert status == 403, (status, data)
    assert _approval(tmp) is None


def test_viewer_cannot_even_pause():
    """VIEWER authorizes NO mutating action -- reading is what GET is for, and
    GET was never gated."""
    tmp, base = _up()
    status, data = _post(base, "/api/control", {"command": "PAUSE", "reason": "x"},
                         token=_role_token(base, VIEWER))
    assert status == 403, (status, data)
    assert data["required_role"] == OPERATOR, data

    from dv_harness.control_plane import ControlPlane
    assert ControlPlane(tmp).is_paused() is False


# ---- the approver-only endpoints -------------------------------------------

def test_waiver_authoring_is_approver_only_and_writes_nothing_below_it():
    tmp, base = _up()
    from dv_harness import waiver_store
    body = {"gate_id": "assertion_placeholder_closure_gate", "item_id": "ITEM-1",
            "approved": True, "evidence": "log line 42"}

    for role in (VIEWER, OPERATOR):
        status, data = _post(base, "/api/waiver", body, token=_role_token(base, role))
        assert status == 403, (role, status, data)
        assert data["required_role"] == APPROVER, (role, data)
    assert waiver_store.read_waivers(tmp) == [], "a sub-approver role authored a waiver"

    status, data = _post(base, "/api/waiver", body, token=_role_token(base, APPROVER))
    assert status == 200, (status, data)
    assert len(waiver_store.read_waivers(tmp)) == 1


def test_policy_write_is_approver_only_and_config_is_untouched_below_it():
    tmp, base = _up()
    cfg_path = tmp / ".dv-harness" / "config.json"
    body = {"key": "require_dv_review_cosign", "value": True}

    status, data = _post(base, "/api/config", body, token=_role_token(base, OPERATOR))
    assert status == 403, (status, data)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "require_dv_review_cosign" not in cfg.get("policy", {})

    status, data = _post(base, "/api/config", body, token=_role_token(base, APPROVER))
    assert status == 200, (status, data)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["policy"]["require_dv_review_cosign"] is True


def test_signoff_export_is_approver_only():
    tmp, base = _up()
    status, data = _post(base, "/api/signoff-export", {}, token=_role_token(base, OPERATOR))
    assert status == 403, (status, data)
    assert data["required_role"] == APPROVER, data
    assert not (tmp / ".dv-harness" / "signoff-export").exists()


def test_research_approve_is_approver_only():
    """The Research card's Approve button routes through the same
    /api/control dispatch as `dv-harness approve RESEARCH_CAPABILITY_EVOLUTION`,
    so it must be gated at the same level as a stage APPROVE."""
    tmp, base = _up()
    body = {"command": "RESEARCH_APPROVE", "candidate_id": "CAND-1",
            "note": "looks good", "reviewer_id": "x", "reviewer_confidence": "HIGH"}
    status, data = _post(base, "/api/control", body, token=_role_token(base, OPERATOR))
    assert status == 403, (status, data)
    assert data["required_role"] == APPROVER, data
    assert data["action"] == "POST /api/control RESEARCH_APPROVE", data


# ---- the operator-only endpoints -------------------------------------------

def test_setup_is_operator_work_and_a_viewer_cannot_do_it():
    tmp, base = _up()
    body = {"db_path": str(tmp / "db"), "working_path": str(tmp / "w")}

    status, data = _post(base, "/api/setup", body, token=_role_token(base, VIEWER))
    assert status == 403, (status, data)
    assert data["required_role"] == OPERATOR, data
    assert not (tmp / ".dv-harness" / "project_meta.json").exists()

    status, data = _post(base, "/api/setup", body, token=_role_token(base, OPERATOR))
    assert status == 200, (status, data)
    assert (tmp / ".dv-harness" / "project_meta.json").exists()


# ---- deny-by-default: an unmapped action requires the HIGHEST role ---------

def test_an_unknown_post_endpoint_requires_approver_not_operator():
    """The property that makes an endpoint added later gated by EXISTING: it
    is refused for everything below APPROVER, and only an APPROVER gets far
    enough to be told it does not exist."""
    tmp, base = _up()

    status, data = _post(base, "/api/not-a-real-endpoint", {}, token=_role_token(base, OPERATOR))
    assert status == 403, (status, data)
    assert data["error"] == "ROLE_NOT_PERMITTED", data
    assert data["required_role"] == APPROVER, data

    status, data = _post(base, "/api/not-a-real-endpoint", {}, token=_role_token(base, APPROVER))
    assert status == 404, (status, data)


def test_an_unknown_control_command_requires_approver_not_operator():
    tmp, base = _up()

    status, data = _post(base, "/api/control", {"command": "SOME_NEW_VERB"},
                         token=_role_token(base, OPERATOR))
    assert status == 403, (status, data)
    assert data["required_role"] == APPROVER, data

    status, data = _post(base, "/api/control", {"command": "SOME_NEW_VERB"},
                         token=_role_token(base, APPROVER))
    assert status == 400, (status, data)
    assert "Unknown command" in data["message"], data


def test_an_unreadable_control_body_requires_approver_and_still_400s_for_one():
    """Not knowing WHICH command a request carries is a reason to demand more
    authority, never less -- and an authorized caller still gets the handler's
    own 400 for the same malformedness."""
    tmp, base = _up()

    status, data = _post(base, "/api/control", b"{not json",
                         token=_role_token(base, OPERATOR))
    assert status == 403, (status, data)
    assert data["required_role"] == APPROVER, data

    status, data = _post(base, "/api/control", b"{not json",
                         token=_role_token(base, APPROVER))
    assert status == 400, (status, data)


# ---- the body is read once: the gate's peek must not eat the payload -------

def test_the_role_peek_does_not_consume_the_body_the_handler_needs():
    """The gate reads /api/control's `command` before dispatch. If that read
    were not cached, every authorized control request would arrive with an
    EMPTY body and fail on a missing field -- so this asserts a real APPROVE's
    own arguments (note, reviewer_id) survived the peek."""
    tmp, base = _up()
    status, data = _post(base, "/api/control",
                         _approve_body("body survived the peek", "peek-reviewer"),
                         token=_role_token(base, APPROVER))
    assert status == 200, (status, data)
    entry = _approval(tmp)
    assert entry["note"] == "body survived the peek"
    assert entry["reviewer_id"] == "peek-reviewer"


# ---- GUI-19's authentication half is untouched ------------------------------

def test_no_token_at_all_is_still_an_auth_failure_not_a_role_failure():
    tmp, base = _up()
    status, data = _post(base, "/api/control", _approve_body("none", "x"), token="")
    assert status == 403, (status, data)
    assert data["error"] == "AUTH_REQUIRED", data
    assert data["reason"] == "MISSING_TOKEN", data
    assert _approval(tmp) is None


def test_a_token_that_is_no_role_is_still_INVALID_TOKEN():
    tmp, base = _up()
    status, data = _post(base, "/api/control", _approve_body("wrong", "x"),
                         token="not-any-of-the-three")
    assert status == 403, (status, data)
    assert data["reason"] == "INVALID_TOKEN", data
    assert _approval(tmp) is None


def test_read_only_gets_stay_open_for_everyone():
    tmp, base = _up()
    for path in ("/api/state", "/api/stats", "/api/audit?limit=5"):
        status, _ = _get(base, path)
        assert status == 200, path


def test_the_startup_banner_token_is_the_approver_token():
    """Backwards compatibility, asserted rather than assumed: the URL the
    dashboard prints and everything read_session_token() returns keep FULL
    authority, so no pre-PC-6 flow lost anything."""
    tmp, base = _up()
    assert dashboard_auth.read_session_token(tmp) == _role_token(base, APPROVER)


def test_the_session_record_carries_three_distinct_role_tokens():
    tmp, base = _up()
    rec = dashboard_auth.read_session_record(tmp)
    tokens = rec[dashboard_auth.ROLE_TOKENS_KEY]
    assert set(tokens) == set(dashboard_auth.ROLES)
    assert len(set(tokens.values())) == 3, "a role reused another role's token"
    for tok in tokens.values():
        assert isinstance(tok, str) and len(tok) >= 32
    assert rec["token"] == tokens[APPROVER]


def test_role_denial_is_recorded_on_the_real_audit_trail():
    tmp, base = _up()
    _post(base, "/api/control", _approve_body("audited", "viewer"),
          token=_role_token(base, VIEWER))
    events = [json.loads(l) for l in
              (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()
              if l.strip()]
    denials = [e for e in events if e.get("event") == "DASHBOARD_AUTH_DENIED"]
    assert denials, events
    last = denials[-1]
    assert last["reason"] == dashboard_auth.ROLE_DENIED_REASON
    assert last["path"] == "/api/control"
    assert last["role"] == VIEWER and last["required_role"] == APPROVER
    assert last["action"] == "POST /api/control APPROVE"


def test_require_auth_false_still_opens_everything_unchanged():
    """The kiosk escape hatch is GUI-19's and is deliberately not narrowed:
    turning authentication off turns the role matrix off with it, because
    there is then no credential to carry a role."""
    tmp, base = _up(dashboard_overrides={"require_auth": False})
    status, data = _post(base, "/api/control", _approve_body("kiosk", "kiosk"), token="")
    assert status == 200, (status, data)
    assert _approval(tmp) is not None


# ---- the matrix itself: shape, ordering and drift --------------------------

def test_roles_are_ordered_and_approver_is_a_superset_of_operator():
    assert dashboard_auth.ROLES == (VIEWER, OPERATOR, APPROVER)
    ranks = dashboard_auth.ROLE_RANK
    assert ranks[VIEWER] < ranks[OPERATOR] < ranks[APPROVER]


def test_no_mutating_action_is_reachable_by_a_viewer():
    """VIEWER exists to be told no. If any action mapped to it, the role would
    be a mutating one wearing a read-only name."""
    required = (list(dashboard_auth.ENDPOINT_REQUIRED_ROLE.values())
                + list(dashboard_auth.CONTROL_COMMAND_REQUIRED_ROLE.values())
                + [dashboard_auth.UNMAPPED_ACTION_ROLE])
    assert VIEWER not in required


def test_the_unmapped_fallback_is_the_highest_role():
    assert dashboard_auth.UNMAPPED_ACTION_ROLE == APPROVER


def test_matrix_covers_every_real_post_endpoint_dashboard_dispatches():
    """Read off dashboard.py's own do_POST source, so adding an endpoint
    without classifying it fails here rather than silently inheriting a
    default."""
    dashboard_auth.assert_endpoints_mapped()
    assert dashboard_auth.dispatched_post_endpoints() == set(
        dashboard_auth.ENDPOINT_REQUIRED_ROLE)


def test_matrix_covers_every_real_control_command_dashboard_dispatches():
    dashboard_auth.assert_control_commands_mapped()
    assert dashboard_auth.dispatched_control_commands() == set(
        dashboard_auth.CONTROL_COMMAND_REQUIRED_ROLE)


def test_the_drift_guards_really_trip():
    """Negative control for the two guards above: without this, a guard that
    silently passed on everything would look identical."""
    import pytest
    original = dict(dashboard_auth.CONTROL_COMMAND_REQUIRED_ROLE)
    try:
        dashboard_auth.CONTROL_COMMAND_REQUIRED_ROLE.pop("APPROVE")
        with pytest.raises(dashboard_auth.DashboardRoleMatrixError):
            dashboard_auth.assert_control_commands_mapped()
    finally:
        dashboard_auth.CONTROL_COMMAND_REQUIRED_ROLE.clear()
        dashboard_auth.CONTROL_COMMAND_REQUIRED_ROLE.update(original)

    original_ep = dict(dashboard_auth.ENDPOINT_REQUIRED_ROLE)
    try:
        dashboard_auth.ENDPOINT_REQUIRED_ROLE["/api/invented"] = APPROVER
        with pytest.raises(dashboard_auth.DashboardRoleMatrixError):
            dashboard_auth.assert_endpoints_mapped()
    finally:
        dashboard_auth.ENDPOINT_REQUIRED_ROLE.clear()
        dashboard_auth.ENDPOINT_REQUIRED_ROLE.update(original_ep)


# ---- resolve_role / authorize_detail, without a server ---------------------

def test_resolve_role_identifies_each_token_and_rejects_a_stranger():
    tokens = {VIEWER: "v" * 40, OPERATOR: "o" * 40, APPROVER: "a" * 40}
    assert dashboard_auth.resolve_role("v" * 40, tokens) == VIEWER
    assert dashboard_auth.resolve_role("o" * 40, tokens) == OPERATOR
    assert dashboard_auth.resolve_role("a" * 40, tokens) == APPROVER
    assert dashboard_auth.resolve_role("z" * 40, tokens) is None
    assert dashboard_auth.resolve_role("", tokens) is None
    assert dashboard_auth.resolve_role("v" * 40, None) is None


def test_a_caller_with_no_role_map_keeps_full_pre_pc6_authority():
    """authorize() with role_tokens=None is GUI-19's exact behaviour: one
    token, and it is the full-authority one. A pre-PC-6 session file (which
    carries `token` and no role map) therefore still approves."""
    headers = {dashboard_auth.TOKEN_HEADER: "tok"}
    allowed, reason = dashboard_auth.authorize(
        "tok", headers, "/api/control", method="POST", control_command="APPROVE")
    assert allowed is True and reason == "OK"

    d = dashboard_auth.authorize_detail("tok", headers, "/api/control",
                                        control_command="APPROVE")
    assert d["role"] == APPROVER and d["required_role"] == APPROVER


def test_read_role_tokens_never_invents_a_role_the_session_never_minted(tmp_path):
    """A session file written before PC-6 carries `token` only. Reporting a
    fabricated VIEWER credential for it would hand out a token that
    authenticates as nothing."""
    d = tmp_path / ".dv-harness"
    d.mkdir(parents=True)
    (d / dashboard_auth.SESSION_FILENAME).write_text(
        json.dumps({"token": "legacy-token", "issued_at": 1, "pid": 1}), encoding="utf-8")
    assert dashboard_auth.read_role_tokens(tmp_path) == {APPROVER: "legacy-token"}


def test_required_role_lookups_match_the_declared_matrix():
    assert dashboard_auth.required_role("/api/waiver")[0] == APPROVER
    assert dashboard_auth.required_role("/api/start")[0] == OPERATOR
    assert dashboard_auth.required_role("/api/control", "PAUSE")[0] == OPERATOR
    assert dashboard_auth.required_role("/api/control", "COSIGN")[0] == APPROVER
    assert dashboard_auth.required_role("/api/control", None)[0] == APPROVER
    # The query string is not part of the action -- the token legitimately
    # arrives as ?token=... on the URL GUI-19's banner prints.
    assert dashboard_auth.required_role("/api/start?token=abc")[0] == OPERATOR
