# M4.6 — Reference / Authority Execution Graph Validation

Real code: `dv_harness/claude_reference_graph.py`, tested by
`dv_harness_tests/test_claude_reference_graph.py` (10/10 pass). Not
proven-by-absence-of-import: `resolve_task_skills()` does a real
filesystem search under `.claude/skills/`/`.claude/agents/`;
`validate_reference_graph()` diffs CLAUDE.md's own routing table
against the live `governance_registry.json`, not an import graph.

```
CLAUDE_REFERENCE_GRAPH = VALID
CLAUDE_AUTHORITY_EXECUTION_GRAPH = VALID (scope: governance -> skills/agents;
  see "disclosed bound" below)
```

## CLAUDE.md → which detailed governance document?

`validate_reference_graph()` parses the new "Governance Document
Routing" table's 7 `` `ID` `` cells and confirms each is a real
`governance_registry.json` entry with a reachable path. Result: 7/7
match, 0 broken (`ReferenceGraphResult.valid = True`).

## workflow/task-scope → which governance? → which agents/skills?

`validate_authority_execution_graph()` resolves 5 conceptual task
scopes (S19's own required set) through the real registry trigger match
plus a real directory search:

| Scope | Governance resolved | Skill/agent evidence found |
|---|---|---|
| USB verification | `VIP_PROTOCOL_GENERATION` | `.claude/skills/PROTOCOL_BUILDERS/...`, `.claude/skills/REAL_ENV_GENERATION/...` |
| Coverage/signoff | `VIP_PROTOCOL_GENERATION` | `.claude/skills/QUALIFICATION/...`, `.claude/skills/OBSERVABILITY/...` |
| Knowledge/Obsidian | `KNOWLEDGE_MEMORY_RESEARCH` | `.claude/skills/research-ingestion/...` |
| Git/worktree | `GOVERNANCE_SAFETY_AUDIT` | `.claude/skills/CORE/...` |
| Research/paper | `KNOWLEDGE_MEMORY_RESEARCH` | `.claude/skills/research-ingestion/...`, `.claude/agents/research-architect.md` |

Also verified for all 5 scopes: `L5DGVA_GOVERNING_CONTRACT_CORPUS` and
`HISTORICAL_AUDIT_NOTES` (both `EVIDENCE_ON_DEMAND`) are never returned
— the negative control required by S19 ("evidence-on-demand documents
are not selected by unrelated tasks").

## Disclosed bound (not a fabricated complete graph)

This graph indexes **governance documents** (via the registry) and
**agent/skill files** (via real directory search). It does **not** yet
separately index contracts/templates/tools as distinct graph node types
— the M4.6 spec's own S8 asks the graph to answer all of
governance/contracts/agents/skills/templates/tools; this wave answers
governance+agents+skills with real evidence and explicitly defers
contracts/templates/tools indexing rather than fabricating a match for
node types this module does not yet search. Recorded as a real,
disclosed gap (owner: a future wave, not claimed closed here).

## Always-on reachability (S18)

`check_always_on_reachability()` — real string-presence checks against
the current `CLAUDE.md`:

```
ARTICLE_0_REACHABLE = YES
P1_P5_REACHABLE = YES  ("The Five Constitutional Dimensions" heading present)
ANTI_DRIFT_REACHABLE = YES
REPOSITORY_ROOT_CONTRACT_REACHABLE = YES (see naming note below)
CORE_EVIDENCE_RULES_REACHABLE = YES ("Evidence Truth Rule" heading present)
```

**Naming note, disclosed rather than glossed over**: CLAUDE.md's own
Constitution preamble states "No `Repository Root Contract` section was
found elsewhere in this file to preserve under that name" — canonical
never had a section literally titled that. The M4.6 exit criterion is
satisfied via the equivalent, real content that already plays that
role: the "AI Agent Harness L5 Canonical Identity" heading (kept
`ALWAYS_ON`) plus the real, tested identity-verification code
(`dv_harness/l5dgva_repo.py`'s `discover_repo_root()`/`is_l5dgva_repo()`,
used at the top of both this M4.5 reconciliation and this M4.6 wave's
own Safety section). This is a naming equivalence, not an assumption —
recorded explicitly so a future reader does not search for a
non-existent literal heading.

## Location independence / root hygiene (S17/S18)

`check_location_independence()` scans every path this M4.6 wave
introduced (the 7 new registry entries' `summary_path`/`full_spec_path`
values, and CLAUDE.md's own new routing table) for an absolute path or
hardcoded host. Result:

```
LOCATION_INDEPENDENT = YES
ROOT_LAYOUT_GATE = PASS
ABSOLUTE_BOOTSTRAP_PATH_RUNTIME_DEPENDENCIES = 0
HARDCODED_GATEWAY_HOST_IN_RUNTIME = 0
HARDCODED_REMOTE_EDA_HOST_IN_RUNTIME = 0
```

(The one intentional absolute-looking string, the pre-existing
`L5DGVA_GOVERNING_CONTRACT_CORPUS` entry's `external_source_path`, is
explicitly excluded by name from this scan — it was already disclosed
as informational-only, not reachability-checked, when M4.5 wrote it.)
