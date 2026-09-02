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
    read_last_reviewed_index, PROTECTED_PARAMETERS, delete_param,
    capture_prior_param_state, gate_ids_with_recent_reverts,
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


# --- Task 5 code-review Finding 3 fix (2026-09-02): read_last_reviewed_index()
# + reset_execution_counter()'s optional last_reviewed_index parameter --
# these let engine.py's _maybe_run_self_tuning_review() scope its
# read_gate_history_since() call to "history since the last successful
# review cycle" instead of always resending the entire cumulative log.

def test_read_last_reviewed_index_defaults_to_zero_when_absent():
    root = _tmp_root()
    try:
        assert read_last_reviewed_index(root) == 0
    finally:
        shutil.rmtree(root)


def test_reset_execution_counter_without_index_preserves_backward_compat_behavior():
    # No last_reviewed_index passed -- must still zero the counter (today's
    # existing, already-tested behavior) and must NOT introduce a
    # last_reviewed_gate_history_index key that wasn't there before.
    root = _tmp_root()
    try:
        increment_execution_counter(root)
        increment_execution_counter(root)
        reset_execution_counter(root)
        state = read_execution_state(root)
        assert state["executions_since_last_review"] == 0
        assert "last_reviewed_gate_history_index" not in state
        assert read_last_reviewed_index(root) == 0
    finally:
        shutil.rmtree(root)


def test_reset_execution_counter_with_index_advances_and_round_trips():
    root = _tmp_root()
    try:
        increment_execution_counter(root)
        reset_execution_counter(root, last_reviewed_index=7)
        assert read_execution_state(root)["executions_since_last_review"] == 0
        assert read_last_reviewed_index(root) == 7
    finally:
        shutil.rmtree(root)


def test_reset_execution_counter_without_index_does_not_clobber_prior_advance():
    # An internal-failure reset (no last_reviewed_index kwarg, e.g.
    # engine.py's malformed-evidence / proposal-gate-failure early-return
    # paths) must not lose an index a PRIOR successful cycle already
    # advanced -- reset_execution_counter reads the existing state first and
    # updates it in place rather than overwriting the whole file.
    root = _tmp_root()
    try:
        reset_execution_counter(root, last_reviewed_index=12)
        increment_execution_counter(root)
        reset_execution_counter(root)  # simulates an internal-failure reset
        assert read_execution_state(root)["executions_since_last_review"] == 0
        assert read_last_reviewed_index(root) == 12
    finally:
        shutil.rmtree(root)


def test_reset_execution_counter_index_zero_is_not_treated_as_omitted():
    # 0 is a legitimate real index (e.g. a project's very first review
    # cycle reviewing history entries 0..N) -- must be written, not treated
    # as falsy-equivalent to "omitted" (the sentinel is None, not falsy).
    root = _tmp_root()
    try:
        reset_execution_counter(root, last_reviewed_index=5)
        reset_execution_counter(root, last_reviewed_index=0)
        assert read_last_reviewed_index(root) == 0
    finally:
        shutil.rmtree(root)


# --- Final-review fix wave (2026-09-02): C1/I1/I2/I3/I4 + bundled
# recent_reverts wiring -- see docs/superpowers/sdd/2026-09-02-autonomous-
# gate-self-tuning-mechanism/final-review-fix-report.md for the full findings.

def test_classify_defers_add_action():
    # Finding C1 regression: an "add" membership proposal must defer to a
    # human exactly like "remove" already did -- effective_stage_gates()
    # materializes an unrecognized add gate_id as a placeholder that can
    # never PASS, permanently breaking the stage if auto-applied.
    p = {"gate_id": "g", "stage": "COMMAND_PATTERN",
         "change": {"action": "add", "gate_id": "brand_new_gate"},
         "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"}
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts=set()) == "DEFER"


def test_apply_proposal_raises_on_protected_parameter():
    # Finding I1 regression: apply_proposal() itself (not just the LLM-
    # analysis proposal gate script) must refuse a PROTECTED_PARAMETERS
    # target -- this is the real chokepoint the CLI approve path goes
    # through with no proposal-gate re-run in between.
    import pytest
    root = _tmp_root()
    try:
        gate_id, param = next(iter(PROTECTED_PARAMETERS))
        p = {"gate_id": gate_id, "change": {"param": param, "from": 1, "to": 2},
             "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"}
        with pytest.raises(ValueError) as exc_info:
            apply_proposal(root, p)
        assert param in str(exc_info.value)
        # The parameter must genuinely be untouched.
        assert get_param(root, gate_id, param, "UNSET") == "UNSET"
    finally:
        shutil.rmtree(root)


def test_apply_proposal_raises_on_blocked_protected_removal():
    # Finding I2 regression: apply_proposal() must propagate
    # propose_remove_override()'s False-on-protected return as a real
    # ValueError, instead of silently no-opping while the caller still
    # thinks the removal succeeded.
    import pytest
    root = _tmp_root()
    try:
        protected_stage, protected_gate = next(iter(PROTECTED_REMOVALS))
        p = {"gate_id": protected_gate, "stage": protected_stage,
             "change": {"action": "remove", "gate_id": protected_gate},
             "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"}
        with pytest.raises(ValueError):
            apply_proposal(root, p)
        overrides = read_overrides(root)
        assert protected_gate not in overrides.get(protected_stage, {}).get("remove", [])
    finally:
        shutil.rmtree(root)


def test_delete_param_removes_previously_set_value():
    root = _tmp_root()
    try:
        set_param(root, "g", "threshold", 42)
        assert get_param(root, "g", "threshold", None) == 42
        delete_param(root, "g", "threshold")
        assert get_param(root, "g", "threshold", "GATE_DEFAULT") == "GATE_DEFAULT"
        # Truly absent from the on-disk file, not merely defaulting.
        data = json.loads((root / ".dv-harness" / "self_tuning" / "parameters.json").read_text(encoding="utf-8"))
        assert "g" not in data or "threshold" not in data.get("g", {})
    finally:
        shutil.rmtree(root)


def test_delete_param_is_noop_when_absent():
    root = _tmp_root()
    try:
        delete_param(root, "never_set_gate", "threshold")  # must not raise
        assert get_param(root, "never_set_gate", "threshold", "d") == "d"
    finally:
        shutil.rmtree(root)


def test_capture_prior_param_state_distinguishes_absent_from_real_value():
    root = _tmp_root()
    try:
        absent = capture_prior_param_state(root, "g", "threshold")
        assert absent == {"prior_was_absent": True, "prior_value": None}

        set_param(root, "g", "threshold", 0)  # a real, falsy prior value
        present = capture_prior_param_state(root, "g", "threshold")
        assert present == {"prior_was_absent": False, "prior_value": 0}
    finally:
        shutil.rmtree(root)


def test_elevated_scrutiny_gates_includes_fix_effectiveness_gate():
    # Finding I4 regression: the old hardcoded 14-entry literal was missing
    # fix_effectiveness_gate, a real live RE_AUDIT gate not in
    # PROTECTED_REMOVALS. Computed dynamically now, so this is included
    # automatically.
    assert "fix_effectiveness_gate" in ELEVATED_SCRUTINY_GATES


def test_elevated_scrutiny_gates_is_computed_not_hardcoded():
    # Proves ELEVATED_SCRUTINY_GATES tracks STAGE_GATES rather than being a
    # frozen literal: patch STAGE_GATES to add a brand-new RE_AUDIT gate and
    # confirm a freshly-recomputed set picks it up.
    from unittest.mock import patch
    from dv_harness import gates as gates_mod
    from dv_harness.self_tuning import _compute_elevated_scrutiny_gates
    patched = dict(gates_mod.STAGE_GATES)
    patched["RE_AUDIT"] = list(patched["RE_AUDIT"]) + [("brand_new_re_audit_gate", "brand_new_re_audit_gate.py", "--x")]
    with patch.object(gates_mod, "STAGE_GATES", patched):
        recomputed = _compute_elevated_scrutiny_gates()
    assert "brand_new_re_audit_gate" in recomputed
    # A gate id that's also in PROTECTED_REMOVALS (e.g. fix_risk_approval_gate)
    # must stay excluded regardless of the patch.
    protected_gate_ids = {gid for (_s, gid) in PROTECTED_REMOVALS}
    assert not (recomputed & protected_gate_ids)


def test_gate_ids_with_recent_reverts_finds_reverted_gate():
    # Bundled fix alongside I3: recent_reverts must be real data (a
    # REVERTED self_tuning_adjustment record in project memory), not always
    # an empty set.
    root = _tmp_root()
    try:
        assert gate_ids_with_recent_reverts(root) == set()
        p = _param_proposal(gate_id="thrashy_gate")
        mem_id = record_adjustment(root, p, status="APPLIED")
        from dv_harness.memory import MemoryStore
        store = MemoryStore(root)
        rec = store.get(mem_id)
        rec["status"] = "REVERTED"
        store.add("project", rec)
        assert gate_ids_with_recent_reverts(root) == {"thrashy_gate"}
    finally:
        shutil.rmtree(root)


def test_gate_ids_with_recent_reverts_causes_defer_for_same_gate():
    # End-to-end of the bundled fix: a gate_id with a REVERTED record must
    # cause classify_proposal() to DEFER a subsequent same-gate proposal
    # that would otherwise AUTO_APPLY.
    root = _tmp_root()
    try:
        p = _param_proposal(gate_id="thrashy_gate")
        mem_id = record_adjustment(root, p, status="APPLIED")
        from dv_harness.memory import MemoryStore
        store = MemoryStore(root)
        rec = store.get(mem_id)
        rec["status"] = "REVERTED"
        store.add("project", rec)

        recent_reverts = gate_ids_with_recent_reverts(root)
        new_proposal = _param_proposal(gate_id="thrashy_gate")
        assert classify_proposal(new_proposal, cycle_proposals=[new_proposal],
                                  recent_reverts=recent_reverts) == "DEFER"
    finally:
        shutil.rmtree(root)
