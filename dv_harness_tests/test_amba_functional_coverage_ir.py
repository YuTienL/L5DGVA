"""Tests for dv_harness/amba_functional_coverage_ir.py."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.amba_functional_coverage_ir import (
    AMBAFunctionalCoverageIR,
    AMBAFunctionalCoverageIRError,
    CATEGORY_CONNECTIVITY,
    CATEGORY_MEMORY_MAP,
    CATEGORY_ORDERING,
    CATEGORY_ROUTING,
    COVERED_OBSERVED,
    CROSS_FULLY_EXPLAINED,
    CROSS_MEANINGFUL,
    CROSS_UNKNOWN,
    PARTIALLY_REACHABLE_CONDITIONAL,
    REACHABILITY_CONTRADICTED,
    REACHABILITY_UNKNOWN_INSUFFICIENT_EVIDENCE,
    REACHABILITY_VALUES,
    REACHABLE_NOT_YET_HIT,
    UNREACHABLE_NO_LEGAL_PATH,
    UNREACHABLE_STRUCTURALLY_EXCLUDED,
    axis_snapshot_from_bins,
    build_connectivity_coverpoints,
    build_memory_map_coverpoints,
    build_ordering_coverpoints,
    build_routing_coverpoints,
    classify_bin_reachability,
    classify_cross_coverage_meaningfulness,
    evaluate_cross,
    execute_verb,
)


# ---------------------------------------------------------------------------
# classify_bin_reachability -- the core 7-value classifier
# ---------------------------------------------------------------------------
class TestClassifyBinReachability:
    def test_observed_hit_wins_over_everything(self):
        status, reason = classify_bin_reachability({"observed_hit": True, "legal": False})
        assert status == COVERED_OBSERVED
        assert "hit" in reason

    def test_legal_true_no_hit_is_reachable_not_yet_hit(self):
        status, _ = classify_bin_reachability({"legal": True})
        assert status == REACHABLE_NOT_YET_HIT

    def test_legal_false_is_unreachable_no_legal_path(self):
        status, _ = classify_bin_reachability({"legal": False})
        assert status == UNREACHABLE_NO_LEGAL_PATH

    def test_legal_none_is_insufficient_evidence(self):
        status, _ = classify_bin_reachability({})
        assert status == REACHABILITY_UNKNOWN_INSUFFICIENT_EVIDENCE

    def test_structurally_excluded_is_its_own_status(self):
        status, _ = classify_bin_reachability({"structurally_excluded": True})
        assert status == UNREACHABLE_STRUCTURALLY_EXCLUDED

    def test_conditional_reachable_is_partially_reachable(self):
        status, _ = classify_bin_reachability({"legal": True, "conditional": True})
        assert status == PARTIALLY_REACHABLE_CONDITIONAL

    def test_explicit_contradiction_flag(self):
        status, _ = classify_bin_reachability({"legal": True, "contradicting_evidence": True})
        assert status == REACHABILITY_CONTRADICTED

    def test_derived_contradiction_from_excluded_and_legal(self):
        # structurally_excluded together with legal=True is a real disagreement even when the
        # caller never set contradicting_evidence explicitly.
        status, reason = classify_bin_reachability({"legal": True, "structurally_excluded": True})
        assert status == REACHABILITY_CONTRADICTED
        assert "disagree" in reason

    def test_all_seven_values_are_independently_reachable(self):
        # Every one of the 7 vocabulary values must be producible from some real input shape --
        # proving the classifier never collapses to a binary covered/uncovered outcome.
        facts = [
            {"observed_hit": True},
            {"legal": True},
            {"legal": False},
            {},
            {"structurally_excluded": True},
            {"legal": True, "conditional": True},
            {"legal": True, "contradicting_evidence": True},
        ]
        seen = {classify_bin_reachability(f)[0] for f in facts}
        assert seen == set(REACHABILITY_VALUES)

    def test_non_dict_fact_raises(self):
        with pytest.raises(AMBAFunctionalCoverageIRError):
            classify_bin_reachability("not-a-dict")


# ---------------------------------------------------------------------------
# Connectivity-driven coverpoints
# ---------------------------------------------------------------------------
class TestConnectivityCoverpoints:
    def test_builds_one_bin_per_edge(self):
        bins = build_connectivity_coverpoints([
            {"master": "M0", "slave": "S0", "legal": True, "observed_hit": True},
            {"master": "M0", "slave": "S1", "legal": True},
            {"master": "M1", "slave": "S0", "legal": False},
        ])
        assert len(bins) == 3
        by_pair = {(b["master"], b["slave"]): b for b in bins}
        assert by_pair[("M0", "S0")]["reachability"] == COVERED_OBSERVED
        assert by_pair[("M0", "S1")]["reachability"] == REACHABLE_NOT_YET_HIT
        assert by_pair[("M1", "S0")]["reachability"] == UNREACHABLE_NO_LEGAL_PATH
        assert all(b["category"] == CATEGORY_CONNECTIVITY for b in bins)

    def test_accepts_source_dest_aliases(self):
        bins = build_connectivity_coverpoints([{"source": "M0", "dest": "S0", "legal": True}])
        assert bins[0]["master"] == "M0" and bins[0]["slave"] == "S0"

    def test_missing_identity_raises(self):
        with pytest.raises(AMBAFunctionalCoverageIRError):
            build_connectivity_coverpoints([{"master": "M0"}])

    def test_duplicate_edge_raises(self):
        with pytest.raises(AMBAFunctionalCoverageIRError):
            build_connectivity_coverpoints([
                {"master": "M0", "slave": "S0", "legal": True},
                {"master": "M0", "slave": "S0", "legal": False},
            ])

    def test_non_list_input_raises(self):
        with pytest.raises(AMBAFunctionalCoverageIRError):
            build_connectivity_coverpoints("nope")

    def test_empty_input_is_legal(self):
        assert build_connectivity_coverpoints([]) == []
        assert build_connectivity_coverpoints(None) == []


# ---------------------------------------------------------------------------
# Memory-map-driven coverpoints
# ---------------------------------------------------------------------------
class TestMemoryMapCoverpoints:
    def test_builds_owner_and_accessor_bins(self):
        bins = build_memory_map_coverpoints([
            {"owner": "SRAM0", "accessor": "M0", "legal": True, "observed_hit": True},
            {"owner": "SRAM0", "accessor": "M1", "legal": True},
            {"owner": "RESERVED0", "structurally_excluded": True},
        ])
        assert len(bins) == 3
        reserved = next(b for b in bins if b["owner"] == "RESERVED0")
        assert reserved["reachability"] == UNREACHABLE_STRUCTURALLY_EXCLUDED
        assert all(b["category"] == CATEGORY_MEMORY_MAP for b in bins)

    def test_accessor_is_optional(self):
        bins = build_memory_map_coverpoints([{"owner": "SRAM0", "legal": True}])
        assert "accessor" not in bins[0]

    def test_missing_owner_raises(self):
        with pytest.raises(AMBAFunctionalCoverageIRError):
            build_memory_map_coverpoints([{"legal": True}])

    def test_duplicate_region_raises(self):
        with pytest.raises(AMBAFunctionalCoverageIRError):
            build_memory_map_coverpoints([
                {"owner": "SRAM0", "legal": True},
                {"owner": "SRAM0", "legal": False},
            ])


# ---------------------------------------------------------------------------
# Routing-driven coverpoints
# ---------------------------------------------------------------------------
class TestRoutingCoverpoints:
    def test_builds_route_bins_with_hops(self):
        bins = build_routing_coverpoints([
            {"source": "M0", "dest": "S0", "hops": ["bridge0", "bridge1"], "legal": True,
             "observed_hit": True},
            {"master": "M1", "slave": "S1", "legal": True},
        ])
        assert len(bins) == 2
        with_hops = next(b for b in bins if "hops" in b)
        assert with_hops["hops"] == "bridge0->bridge1"
        assert all(b["category"] == CATEGORY_ROUTING for b in bins)

    def test_missing_identity_raises(self):
        with pytest.raises(AMBAFunctionalCoverageIRError):
            build_routing_coverpoints([{"source": "M0"}])

    def test_duplicate_route_raises(self):
        with pytest.raises(AMBAFunctionalCoverageIRError):
            build_routing_coverpoints([
                {"source": "M0", "dest": "S0", "legal": True},
                {"source": "M0", "dest": "S0", "legal": False},
            ])


# ---------------------------------------------------------------------------
# Ordering-driven coverpoints
# ---------------------------------------------------------------------------
class TestOrderingCoverpoints:
    def test_builds_scenario_bins(self):
        bins = build_ordering_coverpoints([
            {"scenario": "OUTSTANDING_DEPTH_4", "master": "M0", "legal": True,
             "observed_hit": True},
            {"scenario": "OUT_OF_ORDER_COMPLETION", "legal": True, "conditional": True},
        ])
        assert len(bins) == 2
        depth = next(b for b in bins if b["scenario"] == "OUTSTANDING_DEPTH_4")
        assert depth["master"] == "M0"
        assert depth["reachability"] == COVERED_OBSERVED
        ooo = next(b for b in bins if b["scenario"] == "OUT_OF_ORDER_COMPLETION")
        assert ooo["reachability"] == PARTIALLY_REACHABLE_CONDITIONAL
        assert all(b["category"] == CATEGORY_ORDERING for b in bins)

    def test_missing_scenario_raises(self):
        with pytest.raises(AMBAFunctionalCoverageIRError):
            build_ordering_coverpoints([{"master": "M0"}])

    def test_duplicate_scenario_scoped_by_identity_raises(self):
        with pytest.raises(AMBAFunctionalCoverageIRError):
            build_ordering_coverpoints([
                {"scenario": "S", "master": "M0", "legal": True},
                {"scenario": "S", "master": "M0", "legal": False},
            ])

    def test_same_scenario_different_master_is_a_distinct_bin(self):
        bins = build_ordering_coverpoints([
            {"scenario": "S", "master": "M0", "legal": True},
            {"scenario": "S", "master": "M1", "legal": True},
        ])
        assert len(bins) == 2


# ---------------------------------------------------------------------------
# Meaningful crosses only
# ---------------------------------------------------------------------------
class TestMeaningfulCrossesOnly:
    def test_fully_explained_axes_skip_the_cross(self):
        snapshot = {
            "master": {"bins_total": 2, "bins_hit": 2},
            "protocol_mode": {"bins_total": 2, "bins_hit": 2},
        }
        result = classify_cross_coverage_meaningfulness(
            snapshot, [{"cross_name": "master_x_mode", "axes": ["master", "protocol_mode"]}])
        assert result[0]["verdict"] == CROSS_FULLY_EXPLAINED

    def test_incomplete_axis_is_meaningful(self):
        snapshot = {
            "master": {"bins_total": 2, "bins_hit": 1},
            "protocol_mode": {"bins_total": 2, "bins_hit": 2},
        }
        result = classify_cross_coverage_meaningfulness(
            snapshot, [{"cross_name": "master_x_mode", "axes": ["master", "protocol_mode"]}])
        assert result[0]["verdict"] == CROSS_MEANINGFUL

    def test_missing_axis_is_unknown_never_fully_explained(self):
        snapshot = {"master": {"bins_total": 2, "bins_hit": 2}}
        result = classify_cross_coverage_meaningfulness(
            snapshot, [{"cross_name": "x", "axes": ["master", "protocol_mode"]}])
        assert result[0]["verdict"] == CROSS_UNKNOWN

    def test_bad_cross_definition_raises(self):
        with pytest.raises(AMBAFunctionalCoverageIRError):
            classify_cross_coverage_meaningfulness({}, [{"cross_name": "x", "axes": ["only_one"]}])

    def test_evaluate_cross_skips_building_bins_when_fully_explained(self):
        result = evaluate_cross(
            "master", {"bins_total": 1, "bins_hit": 1},
            "mode", {"bins_total": 1, "bins_hit": 1},
            cross_facts=[{"axis_a_value": "M0", "axis_b_value": "AHB", "legal": True}])
        assert result["skipped"] is True
        assert result["verdict"] == CROSS_FULLY_EXPLAINED
        assert result["bins"] == []

    def test_evaluate_cross_builds_bins_when_meaningful(self):
        result = evaluate_cross(
            "master", {"bins_total": 2, "bins_hit": 0},
            "mode", {"bins_total": 1, "bins_hit": 1},
            cross_facts=[
                {"axis_a_value": "M0", "axis_b_value": "AHB", "legal": True, "observed_hit": True},
                {"axis_a_value": "M1", "axis_b_value": "AHB", "legal": False},
            ])
        assert result["skipped"] is False
        assert result["verdict"] == CROSS_MEANINGFUL
        assert len(result["bins"]) == 2
        by_master = {b["master"]: b for b in result["bins"]}
        assert by_master["M0"]["reachability"] == COVERED_OBSERVED
        assert by_master["M1"]["reachability"] == UNREACHABLE_NO_LEGAL_PATH

    def test_axis_snapshot_from_bins_counts_only_covered_observed(self):
        bins = [
            {"reachability": COVERED_OBSERVED},
            {"reachability": REACHABLE_NOT_YET_HIT},
            {"reachability": UNREACHABLE_NO_LEGAL_PATH},
        ]
        snap = axis_snapshot_from_bins(bins)
        assert snap == {"bins_total": 3, "bins_hit": 1}


# ---------------------------------------------------------------------------
# The assembled IR
# ---------------------------------------------------------------------------
class TestAMBAFunctionalCoverageIR:
    def _facts(self):
        return {
            "legal_edges": [
                {"master": "M0", "slave": "S0", "legal": True, "observed_hit": True},
                {"master": "M0", "slave": "S1", "legal": True},
                {"master": "M1", "slave": "S0", "legal": False},
            ],
            "address_regions": [
                {"owner": "SRAM0", "accessor": "M0", "legal": True, "observed_hit": True},
                {"owner": "RESERVED0", "structurally_excluded": True},
            ],
            "route_facts": [
                {"source": "M0", "dest": "S1", "hops": ["fabric0"], "legal": True},
            ],
            "ordering_facts": [
                {"scenario": "OUTSTANDING_DEPTH_2", "master": "M0", "legal": True},
            ],
        }

    def test_build_assembles_all_four_categories(self):
        ir = AMBAFunctionalCoverageIR.build(**self._facts())
        assert len(ir.connectivity_coverpoints) == 3
        assert len(ir.memory_map_coverpoints) == 2
        assert len(ir.routing_coverpoints) == 1
        assert len(ir.ordering_coverpoints) == 1
        assert len(ir.all_bins()) == 7

    def test_reachability_summary_never_binary(self):
        ir = AMBAFunctionalCoverageIR.build(**self._facts())
        summary = ir.reachability_summary()
        # at least 3 distinct reachability values appear across this fixture's real bins
        nonzero = {k for k, v in summary.items() if v > 0}
        assert len(nonzero) >= 3
        assert set(summary.keys()) == set(REACHABILITY_VALUES)

    def test_cross_request_by_category_skips_fully_explained(self):
        facts = self._facts()
        # Make every connectivity edge and every ordering scenario a real observed hit so the
        # cross between them is fully explained by its own single axes.
        facts["legal_edges"] = [
            {"master": "M0", "slave": "S0", "legal": True, "observed_hit": True},
        ]
        facts["ordering_facts"] = [
            {"scenario": "OUTSTANDING_DEPTH_2", "master": "M0", "legal": True,
             "observed_hit": True},
        ]
        facts["cross_requests"] = [{
            "axis_a_name": "connectivity", "axis_a_category": CATEGORY_CONNECTIVITY,
            "axis_b_name": "ordering", "axis_b_category": CATEGORY_ORDERING,
            "cross_facts": [{"axis_a_value": "M0->S0", "axis_b_value": "OUTSTANDING_DEPTH_2",
                              "legal": True}],
        }]
        ir = AMBAFunctionalCoverageIR.build(**facts)
        assert len(ir.crosses) == 1
        assert ir.crosses[0]["skipped"] is True
        assert ir.skipped_crosses() == ir.crosses
        # the skipped cross contributes no bins to all_bins()
        assert all(b["category"] != "CROSS:connectivity_x_ordering" for b in ir.all_bins())

    def test_cross_request_tracks_bins_when_meaningful(self):
        facts = self._facts()  # connectivity axis here is NOT fully covered (1 of 3 hit)
        facts["cross_requests"] = [{
            "axis_a_name": "connectivity", "axis_a_category": CATEGORY_CONNECTIVITY,
            "axis_b_name": "ordering", "axis_b_category": CATEGORY_ORDERING,
            "cross_facts": [{"axis_a_value": "M0->S0", "axis_b_value": "OUTSTANDING_DEPTH_2",
                              "legal": True}],
        }]
        ir = AMBAFunctionalCoverageIR.build(**facts)
        assert ir.crosses[0]["skipped"] is False
        assert len(ir.crosses[0]["bins"]) == 1
        assert len(ir.all_bins()) == 8  # 7 base bins + 1 real cross bin

    def test_cross_request_missing_axis_names_raises(self):
        facts = self._facts()
        facts["cross_requests"] = [{"axis_a_category": CATEGORY_CONNECTIVITY}]
        with pytest.raises(AMBAFunctionalCoverageIRError):
            AMBAFunctionalCoverageIR.build(**facts)

    def test_cross_request_unknown_category_raises(self):
        facts = self._facts()
        facts["cross_requests"] = [{
            "axis_a_name": "a", "axis_a_category": "NOT_A_REAL_CATEGORY",
            "axis_b_name": "b", "axis_b_snapshot": {"bins_total": 1, "bins_hit": 1},
        }]
        with pytest.raises(AMBAFunctionalCoverageIRError):
            AMBAFunctionalCoverageIR.build(**facts)

    def test_to_dict_round_trips_through_json(self):
        ir = AMBAFunctionalCoverageIR.build(**self._facts())
        doc = ir.to_dict()
        json.dumps(doc)  # must be fully JSON-serializable
        assert doc["reachability_summary"][COVERED_OBSERVED] >= 1

    def test_empty_build_is_legal_and_empty(self):
        ir = AMBAFunctionalCoverageIR.build()
        assert ir.all_bins() == []
        summary = ir.reachability_summary()
        assert all(v == 0 for v in summary.values())


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------
class TestCLI:
    def _write_facts(self, tmp_path: Path) -> Path:
        doc = {
            "legal_edges": [{"master": "M0", "slave": "S0", "legal": True, "observed_hit": True}],
        }
        p = tmp_path / "facts.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        return p

    def test_execute_verb_build_json(self, tmp_path, capsys):
        facts_path = self._write_facts(tmp_path)
        rc = execute_verb(["build", "--facts", str(facts_path), "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        doc = json.loads(out)
        assert len(doc["connectivity_coverpoints"]) == 1

    def test_execute_verb_build_text(self, tmp_path, capsys):
        facts_path = self._write_facts(tmp_path)
        rc = execute_verb(["build", "--facts", str(facts_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "bins=1" in out

    def test_execute_verb_malformed_facts_reports_error(self, tmp_path, capsys):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"legal_edges": [{"master": "M0"}]}), encoding="utf-8")
        rc = execute_verb(["build", "--facts", str(p)])
        assert rc == 2
        assert "status=ERROR" in capsys.readouterr().out

    def test_execute_verb_missing_file_reports_error(self, tmp_path, capsys):
        rc = execute_verb(["build", "--facts", str(tmp_path / "nope.json")])
        assert rc == 2

    def test_real_subprocess_invocation(self, tmp_path):
        facts_path = self._write_facts(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "dv_harness.amba_functional_coverage_ir",
             "build", "--facts", str(facts_path), "--json"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        doc = json.loads(result.stdout)
        assert len(doc["connectivity_coverpoints"]) == 1
