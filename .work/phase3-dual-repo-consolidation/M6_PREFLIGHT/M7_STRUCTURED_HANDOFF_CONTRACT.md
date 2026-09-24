# M7 Preflight -- Structured Handoff Contract

Per this task's own instruction: "Avoid dumping entire CLAUDE.md or
entire repository context into every model... A handoff should carry
Minimum Sufficient Context." This document maps the required minimum
field set (section 8) onto REAL, existing Canonical contracts wherever
one already exists -- never inventing a duplicate field name for
something this project already models.

## Field-by-field reuse mapping

| Required field | Reused from (real, existing) | New? |
|---|---|---|
| `TASK_ID` | `lifecycle.json`'s own task identity + `TaskBoundary.task_id` (`task_boundary_conformance.py`) | Reuse |
| `TASK_TYPE` | `router.DEFAULT_ROUTES`' own task-type vocabulary (`analysis-route`, `implementation-route`, `build-route`, `debug-route`, `regression-route`, `review-route`, `lead-route`, `research-route`) -- already the real taxonomy `model_agent_tool_router.py` routes on | Reuse |
| `OBJECTIVE` | the real `user_goal` string `start_lifecycle()` already threads through every stage | Reuse |
| `SCOPE` | `TaskBoundary.allowed_path_prefixes`/`forbidden_paths`/`require_new_file` (CAP-ATL-004, production-connected as of `M6-TASK-BOUNDARY-PRODUCTION-001`) | Reuse |
| `ALLOWED_FILES` | `TaskBoundary.allowed_path_prefixes` | Reuse (same field, not a duplicate) |
| `FORBIDDEN_FILES` | `TaskBoundary.forbidden_paths` | Reuse |
| `INPUT_EVIDENCE_REFS` | the `evidence_refs` field pattern already real and consistent across 28 real modules (`Candidate.evidence_refs` in `intake_field_resolution.py`, and the same field name/shape reused throughout `clarification_service.py`/`question_queue.py`/`lifecycle.py`/`verification_level.py`/`engine.py`) | Reuse |
| `REQUIRED_GOVERNANCE_REFS` | `governance_registry.py` (task-scoped governance retrieval, `OPERATIONAL` per the M4.5 audit, confirmed still present) | Reuse |
| `CURRENT_HEAD` | `self.state.git_sha` (`engine.py`, already a real, populated field every stage record carries) | Reuse |
| `EXPECTED_OUTPUT_TYPE` | no exact existing field; closest real precedent is `create_environment()`'s own `environment_mode`-keyed result-dict convention | New (a small, additive enum: `code_change` / `review_findings` / `research_synthesis` / `structured_issue`) |
| `EXPECTED_OUTPUT_SCHEMA` | no exact existing field; the STRUCTURED_AGENT_HANDOFF prose schema (`CODEX_L5_DGVA_..._Review_Prompt_v19.md` lines 112-135: `Severity`/`Component`/`ObservedEvidence`/`RequiredRepair`/`Reproduction`/`ReviewerVerdict`) is the real, designed-but-never-operationalized precedent to reuse for the `review_findings` case specifically | Reuse the DESIGN (never operationalized); New for other output types |
| `VALIDATION_REQUIREMENTS` | the real `ValidationState`/`validator=` pattern (`intake_field_resolution.py`, `clarification_service.resolve_or_ask()`'s own additive `validator` parameter, built by `CAP-M5M6-VLEVEL-001`) | Reuse the PATTERN |
| `HUMAN_DECISION_REQUIRED` | `AgentResult(ok=False, raw={"blocked_by": ...})`'s own real vocabulary (`clarification`, `task_boundary`, `generation_*_unresolved`) -- the SAME boolean-ish signal a human-decision point already produces | Reuse the PATTERN |
| `RETURN_EVIDENCE` | same `evidence_refs` field pattern as `INPUT_EVIDENCE_REFS` | Reuse |
| `RESULT_STATUS` | `AgentResult.ok` + `raw["blocked_by"]`/`raw["status"]` -- the real, already-used status vocabulary every `start_lifecycle()`/`create_environment()` caller already reads | Reuse |

**Net new fields required: 2** (`EXPECTED_OUTPUT_TYPE`,
`EXPECTED_OUTPUT_SCHEMA`'s own concrete per-type schema definitions for
output types the STRUCTURED_AGENT_HANDOFF prose design does not yet
cover, e.g. `research_synthesis`). Every other field in this task's own
required minimum set already has a real, evidence-grounded home in this
project -- confirming section 7's own premise ("investigate reuse...
avoid dumping entire CLAUDE.md") is achievable without a new contract
from scratch.

## Minimum Sufficient Context, concretely

A handoff to Codex/ChatGPT for, say, an independent-review task would
carry:

```
TASK_ID + TASK_TYPE=review-route + OBJECTIVE (one sentence)
SCOPE = the exact TaskBoundary already governing the underlying change
INPUT_EVIDENCE_REFS = the exact diff/file-range under review, not the
  whole repo
REQUIRED_GOVERNANCE_REFS = only the CLAUDE.md sections governance_
  registry.py resolves as relevant to this task's own domain, never the
  whole file
EXPECTED_OUTPUT_SCHEMA = the STRUCTURED_AGENT_HANDOFF review-finding
  shape
HUMAN_DECISION_REQUIRED = whether a DE/DV authority decision gates
  accepting the finding
```

This is the concrete difference between "dump CLAUDE.md + the repo" and
"Minimum Sufficient Context" -- every field above is either already a
real, scoped, evidence-grounded value some existing Canonical mechanism
produces, or a small, disclosed net-new field.

## Independent review contamination (section 10)

Where Codex/ChatGPT is used specifically for INDEPENDENT defect
discovery, the handoff must NOT include:

- the implementation model's (Claude's) own stated conclusion/self-
  assessment of the change's correctness
- any prior reviewer's verdict
- a leading framing of what the "expected" finding is

It MUST include: the real diff/scope (`TaskBoundary`), the real
governing requirements (`REQUIRED_GOVERNANCE_REFS`), and the real
observable evidence (`INPUT_EVIDENCE_REFS`) -- exactly the same
"evidence, never a conclusion" discipline this project's own
`SCOPE_CAVEAT`/`Evidence Truth Rule` conventions already apply elsewhere
(e.g. `task_boundary_conformance.SCOPE_CAVEAT`).
