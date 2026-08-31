import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import remote_control as rc

ROOT = Path(__file__).resolve().parents[1]
GATE_NAMES = [
    "remote_control_supervisory_gate.py",
    "remote_state_transition_gate.py",
    "remote_action_audit_gate.py",
    "remote_action_replay_gate.py",
]


@pytest.fixture()
def project(tmp_path):
    """A throwaway project root with the real gate scripts mirrored in, so
    tests exercise the actual gate logic without touching this repo's own
    .dv-harness/remote-control/session.json."""
    gate_dir = tmp_path / "tools" / "verification_flow"
    gate_dir.mkdir(parents=True)
    for name in GATE_NAMES:
        shutil.copy(ROOT / "tools" / "verification_flow" / name, gate_dir / name)
    return tmp_path


def test_bootstrap_lands_on_running(project):
    session = rc.bootstrap_session(project, host="testhost")
    assert session["state"] == "RUNNING"
    assert session["remote_control_enabled"] is True
    actions = rc.read_audit_log(project)
    assert len(actions) == 1
    assert actions[0]["command"] == "BOOTSTRAP"


def test_pause_resume_takeover_stop_sequence(project):
    rc.bootstrap_session(project)

    ok, state, entry, err = rc.validate_and_transition("PAUSE", project_root=project,
                                                         reason="operator requested pause")
    assert ok and state == "PAUSED" and err is None
    assert rc.read_session(project)["state"] == "PAUSED"

    ok, state, entry, err = rc.validate_and_transition("RESUME", project_root=project)
    assert ok and state == "RUNNING"

    ok, state, entry, err = rc.validate_and_transition(
        "TAKEOVER", project_root=project, target_stage="VERIFY",
        reason="human is driving BUILD_DEBUG directly",
    )
    assert ok and state == "TAKEOVER"
    assert entry["target_stage"] == "VERIFY"
    assert entry["evidence_snapshot"] is not None  # TAKEOVER is mutating -> gets a snapshot

    ok, state, entry, err = rc.validate_and_transition(
        "STOP", project_root=project, target_stage="VERIFY", reason="ending session",
    )
    assert ok and state == "STOPPED"
    assert rc.read_session(project)["remote_control_enabled"] is False

    actions = rc.read_audit_log(project)
    # BOOTSTRAP, PAUSE, RESUME, TAKEOVER, STOP
    assert [a["command"] for a in actions] == ["BOOTSTRAP", "PAUSE", "RESUME", "TAKEOVER", "STOP"]
    nonces = [a["nonce"] for a in actions]
    assert len(nonces) == len(set(nonces))  # every nonce unique


def test_illegal_transition_is_rejected_and_nothing_is_persisted(project):
    rc.bootstrap_session(project)  # state = RUNNING

    # RESUME is not legal from RUNNING (RUNNING has no "RESUME" entry in the
    # real remote_state_transition_gate.py table).
    ok, state, entry, err = rc.validate_and_transition("RESUME", project_root=project)
    assert ok is False
    assert state is None and entry is None
    assert err == "ILLEGAL_REMOTE_STATE_TRANSITION"

    # Nothing was persisted: state is unchanged and no new audit entry appended.
    assert rc.read_session(project)["state"] == "RUNNING"
    assert len(rc.read_audit_log(project)) == 1  # just BOOTSTRAP


def test_stopped_is_terminal_for_pause(project):
    rc.bootstrap_session(project)
    rc.validate_and_transition("STOP", project_root=project, target_stage="VERIFY", reason="done")
    ok, state, entry, err = rc.validate_and_transition("PAUSE", project_root=project)
    assert ok is False
    assert err == "ILLEGAL_REMOTE_STATE_TRANSITION"


def test_mutating_command_without_target_stage_is_rejected_before_any_gate(project):
    rc.bootstrap_session(project)
    ok, state, entry, err = rc.validate_and_transition("REDIRECT", project_root=project,
                                                         reason="change course")
    assert ok is False
    assert err == "CONTROL_ACTION_WITHOUT_TARGET_STAGE"


def test_unknown_command_is_rejected(project):
    rc.bootstrap_session(project)
    ok, state, entry, err = rc.validate_and_transition("HACK", project_root=project)
    assert ok is False
    assert err == "INVALID_REMOTE_COMMAND:HACK"


def test_approve_and_reject_have_no_legal_transition_in_any_state(project):
    """Documents a real gap: remote_state_transition_gate.py's ALLOWED table
    has no APPROVE/REJECT entry in ANY state, even though the supervisory
    gate accepts both. This module surfaces that rather than inventing a
    transition for them."""
    rc.bootstrap_session(project)  # RUNNING
    for cmd in ("APPROVE", "REJECT"):
        ok, state, entry, err = rc.validate_and_transition(
            cmd, project_root=project, target_stage="VERIFY", reason="x",
        )
        assert ok is False
        assert err == "ILLEGAL_REMOTE_STATE_TRANSITION"


def test_pause_resume_takeover_approve_actually_move_control_plane_state(project):
    # Regression for the wy6cekeu9 adversarial-verify finding: this module's
    # session.json is a SEPARATE file from .dv-harness/control.json, which is
    # what engine.py's loop()/run_stage() actually reads. Before the fix,
    # validate_and_transition("PAUSE"/...) only flipped session.json -- the
    # autonomous loop kept running underneath a client that believed it had
    # paused it. These assert the REAL ControlPlane.json state, not just
    # remote_control's own session.json.
    from dv_harness.control_plane import ControlPlane
    rc.bootstrap_session(project)

    ok, state, entry, err = rc.validate_and_transition("PAUSE", project_root=project,
                                                         reason="operator requested pause")
    assert ok and err is None
    cp = ControlPlane(project)
    assert cp.is_paused() is True
    assert cp.load()["paused_reason"] == "operator requested pause"

    ok, state, entry, err = rc.validate_and_transition("RESUME", project_root=project)
    assert ok and err is None
    assert ControlPlane(project).is_paused() is False

    ok, state, entry, err = rc.validate_and_transition(
        "TAKEOVER", project_root=project, target_stage="VERIFY", reason="human driving VERIFY",
    )
    assert ok and err is None
    tk = ControlPlane(project).takeover_status()
    assert tk["active"] is True and tk["stage"] == "VERIFY"


def test_redirect_actually_moves_current_stage(project):
    # Same class of regression as above, for REDIRECT -> DVHarness.human_redirect.
    # remote_state_transition_gate.py only allows REDIRECT from PAUSED/TAKEOVER,
    # not RUNNING -- PAUSE first, matching that real table.
    rc.bootstrap_session(project)
    from dv_harness.engine import DVHarness
    h = DVHarness(project)
    assert h.state.current_stage == "ENV_CHECK"

    ok, state, entry, err = rc.validate_and_transition("PAUSE", project_root=project, reason="pause before redirect")
    assert ok and err is None

    ok, state, entry, err = rc.validate_and_transition(
        "REDIRECT", project_root=project, target_stage="DISCOVERY", reason="skip ahead for test",
    )
    assert ok and err is None
    reloaded = DVHarness(project)
    assert reloaded.state.current_stage == "DISCOVERY"


def test_reject_and_stop_have_no_control_plane_effect_even_if_legal():
    # REJECT/STOP are documented as session-status-only (no ControlPlane
    # method exists for either). Directly exercises _apply_control_plane_effect
    # as a no-op for both, independent of whether the transition gate would
    # ever allow them -- this must hold even if that gate's table changes later.
    from dv_harness.remote_control import _apply_control_plane_effect
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    for cmd in ("REJECT", "STOP"):
        _apply_control_plane_effect(cmd, tmp, target_stage="VERIFY", reason="x", actor="test")
    assert not (tmp / ".dv-harness" / "control.json").exists()


def test_get_status_is_read_only(project):
    rc.bootstrap_session(project)
    before = rc.read_audit_log(project)
    status = rc.get_status(project)
    assert status["session"]["state"] == "RUNNING"
    assert status["last_action"]["command"] == "BOOTSTRAP"
    assert rc.read_audit_log(project) == before  # no side effect


def test_hypothesis_is_now_an_allowed_command():
    # Audit finding: HYPOTHESIS is documented in REMOTE_CONTROL_MODE.md but
    # was never added to ALLOWED_COMMANDS, so it failed before even reaching
    # a gate.
    assert "HYPOTHESIS" in rc.ALLOWED_COMMANDS


def test_hypothesis_scores_a_real_confidence_value(project):
    """Crux test: HYPOTHESIS must call inference.score_confidence() against
    the evidence it is handed, not return a hardcoded/self-reported number.
    Two fixtures with genuinely different evidence strength must score
    differently -- same shape as root_cause_evidence_gate's own evidence
    block, mirroring engine.py's _score_root_cause_confidence citation
    counting (list/dict length, else 1/0)."""
    rc.bootstrap_session(project)

    weak_evidence = {
        "first_bad_event": None,
        "causal_chain": None,
        "supporting_evidence": [],
        "counter_evidence": ["contradicting_trace"],
    }
    strong_evidence = {
        "first_bad_event": "clk gating deasserted 2ns early",
        "causal_chain": "reset deassert -> clk ungate -> FIFO underrun",
        "supporting_evidence": ["waveform_ref_1", "waveform_ref_2", "waveform_ref_3"],
        "counter_evidence": [],
        "root_cause": "clk_gate_underrun",
        "hypotheses": [
            {"claim": "phy_link_training_fail", "counter_evidence": ["ref_a"]},
            {"claim": "reset_sequencing_bug", "counter_evidence": ["ref_b"]},
        ],
    }

    ok_weak, _, entry_weak, err_weak = rc.validate_and_transition(
        "HYPOTHESIS", project_root=project, evidence_snapshot=weak_evidence,
    )
    ok_strong, _, entry_strong, err_strong = rc.validate_and_transition(
        "HYPOTHESIS", project_root=project, evidence_snapshot=strong_evidence,
    )

    assert ok_weak and err_weak is None
    assert ok_strong and err_strong is None

    weak_confidence = entry_weak["hypothesis_result"]["confidence"]
    strong_confidence = entry_strong["hypothesis_result"]["confidence"]

    # Real inference.score_confidence() math, not a self-reported value:
    # weak evidence (no sources, unresolved counter-evidence) scores LOW;
    # strong evidence (3 independent sources, verified refs, 2 corroborating
    # ruled-out alternative hypotheses) scores HIGH -- and the raw score
    # itself must differ, not just the bucketed level.
    assert weak_confidence["level"] == "LOW"
    assert strong_confidence["level"] == "HIGH"
    assert strong_confidence["score"] > weak_confidence["score"]

    # gap/next_best_action are also real inference.py output, not stubs:
    # identify_gap() is a pure category-presence check, so strong_evidence's
    # empty counter_evidence list (a real, legitimate "no counter-evidence
    # found" state, not a missing field) still reports as a gap category --
    # exactly matching engine.py's own root-cause-confidence docstring note
    # that a HIGH finding is expected to also carry non-empty counter_evidence.
    assert "first_bad_event" in entry_weak["hypothesis_result"]["gap"]
    assert entry_strong["hypothesis_result"]["gap"] == ["counter_evidence"]


def test_review_is_no_longer_identical_to_status(project):
    """REVIEW must surface the current stage's real StageState (gate
    verdict/evidence/blocking reason) -- content STATUS's plain
    session/last-action summary does not carry at all."""
    rc.bootstrap_session(project)
    from dv_harness.engine import DVHarness

    h = DVHarness(project)
    stage = h.state.current_stage
    h.state.stages[stage]["status"] = "PARTIAL"
    h.state.stages[stage]["evidence"] = ["env_check_gate"]
    h.state.stages[stage]["blocking_reason"] = "missing DUT RTL path"
    h.store.save(h.state)

    ok_status, _, entry_status, err_status = rc.validate_and_transition(
        "STATUS", project_root=project,
    )
    ok_review, _, entry_review, err_review = rc.validate_and_transition(
        "REVIEW", project_root=project,
    )

    assert ok_status and err_status is None
    assert ok_review and err_review is None

    assert "review_detail" not in entry_status
    assert "review_detail" in entry_review
    assert entry_review["review_detail"]["stage"] == stage
    assert entry_review["review_detail"]["gate_verdict"] == "PARTIAL"
    assert entry_review["review_detail"]["evidence"] == ["env_check_gate"]
    assert entry_review["review_detail"]["blocking_reason"] == "missing DUT RTL path"
    assert entry_review != entry_status
