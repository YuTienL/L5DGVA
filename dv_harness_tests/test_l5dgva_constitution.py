"""Real tests for dv_harness/constitution_gate.py -- the Article 0
anti-drift enforcement (see docs/architecture/L5DGVA_CONSTITUTION.md and
CLAUDE.md's own Article 0 section).

No mocking: every test reads the real files on disk in this checkout.
"""
from pathlib import Path

import pytest

from dv_harness import constitution_gate as cg


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_constitution_document_exists_at_the_canonical_path():
    doc = _repo_root() / cg.CONSTITUTION_DOC_PATH
    assert doc.is_file()


def test_constitution_document_contains_article_0_and_all_five_dimensions():
    text = (_repo_root() / cg.CONSTITUTION_DOC_PATH).read_text(encoding="utf-8")
    assert "Article 0" in text
    for dim in cg.CONSTITUTIONAL_DIMENSIONS:
        assert dim in text, "missing constitutional dimension: %s" % dim


def test_constitution_document_contains_the_anti_drift_rule():
    text = (_repo_root() / cg.CONSTITUTION_DOC_PATH).read_text(encoding="utf-8")
    assert "ARCHITECTURE_CONFLICT" in text
    assert "Anti-Drift Rule" in text


def test_claude_md_carries_the_article_0_pointer():
    text = (_repo_root() / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Article 0" in text
    assert cg.CONSTITUTION_DOC_PATH in text


def test_claude_md_article_0_section_precedes_core_operating_rules():
    """Article 0 must sit above ordinary rules -- checked by real
    position, not just presence."""
    text = (_repo_root() / "CLAUDE.md").read_text(encoding="utf-8")
    article_0_pos = text.index("Article 0")
    core_rules_pos = text.index("Core Operating Rules")
    assert article_0_pos < core_rules_pos


def test_check_constitution_intact_passes_on_the_real_repo():
    result = cg.check_constitution_intact(_repo_root())
    assert result.status == "PASS", result.reasons


def test_check_constitution_intact_fails_when_constitution_doc_is_missing(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(
        "# X\n## Article 0\nsee docs/architecture/L5DGVA_CONSTITUTION.md\n",
        encoding="utf-8",
    )
    result = cg.check_constitution_intact(tmp_path)
    assert result.status == "FAIL"
    assert any("constitution" in r.lower() for r in result.reasons)


def test_check_constitution_intact_fails_when_claude_md_pointer_is_missing(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# X\nno pointer here\n", encoding="utf-8")
    doc_dir = tmp_path / "docs" / "architecture"
    doc_dir.mkdir(parents=True)
    (doc_dir / "L5DGVA_CONSTITUTION.md").write_text(
        "# Constitution\n## Article 0\n" + "\n".join(cg.CONSTITUTIONAL_DIMENSIONS)
        + "\nAnti-Drift Rule ARCHITECTURE_CONFLICT\n",
        encoding="utf-8",
    )
    result = cg.check_constitution_intact(tmp_path)
    assert result.status == "FAIL"
    assert any("claude.md" in r.lower() or "pointer" in r.lower() for r in result.reasons)


def test_check_constitution_intact_fails_when_a_dimension_is_silently_removed(tmp_path):
    doc_dir = tmp_path / "docs" / "architecture"
    doc_dir.mkdir(parents=True)
    # Drop one of the five dimensions -- simulates a future silent weakening.
    remaining = [d for d in cg.CONSTITUTIONAL_DIMENSIONS if d != "EVIDENCE_GROUNDED"]
    (doc_dir / "L5DGVA_CONSTITUTION.md").write_text(
        "# Constitution\n## Article 0\n" + "\n".join(remaining)
        + "\nAnti-Drift Rule ARCHITECTURE_CONFLICT\n",
        encoding="utf-8",
    )
    (tmp_path / "CLAUDE.md").write_text(
        "# X\n## Article 0\nsee docs/architecture/L5DGVA_CONSTITUTION.md\n## Core Operating Rules\n",
        encoding="utf-8",
    )
    result = cg.check_constitution_intact(tmp_path)
    assert result.status == "FAIL"
    assert any("EVIDENCE_GROUNDED" in r for r in result.reasons)


def test_final_constitutional_compliance_is_not_yet_pass_status_is_a_distinct_value():
    """L5DGVA_CONSTITUTIONAL_COMPLIANCE is a final-product-only gate --
    intact Article 0 text alone must not be conflated with full
    compliance (which additionally requires both continuous-learning
    loops OPERATIONAL, per the constitution document itself)."""
    assert cg.FINAL_COMPLIANCE_STATUS_INTERMEDIATE != "PASS"


# --- M8 Cohort 5 (GAP-M8-008): evaluate_final_compliance() -----------------

def _constitution_doc_text() -> str:
    return (_repo_root() / cg.CONSTITUTION_DOC_PATH).read_text(encoding="utf-8")


def test_final_acceptance_sub_criteria_match_the_constitution_document():
    # The 13 names are re-derived from the real doc, not hardcoded twice --
    # a drift guard, not a duplicate of the doc's own content.
    text = _constitution_doc_text()
    assert len(cg.FINAL_ACCEPTANCE_SUB_CRITERIA) == 13
    for name in cg.FINAL_ACCEPTANCE_SUB_CRITERIA:
        assert name in text, f"{name} not found in {cg.CONSTITUTION_DOC_PATH}"


def test_evaluate_final_compliance_returns_a_real_composite_on_the_real_repo():
    result = cg.evaluate_final_compliance(_repo_root())
    assert [s.name for s in result.sub_criteria] == list(cg.FINAL_ACCEPTANCE_SUB_CRITERIA)
    for s in result.sub_criteria:
        assert s.status in cg.SUB_CRITERION_STATUSES, (s.name, s.status)
        assert s.evidence.strip(), f"{s.name} has no evidence string"
    # Migration-Wave Scoping: this wave's real verdict is honestly
    # incomplete -- never PASS, and never silently upgraded to look
    # further along than the real evidence supports.
    assert result.overall_status != "PASS"
    assert result.overall_status == cg.combine_sub_criterion_statuses(result.sub_criteria)


def test_evaluate_final_compliance_never_raises_on_a_bare_project(tmp_path):
    # No governance_registry.json, no .dv-harness/state.json, no golden_
    # flow_readiness-relevant files at all -- every sub-check must degrade
    # to a real FAIL/PARTIAL/NO_REAL_EVALUATOR_FOUND, never an exception.
    result = cg.evaluate_final_compliance(tmp_path)
    assert len(result.sub_criteria) == 13
    assert result.overall_status in ("FAIL", "PARTIAL")


def test_evaluate_final_compliance_undiscovered_sub_criteria_are_disclosed_not_hidden():
    # The 4 sub-criteria confirmed (by search this cohort) to have no real
    # evaluator anywhere in this codebase must say so explicitly, never
    # silently reported as FAIL (which would misrepresent "nobody built
    # this check yet" as "the check ran and found a real problem").
    result = cg.evaluate_final_compliance(_repo_root())
    by_name = {s.name: s for s in result.sub_criteria}
    for name in ("IP_END_TO_END", "SUBSYSTEM_END_TO_END", "SYSTEM_LEVEL_END_TO_END",
                 "CANONICAL_CAPABILITY_STRICT_SUPERSET"):
        assert by_name[name].status == cg.NO_REAL_EVALUATOR_FOUND, (name, by_name[name].status)


def test_evaluate_final_compliance_knowledge_promotion_reuses_real_memory_router():
    # Spot-check one PASS sub-criterion's own real evidence source, proving
    # it is not a fabricated status: memory_router really is importable
    # and really does have the 3 named real functions this program's own
    # Cohorts 1/2/4 extensively exercised.
    result = cg.evaluate_final_compliance(_repo_root())
    by_name = {s.name: s for s in result.sub_criteria}
    assert by_name["KNOWLEDGE_PROMOTION"].status == "PASS"
    assert "route_and_store" in by_name["KNOWLEDGE_PROMOTION"].evidence


def test_combine_sub_criterion_statuses_all_pass_is_pass():
    results = tuple(cg.SubCriterionResult(n, "PASS", "e") for n in cg.FINAL_ACCEPTANCE_SUB_CRITERIA)
    assert cg.combine_sub_criterion_statuses(results) == "PASS"


def test_combine_sub_criterion_statuses_one_partial_downgrades_to_partial():
    results = tuple(cg.SubCriterionResult(n, "PASS", "e") for n in cg.FINAL_ACCEPTANCE_SUB_CRITERIA[:-1])
    results += (cg.SubCriterionResult(cg.FINAL_ACCEPTANCE_SUB_CRITERIA[-1], "PARTIAL", "e"),)
    assert cg.combine_sub_criterion_statuses(results) == "PARTIAL"


def test_combine_sub_criterion_statuses_all_fail_or_no_evaluator_is_fail():
    results = (
        cg.SubCriterionResult("A", "FAIL", "e"),
        cg.SubCriterionResult("B", cg.NO_REAL_EVALUATOR_FOUND, "e"),
    )
    assert cg.combine_sub_criterion_statuses(results) == "FAIL"


def test_combine_sub_criterion_statuses_empty_is_fail():
    assert cg.combine_sub_criterion_statuses(()) == "FAIL"


def test_check_constitution_intact_still_passes_after_final_compliance_gate_added():
    # ROLLBACK_BOUNDARY (M8 Cohort 5's own frozen contract): the pre-
    # existing textual-intactness gate must remain byte-for-byte unchanged
    # and still PASS on this real repo after evaluate_final_compliance()
    # was added alongside it.
    result = cg.check_constitution_intact(_repo_root())
    assert result.status == "PASS", result.reasons


# --- Automatic invocation (GAP-M8-007) --------------------------------------

def test_constitution_check_cli_verb_is_registered():
    text = (_repo_root() / "dv_harness" / "cli.py").read_text(encoding="utf-8")
    assert '"constitution-check"' in text


def test_constitution_check_cli_verb_real_subprocess_invocation():
    import json
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "constitution-check"],
        cwd=str(_repo_root()), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["intact_status"] == "PASS"
    assert out["final_compliance"]["overall_status"] in ("PASS", "PARTIAL", "FAIL")
    assert len(out["final_compliance"]["sub_criteria"]) == 13


def test_pre_push_hook_runs_constitution_check_by_default():
    # The real, live core.hooksPath script's own default CHECKS list --
    # this is what makes GAP-M8-007 genuinely automatic, not merely
    # on-demand. A string match against the real file, not a paraphrase.
    text = (_repo_root() / "tools" / "git-hooks" / "pre-push").read_text(encoding="utf-8")
    assert 'CHECKS=${DV_HARNESS_SELF_TEST_CHECKS:-"import-sanity,self-audit,constitution"}' in text


def test_self_test_constitution_check_is_registered():
    import importlib.util
    path = _repo_root() / "tools" / "testing" / "self_test.py"
    spec = importlib.util.spec_from_file_location("self_test_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "constitution" in mod.CHECK_NAMES
    assert "constitution" in mod.CHECK_FUNCS


def test_self_test_constitution_check_real_run():
    import importlib.util
    path = _repo_root() / "tools" / "testing" / "self_test.py"
    spec = importlib.util.spec_from_file_location("self_test_probe2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = mod.run_constitution_check()
    assert result.name == "constitution"
    assert result.ok is True
    assert result.detail["intact_status"] == "PASS"
