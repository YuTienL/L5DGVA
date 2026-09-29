"""Tests for dv_harness/feature_enablement_matrix.py -- the parameter/config-bit -> named-feature
enablement matrix, built ONLY from real, cited evidence text (never from a parameter's own name)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.feature_enablement_matrix import (
    ENABLEMENT_STATUSES,
    EvidenceExcerpt,
    FeatureEnablementError,
    build_feature_enablement_matrix,
    classify_feature_enablement,
    overall_status,
)


# ---------------------------------------------------------------------------
# Vocabulary hygiene
# ---------------------------------------------------------------------------

def test_status_vocabulary_disjoint_from_models_status():
    from dv_harness.models import Status
    verdict_tokens = {s.value for s in Status}
    assert not verdict_tokens.intersection(set(ENABLEMENT_STATUSES))


def test_vocabulary_guard_has_real_detection_power():
    import dv_harness.feature_enablement_matrix as mod
    original = mod.ENABLEMENT_STATUSES
    try:
        mod.ENABLEMENT_STATUSES = tuple(original) + ("PASS",)
        with pytest.raises(AssertionError):
            mod.assert_no_verification_verdict_vocabulary()
    finally:
        mod.ENABLEMENT_STATUSES = original


# ---------------------------------------------------------------------------
# EvidenceExcerpt construction: citation required, enforced at construction
# ---------------------------------------------------------------------------

def test_evidence_excerpt_refuses_missing_citation():
    with pytest.raises(FeatureEnablementError):
        EvidenceExcerpt(text="When set, this bit enables PCIe Gen3 mode.", citation="")


def test_evidence_excerpt_refuses_missing_text():
    with pytest.raises(FeatureEnablementError):
        EvidenceExcerpt(text="", citation="spec.pdf section 4.2")


def test_evidence_excerpt_accepts_real_text_and_citation():
    e = EvidenceExcerpt(text="Enable bit for PCIe Gen3 mode.", citation="rtl/top.v:120")
    assert e.text and e.citation


# ---------------------------------------------------------------------------
# The Evidence Truth Rule: NEVER from the parameter/bit name alone
# ---------------------------------------------------------------------------

def test_no_evidence_is_honestly_not_available_regardless_of_suggestive_name():
    result = classify_feature_enablement("usb3_enable", evidence=None)
    assert result.status == "NOT_AVAILABLE"
    assert result.feature is None
    assert "name alone" in result.reason


def test_empty_evidence_list_is_not_available():
    result = classify_feature_enablement("usb3_enable", evidence=[])
    assert result.status == "NOT_AVAILABLE"


def test_name_never_drives_classification_even_with_conflicting_name_and_evidence():
    """The headline negative control: a parameter literally named `usb3_enable`, whose supplied
    evidence describes a DIFFERENT feature (PCIe Gen3 mode), classifies PCIe Gen3 mode -- never
    the name-implied USB3."""
    result = classify_feature_enablement(
        "usb3_enable",
        evidence=[{"text": "When set, this bit enables PCIe Gen3 mode.",
                   "citation": "rtl/top_ctrl.v:88"}])
    assert result.status == "RESOLVED"
    assert result.feature == "PCIe Gen3 mode"
    assert "usb3" not in (result.feature or "").lower()


def test_unrecognized_evidence_text_is_not_available():
    result = classify_feature_enablement(
        "cfg_reg_3",
        evidence=[{"text": "This register is reserved for future use.",
                   "citation": "programming_guide.pdf p12"}])
    assert result.status == "NOT_AVAILABLE"
    assert "no recognized enablement phrase" in result.reason


# ---------------------------------------------------------------------------
# Each real enablement phrase pattern, positively
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_feature_substring", [
    ("Enable bit for jumbo frame support.", "jumbo frame"),
    ("This bit must be asserted to enable low-power link state L1.", "low-power link state l1"),
    ("When set to 1'b1, this register bit enables scrambling.", "scrambling"),
    ("Controls whether TCP checksum offload is enabled.", "tcp checksum offload"),
    ("Setting CFG[2] enables the debug trace feature.", "debug trace"),
])
def test_each_real_enablement_phrase_classifies_resolved(text, expected_feature_substring):
    result = classify_feature_enablement(
        "cfg_bit_x", evidence=[{"text": text, "citation": "rtl/ctrl.v:1"}])
    assert result.status == "RESOLVED", result.reason
    assert expected_feature_substring in (result.feature or "").lower()
    assert result.citations
    assert result.citations[0].citation == "rtl/ctrl.v:1"


# ---------------------------------------------------------------------------
# Multiple citations for the SAME feature merge; for DIFFERENT features conflict
# ---------------------------------------------------------------------------

def test_two_citations_for_the_same_feature_merge_into_one_resolved_entry():
    result = classify_feature_enablement(
        "pcie_gen3_en",
        evidence=[
            {"text": "Enable bit for PCIe Gen3 mode.", "citation": "rtl/pcie.v:40"},
            {"text": "When set, this bit enables PCIe Gen3 Mode.",
             "citation": "spec.pdf section 6.1"},
        ])
    assert result.status == "RESOLVED"
    assert len(result.citations) == 2
    cited_sources = {c.citation for c in result.citations}
    assert cited_sources == {"rtl/pcie.v:40", "spec.pdf section 6.1"}


def test_two_citations_for_different_features_are_ambiguous_never_arbitrated():
    result = classify_feature_enablement(
        "cfg_bit_y",
        evidence=[
            {"text": "Enable bit for jumbo frame support.", "citation": "rtl/eth.v:10"},
            {"text": "Enable bit for scrambling.", "citation": "spec.pdf section 3.4"},
        ])
    assert result.status == "AMBIGUOUS"
    assert result.feature is None
    features = {c.feature_name.lower() for c in result.citations}
    assert "jumbo frame support" in features
    assert "scrambling" in features
    assert "jumbo frame support" in result.reason.lower() or "scrambling" in result.reason.lower()


def test_malformed_evidence_item_shape_raises():
    with pytest.raises(FeatureEnablementError):
        classify_feature_enablement("p", evidence=[123])


# ---------------------------------------------------------------------------
# build_feature_enablement_matrix: the full matrix
# ---------------------------------------------------------------------------

def _clean_facts():
    return [
        {
            "parameter_name": "pcie_gen3_en",
            "config_bit": "CFG[3]",
            "evidence": [{"text": "Enable bit for PCIe Gen3 mode.", "citation": "rtl/pcie.v:40"}],
        },
        {
            "parameter_name": "reserved_bit_9",
            "config_bit": "CFG[9]",
            "evidence": [],
        },
        {
            "parameter_name": "cfg_bit_conflict",
            "config_bit": "CFG[4]",
            "evidence": [
                {"text": "Enable bit for jumbo frame support.", "citation": "rtl/eth.v:10"},
                {"text": "Enable bit for scrambling.", "citation": "spec.pdf section 3.4"},
            ],
        },
    ]


def test_build_matrix_positive_path():
    matrix = build_feature_enablement_matrix(_clean_facts())
    assert len(matrix.entries) == 3
    resolved = matrix.resolved_entries()
    ambiguous = matrix.ambiguous_entries()
    not_available = matrix.not_available_entries()
    assert len(resolved) == 1
    assert resolved[0].parameter_name == "pcie_gen3_en"
    assert resolved[0].result.feature == "PCIe Gen3 mode"
    assert len(ambiguous) == 1
    assert ambiguous[0].parameter_name == "cfg_bit_conflict"
    assert len(not_available) == 1
    assert not_available[0].parameter_name == "reserved_bit_9"


def test_build_matrix_refuses_duplicate_identity():
    facts = _clean_facts() + [_clean_facts()[0]]
    with pytest.raises(FeatureEnablementError):
        build_feature_enablement_matrix(facts)


def test_build_matrix_allows_same_parameter_name_with_different_config_bit():
    facts = [
        {"parameter_name": "shared_reg", "config_bit": "CFG[0]",
         "evidence": [{"text": "Enable bit for feature A.", "citation": "rtl/x.v:1"}]},
        {"parameter_name": "shared_reg", "config_bit": "CFG[1]",
         "evidence": [{"text": "Enable bit for feature B.", "citation": "rtl/x.v:2"}]},
    ]
    matrix = build_feature_enablement_matrix(facts)
    assert len(matrix.entries) == 2


def test_build_matrix_refuses_non_list_input():
    with pytest.raises(FeatureEnablementError):
        build_feature_enablement_matrix("not-a-list")


def test_build_matrix_refuses_non_mapping_fact():
    with pytest.raises(FeatureEnablementError):
        build_feature_enablement_matrix([123])


def test_build_matrix_refuses_missing_parameter_name():
    with pytest.raises(FeatureEnablementError):
        build_feature_enablement_matrix([{"evidence": []}])


def test_build_matrix_refuses_blank_parameter_name():
    with pytest.raises(FeatureEnablementError):
        build_feature_enablement_matrix([{"parameter_name": "   "}])


def test_build_matrix_refuses_non_string_config_bit():
    with pytest.raises(FeatureEnablementError):
        build_feature_enablement_matrix(
            [{"parameter_name": "p", "config_bit": 3, "evidence": []}])


def test_build_matrix_refuses_non_list_evidence():
    with pytest.raises(FeatureEnablementError):
        build_feature_enablement_matrix(
            [{"parameter_name": "p", "evidence": "not-a-list"}])


def test_build_matrix_propagates_uncited_evidence_refusal():
    with pytest.raises(FeatureEnablementError):
        build_feature_enablement_matrix([
            {"parameter_name": "p",
             "evidence": [{"text": "Enable bit for X.", "citation": ""}]},
        ])


def test_empty_matrix_reports_not_available_overall():
    matrix = build_feature_enablement_matrix([])
    assert matrix.entries == []
    assert overall_status(matrix) == "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# overall_status worst-wins composite
# ---------------------------------------------------------------------------

def test_overall_status_worst_wins_ambiguous_outranks_resolved_and_not_available():
    matrix = build_feature_enablement_matrix(_clean_facts())
    assert overall_status(matrix) == "AMBIGUOUS"


def test_overall_status_not_available_outranks_all_resolved():
    facts = [
        {"parameter_name": "p1", "evidence": [{"text": "Enable bit for X.", "citation": "a"}]},
        {"parameter_name": "p2", "evidence": []},
    ]
    matrix = build_feature_enablement_matrix(facts)
    assert overall_status(matrix) == "NOT_AVAILABLE"


def test_overall_status_resolved_only_when_every_entry_resolved():
    facts = [
        {"parameter_name": "p1", "evidence": [{"text": "Enable bit for X.", "citation": "a"}]},
        {"parameter_name": "p2", "evidence": [{"text": "Enable bit for Y.", "citation": "b"}]},
    ]
    matrix = build_feature_enablement_matrix(facts)
    assert overall_status(matrix) == "RESOLVED"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_markdown_produces_a_real_table():
    matrix = build_feature_enablement_matrix(_clean_facts())
    text = matrix.render_markdown()
    assert "Feature Enabled" in text
    assert "PCIe Gen3 mode" in text
    assert "pcie_gen3_en" in text


def test_render_markdown_empty_note_for_no_entries():
    matrix = build_feature_enablement_matrix([])
    text = matrix.render_markdown()
    assert "no rows" in text.lower() or "nothing to classify" in text.lower()


def test_to_dict_round_trip_shape():
    matrix = build_feature_enablement_matrix(_clean_facts())
    d = matrix.to_dict()
    assert "entries" in d
    assert len(d["entries"]) == 3
    assert d["entries"][0]["status"] in ENABLEMENT_STATUSES


# ---------------------------------------------------------------------------
# Real CLI subprocess invocations
# ---------------------------------------------------------------------------

def _run_cli(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.feature_enablement_matrix"] + args,
        cwd=str(cwd), capture_output=True, text=True)


def test_cli_resolved_exit_code_0(tmp_path):
    facts = [
        {"parameter_name": "pcie_gen3_en", "config_bit": "CFG[3]",
         "evidence": [{"text": "Enable bit for PCIe Gen3 mode.", "citation": "rtl/pcie.v:40"}]},
    ]
    pf = tmp_path / "parameters.json"
    pf.write_text(json.dumps(facts), encoding="utf-8")
    repo_root = Path(__file__).resolve().parent.parent
    result = _run_cli(["build", "--parameters", str(pf), "--json"], cwd=repo_root)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["entries"][0]["status"] == "RESOLVED"


def test_cli_ambiguous_exit_code_1(tmp_path):
    pf = tmp_path / "parameters.json"
    pf.write_text(json.dumps(_clean_facts()), encoding="utf-8")
    repo_root = Path(__file__).resolve().parent.parent
    result = _run_cli(["build", "--parameters", str(pf)], cwd=repo_root)
    assert result.returncode == 1, result.stderr
    assert "PCIe Gen3 mode" in result.stdout


def test_cli_not_available_exit_code_2(tmp_path):
    facts = [{"parameter_name": "reserved_bit_9", "evidence": []}]
    pf = tmp_path / "parameters.json"
    pf.write_text(json.dumps(facts), encoding="utf-8")
    repo_root = Path(__file__).resolve().parent.parent
    result = _run_cli(["build", "--parameters", str(pf)], cwd=repo_root)
    assert result.returncode == 2, result.stderr


def test_cli_malformed_input_exit_code_2(tmp_path):
    pf = tmp_path / "parameters.json"
    pf.write_text(json.dumps([{"evidence": []}]), encoding="utf-8")
    repo_root = Path(__file__).resolve().parent.parent
    result = _run_cli(["build", "--parameters", str(pf)], cwd=repo_root)
    assert result.returncode == 2, result.stderr
    assert "MALFORMED_INPUT" in result.stderr


def test_cli_accepts_wrapper_object_with_parameters_key(tmp_path):
    facts = {"parameters": [
        {"parameter_name": "pcie_gen3_en",
         "evidence": [{"text": "Enable bit for PCIe Gen3 mode.", "citation": "rtl/pcie.v:40"}]},
    ]}
    pf = tmp_path / "parameters.json"
    pf.write_text(json.dumps(facts), encoding="utf-8")
    repo_root = Path(__file__).resolve().parent.parent
    result = _run_cli(["build", "--parameters", str(pf)], cwd=repo_root)
    assert result.returncode == 0, result.stderr
