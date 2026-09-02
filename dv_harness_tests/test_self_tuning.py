import json
import tempfile
import shutil
from pathlib import Path

from dv_harness.self_tuning import (
    get_param, set_param, read_overrides, propose_add_override,
    propose_remove_override, PROTECTED_REMOVALS, read_execution_state,
    increment_execution_counter, reset_execution_counter,
    append_gate_history, read_gate_history_since, gate_history_length,
    classify_proposal, ELEVATED_SCRUTINY_GATES, record_adjustment, apply_proposal,
)


def _tmp_root():
    return Path(tempfile.mkdtemp())


def test_get_param_returns_default_when_file_absent():
    root = _tmp_root()
    try:
        assert get_param(root, "fake_gate", "threshold", 5) == 5
    finally:
        shutil.rmtree(root)


def test_set_param_then_get_param_round_trips():
    root = _tmp_root()
    try:
        set_param(root, "fake_gate", "threshold", 42)
        assert get_param(root, "fake_gate", "threshold", 5) == 42
        assert get_param(root, "fake_gate", "other", "d") == "d"
    finally:
        shutil.rmtree(root)


def test_get_param_returns_default_on_malformed_json():
    root = _tmp_root()
    try:
        p = root / ".dv-harness" / "self_tuning"
        p.mkdir(parents=True)
        (p / "parameters.json").write_text("{not json", encoding="utf-8")
        assert get_param(root, "fake_gate", "threshold", 5) == 5
    finally:
        shutil.rmtree(root)


def test_read_overrides_empty_when_absent():
    root = _tmp_root()
    try:
        assert read_overrides(root) == {}
    finally:
        shutil.rmtree(root)


def test_propose_add_override_writes_and_round_trips():
    root = _tmp_root()
    try:
        propose_add_override(root, "IMPLEMENT", "fake_gate")
        overrides = read_overrides(root)
        assert overrides["IMPLEMENT"]["add"] == ["fake_gate"]
    finally:
        shutil.rmtree(root)


def test_propose_remove_override_blocks_protected_pair():
    root = _tmp_root()
    try:
        protected_stage, protected_gate = next(iter(PROTECTED_REMOVALS))
        ok = propose_remove_override(root, protected_stage, protected_gate)
        assert ok is False
        overrides = read_overrides(root)
        assert protected_gate not in overrides.get(protected_stage, {}).get("remove", [])
    finally:
        shutil.rmtree(root)


def test_propose_remove_override_allows_unprotected_pair():
    root = _tmp_root()
    try:
        ok = propose_remove_override(root, "COMMAND_PATTERN", "some_unprotected_gate")
        assert ok is True
        overrides = read_overrides(root)
        assert overrides["COMMAND_PATTERN"]["remove"] == ["some_unprotected_gate"]
    finally:
        shutil.rmtree(root)


def test_execution_counter_increments_and_resets():
    root = _tmp_root()
    try:
        assert read_execution_state(root)["executions_since_last_review"] == 0
        assert increment_execution_counter(root) == 1
        assert increment_execution_counter(root) == 2
        reset_execution_counter(root)
        assert read_execution_state(root)["executions_since_last_review"] == 0
    finally:
        shutil.rmtree(root)


def test_gate_history_append_and_read_since():
    root = _tmp_root()
    try:
        append_gate_history(root, "gate_a", "IMPLEMENT", True, "PASS", 1.0)
        append_gate_history(root, "gate_b", "IMPLEMENT", False, "GATE_FAIL", 2.0)
        assert gate_history_length(root) == 2
        entries = read_gate_history_since(root, 1)
        assert len(entries) == 1
        assert entries[0]["gate_id"] == "gate_b"
    finally:
        shutil.rmtree(root)


from dv_harness.gates import effective_stage_gates, STAGE_GATES
from dv_harness.self_tuning import propose_add_override, propose_remove_override


def test_effective_stage_gates_matches_baseline_when_no_overrides():
    root = _tmp_root()
    try:
        assert effective_stage_gates("COMMAND_PATTERN", root) == STAGE_GATES["COMMAND_PATTERN"]
    finally:
        shutil.rmtree(root)


def test_effective_stage_gates_applies_add_override():
    root = _tmp_root()
    try:
        propose_add_override(root, "COMMAND_PATTERN", "fake_extra_gate")
        result = effective_stage_gates("COMMAND_PATTERN", root)
        ids = [g[0] for g in result]
        assert "fake_extra_gate" in ids
    finally:
        shutil.rmtree(root)


def test_effective_stage_gates_ignores_protected_removal():
    root = _tmp_root()
    try:
        # fix_risk_approval_gate/RE_AUDIT is protected -- direct JSON write
        # (bypassing propose_remove_override's own check) to prove
        # effective_stage_gates() enforces this independently, not only
        # the proposer function.
        from dv_harness.self_tuning import _overrides_path, _write_json_atomic
        _write_json_atomic(_overrides_path(root), {
            "RE_AUDIT": {"add": [], "remove": ["fix_risk_approval_gate"]}
        })
        result = effective_stage_gates("RE_AUDIT", root)
        ids = [g[0] for g in result]
        assert "fix_risk_approval_gate" in ids
    finally:
        shutil.rmtree(root)


def test_effective_stage_gates_applies_unprotected_removal():
    root = _tmp_root()
    try:
        propose_remove_override(root, "COMMAND_PATTERN", "command_migration_integrity_gate")
        result = effective_stage_gates("COMMAND_PATTERN", root)
        ids = [g[0] for g in result]
        assert "command_migration_integrity_gate" not in ids
    finally:
        shutil.rmtree(root)


def test_real_stage_evaluation_actually_uses_effective_stage_gates_overlay():
    # The load-bearing wiring check: effective_stage_gates() must not be
    # dead code -- a real _evaluate_stage_evidence_core() call for a stage
    # with an unprotected gate removed via the overlay must NOT fail for
    # missing that gate's evidence block (it's no longer in the effective
    # set for this project root).
    from dv_harness.gates import _evaluate_stage_evidence_core
    root = _tmp_root()
    try:
        propose_remove_override(root, "COMMAND_PATTERN", "command_migration_integrity_gate")
        verdict, reasons, signatures, completion = _evaluate_stage_evidence_core(root, "COMMAND_PATTERN", "")
        # With the only real STAGE_GATES["COMMAND_PATTERN"] entry removed via
        # the overlay, this stage now has zero effective gates.
        assert verdict == "NO_GATE_REQUIRED"
        assert signatures == []
    finally:
        shutil.rmtree(root)


def _param_proposal(gate_id="unprotected_gate", confidence="HIGH", risk_level="LOW"):
    return {
        "gate_id": gate_id, "change": {"param": "threshold", "from": 5, "to": 6},
        "rationale": "r", "confidence": confidence, "risk_level": risk_level,
    }


def test_classify_auto_applies_high_confidence_low_risk_single_change():
    p = _param_proposal()
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts=set()) == "AUTO_APPLY"


def test_classify_defers_on_low_confidence():
    p = _param_proposal(confidence="LOW")
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts=set()) == "DEFER"


def test_classify_defers_on_high_risk():
    p = _param_proposal(risk_level="HIGH")
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts=set()) == "DEFER"


def test_classify_defers_removal_action():
    p = {"gate_id": "g", "stage": "COMMAND_PATTERN",
         "change": {"action": "remove", "gate_id": "g"},
         "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"}
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts=set()) == "DEFER"


def test_classify_defers_elevated_scrutiny_gate():
    gate_id = next(iter(ELEVATED_SCRUTINY_GATES))
    p = _param_proposal(gate_id=gate_id)
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts=set()) == "DEFER"


def test_classify_defers_multi_gate_cycle():
    p1 = _param_proposal(gate_id="gate_a")
    p2 = _param_proposal(gate_id="gate_b")
    assert classify_proposal(p1, cycle_proposals=[p1, p2], recent_reverts=set()) == "DEFER"


def test_classify_defers_recently_reverted_gate():
    p = _param_proposal(gate_id="gate_a")
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts={"gate_a"}) == "DEFER"


def test_apply_proposal_sets_param():
    root = _tmp_root()
    try:
        apply_proposal(root, _param_proposal())
        assert get_param(root, "unprotected_gate", "threshold", None) == 6
    finally:
        shutil.rmtree(root)


def test_apply_proposal_adds_override():
    root = _tmp_root()
    try:
        p = {"gate_id": "g", "stage": "COMMAND_PATTERN",
             "change": {"action": "add", "gate_id": "g"},
             "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"}
        apply_proposal(root, p)
        assert "g" in read_overrides(root)["COMMAND_PATTERN"]["add"]
    finally:
        shutil.rmtree(root)


def test_record_adjustment_stores_locally_not_shared():
    root = _tmp_root()
    try:
        mem_id = record_adjustment(root, _param_proposal(), status="APPLIED")
        assert mem_id.startswith("MEM-")
        stored = json.loads((root / ".dv-harness" / "memory" / "project" / f"{mem_id}.json").read_text(encoding="utf-8"))
        assert stored["kind"] == "self_tuning_adjustment"
        assert stored["status"] == "APPLIED"
    finally:
        shutil.rmtree(root)


def test_apply_proposal_raises_on_empty_change_dict():
    """Regression test: proposal with change = {} (neither action nor param)
    should raise ValueError with informative message, not KeyError."""
    import pytest
    root = _tmp_root()
    try:
        p = {"gate_id": "bad_gate", "change": {}, "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"}
        with pytest.raises(ValueError) as exc_info:
            apply_proposal(root, p)
        assert "bad_gate" in str(exc_info.value)
        assert "change" in str(exc_info.value).lower()
    finally:
        shutil.rmtree(root)


def test_apply_proposal_raises_on_add_missing_stage():
    """Regression test: add/remove proposal missing stage should raise ValueError,
    not KeyError."""
    import pytest
    root = _tmp_root()
    try:
        p = {
            "gate_id": "bad_gate",
            "change": {"action": "add", "gate_id": "bad_gate"},
            "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"
        }
        with pytest.raises(ValueError) as exc_info:
            apply_proposal(root, p)
        assert "bad_gate" in str(exc_info.value)
        assert "stage" in str(exc_info.value).lower()
    finally:
        shutil.rmtree(root)


def test_apply_proposal_raises_on_remove_missing_stage():
    """Regression test: remove proposal missing stage should raise ValueError."""
    import pytest
    root = _tmp_root()
    try:
        p = {
            "gate_id": "bad_gate",
            "change": {"action": "remove", "gate_id": "bad_gate"},
            "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"
        }
        with pytest.raises(ValueError) as exc_info:
            apply_proposal(root, p)
        assert "bad_gate" in str(exc_info.value)
        assert "stage" in str(exc_info.value).lower()
    finally:
        shutil.rmtree(root)


def test_apply_proposal_raises_on_param_change_missing_param():
    """Regression test: param-change proposal missing 'param' key should raise ValueError."""
    import pytest
    root = _tmp_root()
    try:
        p = {
            "gate_id": "bad_gate",
            "change": {"to": 42},
            "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"
        }
        with pytest.raises(ValueError) as exc_info:
            apply_proposal(root, p)
        assert "bad_gate" in str(exc_info.value)
        assert "param" in str(exc_info.value).lower()
    finally:
        shutil.rmtree(root)


def test_apply_proposal_raises_on_param_change_missing_to():
    """Regression test: param-change proposal missing 'to' key should raise ValueError.
    This is critical because a valid target value could be 0/False/None."""
    import pytest
    root = _tmp_root()
    try:
        p = {
            "gate_id": "bad_gate",
            "change": {"param": "threshold"},
            "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"
        }
        with pytest.raises(ValueError) as exc_info:
            apply_proposal(root, p)
        assert "bad_gate" in str(exc_info.value)
        assert "to" in str(exc_info.value).lower()
    finally:
        shutil.rmtree(root)


def test_apply_proposal_param_change_with_falsy_to_value_works():
    """Regression test: param-change proposal with falsy 'to' values (0, False, None)
    should work correctly."""
    root = _tmp_root()
    try:
        # Test with 0
        apply_proposal(root, {
            "gate_id": "g", "change": {"param": "threshold", "to": 0},
            "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"
        })
        assert get_param(root, "g", "threshold", None) == 0

        # Test with False
        apply_proposal(root, {
            "gate_id": "g2", "change": {"param": "flag", "to": False},
            "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"
        })
        assert get_param(root, "g2", "flag", None) is False

        # Test with None
        apply_proposal(root, {
            "gate_id": "g3", "change": {"param": "value", "to": None},
            "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"
        })
        assert get_param(root, "g3", "value", "default") is None
    finally:
        shutil.rmtree(root)
