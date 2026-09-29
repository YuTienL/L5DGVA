"""Tests for dv_harness/vip_erratum_correlation.py -- erratum/known-
limitation facts extracted from a REAL, offline-distilled VIP document, each
with a real document+line citation, correlated against caller-declared,
evidence-cited project usage facts (which pattern/config exercises which
feature).

The synthetic errata-sheet fixture below states in its own text that it is a
test fixture and describes no real vendor VIP -- consistent with the
"No Golden-Reference Content Mining" rule: nothing here is mined from, or
compared against, a real vendor's errata sheet.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import vip_erratum_correlation as vec
from dv_harness import vip_user_guide_distill as ugd

FIXTURE_TEXT = """1.0 Overview

This is a synthetic VIP errata document test fixture. It is not real vendor
content and describes no real VIP feature set.

5.0 Known Limitations

ERR-101: The LPM sub-state machine may re-enter L1 prematurely. This limitation affects the LPM exit-latency logic.

ERR-102: Burst-mode DMA transfers longer than 4KB may stall. This restriction applies to DMA burst-mode transfers.

- Scoreboard checksum validation is skipped when using non-standard packet sizes.

Known Issue 5: minor cosmetic log message formatting.

USB3 LPM: exit latency may exceed spec under back-to-back transactions.

6.0 Compliance Requirements

- Eye height shall exceed 50 mV at the compliance test point.
"""

NO_MARKER_TEXT = """1.0 Overview

This synthetic fixture intentionally contains none of this module's
structural errata section markers anywhere in its text.

2.0 Miscellaneous

- Some bullet point that is not inside any recognized section.
"""

MARKER_NO_ITEMS_TEXT = """5.0 Known Limitations

This section discusses known limitations in prose only, with no recognizable
"ID: description" or bulleted/numbered item lines at all, just paragraphs of
running text that happen to be longer than a heading and end with a period
so they are never mistaken for one either.
"""


@pytest.fixture()
def distilled_errata_doc(tmp_path):
    src = tmp_path / "synthetic_errata.txt"
    src.write_text(FIXTURE_TEXT, encoding="utf-8")
    out_dir = tmp_path / "distilled"
    record = ugd.distill_user_guide(src, out_dir, title="Synthetic VIP Errata Sheet",
                                      doc_kind="vip_user_guide")
    return record


def _distill(tmp_path, text, name="doc.txt"):
    src = tmp_path / name
    src.write_text(text, encoding="utf-8")
    return ugd.distill_user_guide(src, tmp_path / "distilled", title="Synthetic", doc_kind="vip_user_guide")


# ===========================================================================
# vocabulary hygiene
# ===========================================================================

def test_vocabulary_does_not_collide_with_models_status():
    vec.assert_no_verification_verdict_vocabulary()  # must not raise


# ===========================================================================
# absent/malformed document -> NOT_AVAILABLE, never a guess
# ===========================================================================

def test_no_document_supplied_is_not_available():
    report = vec.build_erratum_correlation()
    assert report["status"] == vec.STATUS_NOT_AVAILABLE
    assert report["source"] is None
    assert report["entries"] == []
    assert report["reason"]


def test_missing_reference_record_path_reports_not_available(tmp_path):
    report = vec.build_erratum_correlation(reference_record_path=tmp_path / "nope.reference.json")
    assert report["status"] == vec.STATUS_NOT_AVAILABLE
    assert "could not load" in report["reason"]


def test_malformed_reference_record_dict_is_rejected():
    report = vec.build_erratum_correlation(reference_record={"schema_version": "1.0"})
    assert report["status"] == vec.STATUS_NOT_AVAILABLE
    assert "missing" in report["reason"]


def test_missing_fulltext_file_on_disk_reports_not_available(distilled_errata_doc):
    Path(distilled_errata_doc["full_text_extract"]["path"]).unlink()
    report = vec.build_erratum_correlation(reference_record=distilled_errata_doc)
    assert report["status"] == vec.STATUS_NOT_AVAILABLE
    assert "missing on disk" in report["reason"]


def test_no_marker_section_at_all_reports_not_available(tmp_path):
    record = _distill(tmp_path, NO_MARKER_TEXT)
    report = vec.build_erratum_correlation(reference_record=record)
    assert report["status"] == vec.STATUS_NOT_AVAILABLE
    assert report["source"]["marker_seen"] is False
    assert report["entries"] == []


def test_marker_section_with_no_items_reports_not_available(tmp_path):
    record = _distill(tmp_path, MARKER_NO_ITEMS_TEXT)
    report = vec.build_erratum_correlation(reference_record=record)
    assert report["status"] == vec.STATUS_NOT_AVAILABLE
    assert report["source"]["marker_seen"] is True
    assert report["entries"] == []


# ===========================================================================
# real document -> real erratum entries, real citations
# ===========================================================================

def test_extracted_entries_have_real_line_citations(distilled_errata_doc):
    report = vec.build_erratum_correlation(reference_record=distilled_errata_doc)
    assert report["status"] == "SCANNED"
    assert report["source"]["marker_seen"] is True
    assert report["source"]["fulltext_sha256_verified"] is True
    assert len(report["entries"]) >= 4
    for e in report["entries"]:
        assert e["citation"]["document"] == "Synthetic VIP Errata Sheet"
        assert e["citation"]["line"] > 0
        assert e["citation"]["fulltext_path"]


def test_compliance_section_never_leaks_into_known_limitations(distilled_errata_doc):
    report = vec.build_erratum_correlation(reference_record=distilled_errata_doc)
    descriptions = [e["description"] for e in report["entries"]]
    assert not any("Eye height" in d for d in descriptions)


def test_explicit_affects_phrase_wins_over_id_label(distilled_errata_doc):
    report = vec.build_erratum_correlation(reference_record=distilled_errata_doc)
    entry = next(e for e in report["entries"] if e["erratum_id"] == "ERR-101")
    assert entry["affected_feature"] == "LPM exit-latency logic"
    assert entry["affected_feature_source"] == vec.FEATURE_SOURCE_PHRASE_MATCH


def test_applies_to_phrase_extracted_for_second_entry(distilled_errata_doc):
    report = vec.build_erratum_correlation(reference_record=distilled_errata_doc)
    entry = next(e for e in report["entries"] if e["erratum_id"] == "ERR-102")
    assert entry["affected_feature"] == "DMA burst-mode transfers"
    assert entry["affected_feature_source"] == vec.FEATURE_SOURCE_PHRASE_MATCH


def test_when_using_phrase_extracted_for_bare_bullet_item(distilled_errata_doc):
    report = vec.build_erratum_correlation(reference_record=distilled_errata_doc)
    bullet = next(e for e in report["entries"] if e["erratum_id"] is None)
    assert bullet["affected_feature"] == "non-standard packet sizes"
    assert bullet["affected_feature_source"] == vec.FEATURE_SOURCE_PHRASE_MATCH


def test_pure_id_label_never_becomes_a_feature_name(distilled_errata_doc):
    report = vec.build_erratum_correlation(reference_record=distilled_errata_doc)
    entry = next(e for e in report["entries"] if e["erratum_id"] == "Known Issue 5")
    assert entry["affected_feature"] is None
    assert entry["affected_feature_source"] == vec.FEATURE_SOURCE_NOT_ANNOTATED
    assert entry["correlation"]["status"] == vec.STATUS_UNRESOLVABLE_NO_AFFECTED_FEATURE


def test_non_id_shaped_label_falls_back_to_id_label_inferred(distilled_errata_doc):
    report = vec.build_erratum_correlation(reference_record=distilled_errata_doc)
    entry = next(e for e in report["entries"] if e["erratum_id"] == "USB3 LPM")
    assert entry["affected_feature"] == "USB3 LPM"
    assert entry["affected_feature_source"] == vec.FEATURE_SOURCE_ID_LABEL_INFERRED


def test_looks_like_pure_id_helper_directly():
    assert vec._looks_like_pure_id("ERR-101")
    assert vec._looks_like_pure_id("KI3")
    assert vec._looks_like_pure_id("Issue #12")
    assert vec._looks_like_pure_id("1.2.3")
    assert vec._looks_like_pure_id("Known Issue 5")
    assert not vec._looks_like_pure_id("USB3 LPM")
    assert not vec._looks_like_pure_id("DMA burst mode")


# ===========================================================================
# usage-fact validation -- an uncited claim is refused, never accepted
# ===========================================================================

def test_validate_usage_facts_accepts_a_clean_fact():
    facts = vec.validate_usage_facts([
        {"id": "pattern_usb3_lpm_stress", "kind": "pattern",
         "exercises_features": ["LPM exit-latency logic"], "evidence": "command.txt:142"},
    ])
    assert facts[0]["id"] == "pattern_usb3_lpm_stress"
    assert facts[0]["kind"] == "pattern"


def test_validate_usage_facts_none_or_empty_is_a_clean_empty_list():
    assert vec.validate_usage_facts(None) == []
    assert vec.validate_usage_facts([]) == []


def test_validate_usage_facts_rejects_non_dict_entry():
    with pytest.raises(vec.VipErratumCorrelationError, match="not an object"):
        vec.validate_usage_facts(["not-a-dict"])


def test_validate_usage_facts_rejects_missing_id():
    with pytest.raises(vec.VipErratumCorrelationError, match="'id'"):
        vec.validate_usage_facts([{"exercises_features": ["x"], "evidence": "e"}])


def test_validate_usage_facts_rejects_missing_exercises_features():
    with pytest.raises(vec.VipErratumCorrelationError, match="exercises_features"):
        vec.validate_usage_facts([{"id": "p1", "evidence": "e"}])


def test_validate_usage_facts_rejects_empty_exercises_features():
    with pytest.raises(vec.VipErratumCorrelationError, match="exercises_features"):
        vec.validate_usage_facts([{"id": "p1", "exercises_features": [], "evidence": "e"}])


def test_validate_usage_facts_rejects_non_string_feature_entry():
    with pytest.raises(vec.VipErratumCorrelationError, match="exercises_features"):
        vec.validate_usage_facts([{"id": "p1", "exercises_features": [123], "evidence": "e"}])


def test_validate_usage_facts_rejects_missing_evidence():
    with pytest.raises(vec.VipErratumCorrelationError, match="evidence"):
        vec.validate_usage_facts([{"id": "p1", "exercises_features": ["x"]}])


def test_validate_usage_facts_rejects_blank_evidence():
    with pytest.raises(vec.VipErratumCorrelationError, match="evidence"):
        vec.validate_usage_facts([{"id": "p1", "exercises_features": ["x"], "evidence": "   "}])


def test_build_erratum_correlation_propagates_malformed_usage_fact(distilled_errata_doc):
    with pytest.raises(vec.VipErratumCorrelationError):
        vec.build_erratum_correlation(
            reference_record=distilled_errata_doc,
            usage_facts=[{"id": "p1", "exercises_features": ["x"]}],  # no evidence
        )


# ===========================================================================
# correlate_entry() -- the four-status verdict
# ===========================================================================

def _entry(affected_feature):
    return {
        "sequence_index": 0, "erratum_id": "ERR-1", "description": "d",
        "affected_feature": affected_feature, "affected_feature_source": vec.FEATURE_SOURCE_PHRASE_MATCH,
        "citation": {"document": "doc", "fulltext_path": "p", "line": 1},
    }


def test_correlate_entry_unresolvable_when_no_affected_feature():
    entry = _entry(None)
    entry["affected_feature_source"] = vec.FEATURE_SOURCE_NOT_ANNOTATED
    result = vec.correlate_entry(entry, [
        {"id": "p1", "kind": "pattern", "exercises_features": ["anything"], "evidence": "e"},
    ])
    assert result["status"] == vec.STATUS_UNRESOLVABLE_NO_AFFECTED_FEATURE
    assert result["matches"] == []


def test_correlate_entry_not_available_when_no_usage_facts_supplied():
    result = vec.correlate_entry(_entry("LPM exit-latency logic"), [])
    assert result["status"] == vec.STATUS_NOT_AVAILABLE
    assert result["matches"] == []


def test_correlate_entry_not_correlated_when_facts_supplied_but_none_match():
    result = vec.correlate_entry(_entry("LPM exit-latency logic"), [
        {"id": "p1", "kind": "pattern", "exercises_features": ["bulk transfer stress"], "evidence": "e"},
    ])
    assert result["status"] == vec.STATUS_NOT_CORRELATED
    assert result["matches"] == []


def test_correlate_entry_correlated_on_exact_match():
    result = vec.correlate_entry(_entry("LPM exit-latency logic"), [
        {"id": "p1", "kind": "pattern", "exercises_features": ["LPM exit-latency logic"], "evidence": "cmd.txt:1"},
    ])
    assert result["status"] == vec.STATUS_CORRELATED
    assert result["matches"][0]["usage_fact_id"] == "p1"
    assert result["matches"][0]["match_kind"] == "EXACT"
    assert result["matches"][0]["evidence"] == "cmd.txt:1"


def test_correlate_entry_correlated_on_substring_match():
    result = vec.correlate_entry(_entry("LPM"), [
        {"id": "p1", "kind": "config", "exercises_features": ["LPM low power mode"], "evidence": "cfg.json"},
    ])
    assert result["status"] == vec.STATUS_CORRELATED
    assert result["matches"][0]["match_kind"] == "SUBSTRING"


def test_correlate_entry_never_matches_on_an_unrelated_feature():
    result = vec.correlate_entry(_entry("DMA burst-mode transfers"), [
        {"id": "p1", "kind": "pattern", "exercises_features": ["interrupt storm scenario"], "evidence": "e"},
    ])
    assert result["status"] == vec.STATUS_NOT_CORRELATED


# ===========================================================================
# full report composition against the real fixture
# ===========================================================================

def test_full_report_correlates_matching_usage_facts(distilled_errata_doc):
    report = vec.build_erratum_correlation(
        reference_record=distilled_errata_doc,
        usage_facts=[
            {"id": "pattern_lpm_stress", "kind": "pattern",
             "exercises_features": ["LPM exit-latency logic"], "evidence": "command.txt:210"},
        ],
    )
    err_101 = next(e for e in report["entries"] if e["erratum_id"] == "ERR-101")
    assert err_101["correlation"]["status"] == vec.STATUS_CORRELATED
    err_102 = next(e for e in report["entries"] if e["erratum_id"] == "ERR-102")
    assert err_102["correlation"]["status"] == vec.STATUS_NOT_CORRELATED
    assert report["summary"][vec.STATUS_CORRELATED] == 1
    assert report["summary"][vec.STATUS_NOT_CORRELATED] >= 1
    assert report["summary"][vec.STATUS_UNRESOLVABLE_NO_AFFECTED_FEATURE] == 1


def test_full_report_all_not_available_when_no_usage_facts_supplied(distilled_errata_doc):
    report = vec.build_erratum_correlation(reference_record=distilled_errata_doc)
    resolvable = [e for e in report["entries"] if e["affected_feature"]]
    assert resolvable, "fixture must contain at least one entry with a resolvable feature"
    for e in resolvable:
        assert e["correlation"]["status"] == vec.STATUS_NOT_AVAILABLE


# ===========================================================================
# CLI front door
# ===========================================================================

def test_cli_exit_code_2_on_not_available(tmp_path, capsys):
    rc = vec.execute_verb(["--reference-record", str(tmp_path / "nope.reference.json")])
    assert rc == 2


def test_cli_exit_code_0_when_all_resolvable_correlated(distilled_errata_doc, tmp_path, capsys):
    facts_path = tmp_path / "usage_facts.json"
    facts_path.write_text(json.dumps([
        {"id": "p1", "kind": "pattern", "exercises_features": ["LPM exit-latency logic"], "evidence": "e1"},
        {"id": "p2", "kind": "pattern", "exercises_features": ["DMA burst-mode transfers"], "evidence": "e2"},
        {"id": "p3", "kind": "pattern", "exercises_features": ["non-standard packet sizes"], "evidence": "e3"},
        {"id": "p4", "kind": "config", "exercises_features": ["USB3 LPM"], "evidence": "e4"},
    ]), encoding="utf-8")
    rc = vec.execute_verb([
        "--reference-record", distilled_errata_doc["distilled_reference"]["path"].replace(
            ".reference.md", ".reference.json"),
        "--usage-facts", str(facts_path),
    ])
    assert rc == 0


def test_cli_exit_code_1_when_something_not_correlated(distilled_errata_doc, tmp_path):
    facts_path = tmp_path / "usage_facts.json"
    facts_path.write_text(json.dumps([
        {"id": "p1", "kind": "pattern", "exercises_features": ["unrelated feature"], "evidence": "e1"},
    ]), encoding="utf-8")
    ref_json = distilled_errata_doc["distilled_reference"]["path"].replace(".reference.md", ".reference.json")
    rc = vec.execute_verb(["--reference-record", ref_json, "--usage-facts", str(facts_path)])
    assert rc == 1


def test_cli_malformed_usage_fact_exits_2(distilled_errata_doc, tmp_path):
    facts_path = tmp_path / "usage_facts.json"
    facts_path.write_text(json.dumps([{"id": "p1"}]), encoding="utf-8")
    ref_json = distilled_errata_doc["distilled_reference"]["path"].replace(".reference.md", ".reference.json")
    rc = vec.execute_verb(["--reference-record", ref_json, "--usage-facts", str(facts_path)])
    assert rc == 2


def test_cli_json_output_is_valid_json(distilled_errata_doc, capsys):
    ref_json = distilled_errata_doc["distilled_reference"]["path"].replace(".reference.md", ".reference.json")
    rc = vec.execute_verb(["--reference-record", ref_json, "--json"])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["status"] == "SCANNED"


def test_real_subprocess_invocation(distilled_errata_doc):
    ref_json = distilled_errata_doc["distilled_reference"]["path"].replace(".reference.md", ".reference.json")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_erratum_correlation", "--reference-record", ref_json, "--json"],
        cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["status"] == "SCANNED"
    assert len(parsed["entries"]) >= 4
