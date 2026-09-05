"""GET /api/research + the Research / Capability Evolution card's three
governance actions (GUI-10, 2026-09-05 GUI completeness audit).

Before this, dashboard.py contained zero references to the research /
capability-evolution path, even though CLAUDE.md's "Research Front Door" and
"Research Stage Boundaries" sections describe it as installed and permanent:
dv_harness/capability_evolution.py owns the CapabilityEvolutionCandidate state
machine, its candidates already live on ONE Blackboard topic, and its Human
Approval Gate is already the real ControlPlane keyed on
RESEARCH_CAPABILITY_EVOLUTION. A human could file a candidate and then had no
surface to act on it except a terminal.

Two things these tests exist to prove, beyond "the endpoint returns 200":

  * The card READS the real module. Every asserted value is compared against
    what capability_evolution.py itself computes (read_candidates(),
    LEGAL_TRANSITIONS, human_approval_status(), decide_recommendation()'s
    derived recommendation) -- never against a string typed into the test, so a
    dashboard-local re-derivation that drifted from the real state machine
    fails here.
  * The buttons ARE the real gate. Approve writes the same control.json record
    `dv-harness approve RESEARCH_CAPABILITY_EVOLUTION` writes and is consumed by
    the real transition(); an approve from an illegal state writes NO approval
    at all; and a Hold really blocks a subsequent Stage-3 production write
    through capability_evolution's own assert_no_production_write_authorized().

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's harness helpers and
test_capability_evolution_research_architect.py's candidate fixture rather than
standing up second copies of either -- the same cross-test import convention
test_dashboard_amba_card.py already uses.
"""
from __future__ import annotations

import json
import shutil
import urllib.request
from pathlib import Path

import pytest

from dv_harness import capability_evolution as ce
from dv_harness.control_plane import ControlPlane
from dv_harness_tests.test_capability_evolution_research_architect import (
    _semantic_change_impact_fields,
)
from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _post,
    _start_dashboard,
    _wait_ready,
)


def _file_candidate(tmp: Path, **overrides) -> dict:
    """A real, schema-valid ENHANCE candidate persisted through the REAL
    persist_candidate() -- which writes the one Blackboard topic AND the
    Working Memory audit record, and refuses anything that would land in a
    higher memory tier. Building it any other way would prove the endpoint
    against a shape the real pipeline never produces."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields(**overrides))
    ce.persist_candidate(tmp, candidate)
    return candidate


def _walk_to(tmp: Path, candidate: dict, target: str) -> dict:
    """Advance a candidate through the REAL transition() one legal state at a
    time until it reaches `target`. No shortcut write to the Blackboard: the
    point of a governance-state test is that the state was reached the way the
    state machine allows."""
    path = ["EVIDENCE_GATHERING", "PROPOSED", "EXPERIMENT_APPROVED",
            "EXPERIMENTING", "BENCHMARKED", "PROMOTION_CANDIDATE"]
    for state in path:
        candidate = ce.transition(tmp, candidate, state, by="tester",
                                   reason=f"advance to {state}")
        if state == target:
            return candidate
    return candidate


def test_research_reports_honest_empty_state_when_no_candidate_filed():
    """No research pass has run in this project: the endpoint must say so and
    still report the real gate state, never invent a candidate -- the same
    honest-empty-state contract GET /api/coverage and GET /api/amba hold to."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/research")
        assert status == 200
        assert data["available"] is False
        assert data["candidates"] == []
        assert data["counts"] is None
        assert data["error"] is None
        assert data["blackboard_topic"] == ce.BLACKBOARD_TOPIC
        assert data["promotion_states"] == list(ce.PROMOTION_STATES)
        assert data["recommendations"] == list(ce.RECOMMENDATIONS)
        # "No candidate yet" must NOT hide the gate's own state: whether an
        # approval stands is exactly what a reviewer opens this card to check.
        assert data["approval"]["stage"] == ce.HUMAN_APPROVAL_STAGE
        assert data["approval"]["approved"] is False
        assert ce.HUMAN_APPROVAL_STAGE in data["approval"]["approve_command"]
    finally:
        shutil.rmtree(tmp)


def test_research_returns_real_candidate_rows_read_from_the_real_module():
    """A real candidate on the real Blackboard topic reaches the endpoint with
    its DERIVED recommendation/overlap intact, and its offered next states equal
    capability_evolution.LEGAL_TRANSITIONS itself."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        candidate = _file_candidate(tmp)

        status, data = _get(base, "/api/research")
        assert status == 200
        assert data["available"] is True and data["error"] is None
        assert len(data["candidates"]) == 1
        row = data["candidates"][0]

        # Compared against the real module's own record, never a typed string.
        live = ce.read_candidate(tmp, candidate["candidate_id"])
        assert row["candidate_id"] == live["candidate_id"]
        assert row["affected_capability"] == live["affected_capability"]
        assert row["recommendation"] == live["recommendation"] == "ENHANCE"
        assert row["overlap_status"] == live["overlap_status"] == "PARTIAL_MATCH"
        assert row["current_status"] == "DISCOVERED"
        assert row["confidence"] == live["confidence"]["level"]
        assert row["experiment_required"] is True
        assert row["decision_rationale"] == live["decision_rationale"]
        assert row["evidence_refs"] == list(live["evidence_refs"])
        assert row["legal_transitions"] == list(ce.LEGAL_TRANSITIONS["DISCOVERED"])
        # HUMAN_APPROVED is NOT reachable from DISCOVERED, so the card must not
        # offer it -- the button set is derived from the state machine.
        assert "HUMAN_APPROVED" not in row["legal_transitions"]

        counts = data["counts"]
        assert counts["total"] == 1
        assert counts["by_status"] == {"DISCOVERED": 1}
        assert counts["by_recommendation"] == {"ENHANCE": 1}

        # The Working Memory audit trail persist_candidate() really wrote,
        # through the real candidate_audit_records() -- not a second log.
        assert data["audit_records"], "no capability-evolution audit record reached the card"
        assert data["audit_records"][0]["kind"] == ce.CANDIDATE_MEMORY_KIND
        assert data["audit_records"][0]["candidate_id"] == candidate["candidate_id"]
    finally:
        shutil.rmtree(tmp)


def test_research_approve_writes_the_real_control_plane_approval_and_transitions():
    """POST /api/control {command: RESEARCH_APPROVE} must produce EXACTLY what
    the CLI's `dv-harness approve RESEARCH_CAPABILITY_EVOLUTION` produces --
    one real control.json approval -- and then have the real transition()
    consume it into the candidate's own status_history."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        candidate = _walk_to(tmp, _file_candidate(tmp), "PROMOTION_CANDIDATE")
        assert candidate["current_status"] == "PROMOTION_CANDIDATE"

        status, body = _post(base, "/api/control", {
            "command": "RESEARCH_APPROVE", "candidate_id": candidate["candidate_id"],
            "note": "reviewed the semantic-delta proposal against change_impact.py",
            "reviewer_id": "dv-lead", "reviewer_confidence": "MEDIUM"})
        assert status == 200, body
        result = body["result"]
        assert result["from_status"] == "PROMOTION_CANDIDATE"
        assert result["current_status"] == "HUMAN_APPROVED"

        # The real ControlPlane record, read back off disk.
        approval = ControlPlane(tmp).get_approval(ce.HUMAN_APPROVAL_STAGE)
        assert approval is not None
        assert approval["reviewer_id"] == "dv-lead"
        assert approval["reviewer_confidence"] == "MEDIUM"
        assert approval["note"].startswith("reviewed the semantic-delta")
        # ... and it is the SAME record capability_evolution's own gate reads.
        assert ce.assert_human_approval(tmp, candidate) == approval
        assert ce.human_approval_status(tmp)["approved"] is True

        # The candidate carries its own evidence that a human acted.
        live = ce.read_candidate(tmp, candidate["candidate_id"])
        assert live["current_status"] == "HUMAN_APPROVED"
        assert live["promotion_status"] == "HUMAN_APPROVED"
        last = live["status_history"][-1]
        assert last["from_status"] == "PROMOTION_CANDIDATE"
        assert last["to_status"] == "HUMAN_APPROVED"
        assert last["approval_ref"] == approval

        # One real audit event, on the same events.jsonl every other verb uses.
        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        assert any(e.get("cmd") == "approve" and e.get("stage") == ce.HUMAN_APPROVAL_STAGE
                   for e in events)
        assert any(e.get("cmd") == "research_approve"
                   and e.get("candidate_id") == candidate["candidate_id"]
                   and e.get("to_status") == "HUMAN_APPROVED" for e in events)

        # And the card now shows it, with no further legal step but ROLLED_BACK
        # unavailable from HUMAN_APPROVED (only PRODUCTION / REJECTED are).
        _, data = _get(base, "/api/research")
        row = data["candidates"][0]
        assert row["current_status"] == "HUMAN_APPROVED"
        assert row["legal_transitions"] == list(ce.LEGAL_TRANSITIONS["HUMAN_APPROVED"])
        assert data["approval"]["approved"] is True
    finally:
        shutil.rmtree(tmp)


def test_research_approve_from_an_illegal_state_writes_no_approval_at_all():
    """The legality check runs BEFORE the approval is written. A DISCOVERED
    candidate cannot jump the governance states, and the refusal must not leave
    a standing production-write authorization on disk that no transition
    consumed -- the exact failure an approve-first ordering would cause."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        candidate = _file_candidate(tmp)

        status, body = _post(base, "/api/control", {
            "command": "RESEARCH_APPROVE", "candidate_id": candidate["candidate_id"],
            "note": "looks good to me"})
        assert status == 400, body
        assert body["error"] == "BAD_REQUEST"
        assert "not a legal transition" in body["message"]

        assert ControlPlane(tmp).get_approval(ce.HUMAN_APPROVAL_STAGE) is None
        assert ce.read_candidate(tmp, candidate["candidate_id"])["current_status"] == "DISCOVERED"
        with pytest.raises(ce.HumanApprovalRequiredError):
            ce.assert_human_approval(tmp, candidate)
    finally:
        shutil.rmtree(tmp)


def test_research_reject_transitions_to_rejected_and_needs_no_approval():
    """Declining a proposal about the harness is not a production write, so it
    requires no ControlPlane approval -- and it is terminal."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        candidate = _file_candidate(tmp)

        status, body = _post(base, "/api/control", {
            "command": "RESEARCH_REJECT", "candidate_id": candidate["candidate_id"],
            "reason": "the existing change_impact.py path already covers this",
            "reviewer_id": "dv-lead"})
        assert status == 200, body
        assert body["result"]["current_status"] == "REJECTED"

        live = ce.read_candidate(tmp, candidate["candidate_id"])
        assert live["current_status"] == "REJECTED"
        assert live["status_history"][-1]["by"] == "dv-lead"
        assert live["status_history"][-1]["reason"].startswith("the existing change_impact.py")
        assert ControlPlane(tmp).get_approval(ce.HUMAN_APPROVAL_STAGE) is None

        _, data = _get(base, "/api/research")
        row = data["candidates"][0]
        assert row["current_status"] == "REJECTED"
        assert row["legal_transitions"] == []  # terminal: the card offers nothing
    finally:
        shutil.rmtree(tmp)


def test_research_hold_withdraws_the_standing_approval_and_really_blocks():
    """Hold is a real gate action, not a label. After it: no approval stands,
    the withdrawn one is ARCHIVED (never deleted) with its own outcome, and
    capability_evolution's own Stage-3 check refuses a production write on a
    candidate that already reached HUMAN_APPROVED."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        candidate = _walk_to(tmp, _file_candidate(tmp), "PROMOTION_CANDIDATE")
        status, body = _post(base, "/api/control", {
            "command": "RESEARCH_APPROVE", "candidate_id": candidate["candidate_id"],
            "note": "approved for implementation", "reviewer_id": "dv-lead"})
        assert status == 200, body
        approved = ce.read_candidate(tmp, candidate["candidate_id"])
        # Precondition: the Stage-3 check passes while the approval stands.
        ce.assert_no_production_write_authorized(tmp, approved)

        status, body = _post(base, "/api/control", {
            "command": "RESEARCH_HOLD", "candidate_id": candidate["candidate_id"],
            "reason": "hold pending a second reviewer", "reviewer_id": "dv-manager"})
        assert status == 200, body
        assert body["result"]["held"] is True
        assert body["result"]["withdrew_standing_approval"] is True
        assert body["result"]["stage"] == ce.HUMAN_APPROVAL_STAGE

        cp = ControlPlane(tmp)
        assert cp.get_approval(ce.HUMAN_APPROVAL_STAGE) is None
        history = cp.get_approval_history(ce.HUMAN_APPROVAL_STAGE)
        assert history[-1]["outcome"] == "WITHDRAWN_BY_HUMAN_HOLD"
        assert history[-1]["reviewer_id"] == "dv-lead"
        assert history[-1]["note"] == "approved for implementation"

        # THE BLOCK, proven rather than asserted: the same Stage-3 check that
        # passed above now refuses, on the unchanged candidate.
        with pytest.raises(ce.HumanApprovalRequiredError):
            ce.assert_no_production_write_authorized(tmp, approved)
        # A hold withholds authorization; it does not rewind the human decision.
        assert ce.read_candidate(tmp, candidate["candidate_id"])["current_status"] == "HUMAN_APPROVED"

        _, data = _get(base, "/api/research")
        assert data["approval"]["approved"] is False
        assert len(data["approval"]["history"]) == 1
    finally:
        shutil.rmtree(tmp)


def test_research_hold_with_no_standing_approval_is_still_recorded():
    """A hold raised before anyone approved is a real, recorded decision -- it
    withholds nothing yet and says so, rather than failing."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, body = _post(base, "/api/control", {
            "command": "RESEARCH_HOLD", "reason": "no reviewer available this week"})
        assert status == 200, body
        assert body["result"]["withdrew_standing_approval"] is False
        assert body["result"]["candidate_id"] is None

        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        held = [e for e in events if e.get("cmd") == "research_hold"]
        assert held and held[-1]["reason"] == "no reviewer available this week"
        assert held[-1]["stage"] == ce.HUMAN_APPROVAL_STAGE
    finally:
        shutil.rmtree(tmp)


@pytest.mark.parametrize("body,expected", [
    ({"command": "RESEARCH_APPROVE", "note": "x"}, "candidate_id is required"),
    ({"command": "RESEARCH_APPROVE", "candidate_id": "CE-1"}, "note is required"),
    ({"command": "RESEARCH_REJECT", "candidate_id": "CE-1"}, "reason is required"),
    ({"command": "RESEARCH_REJECT", "reason": "no"}, "candidate_id is required"),
    ({"command": "RESEARCH_HOLD"}, "reason is required"),
    ({"command": "RESEARCH_APPROVE", "candidate_id": "CE-nope", "note": "x"},
     "unknown capability-evolution candidate"),
])
def test_research_actions_reject_incomplete_requests_with_400(body, expected):
    """An unexplained or unaddressed governance action is not an audit record
    and must not reach the state machine."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, resp = _post(base, "/api/control", body)
        assert status == 400, resp
        assert resp["error"] == "BAD_REQUEST"
        assert expected in resp["message"]
        assert ControlPlane(tmp).get_approval(ce.HUMAN_APPROVAL_STAGE) is None
    finally:
        shutil.rmtree(tmp)


def test_research_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML, be refreshed by load(), and post
    its actions through /api/control -- an endpoint no page ever calls, or a
    button posting to a private research write path, is exactly the shape this
    gap-close exists to avoid."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="researchCard"' in html
        assert "Research / Capability Evolution" in html
        assert "'/api/research'" in html
        assert "await loadResearch();" in html
        for command in ("RESEARCH_APPROVE", "RESEARCH_REJECT", "RESEARCH_HOLD"):
            assert command in html
        # The three actions go through the SAME control dispatch as every other
        # Human Control Plane verb -- no parallel approval endpoint exists.
        assert "postJSON('/api/control', body)" in html
        assert "/api/research-approve" not in html
        # The stage-scoped limit of Hold is disclosed on the card itself.
        assert "STAGE-scoped, not candidate-scoped" in html
    finally:
        shutil.rmtree(tmp)
