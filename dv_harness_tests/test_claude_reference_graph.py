"""Real tests for dv_harness/claude_reference_graph.py -- M4.6 CLAUDE Context
Normalization's CLAUDE_REFERENCE_GRAPH / CLAUDE_AUTHORITY_EXECUTION_GRAPH
validation (S8 of the M4.6 spec).

Answers, with real evidence (no mocking):
  CLAUDE.md -> which detailed governance document?
  workflow/task-scope -> which governance? -> which agents/skills?

Bounds disclosed rather than hidden: this graph indexes governance
documents (via governance_registry.json) and agents/skills (via real
directory listings under .claude/); it does not yet separately index
contracts/templates/tools as distinct graph node types -- a real,
disclosed PARTIAL, not a fabricated complete graph.
"""
from pathlib import Path

from dv_harness import claude_reference_graph as crg


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_validate_reference_graph_is_valid_on_the_real_repo():
    result = crg.validate_reference_graph(_repo_root())
    assert result.valid, result.broken


def test_every_claude_md_routing_table_entry_exists_in_the_registry():
    """CLAUDE.md's own Governance Document Routing table lists 7 registry
    ids by name -- cross-check that every one of them is really registered,
    catching a drift between the two if CLAUDE.md's table is ever hand-edited
    without updating the registry (or vice versa)."""
    result = crg.validate_reference_graph(_repo_root())
    for expected_id in [
        "VIP_PROTOCOL_GENERATION", "GUI_DASHBOARD_WEB",
        "EXECUTION_REMOTE_REGRESSION_RCA", "INTAKE_CLARIFICATION_QUESTION",
        "KNOWLEDGE_MEMORY_RESEARCH", "GOVERNANCE_SAFETY_AUDIT",
        "HISTORICAL_AUDIT_NOTES",
    ]:
        assert expected_id in result.claude_md_table_ids, (
            f"{expected_id} missing from CLAUDE.md's routing table")
        assert expected_id in result.registry_ids, (
            f"{expected_id} in CLAUDE.md's table but not registered")


def test_article_0_p1_p5_anti_drift_and_identity_are_always_on_reachable():
    result = crg.check_always_on_reachability(_repo_root())
    assert result.article_0_reachable
    assert result.p1_p5_reachable
    assert result.anti_drift_reachable
    assert result.repository_identity_reachable
    assert result.core_evidence_rules_reachable


def test_authority_execution_graph_resolves_usb_verification_scope():
    result = crg.validate_authority_execution_graph(_repo_root())
    scope = result.scopes["usb_verification"]
    assert scope.governance_ids, "USB verification scope resolved no governance document"
    assert "VIP_PROTOCOL_GENERATION" in scope.governance_ids
    assert scope.skill_paths, "USB verification scope resolved no real skill/agent"


def test_authority_execution_graph_resolves_coverage_signoff_scope():
    result = crg.validate_authority_execution_graph(_repo_root())
    scope = result.scopes["coverage_signoff"]
    assert "VIP_PROTOCOL_GENERATION" in scope.governance_ids


def test_authority_execution_graph_resolves_knowledge_obsidian_scope():
    result = crg.validate_authority_execution_graph(_repo_root())
    scope = result.scopes["knowledge_obsidian"]
    assert "KNOWLEDGE_MEMORY_RESEARCH" in scope.governance_ids


def test_authority_execution_graph_resolves_git_worktree_scope():
    result = crg.validate_authority_execution_graph(_repo_root())
    scope = result.scopes["git_worktree"]
    assert "GOVERNANCE_SAFETY_AUDIT" in scope.governance_ids


def test_authority_execution_graph_resolves_research_paper_scope():
    result = crg.validate_authority_execution_graph(_repo_root())
    scope = result.scopes["research_paper"]
    assert "KNOWLEDGE_MEMORY_RESEARCH" in scope.governance_ids


def test_evidence_on_demand_not_selected_by_an_unrelated_scope():
    """The 25-document governing-contract corpus and the historical-audit
    notes must never surface for an ordinary VIP/coverage/knowledge task --
    only EVIDENCE_ON_DEMAND, never auto-selected by a TASK_SCOPED trigger
    match against an unrelated domain."""
    result = crg.validate_authority_execution_graph(_repo_root())
    for scope_name in ["usb_verification", "coverage_signoff", "knowledge_obsidian",
                        "git_worktree", "research_paper"]:
        ids = result.scopes[scope_name].governance_ids
        assert "L5DGVA_GOVERNING_CONTRACT_CORPUS" not in ids
        assert "HISTORICAL_AUDIT_NOTES" not in ids


def test_location_independence_and_root_hygiene_still_hold():
    result = crg.check_location_independence(_repo_root())
    assert result.location_independent
    assert result.root_layout_gate_pass
