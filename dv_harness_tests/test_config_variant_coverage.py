"""Tests for dv_harness/config_variant_coverage.py -- spec section 232
CONFIGURATION VARIANT EXPLOSION CONTROL.

WHAT THESE TESTS ARE HOLDING THE MODULE TO. The claim being made is
mathematical -- "this reduced set of configurations covers every legal
pairwise interaction of the declared space" -- so the central tests do NOT
call `verify_coverage()` and assert it says FULL. That would only prove the
module agrees with itself. `_brute_force_uncovered_pairs()` below is an
INDEPENDENT re-derivation written from scratch in this file: it enumerates
every legal (dim_a=va, dim_b=vb) pair by nested loops over the declared
dimensions and rescans the emitted rows. The generator's own bookkeeping,
its target-tuple helper, and its verifier are all bypassed.

The fixture is `fixtures/config_variants/synthetic_pcie_ep_space.json`, whose
own description states it is a test fixture and not any real DUT's
configuration -- 8 dimensions shaped like the ones section 232 names, 3
constraints, 2 declared critical combinations (one of them only partially
pinned). Nothing here builds, runs, submits or approves anything.
"""
from __future__ import annotations

import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import config_variant_coverage as cvc
from dv_harness.config_variant_coverage import (
    ConfigSpace, ConfigSpaceError, STATUS_FULL, STATUS_FULL_EXCEPT_UNREACHABLE,
    STATUS_PARTIAL,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "dv_harness_tests" / "fixtures" / "config_variants" / "synthetic_pcie_ep_space.json"


# --------------------------------------------------------------------------
# independent re-derivations (deliberately NOT using the module's helpers)
# --------------------------------------------------------------------------

def _fixture_space() -> ConfigSpace:
    return cvc.load_config_space(FIXTURE)


def _raw_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _independent_is_legal(raw: dict, row: dict) -> bool:
    """Constraint check re-implemented from the fixture JSON directly."""
    for con in raw.get("constraints", []):
        forbid = con["forbid"]
        hit = True
        for dim, val in forbid.items():
            allowed = val if isinstance(val, list) else [val]
            if dim not in row or row[dim] not in allowed:
                hit = False
                break
        if hit:
            return False
    return True


def _brute_force_uncovered_pairs(raw: dict, rows):
    """Every legal 2-way interaction of the declared space that does NOT
    appear in `rows`. Nested loops over the raw fixture JSON -- no module
    code is used to build the target set or to scan the rows."""
    dims = [(d["name"], d["values"]) for d in raw["dimensions"]]
    uncovered = []
    for (name_a, vals_a), (name_b, vals_b) in itertools.combinations(dims, 2):
        for va in vals_a:
            for vb in vals_b:
                pair = {name_a: va, name_b: vb}
                if not _independent_is_legal(raw, pair):
                    continue  # the interaction itself is forbidden
                found = False
                for row in rows:
                    if row.get(name_a) == va and row.get(name_b) == vb:
                        found = True
                        break
                if not found:
                    uncovered.append(pair)
    return uncovered


def _brute_force_uncovered_triples(raw: dict, rows):
    dims = [(d["name"], d["values"]) for d in raw["dimensions"]]
    uncovered = []
    for trio in itertools.combinations(dims, 3):
        names = [n for n, _ in trio]
        for combo in itertools.product(*[v for _, v in trio]):
            triple = dict(zip(names, combo))
            if not _independent_is_legal(raw, triple):
                continue
            if not any(all(row.get(k) == v for k, v in triple.items()) for row in rows):
                uncovered.append(triple)
    return uncovered


# --------------------------------------------------------------------------
# the central claim: real pairwise coverage, really reduced
# --------------------------------------------------------------------------

def test_pairwise_plan_covers_every_legal_pair_by_independent_recount():
    space = _fixture_space()
    raw = _raw_fixture()
    combos = cvc.generate_covering_array(space, 2)

    uncovered = _brute_force_uncovered_pairs(raw, combos)
    assert uncovered == [], (
        f"{len(uncovered)} legal pairwise interaction(s) missing from the generated set, "
        f"first few: {uncovered[:5]}")


def test_plan_is_dramatically_smaller_than_the_cross_product():
    """The whole point of section 232: 8 dimensions is already a
    four-thousand-configuration Cartesian product. A pairwise set that is not
    meaningfully smaller has not controlled anything."""
    space = _fixture_space()
    plan = cvc.build_plan(space, 2)

    assert plan["full_cross_product_size"] == 3 * 5 * 3 * 3 * 4 * 3 * 2 * 2 == 6480
    legal = plan["legal_cross_product_size"]
    assert 0 < legal < 6480, "the fixture's constraints must remove some cross-product points"

    selected = plan["selected_combination_count"]
    # The information-theoretic floor for pairwise coverage is the product of
    # the two largest value counts (5 lane widths x 4 feature modes): no
    # covering array can be smaller, so a "smaller" answer would be a bug,
    # not an improvement.
    assert selected >= 5 * 4
    # ... and it must be a real reduction, not a token one.
    assert selected < legal / 20, f"selected {selected} vs {legal} legal configurations"
    assert plan["reduction_ratio"] > 0.95


def test_every_emitted_configuration_is_complete_and_legal():
    space = _fixture_space()
    raw = _raw_fixture()
    combos = cvc.generate_covering_array(space, 2)
    dim_names = {d["name"] for d in raw["dimensions"]}
    legal_values = {d["name"]: d["values"] for d in raw["dimensions"]}

    for row in combos:
        assert set(row) == dim_names, f"incomplete configuration emitted: {row}"
        for k, v in row.items():
            assert v in legal_values[k], f"illegal value {k}={v!r} emitted"
        assert _independent_is_legal(raw, row), f"constraint-violating configuration emitted: {row}"


def test_three_way_strength_covers_every_legal_triple():
    """One implementation, any strength -- the IPOG generalisation, checked
    against an independent triple recount rather than assumed from the
    pairwise result."""
    space = _fixture_space()
    raw = _raw_fixture()
    combos = cvc.generate_covering_array(space, 3)

    assert _brute_force_uncovered_triples(raw, combos) == []
    # 3-way costs more than 2-way but must still be far below the product.
    assert len(combos) > len(cvc.generate_covering_array(space, 2))
    assert len(combos) < space.legal_cross_product_size()[0] / 10


def test_growth_is_combinatorial_for_the_product_and_not_for_the_plan():
    """A non-trivial dimension count: 10 ternary dimensions is a 59049-point
    Cartesian product, and pairwise coverage of it needs on the order of
    tens of configurations. This is the property that makes the mechanism
    worth having at all."""
    space = ConfigSpace(
        space_id="ten_ternary_dimensions",
        dimensions=tuple(cvc.ConfigDimension(name=f"d{i}", values=("x", "y", "z"))
                         for i in range(10)))
    assert space.full_cross_product_size() == 3 ** 10 == 59049

    combos = cvc.generate_covering_array(space, 2)
    raw = {"dimensions": [{"name": f"d{i}", "values": ["x", "y", "z"]} for i in range(10)],
           "constraints": []}
    assert _brute_force_uncovered_pairs(raw, combos) == []
    assert 9 <= len(combos) <= 30, f"expected tens of configurations, got {len(combos)}"


# --------------------------------------------------------------------------
# section 232's own rule: critical configurations are never dropped
# --------------------------------------------------------------------------

def test_declared_critical_combinations_survive_into_the_plan():
    space = _fixture_space()
    plan = cvc.build_plan(space, 2)
    combos = plan["combinations"]

    assert plan["critical_combinations"]["declared"] == 2
    assert plan["critical_combinations"]["missing_count"] == 0
    assert any(r["gen_speed"] == "gen5" and r["lane_width"] == 16 and r["sku"] == "server"
               for r in combos)
    # the partially-pinned one was completed to a full legal configuration
    assert any(r["feature_mode"] == "ide" and r["gen_speed"] == "gen5" for r in combos)


def test_a_critical_combination_is_kept_even_when_it_is_redundant():
    """The pruning pass drops rows whose pair contribution is already
    covered. A critical row that is entirely redundant must survive it
    anyway -- that is the difference between "reduce compute" and "remove a
    critical configuration to reduce compute"."""
    dims = (cvc.ConfigDimension(name="a", values=("a1", "a2")),
            cvc.ConfigDimension(name="b", values=("b1", "b2")))
    plain = ConfigSpace(space_id="plain", dimensions=dims)
    with_crit = ConfigSpace(
        space_id="with_crit", dimensions=dims,
        critical_combinations=(cvc.CriticalCombination(
            assignment={"a": "a1", "b": "b1"}, reason="declared critical"),))

    # With 2 dimensions the pairwise set IS the full product: the critical row
    # is fully redundant with it.
    base = cvc.generate_covering_array(plain, 2)
    kept = cvc.generate_covering_array(with_crit, 2)
    assert len(base) == 4
    assert {"a": "a1", "b": "b1"} in kept
    assert cvc.critical_combination_status(with_crit, kept)["missing_count"] == 0


def test_a_critical_combination_contradicting_a_constraint_is_refused():
    with pytest.raises(ConfigSpaceError) as e:
        ConfigSpace(
            space_id="contradiction",
            dimensions=(cvc.ConfigDimension(name="a", values=("a1", "a2")),),
            constraints=(cvc.Constraint(forbid={"a": ("a1",)}, reason="forbidden"),),
            critical_combinations=(cvc.CriticalCombination(assignment={"a": "a1"}),))
    assert "forbidden by this space's own constraints" in str(e.value)


def test_a_critical_combination_with_no_legal_completion_is_surfaced_not_dropped():
    """Legal as a partial assignment, but no full configuration containing it
    exists. Section 232 forbids quietly dropping it, so generation raises."""
    space = ConfigSpace(
        space_id="uncompletable_critical",
        dimensions=(cvc.ConfigDimension(name="a", values=("a1", "a2")),
                    cvc.ConfigDimension(name="b", values=("b1", "b2"))),
        constraints=(cvc.Constraint(forbid={"a": ("a1",), "b": ("b1",)}, reason="x"),
                     cvc.Constraint(forbid={"a": ("a1",), "b": ("b2",)}, reason="y")),
        critical_combinations=(cvc.CriticalCombination(assignment={"a": "a1"},
                                                       reason="declared critical"),))
    with pytest.raises(ConfigSpaceError) as e:
        cvc.generate_covering_array(space, 2)
    assert "no legal completion" in str(e.value)


# --------------------------------------------------------------------------
# constraints: excluded, unreachable, never silently "covered"
# --------------------------------------------------------------------------

def test_forbidden_pairs_are_excluded_from_the_target_set_and_reported():
    space = _fixture_space()
    targets, excluded = cvc.target_tuples(space, 2)
    excluded_pairs = [e["tuple"] for e in excluded]

    assert {"gen_speed": "gen5", "lane_width": 1} in excluded_pairs
    assert {"feature_mode": "sriov", "sku": "client"} in excluded_pairs
    assert {"clock_mode": "srns", "gen_speed": "gen3"} in excluded_pairs
    assert len(excluded) == 3
    for e in excluded:
        assert e["excluded_by_constraint"]["reason"]
    for tup in targets:
        assert dict(tup) not in excluded_pairs


def test_an_individually_legal_but_uncompletable_pair_is_reported_unreachable():
    """`a1,b1` violates no single constraint, but every completion of it does.
    It must be named UNREACHABLE_UNDER_CONSTRAINTS -- not silently absent and
    not counted as covered."""
    space = ConfigSpace(
        space_id="unreachable_pair",
        dimensions=(cvc.ConfigDimension(name="a", values=("a1", "a2")),
                    cvc.ConfigDimension(name="b", values=("b1", "b2")),
                    cvc.ConfigDimension(name="c", values=("c1", "c2"))),
        constraints=(cvc.Constraint(forbid={"a": ("a1",), "b": ("b1",), "c": ("c1",)}, reason="x"),
                     cvc.Constraint(forbid={"a": ("a1",), "b": ("b1",), "c": ("c2",)}, reason="y")))
    plan = cvc.build_plan(space, 2)

    assert plan["status"] == STATUS_FULL_EXCEPT_UNREACHABLE
    unreachable = [u["tuple"] for u in plan["coverage"]["unreachable_tuples"]]
    assert unreachable == [{"a": "a1", "b": "b1"}]
    assert plan["coverage"]["uncovered_tuple_count"] == 0
    for row in plan["combinations"]:
        assert space.is_valid(row)


def test_legal_cross_product_is_exactly_counted_and_smaller_than_the_raw_product():
    space = _fixture_space()
    legal, reason = space.legal_cross_product_size()
    assert reason == "exactly enumerated"

    # independent recount
    names = [d["name"] for d in _raw_fixture()["dimensions"]]
    values = [d["values"] for d in _raw_fixture()["dimensions"]]
    expected = sum(1 for combo in itertools.product(*values)
                   if _independent_is_legal(_raw_fixture(), dict(zip(names, combo))))
    assert legal == expected < space.full_cross_product_size()


def test_an_oversized_space_reports_uncounted_rather_than_a_guess():
    space = ConfigSpace(
        space_id="huge",
        dimensions=tuple(cvc.ConfigDimension(name=f"d{i}", values=tuple(range(10)))
                         for i in range(6)),
        constraints=(cvc.Constraint(forbid={"d0": (0,), "d1": (0,)}, reason="x"),))
    legal, reason = space.legal_cross_product_size()
    assert legal is None
    assert reason.startswith("UNCOUNTED:")


# --------------------------------------------------------------------------
# the verifier is not vacuous
# --------------------------------------------------------------------------

def test_verifier_rejects_a_deficient_hand_written_set():
    """If `verify_coverage` said FULL for anything handed to it, the coverage
    claim above would be worthless. Drop one row from a proven-good plan and
    the verifier must name the pairs that went missing."""
    space = _fixture_space()
    combos = cvc.generate_covering_array(space, 2)
    deficient = combos[:-1]

    report = cvc.verify_coverage(space, deficient, 2)
    assert report["status"] == STATUS_PARTIAL
    assert report["uncovered_tuple_count"] > 0
    assert report["unreachable_tuples"] == []

    # and the named pairs really are absent, by independent recount
    raw = _raw_fixture()
    independently_missing = _brute_force_uncovered_pairs(raw, deficient)
    def _canon(pairs):
        return sorted(tuple(sorted(p.items(), key=repr)) for p in pairs)

    named = [e["tuple"] for e in report["uncovered_tuples"]]
    assert _canon(named) == _canon(independently_missing)


def test_verifier_rejects_an_illegal_or_incomplete_row():
    space = _fixture_space()
    combos = cvc.generate_covering_array(space, 2)

    illegal = list(combos)
    bad = dict(combos[0])
    bad.update({"gen_speed": "gen5", "lane_width": 1})  # a declared forbidden pair
    illegal.append(bad)
    report = cvc.verify_coverage(space, illegal, 2)
    assert report["status"] == STATUS_PARTIAL
    assert report["illegal_combinations"]
    assert report["illegal_combinations"][0]["violates"]["forbid"] == {"gen_speed": "gen5",
                                                                       "lane_width": 1}

    incomplete = [dict(r) for r in combos]
    incomplete[0].pop("vip_config")
    incomplete[0]["not_a_dimension"] = 1
    report2 = cvc.verify_coverage(space, incomplete, 2)
    assert report2["status"] == STATUS_PARTIAL
    assert report2["incomplete_combinations"][0]["unassigned_dimensions"] == ["vip_config"]
    assert report2["incomplete_combinations"][0]["unknown_dimensions"] == ["not_a_dimension"]


def test_verifier_rejects_a_row_with_an_undeclared_value():
    space = _fixture_space()
    combos = cvc.generate_covering_array(space, 2)
    tampered = [dict(r) for r in combos]
    tampered[0]["gen_speed"] = "gen6"
    report = cvc.verify_coverage(space, tampered, 2)
    assert report["status"] == STATUS_PARTIAL
    assert report["illegal_combinations"][0]["illegal_value"] == {"dimension": "gen_speed",
                                                                  "value": "gen6"}


def test_the_plan_verifies_itself_and_the_two_agree():
    space = _fixture_space()
    plan = cvc.build_plan(space, 2)
    assert plan["status"] == STATUS_FULL
    assert plan["coverage"]["covered_tuple_count"] == plan["coverage"]["target_tuple_count"]
    # and the independent recount agrees with the module's own count
    raw = _raw_fixture()
    dims = [(d["name"], d["values"]) for d in raw["dimensions"]]
    expected_targets = 0
    for (na, va), (nb, vb) in itertools.combinations(dims, 2):
        for x in va:
            for y in vb:
                if _independent_is_legal(raw, {na: x, nb: y}):
                    expected_targets += 1
    assert plan["coverage"]["target_tuple_count"] == expected_targets


# --------------------------------------------------------------------------
# determinism, artifacts, declaration errors
# --------------------------------------------------------------------------

def test_generation_is_deterministic():
    space = _fixture_space()
    a = cvc.generate_covering_array(space, 2)
    b = cvc.generate_covering_array(_fixture_space(), 2)
    assert a == b


def test_plan_artifact_round_trips(tmp_path):
    space = _fixture_space()
    plan = cvc.build_plan(space, 2)
    out = cvc.write_plan(tmp_path, plan)
    assert out == tmp_path / ".dv-harness" / "regression" / "config_variant_plan.json"
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["algorithm"] == "IPOG"
    assert "ECBS 2007" in loaded["algorithm_reference"]
    # the artifact is re-verifiable on its own
    assert cvc.verify_coverage(space, loaded["combinations"], 2)["status"] == STATUS_FULL


@pytest.mark.parametrize("payload, needle", [
    ({"dimensions": [{"name": "a", "values": ["x"]}],
      "constraints": [{"forbid": {"nope": "x"}}]}, "unknown dimension"),
    ({"dimensions": [{"name": "a", "values": ["x"]}],
      "constraints": [{"forbid": {"a": "y"}}]}, "not one of"),
    ({"dimensions": [{"name": "a", "values": [["nested"]]}]}, "not a JSON scalar"),
    ({"dimensions": [{"name": "a", "values": []}]}, "no legal values"),
    ({"dimensions": [{"name": "a", "values": ["x", "x"]}]}, "duplicate value"),
    ({"dimensions": [{"name": "a", "values": ["x"]}, {"name": "a", "values": ["y"]}]},
     "duplicate dimension name"),
    ({"dimensions": [{"name": "a", "values": ["x"]}],
      "critical_combinations": [{"assignment": {"a": "zzz"}}]}, "not one of its"),
])
def test_a_broken_declaration_is_refused_with_a_reason(payload, needle):
    with pytest.raises(ConfigSpaceError) as e:
        cvc.config_space_from_dict(payload)
    assert needle in str(e.value)


def test_strength_beyond_the_dimension_count_is_refused():
    space = ConfigSpace(space_id="tiny",
                        dimensions=(cvc.ConfigDimension(name="a", values=("x", "y")),))
    with pytest.raises(ConfigSpaceError) as e:
        cvc.target_tuples(space, 2)
    assert "exceeds" in str(e.value)


# --------------------------------------------------------------------------
# vPlan-stage wiring: plan_from_requirement_configuration()
# --------------------------------------------------------------------------
# A synthetic requirement's declared configuration -- the dimension->legal-
# values MAPPING shape the adapter takes, deliberately distinct from
# requirement_contract.schema.json's own `configuration` FIELD (free-text
# `contract_text`, confirmed by reading that schema rather than assumed).

SYNTHETIC_REQUIREMENT_CONFIGURATION = {
    "gen_speed": ["gen3", "gen4", "gen5"],
    "lane_width": [1, 2, 4, 8],
    "feature_mode": ["ide", "sriov"],
}


def test_plan_from_requirement_configuration_covers_every_legal_pair_by_independent_recount():
    plan = cvc.plan_from_requirement_configuration(
        SYNTHETIC_REQUIREMENT_CONFIGURATION, requirement_id="REQ-232-1")

    raw = {"dimensions": [{"name": name, "values": values}
                          for name, values in SYNTHETIC_REQUIREMENT_CONFIGURATION.items()],
           "constraints": []}
    uncovered = _brute_force_uncovered_pairs(raw, plan["combinations"])
    assert uncovered == [], f"missing pairwise interaction(s): {uncovered[:5]}"
    assert plan["status"] == STATUS_FULL
    assert plan["algorithm"] == "IPOG"
    # a real reduction versus the 3*4*2 = 24-point cross product
    assert plan["full_cross_product_size"] == 24
    assert plan["selected_combination_count"] < 24


def test_plan_from_requirement_configuration_carries_requirement_id_as_provenance():
    plan = cvc.plan_from_requirement_configuration(
        SYNTHETIC_REQUIREMENT_CONFIGURATION, requirement_id="REQ-232-1")

    assert plan["space_id"] == "requirement_REQ-232-1_configuration"
    assert "REQ-232-1" in plan["description"]
    for dim in plan["dimensions"]:
        assert dim["source"] == "requirement_contract:REQ-232-1"

    # no requirement_id at all is still honestly labelled, never left blank
    unattributed = cvc.plan_from_requirement_configuration(SYNTHETIC_REQUIREMENT_CONFIGURATION)
    assert unattributed["space_id"] == "requirement_configuration"
    for dim in unattributed["dimensions"]:
        assert dim["source"] == "requirement_contract"


def test_plan_from_requirement_configuration_passes_through_constraints_and_critical_combinations():
    plan = cvc.plan_from_requirement_configuration(
        SYNTHETIC_REQUIREMENT_CONFIGURATION,
        requirement_id="REQ-232-2",
        constraints=[{"forbid": {"gen_speed": "gen3", "lane_width": 8}, "reason": "not a legal combo"}],
        critical_combinations=[{"assignment": {"gen_speed": "gen5", "feature_mode": "sriov"},
                                "reason": "declared critical by the requirement"}])

    assert plan["constraint_count"] == 1
    assert not any(r["gen_speed"] == "gen3" and r["lane_width"] == 8 for r in plan["combinations"])
    assert plan["critical_combinations"]["declared"] == 1
    assert plan["critical_combinations"]["missing_count"] == 0
    assert any(r["gen_speed"] == "gen5" and r["feature_mode"] == "sriov"
               for r in plan["combinations"])


@pytest.mark.parametrize("bad_configuration, needle", [
    ({}, "non-empty mapping"),
    (None, "non-empty mapping"),
    ({"gen_speed": "gen3"}, "must declare its legal values as a list/tuple"),
])
def test_plan_from_requirement_configuration_refuses_a_malformed_mapping(bad_configuration, needle):
    """Three distinct negative controls: an empty mapping, a non-mapping, and
    a dimension whose 'values' is a bare scalar rather than a list -- none of
    these may silently produce a one-dimension or zero-dimension plan."""
    with pytest.raises(ConfigSpaceError) as e:
        cvc.plan_from_requirement_configuration(bad_configuration)
    assert needle in str(e.value)


def test_plan_from_requirement_configuration_still_refuses_an_uncompletable_critical_combination():
    """The adapter forwards to the same generate_covering_array() that already
    refuses to silently drop a critical combination with no legal completion
    -- it must not swallow or soften that refusal."""
    with pytest.raises(ConfigSpaceError) as e:
        cvc.plan_from_requirement_configuration(
            {"a": ["a1", "a2"], "b": ["b1", "b2"]},
            requirement_id="REQ-232-3",
            constraints=[{"forbid": {"a": "a1", "b": "b1"}, "reason": "x"},
                        {"forbid": {"a": "a1", "b": "b2"}, "reason": "y"}],
            critical_combinations=[{"assignment": {"a": "a1"}, "reason": "declared critical"}])
    assert "no legal completion" in str(e.value)


# --------------------------------------------------------------------------
# the real CLI entry points, driven as real subprocesses
# --------------------------------------------------------------------------

def _run(args):
    return subprocess.run(args, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)


def test_module_cli_plan_and_verify_round_trip(tmp_path):
    out = tmp_path / "plan.json"
    r = _run([sys.executable, "-m", "dv_harness.config_variant_coverage", "plan",
              "--space", str(FIXTURE), "--out", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FULL_COVERAGE" in r.stdout
    assert "IPOG" in r.stdout
    assert out.exists()

    r2 = _run([sys.executable, "-m", "dv_harness.config_variant_coverage", "verify",
               "--space", str(FIXTURE), "--combinations", str(out)])
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "FULL_COVERAGE" in r2.stdout

    # a deficient set exits non-zero and names what is missing
    plan = json.loads(out.read_text(encoding="utf-8"))
    deficient = tmp_path / "deficient.json"
    deficient.write_text(json.dumps(plan["combinations"][:-2]), encoding="utf-8")
    r3 = _run([sys.executable, "-m", "dv_harness.config_variant_coverage", "verify",
               "--space", str(FIXTURE), "--combinations", str(deficient)])
    assert r3.returncode == 1, r3.stdout + r3.stderr
    assert "UNCOVERED" in r3.stdout


def test_dv_harness_cli_verb_is_wired(tmp_path):
    out = tmp_path / "cli_plan.json"
    r = _run([sys.executable, "-m", "dv_harness", "config-variants", "plan",
              "--space", str(FIXTURE), "--out", str(out), "--json"])
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["algorithm"] == "IPOG"
    assert payload["status"] == STATUS_FULL
    assert out.exists()

    # and the same verb verifies what it just wrote
    r2 = _run([sys.executable, "-m", "dv_harness", "config-variants", "verify",
               "--space", str(FIXTURE), "--combinations", str(out)])
    assert r2.returncode == 0, r2.stdout + r2.stderr


def test_cli_reports_a_missing_space_file_as_a_usage_error(tmp_path):
    r = _run([sys.executable, "-m", "dv_harness.config_variant_coverage", "plan",
              "--space", str(tmp_path / "nope.json")])
    assert r.returncode == 2
    assert "does not exist" in r.stdout
