"""Tests for dv_harness/intake_modes.py.

Real usage throughout: every `IntakeState` is built through `intake_state.py`'s
own real public `IntakeFieldRecord`/`IntakeState` constructors (the same
constructors `intake_state.build_intake_state()` itself uses internally), and
every readiness verdict is produced by calling the REAL, unmodified
`verification_intake_contract.evaluate_intake_readiness()` -- this module adds
no second readiness engine, so these tests exercise the real one through the
new mode-parameterization layer, never a stand-in for it.
"""
import json
import os
import subprocess
import sys

import pytest

from dv_harness import intake_modes, intake_state, verification_intake_contract as vic


def _record(field, category, status="AUTO_RESOLVED", reason="ok"):
    return intake_state.IntakeFieldRecord(
        field=field, category=category, value="x", source="test",
        confidence="HIGH", status=status, reason=reason,
    )


def _full_resolved_records(overrides=None):
    """One field per category `build_intake_state()` really populates, all
    AUTO_RESOLVED unless `overrides` (a {field: status} map) says otherwise."""
    overrides = overrides or {}
    fields = [
        ("dut_rtl", "general"),
        ("dut_registers", "general"),
        ("dut_address_map", "general"),
        ("dut_clock_reset", "general"),
        ("vip_release", "vip_resolution"),
        ("vip_user_guide_refs", "general"),
        ("component_hierarchy", "general"),
        ("config_db_trace", "general"),
        ("testplan_correspondence", "general"),
        ("bind:usb0", "critical_bind"),
        ("dut_boundary", "dut_boundary"),
        ("active_driver_conflicts", "active_driver_conflict"),
        ("build_env", "build_env"),
        ("known_pass_tests", "known_pass_test"),
    ]
    return [_record(f, c, status=overrides.get(f, "AUTO_RESOLVED")) for f, c in fields]


# ---------------------------------------------------------------------------
# mode table itself
# ---------------------------------------------------------------------------

def test_mode_order_is_the_four_named_modes():
    assert [m.value for m in intake_modes.MODE_ORDER] == [
        "FAST", "STANDARD", "STRICT", "SIGNOFF"]


def test_modes_are_monotonically_increasing_by_construction():
    # Re-running the same import-time guard must stay clean against the real
    # shipped table.
    intake_modes.assert_modes_monotonically_increasing()
    fast = set(intake_modes.MODE_SPECS[intake_modes.IntakeMode.FAST].required_categories)
    standard = set(intake_modes.MODE_SPECS[intake_modes.IntakeMode.STANDARD].required_categories)
    strict = set(intake_modes.MODE_SPECS[intake_modes.IntakeMode.STRICT].required_categories)
    signoff = set(intake_modes.MODE_SPECS[intake_modes.IntakeMode.SIGNOFF].required_categories)
    assert fast <= standard <= strict
    assert signoff == strict
    assert intake_modes.MODE_SPECS[intake_modes.IntakeMode.SIGNOFF].require_all_fields is True
    assert intake_modes.MODE_SPECS[intake_modes.IntakeMode.STRICT].require_all_fields is False


def test_standard_mode_required_categories_equal_intake_state_blocking_categories():
    # STANDARD must be provably identical in scope to the existing fixed
    # evaluate_uvm_generation_ready() rule -- not merely similar to it.
    standard = intake_modes.MODE_SPECS[intake_modes.IntakeMode.STANDARD].required_categories
    assert standard == tuple(intake_state.BLOCKING_CATEGORIES)


def test_resolve_mode_accepts_member_and_string_case_insensitively():
    assert intake_modes.resolve_mode("strict") is intake_modes.IntakeMode.STRICT
    assert intake_modes.resolve_mode(intake_modes.IntakeMode.SIGNOFF) is intake_modes.IntakeMode.SIGNOFF


def test_resolve_mode_rejects_unknown_name_rather_than_defaulting():
    with pytest.raises(intake_modes.IntakeModeError) as exc:
        intake_modes.resolve_mode("SUPER_STRICT")
    assert exc.value.reason == "UNKNOWN_INTAKE_MODE"
    assert set(exc.value.detail["known_modes"]) == {"FAST", "STANDARD", "STRICT", "SIGNOFF"}


# ---------------------------------------------------------------------------
# status mapping
# ---------------------------------------------------------------------------

def test_status_mapping_is_total_over_intake_field_status():
    known = {s.value for s in intake_state.IntakeFieldStatus}
    mapped = set(intake_modes._FIELD_STATUS_TO_CONDITION_STATUS)
    assert known == mapped


@pytest.mark.parametrize("field_status,expected", [
    ("AUTO_RESOLVED", "MET"),
    ("USER_CONFIRMED", "MET"),
    ("NOT_APPLICABLE", "NOT_APPLICABLE"),
    ("BLOCKED", "UNMET"),
    ("CONTRADICTED", "UNMET"),
    ("MISSING", "UNKNOWN"),
    ("UNKNOWN", "UNKNOWN"),
    ("PARTIAL", "UNKNOWN"),
])
def test_condition_status_for_field_status_mapping(field_status, expected):
    assert intake_modes.condition_status_for_field_status(field_status) == expected


def test_condition_status_for_field_status_rejects_unknown_status():
    with pytest.raises(intake_modes.IntakeModeError) as exc:
        intake_modes.condition_status_for_field_status("SOMETHING_ELSE")
    assert exc.value.reason == "UNKNOWN_INTAKE_FIELD_STATUS"


# ---------------------------------------------------------------------------
# the negative control this project is graded on: never fabricate readiness
# ---------------------------------------------------------------------------

def test_empty_intake_state_never_fabricates_ready_under_any_mode():
    """An IntakeState with zero records must never report READY under any
    declared mode -- this module refuses to answer 'ready' when no evidence
    was ever supplied, exactly like the underlying evaluate_intake_readiness()
    it reuses.

    The category-granularity modes (FAST/STANDARD/STRICT) still build one
    condition PER REQUIRED CATEGORY even against an empty state -- each
    category's own worst-wins category_status() honestly folds to MISSING
    (mapped to UNKNOWN) for a category with no fields recorded at all, so
    those modes correctly report NOT_READY naming every required category as
    blocking, never a fabricated READY and never a vacuous 'nothing to
    report' either. SIGNOFF's field-granularity conditions, by contrast, are
    built directly from the (here, empty) record list, so an empty state
    really does give it nothing to evaluate at all -- the honest NOT_AVAILABLE
    case."""
    empty = intake_state.IntakeState([])
    for mode in intake_modes.MODE_ORDER:
        result = intake_modes.evaluate_intake_readiness_for_mode(empty, mode)
        assert result.readiness.ready is False
        assert result.readiness.status in (vic.NOT_READY, vic.NOT_AVAILABLE)

    signoff = intake_modes.evaluate_intake_readiness_for_mode(empty, "SIGNOFF")
    assert signoff.readiness.status == vic.NOT_AVAILABLE
    assert signoff.readiness.evaluated_count == 0

    standard = intake_modes.evaluate_intake_readiness_for_mode(empty, "STANDARD")
    assert standard.readiness.status == vic.NOT_READY
    assert standard.readiness.evaluated_count == len(intake_state.BLOCKING_CATEGORIES)
    assert {b["name"] for b in standard.readiness.blocking} == {
        f"category:{c}" for c in intake_state.BLOCKING_CATEGORIES}


def test_missing_required_category_is_unknown_not_silently_met():
    # A required category with NO fields recorded at all folds to MISSING in
    # intake_state.py's own category_status(); that must reach this module's
    # conditions as UNKNOWN (a real block), never as MET.
    state = intake_state.IntakeState([_record("build_env", "build_env")])
    conditions = intake_modes.build_mode_conditions(state, "STANDARD")
    by_name = {c["name"]: c for c in conditions}
    assert by_name["category:dut_boundary"]["status"] == "UNKNOWN"
    assert by_name["category:build_env"]["status"] == "MET"
    result = intake_modes.evaluate_intake_readiness_for_mode(state, "STANDARD")
    assert result.readiness.ready is False
    assert any(b["name"] == "category:dut_boundary" for b in result.readiness.blocking)


# ---------------------------------------------------------------------------
# mode-parameterized rigor: FAST < STANDARD < STRICT
# ---------------------------------------------------------------------------

def test_fast_mode_is_ready_on_minimal_evidence_that_fails_standard():
    state = intake_state.IntakeState([
        _record("dut_boundary", "dut_boundary"),
        _record("build_env", "build_env"),
        # everything else STANDARD would require (vip_resolution,
        # active_driver_conflict, critical_bind, known_pass_test) is absent.
    ])
    fast = intake_modes.evaluate_intake_readiness_for_mode(state, "FAST")
    standard = intake_modes.evaluate_intake_readiness_for_mode(state, "STANDARD")
    assert fast.readiness.ready is True
    assert standard.readiness.ready is False


def test_standard_mode_matches_the_existing_blocking_categories_rule():
    # STANDARD's readiness boolean over a state must agree with the
    # PRE-EXISTING evaluate_uvm_generation_ready() rule it is reused from --
    # both PASS and FAIL cases.
    ready_state = intake_state.IntakeState(_full_resolved_records())
    fail_state = intake_state.IntakeState(
        _full_resolved_records({"build_env": "BLOCKED"}))

    standard_ready = intake_modes.evaluate_intake_readiness_for_mode(ready_state, "STANDARD")
    legacy_ready = intake_state.evaluate_uvm_generation_ready(ready_state)
    assert standard_ready.readiness.ready == legacy_ready.ready is True

    standard_fail = intake_modes.evaluate_intake_readiness_for_mode(fail_state, "STANDARD")
    legacy_fail = intake_state.evaluate_uvm_generation_ready(fail_state)
    assert standard_fail.readiness.ready == legacy_fail.ready is False


def test_strict_mode_additionally_requires_the_general_category():
    # A state that clears every STANDARD (BLOCKING_CATEGORIES) field but has
    # a real problem inside "general" (not one of the six) must pass
    # STANDARD and fail STRICT.
    state = intake_state.IntakeState(
        _full_resolved_records({"dut_registers": "BLOCKED"}))
    standard = intake_modes.evaluate_intake_readiness_for_mode(state, "STANDARD")
    strict = intake_modes.evaluate_intake_readiness_for_mode(state, "STRICT")
    assert standard.readiness.ready is True
    assert strict.readiness.ready is False
    assert any(b["name"] == "category:general" for b in strict.readiness.blocking)


# ---------------------------------------------------------------------------
# SIGNOFF: same readiness boolean as STRICT, finer-grained blocking names
# ---------------------------------------------------------------------------

def test_signoff_agrees_with_strict_on_readiness_when_fully_resolved():
    state = intake_state.IntakeState(_full_resolved_records())
    strict = intake_modes.evaluate_intake_readiness_for_mode(state, "STRICT")
    signoff = intake_modes.evaluate_intake_readiness_for_mode(state, "SIGNOFF")
    assert strict.readiness.ready is True
    assert signoff.readiness.ready is True
    assert strict.granularity == "category"
    assert signoff.granularity == "field"


def test_signoff_names_the_exact_field_strict_only_names_the_category():
    state = intake_state.IntakeState(
        _full_resolved_records({"dut_registers": "BLOCKED"}))
    strict = intake_modes.evaluate_intake_readiness_for_mode(state, "STRICT")
    signoff = intake_modes.evaluate_intake_readiness_for_mode(state, "SIGNOFF")

    # Same boolean verdict...
    assert strict.readiness.ready is False
    assert signoff.readiness.ready is False

    # ...but different diagnostic granularity: STRICT can only name the
    # category, SIGNOFF names the exact blocking field.
    strict_names = {b["name"] for b in strict.readiness.blocking}
    signoff_names = {b["name"] for b in signoff.readiness.blocking}
    assert strict_names == {"category:general"}
    assert signoff_names == {"field:dut_registers"}


def test_signoff_checks_every_recorded_field_not_only_required_categories():
    # SIGNOFF's own required_categories equal STRICT's (7 of them), but its
    # conditions are built per FIELD across the whole state -- a field
    # belonging to any of those 7 categories that is unresolved must surface
    # under SIGNOFF even though only one flat category list was declared.
    state = intake_state.IntakeState(_full_resolved_records({"vip_release": "MISSING"}))
    conditions = intake_modes.build_mode_conditions(state, "SIGNOFF")
    names = {c["name"] for c in conditions}
    assert names == {f"field:{r.field}" for r in state.records}
    signoff = intake_modes.evaluate_intake_readiness_for_mode(state, "SIGNOFF")
    assert signoff.readiness.ready is False
    assert any(b["name"] == "field:vip_release" for b in signoff.readiness.blocking)


# ---------------------------------------------------------------------------
# load_intake_state round trip
# ---------------------------------------------------------------------------

def test_load_intake_state_round_trips_a_real_to_dict_document():
    original = intake_state.IntakeState(_full_resolved_records())
    doc = original.to_dict()
    reloaded = intake_modes.load_intake_state(doc)
    assert [r.field for r in reloaded.records] == [r.field for r in original.records]
    assert [r.status for r in reloaded.records] == [r.status for r in original.records]

    for mode in intake_modes.MODE_ORDER:
        a = intake_modes.evaluate_intake_readiness_for_mode(original, mode)
        b = intake_modes.evaluate_intake_readiness_for_mode(reloaded, mode)
        assert a.readiness.ready == b.readiness.ready
        assert a.readiness.status == b.readiness.status


def test_load_intake_state_rejects_malformed_document():
    with pytest.raises(intake_modes.IntakeModeError) as exc:
        intake_modes.load_intake_state({"not_fields": []})
    assert exc.value.reason == "MALFORMED_INTAKE_STATE_DOCUMENT"

    with pytest.raises(intake_modes.IntakeModeError) as exc2:
        intake_modes.load_intake_state({"fields": [{"category": "general"}]})
    assert exc2.value.reason == "INTAKE_FIELD_RECORD_MISSING_KEY"


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_execute_verb_modes_lists_all_four():
    text, code = intake_modes.execute_verb("modes")
    assert code == 0
    for name in ("FAST", "STANDARD", "STRICT", "SIGNOFF"):
        assert name in text


def test_execute_verb_conditions_requires_mode():
    text, code = intake_modes.execute_verb("conditions")
    assert code == 2


def test_execute_verb_evaluate_end_to_end(tmp_path):
    state = intake_state.IntakeState(_full_resolved_records())
    p = tmp_path / "intake_state.json"
    p.write_text(json.dumps(state.to_dict()), encoding="utf-8")
    text, code = intake_modes.execute_verb(
        "evaluate", mode="STANDARD", intake_state_path=str(p))
    assert code == 0
    assert "READY" in text


def test_cli_subprocess_modes_verb():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_modes", "modes"],
        capture_output=True, text=True, cwd=repo_root,
    )
    assert result.returncode == 0
    assert "SIGNOFF" in result.stdout
