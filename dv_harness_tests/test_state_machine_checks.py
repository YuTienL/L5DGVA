"""Tests for dv_harness/uvm_generator/state_machine_checks.py -- the
STATE_MACHINE_CHECKS DSL (checker-sva-generator task, 2026-09-01, see
.work/checker-sva-generator-design-report.md and
.work/checker-sva-generator-implementation-report.md).

Mirrors test_pcie_ltssm_generator.py's own style for the pure-function
half (legal/illegal cases exercised directly against the compiled SV
text, since this DSL -- unlike pcie_ltssm_generator.py's own
validate_transition() -- compiles straight to SV text with no separate
Python-side "is this legal" predicate to test independently) plus a
generator.py integration section proving the new
UVMEnvironmentGenerator.assertions() method is a true byte-identical
no-op when "state_machine_checks" is absent, and correctly extends when
present.

Groups:
  - valid_transition_table: legal compiled shape, unknown source/target
    state refusal, malformed states list, missing state_signal
  - mutual_exclusion: exactly_one ($onehot) / at_most_one ($onehot0),
    invalid mode, too-few signals
  - legal_value_set: legal compiled shape, empty legal_values list,
    missing value_signal
  - common-field validation: missing assertion_name, invalid kind, missing
    evidence, invalid on_violation severity
  - generator.py wiring: absent/empty key -> byte-identical placeholder;
    present key -> real compiled property/assert appended; duplicate
    assertion_name across entries refused
"""
from __future__ import annotations

import tempfile

import pytest

from dv_harness.uvm_generator.generator import UVMEnvironmentGenerator, sv_id
from dv_harness.uvm_generator.state_machine_checks import (
    StateMachineCheckError,
    emit_check,
)


def _gen():
    return UVMEnvironmentGenerator(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# common-field validation
# ---------------------------------------------------------------------------

def test_missing_assertion_name_raises_typed_error():
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check({"kind": "legal_value_set", "evidence": "e",
                    "value_signal": "sig", "legal_values": ["0", "1"]})
    assert exc.value.reason == "MISSING_ASSERTION_NAME"


def test_invalid_kind_raises_typed_error():
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check({"assertion_name": "a1", "kind": "not_a_real_kind", "evidence": "e"})
    assert exc.value.reason == "INVALID_STATE_MACHINE_CHECK_KIND"


def test_missing_evidence_raises_typed_error():
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check({"assertion_name": "a1", "kind": "legal_value_set",
                    "value_signal": "sig", "legal_values": ["0"]})
    assert exc.value.reason == "MISSING_STATE_MACHINE_CHECK_EVIDENCE"


def test_invalid_on_violation_severity_raises_typed_error():
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check({"assertion_name": "a1", "kind": "legal_value_set", "evidence": "e",
                    "value_signal": "sig", "legal_values": ["0"],
                    "on_violation": {"severity": "UVM_CRITICAL"}})
    assert exc.value.reason == "INVALID_VIOLATION_SEVERITY"


def test_default_severity_is_uvm_error():
    sv = emit_check({"assertion_name": "a1", "kind": "legal_value_set", "evidence": "e",
                      "value_signal": "sig", "legal_values": ["0", "1"]})
    assert "`uvm_error" in sv


# ---------------------------------------------------------------------------
# valid_transition_table (generalizes pcie_ltssm_generator's own pattern)
# ---------------------------------------------------------------------------

LTSSM_LIKE_ENTRY = {
    "assertion_name": "ltssm_legal_transition",
    "kind": "valid_transition_table",
    "evidence": "PCIe Base Spec LTSSM top-level state diagram (illustrative, "
                 "generalized from pcie_ltssm_generator.py's own LTSSM_TRANSITIONS)",
    "state_signal": "ltssm_state",
    "states": ["DETECT", "POLLING", "CONFIGURATION", "L0"],
    "transitions": {
        "DETECT": ["POLLING"],
        "POLLING": ["CONFIGURATION", "DETECT"],
        "CONFIGURATION": ["L0", "DETECT"],
        "L0": ["DETECT"],
    },
}


def test_valid_transition_table_compiles_case_statement_and_property():
    sv = emit_check(LTSSM_LIKE_ENTRY, clk="clk", rst="rst_n")
    assert "function automatic bit ltssm_legal_transition_transition_legal(" in sv
    assert "DETECT: return (to_state inside {POLLING});" in sv
    assert "POLLING: return (to_state inside {CONFIGURATION, DETECT});" in sv
    assert "default: return 1'b0;" in sv
    assert "property ltssm_legal_transition_p;" in sv
    assert "@(posedge clk) disable iff (!rst_n)" in sv
    assert "$changed(ltssm_state) |-> ltssm_legal_transition_transition_legal($past(ltssm_state), ltssm_state);" in sv
    assert "ltssm_legal_transition_a: assert property (ltssm_legal_transition_p)" in sv
    assert "`uvm_error(\"LTSSM_LEGAL_TRANSITION_ILLEGAL_TRANSITION\"" in sv


def test_valid_transition_table_reuses_supplied_clk_rst():
    sv = emit_check(LTSSM_LIKE_ENTRY, clk="pclk", rst="presetn")
    assert "@(posedge pclk) disable iff (!presetn)" in sv


def test_valid_transition_table_missing_state_signal_raises():
    entry = dict(LTSSM_LIKE_ENTRY)
    del entry["state_signal"]
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check(entry)
    assert exc.value.reason == "MISSING_STATE_SIGNAL"


def test_valid_transition_table_invalid_states_list_raises():
    entry = dict(LTSSM_LIKE_ENTRY, states=[])
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check(entry)
    assert exc.value.reason == "INVALID_STATES_LIST"


def test_valid_transition_table_duplicate_states_raises():
    entry = dict(LTSSM_LIKE_ENTRY, states=["DETECT", "DETECT", "POLLING"])
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check(entry)
    assert exc.value.reason == "INVALID_STATES_LIST"


def test_valid_transition_table_missing_transitions_map_raises():
    entry = dict(LTSSM_LIKE_ENTRY)
    del entry["transitions"]
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check(entry)
    assert exc.value.reason == "INVALID_TRANSITIONS_MAP"


def test_valid_transition_table_unknown_source_state_raises():
    entry = dict(LTSSM_LIKE_ENTRY, transitions=dict(LTSSM_LIKE_ENTRY["transitions"],
                                                     NOT_A_STATE=["DETECT"]))
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check(entry)
    assert exc.value.reason == "UNKNOWN_TRANSITION_SOURCE_STATE"
    assert exc.value.detail["source_state"] == "NOT_A_STATE"


def test_valid_transition_table_unknown_target_state_raises():
    entry = dict(LTSSM_LIKE_ENTRY, transitions=dict(LTSSM_LIKE_ENTRY["transitions"],
                                                     DETECT=["NOT_A_STATE"]))
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check(entry)
    assert exc.value.reason == "UNKNOWN_TRANSITION_TARGET_STATE"
    assert exc.value.detail["target_state"] == "NOT_A_STATE"


def test_valid_transition_table_custom_state_type_is_used_verbatim():
    entry = dict(LTSSM_LIKE_ENTRY, state_type="my_ltssm_pkg::ltssm_state_e")
    sv = emit_check(entry)
    assert "my_ltssm_pkg::ltssm_state_e from_state, my_ltssm_pkg::ltssm_state_e to_state" in sv


# ---------------------------------------------------------------------------
# mutual_exclusion (generalizes canfd_arbitration_generator's single-winner fact)
# ---------------------------------------------------------------------------

def test_mutual_exclusion_exactly_one_uses_onehot():
    sv = emit_check({
        "assertion_name": "arb_grant_onehot",
        "kind": "mutual_exclusion",
        "evidence": "CAN-FD bus arbitration: exactly one node may win (illustrative)",
        "signals": ["grant_a", "grant_b", "grant_c"],
        "mode": "exactly_one",
    })
    assert "$onehot({grant_a, grant_b, grant_c})" in sv
    assert "property arb_grant_onehot_p;" in sv
    assert "arb_grant_onehot_a: assert property (arb_grant_onehot_p)" in sv


def test_mutual_exclusion_at_most_one_uses_onehot0():
    sv = emit_check({
        "assertion_name": "arb_grant_onehot0",
        "kind": "mutual_exclusion",
        "evidence": "at most one requester may be granted at a time (illustrative)",
        "signals": ["grant_a", "grant_b"],
        "mode": "at_most_one",
    })
    assert "$onehot0({grant_a, grant_b})" in sv


def test_mutual_exclusion_guard_is_applied():
    sv = emit_check({
        "assertion_name": "arb_grant_guarded",
        "kind": "mutual_exclusion",
        "evidence": "e",
        "signals": ["a", "b"],
        "mode": "exactly_one",
        "guard": "arb_active",
    })
    assert "disable iff (!rst_n) (arb_active) |-> $onehot({a, b});" in sv


def test_mutual_exclusion_too_few_signals_raises():
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check({"assertion_name": "a1", "kind": "mutual_exclusion", "evidence": "e",
                    "signals": ["only_one"], "mode": "exactly_one"})
    assert exc.value.reason == "INVALID_MUTEX_SIGNAL_LIST"


def test_mutual_exclusion_invalid_mode_raises():
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check({"assertion_name": "a1", "kind": "mutual_exclusion", "evidence": "e",
                    "signals": ["a", "b"], "mode": "some_other_mode"})
    assert exc.value.reason == "INVALID_MUTEX_MODE"


# ---------------------------------------------------------------------------
# legal_value_set
# ---------------------------------------------------------------------------

def test_legal_value_set_compiles_inside_property():
    sv = emit_check({
        "assertion_name": "eptype_legal",
        "kind": "legal_value_set",
        "evidence": "DEPCFG EPTYPE field is a 2-bit enum with 4 legal encodings (illustrative)",
        "value_signal": "eptype",
        "legal_values": ["2'd0", "2'd1", "2'd2", "2'd3"],
    })
    assert "(eptype inside {2'd0, 2'd1, 2'd2, 2'd3});" in sv
    assert "eptype_legal_a: assert property (eptype_legal_p)" in sv
    assert "EPTYPE_LEGAL_ILLEGAL_VALUE" in sv


def test_legal_value_set_missing_value_signal_raises():
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check({"assertion_name": "a1", "kind": "legal_value_set", "evidence": "e",
                    "legal_values": ["0"]})
    assert exc.value.reason == "MISSING_VALUE_SIGNAL"


def test_legal_value_set_empty_legal_values_raises():
    with pytest.raises(StateMachineCheckError) as exc:
        emit_check({"assertion_name": "a1", "kind": "legal_value_set", "evidence": "e",
                    "value_signal": "sig", "legal_values": []})
    assert exc.value.reason == "INVALID_LEGAL_VALUES_LIST"


# ---------------------------------------------------------------------------
# generator.py wiring: UVMEnvironmentGenerator.assertions()
# ---------------------------------------------------------------------------

BASE_MANIFEST = {"protocol": "demo_proto", "role": "DEVICE"}


def test_assertions_absent_key_is_placeholder_only():
    g = _gen()
    out = g.assertions(BASE_MANIFEST, sv_id(BASE_MANIFEST["protocol"]))
    assert out == "// Protocol-specific SVA properties come from the semantic model.\n"


def test_assertions_empty_list_is_same_placeholder_as_absent():
    g = _gen()
    m = dict(BASE_MANIFEST, state_machine_checks=[])
    out_empty = g.assertions(m, sv_id(m["protocol"]))
    out_absent = g.assertions(BASE_MANIFEST, sv_id(BASE_MANIFEST["protocol"]))
    assert out_empty == out_absent


def test_assertions_with_entry_appends_real_compiled_check():
    g = _gen()
    m = dict(BASE_MANIFEST, state_machine_checks=[LTSSM_LIKE_ENTRY])
    out = g.assertions(m, sv_id(m["protocol"]))
    assert out.startswith("// Protocol-specific SVA properties come from the semantic model.\n")
    assert "ltssm_legal_transition_a: assert property" in out


def test_assertions_reuses_manifest_clocks_and_resets_fields():
    g = _gen()
    m = dict(BASE_MANIFEST, state_machine_checks=[LTSSM_LIKE_ENTRY],
             clocks=[{"name": "pclk"}], resets=[{"name": "presetn"}])
    out = g.assertions(m, sv_id(m["protocol"]))
    assert "@(posedge pclk) disable iff (!presetn)" in out


def test_assertions_duplicate_assertion_name_raises():
    g = _gen()
    dup = dict(LTSSM_LIKE_ENTRY)
    m = dict(BASE_MANIFEST, state_machine_checks=[LTSSM_LIKE_ENTRY, dup])
    with pytest.raises(StateMachineCheckError) as exc:
        g.assertions(m, sv_id(m["protocol"]))
    assert exc.value.reason == "DUPLICATE_ASSERTION_NAME"


def test_generate_produces_assertions_file_and_wires_it_into_pkg_includes():
    g = _gen()
    m = dict(BASE_MANIFEST, state_machine_checks=[LTSSM_LIKE_ENTRY])
    files = g.generate(m)
    p = sv_id(m["protocol"])
    assert p + "_assertions.sv" in files
    content = (g.out / (p + "_assertions.sv")).read_text(encoding="utf-8")
    assert "ltssm_legal_transition_a: assert property" in content
    pkg_content = (g.out / (p + "_env_pkg.sv")).read_text(encoding="utf-8")
    assert p + "_assertions.sv" in pkg_content


def test_generate_without_state_machine_checks_still_emits_placeholder_assertions_file():
    g = _gen()
    files = g.generate(BASE_MANIFEST)
    p = sv_id(BASE_MANIFEST["protocol"])
    assert p + "_assertions.sv" in files
    content = (g.out / (p + "_assertions.sv")).read_text(encoding="utf-8")
    assert content == "// Protocol-specific SVA properties come from the semantic model.\n"
