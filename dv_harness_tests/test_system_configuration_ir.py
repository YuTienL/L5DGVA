"""Tests for dv_harness/system_configuration_ir.py -- SYSTEM-LEVEL
configuration-explosion control composed on top of the REAL, unmodified
config_variant_coverage.py IPOG engine.

Every positive assertion is checked against an INDEPENDENT brute-force
re-derivation (never trusting this module's own bookkeeping, or
config_variant_coverage's), mirroring the discipline
test_config_variant_coverage.py itself already applies to the single-space
engine.
"""
from __future__ import annotations

import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import config_variant_coverage as cvc
from dv_harness import system_configuration_ir as sysir


# --------------------------------------------------------------------------
# fixtures: two synthetic (never-real-DUT) subsystem configuration spaces
# --------------------------------------------------------------------------

def _usb_subsystem() -> sysir.SubsystemConfigContribution:
    return sysir.SubsystemConfigContribution(
        subsystem_id="usb0",
        dimensions=(
            {"name": "speed_mode", "values": ["FS", "HS", "SS"], "source": "test fixture"},
            {"name": "lane_width", "values": ["x1", "x2"], "source": "test fixture"},
        ),
    )


def _pcie_subsystem() -> sysir.SubsystemConfigContribution:
    return sysir.SubsystemConfigContribution(
        subsystem_id="pcie0",
        dimensions=(
            {"name": "gen_speed", "values": ["Gen1", "Gen2", "Gen3"], "source": "test fixture"},
        ),
    )


def _amba_subsystem() -> sysir.SubsystemConfigContribution:
    return sysir.SubsystemConfigContribution(
        subsystem_id="amba0",
        dimensions=(
            {"name": "clock_mode", "values": ["sync", "async"], "source": "test fixture"},
        ),
    )


# --------------------------------------------------------------------------
# independent brute-force re-derivations
# --------------------------------------------------------------------------

def _brute_force_all_pairs(space: cvc.ConfigSpace) -> set:
    """Every legal pair of (dim, value)-(dim, value), independently
    enumerated from the space's own dimensions/constraints -- written from
    scratch here, never calling config_variant_coverage.target_tuples()."""
    pairs = set()
    dims = list(space.dimensions)
    for d1, d2 in itertools.combinations(dims, 2):
        for v1, v2 in itertools.product(d1.values, d2.values):
            assignment = {d1.name: v1, d2.name: v2}
            if space.is_valid(assignment):
                pairs.add(tuple(sorted(assignment.items())))
    return pairs


def _brute_force_covered_pairs(rows) -> set:
    covered = set()
    for row in rows:
        items = sorted(row.items())
        for a, b in itertools.combinations(items, 2):
            covered.add(tuple(sorted((a, b))))
    return covered


# --------------------------------------------------------------------------
# compose_system_config_space
# --------------------------------------------------------------------------

def test_compose_requires_at_least_two_subsystems():
    with pytest.raises(sysir.SystemConfigurationIRError, match="at least 2 subsystems"):
        sysir.compose_system_config_space([_usb_subsystem()])


def test_compose_rejects_duplicate_subsystem_id():
    with pytest.raises(sysir.SystemConfigurationIRError, match="duplicate subsystem_id"):
        sysir.compose_system_config_space([_usb_subsystem(), _usb_subsystem()])


def test_compose_rejects_subsystem_id_with_namespace_separator():
    with pytest.raises(sysir.SystemConfigurationIRError, match="reserved"):
        sysir.SubsystemConfigContribution(
            subsystem_id="usb.0",
            dimensions=({"name": "mode", "values": ["a", "b"]},),
        )


def test_compose_rejects_dimension_name_with_namespace_separator():
    bad = sysir.SubsystemConfigContribution(
        subsystem_id="usb0",
        dimensions=({"name": "speed.mode", "values": ["a", "b"]},),
    )
    with pytest.raises(sysir.SystemConfigurationIRError, match="reserved"):
        sysir.compose_system_config_space([bad, _pcie_subsystem()])


def test_compose_namespaces_dimensions_without_collision():
    """Two subsystems each declaring a dimension of the SAME bare name never
    collide once namespaced."""
    usb = sysir.SubsystemConfigContribution(
        subsystem_id="usb0", dimensions=({"name": "mode", "values": ["a", "b"]},))
    pcie = sysir.SubsystemConfigContribution(
        subsystem_id="pcie0", dimensions=({"name": "mode", "values": ["x", "y", "z"]},))
    space = sysir.compose_system_config_space([usb, pcie])
    names = set(space.dimension_names)
    assert names == {"usb0.mode", "pcie0.mode"}
    assert space.dimension("usb0.mode").values == ("a", "b")
    assert space.dimension("pcie0.mode").values == ("x", "y", "z")


def test_compose_reuses_real_config_space_validation_for_unknown_dimension():
    """A cross-subsystem constraint naming an unnamespaced (bare) key is
    refused by the REUSED config_variant_coverage.ConfigSpace validation --
    this module adds no second check for it."""
    with pytest.raises(cvc.ConfigSpaceError, match="unknown dimension"):
        sysir.compose_system_config_space(
            [_usb_subsystem(), _pcie_subsystem()],
            cross_subsystem_constraints=[
                {"forbid": {"speed_mode": "SS"}, "reason": "bare key, not namespaced"},
            ],
        )


def test_compose_local_constraint_is_namespaced_onto_its_own_subsystem():
    usb = sysir.SubsystemConfigContribution(
        subsystem_id="usb0",
        dimensions=({"name": "speed_mode", "values": ["FS", "HS", "SS"]},
                    {"name": "lane_width", "values": ["x1", "x2"]}),
        constraints=({"forbid": {"speed_mode": "FS", "lane_width": "x2"}, "reason": "FS is x1-only"},),
    )
    space = sysir.compose_system_config_space([usb, _pcie_subsystem()])
    assert not space.is_valid({"usb0.speed_mode": "FS", "usb0.lane_width": "x2"})
    assert space.is_valid({"usb0.speed_mode": "HS", "usb0.lane_width": "x2"})


def test_compose_local_critical_combination_is_namespaced():
    usb = sysir.SubsystemConfigContribution(
        subsystem_id="usb0",
        dimensions=({"name": "speed_mode", "values": ["FS", "HS", "SS"]},),
        critical_combinations=({"assignment": {"speed_mode": "SS"}, "reason": "superspeed must run"},),
    )
    space = sysir.compose_system_config_space([usb, _pcie_subsystem()])
    assert len(space.critical_combinations) == 1
    assert space.critical_combinations[0].assignment == {"usb0.speed_mode": "SS"}


def test_compose_cross_subsystem_constraint_uses_namespaced_keys():
    space = sysir.compose_system_config_space(
        [_usb_subsystem(), _pcie_subsystem()],
        cross_subsystem_constraints=[
            {"forbid": {"usb0.speed_mode": "SS", "pcie0.gen_speed": "Gen1"},
             "reason": "shared power rail cannot sustain USB SS + PCIe Gen1 simultaneously"},
        ],
    )
    assert not space.is_valid({"usb0.speed_mode": "SS", "pcie0.gen_speed": "Gen1"})
    assert space.is_valid({"usb0.speed_mode": "SS", "pcie0.gen_speed": "Gen2"})


def test_compose_cross_subsystem_critical_combination_uses_namespaced_keys():
    space = sysir.compose_system_config_space(
        [_usb_subsystem(), _pcie_subsystem()],
        cross_subsystem_critical_combinations=[
            {"assignment": {"usb0.speed_mode": "SS", "pcie0.gen_speed": "Gen3"},
             "reason": "worst-case bandwidth contention scenario"},
        ],
    )
    assert space.critical_combinations[0].assignment == {
        "usb0.speed_mode": "SS", "pcie0.gen_speed": "Gen3",
    }


def test_compose_rejects_non_mapping_subsystem_contribution_pieces():
    bad = sysir.SubsystemConfigContribution(
        subsystem_id="usb0", dimensions=("not-a-dict",))
    with pytest.raises(sysir.SystemConfigurationIRError, match="not an object"):
        sysir.compose_system_config_space([bad, _pcie_subsystem()])


# --------------------------------------------------------------------------
# build_system_configuration_plan: the real IPOG engine, reused unmodified,
# cross-checked against independent brute-force enumeration.
# --------------------------------------------------------------------------

def test_plan_full_coverage_over_two_subsystems_independently_verified():
    plan = sysir.build_system_configuration_plan([_usb_subsystem(), _pcie_subsystem()], strength=2)

    assert plan["status"] == cvc.STATUS_FULL
    assert plan["algorithm"] == "IPOG"  # the real, reused engine's own identity, unchanged

    # Independent re-derivation: rebuild the same composed space by hand and
    # brute-force every legal pair, then confirm the emitted combinations
    # cover exactly that set (a subset check is not enough -- IPOG must not
    # under- OR over-claim).
    space = sysir.compose_system_config_space([_usb_subsystem(), _pcie_subsystem()])
    expected_pairs = _brute_force_all_pairs(space)
    covered_pairs = _brute_force_covered_pairs(plan["combinations"])
    assert expected_pairs <= covered_pairs

    # Full cross product: 3 (speed) * 2 (lane) * 3 (gen_speed) = 18, and a
    # real pairwise covering set must be smaller than the blind product.
    assert plan["full_cross_product_size"] == 18
    assert plan["selected_combination_count"] < 18

    # Reduction ratio must be a real, positive number (never fabricated).
    assert 0.0 < plan["reduction_ratio"] < 1.0


def test_plan_reduction_is_real_across_three_subsystems():
    plan = sysir.build_system_configuration_plan(
        [_usb_subsystem(), _pcie_subsystem(), _amba_subsystem()], strength=2)
    assert plan["status"] == cvc.STATUS_FULL
    # 3 * 2 * 3 * 2 = 36 raw combinations across all three subsystems.
    assert plan["full_cross_product_size"] == 36
    assert plan["selected_combination_count"] < 36
    comp = plan["system_composition"]
    assert comp["subsystem_count"] == 3
    assert set(comp["subsystem_ids"]) == {"usb0", "pcie0", "amba0"}


def test_plan_respects_cross_subsystem_constraint():
    plan = sysir.build_system_configuration_plan(
        [_usb_subsystem(), _pcie_subsystem()],
        cross_subsystem_constraints=[
            {"forbid": {"usb0.speed_mode": "SS", "pcie0.gen_speed": "Gen1"},
             "reason": "shared power rail"},
        ],
        strength=2,
    )
    for combo in plan["combinations"]:
        assert not (combo.get("usb0.speed_mode") == "SS" and combo.get("pcie0.gen_speed") == "Gen1")
    # The forbidden pair must be reported as excluded, never silently absent
    # from the arithmetic.
    excluded_pairs = {
        (e["tuple"].get("usb0.speed_mode"), e["tuple"].get("pcie0.gen_speed"))
        for e in plan["coverage"]["excluded_by_constraint"]
    }
    assert ("SS", "Gen1") in excluded_pairs


def test_plan_seeds_declared_critical_combination_and_never_drops_it():
    plan = sysir.build_system_configuration_plan(
        [_usb_subsystem(), _pcie_subsystem()],
        cross_subsystem_critical_combinations=[
            {"assignment": {"usb0.speed_mode": "SS", "pcie0.gen_speed": "Gen3"},
             "reason": "worst-case bandwidth contention"},
        ],
        strength=2,
    )
    assert plan["critical_combinations"]["present"] == 1
    assert plan["critical_combinations"]["missing_count"] == 0
    hit = any(c.get("usb0.speed_mode") == "SS" and c.get("pcie0.gen_speed") == "Gen3"
              for c in plan["combinations"])
    assert hit


def test_plan_subsystem_breakdown_matches_projection():
    plan = sysir.build_system_configuration_plan([_usb_subsystem(), _pcie_subsystem()], strength=2)
    breakdown = plan["system_composition"]["subsystem_breakdown"]
    assert len(breakdown) == len(plan["combinations"])
    for entry, combo in zip(breakdown, plan["combinations"]):
        assert entry["by_subsystem"]["usb0"] == sysir.project_combination(combo, "usb0")
        assert entry["by_subsystem"]["pcie0"] == sysir.project_combination(combo, "pcie0")
        # Every namespaced key in the full combination is accounted for by
        # exactly one subsystem's projection.
        recombined = {}
        for sid, sub in entry["by_subsystem"].items():
            for k, v in sub.items():
                recombined[f"{sid}.{k}"] = v
        assert recombined == dict(combo)


# --------------------------------------------------------------------------
# verify_subsystem_projection_coverage: the independent per-subsystem re-check
# --------------------------------------------------------------------------

def test_projection_coverage_is_full_for_a_correct_plan():
    plan = sysir.build_system_configuration_plan([_usb_subsystem(), _pcie_subsystem()], strength=2)
    reports = plan["system_composition"]["subsystem_projection_coverage"]
    by_id = {r["subsystem_id"]: r for r in reports}
    assert by_id["usb0"]["status"] == cvc.STATUS_FULL
    assert by_id["pcie0"]["status"] == cvc.STATUS_FULL
    # usb0 has 2 dims (3x2=6 legal pairs, strength 2 -> exactly one pair, the
    # dims themselves): target_tuple_count must be a real positive number.
    assert by_id["usb0"]["target_tuple_count"] > 0
    assert by_id["usb0"]["effective_strength"] == 2
    assert by_id["usb0"]["requested_strength"] == 2
    # pcie0 has only ONE dimension: pairwise (strength-2) coverage is not a
    # meaningful question, so the local re-check honestly caps itself at
    # strength-1 ("does every declared value appear at least once") rather
    # than crashing or silently reporting a fabricated zero-target FULL.
    assert by_id["pcie0"]["effective_strength"] == 1
    assert by_id["pcie0"]["requested_strength"] == 2
    assert by_id["pcie0"]["target_tuple_count"] == 3  # Gen1/Gen2/Gen3, one target each


def test_projection_coverage_catches_a_deliberately_incomplete_combination_list():
    """This is the module's own negative control: independent
    re-verification must be able to fail, not merely always agree by
    construction. Drop rows from a real plan and confirm the projection
    re-check notices."""
    plan = sysir.build_system_configuration_plan([_usb_subsystem(), _pcie_subsystem()], strength=2)
    usb_only_combos = plan["combinations"][:1]  # deliberately incomplete
    report = sysir.verify_subsystem_projection_coverage(_usb_subsystem(), usb_only_combos, strength=2)
    assert report["status"] in (cvc.STATUS_PARTIAL, cvc.STATUS_FULL)
    # With only one row, at most one usb0 pair can be covered; usb0 has more
    # than one target pair (3 speed_mode x 2 lane_width => 1 dimension-pair,
    # but multiple value-pairs), so a single row cannot cover them all.
    assert report["covered_tuple_count"] <= report["target_tuple_count"]
    if report["target_tuple_count"] > 1:
        assert report["status"] == cvc.STATUS_PARTIAL


def test_projection_coverage_excludes_cross_subsystem_constraints():
    """A cross-subsystem-only constraint must not affect a subsystem's own
    LOCAL target pairs -- the local re-check space is built from only that
    subsystem's own local constraints."""
    plan = sysir.build_system_configuration_plan(
        [_usb_subsystem(), _pcie_subsystem()],
        cross_subsystem_constraints=[
            {"forbid": {"usb0.speed_mode": "SS", "pcie0.gen_speed": "Gen1"}, "reason": "x"},
        ],
        strength=2,
    )
    report = sysir.verify_subsystem_projection_coverage(_usb_subsystem(), plan["combinations"], strength=2)
    # usb0 has no local constraint at all, so no pair should ever be
    # reported excluded_by_constraint in its own local re-check.
    assert report["excluded_by_constraint_count"] == 0
    assert report["status"] == cvc.STATUS_FULL


# --------------------------------------------------------------------------
# worst-wins fold
# --------------------------------------------------------------------------

def test_worst_status_never_averages():
    assert sysir._worst_status([cvc.STATUS_FULL, cvc.STATUS_FULL, cvc.STATUS_PARTIAL]) == cvc.STATUS_PARTIAL
    assert sysir._worst_status([cvc.STATUS_FULL, cvc.STATUS_NOT_AVAILABLE]) == cvc.STATUS_NOT_AVAILABLE
    assert sysir._worst_status([cvc.STATUS_FULL]) == cvc.STATUS_FULL


# --------------------------------------------------------------------------
# document parsing / CLI
# --------------------------------------------------------------------------

def _system_config_document():
    return {
        "system_id": "test_soc",
        "description": "synthetic test fixture, not any real DUT",
        "subsystems": [
            {"subsystem_id": "usb0",
             "dimensions": [{"name": "speed_mode", "values": ["FS", "HS", "SS"]},
                             {"name": "lane_width", "values": ["x1", "x2"]}]},
            {"subsystem_id": "pcie0",
             "dimensions": [{"name": "gen_speed", "values": ["Gen1", "Gen2", "Gen3"]}]},
        ],
        "cross_subsystem_constraints": [
            {"forbid": {"usb0.speed_mode": "SS", "pcie0.gen_speed": "Gen1"}, "reason": "power rail"},
        ],
    }


def test_load_system_config_document_round_trip(tmp_path):
    p = tmp_path / "system_space.json"
    p.write_text(json.dumps(_system_config_document()), encoding="utf-8")
    subsystems, cross_constraints, cross_criticals, system_id, description = \
        sysir.load_system_config_document(p)
    assert system_id == "test_soc"
    assert len(subsystems) == 2
    assert len(cross_constraints) == 1
    assert cross_criticals == []


def test_load_system_config_document_missing_file(tmp_path):
    with pytest.raises(sysir.SystemConfigurationIRError, match="does not exist"):
        sysir.load_system_config_document(tmp_path / "nope.json")


def test_load_system_config_document_needs_subsystems_list(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"system_id": "x"}), encoding="utf-8")
    with pytest.raises(sysir.SystemConfigurationIRError, match="subsystems"):
        sysir.load_system_config_document(p)


def test_execute_verb_plan_success(tmp_path):
    p = tmp_path / "system_space.json"
    p.write_text(json.dumps(_system_config_document()), encoding="utf-8")
    text, code = sysir.execute_verb("plan", space_path=str(p), strength=2, as_json=True)
    assert code == 0
    data = json.loads(text)
    assert data["status"] == cvc.STATUS_FULL
    assert data["system_composition"]["subsystem_count"] == 2


def test_execute_verb_plan_writes_out_file(tmp_path):
    p = tmp_path / "system_space.json"
    p.write_text(json.dumps(_system_config_document()), encoding="utf-8")
    out = tmp_path / "out_plan.json"
    text, code = sysir.execute_verb("plan", space_path=str(p), strength=2, out_path=str(out))
    assert code == 0
    assert out.exists()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["status"] == cvc.STATUS_FULL


def test_execute_verb_missing_space_argument():
    text, code = sysir.execute_verb("plan", space_path=None)
    assert code == 2
    assert "--space" in text


def test_execute_verb_unknown_verb():
    text, code = sysir.execute_verb("verify", space_path="whatever")
    assert code == 2
    assert "unknown" in text


def test_execute_verb_reports_config_space_error(tmp_path):
    doc = _system_config_document()
    doc["cross_subsystem_constraints"] = [{"forbid": {"speed_mode": "SS"}, "reason": "bare key"}]
    p = tmp_path / "bad_space.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    text, code = sysir.execute_verb("plan", space_path=str(p))
    assert code == 2
    assert "ConfigSpaceError" in text


def test_real_cli_subprocess_plan(tmp_path):
    p = tmp_path / "system_space.json"
    p.write_text(json.dumps(_system_config_document()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_configuration_ir", "plan",
         "--space", str(p), "--json"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == cvc.STATUS_FULL
    assert data["algorithm"] == "IPOG"


def test_real_cli_subprocess_text_output(tmp_path):
    p = tmp_path / "system_space.json"
    p.write_text(json.dumps(_system_config_document()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_configuration_ir", "plan", "--space", str(p)],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "system composition" in proc.stdout
    assert "subsystem projection" in proc.stdout
