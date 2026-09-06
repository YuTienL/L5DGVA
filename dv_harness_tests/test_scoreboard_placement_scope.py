"""Tests for dv_harness/scoreboard_placement_scope.py.

Real, no-mock unit tests over the module's own public functions -- there is
no external system to fake here (no filesystem/network/subprocess
dependency in the core classifier), so every test drives the real
`classify_scoreboard_scope()` / `extract_scope_signal()` /
`detect_vip_adjacent_compare_engine()` functions directly, plus the real
`python -m dv_harness.scoreboard_placement_scope` CLI as an actual
subprocess for the front-door tests.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.scoreboard_placement_scope import (
    ScopeClassification,
    ScoreboardPlacementScopeError,
    SCOPE_BLOCK_LOCAL,
    SCOPE_CROSS_PORT,
    SCOPE_DMA_PATH,
    SCOPE_END_TO_END,
    SCOPE_FUNCTION_LOCAL,
    SCOPE_INTERRUPT_PATH,
    SCOPE_MEMORY_PATH,
    SCOPE_PORT_LOCAL,
    SCOPE_PRECEDENCE,
    SCOPE_VALUES,
    STATUS_CLASSIFIED,
    STATUS_DEFAULTED,
    STATUS_UNVERIFIABLE,
    ROLE_QUEUE_COMPARE_ENGINE_DEFAULT,
    classify_scoreboard_scope,
    detect_vip_adjacent_compare_engine,
    extract_scope_signal,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ===========================================================================
# Taxonomy shape
# ===========================================================================

def test_all_8_scope_values_present_and_unique():
    assert len(SCOPE_VALUES) == 8
    assert len(set(SCOPE_VALUES)) == 8
    assert set(SCOPE_VALUES) == {
        SCOPE_PORT_LOCAL, SCOPE_FUNCTION_LOCAL, SCOPE_BLOCK_LOCAL, SCOPE_CROSS_PORT,
        SCOPE_DMA_PATH, SCOPE_MEMORY_PATH, SCOPE_INTERRUPT_PATH, SCOPE_END_TO_END,
    }


def test_precedence_is_a_permutation_of_scope_values():
    assert set(SCOPE_PRECEDENCE) == set(SCOPE_VALUES)
    assert len(SCOPE_PRECEDENCE) == len(SCOPE_VALUES)


def test_role_default_is_not_a_scope_value():
    # The SyoSil default role must never collide with the real taxonomy --
    # it is a statement about ARCHITECTURAL ROLE, not an asserted placement.
    assert ROLE_QUEUE_COMPARE_ENGINE_DEFAULT not in SCOPE_VALUES


# ===========================================================================
# Core positive path: each scope classified from its own real fact
# ===========================================================================

@pytest.mark.parametrize(
    "description,expected_scope,expected_fact",
    [
        ({"port_count": 1}, SCOPE_PORT_LOCAL, "port_count"),
        ({"single_function_unit": True}, SCOPE_FUNCTION_LOCAL, "single_function_unit"),
        ({"block_local": True}, SCOPE_BLOCK_LOCAL, "block_local"),
        ({"port_count": 3}, SCOPE_CROSS_PORT, "port_count"),
        ({"spans_dma_engine": True}, SCOPE_DMA_PATH, "spans_dma_engine"),
        ({"spans_memory_controller": True}, SCOPE_MEMORY_PATH, "spans_memory_controller"),
        ({"spans_interrupt_chain": True}, SCOPE_INTERRUPT_PATH, "spans_interrupt_chain"),
        (
            {"spans_end_to_end_stimulus_to_system_effect": True},
            SCOPE_END_TO_END,
            "spans_end_to_end_stimulus_to_system_effect",
        ),
    ],
)
def test_each_scope_is_classified_from_its_own_real_fact(description, expected_scope, expected_fact):
    result = classify_scoreboard_scope(description)
    assert result.status == STATUS_CLASSIFIED
    assert result.scope == expected_scope
    assert result.matched_fact == expected_fact
    assert result.source == "compare_description"
    assert result.default_rule_applied is False


def test_declared_scope_field_is_the_highest_precedence_signal():
    # A direct declared_scope tag wins even over a fact that would otherwise
    # resolve to a different, lower-precedence scope.
    result = classify_scoreboard_scope({"declared_scope": SCOPE_MEMORY_PATH, "port_count": 1})
    assert result.status == STATUS_CLASSIFIED
    assert result.scope == SCOPE_MEMORY_PATH
    assert result.matched_fact == "declared_scope"


def test_precedence_prefers_more_specific_scope_over_cross_port():
    # A compare that spans a DMA engine AND crosses multiple ports is named
    # DMA_PATH, the more architecturally informative fact, not CROSS_PORT.
    result = classify_scoreboard_scope({"spans_dma_engine": True, "port_count": 4})
    assert result.scope == SCOPE_DMA_PATH
    assert result.matched_fact == "spans_dma_engine"


def test_end_to_end_outranks_every_other_fact():
    result = classify_scoreboard_scope({
        "spans_end_to_end_stimulus_to_system_effect": True,
        "spans_interrupt_chain": True,
        "spans_dma_engine": True,
        "port_count": 5,
    })
    assert result.scope == SCOPE_END_TO_END


# ===========================================================================
# Negative controls -- ambiguous/unverifiable input must read as
# UNVERIFIABLE/UNKNOWN, never a confident guess
# ===========================================================================

def test_negative_control_empty_description_is_unverifiable():
    result = classify_scoreboard_scope({})
    assert result.status == STATUS_UNVERIFIABLE
    assert result.scope is None
    assert result.default_rule_applied is False
    assert "no scope-placement fact" in result.reason


def test_negative_control_none_description_is_unverifiable():
    result = classify_scoreboard_scope(None)
    assert result.status == STATUS_UNVERIFIABLE
    assert result.scope is None


def test_negative_control_all_facts_explicitly_false_is_still_unverifiable():
    # Explicit False is a real, distinguishable fact (not "absent"), but it
    # carries no POSITIVE placement signal either -- still UNVERIFIABLE.
    description = {
        "spans_end_to_end_stimulus_to_system_effect": False,
        "spans_interrupt_chain": False,
        "spans_dma_engine": False,
        "spans_memory_controller": False,
        "port_count": 0,
        "single_function_unit": False,
        "block_local": False,
    }
    result = classify_scoreboard_scope(description)
    assert result.status == STATUS_UNVERIFIABLE
    assert result.scope is None


def test_negative_control_non_syosil_component_with_no_facts_is_unverifiable_not_defaulted():
    # The default rule must NEVER fire for a component that is not declared
    # VIP-adjacent, even if it is otherwise unidentified.
    description = {"component_vendor": "AcmeCustomBFM", "component_kind": "hand_written_driver"}
    result = classify_scoreboard_scope(description)
    assert result.status == STATUS_UNVERIFIABLE
    assert result.is_vip_adjacent_compare_engine is False
    assert result.default_rule_applicable is False
    assert result.default_rule_applied is False


def test_negative_control_malformed_bool_fact_raises_rather_than_coerces():
    with pytest.raises(ScoreboardPlacementScopeError):
        classify_scoreboard_scope({"spans_dma_engine": "yes"})


def test_negative_control_malformed_port_count_raises():
    with pytest.raises(ScoreboardPlacementScopeError):
        classify_scoreboard_scope({"port_count": "two"})


def test_negative_control_negative_port_count_raises():
    with pytest.raises(ScoreboardPlacementScopeError):
        classify_scoreboard_scope({"port_count": -1})


def test_negative_control_unrecognised_declared_scope_raises():
    with pytest.raises(ScoreboardPlacementScopeError):
        classify_scoreboard_scope({"declared_scope": "NOT_A_REAL_SCOPE"})


def test_negative_control_bool_as_port_count_raises():
    # bool is a subclass of int in Python -- must not silently pass as a port count.
    with pytest.raises(ScoreboardPlacementScopeError):
        classify_scoreboard_scope({"port_count": True})


def test_negative_control_non_dict_description_raises():
    with pytest.raises(ScoreboardPlacementScopeError):
        classify_scoreboard_scope("not a dict")


def test_negative_control_non_dict_evidence_raises():
    with pytest.raises(ScoreboardPlacementScopeError):
        classify_scoreboard_scope({}, project_evidence="not a dict")


# ===========================================================================
# SyoSil/similar VIP-adjacent default rule
# ===========================================================================

@pytest.mark.parametrize(
    "vendor_field,value",
    [
        ("component_vendor", "SyoSil ApS"),
        ("component_kind", "SYOSCB"),
        ("component_name", "usb_syoscb_inst0"),
        ("component_vendor", "syosil"),
    ],
)
def test_syosil_marker_detected_case_insensitively(vendor_field, value):
    detected, reason = detect_vip_adjacent_compare_engine({vendor_field: value})
    assert detected is True
    assert value.lower().split()[0][:6] in reason.lower() or "marker" in reason.lower()


def test_similar_component_escape_hatch_flag():
    detected, reason = detect_vip_adjacent_compare_engine(
        {"vip_adjacent_compare_engine_declared": True, "component_vendor": "GenericVendorX"}
    )
    assert detected is True
    assert "explicitly declared" in reason


def test_non_syosil_vendor_is_not_detected():
    detected, reason = detect_vip_adjacent_compare_engine({"component_vendor": "AcmeCorp"})
    assert detected is False


def test_syosil_component_with_no_scope_facts_defaults_explicitly():
    description = {"component_vendor": "SyoSil ApS", "component_kind": "SYOSCB"}
    result = classify_scoreboard_scope(description)
    assert result.status == STATUS_DEFAULTED
    assert result.scope is None
    assert result.role == ROLE_QUEUE_COMPARE_ENGINE_DEFAULT
    assert result.is_vip_adjacent_compare_engine is True
    assert result.default_rule_applicable is True
    assert result.default_rule_applied is True
    assert result.default_rule_overridden_by_evidence is False
    assert "default rule fired" in result.reason


def test_syosil_component_with_own_scope_fact_is_classified_not_defaulted():
    # A real placement fact on the description itself always wins over the
    # default rule, even for a declared SyoSil component.
    description = {"component_vendor": "SyoSil", "port_count": 1}
    result = classify_scoreboard_scope(description)
    assert result.status == STATUS_CLASSIFIED
    assert result.scope == SCOPE_PORT_LOCAL
    assert result.role == ROLE_QUEUE_COMPARE_ENGINE_DEFAULT
    assert result.default_rule_applied is False
    assert result.is_vip_adjacent_compare_engine is True


def test_syosil_component_default_overridden_by_cited_project_evidence():
    description = {"component_vendor": "SyoSil ApS"}
    evidence = {
        "spans_dma_engine": True,
        "source": "design_doc.md:section 4.2 -- this SYOSCB instance binds the DMA descriptor/data compare path",
    }
    result = classify_scoreboard_scope(description, project_evidence=evidence)
    assert result.status == STATUS_CLASSIFIED
    assert result.scope == SCOPE_DMA_PATH
    assert result.source == "project_evidence"
    assert result.default_rule_applicable is True
    assert result.default_rule_applied is False
    assert result.default_rule_overridden_by_evidence is True
    assert "design_doc.md" in result.reason


def test_project_evidence_without_source_citation_is_refused():
    description = {"component_vendor": "SyoSil ApS"}
    evidence = {"spans_dma_engine": True}  # no 'source' key
    with pytest.raises(ScoreboardPlacementScopeError):
        classify_scoreboard_scope(description, project_evidence=evidence)


def test_project_evidence_with_blank_source_citation_is_refused():
    description = {"component_vendor": "SyoSil ApS"}
    evidence = {"spans_dma_engine": True, "source": "   "}
    with pytest.raises(ScoreboardPlacementScopeError):
        classify_scoreboard_scope(description, project_evidence=evidence)


def test_project_evidence_also_resolves_a_non_syosil_unverifiable_case():
    # Evidence is generically useful, not tied only to the SyoSil branch.
    description = {"component_vendor": "AcmeCorp"}
    evidence = {"declared_scope": SCOPE_BLOCK_LOCAL, "source": "review notes 2026-09-06"}
    result = classify_scoreboard_scope(description, project_evidence=evidence)
    assert result.status == STATUS_CLASSIFIED
    assert result.scope == SCOPE_BLOCK_LOCAL
    assert result.default_rule_overridden_by_evidence is False  # rule never applied here
    assert result.is_vip_adjacent_compare_engine is False


# ===========================================================================
# extract_scope_signal() directly
# ===========================================================================

def test_extract_scope_signal_returns_none_on_empty_or_none():
    assert extract_scope_signal(None) is None
    assert extract_scope_signal({}) is None


def test_extract_scope_signal_raises_on_non_dict():
    with pytest.raises(ScoreboardPlacementScopeError):
        extract_scope_signal(["not", "a", "dict"])


# ===========================================================================
# CLI front door -- real subprocess
# ===========================================================================

def _run_cli(args, cwd=REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.scoreboard_placement_scope"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_cli_scopes_verb_lists_all_8(tmp_path):
    proc = _run_cli(["scopes"])
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert set(payload["scope_values"]) == set(SCOPE_VALUES)


def test_cli_classify_verb_exit_0_on_classified(tmp_path):
    desc_path = tmp_path / "description.json"
    desc_path.write_text(json.dumps({"port_count": 1}), encoding="utf-8")
    proc = _run_cli(["classify", "--description", str(desc_path), "--json"])
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == STATUS_CLASSIFIED
    assert payload["scope"] == SCOPE_PORT_LOCAL


def test_cli_classify_verb_exit_1_on_defaulted(tmp_path):
    desc_path = tmp_path / "description.json"
    desc_path.write_text(json.dumps({"component_vendor": "SyoSil ApS"}), encoding="utf-8")
    proc = _run_cli(["classify", "--description", str(desc_path), "--json"])
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == STATUS_DEFAULTED
    assert payload["role"] == ROLE_QUEUE_COMPARE_ENGINE_DEFAULT


def test_cli_classify_verb_exit_2_on_unverifiable(tmp_path):
    desc_path = tmp_path / "description.json"
    desc_path.write_text(json.dumps({}), encoding="utf-8")
    proc = _run_cli(["classify", "--description", str(desc_path), "--json"])
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["status"] == STATUS_UNVERIFIABLE


def test_cli_classify_with_evidence_file(tmp_path):
    desc_path = tmp_path / "description.json"
    ev_path = tmp_path / "evidence.json"
    desc_path.write_text(json.dumps({"component_vendor": "SyoSil"}), encoding="utf-8")
    ev_path.write_text(
        json.dumps({"spans_interrupt_chain": True, "source": "irq_map.md:12"}), encoding="utf-8"
    )
    proc = _run_cli(
        ["classify", "--description", str(desc_path), "--evidence", str(ev_path), "--json"]
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["scope"] == SCOPE_INTERRUPT_PATH
    assert payload["default_rule_overridden_by_evidence"] is True
