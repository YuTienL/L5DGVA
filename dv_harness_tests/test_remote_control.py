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
