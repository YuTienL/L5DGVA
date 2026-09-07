"""Tests for dv_harness/usage_recipe_catalog.py.

Real fixtures: small real JSON documents written to a temp directory (via
`tmp_path`), and the real CLI entry point driven as a real subprocess. No
mocks. Reuses `programming_sequence_ir`'s own real dataclasses/parsers/
validator throughout, exactly as the module under test does.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import programming_sequence_ir as psir
from dv_harness import usage_recipe_catalog as urc


# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------

def _clean_sequence_doc():
    return {
        "name": "usb3_link_bringup",
        "steps": [
            {"index": 0, "phase": "INIT", "action": "write",
             "register": "clk_en", "value": "0x1"},
            {"index": 1, "phase": "CONFIGURE", "action": "write",
             "register": "phy_cfg", "value": "0x3"},
            {"index": 2, "phase": "CONFIGURE", "action": "write",
             "register": "link_cfg", "value": "0x7"},
            {"index": 3, "phase": "ENABLE", "action": "write",
             "register": "link_en", "value": "0x1"},
            {"index": 4, "phase": "WAIT", "action": "wait"},
            {"index": 5, "phase": "VERIFY", "action": "read",
             "register": "link_status"},
            {"index": 6, "phase": "RESET", "action": "write",
             "register": "soft_reset", "value": "0x1"},
        ],
    }


def _clean_facts():
    return [
        {"name": "clk_en", "offset": "0x0", "access_type": "RW", "depends_on": []},
        {"name": "phy_cfg", "offset": "0x4", "access_type": "RW", "depends_on": ["clk_en"]},
        {"name": "link_cfg", "offset": "0x8", "access_type": "RW", "depends_on": ["phy_cfg"]},
        {"name": "link_en", "offset": "0xC", "access_type": "RW", "depends_on": ["link_cfg"]},
        {"name": "link_status", "offset": "0x10", "access_type": "RO", "depends_on": []},
        {"name": "soft_reset", "offset": "0x14", "access_type": "WO", "depends_on": []},
    ]


def _ir(doc=None):
    return psir.programming_sequence_ir_from_dict(doc or _clean_sequence_doc())


def _facts(raw=None):
    return psir.register_facts_from_dicts(raw if raw is not None else _clean_facts())


def _bringup_recipe_dict(recipe_id="bring_up_link", citation="programming_guide.md section 4.2"):
    doc = _clean_sequence_doc()
    return {
        "recipe_id": recipe_id,
        "purpose": "Bring the USB3 link up from reset to VERIFY-ready.",
        "citation": citation,
        "steps": doc["steps"],
    }


def _teardown_recipe_dict(recipe_id="reset_link"):
    return {
        "recipe_id": recipe_id,
        "purpose": "Soft-reset the link after a failed bring-up attempt.",
        "citation": "programming_guide.md section 4.9",
        "steps": [
            {"index": 0, "phase": "RESET", "action": "write",
             "register": "soft_reset", "value": "0x1"},
        ],
    }


# ---------------------------------------------------------------------------
# assembly from a raw dict -- positive path
# ---------------------------------------------------------------------------

def test_recipe_from_dict_carries_purpose_citation_and_reused_steps():
    recipe = urc.usage_recipe_from_dict(_bringup_recipe_dict())
    assert recipe.recipe_id == "bring_up_link"
    assert recipe.purpose == "Bring the USB3 link up from reset to VERIFY-ready."
    assert recipe.citation == "programming_guide.md section 4.2"
    assert len(recipe.steps) == 7
    # steps really are programming_sequence_ir's own dataclass, not a parallel shape
    assert all(isinstance(s, psir.ProgrammingSequenceStep) for s in recipe.steps)
    assert recipe.steps[0].phase == "INIT"
    assert recipe.steps[-1].phase == "RESET"


def test_recipe_from_dict_malformed_steps_reuses_real_step_parser_error():
    raw = _bringup_recipe_dict()
    raw["steps"][2]["index"] = 99  # break contiguity -- programming_sequence_ir's own check
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_dict(raw)


# ---------------------------------------------------------------------------
# Evidence Truth Rule: assembly-time refusals (never a placeholder purpose/
# citation, never a zero-step "recipe")
# ---------------------------------------------------------------------------

def test_missing_purpose_refused():
    raw = _bringup_recipe_dict()
    del raw["purpose"]
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_dict(raw)


def test_empty_purpose_refused():
    raw = _bringup_recipe_dict()
    raw["purpose"] = ""
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_dict(raw)


def test_missing_citation_refused():
    raw = _bringup_recipe_dict()
    del raw["citation"]
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_dict(raw)


def test_empty_citation_refused():
    raw = _bringup_recipe_dict()
    raw["citation"] = ""
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_dict(raw)


def test_zero_steps_refused():
    raw = _bringup_recipe_dict()
    raw["steps"] = []
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_dict(raw)


def test_missing_recipe_id_refused():
    raw = _bringup_recipe_dict()
    del raw["recipe_id"]
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_dict(raw)


# ---------------------------------------------------------------------------
# assembly from a real ProgrammingSequenceIR slice -- the "higher-level
# artifact over per-sequence facts" operation
# ---------------------------------------------------------------------------

def test_slice_recipe_reuses_real_steps_from_source_sequence():
    ir = _ir()
    recipe = urc.usage_recipe_from_sequence_slice(
        ir, "configure_only", "Program the PHY/link configuration registers only.",
        "programming_guide.md section 4.3", step_indices=[1, 2])
    assert recipe.source_sequence_name == "usb3_link_bringup"
    assert [s.register for s in recipe.steps] == ["phy_cfg", "link_cfg"]
    # the SAME step objects the source sequence carries, not copies with a
    # parallel shape
    assert recipe.steps[0] is ir.steps[1]
    assert recipe.steps[1] is ir.steps[2]


def test_slice_recipe_from_valid_sequence_validates_order_valid():
    # link_status (WAIT + VERIFY-read) carries no depends_on chain, so this
    # slice is clean under both the phase check AND the dependency check.
    ir = _ir()
    recipe = urc.usage_recipe_from_sequence_slice(
        ir, "poll_link_status", "Wait for and read the link status register.",
        "programming_guide.md section 4.5", step_indices=[4, 5])
    report = urc.validate_recipe_ordering(recipe, _facts())
    assert report["status"] == psir.STATUS_ORDER_VALID
    assert report["findings"] == []


def test_slice_recipe_can_honestly_surface_a_broken_dependency_chain():
    # Slicing OUT of dependency context is a real, disclosed limitation: the
    # phase-monotonicity property survives any order-preserving subsequence,
    # but a depends_on chain does not -- phy_cfg's own real depends_on=[clk_en]
    # fires DEPENDENCY_NOT_YET_SATISFIED honestly when clk_en's own write step
    # is left out of the slice, rather than silently reporting clean.
    ir = _ir()
    recipe = urc.usage_recipe_from_sequence_slice(
        ir, "configure_only", "Program the PHY/link configuration registers only.",
        "programming_guide.md section 4.3", step_indices=[1, 2])
    report = urc.validate_recipe_ordering(recipe, _facts())
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_DEPENDENCY_NOT_YET_SATISFIED in codes


def test_slice_non_ascending_indices_refused():
    ir = _ir()
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_sequence_slice(
            ir, "bad", "purpose", "citation", step_indices=[3, 1])


def test_slice_duplicate_index_refused():
    ir = _ir()
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_sequence_slice(
            ir, "bad", "purpose", "citation", step_indices=[1, 1, 2])


def test_slice_unknown_index_refused():
    ir = _ir()
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_sequence_slice(
            ir, "bad", "purpose", "citation", step_indices=[1, 99])


def test_slice_empty_indices_refused():
    ir = _ir()
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_sequence_slice(ir, "bad", "purpose", "citation", step_indices=[])


def test_slice_missing_citation_refused():
    ir = _ir()
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_from_sequence_slice(ir, "bad", "purpose", "", step_indices=[1])


# ---------------------------------------------------------------------------
# validate_recipe_ordering: pure delegation to programming_sequence_ir.py --
# including the honest-absence contract flowing through unchanged
# ---------------------------------------------------------------------------

def test_clean_recipe_validates_order_valid():
    recipe = urc.usage_recipe_from_dict(_bringup_recipe_dict())
    report = urc.validate_recipe_ordering(recipe, _facts())
    assert report["status"] == psir.STATUS_ORDER_VALID
    assert report["recipe_id"] == "bring_up_link"
    assert report["purpose"] == recipe.purpose
    assert report["citation"] == recipe.citation


def test_recipe_ordering_no_facts_reports_not_available_never_fabricated_valid():
    """The core Evidence Truth Rule negative control for this module: absent
    register facts must NEVER be silently upgraded into a fabricated
    ORDER_VALID just because the caller assembled a documented recipe."""
    recipe = urc.usage_recipe_from_dict(_bringup_recipe_dict())
    report = urc.validate_recipe_ordering(recipe, None)
    assert report["status"] == psir.STATUS_NOT_AVAILABLE
    assert report["status"] != psir.STATUS_ORDER_VALID
    assert "reason" in report and report["reason"]


def test_broken_recipe_ordering_reported_invalid_with_real_finding():
    raw = _bringup_recipe_dict()
    raw["steps"][5] = {"index": 5, "phase": "VERIFY", "action": "write",
                        "register": "link_status", "value": "0x1"}  # RO register
    recipe = urc.usage_recipe_from_dict(raw)
    report = urc.validate_recipe_ordering(recipe, _facts())
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_ACCESS_TYPE_MISMATCH in codes


# ---------------------------------------------------------------------------
# catalog: build, lookup, cross-reference, listing report
# ---------------------------------------------------------------------------

def test_catalog_build_and_lookup():
    recipes = urc.usage_recipe_catalog_from_dicts(
        [_bringup_recipe_dict(), _teardown_recipe_dict()])
    cat = urc.UsageRecipeCatalog.build(recipes)
    assert cat.recipe_count == 2
    assert cat.recipe_ids == ["bring_up_link", "reset_link"]
    assert cat.get("bring_up_link") is not None
    assert cat.get("does_not_exist") is None


def test_catalog_duplicate_recipe_id_refused():
    with pytest.raises(urc.UsageRecipeError):
        urc.usage_recipe_catalog_from_dicts(
            [_bringup_recipe_dict(recipe_id="dup"), _teardown_recipe_dict(recipe_id="dup")])


def test_recipes_touching_register():
    recipes = urc.usage_recipe_catalog_from_dicts(
        [_bringup_recipe_dict(), _teardown_recipe_dict()])
    cat = urc.UsageRecipeCatalog.build(recipes)
    assert cat.recipes_touching_register("soft_reset") == ["bring_up_link", "reset_link"]
    assert cat.recipes_touching_register("phy_cfg") == ["bring_up_link"]
    assert cat.recipes_touching_register("nonexistent_register") == []


def test_catalog_report_lists_real_metadata():
    recipes = urc.usage_recipe_catalog_from_dicts([_bringup_recipe_dict()])
    cat = urc.UsageRecipeCatalog.build(recipes)
    report = cat.to_catalog_report()
    assert report["status"] == urc.STATUS_CATALOG_AVAILABLE
    assert report["recipe_count"] == 1
    entry = report["recipes"][0]
    assert entry["recipe_id"] == "bring_up_link"
    assert entry["step_count"] == 7
    assert "CONFIGURE" in entry["phases_used"]
    assert "phy_cfg" in entry["registers_touched"]


def test_empty_catalog_report_is_honest_catalog_empty():
    cat = urc.UsageRecipeCatalog.build([])
    report = cat.to_catalog_report()
    assert report["status"] == urc.STATUS_CATALOG_EMPTY
    assert report["recipe_count"] == 0
    assert "reason" in report and report["reason"]


# ---------------------------------------------------------------------------
# catalog-wide worst-wins ordering rollup (rule 3: worst-wins composite gate)
# ---------------------------------------------------------------------------

def test_rollup_all_valid_when_every_recipe_valid():
    status = urc._rollup_catalog_status(
        [psir.STATUS_ORDER_VALID, psir.STATUS_ORDER_VALID, psir.STATUS_ORDER_VALID])
    assert status == urc.STATUS_RECIPE_CATALOG_ALL_VALID


def test_rollup_worst_wins_single_invalid_fails_whole_catalog():
    """A single ORDER_INVALID recipe must fail the whole rollup even though
    two other recipes are clean -- never averaged, never a majority pass."""
    status = urc._rollup_catalog_status(
        [psir.STATUS_ORDER_VALID, psir.STATUS_ORDER_INVALID, psir.STATUS_ORDER_VALID])
    assert status == urc.STATUS_RECIPE_CATALOG_ORDER_INVALID


def test_rollup_worst_wins_incomplete_evidence_over_partial_valid():
    """A single NOT_AVAILABLE among otherwise-valid recipes must still block
    an honest ALL_VALID claim, and INVALID still outranks it when both are
    present."""
    status = urc._rollup_catalog_status(
        [psir.STATUS_ORDER_VALID, psir.STATUS_NOT_AVAILABLE])
    assert status == urc.STATUS_RECIPE_CATALOG_INCOMPLETE_EVIDENCE

    status2 = urc._rollup_catalog_status(
        [psir.STATUS_ORDER_INVALID, psir.STATUS_NOT_AVAILABLE, psir.STATUS_ORDER_VALID])
    assert status2 == urc.STATUS_RECIPE_CATALOG_ORDER_INVALID


def test_rollup_empty_is_honest_catalog_empty_not_vacuous_valid():
    assert urc._rollup_catalog_status([]) == urc.STATUS_RECIPE_CATALOG_EMPTY


def test_validate_catalog_ordering_integration_worst_wins():
    good = _bringup_recipe_dict()
    bad = _teardown_recipe_dict()
    bad["steps"] = [
        {"index": 0, "phase": "VERIFY", "action": "write",
         "register": "link_status", "value": "0x1"},  # RO -> ACCESS_TYPE_MISMATCH
    ]
    recipes = urc.usage_recipe_catalog_from_dicts([good, bad])
    cat = urc.UsageRecipeCatalog.build(recipes)
    report = urc.validate_catalog_ordering(cat, _facts())
    assert report["status"] == urc.STATUS_RECIPE_CATALOG_ORDER_INVALID
    assert report["per_recipe"]["bring_up_link"]["status"] == psir.STATUS_ORDER_VALID
    assert report["per_recipe"]["reset_link"]["status"] == psir.STATUS_ORDER_INVALID


def test_validate_catalog_ordering_no_facts_is_incomplete_evidence_not_fabricated_valid():
    recipes = urc.usage_recipe_catalog_from_dicts([_bringup_recipe_dict(), _teardown_recipe_dict()])
    cat = urc.UsageRecipeCatalog.build(recipes)
    report = urc.validate_catalog_ordering(cat, None)
    assert report["status"] == urc.STATUS_RECIPE_CATALOG_INCOMPLETE_EVIDENCE
    assert report["status"] != urc.STATUS_RECIPE_CATALOG_ALL_VALID


# ---------------------------------------------------------------------------
# CLI: real subprocess, real files
# ---------------------------------------------------------------------------

def _run_cli(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.usage_recipe_catalog"] + args,
        cwd=cwd, capture_output=True, text=True,
    )


def _repo_root():
    return Path(__file__).resolve().parents[1]


def test_cli_catalog_exit_0(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    recipes_path.write_text(json.dumps([_bringup_recipe_dict(), _teardown_recipe_dict()]),
                             encoding="utf-8")
    result = _run_cli(["catalog", "--recipes", str(recipes_path), "--json"], cwd=str(_repo_root()))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "CATALOG_AVAILABLE"
    assert report["recipe_count"] == 2


def test_cli_catalog_malformed_input_exit_2(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    bad = _bringup_recipe_dict()
    del bad["citation"]
    recipes_path.write_text(json.dumps([bad]), encoding="utf-8")
    result = _run_cli(["catalog", "--recipes", str(recipes_path), "--json"], cwd=str(_repo_root()))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "UsageRecipeError" in result.stdout


def test_cli_validate_single_recipe_pass_exit_0(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    facts_path = tmp_path / "facts.json"
    recipes_path.write_text(json.dumps([_bringup_recipe_dict()]), encoding="utf-8")
    facts_path.write_text(json.dumps(_clean_facts()), encoding="utf-8")
    result = _run_cli(
        ["validate", "--recipes", str(recipes_path), "--facts", str(facts_path),
         "--recipe-id", "bring_up_link", "--json"], cwd=str(_repo_root()))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ORDER_VALID"
    assert report["recipe_id"] == "bring_up_link"


def test_cli_validate_unknown_recipe_id_exit_2(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    recipes_path.write_text(json.dumps([_bringup_recipe_dict()]), encoding="utf-8")
    result = _run_cli(
        ["validate", "--recipes", str(recipes_path), "--recipe-id", "ghost", "--json"],
        cwd=str(_repo_root()))
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "RECIPE_NOT_FOUND"


def test_cli_validate_whole_catalog_worst_wins_exit_1(tmp_path):
    good = _bringup_recipe_dict()
    bad = _teardown_recipe_dict()
    bad["steps"] = [
        {"index": 0, "phase": "VERIFY", "action": "write",
         "register": "link_status", "value": "0x1"},
    ]
    recipes_path = tmp_path / "recipes.json"
    facts_path = tmp_path / "facts.json"
    recipes_path.write_text(json.dumps([good, bad]), encoding="utf-8")
    facts_path.write_text(json.dumps(_clean_facts()), encoding="utf-8")
    result = _run_cli(
        ["validate", "--recipes", str(recipes_path), "--facts", str(facts_path), "--json"],
        cwd=str(_repo_root()))
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "RECIPE_CATALOG_ORDER_INVALID"


def test_cli_validate_no_facts_not_available_exit_2(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    recipes_path.write_text(json.dumps([_bringup_recipe_dict()]), encoding="utf-8")
    result = _run_cli(
        ["validate", "--recipes", str(recipes_path), "--recipe-id", "bring_up_link", "--json"],
        cwd=str(_repo_root()))
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# vocabulary disjointness
# ---------------------------------------------------------------------------

def test_vocabulary_disjoint_from_models_status():
    urc.assert_no_verification_verdict_vocabulary()  # must not raise
