"""Tests for dv_harness/architecture_choice_ranking.py.

Real integration wherever the module claims reuse: `phy_boundary.classify_boundary()` /
`decide_bind_location()` are called for real to produce a `bind_decision`, and
`verification_boundary_ir.build_verification_boundary_ir()` is called for real (through this
module's own `_count_clock_domain_crossings()`) to prove `CLASS_CLOCK_RESET` boundaries are
really being classified, not stubbed. The house-required negative control (module refuses to
fabricate an answer when evidence is absent) is `test_no_boundary_declarations_is_honestly_not_declared_never_zero_assessed`.
"""
import json

import pytest

from dv_harness import phy_boundary
from dv_harness.architecture_choice_ranking import (
    CROSSING_ASSESSED,
    CROSSING_NOT_DECLARED,
    CROSSING_PARTIAL,
    EXCLUDE_BINDABLE_FIELD_MISSING,
    EXCLUDE_NOT_BINDABLE,
    EXCLUDE_NO_BIND_DECISION,
    STATUS_MULTIPLE_RANKED,
    STATUS_NO_VALID_BIND_LOCATION,
    STATUS_SINGLE_VALID_BIND_LOCATION,
    ArchitectureChoiceRankingError,
    execute_verb,
    rank_bind_location_candidates,
    render_ranking_markdown,
)


# ---------------------------------------------------------------------------
# Helpers -- real phy_boundary evidence, never hand-faked bind_decision shapes
# ---------------------------------------------------------------------------

def _real_parallel_bind_decision():
    """A real, bindable PARALLEL boundary decision, built through the real
    phy_boundary.classify_boundary()/decide_bind_location() pipeline."""
    boundary_signals = [
        {"name": "pipe_txdata", "width": 8, "phy_direction": "output", "controller_direction": "input"},
        {"name": "pipe_txvalid", "width": 1, "phy_direction": "output", "controller_direction": "input"},
    ]
    classification = phy_boundary.classify_boundary(boundary_signals)
    assert classification["kind"] == "PARALLEL"
    decision = phy_boundary.decide_bind_location(classification, boundary_signals)
    assert decision["bindable"] is True
    return decision, classification


def _real_mixed_boundary_classification():
    """A real MIXED boundary classification (serial + parallel signals both present) --
    verification_architecture.classify_wrapper_bridge_hop() reads this and reports BRIDGE."""
    boundary_signals = [
        {"name": "txp", "width": 1, "phy_direction": "output", "controller_direction": "input"},
        {"name": "txn", "width": 1, "phy_direction": "output", "controller_direction": "input"},
        {"name": "pipe_txdata", "width": 8, "phy_direction": "output", "controller_direction": "input"},
    ]
    classification = phy_boundary.classify_boundary(boundary_signals)
    assert classification["kind"] == "MIXED"
    return classification


def _candidate(candidate_id, bindable=True, bridge=False, crossings=None, target=None):
    """A minimal, self-consistent candidate dict for tests that don't need the real
    phy_boundary/verification_boundary_ir plumbing exercised directly."""
    bind_decision = {"bindable": bindable, "mount_layer": "controller_phy_parallel_boundary",
                      "rationale": "test fixture"}
    chain_hops = []
    if bridge:
        chain_hops = [{
            "instance": f"{candidate_id}.bridge0", "module": "bridge_mod",
            "boundary_classification": {"kind": "MIXED"},
        }]
    boundary_declarations = None
    if crossings is not None:
        boundary_declarations = [
            {
                "boundary_id": f"{candidate_id}:cdc{i}",
                "boundary_class": "CLOCK_RESET",
                "class_evidence": f"test citation {i}",
            }
            for i in range(crossings)
        ]
    return {
        "candidate_id": candidate_id,
        "target_instance": target or f"top.{candidate_id}",
        "bind_decision": bind_decision,
        "chain_hops": chain_hops,
        "boundary_declarations": boundary_declarations,
    }


# ---------------------------------------------------------------------------
# Ranking order
# ---------------------------------------------------------------------------

def test_fewer_bridge_hops_ranks_first():
    candidates = [_candidate("direct", bridge=False), _candidate("via_bridge", bridge=True)]
    report = rank_bind_location_candidates(candidates)
    assert report.status == STATUS_MULTIPLE_RANKED
    assert [r.candidate_id for r in report.ranked] == ["direct", "via_bridge"]
    assert report.ranked[0].bridge_hop_count == 0
    assert report.ranked[0].rank == 1
    assert report.ranked[1].bridge_hop_count == 1
    assert report.ranked[1].rank == 2


def test_tied_bridge_hops_broken_by_clock_domain_crossings():
    candidates = [
        _candidate("more_cdc", bridge=False, crossings=2),
        _candidate("fewer_cdc", bridge=False, crossings=0),
    ]
    report = rank_bind_location_candidates(candidates)
    assert [r.candidate_id for r in report.ranked] == ["fewer_cdc", "more_cdc"]
    assert report.ranked[0].clock_domain_crossings == 0
    assert report.ranked[0].clock_domain_crossing_status == CROSSING_ASSESSED
    assert report.ranked[1].clock_domain_crossings == 2


def test_tied_bridge_and_crossings_broken_by_total_hop_count():
    a = _candidate("shorter", bridge=False)
    a["chain_hops"] = [{"instance": "top.wrap0", "module": "wrap", "boundary_classification": {"kind": "PARALLEL"}}]
    b = _candidate("longer", bridge=False)
    b["chain_hops"] = [
        {"instance": "top.wrap0", "module": "wrap", "boundary_classification": {"kind": "PARALLEL"}},
        {"instance": "top.wrap1", "module": "wrap2", "boundary_classification": {"kind": "PARALLEL"}},
    ]
    report = rank_bind_location_candidates([b, a])
    assert [r.candidate_id for r in report.ranked] == ["shorter", "longer"]
    assert report.ranked[0].bridge_hop_count == 0 == report.ranked[1].bridge_hop_count
    assert report.ranked[0].total_hop_count == 1
    assert report.ranked[1].total_hop_count == 2


def test_full_tie_broken_alphabetically_by_candidate_id():
    candidates = [_candidate("zeta"), _candidate("alpha")]
    report = rank_bind_location_candidates(candidates)
    assert [r.candidate_id for r in report.ranked] == ["alpha", "zeta"]


def test_unknown_crossing_status_ranks_after_a_known_zero_crossing_candidate():
    known = _candidate("known_zero", crossings=0)
    unknown = _candidate("unknown_crossings")  # boundary_declarations omitted -> NOT_DECLARED
    report = rank_bind_location_candidates([unknown, known])
    assert [r.candidate_id for r in report.ranked] == ["known_zero", "unknown_crossings"]
    assert report.ranked[1].clock_domain_crossing_status == CROSSING_NOT_DECLARED
    assert report.ranked[1].clock_domain_crossings is None


# ---------------------------------------------------------------------------
# Real phy_boundary / verification_boundary_ir integration
# ---------------------------------------------------------------------------

def test_real_phy_boundary_bind_decision_is_consumed_not_rederived():
    decision, _classification = _real_parallel_bind_decision()
    candidate = {
        "candidate_id": "real_parallel",
        "target_instance": "top.phy0.parallel_iface",
        "bind_decision": decision,
        "chain_hops": [],
    }
    report = rank_bind_location_candidates([candidate])
    assert report.status == STATUS_SINGLE_VALID_BIND_LOCATION
    assert report.ranked[0].bind_decision is decision
    assert report.ranked[0].bind_decision["mount_layer"] == "controller_phy_parallel_boundary"


def test_real_mixed_boundary_classification_counts_as_a_bridge_hop():
    mixed_classification = _real_mixed_boundary_classification()
    decision, _ = _real_parallel_bind_decision()
    candidate = {
        "candidate_id": "crosses_real_bridge",
        "bind_decision": decision,
        "chain_hops": [{
            "instance": "top.bridge0", "module": "phy_bridge",
            "boundary_classification": mixed_classification,
        }],
    }
    report = rank_bind_location_candidates([candidate])
    ranked = report.ranked[0]
    assert ranked.bridge_hop_count == 1
    assert ranked.chain[0]["role"] == "BRIDGE"
    assert "MIXED" in ranked.chain[0]["rationale"]


def test_real_clock_reset_boundary_declaration_is_counted_as_a_crossing():
    decision, _ = _real_parallel_bind_decision()
    candidate = {
        "candidate_id": "real_cdc",
        "bind_decision": decision,
        "boundary_declarations": [{
            "boundary_id": "cdc0",
            "boundary_class": "CLOCK_RESET",
            "class_evidence": "spec section 4.2: async FIFO crossing core_clk -> phy_clk",
        }],
    }
    report = rank_bind_location_candidates([candidate])
    ranked = report.ranked[0]
    assert ranked.clock_domain_crossings == 1
    assert ranked.clock_domain_crossing_status == CROSSING_ASSESSED


def test_real_external_protocol_boundary_declaration_is_not_counted_as_a_crossing():
    decision, _ = _real_parallel_bind_decision()
    candidate = {
        "candidate_id": "real_non_cdc",
        "bind_decision": decision,
        "boundary_declarations": [{
            "boundary_id": "usb_iface",
            "boundary_class": "EXTERNAL_PROTOCOL",
            "class_evidence": "USB3 spec section 6.1",
        }],
    }
    report = rank_bind_location_candidates([candidate])
    assert report.ranked[0].clock_domain_crossings == 0
    assert report.ranked[0].clock_domain_crossing_status == CROSSING_ASSESSED


# ---------------------------------------------------------------------------
# Honesty / exclusion behaviour
# ---------------------------------------------------------------------------

def test_no_boundary_declarations_is_honestly_not_declared_never_zero_assessed():
    """Negative control: absence of cited clock-domain-crossing evidence must never be silently
    read as "zero crossings confirmed" -- it is NOT_DECLARED, a distinct status, and
    `clock_domain_crossings` stays None rather than a fabricated 0."""
    candidate = _candidate("no_cdc_evidence")  # crossings=None -> boundary_declarations omitted
    report = rank_bind_location_candidates([candidate])
    ranked = report.ranked[0]
    assert ranked.clock_domain_crossing_status == CROSSING_NOT_DECLARED
    assert ranked.clock_domain_crossings is None


def test_explicit_empty_boundary_declarations_is_assessed_zero_distinct_from_not_declared():
    """An explicit, caller-supplied empty list is a STRONGER fact than omitting the key
    entirely -- "these are the hops I checked and none are cited CLOCK_RESET boundaries" -- and
    must classify ASSESSED with count 0, never collapsed onto the same NOT_DECLARED status an
    omitted key gets."""
    decision, _ = _real_parallel_bind_decision()
    candidate = {"candidate_id": "explicitly_checked_none", "bind_decision": decision,
                 "boundary_declarations": []}
    report = rank_bind_location_candidates([candidate])
    ranked = report.ranked[0]
    assert ranked.clock_domain_crossing_status == CROSSING_ASSESSED
    assert ranked.clock_domain_crossings == 0


def test_malformed_boundary_declaration_is_partial_not_silently_dropped_or_fully_counted():
    decision, _ = _real_parallel_bind_decision()
    candidate = {
        "candidate_id": "mixed_evidence_quality",
        "bind_decision": decision,
        "boundary_declarations": [
            {"boundary_id": "good_cdc", "boundary_class": "CLOCK_RESET", "class_evidence": "cited"},
            {"boundary_id": "uncited_cdc", "boundary_class": "CLOCK_RESET"},  # no class_evidence
        ],
    }
    report = rank_bind_location_candidates([candidate])
    ranked = report.ranked[0]
    assert ranked.clock_domain_crossing_status == CROSSING_PARTIAL
    assert ranked.clock_domain_crossings == 1  # only the cited one counted
    assert len(ranked.boundary_declaration_errors) == 1
    assert "uncited_cdc" in ranked.boundary_declaration_errors[0]


def test_candidate_with_no_bind_decision_is_excluded_never_ranked():
    candidates = [
        {"candidate_id": "no_evidence", "target_instance": "top.x"},
        _candidate("has_evidence"),
    ]
    report = rank_bind_location_candidates(candidates)
    assert report.status == STATUS_SINGLE_VALID_BIND_LOCATION
    assert [r.candidate_id for r in report.ranked] == ["has_evidence"]
    assert len(report.excluded) == 1
    assert report.excluded[0].candidate_id == "no_evidence"
    assert report.excluded[0].reason == EXCLUDE_NO_BIND_DECISION


def test_candidate_with_bindable_false_is_excluded():
    candidates = [_candidate("not_bindable", bindable=False), _candidate("bindable_one")]
    report = rank_bind_location_candidates(candidates)
    assert report.status == STATUS_SINGLE_VALID_BIND_LOCATION
    assert [e.candidate_id for e in report.excluded] == ["not_bindable"]
    assert report.excluded[0].reason == EXCLUDE_NOT_BINDABLE


def test_candidate_with_missing_bindable_field_is_excluded_distinctly():
    candidates = [
        {"candidate_id": "no_bindable_field", "bind_decision": {"mount_layer": "x"}},
    ]
    report = rank_bind_location_candidates(candidates)
    assert report.status == STATUS_NO_VALID_BIND_LOCATION
    assert report.excluded[0].reason == EXCLUDE_BINDABLE_FIELD_MISSING


def test_zero_valid_candidates_reports_no_valid_bind_location():
    candidates = [_candidate("a", bindable=False), _candidate("b", bindable=False)]
    report = rank_bind_location_candidates(candidates)
    assert report.status == STATUS_NO_VALID_BIND_LOCATION
    assert report.ranked == []
    assert len(report.excluded) == 2
    assert report.best() is None


def test_single_valid_candidate_reports_single_status_with_rank_one():
    report = rank_bind_location_candidates([_candidate("only")])
    assert report.status == STATUS_SINGLE_VALID_BIND_LOCATION
    assert report.ranked[0].rank == 1
    assert report.best().candidate_id == "only"


# ---------------------------------------------------------------------------
# Malformed input -- shape defects raise, never silently skipped
# ---------------------------------------------------------------------------

def test_missing_candidate_id_raises():
    with pytest.raises(ArchitectureChoiceRankingError, match="candidate_id"):
        rank_bind_location_candidates([{"bind_decision": {"bindable": True}}])


def test_blank_candidate_id_raises():
    with pytest.raises(ArchitectureChoiceRankingError):
        rank_bind_location_candidates([{"candidate_id": "   ", "bind_decision": {"bindable": True}}])


def test_duplicate_candidate_id_raises():
    with pytest.raises(ArchitectureChoiceRankingError, match="duplicate"):
        rank_bind_location_candidates([_candidate("dup"), _candidate("dup")])


def test_candidates_not_a_list_raises():
    with pytest.raises(ArchitectureChoiceRankingError):
        rank_bind_location_candidates({"candidate_id": "x"})


def test_candidate_not_a_dict_raises():
    with pytest.raises(ArchitectureChoiceRankingError):
        rank_bind_location_candidates(["not a dict"])


def test_bind_decision_wrong_type_raises():
    with pytest.raises(ArchitectureChoiceRankingError, match="bind_decision"):
        rank_bind_location_candidates([{"candidate_id": "x", "bind_decision": "not a dict"}])


def test_chain_hops_wrong_type_raises():
    with pytest.raises(ArchitectureChoiceRankingError, match="chain_hops"):
        rank_bind_location_candidates([{
            "candidate_id": "x", "bind_decision": {"bindable": True}, "chain_hops": "nope",
        }])


def test_boundary_declarations_wrong_type_raises():
    with pytest.raises(ArchitectureChoiceRankingError, match="boundary_declarations"):
        rank_bind_location_candidates([{
            "candidate_id": "x", "bind_decision": {"bindable": True}, "boundary_declarations": "nope",
        }])


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_markdown_lists_ranked_and_excluded():
    candidates = [_candidate("direct", bridge=False), _candidate("blocked", bindable=False)]
    report = rank_bind_location_candidates(candidates)
    text = render_ranking_markdown(report)
    assert "direct" in text
    assert "Excluded candidates" in text
    assert "blocked" in text
    assert EXCLUDE_NOT_BINDABLE in text


def test_render_markdown_empty_note_when_nothing_ranked():
    report = rank_bind_location_candidates([_candidate("only_blocked", bindable=False)])
    text = render_ranking_markdown(report)
    assert "no valid bind location candidates" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_json_output_multiple_ranked(tmp_path):
    candidates = [_candidate("direct", bridge=False), _candidate("via_bridge", bridge=True)]
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(candidates), encoding="utf-8")

    exit_code, result, text = execute_verb(["--candidates", str(path), "--json"])
    assert exit_code == 0
    assert result["status"] == STATUS_MULTIPLE_RANKED
    parsed = json.loads(text)
    assert parsed["ranked"][0]["candidate_id"] == "direct"


def test_cli_text_output_single_valid(tmp_path):
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps([_candidate("only")]), encoding="utf-8")

    exit_code, result, text = execute_verb(["--candidates", str(path)])
    assert exit_code == 1
    assert result["status"] == STATUS_SINGLE_VALID_BIND_LOCATION
    assert "only" in text


def test_cli_malformed_input_exits_2(tmp_path):
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps([{"bind_decision": {"bindable": True}}]), encoding="utf-8")

    exit_code, result, _text = execute_verb(["--candidates", str(path)])
    assert exit_code == 2
    assert "error" in result
