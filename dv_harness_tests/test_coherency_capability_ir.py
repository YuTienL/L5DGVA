"""Tests for dv_harness/coherency_capability_ir.py.

Every test drives real module functions -- `classify_axis()`,
`build_coherency_capability_ir()`, `derive_overall_capability()`,
`render_coherency_capability_table()` -- and the real `python -m` CLI entry
point as a subprocess. Nothing is mocked; evidence dicts are the module's own
documented duck-typed input shape.
"""
import json
import subprocess
import sys

import pytest

from dv_harness import coherency_capability_ir as ir_mod
from dv_harness.coherency_capability_ir import (
    AXIS_NAMES,
    AXIS_BARRIER_TRANSACTION,
    AXIS_DIRTY_CLEAN_TRACKING,
    AXIS_DOMAIN_MEMBERSHIP,
    AXIS_SNOOP_TYPE,
    BASIS_DECLARED_NOT_APPLICABLE,
    BASIS_NO_EVIDENCE,
    BASIS_RTL_SIGNAL_ABSENT_FULL_ENUMERATION,
    BASIS_RTL_SIGNAL_PRESENT,
    BASIS_SIMULATION_OBSERVED,
    BASIS_SPEC_DOCUMENTED,
    CAP_NOT_APPLICABLE,
    CAP_NOT_SUPPORTED,
    CAP_SUPPORTED,
    CAP_UNKNOWN,
    OVERALL_FULL_SUPPORT,
    OVERALL_NOT_APPLICABLE,
    OVERALL_NO_SUPPORT,
    OVERALL_PARTIAL_SUPPORT,
    OVERALL_UNKNOWN,
    CoherencyCapabilityIRError,
    assert_ir_complete,
    build_coherency_capability_ir,
    classify_axis,
    derive_overall_capability,
    render_coherency_capability_table,
)


# ===========================================================================
# Core positive path
# ===========================================================================

def test_signal_presence_proves_supported_with_citation():
    result = classify_axis(AXIS_SNOOP_TYPE, {
        "signals_present": ["ARSNOOP", "AWSNOOP", "ARADDR"],
        "signals_evidence_source": "verible parse of dut_top.v:120",
    })
    assert result["status"] == CAP_SUPPORTED
    assert result["evidence_basis"] == BASIS_RTL_SIGNAL_PRESENT
    assert result["matched_signals"] == ["ARSNOOP", "AWSNOOP"]
    assert result["citations"] == ["verible parse of dut_top.v:120"]


def test_full_enumeration_absent_proves_not_supported():
    result = classify_axis(AXIS_BARRIER_TRANSACTION, {
        "signals_checked": ["ARBAR", "AWBAR", "WACK", "RACK", "ARADDR", "AWADDR"],
        "signals_evidence_source": "verible parse of dut_top.v full port list",
    })
    assert result["status"] == CAP_NOT_SUPPORTED
    assert result["evidence_basis"] == BASIS_RTL_SIGNAL_ABSENT_FULL_ENUMERATION
    assert result["matched_signals"] == []


def test_no_evidence_at_all_is_unknown_never_a_default():
    result = classify_axis(AXIS_DIRTY_CLEAN_TRACKING, None)
    assert result["status"] == CAP_UNKNOWN
    assert result["evidence_basis"] == BASIS_NO_EVIDENCE
    assert result["citations"] == []


def test_empty_dict_evidence_is_also_unknown():
    result = classify_axis(AXIS_DIRTY_CLEAN_TRACKING, {})
    assert result["status"] == CAP_UNKNOWN


def test_spec_statement_supported_is_cited():
    result = classify_axis(AXIS_DOMAIN_MEMBERSHIP, {
        "spec_statement": {"supported": True, "citation": "progguide.pdf p.44",
                            "text": "Port A participates in the Inner Shareable domain"},
    })
    assert result["status"] == CAP_SUPPORTED
    assert result["evidence_basis"] == BASIS_SPEC_DOCUMENTED
    assert result["citations"] == ["progguide.pdf p.44"]


def test_spec_statement_not_supported_is_cited():
    result = classify_axis(AXIS_BARRIER_TRANSACTION, {
        "spec_statement": {"supported": False, "citation": "progguide.pdf p.9",
                            "text": "Barrier transactions are not implemented on this port"},
    })
    assert result["status"] == CAP_NOT_SUPPORTED
    assert result["evidence_basis"] == BASIS_SPEC_DOCUMENTED


def test_simulation_observed_values_prove_supported():
    result = classify_axis(AXIS_DOMAIN_MEMBERSHIP, {
        "simulation_observed_values": ["INNER_SHAREABLE", "OUTER_SHAREABLE"],
        "simulation_evidence_source": "sim.log:4021 ARDOMAIN capture",
    })
    assert result["status"] == CAP_SUPPORTED
    assert result["evidence_basis"] == BASIS_SIMULATION_OBSERVED
    assert result["citations"] == ["sim.log:4021 ARDOMAIN capture"]


def test_declared_not_applicable_requires_reason_and_citation_and_is_honored():
    result = classify_axis(AXIS_SNOOP_TYPE, {
        "declared_not_applicable": {
            "reason": "this port is a pure APB peripheral bus with no ACE overlay of any kind",
            "citation": "soc_arch_map.json:port.apb0",
        },
    })
    assert result["status"] == CAP_NOT_APPLICABLE
    assert result["evidence_basis"] == BASIS_DECLARED_NOT_APPLICABLE


def test_full_ir_all_four_axes_supported_rolls_up_to_full_support():
    evidence = {
        AXIS_SNOOP_TYPE: {"signals_present": ["ARSNOOP"], "signals_evidence_source": "s1"},
        AXIS_DOMAIN_MEMBERSHIP: {"signals_present": ["ARDOMAIN"], "signals_evidence_source": "s2"},
        AXIS_BARRIER_TRANSACTION: {"signals_present": ["ARBAR"], "signals_evidence_source": "s3"},
        AXIS_DIRTY_CLEAN_TRACKING: {"signals_present": ["CRRESP"], "signals_evidence_source": "s4"},
    }
    ir = build_coherency_capability_ir(evidence, protocol="AXI_MM", dut_name="fabric0")
    assert_ir_complete(ir)
    assert ir.overall_capability == OVERALL_FULL_SUPPORT
    assert ir.unresolved_axes == []
    assert set(ir.axes.keys()) == set(AXIS_NAMES)


# ===========================================================================
# The Evidence Truth Rule: never inferred from a protocol name
# ===========================================================================

def test_axis_classification_never_reads_the_protocol_field():
    """`classify_axis()`'s signature carries no `protocol` argument at all --
    proven here by driving `build_coherency_capability_ir()` with the
    IDENTICAL evidence under three very different declared protocol names
    and asserting the axis results are byte-identical every time."""
    evidence = {AXIS_SNOOP_TYPE: {"signals_present": ["ARSNOOP"],
                                   "signals_evidence_source": "s1"}}
    ir_axi = build_coherency_capability_ir(evidence, protocol="AXI_MM")
    ir_amba4 = build_coherency_capability_ir(evidence, protocol="AMBA4")
    ir_none = build_coherency_capability_ir(evidence, protocol=None)
    assert ir_axi.axes == ir_amba4.axes == ir_none.axes


def test_ace_support_is_never_assumed_from_an_axi_base_protocol_name_alone():
    """Declaring `protocol="AXI_MM"` with NO evidence at all must still
    report every axis UNKNOWN -- never a fabricated NOT_SUPPORTED just
    because the base protocol is plain AXI."""
    ir = build_coherency_capability_ir({}, protocol="AXI_MM")
    assert ir.overall_capability == OVERALL_UNKNOWN
    for axis in AXIS_NAMES:
        assert ir.axes[axis]["status"] == CAP_UNKNOWN


# ===========================================================================
# Negative controls: malformed / incomplete evidence must raise, never guess
# ===========================================================================

def test_unknown_axis_name_raises():
    with pytest.raises(CoherencyCapabilityIRError) as excinfo:
        classify_axis("not_a_real_axis", {})
    assert excinfo.value.code == "UNKNOWN_AXIS"


def test_signals_present_without_a_citation_raises():
    with pytest.raises(CoherencyCapabilityIRError) as excinfo:
        classify_axis(AXIS_SNOOP_TYPE, {"signals_present": ["ARSNOOP"]})
    assert excinfo.value.code == "SIGNAL_EVIDENCE_MISSING_SOURCE"


def test_partial_signal_enumeration_never_manufactures_not_supported():
    """A caller supplying only PART of the axis's witness vocabulary as
    `signals_checked` must not be able to claim NOT_SUPPORTED -- the checked
    set must be a real superset of the full witness set."""
    result = classify_axis(AXIS_BARRIER_TRANSACTION, {
        "signals_checked": ["ARBAR"],  # missing AWBAR/WACK/RACK
        "signals_evidence_source": "partial grep only",
    })
    assert result["status"] == CAP_UNKNOWN


def test_spec_statement_missing_citation_raises():
    with pytest.raises(CoherencyCapabilityIRError) as excinfo:
        classify_axis(AXIS_DOMAIN_MEMBERSHIP, {"spec_statement": {"supported": True}})
    assert excinfo.value.code == "SPEC_STATEMENT_INCOMPLETE"


def test_declared_not_applicable_missing_reason_raises():
    with pytest.raises(CoherencyCapabilityIRError) as excinfo:
        classify_axis(AXIS_SNOOP_TYPE, {
            "declared_not_applicable": {"citation": "doc.pdf p.1"}})
    assert excinfo.value.code == "DECLARED_NOT_APPLICABLE_MISSING_CITATION"


def test_simulation_evidence_missing_source_raises():
    with pytest.raises(CoherencyCapabilityIRError) as excinfo:
        classify_axis(AXIS_DOMAIN_MEMBERSHIP, {
            "simulation_observed_values": ["INNER_SHAREABLE"]})
    assert excinfo.value.code == "SIMULATION_EVIDENCE_MISSING_SOURCE"


def test_evidence_not_a_mapping_raises():
    with pytest.raises(CoherencyCapabilityIRError) as excinfo:
        classify_axis(AXIS_SNOOP_TYPE, ["ARSNOOP"])
    assert excinfo.value.code == "EVIDENCE_NOT_A_MAPPING"


def test_unknown_axis_key_in_full_evidence_document_raises():
    with pytest.raises(CoherencyCapabilityIRError) as excinfo:
        build_coherency_capability_ir({"bogus_axis": {}})
    assert excinfo.value.code == "UNKNOWN_AXIS_IN_EVIDENCE"


def test_evidence_by_axis_must_be_a_mapping():
    with pytest.raises(CoherencyCapabilityIRError) as excinfo:
        build_coherency_capability_ir(["not", "a", "dict"])
    assert excinfo.value.code == "EVIDENCE_BY_AXIS_NOT_A_MAPPING"


# ===========================================================================
# Overall rollup
# ===========================================================================

def test_overall_no_support_when_all_axes_confirmed_absent():
    axes = {a: classify_axis(a, {"signals_checked": sorted(ir_mod.AXIS_WITNESS_SIGNALS[a]
                                                            | {"UNRELATED_SIGNAL"}),
                                  "signals_evidence_source": "full port dump"})
            for a in AXIS_NAMES}
    assert derive_overall_capability(axes) == OVERALL_NO_SUPPORT


def test_overall_not_applicable_when_every_axis_explicitly_declared_na():
    na_evidence = {"declared_not_applicable": {"reason": "no ACE overlay on this port",
                                                "citation": "doc:1"}}
    axes = {a: classify_axis(a, na_evidence) for a in AXIS_NAMES}
    assert derive_overall_capability(axes) == OVERALL_NOT_APPLICABLE


def test_overall_partial_when_some_supported_and_some_not():
    axes = dict(ir_mod.AXIS_WITNESS_SIGNALS)  # placeholder, overwritten below
    axes = {
        AXIS_SNOOP_TYPE: classify_axis(AXIS_SNOOP_TYPE, {
            "signals_present": ["ARSNOOP"], "signals_evidence_source": "s1"}),
        AXIS_DOMAIN_MEMBERSHIP: classify_axis(AXIS_DOMAIN_MEMBERSHIP, {
            "signals_checked": sorted(ir_mod.AXIS_WITNESS_SIGNALS[AXIS_DOMAIN_MEMBERSHIP]),
            "signals_evidence_source": "s2"}),
        AXIS_BARRIER_TRANSACTION: classify_axis(AXIS_BARRIER_TRANSACTION, {
            "signals_present": ["ARBAR"], "signals_evidence_source": "s3"}),
        AXIS_DIRTY_CLEAN_TRACKING: classify_axis(AXIS_DIRTY_CLEAN_TRACKING, {
            "signals_checked": sorted(ir_mod.AXIS_WITNESS_SIGNALS[AXIS_DIRTY_CLEAN_TRACKING]),
            "signals_evidence_source": "s4"}),
    }
    assert derive_overall_capability(axes) == OVERALL_PARTIAL_SUPPORT


def test_overall_unknown_wins_even_with_one_axis_confirmed_supported():
    axes = {
        AXIS_SNOOP_TYPE: classify_axis(AXIS_SNOOP_TYPE, {
            "signals_present": ["ARSNOOP"], "signals_evidence_source": "s1"}),
        AXIS_DOMAIN_MEMBERSHIP: classify_axis(AXIS_DOMAIN_MEMBERSHIP, None),
        AXIS_BARRIER_TRANSACTION: classify_axis(AXIS_BARRIER_TRANSACTION, None),
        AXIS_DIRTY_CLEAN_TRACKING: classify_axis(AXIS_DIRTY_CLEAN_TRACKING, None),
    }
    assert derive_overall_capability(axes) == OVERALL_UNKNOWN


# ===========================================================================
# Rendering + IR completeness
# ===========================================================================

def test_render_table_names_every_axis_and_the_overall_verdict():
    ir = build_coherency_capability_ir({}, protocol="AMBA4")
    text = render_coherency_capability_table(ir)
    for axis in AXIS_NAMES:
        assert axis in text
    assert OVERALL_UNKNOWN in text


def test_assert_ir_complete_passes_on_a_real_built_ir():
    ir = build_coherency_capability_ir({AXIS_SNOOP_TYPE: {
        "signals_present": ["ARSNOOP"], "signals_evidence_source": "s1"}})
    assert_ir_complete(ir)  # must not raise


def test_assert_ir_complete_rejects_a_missing_axis():
    ir = build_coherency_capability_ir({})
    del ir.axes[AXIS_SNOOP_TYPE]
    with pytest.raises(CoherencyCapabilityIRError) as excinfo:
        assert_ir_complete(ir)
    assert excinfo.value.code == "IR_MISSING_AXES"


# ===========================================================================
# CLI, driven as a real subprocess
# ===========================================================================

def _run_cli(evidence_path, extra_args=None):
    cmd = [sys.executable, "-m", "dv_harness.coherency_capability_ir",
           "--evidence", str(evidence_path)] + (extra_args or [])
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(
        __import__("pathlib").Path(__file__).resolve().parents[1]))


def test_cli_fully_supported_exits_zero(tmp_path):
    doc = {
        "protocol": "AMBA4", "dut_name": "coherent_fabric0",
        "axes": {
            AXIS_SNOOP_TYPE: {"signals_present": ["ARSNOOP"], "signals_evidence_source": "s1"},
            AXIS_DOMAIN_MEMBERSHIP: {"signals_present": ["ARDOMAIN"],
                                      "signals_evidence_source": "s2"},
            AXIS_BARRIER_TRANSACTION: {"signals_present": ["ARBAR"],
                                        "signals_evidence_source": "s3"},
            AXIS_DIRTY_CLEAN_TRACKING: {"signals_present": ["CRRESP"],
                                         "signals_evidence_source": "s4"},
        },
    }
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(doc), encoding="utf-8")
    result = _run_cli(evidence_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert OVERALL_FULL_SUPPORT in result.stdout


def test_cli_unresolved_axis_exits_one(tmp_path):
    doc = {"protocol": "AMBA4", "axes": {}}
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(doc), encoding="utf-8")
    result = _run_cli(evidence_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert OVERALL_UNKNOWN in result.stdout


def test_cli_missing_file_exits_two():
    result = _run_cli("does_not_exist.json")
    assert result.returncode == 2
    assert "NOT_AVAILABLE" in result.stdout


def test_cli_json_output_round_trips(tmp_path):
    doc = {"protocol": "AMBA4", "axes": {}}
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(doc), encoding="utf-8")
    result = _run_cli(evidence_path, extra_args=["--json"])
    parsed = json.loads(result.stdout)
    assert parsed["overall_capability"] == OVERALL_UNKNOWN
    assert set(parsed["axes"].keys()) == set(AXIS_NAMES)
