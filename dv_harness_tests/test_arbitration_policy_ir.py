"""Tests for dv_harness/arbitration_policy_ir.py -- scheme classification strictly from supplied
evidence text (never a component name), and starvation-risk detection over a declared fairness bound
vs. a declared request pattern (never an invented bound)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dv_harness import arbitration_policy_ir as apir


# ---------------------------------------------------------------------------
# classify_arbitration_scheme -- one positive control per real scheme
# ---------------------------------------------------------------------------

def test_fixed_priority_resolved_from_evidence_text():
    text = "The APB bridge implements fixed priority arbitration among the three masters."
    r = apir.classify_arbitration_scheme(text)
    assert r.scheme == "FIXED_PRIORITY"
    assert r.status == "RESOLVED"
    assert r.evidence and r.evidence[0].matched_text == "fixed priority arbitration"


def test_round_robin_resolved_from_evidence_text():
    text = "Grant is issued using round robin arbitration across all active requesters."
    r = apir.classify_arbitration_scheme(text)
    assert r.scheme == "ROUND_ROBIN"
    assert r.status == "RESOLVED"


def test_weighted_round_robin_resolved_and_not_ambiguous_with_round_robin():
    text = "This fabric uses weighted round robin arbitration; each master carries a static weight."
    r = apir.classify_arbitration_scheme(text)
    assert r.scheme == "WEIGHTED_ROUND_ROBIN"
    assert r.status == "RESOLVED"
    # de-duplication rule: the "round robin arbitration" substring must not also register as a
    # second, distinct ROUND_ROBIN finding -- containment, not ambiguity.
    schemes_cited = {e.scheme for e in r.evidence}
    assert schemes_cited == {"WEIGHTED_ROUND_ROBIN"}


def test_age_based_resolved_from_evidence_text():
    text = "Arbitration is based on request age; the oldest pending request is granted first."
    r = apir.classify_arbitration_scheme(text)
    assert r.scheme == "AGE_BASED"
    assert r.status == "RESOLVED"


def test_qos_based_resolved_from_evidence_text():
    text = "Transactions are arbitrated according to QoS: ARQOS/AWQOS values set relative priority."
    r = apir.classify_arbitration_scheme(text)
    assert r.scheme == "QOS_BASED"
    assert r.status == "RESOLVED"


# ---------------------------------------------------------------------------
# Negative controls: honest absence, never a guess
# ---------------------------------------------------------------------------

def test_no_evidence_text_is_not_available_never_guessed():
    r = apir.classify_arbitration_scheme(None)
    assert r.scheme == "UNKNOWN"
    assert r.status == "NOT_AVAILABLE"
    assert r.evidence == []

    r2 = apir.classify_arbitration_scheme("   ")
    assert r2.status == "NOT_AVAILABLE"


def test_unrecognized_phrasing_is_not_available_never_guessed():
    text = "The arbiter grants access to requesters somehow, details are implementation-defined."
    r = apir.classify_arbitration_scheme(text)
    assert r.scheme == "UNKNOWN"
    assert r.status == "NOT_AVAILABLE"


def test_component_name_alone_never_drives_classification():
    # A component NAMED for round-robin arbitration, but whose real evidence text describes a
    # completely different scheme, must classify from the TEXT, never the name.
    text = "This block implements fixed priority arbitration with master 0 always highest priority."
    r = apir.classify_arbitration_scheme(text, component_name="round_robin_arbiter_inst")
    assert r.scheme == "FIXED_PRIORITY"

    # And a suggestively-named component with NO evidence text at all must still be NOT_AVAILABLE --
    # the name is never substituted for missing evidence.
    r2 = apir.classify_arbitration_scheme(None, component_name="round_robin_arbiter_inst")
    assert r2.status == "NOT_AVAILABLE"
    assert r2.scheme == "UNKNOWN"


def test_two_genuinely_distinct_schemes_cited_is_ambiguous():
    text = ("High-priority masters use fixed priority arbitration; low-priority masters are served "
            "via round robin arbitration among themselves.")
    r = apir.classify_arbitration_scheme(text)
    assert r.status == "AMBIGUOUS"
    assert r.scheme == "UNKNOWN"
    schemes_cited = {e.scheme for e in r.evidence}
    assert schemes_cited == {"FIXED_PRIORITY", "ROUND_ROBIN"}


# ---------------------------------------------------------------------------
# extract_fairness_bound
# ---------------------------------------------------------------------------

def test_extract_fairness_bound_matches_several_real_phrasings():
    cases = [
        ("No requester shall wait more than 16 cycles for a grant.", 16),
        ("The arbiter guarantees a maximum wait of 8 cycles per requester.", 8),
        ("Grants are bounded to 32 grants per round.", 32),
        ("The scheme is starvation-free within 12 arbitration cycles.", 12),
        ("Design carries a fairness bound of 20 cycles.", 20),
    ]
    for text, expected in cases:
        bound = apir.extract_fairness_bound(text)
        assert bound is not None, text
        assert bound.value == expected


def test_extract_fairness_bound_none_when_not_stated():
    assert apir.extract_fairness_bound("Fixed priority arbitration, no further guarantee is made.") is None
    assert apir.extract_fairness_bound(None) is None
    assert apir.extract_fairness_bound("") is None


# ---------------------------------------------------------------------------
# detect_starvation_risk
# ---------------------------------------------------------------------------

def test_no_bound_fixed_priority_with_continuous_high_priority_traffic_is_potential_starvation():
    text = "The bridge implements fixed priority arbitration among the three masters."
    pattern = {"continuous_high_priority_traffic": True, "low_priority_requester_present": True}
    r = apir.detect_starvation_risk(text, "FIXED_PRIORITY", pattern)
    assert r.status == "POTENTIAL_STARVATION"
    assert r.fairness_bound is None


def test_no_bound_no_continuous_traffic_is_unknown_never_bounded():
    text = "The bridge implements fixed priority arbitration among the three masters."
    r = apir.detect_starvation_risk(text, "FIXED_PRIORITY", {"continuous_high_priority_traffic": False})
    assert r.status == "UNKNOWN"
    assert r.fairness_bound is None


def test_no_bound_non_fixed_priority_scheme_with_continuous_traffic_is_still_unknown():
    # The "continuous high-priority traffic starves a lower-priority requester" rule is specific to
    # FIXED_PRIORITY (no rotation/aging/weighting mechanism at all) -- it must not fire for a scheme
    # this module does not have evidence starves under continuous traffic.
    text = "Grant is issued using round robin arbitration across all active requesters."
    pattern = {"continuous_high_priority_traffic": True, "low_priority_requester_present": True}
    r = apir.detect_starvation_risk(text, "ROUND_ROBIN", pattern)
    assert r.status == "UNKNOWN"


def test_bound_present_observed_within_bound_is_bounded():
    text = "No requester shall wait more than 16 cycles for a grant."
    r = apir.detect_starvation_risk(text, "ROUND_ROBIN", {"max_grants_between_service": 10})
    assert r.status == "BOUNDED"
    assert r.fairness_bound is not None
    assert r.fairness_bound.value == 16


def test_bound_present_observed_exceeds_bound_is_potential_starvation():
    text = "No requester shall wait more than 16 cycles for a grant."
    r = apir.detect_starvation_risk(text, "ROUND_ROBIN", {"max_grants_between_service": 20})
    assert r.status == "POTENTIAL_STARVATION"
    assert r.fairness_bound.value == 16


def test_bound_present_no_observed_pattern_is_unknown_never_bounded():
    text = "No requester shall wait more than 16 cycles for a grant."
    r = apir.detect_starvation_risk(text, "ROUND_ROBIN", {})
    assert r.status == "UNKNOWN"
    assert r.fairness_bound is not None


def test_invalid_observed_pattern_value_raises():
    text = "No requester shall wait more than 16 cycles for a grant."
    with pytest.raises(apir.ArbitrationPolicyIRError):
        apir.detect_starvation_risk(text, "ROUND_ROBIN", {"max_grants_between_service": "a lot"})
    with pytest.raises(apir.ArbitrationPolicyIRError):
        apir.detect_starvation_risk(text, "ROUND_ROBIN", {"max_grants_between_service": True})


def test_request_pattern_duck_typed_object_supported():
    class Pattern:
        def get(self, key):
            return {"max_grants_between_service": 5}.get(key)

    text = "The arbiter guarantees a maximum wait of 8 cycles per requester."
    r = apir.detect_starvation_risk(text, "AGE_BASED", Pattern())
    assert r.status == "BOUNDED"


# ---------------------------------------------------------------------------
# build_arbitration_policy_ir -- the combined record
# ---------------------------------------------------------------------------

def test_build_arbitration_policy_ir_combines_scheme_and_starvation():
    text = ("The shared APB bridge implements fixed priority arbitration among the three masters. "
            "No requester shall wait more than 16 cycles for a grant.")
    ir = apir.build_arbitration_policy_ir(
        text, fabric_name="apb_bridge_top", component_name="apb_arb_inst",
        request_pattern={"max_grants_between_service": 12})
    assert ir.scheme_result.scheme == "FIXED_PRIORITY"
    assert ir.scheme_result.status == "RESOLVED"
    assert ir.starvation_result.status == "BOUNDED"
    d = ir.to_dict()
    assert d["fabric_name"] == "apb_bridge_top"
    assert d["scheme"]["scheme"] == "FIXED_PRIORITY"
    assert d["starvation_risk"]["status"] == "BOUNDED"


def test_build_arbitration_policy_ir_ambiguous_scheme_still_produces_starvation_verdict():
    text = ("High-priority masters use fixed priority arbitration; low-priority masters are served "
            "via round robin arbitration among themselves.")
    ir = apir.build_arbitration_policy_ir(text, request_pattern={"continuous_high_priority_traffic": True})
    assert ir.scheme_result.status == "AMBIGUOUS"
    # starvation risk is assessed against the (UNKNOWN) resolved scheme -- the FIXED_PRIORITY-only
    # starvation rule must not fire when the scheme itself could not be resolved.
    assert ir.starvation_result.status == "UNKNOWN"


def test_format_arbitration_policy_report_renders_without_error():
    text = "Grant is issued using round robin arbitration across all active requesters."
    ir = apir.build_arbitration_policy_ir(text, fabric_name="axi_fabric_0")
    report = apir.format_arbitration_policy_report(ir)
    assert "axi_fabric_0" in report
    assert "ROUND_ROBIN" in report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_json_output(tmp_path: Path, capsys):
    evidence = tmp_path / "evidence.txt"
    evidence.write_text(
        "The bridge implements fixed priority arbitration. "
        "No requester shall wait more than 16 cycles for a grant.",
        encoding="utf-8")
    pattern_file = tmp_path / "pattern.json"
    pattern_file.write_text(json.dumps({"max_grants_between_service": 4}), encoding="utf-8")

    rc = apir.main(["--evidence-file", str(evidence), "--request-pattern-file", str(pattern_file),
                     "--fabric-name", "apb_fabric", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["fabric_name"] == "apb_fabric"
    assert out["scheme"]["scheme"] == "FIXED_PRIORITY"
    assert out["starvation_risk"]["status"] == "BOUNDED"


def test_cli_text_output_with_no_inputs(capsys):
    rc = apir.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "UNKNOWN" in out
