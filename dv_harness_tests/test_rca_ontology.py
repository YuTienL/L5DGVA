"""Tests for dv_harness/rca_ontology.py -- Root-Cause Ontology + Failure-Signature
Normalization.

Covers: (1) the eleven-category ontology's positive/negative classification and
its priority order; (2) closure-status reuse of the real
`memory_router.route_memory()` / `engineering_admission_gate()` machinery,
including the negative control that an unverified/ungated record is NEVER
categorized (the Evidence Truth Rule's own refuse-to-fabricate property); (3)
the canonical failure-signature normalizer, proven to be a genuine reuse of
`sim_log_analysis.normalize_failure_signature()` / `memory_vault.
build_failure_signature()` / `evidence_db.signature_key()` -- not a fourth,
independently-invented definition of "same failure"; (4) the aggregation
report's honest exclusion accounting; (5) the vocabulary-disjointness guards;
(6) the standalone CLI front door.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import rca_ontology as rca
from dv_harness.sim_log_analysis import normalize_failure_signature
from dv_harness.memory_vault import build_failure_signature
from dv_harness.evidence_db import signature_key


# ---------------------------------------------------------------------------
# Fixtures: real record shapes mirroring engine._promote_verified_fix_
# knowledge()'s own kind="verified_fix" record.
# ---------------------------------------------------------------------------

def _closed_record(**overrides):
    rec = {
        "kind": "verified_fix",
        "verified": True,
        "title": "Verified fix: scoreboard mismatch",
        "scope": "engineering",
        "symptoms": ["APB read data mismatch @ 12345 ns, seed=9981"],
        "root_cause": "A comparison logic bug in the reference model predictor "
                       "caused a scoreboard mismatch on read data.",
        "fix": "Corrected predictor byte-lane indexing.",
        "evidence": "sim.log excerpt at .dv-harness/lsf/jobs/job-1.log:412 shows the mismatch",
        "confidence": "HIGH",
        "protocol": "APB",
        "pattern": "apb_rw_pattern",
    }
    rec.update(overrides)
    return rec


# ---------------------------------------------------------------------------
# (1) Category ontology.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("category,text", [
    ("KNOWN_LIMITATION_ACCEPTED_RISK", "This is a known limitation of the current design."),
    ("FLAKY_NONDETERMINISTIC_BEHAVIOR", "The test is flaky and intermittently fails."),
    ("TOOLCHAIN_INFRASTRUCTURE_DEFECT", "Root cause was a license server outage."),
    ("CONFIGURATION_ERROR", "The environment was misconfigured with a wrong plusarg."),
    ("SPEC_REQUIREMENT_DEFECT", "The specification is ambiguous about reset timing."),
    ("COVERAGE_MODEL_DEFECT", "There was a coverage bin error in the covergroup bug."),
    ("CHECKER_SCOREBOARD_DEFECT", "A scoreboard bug caused a predictor mismatch."),
    ("STIMULUS_SEQUENCE_DEFECT", "A sequence bug caused invalid stimulus generation error."),
    ("VIP_DEFECT_OR_MISCONFIGURATION", "Traced to a vip bug in the svt_apb_master agent."),
    ("TESTBENCH_ENVIRONMENT_DEFECT", "A testbench bug in the monitor bug caused this."),
    ("DUT_RTL_DEFECT", "This was a genuine rtl bug in the FSM logic."),
])
def test_classify_root_cause_category_positive(category, text):
    result = rca.classify_root_cause_category(text)
    assert result.category == category
    assert result.matched_evidence
    assert result.matched_evidence.lower() in text.lower()


def test_classify_root_cause_category_unclassified_on_no_match():
    result = rca.classify_root_cause_category("Everything passed cleanly with no issue.")
    assert result.category == rca.UNCLASSIFIED
    assert result.matched_evidence == ""


def test_classify_root_cause_category_unclassified_on_empty_or_none():
    assert rca.classify_root_cause_category("").category == rca.UNCLASSIFIED
    assert rca.classify_root_cause_category(None).category == rca.UNCLASSIFIED


def test_classification_order_matches_categories_exactly():
    assert set(rca.CLASSIFICATION_ORDER) == set(rca.ROOT_CAUSE_CATEGORIES)
    assert len(rca.CLASSIFICATION_ORDER) == 11


def test_known_limitation_wins_priority_over_component_defect_language():
    # "known limitation" (checked first) must win even when a component-defect
    # phrase ("rtl bug") also appears in the same text.
    text = "This is a known limitation; an rtl bug elsewhere is unrelated noise."
    result = rca.classify_root_cause_category(text)
    assert result.category == "KNOWN_LIMITATION_ACCEPTED_RISK"


# ---------------------------------------------------------------------------
# (2) Closure status -- reused, not re-derived.
# ---------------------------------------------------------------------------

def test_closure_status_not_root_cause_record_for_wrong_kind():
    rec = _closed_record(kind="job_result")
    status, reasons = rca.closure_status(rec)
    assert status == rca.NOT_ROOT_CAUSE_RECORD
    assert reasons


def test_closure_status_not_root_cause_record_for_unverified():
    rec = _closed_record(verified=False)
    status, reasons = rca.closure_status(rec)
    assert status == rca.NOT_ROOT_CAUSE_RECORD


def test_closure_status_not_yet_closed_for_unevidenced_low_confidence_guess():
    # kind+verified pass route_memory()'s check, but no real evidence, low
    # confidence, and no reusable claim field -- must fail the real
    # engineering_admission_gate() and be reported NOT_YET_CLOSED, never
    # silently treated as closed.
    rec = {"kind": "root_cause", "verified": True}
    status, reasons = rca.closure_status(rec)
    assert status == rca.NOT_YET_CLOSED
    assert "NO_EVIDENCE" in reasons
    assert "CONFIDENCE_BELOW_HIGH" in reasons
    assert "NO_REUSABLE_CLAIM" in reasons


def test_closure_status_closed_eligible_for_a_real_gate_verified_record():
    rec = _closed_record()
    status, reasons = rca.closure_status(rec)
    assert status == rca.CLOSED_ELIGIBLE
    assert reasons == []


def test_closure_status_raises_on_non_dict_record():
    with pytest.raises(rca.RcaOntologyError):
        rca.closure_status("not a dict")


# ---------------------------------------------------------------------------
# Negative control: an ungated record is NEVER categorized or keyed -- the
# Evidence Truth Rule's own "never fabricate an answer when evidence is
# absent" property, proven directly.
# ---------------------------------------------------------------------------

def test_unclosed_record_is_never_categorized_or_signature_keyed():
    rec = {"kind": "root_cause", "verified": True, "root_cause": "an rtl bug"}
    result = rca.classify_closed_root_cause_record(rec)
    assert result.closure_status == rca.NOT_YET_CLOSED
    assert result.category is None
    assert result.signature_key is None
    assert result.signature is None
    assert result.matched_evidence == ""


def test_wrong_kind_record_is_never_categorized_or_signature_keyed():
    rec = {"kind": "job_result", "verified": True, "root_cause": "an rtl bug"}
    result = rca.classify_closed_root_cause_record(rec)
    assert result.closure_status == rca.NOT_ROOT_CAUSE_RECORD
    assert result.category is None
    assert result.signature_key is None


def test_closed_eligible_record_is_categorized_with_real_evidence():
    rec = _closed_record()
    result = rca.classify_closed_root_cause_record(rec)
    assert result.closure_status == rca.CLOSED_ELIGIBLE
    assert result.category == "CHECKER_SCOREBOARD_DEFECT"
    assert result.matched_evidence
    assert result.signature_key
    assert isinstance(result.signature, dict)


# ---------------------------------------------------------------------------
# (3) Canonical failure-signature normalizer -- proven to be a REAL reuse.
# ---------------------------------------------------------------------------

def test_canonical_failure_signature_matches_direct_composition_of_reused_functions():
    """The headline reuse proof: canonical_failure_signature()'s result must be
    IDENTICAL to manually chaining sim_log_analysis.normalize_failure_signature()
    -> memory_vault.build_failure_signature() -> evidence_db.signature_key()
    directly -- proving this module adds no independent signature logic of its
    own."""
    raw_symptom = "APB read data mismatch @ 12345 ns, seed=9981"
    raw_hint = "predictor byte-lane bug @ 500 ns"

    expected_symptom = normalize_failure_signature(raw_symptom)
    expected_hint = normalize_failure_signature(raw_hint)
    expected_sig = build_failure_signature(
        protocol="APB", pattern="apb_rw_pattern",
        symptom=expected_symptom, root_cause_hint=expected_hint,
    )
    expected_key = signature_key(expected_sig)

    result = rca.canonical_failure_signature(
        protocol="APB", pattern="apb_rw_pattern",
        symptom=raw_symptom, root_cause_hint=raw_hint,
    )
    assert result.signature == expected_sig
    assert result.signature_key == expected_key


def test_canonical_failure_signature_normalization_collapses_cosmetic_variance():
    """Two symptom strings differing only in timestamp/seed (the exact cosmetic
    variance sim_log_analysis.normalize_failure_signature() strips) must
    collapse to the SAME signature key when normalize_text=True."""
    sig_a = rca.canonical_failure_signature(
        protocol="APB", symptom="mismatch on read data @ 100 ns, seed=1",
    )
    sig_b = rca.canonical_failure_signature(
        protocol="APB", symptom="mismatch on read data @ 999999 ns, seed=42",
    )
    assert sig_a.signature_key == sig_b.signature_key


def test_canonical_failure_signature_normalize_false_preserves_raw_text():
    sig = rca.canonical_failure_signature(
        protocol="APB", symptom="mismatch @ 100 ns", normalize_text=False,
    )
    assert sig.signature["symptom"] == "mismatch @ 100 ns"


def test_canonical_signature_for_record_uses_root_cause_when_no_symptom_declared():
    rec = {"protocol": "APB", "pattern": "p", "root_cause": "bug @ 100 ns"}
    result = rca.canonical_signature_for_record(rec)
    # the record's own root_cause text feeds BOTH symptom (fallback) and
    # root_cause_hint -- normalized identically -- so the signature dict
    # actually carries real, non-empty content sourced from the record.
    assert result.signature["symptom"]
    assert result.signature["root_cause_hint"]


def test_canonical_signature_for_record_prefers_declared_symptom():
    rec = _closed_record()
    result = rca.canonical_signature_for_record(rec)
    assert "read data mismatch" in result.signature["symptom"]


def test_canonical_signature_for_record_raises_on_non_dict():
    with pytest.raises(rca.RcaOntologyError):
        rca.canonical_signature_for_record("not a dict")


# ---------------------------------------------------------------------------
# (4) Aggregation report -- honest exclusion accounting.
# ---------------------------------------------------------------------------

def test_aggregate_root_cause_categories_only_counts_eligible_records():
    records = [
        _closed_record(),                                    # CLOSED_ELIGIBLE, CHECKER_SCOREBOARD_DEFECT
        {"kind": "root_cause", "verified": True},              # NOT_YET_CLOSED
        {"kind": "job_result", "verified": True},               # NOT_ROOT_CAUSE_RECORD
        _closed_record(root_cause="Traced to an rtl bug in the FSM.",
                        symptoms=["a different symptom @ 1 ns"]),  # CLOSED_ELIGIBLE, DUT_RTL_DEFECT
    ]
    report = rca.aggregate_root_cause_categories(records)
    assert len(report.eligible_records()) == 2
    assert report.excluded_count == 2
    assert report.category_counts.get("CHECKER_SCOREBOARD_DEFECT") == 1
    assert report.category_counts.get("DUT_RTL_DEFECT") == 1
    assert len(report.records) == 4


def test_aggregate_root_cause_categories_groups_identical_signatures():
    # Two closed records whose real evidence differs only in cosmetic variance
    # (a timestamp) must land in the SAME signature group.
    records = [
        _closed_record(symptoms=["APB read data mismatch @ 1 ns, seed=1"]),
        _closed_record(symptoms=["APB read data mismatch @ 999 ns, seed=2"]),
    ]
    report = rca.aggregate_root_cause_categories(records)
    assert len(report.eligible_records()) == 2
    assert len(report.signature_groups) == 1
    (only_key, ids), = report.signature_groups.items()
    assert len(ids) == 2


def test_aggregate_root_cause_categories_raises_on_non_list_input():
    with pytest.raises(rca.RcaOntologyError):
        rca.aggregate_root_cause_categories("not a list")


def test_aggregate_root_cause_categories_empty_list_reports_zero_eligible():
    report = rca.aggregate_root_cause_categories([])
    assert report.eligible_records() == []
    assert report.excluded_count == 0
    assert report.category_counts == {}


# ---------------------------------------------------------------------------
# (5) Vocabulary disjointness -- distinct from command_error_taxonomy.py /
# system_failure_taxonomy.py / models.Status, per the task's own requirement.
# ---------------------------------------------------------------------------

def test_disjoint_from_command_error_taxonomy():
    from dv_harness import command_error_taxonomy as cet
    rca.assert_disjoint_from_command_error_taxonomy()  # must not raise
    assert not set(rca.ROOT_CAUSE_CATEGORIES).intersection(set(cet.CATEGORIES))


def test_disjoint_from_system_failure_taxonomy():
    from dv_harness import system_failure_taxonomy as sft
    rca.assert_disjoint_from_system_failure_taxonomy()  # must not raise
    assert not set(rca.ROOT_CAUSE_CATEGORIES).intersection(set(sft.FAILURE_CATEGORIES))


def test_disjoint_from_verification_verdict_vocabulary():
    from dv_harness.models import Status
    rca.assert_no_verification_verdict_vocabulary()  # must not raise
    verdicts = {s.value for s in Status}
    vocab = set(rca.ROOT_CAUSE_CATEGORIES) | {rca.UNCLASSIFIED} | set(rca.CLOSURE_STATUSES)
    assert not vocab.intersection(verdicts)


def test_vocabulary_guards_have_real_detection_power():
    """Mutation-style proof the disjointness guards actually detect a real
    collision rather than trivially passing on any input."""
    import dv_harness.rca_ontology as m
    original = list(m.ROOT_CAUSE_CATEGORIES)
    try:
        m.ROOT_CAUSE_CATEGORIES = tuple(original) + ("PASS",)  # collides with models.Status
        with pytest.raises(AssertionError):
            m.assert_no_verification_verdict_vocabulary()
    finally:
        m.ROOT_CAUSE_CATEGORIES = tuple(original)


# ---------------------------------------------------------------------------
# (6) Standalone CLI front door.
# ---------------------------------------------------------------------------

def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.rca_ontology", *args],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True,
    )


def test_cli_categories_lists_all_eleven():
    proc = _run_cli("categories")
    assert proc.returncode == 0
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    assert set(lines) == set(rca.ROOT_CAUSE_CATEGORIES)


def test_cli_classify_exit_0_on_real_records(tmp_path):
    records_file = tmp_path / "records.json"
    records_file.write_text(json.dumps([_closed_record()]), encoding="utf-8")
    proc = _run_cli("classify", "--records", str(records_file))
    assert proc.returncode == 0
    assert "eligible=1" in proc.stdout
    assert "CHECKER_SCOREBOARD_DEFECT" in proc.stdout


def test_cli_classify_exit_1_on_malformed_json(tmp_path):
    records_file = tmp_path / "bad.json"
    records_file.write_text("{not json", encoding="utf-8")
    proc = _run_cli("classify", "--records", str(records_file))
    assert proc.returncode == 1
    assert "MALFORMED_INPUT" in proc.stdout


def test_cli_classify_exit_2_on_empty_records(tmp_path):
    records_file = tmp_path / "empty.json"
    records_file.write_text("[]", encoding="utf-8")
    proc = _run_cli("classify", "--records", str(records_file))
    assert proc.returncode == 2
    assert "NOT_AVAILABLE" in proc.stdout


def test_cli_classify_exit_2_on_missing_file(tmp_path):
    proc = _run_cli("classify", "--records", str(tmp_path / "nope.json"))
    assert proc.returncode == 2
    assert "NOT_AVAILABLE" in proc.stdout
