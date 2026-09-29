# M4.6 — Context-Selection Test Report

Real pytest run, `dv_harness_tests/test_claude_reference_graph.py`,
`10 passed in 3.51s` (no external model invocation, per S19's own
instruction — pure filesystem/registry checks against this repo).

```
dv_harness_tests/test_claude_reference_graph.py::test_validate_reference_graph_is_valid_on_the_real_repo PASSED
dv_harness_tests/test_claude_reference_graph.py::test_every_claude_md_routing_table_entry_exists_in_the_registry PASSED
dv_harness_tests/test_claude_reference_graph.py::test_article_0_p1_p5_anti_drift_and_identity_are_always_on_reachable PASSED
dv_harness_tests/test_claude_reference_graph.py::test_authority_execution_graph_resolves_usb_verification_scope PASSED
dv_harness_tests/test_claude_reference_graph.py::test_authority_execution_graph_resolves_coverage_signoff_scope PASSED
dv_harness_tests/test_claude_reference_graph.py::test_authority_execution_graph_resolves_knowledge_obsidian_scope PASSED
dv_harness_tests/test_claude_reference_graph.py::test_authority_execution_graph_resolves_git_worktree_scope PASSED
dv_harness_tests/test_claude_reference_graph.py::test_authority_execution_graph_resolves_research_paper_scope PASSED
dv_harness_tests/test_claude_reference_graph.py::test_evidence_on_demand_not_selected_by_an_unrelated_scope PASSED
dv_harness_tests/test_claude_reference_graph.py::test_location_independence_and_root_hygiene_still_hold PASSED
```

## Per-scope resolution (the 5 conceptual scopes S19 requires)

| Scope | Required governance selected | Unrelated large governance NOT selected | Real skill/agent evidence (first 3) |
|---|---|---|---|
| USB verification | `VIP_PROTOCOL_GENERATION` | `L5DGVA_GOVERNING_CONTRACT_CORPUS`, `HISTORICAL_AUDIT_NOTES` absent | `.claude/skills/PROTOCOL_BUILDERS/`, `.../amba4-soc-environment-builder/SKILL.md` |
| Coverage/signoff | `VIP_PROTOCOL_GENERATION` | same, absent | `.claude/skills/CORE/simulation-observability-policy/SKILL.md`, `.claude/skills/OBSERVABILITY/` |
| Knowledge/Obsidian | `KNOWLEDGE_MEMORY_RESEARCH` | same, absent | `.claude/skills/research-ingestion/SKILL.md` |
| Git/worktree | `GOVERNANCE_SAFETY_AUDIT` (plus `L5DGVA_CONSTITUTION`, since "governance" also matches the Constitution's own registry trigger — a true positive, not noise) | same, absent | `.claude/skills/CORE/agent-checkpoint-discipline/SKILL.md` |
| Research/paper | `KNOWLEDGE_MEMORY_RESEARCH` | same, absent | `.claude/skills/research-ingestion/SKILL.md`, `.claude/agents/research-architect.md` (present in the real `.claude/agents/` listing) |

## Article 0 / core rules remain available in every scope

`check_always_on_reachability()` is scope-independent by construction —
it reads the one, single, always-loaded `CLAUDE.md`, so Article 0/P1–P5/
Anti-Drift/repository-identity/core-evidence-rules are reachable for
every scope above by definition (they never depended on a trigger
match). Verified true after the split (`test_article_0_p1_p5_anti_drift_and_identity_are_always_on_reachable`
passes), not merely assumed to still hold.

`GOVERNANCE_DUMP = PROHIBITED` — confirmed by
`test_evidence_on_demand_not_selected_by_an_unrelated_scope`: no scope's
trigger match ever returns an `EVIDENCE_ON_DEMAND` entry.
