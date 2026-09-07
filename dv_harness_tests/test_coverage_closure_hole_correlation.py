"""Tests for dv_harness/coverage_closure_hole_correlation.py -- cross-hole correlation and
multi-hole action identification built on top of coverage_analysis.classify_coverage_hole_taxonomy()
and coverage_closure_action_utility.rank_coverage_closure_actions() (both unmodified)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.coverage_closure_action_utility import (
    CoverageClosureActionUtilityError,
    rank_coverage_closure_actions,
)
from dv_harness.coverage_closure_hole_correlation import (
    CORRELATION_SHARED_REGISTER,
    CORRELATION_SHARED_CROSS_AXIS,
    CORRELATION_SHARED_LINKED_PATTERN,
    CORRELATION_SHARED_MISSING_CONFIG,
    BUNDLE_NOT_DECLARED,
    BUNDLE_REFERENCES_ONLY_UNKNOWN_HOLES,
    BUNDLE_SINGLE_HOLE,
    BUNDLE_CORRELATED,
    BUNDLE_PARTIALLY_CORRELATED,
    BUNDLE_UNCORRELATED,
    CoverageClosureHoleCorrelationError,
    correlate_coverage_holes,
    build_multi_hole_action_intelligence,
    format_intelligence_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_requirements_csv(root: Path, rows) -> None:
    """Mirrors test_coverage_analysis.py's own helper of the same name -- the real
    requirements.csv shape change_impact.load_trace_registry()/patterns_for_coverage_id() read."""
    d = root / ".dv-harness"
    d.mkdir(parents=True, exist_ok=True)
    header = ["REQ_ID", "SOURCE", "SCOPE", "VPLAN_ID", "SCENARIO_ID", "COMMAND_ID",
              "PATTERN_ID", "CHECKER_ID", "COVERAGE_ID", "RESULT", "STATUS", "EVIDENCE"]
    lines = [",".join(header)]
    for r in rows:
        lines.append(",".join(str(r.get(h, "")) for h in header))
    (d / "requirements.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _clean_action(action_id, gain=10.0, priority=5.0, risk=3.0, cost=1.0, closes_holes=None):
    a = {
        "action_id": action_id,
        "expected_coverage_gain": gain,
        "requirement_priority": priority,
        "risk_coverage": risk,
        "cost": cost,
        "correctness_status": "CONFIRMED_CORRECT",
        "risk_status": "ACCEPTABLE_RISK",
    }
    if closes_holes is not None:
        a["closes_holes"] = closes_holes
    return a


# ---- correlate_coverage_holes: correlation-group detection -----------------------------------

def test_shared_register_group_detected(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "register_name": "USB3_LINK_CTRL", "register_fields": ["X"]},
        {"coverage_id": "cov_b", "register_name": "usb3_link_ctrl"},  # case/whitespace tolerant
        {"coverage_id": "cov_c", "register_name": "OTHER_REG"},
    ]
    report = correlate_coverage_holes(holes, tmp_path)
    reg_groups = [g for g in report.groups if g.kind == CORRELATION_SHARED_REGISTER]
    assert len(reg_groups) == 1
    assert reg_groups[0].coverage_ids == ["cov_a", "cov_b"]
    assert reg_groups[0].evidence["register_name"].strip().upper() == "USB3_LINK_CTRL"


def test_shared_cross_axis_group_detected(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "cross_axes": ["cp_speed", "cp_port"]},
        {"coverage_id": "cov_b", "cross_axes": ["cp_speed", "cp_mode"]},
        {"coverage_id": "cov_c", "cross_axes": ["cp_mode"]},
    ]
    report = correlate_coverage_holes(holes, tmp_path)
    kinds_keys = {(g.kind, g.key): set(g.coverage_ids) for g in report.groups}
    assert kinds_keys[(CORRELATION_SHARED_CROSS_AXIS, "cp_speed")] == {"cov_a", "cov_b"}
    assert kinds_keys[(CORRELATION_SHARED_CROSS_AXIS, "cp_mode")] == {"cov_b", "cov_c"}
    # cp_port only appears once -- never reported as a group of size 1
    assert (CORRELATION_SHARED_CROSS_AXIS, "cp_port") not in kinds_keys


def test_shared_linked_pattern_group_detected(tmp_path):
    _write_requirements_csv(tmp_path, [
        {"REQ_ID": "R1", "PATTERN_ID": "pat_link_train", "COVERAGE_ID": "cov_a"},
        {"REQ_ID": "R2", "PATTERN_ID": "pat_link_train", "COVERAGE_ID": "cov_b"},
        {"REQ_ID": "R3", "PATTERN_ID": "pat_unrelated", "COVERAGE_ID": "cov_c"},
    ])
    holes = [{"coverage_id": c} for c in ("cov_a", "cov_b", "cov_c")]
    report = correlate_coverage_holes(holes, tmp_path)
    pattern_groups = [g for g in report.groups if g.kind == CORRELATION_SHARED_LINKED_PATTERN]
    assert len(pattern_groups) == 1
    assert pattern_groups[0].key == "pat_link_train"
    assert pattern_groups[0].coverage_ids == ["cov_a", "cov_b"]


def test_shared_missing_config_group_detected(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "hit_in_configs": ["cfgA"], "legal_configs": ["cfgA", "cfgB"]},
        {"coverage_id": "cov_b", "hit_in_configs": ["cfgC"], "legal_configs": ["cfgB", "cfgC"]},
        {"coverage_id": "cov_c", "hit_in_configs": ["cfgB", "cfgC"], "legal_configs": ["cfgB", "cfgC"]},
    ]
    report = correlate_coverage_holes(holes, tmp_path)
    cfg_groups = [g for g in report.groups if g.kind == CORRELATION_SHARED_MISSING_CONFIG]
    assert len(cfg_groups) == 1
    assert cfg_groups[0].key == "cfgB"
    assert cfg_groups[0].coverage_ids == ["cov_a", "cov_b"]
    # cov_c is fully hit -- it never contributes a "missing" config at all


def test_two_taxonomy_categories_never_assumed_correlated(tmp_path):
    # Both holes are structurally unclassified (no shared declared evidence) even though a
    # human might guess they are "related" -- this module never infers from the taxonomy
    # label alone.
    holes = [
        {"coverage_id": "cov_a", "bin_kind": "transition"},
        {"coverage_id": "cov_b", "bin_kind": "transition"},
    ]
    report = correlate_coverage_holes(holes, tmp_path)
    assert report.groups == []


def test_correlate_holes_empty_list_is_not_an_error(tmp_path):
    report = correlate_coverage_holes([], tmp_path)
    assert report.groups == []
    assert report.taxonomy_by_id == {}


def test_correlate_holes_missing_coverage_id_raises(tmp_path):
    with pytest.raises(CoverageClosureHoleCorrelationError) as exc:
        correlate_coverage_holes([{"register_name": "R"}], tmp_path)
    assert exc.value.reason == "HOLE_MISSING_COVERAGE_ID"


def test_correlate_holes_duplicate_coverage_id_raises(tmp_path):
    holes = [{"coverage_id": "cov_a"}, {"coverage_id": "cov_a"}]
    with pytest.raises(CoverageClosureHoleCorrelationError) as exc:
        correlate_coverage_holes(holes, tmp_path)
    assert exc.value.reason == "DUPLICATE_COVERAGE_ID"


def test_correlate_holes_malformed_hole_raises(tmp_path):
    with pytest.raises(CoverageClosureHoleCorrelationError) as exc:
        correlate_coverage_holes(["not-a-dict"], tmp_path)
    assert exc.value.reason == "MALFORMED_HOLE"


# ---- build_multi_hole_action_intelligence -----------------------------------------------------

def test_correlated_multi_hole_bundle_reported(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "register_name": "REG1", "register_fields": ["F1"]},
        {"coverage_id": "cov_b", "register_name": "REG1", "register_fields": ["F2"]},
    ]
    candidates = [_clean_action("act_fix_reg1", closes_holes=["cov_a", "cov_b"])]
    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)

    assert len(report.action_hole_impacts) == 1
    impact = report.action_hole_impacts[0]
    assert impact.bundle_status == BUNDLE_CORRELATED
    assert impact.known_hole_ids == ["cov_a", "cov_b"]
    assert impact.unknown_hole_ids == []
    assert impact.correlated_pairs == 1 and impact.total_pairs == 1
    assert impact.status == "RANKED"
    assert impact.rank == 1

    # And it shows up in the high-value advisory view.
    assert len(report.high_value_multi_hole_actions) == 1
    assert report.high_value_multi_hole_actions[0].action_id == "act_fix_reg1"


def test_uncorrelated_multi_hole_bundle_never_fabricated_as_correlated(tmp_path):
    # Two holes sharing NO real evidence -- the headline negative control: this module must
    # refuse to report a correlation it cannot support from real declared facts.
    holes = [
        {"coverage_id": "cov_a", "register_name": "REG_A"},
        {"coverage_id": "cov_b", "register_name": "REG_B"},
    ]
    candidates = [_clean_action("act_bundle", closes_holes=["cov_a", "cov_b"])]
    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)

    impact = report.action_hole_impacts[0]
    assert impact.bundle_status == BUNDLE_UNCORRELATED
    assert impact.correlated_pairs == 0 and impact.total_pairs == 1
    # And it must NOT be promoted into the high-value view merely for closing two holes.
    assert report.high_value_multi_hole_actions == []


def test_partially_correlated_bundle(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "register_name": "REG1"},
        {"coverage_id": "cov_b", "register_name": "REG1"},
        {"coverage_id": "cov_c", "register_name": "REG_UNRELATED"},
    ]
    candidates = [_clean_action("act_three", closes_holes=["cov_a", "cov_b", "cov_c"])]
    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)

    impact = report.action_hole_impacts[0]
    assert impact.bundle_status == BUNDLE_PARTIALLY_CORRELATED
    assert impact.total_pairs == 3  # (a,b) (a,c) (b,c)
    assert impact.correlated_pairs == 1  # only (a,b)
    assert report.high_value_multi_hole_actions == []


def test_single_hole_action_bundle_status(tmp_path):
    holes = [{"coverage_id": "cov_a", "register_name": "REG1"}]
    candidates = [_clean_action("act_single", closes_holes=["cov_a"])]
    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)
    impact = report.action_hole_impacts[0]
    assert impact.bundle_status == BUNDLE_SINGLE_HOLE
    assert impact.total_pairs == 0


def test_not_declared_bundle_status_when_field_absent(tmp_path):
    holes = [{"coverage_id": "cov_a"}]
    candidates = [_clean_action("act_no_field")]  # no closes_holes key at all
    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)
    impact = report.action_hole_impacts[0]
    assert impact.bundle_status == BUNDLE_NOT_DECLARED
    assert impact.declared_closes_holes == []


def test_unknown_hole_reference_never_treated_as_correlated(tmp_path):
    holes = [{"coverage_id": "cov_a", "register_name": "REG1"}]
    candidates = [_clean_action("act_ghost", closes_holes=["cov_missing"])]
    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)
    impact = report.action_hole_impacts[0]
    assert impact.bundle_status == BUNDLE_REFERENCES_ONLY_UNKNOWN_HOLES
    assert impact.unknown_hole_ids == ["cov_missing"]
    assert impact.known_hole_ids == []


def test_mixed_known_and_unknown_hole_references(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "register_name": "REG1"},
        {"coverage_id": "cov_b", "register_name": "REG1"},
    ]
    candidates = [_clean_action("act_mixed", closes_holes=["cov_a", "cov_b", "cov_missing"])]
    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)
    impact = report.action_hole_impacts[0]
    assert impact.known_hole_ids == ["cov_a", "cov_b"]
    assert impact.unknown_hole_ids == ["cov_missing"]
    assert impact.bundle_status == BUNDLE_CORRELATED  # judged only over the known pair


def test_duplicate_declared_hole_ids_deduplicated(tmp_path):
    holes = [{"coverage_id": "cov_a", "register_name": "REG1"}]
    candidates = [_clean_action("act_dup", closes_holes=["cov_a", "cov_a"])]
    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)
    impact = report.action_hole_impacts[0]
    assert impact.declared_closes_holes == ["cov_a"]
    assert impact.bundle_status == BUNDLE_SINGLE_HOLE


def test_invalid_closes_holes_declaration_raises(tmp_path):
    holes = [{"coverage_id": "cov_a"}]
    candidates = [_clean_action("act_bad", closes_holes=[1, 2])]  # not a list of strings
    ranking = rank_coverage_closure_actions(candidates)
    with pytest.raises(CoverageClosureHoleCorrelationError) as exc:
        build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)
    assert exc.value.reason == "INVALID_CLOSES_HOLES_DECLARATION"


# ---- gate-respect: excluded/unrankable actions never promoted, however correlated ------------

def test_excluded_action_never_promoted_into_high_value_despite_correlation(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "register_name": "REG1"},
        {"coverage_id": "cov_b", "register_name": "REG1"},
    ]
    # Enormous utility factors, but FLAGGED_INCORRECT -- the utility module's own gate excludes
    # it from ranking entirely, regardless of cost/gain/priority/risk_coverage.
    candidates = [
        _clean_action("act_flagged", gain=1000.0, priority=1000.0, risk=1000.0, cost=0.001,
                       closes_holes=["cov_a", "cov_b"])
    ]
    candidates[0]["correctness_status"] = "FLAGGED_INCORRECT"
    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)

    impact = report.action_hole_impacts[0]
    assert impact.status == "EXCLUDED"
    assert impact.bundle_status == BUNDLE_CORRELATED  # correlation is still honestly reported
    assert report.high_value_multi_hole_actions == []  # but never promoted -- the gate wins


def test_unrankable_action_reported_but_never_promoted(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "register_name": "REG1"},
        {"coverage_id": "cov_b", "register_name": "REG1"},
    ]
    candidate = _clean_action("act_missing_factor", closes_holes=["cov_a", "cov_b"])
    del candidate["cost"]  # missing utility factor -> UNRANKABLE
    ranking = rank_coverage_closure_actions([candidate])
    report = build_multi_hole_action_intelligence([candidate], ranking, holes, tmp_path)

    impact = report.action_hole_impacts[0]
    assert impact.status == "UNRANKABLE"
    assert impact.bundle_status == BUNDLE_CORRELATED
    assert report.high_value_multi_hole_actions == []


def test_high_value_never_includes_a_ranked_but_uncorrelated_action(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "register_name": "REG_A"},
        {"coverage_id": "cov_b", "register_name": "REG_B"},
    ]
    candidates = [_clean_action("act_ranked_uncorrelated", closes_holes=["cov_a", "cov_b"])]
    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)
    assert report.action_hole_impacts[0].status == "RANKED"
    assert report.high_value_multi_hole_actions == []


def test_action_not_in_ranking_raises(tmp_path):
    holes = [{"coverage_id": "cov_a"}]
    candidates = [_clean_action("act_x")]
    ranking = rank_coverage_closure_actions(candidates)
    other_candidates = [_clean_action("act_y")]  # a DIFFERENT candidate list than `ranking` was built from
    with pytest.raises(CoverageClosureHoleCorrelationError) as exc:
        build_multi_hole_action_intelligence(other_candidates, ranking, holes, tmp_path)
    assert exc.value.reason == "ACTION_NOT_IN_RANKING"


def test_high_value_ranking_never_reorders_underlying_utility_ranking(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "register_name": "REG1"},
        {"coverage_id": "cov_b", "register_name": "REG1"},
        {"coverage_id": "cov_c", "register_name": "REG2"},
        {"coverage_id": "cov_d", "register_name": "REG2"},
    ]
    # act_lo has lower utility but closes 2 correlated holes; act_hi has higher utility but
    # closes only 1 hole. The underlying ranking must still order act_hi first.
    candidates = [
        _clean_action("act_lo", gain=2.0, priority=1.0, risk=1.0, cost=1.0,
                       closes_holes=["cov_a", "cov_b"]),
        _clean_action("act_hi", gain=20.0, priority=5.0, risk=5.0, cost=1.0,
                       closes_holes=["cov_c", "cov_d"]),
    ]
    ranking = rank_coverage_closure_actions(candidates)
    assert [r.action_id for r in ranking.ranked] == ["act_hi", "act_lo"]

    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)
    # Both are correlated multi-hole bundles -- both real ranks are preserved unchanged.
    ranks = {i.action_id: i.rank for i in report.action_hole_impacts}
    assert ranks == {"act_hi": 1, "act_lo": 2}


# ---- rendering / CLI ----------------------------------------------------------------------

def test_format_intelligence_report_smoke(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "register_name": "REG1"},
        {"coverage_id": "cov_b", "register_name": "REG1"},
    ]
    candidates = [_clean_action("act_fix", closes_holes=["cov_a", "cov_b"])]
    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(candidates, ranking, holes, tmp_path)
    text = format_intelligence_report(report)
    assert "act_fix" in text
    assert "SHARED_REGISTER" in text
    assert "HIGH-VALUE MULTI-HOLE ACTIONS" in text


def test_cli_json_end_to_end(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "register_name": "REG1"},
        {"coverage_id": "cov_b", "register_name": "REG1"},
    ]
    candidates = [_clean_action("act_fix", closes_holes=["cov_a", "cov_b"])]
    holes_file = tmp_path / "holes.json"
    candidates_file = tmp_path / "candidates.json"
    holes_file.write_text(json.dumps(holes), encoding="utf-8")
    candidates_file.write_text(json.dumps(candidates), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.coverage_closure_hole_correlation",
         "--root", str(tmp_path), "--holes-file", str(holes_file),
         "--candidates-file", str(candidates_file), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["high_value_multi_hole_actions"]) == 1
    assert payload["high_value_multi_hole_actions"][0]["action_id"] == "act_fix"


def test_cli_text_output_default(tmp_path):
    holes_file = tmp_path / "holes.json"
    candidates_file = tmp_path / "candidates.json"
    holes_file.write_text(json.dumps([{"coverage_id": "cov_a"}]), encoding="utf-8")
    candidates_file.write_text(json.dumps([_clean_action("act_only")]), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.coverage_closure_hole_correlation",
         "--root", str(tmp_path), "--holes-file", str(holes_file),
         "--candidates-file", str(candidates_file)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "Coverage-Closure Hole Correlation" in result.stdout
