"""Tests for spec section 184's Canonical Requirement Contract
(dv_harness/requirement_contract.py) and the extended
tools/verification_flow/spec_to_vplan_requirement_quality_gate.py.

Discipline followed here, matching test_uvm_structural_lint.py and
test_power_intent.py: ONE clean, fully-populated requirement is asserted to
produce zero findings and status COMPLETE, and every rule is then driven by
MUTATING that same clean record ONE defect at a time -- so each assertion
proves that rule caught that specific injected defect, rather than proving a
function returns a value. The gate half is driven as a REAL subprocess against
REAL files on disk, both for contract-shaped records and for records in the
older shape (whose behaviour must be byte-identical to before this change).
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "verification_flow" / "spec_to_vplan_requirement_quality_gate.py"

from dv_harness import requirement_contract as rc  # noqa: E402


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def clean_record():
    """A fully-populated, internally coherent COMPLETE requirement. Synthetic
    -- it describes no real DUT; it exists to be mutated."""
    return {
        "contract_schema_version": "1.0",
        "requirement_id": "REQ-USB-LPM-001",
        "source": {"document": "usb2_spec.pdf", "locator": "section 7.2.3",
                   "quote": "The device shall enter L1 within tL1Entry."},
        "feature": "LPM L1 entry",
        "protocol": "USB2",
        "configuration": "HS, LPM enabled",
        "precondition": "device configured, link in U0",
        "stimulus": "host issues an LPM EXT token with HIRD=3",
        "expected_result": "device ACKs and enters L1 within tL1Entry",
        "observability": "utmi_suspend_o asserted; VIP LPM callback",
        "checker": "scoreboard compares observed L1 entry latency against tL1Entry",
        "coverage_intent": "cover HIRD 0..15 crossed with BESL",
        "priority": "P0",
        "criticality": "BLOCKER",
        "confidence": "HIGH",
        "status": "COMPLETE",
    }


def legacy_record(**over):
    """A requirement in the OLDER shape the gate has always accepted."""
    r = {"req_id": "R1", "spec_ref": "s1", "feature": "f1",
         "expected_behavior": "b1", "verification_method": "directed",
         "coverage_goal": "cg1"}
    r.update(over)
    return r


def run_gate(payload, tmp_path):
    p = tmp_path / "requirements.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run([sys.executable, str(GATE), "--requirements", str(p)],
                          capture_output=True, text=True, cwd=str(ROOT))


def codes(findings):
    return {f["code"] for f in findings}


def errors(findings):
    return [f for f in findings if f["severity"] == rc.SEVERITY_ERROR]


# --------------------------------------------------------------------------
# The contract itself: fields and vocabulary
# --------------------------------------------------------------------------

def test_contract_has_section_184s_fifteen_fields_in_document_order():
    assert rc.CONTRACT_FIELDS == (
        "requirement_id", "source", "feature", "protocol", "configuration",
        "precondition", "stimulus", "expected_result", "observability",
        "checker", "coverage_intent", "priority", "criticality",
        "confidence", "status",
    )
    assert len(rc.CONTRACT_FIELDS) == 15


def test_status_vocabulary_is_section_184s_five_values():
    assert rc.REQUIREMENT_STATUSES == (
        "COMPLETE", "PARTIAL", "AMBIGUOUS", "CONTRADICTORY", "UNKNOWN")
    assert set(rc.STATUS_DEFINITIONS) == set(rc.REQUIREMENT_STATUSES)


def test_vocabularies_are_reused_not_re_typed():
    """A second copy of an existing vocabulary is exactly what this project's
    Methodology Consolidation Rule forbids, so the reuse is asserted."""
    from dv_harness.inference import CONFIDENCE_LEVELS
    from dv_harness.memory import CORNER_CASE_RISK_TIERS
    assert rc.PRIORITY_VALUES == tuple(CORNER_CASE_RISK_TIERS)
    assert rc.CONFIDENCE_VALUES == tuple(CONFIDENCE_LEVELS) + ("UNKNOWN",)


def test_clean_record_validates_against_the_json_schema():
    rc.validate_requirement_contract(clean_record())
    rc.validate_requirement_contract_set(
        {"schema_version": rc.SCHEMA_VERSION, "requirements": [clean_record()]})


def test_clean_record_is_complete_and_finding_free():
    r = clean_record()
    assert rc.analyze_requirement_contract(r) == []
    assert rc.derive_status(r)[0] == "COMPLETE"
    ok, why = rc.downstream_consumable(r)
    assert ok, why


def test_dataclass_round_trips_the_clean_record():
    c = rc.RequirementContract.from_dict(clean_record())
    assert c.requirement_id == "REQ-USB-LPM-001"
    assert c.derived_status()[0] == "COMPLETE"
    assert c.analyze() == []
    assert c.is_downstream_consumable()[0] is True
    # to_dict() preserves the contract's declared field order for diffability.
    keys = [k for k in c.to_dict() if k in rc.CONTRACT_FIELDS]
    assert keys == list(rc.CONTRACT_FIELDS)


# --------------------------------------------------------------------------
# All five status values, each DERIVED from real content
# --------------------------------------------------------------------------

def test_status_complete_is_derived_from_a_fully_resolved_record():
    assert rc.derive_status(clean_record())[0] == "COMPLETE"


def test_status_partial_is_derived_when_one_contract_field_is_unresolved():
    r = clean_record()
    r["coverage_intent"] = "TBD"
    r["status"] = "PARTIAL"
    derived, reason = rc.derive_status(r)
    assert derived == "PARTIAL"
    assert "coverage_intent" in reason
    assert rc.analyze_requirement_contract(r) == []      # declared matches derived
    assert rc.downstream_consumable(r)[0] is False


def test_status_ambiguous_is_derived_from_an_open_ambiguity():
    r = clean_record()
    r["ambiguities"] = [{"description": "tL1Entry start point undefined",
                         "resolution_or_question": "Q: measured from token or from ACK?"}]
    r["status"] = "AMBIGUOUS"
    derived, reason = rc.derive_status(r)
    assert derived == "AMBIGUOUS"
    assert "tL1Entry" in reason
    assert rc.analyze_requirement_contract(r) == []
    assert rc.downstream_consumable(r)[0] is False


def test_a_filed_question_alone_does_not_close_an_ambiguity():
    """Filing the question is escalation, not resolution -- section 32's
    'unresolved requirements remain visible as gaps'. Only an explicit
    resolved:true alongside real resolution text closes it."""
    r = clean_record()
    r["ambiguities"] = [{"description": "d", "resolution_or_question": "Q: which?"}]
    assert rc.derive_status(r)[0] == "AMBIGUOUS"
    r["ambiguities"] = [{"description": "d",
                         "resolution_or_question": "resolved: measured from the ACK",
                         "resolved": True}]
    assert rc.derive_status(r)[0] == "COMPLETE"


def test_status_contradictory_is_derived_from_an_unresolved_contradiction():
    r = clean_record()
    r["contradictions"] = [{
        "description": "tL1Entry differs between the spec and the PHY databook",
        "conflicting_sources": [{"document": "usb2_spec.pdf", "locator": "7.2.3"},
                                {"document": "phy_databook.pdf", "locator": "4.1"}]}]
    r["status"] = "CONTRADICTORY"
    derived, reason = rc.derive_status(r)
    assert derived == "CONTRADICTORY"
    assert "databook" in reason
    assert rc.analyze_requirement_contract(r) == []
    assert rc.downstream_consumable(r)[0] is False


def test_a_contradiction_outranks_an_ambiguity():
    """An unresolved conflict cannot be fixed by filling more fields in, so it
    takes precedence in derive_status()'s worst-first ordering."""
    r = clean_record()
    r["ambiguities"] = [{"description": "a", "resolution_or_question": "Q?"}]
    r["contradictions"] = [{"description": "c", "conflicting_sources": [
        {"document": "a.pdf"}, {"document": "b.pdf"}]}]
    assert rc.derive_status(r)[0] == "CONTRADICTORY"


def test_status_unknown_is_derived_when_nothing_verifiable_was_extracted():
    r = clean_record()
    r["stimulus"] = ""
    r["expected_result"] = "TBD"
    r["status"] = "UNKNOWN"
    derived, reason = rc.derive_status(r)
    assert derived == "UNKNOWN"
    assert "nothing" in reason
    assert codes(rc.analyze_requirement_contract(r)) == {"UNKNOWN_STATUS_IS_A_VISIBLE_GAP"}
    assert errors(rc.analyze_requirement_contract(r)) == []
    assert rc.downstream_consumable(r)[0] is False


def test_status_unknown_is_derived_when_the_extraction_itself_is_not_trusted():
    r = clean_record()
    r["confidence"] = "UNKNOWN"
    r["status"] = "UNKNOWN"
    derived, reason = rc.derive_status(r)
    assert derived == "UNKNOWN"
    assert "not trusted" in reason


def test_every_one_of_the_five_status_values_is_reachable_and_self_consistent():
    """One record per status value, each declaring the status its own content
    derives, each accepted with no ERROR."""
    seen = {}
    a = clean_record()
    seen["COMPLETE"] = a

    b = clean_record(); b["status"] = "PARTIAL"; b["observability"] = "TBD"
    seen["PARTIAL"] = b

    c = clean_record(); c["status"] = "AMBIGUOUS"
    c["ambiguities"] = [{"description": "d", "resolution_or_question": "Q?"}]
    seen["AMBIGUOUS"] = c

    d = clean_record(); d["status"] = "CONTRADICTORY"
    d["contradictions"] = [{"description": "d", "conflicting_sources": [
        {"document": "x.pdf"}, {"document": "y.pdf"}]}]
    seen["CONTRADICTORY"] = d

    e = clean_record(); e["status"] = "UNKNOWN"; e["confidence"] = "UNKNOWN"
    seen["UNKNOWN"] = e

    assert set(seen) == set(rc.REQUIREMENT_STATUSES)
    for status, record in seen.items():
        rc.validate_requirement_contract(record)
        assert rc.derive_status(record)[0] == status, status
        assert errors(rc.analyze_requirement_contract(record)) == [], status
        # Only COMPLETE may feed a generator.
        assert rc.downstream_consumable(record)[0] is (status == "COMPLETE"), status


# --------------------------------------------------------------------------
# A missing required field is rejected / flagged
# --------------------------------------------------------------------------

@pytest.mark.parametrize("missing", rc.CONTRACT_FIELDS)
def test_a_required_field_absent_from_the_record_is_rejected_by_the_schema(missing):
    r = clean_record()
    del r[missing]
    with pytest.raises(rc.RequirementContractValidationError) as exc:
        rc.validate_requirement_contract(r)
    assert missing in str(exc.value)


@pytest.mark.parametrize("missing", rc.CONTRACT_FIELDS)
def test_a_required_field_absent_from_the_record_is_flagged_by_the_analysis(missing):
    """The schema rejects it; the analysis names it too, because the gate
    reports findings and a caller must be told WHICH field is missing."""
    r = clean_record()
    del r[missing]
    found = rc.analyze_requirement_contract(r)
    named = [f for f in found
             if f["code"] == "MISSING_CONTRACT_FIELD" and missing in f["missing"]]
    assert named, f"{missing} not reported: {found}"
    assert named[0]["severity"] == rc.SEVERITY_ERROR


@pytest.mark.parametrize("field_name", rc.CONTRACT_TEXT_FIELDS)
def test_an_unresolved_text_field_downgrades_complete_to_partial(field_name):
    r = clean_record()
    r[field_name] = "TBD"
    derived, reason = rc.derive_status(r)
    assert derived != "COMPLETE"
    assert field_name in reason


@pytest.mark.parametrize("placeholder", ["", "   ", "UNKNOWN", "tbd", "TBD.", "N/A", "na", "?", "none"])
def test_placeholder_text_does_not_count_as_a_populated_field(placeholder):
    r = clean_record()
    r["checker"] = placeholder
    assert rc.derive_status(r)[0] == "PARTIAL"
    assert "checker" in rc.derive_status(r)[1]


def test_explicit_uppercase_none_is_a_decision_only_where_absence_is_meaningful():
    r = clean_record()
    r["configuration"] = "NONE"
    r["precondition"] = "NONE"
    assert rc.derive_status(r)[0] == "COMPLETE"
    r2 = clean_record()
    r2["checker"] = "NONE"          # a requirement with no checker is not a decision
    assert rc.derive_status(r2)[0] == "PARTIAL"


# --------------------------------------------------------------------------
# The two load-bearing dishonesty rules
# --------------------------------------------------------------------------

def test_status_overclaimed_when_complete_is_declared_over_an_unresolved_field():
    r = clean_record()
    r["checker"] = "TBD"                    # still says COMPLETE
    found = rc.analyze_requirement_contract(r)
    over = [f for f in found if f["code"] == "STATUS_OVERCLAIMED"]
    assert over and over[0]["severity"] == rc.SEVERITY_ERROR
    assert over[0]["derived_status"] == "PARTIAL"
    assert "checker" in over[0]["detail"]
    assert rc.downstream_consumable(r)[0] is False


def test_unresolved_blocker_hidden_when_a_filed_contradiction_is_stepped_over():
    r = clean_record()
    r["status"] = "PARTIAL"                 # not COMPLETE, but still hides the conflict
    r["contradictions"] = [{"description": "spec vs databook", "conflicting_sources": [
        {"document": "a.pdf"}, {"document": "b.pdf"}]}]
    found = rc.analyze_requirement_contract(r)
    hid = [f for f in found if f["code"] == "UNRESOLVED_BLOCKER_HIDDEN"]
    assert hid and hid[0]["severity"] == rc.SEVERITY_ERROR
    assert hid[0]["derived_status"] == "CONTRADICTORY"


def test_unresolved_blocker_hidden_also_fires_for_a_stepped_over_ambiguity():
    r = clean_record()
    r["status"] = "PARTIAL"
    r["observability"] = "TBD"
    r["ambiguities"] = [{"description": "a", "resolution_or_question": "Q?"}]
    assert "UNRESOLVED_BLOCKER_HIDDEN" in codes(rc.analyze_requirement_contract(r))


def test_declaring_a_weaker_status_than_the_content_supports_is_a_warning_not_an_error():
    """Honest conservatism must stay legal, but the disagreement stays visible."""
    r = clean_record()
    r["status"] = "PARTIAL"                 # everything is actually resolved
    found = rc.analyze_requirement_contract(r)
    assert codes(found) == {"STATUS_DISAGREES_WITH_CONTENT"}
    assert found[0]["severity"] == rc.SEVERITY_WARNING
    assert found[0]["derived_status"] == "COMPLETE"
    assert rc.downstream_consumable(r)[0] is False   # still not generatable


# --------------------------------------------------------------------------
# The remaining coherence rules
# --------------------------------------------------------------------------

def test_an_ambiguity_with_neither_resolution_nor_question_is_an_error():
    r = clean_record()
    r["status"] = "AMBIGUOUS"
    r["ambiguities"] = [{"description": "nobody even asked"}]
    assert "AMBIGUITY_WITHOUT_RESOLUTION_OR_QUESTION" in codes(rc.analyze_requirement_contract(r))


def test_a_contradiction_naming_fewer_than_two_sources_is_an_error():
    r = clean_record()
    r["status"] = "CONTRADICTORY"
    r["contradictions"] = [{"description": "d", "conflicting_sources": [{"document": "only.pdf"}]}]
    assert "CONTRADICTION_WITHOUT_CONFLICTING_SOURCES" in codes(rc.analyze_requirement_contract(r))


def test_declaring_ambiguous_or_contradictory_with_nothing_on_file_is_an_error():
    for status in ("AMBIGUOUS", "CONTRADICTORY"):
        r = clean_record()
        r["status"] = status
        assert "STATUS_WITHOUT_SUPPORTING_RECORD" in codes(rc.analyze_requirement_contract(r)), status


def test_an_unsourced_requirement_is_an_error():
    r = clean_record()
    r["source"] = {"document": "   "}
    assert "MISSING_SOURCE_PROVENANCE" in codes(rc.analyze_requirement_contract(r))


@pytest.mark.parametrize("field_name,bad,code", [
    ("status", "DONE", "INVALID_REQUIREMENT_STATUS"),
    ("priority", "P9", "INVALID_PRIORITY"),
    ("criticality", "CATASTROPHIC", "INVALID_CRITICALITY"),
    ("confidence", "PRETTY_SURE", "INVALID_CONFIDENCE"),
])
def test_an_out_of_vocabulary_value_is_an_error(field_name, bad, code):
    r = clean_record()
    r[field_name] = bad
    assert code in codes(rc.analyze_requirement_contract(r))
    with pytest.raises(rc.RequirementContractValidationError):
        rc.validate_requirement_contract(r)


def test_the_older_shapes_unsupported_by_dut_rule_is_carried_over():
    r = clean_record()
    r["support_status"] = "UNSUPPORTED_BY_DUT"
    assert "UNSUPPORTED_WITHOUT_DESIGN_EVIDENCE" in codes(rc.analyze_requirement_contract(r))
    r["design_evidence"] = "grep of usb_core.v shows no LPM state"
    assert "UNSUPPORTED_WITHOUT_DESIGN_EVIDENCE" not in codes(rc.analyze_requirement_contract(r))


# --------------------------------------------------------------------------
# Ambiguous-language detection (additive; does not touch derive_status())
# --------------------------------------------------------------------------

def test_clean_record_has_no_ambiguous_language():
    """The baseline fixture is unambiguous prose -- the positive control for
    every mutation below."""
    r = clean_record()
    assert rc.scan_requirement_ambiguous_language(r) == []
    assert "AMBIGUOUS_LANGUAGE_DETECTED" not in codes(rc.analyze_requirement_contract(r))


@pytest.mark.parametrize("field_name,phrase", [
    ("expected_result", "the device should generally enter L1"),
    ("expected_result", "the device typically enters L1 within tL1Entry"),
    ("checker", "check that latency is roughly tL1Entry, or similar"),
    ("checker", "the scoreboard checks as appropriate for the current mode"),
])
def test_ambiguous_hedging_language_is_detected_and_cited(field_name, phrase):
    r = clean_record()
    r[field_name] = phrase
    hits = rc.scan_requirement_ambiguous_language(r)
    assert hits and hits[0]["field"] == field_name
    assert hits[0]["phrase"] in phrase.lower()
    found = [f for f in rc.analyze_requirement_contract(r)
             if f["code"] == "AMBIGUOUS_LANGUAGE_DETECTED"]
    assert found and found[0]["severity"] == rc.SEVERITY_WARNING
    assert found[0]["field"] == field_name
    assert found[0]["matched_phrase"] in phrase.lower()
    assert phrase.lower().count(found[0]["matched_phrase"]) >= 1


def test_a_longer_hedging_phrase_is_cited_whole_not_as_a_shorter_substring():
    r = clean_record()
    r["expected_result"] = "the device should generally enter L1"
    hits = rc.scan_requirement_ambiguous_language(r)
    phrases = {h["phrase"] for h in hits}
    assert "should generally" in phrases
    assert "generally" not in phrases   # not double-cited as a substring


def test_ambiguous_language_detection_does_not_change_derived_or_declared_status():
    """Purely additive: detecting hedging prose must not flip status, must not
    block COMPLETE, and must not interact with STATUS_OVERCLAIMED /
    UNRESOLVED_BLOCKER_HIDDEN."""
    r = clean_record()
    r["expected_result"] = "the device typically enters L1 within tL1Entry"
    assert rc.derive_status(r)[0] == "COMPLETE"
    assert rc.downstream_consumable(r)[0] is True
    codes_found = codes(rc.analyze_requirement_contract(r))
    assert codes_found == {"AMBIGUOUS_LANGUAGE_DETECTED"}


@pytest.mark.parametrize("placeholder", ["TBD", "", "   ", "N/A"])
def test_a_placeholder_field_is_not_reported_as_ambiguous_language(placeholder):
    """An unresolved/placeholder field is the already-covered PARTIAL /
    MISSING_CONTRACT_FIELD defect, never vague language."""
    r = clean_record()
    r["checker"] = placeholder
    assert rc.scan_requirement_ambiguous_language(r) == []


def test_detect_ambiguous_language_ignores_non_string_input():
    assert rc.detect_ambiguous_language(None) == []
    assert rc.detect_ambiguous_language(123) == []
    assert rc.detect_ambiguous_language({"document": "x"}) == []


# --------------------------------------------------------------------------
# Cross-source contradiction (additive; a SET-level check)
# --------------------------------------------------------------------------

def test_two_records_on_the_same_feature_that_agree_report_no_contradiction():
    a, b = clean_record(), clean_record()
    a["requirement_id"], b["requirement_id"] = "REQ-A", "REQ-B"
    assert rc.cross_source_contradictions([a, b]) == []
    result = rc.analyze_requirement_contract_set([a, b])
    assert "CROSS_SOURCE_CONTRADICTION" not in codes(result["findings"])


def test_two_records_on_the_same_feature_disagreeing_on_expected_result_is_flagged():
    a, b = clean_record(), clean_record()
    a["requirement_id"], b["requirement_id"] = "REQ-A", "REQ-B"
    a["source"] = {"document": "usb2_spec.pdf", "locator": "7.2.3"}
    b["source"] = {"document": "phy_databook.pdf", "locator": "4.1"}
    b["expected_result"] = "device NAKs and stays in U0 until host retries"
    found = rc.cross_source_contradictions([a, b])
    assert len(found) == 1
    f = found[0]
    assert f["severity"] == rc.SEVERITY_WARNING
    assert f["code"] == "CROSS_SOURCE_CONTRADICTION"
    assert f["requirement_id"] == "REQ-A"
    assert f["other_requirement_id"] == "REQ-B"
    assert f["field"] == "expected_result"
    assert "CROSS_SOURCE_CONTRADICTION" in codes(
        rc.analyze_requirement_contract_set([a, b])["findings"])


def test_two_records_on_the_same_feature_disagreeing_on_configuration_is_flagged():
    a, b = clean_record(), clean_record()
    a["requirement_id"], b["requirement_id"] = "REQ-A", "REQ-B"
    b["configuration"] = "FS, LPM disabled"
    found = rc.cross_source_contradictions([a, b])
    assert any(f["field"] == "configuration" for f in found)


def test_records_on_different_features_are_never_compared():
    a, b = clean_record(), clean_record()
    a["requirement_id"], b["requirement_id"] = "REQ-A", "REQ-B"
    b["feature"] = "a completely different feature"
    b["expected_result"] = "something else entirely"
    assert rc.cross_source_contradictions([a, b]) == []


def test_feature_matching_is_case_and_whitespace_insensitive():
    a, b = clean_record(), clean_record()
    a["requirement_id"], b["requirement_id"] = "REQ-A", "REQ-B"
    a["feature"] = "  LPM L1 Entry  "
    b["feature"] = "lpm l1 entry"
    b["expected_result"] = "device NAKs instead"
    found = rc.cross_source_contradictions([a, b])
    assert len(found) == 1


def test_a_purely_cosmetic_difference_is_not_reported():
    """Whitespace/case-only differences on the compared field are NOT a
    contradiction -- only genuinely different text is."""
    a, b = clean_record(), clean_record()
    a["requirement_id"], b["requirement_id"] = "REQ-A", "REQ-B"
    b["expected_result"] = "  " + a["expected_result"].upper() + "  "
    assert rc.cross_source_contradictions([a, b]) == []


@pytest.mark.parametrize("field_name", ["expected_result", "configuration"])
def test_an_unresolved_field_on_either_side_is_not_reported_as_a_contradiction(field_name):
    """An unresolved field is the already-covered PARTIAL defect, not a
    cross-source contradiction -- reporting both would be double-counting one
    problem as two."""
    a, b = clean_record(), clean_record()
    a["requirement_id"], b["requirement_id"] = "REQ-A", "REQ-B"
    b[field_name] = "TBD"
    assert rc.cross_source_contradictions([a, b]) == []


def test_a_single_record_alone_reports_no_cross_source_contradiction():
    a = clean_record()
    assert rc.cross_source_contradictions([a]) == []


def test_legacy_records_never_participate_in_cross_source_comparison():
    a = clean_record()
    a["requirement_id"] = "REQ-A"
    legacy = legacy_record(feature=a["feature"])
    assert rc.cross_source_contradictions([a, legacy]) == []


def test_three_way_group_reports_every_disagreeing_pair():
    a, b, c = clean_record(), clean_record(), clean_record()
    a["requirement_id"], b["requirement_id"], c["requirement_id"] = "REQ-A", "REQ-B", "REQ-C"
    b["expected_result"] = "device NAKs"
    c["expected_result"] = "device ignores the token"
    found = rc.cross_source_contradictions([a, b, c])
    pairs = {(f["requirement_id"], f["other_requirement_id"]) for f in found}
    assert pairs == {("REQ-A", "REQ-B"), ("REQ-A", "REQ-C"), ("REQ-B", "REQ-C")}


def test_cross_source_contradiction_never_mutates_any_record_or_files_a_contradiction():
    """ARBITRATION IS NOT HERE: this surfaces a disagreement, it never writes
    into either record's own `contradictions` array."""
    a, b = clean_record(), clean_record()
    a["requirement_id"], b["requirement_id"] = "REQ-A", "REQ-B"
    b["expected_result"] = "device NAKs"
    snap_a, snap_b = copy.deepcopy(a), copy.deepcopy(b)
    rc.cross_source_contradictions([a, b])
    assert a == snap_a and b == snap_b
    assert a.get("contradictions", []) == [] and b.get("contradictions", []) == []


def test_duplicate_requirement_ids_are_rejected_across_the_set():
    a, b = clean_record(), clean_record()
    result = rc.analyze_requirement_contract_set([a, b])
    assert result["analyzed"] == 2
    assert "DUPLICATE_REQUIREMENT_ID" in codes(result["findings"])


def test_the_set_analysis_ignores_records_not_in_the_contract_shape():
    result = rc.analyze_requirement_contract_set([clean_record(), legacy_record()])
    assert result["analyzed"] == 1
    assert result["status_counts"]["COMPLETE"] == 1


def test_arbitration_is_never_performed_here():
    """A CONTRADICTORY requirement stops; nothing in this module picks a
    winner between two disagreeing sources."""
    r = clean_record()
    r["status"] = "CONTRADICTORY"
    r["contradictions"] = [{"description": "d", "conflicting_sources": [
        {"document": "spec.pdf"}, {"document": "databook.pdf"}]}]
    out = json.dumps(rc.analyze_requirement_contract(r)) + json.dumps(rc.derive_status(r))
    for word in ("winner", "chosen", "selected_source", "arbitrated", "auto_resolved"):
        assert word not in out
    assert rc.downstream_consumable(r)[0] is False


# --------------------------------------------------------------------------
# The extended gate, driven as a REAL subprocess
# --------------------------------------------------------------------------

def test_gate_behaviour_for_the_older_shape_is_unchanged(tmp_path):
    r = run_gate({"requirements": [legacy_record()]}, tmp_path)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["status"] == "PASS" and out["requirements"] == 1
    assert "contract_requirements" not in out   # nothing declared the new shape


@pytest.mark.parametrize("payload,code,reason", [
    ({"requirements": []}, 2, "NO_REQUIREMENTS"),
    ({"requirements": [legacy_record(coverage_goal="")]}, 3, "INCOMPLETE_VPLAN_REQUIREMENT"),
    ({"requirements": [legacy_record(ambiguity="a")]}, 4, "UNRESOLVED_REQUIREMENT_AMBIGUITY"),
    ({"requirements": [legacy_record(support_status="UNSUPPORTED_BY_DUT")]}, 5,
     "UNSUPPORTED_WITHOUT_DESIGN_EVIDENCE"),
])
def test_gates_original_exit_codes_are_preserved(payload, code, reason, tmp_path):
    r = run_gate(payload, tmp_path)
    assert r.returncode == code, r.stdout
    assert json.loads(r.stdout)["reason"] == reason


def test_gate_passes_a_clean_contract_shaped_requirement(tmp_path):
    r = run_gate({"requirements": [clean_record()]}, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["status"] == "PASS"
    assert out["contract_requirements"] == 1
    assert out["status_counts"]["COMPLETE"] == 1


def test_gate_fails_a_contract_record_that_overclaims_complete(tmp_path):
    """The headline case: this record would have PASSED the pre-2026-09-06
    gate, because none of the fields it lies about (checker, observability)
    were among the five that gate checked."""
    bad = clean_record()
    bad["checker"] = "TBD"
    # It also carries every field the OLD gate checked, so the old layer would
    # have had nothing to object to.
    bad.update({"spec_ref": "s", "expected_behavior": "b",
                "verification_method": "directed", "coverage_goal": "cg"})
    r = run_gate({"requirements": [bad]}, tmp_path)
    assert r.returncode == 6, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["reason"] == "REQUIREMENT_CONTRACT_VIOLATION"
    assert "STATUS_OVERCLAIMED" in {f["code"] for f in out["findings"]}


def test_gate_fails_a_contract_record_missing_a_required_field(tmp_path):
    bad = clean_record()
    del bad["observability"]
    r = run_gate({"requirements": [bad]}, tmp_path)
    assert r.returncode == 6, r.stdout + r.stderr
    out = json.loads(r.stdout)
    found = {f["code"] for f in out["findings"]}
    assert "CONTRACT_SCHEMA_INVALID" in found or "MISSING_CONTRACT_FIELD" in found
    assert any("observability" in json.dumps(f) for f in out["findings"])


def test_gate_fails_a_contract_record_that_hides_a_contradiction(tmp_path):
    bad = clean_record()
    bad["status"] = "PARTIAL"
    bad["contradictions"] = [{"description": "spec vs databook", "conflicting_sources": [
        {"document": "a.pdf"}, {"document": "b.pdf"}]}]
    r = run_gate({"requirements": [bad]}, tmp_path)
    assert r.returncode == 6, r.stdout + r.stderr
    assert "UNRESOLVED_BLOCKER_HIDDEN" in {f["code"] for f in json.loads(r.stdout)["findings"]}


def test_gate_accepts_a_mixed_document_and_applies_each_layer_to_its_own_records(tmp_path):
    """A contract record is NOT failed for lacking `spec_ref`/`expected_behavior`
    (fields the contract deliberately renamed), and a legacy record is NOT held
    to the contract."""
    r = run_gate({"requirements": [clean_record(), legacy_record()]}, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["requirements"] == 2 and out["contract_requirements"] == 1


def test_gate_still_applies_the_legacy_rules_to_legacy_records_in_a_mixed_document(tmp_path):
    r = run_gate({"requirements": [clean_record(), legacy_record(feature="")]}, tmp_path)
    assert r.returncode == 3, r.stdout
    assert json.loads(r.stdout)["reason"] == "INCOMPLETE_VPLAN_REQUIREMENT"


def test_gate_is_fail_closed_when_the_contract_validator_cannot_be_imported(tmp_path):
    """A record that EXPLICITLY asked to be held to the richer contract must
    never pass because the validator was missing -- that would turn a stricter
    declaration into a weaker gate."""
    p = tmp_path / "requirements.json"
    p.write_text(json.dumps({"requirements": [clean_record()]}), encoding="utf-8")
    empty = tmp_path / "no_dv_harness"
    empty.mkdir()
    r = subprocess.run([sys.executable, str(GATE), "--requirements", str(p)],
                       capture_output=True, text=True, cwd=str(tmp_path),
                       env={**_clean_env(), "DV_HARNESS_PACKAGE_ROOT": str(empty)})
    assert r.returncode == 7, r.stdout + r.stderr
    assert json.loads(r.stdout)["reason"] == "REQUIREMENT_CONTRACT_VALIDATOR_UNAVAILABLE"


def _clean_env():
    """An environment with this repo removed from PYTHONPATH, so the
    fail-closed test really cannot import dv_harness."""
    import os
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


# --------------------------------------------------------------------------
# The CLI verb, driven as a REAL subprocess
# --------------------------------------------------------------------------

def _cli(tmp_path, payload, *extra):
    p = tmp_path / "reqs.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.requirement_contract",
         "--requirements", str(p), *extra],
        capture_output=True, text=True, cwd=str(ROOT))


def test_cli_exit_codes(tmp_path):
    ok = _cli(tmp_path, {"requirements": [clean_record()]}, "--json")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert json.loads(ok.stdout)["status"] == "PASS"

    bad = clean_record(); bad["checker"] = "TBD"
    fail = _cli(tmp_path, {"requirements": [bad]}, "--json")
    assert fail.returncode == 1
    assert json.loads(fail.stdout)["status"] == "FAIL"

    # Nothing in the contract shape is NOT_AVAILABLE, never a clean PASS.
    na = _cli(tmp_path, {"requirements": [legacy_record()]}, "--json")
    assert na.returncode == 2
    assert json.loads(na.stdout)["status"] == "NOT_AVAILABLE"


def test_cli_fail_on_error_also_fails_on_warnings(tmp_path):
    warn = clean_record(); warn["status"] = "PARTIAL"     # honest conservatism
    assert _cli(tmp_path, {"requirements": [warn]}, "--json").returncode == 0
    assert _cli(tmp_path, {"requirements": [warn]}, "--json",
                "--fail-on-error").returncode == 1


def test_dv_harness_cli_exposes_the_same_implementation(tmp_path):
    p = tmp_path / "reqs.json"
    p.write_text(json.dumps({"requirements": [clean_record()]}), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "dv_harness", "requirement-contract",
                        "--requirements", str(p), "--json"],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout[r.stdout.index("{"):])["status"] == "PASS"


def test_analysis_is_pure_and_does_not_mutate_its_input():
    r = clean_record()
    snapshot = copy.deepcopy(r)
    rc.analyze_requirement_contract(r)
    rc.derive_status(r)
    rc.downstream_consumable(r)
    assert r == snapshot
