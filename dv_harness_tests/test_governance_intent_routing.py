"""M8 Cohort 3 (CAP-M4.6-002 / GAP-M8-005): systematic behavioral
discoverability proof for governance_registry.py's TASK_SCOPED entries.

Same shape as test_research_intent_routing.py (the ONE proven precedent
GAP-M8-005's own text names): replay plausible, sentence-length task
phrasing -- never the trigger keywords themselves verbatim -- through the
real resolver, and assert the right governance document surfaces. A
single parameterized test over the real, live registry (not a fixture
copy) so this suite never silently drifts out of sync with the actual
TASK_SCOPED population -- adding a 14th registry entry with no
corresponding case here fails the population-coverage test below, loudly,
rather than leaving a newly-declared entry permanently unproven.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dv_harness import governance_registry as gr

ROOT = Path(__file__).resolve().parents[1]

# One plausible, realistic task sentence per real TASK_SCOPED registry id --
# deliberately phrased the way a person would actually ask, not copy-pasted
# from the entry's own `trigger` keyword bag (a test that just echoed the
# trigger back would prove substring containment, not behavioral
# discoverability from realistic phrasing).
PLAUSIBLE_PHRASING_BY_ID = {
    "L5DGVA_CONSTITUTION": (
        "I need the full constitutional rationale behind this architecture "
        "migration decision, beyond what CLAUDE.md's compact summary says."),
    "CANONICAL_CAPABILITY_SUPERSET_MATRIX": (
        "Is this specific named capability actually preserved and still "
        "operational anywhere in the codebase, or was it dropped?"),
    "VIP_PROTOCOL_GENERATION": (
        "I need to generate a VIP-based UVM testbench for this DUT's AMBA "
        "AXI protocol, with a vplan and a scoreboard checker."),
    "GUI_DASHBOARD_WEB": (
        "How do I add a new live status bar widget to the web dashboard's "
        "control plane UI?"),
    "EXECUTION_REMOTE_REGRESSION_RCA": (
        "The nightly regression on the remote LSF farm keeps failing -- I "
        "need to check the FSDB waveform for root cause."),
    "INTAKE_CLARIFICATION_QUESTION": (
        "During project intake I have a clarification question that needs "
        "a human answer before onboarding can continue."),
    "KNOWLEDGE_MEMORY_RESEARCH": (
        "I want to search the Obsidian knowledge vault for prior research "
        "and memory about this same experience."),
    "GOVERNANCE_SAFETY_AUDIT": (
        "I need a security audit of this multi-agent sandbox's rollback "
        "and supply-chain policy traceability."),
    "L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2": (
        "What is the M8 capability migration roadmap reconciliation "
        "status, and is this a capability island or truly production-"
        "wired?"),
    "L5DGVA_RESULT_DRIVEN_AUTONOMOUS_CLOSED_LOOP": (
        "How does the autonomous closed loop route an external model's "
        "findings into auto-remediation within its loop termination "
        "budget?"),
    "L5DGVA_HUMAN_NON_SCHEDULER_EXECUTION_CONTRACT": (
        "Can I stop this autonomous workflow right now, or do I need to "
        "wait for the human gate transport authority first?"),
    "L5DGVA_AUTOMATIC_EXTERNAL_RESULT_INGESTION": (
        "The result watcher needs to auto-import a ChatGPT review result "
        "and check its sha256 hash for duplicate suppression."),
    "L5DGVA_AUTONOMOUS_AGENT_EXECUTION_BACKEND": (
        "I need to launch a controlled Claude worker agent run with a "
        "mutation lease for preauthorized safe tool execution."),
}


def _real_task_scoped_ids():
    entries = gr.load_registry(ROOT)
    return sorted(e["id"] for e in gr.get_entries_by_policy(entries, "TASK_SCOPED"))


def test_plausible_phrasing_covers_the_entire_real_task_scoped_population():
    # Population-coverage guard (dispatch section 6's denominator
    # discipline, applied as a live drift check): every TASK_SCOPED entry
    # actually in the registry right now has a corresponding case above,
    # and vice versa -- neither a stale case for a removed entry nor an
    # unproven new one can silently exist.
    real_ids = set(_real_task_scoped_ids())
    cased_ids = set(PLAUSIBLE_PHRASING_BY_ID)
    assert real_ids == cased_ids, (
        f"missing cases: {real_ids - cased_ids}; stale cases: {cased_ids - real_ids}")


@pytest.mark.parametrize("registry_id,phrasing", sorted(PLAUSIBLE_PHRASING_BY_ID.items()))
def test_behavioral_discoverability_positive(registry_id, phrasing):
    result = gr.resolve_governance_intent(ROOT, {"task_description": phrasing})
    assert result["resolved"] is True, result
    assert result["registry_id"] == registry_id, (
        f"expected {registry_id!r}, resolved {result['registry_id']!r} for phrasing "
        f"{phrasing!r}: {result}")
    assert result["matched_keywords"], result
    assert result["evidence"].strip(), "evidence must be a non-empty explanation"


def test_unrelated_phrasing_does_not_falsely_discover_anything():
    # No false discoverability claim: genuinely unrelated text must not be
    # forced onto the nearest entry.
    result = gr.resolve_governance_intent(ROOT, {"task_description": "please order me a pizza for lunch"})
    assert result["resolved"] is False, result
    assert result["registry_id"] is None


def test_empty_task_description_is_unresolved_not_an_error():
    result = gr.resolve_governance_intent(ROOT, {"task_description": ""})
    assert result["resolved"] is False
    assert "no populated" in result["evidence"]


def test_missing_task_description_field_is_unresolved():
    result = gr.resolve_governance_intent(ROOT, {})
    assert result["resolved"] is False


def test_stopword_only_phrasing_is_unresolved():
    # "invalid/stale registration"-adjacent case: input that tokenizes to
    # nothing real (all stopwords) must not crash or fall through to a
    # spurious match.
    result = gr.resolve_governance_intent(ROOT, {"task_description": "the a an to for of and"})
    assert result["resolved"] is False
    assert "no real" in result["evidence"]


def test_resolution_is_deterministic():
    # Idempotent repeated audit: the exact same query resolves to the
    # exact same answer every time -- no hidden randomness/ordering
    # dependence in the scoring/tie-break.
    phrasing = PLAUSIBLE_PHRASING_BY_ID["VIP_PROTOCOL_GENERATION"]
    results = [gr.resolve_governance_intent(ROOT, {"task_description": phrasing}) for _ in range(5)]
    assert len(set(r["registry_id"] for r in results)) == 1
    assert all(r == results[0] for r in results)


def test_resolver_fails_closed_for_a_project_with_no_registry_at_all(tmp_path):
    # Wrong project/repo context: a root with no governance_registry.json
    # at all is a real infrastructure defect (the same class check_
    # reachability() already treats as fatal), never silently reported as
    # an ordinary "resolved: False" content non-match -- the one
    # intentional divergence from resolve_research_intent()'s blanket
    # never-raises contract, disclosed in resolve_governance_intent()'s
    # own docstring.
    with pytest.raises(Exception):
        gr.resolve_governance_intent(tmp_path, {"task_description": "anything at all"})


def test_resolver_scoped_to_the_queried_root_not_the_real_repo(tmp_path):
    # A second, isolated project root with its OWN minimal registry (only
    # one TASK_SCOPED entry, deliberately different triggers than the real
    # repo's) must resolve against ITS OWN entries, never silently fall
    # back to or leak the real repo's own 13-entry population.
    import json
    dv_dir = tmp_path / "dv_harness"
    dv_dir.mkdir(parents=True)
    (dv_dir / "governance_registry.json").write_text(json.dumps({"entries": [
        {"id": "ISOLATED_TEST_ENTRY", "load_policy": "TASK_SCOPED",
         "trigger": "widget gadget contraption", "priority": "HIGH",
         "token_class": "COMPACT", "summary_path": None, "full_spec_path": None},
    ]}), encoding="utf-8")
    result = gr.resolve_governance_intent(tmp_path, {"task_description": "I need to fix this widget"})
    assert result["resolved"] is True
    assert result["registry_id"] == "ISOLATED_TEST_ENTRY"
    # The real repo's own VIP/coverage-flavored phrasing must NOT resolve
    # against this isolated, unrelated registry.
    real_repo_phrasing = PLAUSIBLE_PHRASING_BY_ID["VIP_PROTOCOL_GENERATION"]
    cross = gr.resolve_governance_intent(tmp_path, {"task_description": real_repo_phrasing})
    assert cross["resolved"] is False, cross


def test_ambiguous_query_prefers_the_higher_overlap_entry():
    # A query that plausibly touches two entries' keyword bags resolves to
    # whichever one it overlaps MORE with, not an arbitrary/undefined pick.
    result = gr.resolve_governance_intent(
        ROOT, {"task_description": "coverage signoff waiver checker scoreboard pattern branch command"})
    assert result["resolved"] is True
    assert result["registry_id"] == "VIP_PROTOCOL_GENERATION"


def test_cli_governance_lookup_production_call_path(tmp_path):
    # Production-caller proof: the exact real `dv-harness governance-lookup`
    # CLI entry point, invoked as a real subprocess exactly as an operator
    # would run it -- not a direct Python function call.
    import json
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "governance-lookup",
         "I need to debug a stuck LSF regression job and check the FSDB waveform"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["resolved"] is True
    assert out["registry_id"] == "EXECUTION_REMOTE_REGRESSION_RCA"


def test_cli_governance_lookup_exits_nonzero_when_unresolved():
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "governance-lookup", "order", "a", "pizza"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 1
