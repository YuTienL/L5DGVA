> See START_HERE.md for the canonical entry point and current mechanism overview; this page remains accurate for its specific topic.

# Changelog — v0 (pristine baseline) → v50 (this session)

No git history exists in this package, so this file documents the diff
between `v0/` (untouched baseline) and `v50/` (this session's working
copy) as a substitute changelog. Generated 2026-08-28.

## 1. Mechanism-first pipeline extension (core engine)

`dv_harness/models.py`'s `Stage` enum grew from **24 stages** (linear:
`ENV_CHECK...SIGNOFF`) to **35 stages**, aligned to a mechanism-first
pipeline the user specified in detail across many messages:

New stages inserted: `DE_BASELINE_REPRODUCTION`, `ARCH_DISCOVERY`,
`ARCH_CALIBRATION`, `PROTOCOL_CAPABILITY`, `VERIFICATION_ARCHITECTURE`,
`COVERAGE_CLOSURE`, `SYSTEM_LEVEL`, `EXPERT_FEEDBACK_LOOP`,
`PROMOTION_READINESS`, `BUILD_DEBUG`, `INFRA_RECOVERY`.

Reordered: `COMMAND_PATTERN` moved earlier (before vPlan work, right after
`DISCOVERY`); `VPLAN` moved later (after architecture discovery/
calibration/protocol capability, not immediately after `PROJECT_MODEL`).

Files: `dv_harness/models.py`, `.dv-harness/graph/main_graph.json` (nodes +
edges rewritten to match), `dv_harness/prompts.py` (per-stage instructions
+ evidence-block formats for every new/changed stage), `dv_harness/gates.py`
(new module).

## 2. Gate wiring (dv_harness/gates.py — new file)

157 existing `tools/verification_flow/*.py` gate scripts were previously
never invoked by the executing engine. `gates.py` wires **15 stages** to
**19 gate scripts** via a `` ```dv-harness-evidence:<gate_id>``` `` fenced-block
convention the agent must emit; a stage can only be promoted from
transport-success to `Status.PASS` if its mapped gate(s) actually pass
against agent-supplied evidence (previously: any successful Claude
subprocess call = automatic PASS, regardless of DV outcome).

Stages gated: `DE_BASELINE_REPRODUCTION`, `ARCH_DISCOVERY`,
`ARCH_CALIBRATION`, `REQUIREMENTS_TRACEABILITY`, `VERIFICATION_ARCHITECTURE`,
`IMPLEMENT`, `VERIFY`, `REGRESSION_MONITOR`, `COVERAGE_CLOSURE`, `RE_AUDIT`,
`SYSTEM_LEVEL`, `EXPERT_FEEDBACK_LOOP`, `REQUIREMENT_CLOSURE`,
`PROMOTION_READINESS`, `SIGNOFF`.

Deliberately left unwired (contract not verified, to avoid guessing wrong
and blocking real evidence): `PROTOCOL_CAPABILITY` (`protocol_family_
qualification_gate`), `VERIFICATION_ARCHITECTURE`'s `observability_
sufficiency_gate`.

## 3. Fatal pre-existing bugs fixed (the CLI had never worked)

- `dv_harness/engine.py` imported `stage_profile.extract_provider_usage`,
  which didn't exist → `ImportError` on every invocation. Added the
  function to `dv_harness/stage_profile.py`.
- `engine.py` called `StageExecutionProfiler.add_agent_run()` with keyword
  args that didn't match its real signature → would have raised
  `TypeError` on the first real stage run. Fixed the call site.
- Bare `pytest` at repo root crashed with an `INTERNALERROR`:
  `tools/verification_flow/test_*.py` are standalone argparse CLI scripts,
  not pytest tests, but matched pytest's default `test_*.py` discovery
  glob. Added `[tool.pytest.ini_options] testpaths = ["dv_harness_tests"]`
  to `pyproject.toml`; created `dv_harness_tests/` (new directory, 14
  tests, all passing).
- `gates.py::run_gate()` originally checked `detail.get("status")=="PASS"`
  for success, but some gates report success under a different status
  string (`mechanism_readiness_gate` → `READY_FOR_TEST_GENERATION`,
  `execution_evidence_gate` → `READY_FOR_CLOSURE`) — both always failed.
  Fixed to rely on `returncode==0` (every gate script's only reliable
  success signal).

## 4. Memory system (dv_harness/memory.py, memory_router.py)

- `memory_router.py::route_memory()` existed but was **never called**
  anywhere (`memory_cli.py` and `MemoryConsolidator` both bypassed it with
  hardcoded storage levels). Added `route_and_store()` as the real entry
  point: routes a "new knowledge" record to `MemoryStore` (job/project/
  engineering/organizational), the `Blackboard`, Claude's own project
  memory (surfaced as an action, not written directly), or rejects
  credential-like records outright.
- `MemoryRetriever.search()` was missing a "Recency" ranking factor the
  user explicitly named alongside Context/Protocol/Symptom/Evidence
  Strength. Added exponential recency decay (~90-day half-life). Also
  fixed `MemoryStore.add()`, which wrote `last_used_at` to the search
  index but never `created_at` — recency scoring was silently a no-op
  until this was added.

## 5. LSF regression (dv_harness/lsf_client.py — new file)

No code anywhere called `bsub`/`bjobs`/`bkill`; `.dv-harness/lsf/jobs/`
held only a README. New module: `JobState`/`Discrepancy` dataclasses
matching `job_state_schema.json` field-for-field, `bsub_submit`/
`bjobs_query`/`bjobs_query_many`/`bkill_job` (argv-only subprocess calls,
`LsfUnavailableError` on missing binaries), `reconcile_job()` (live `bjobs`
is authoritative for `lsf_status`, but a live DONE/EXIT never auto-promotes
`sim_status` — flagged `ANALYSIS_OWED` instead, operationalizing "LSF DONE
!= DV PASS"), `reconcile_batch()`.

`job_state_schema.json` gained a `regression_id` field (previously absent
everywhere); `regression_reporter.py` now displays it in the snapshot
header when present.

## 6. Dashboard (dv_harness/dashboard.py)

Previously showed only a flat JSON summary + bare stage list. Added
`/api/graph` (all 35 stages + status, derived from real `state.json`,
not mock data) and `/api/lsf` (real job-count aggregation from
`.dv-harness/lsf/jobs/*.json`). Frontend redone with status tiles,
LSF tiles, findings tiles, and a graph view with ✓/✗/▶/○ icons and a
"you are here" highlight. Deliberately does **not** show a fabricated
"confidence" number — no such single tracked field exists in
`HarnessState`, and inventing one would contradict the project's own
Evidence Truth principle.

Also fixed in `stage_profile_report.py`: the Tokens column always printed
`N/A` (checked a `token_usage_available` flag that was never written
anywhere); now checks the value itself. `stage_profile.py::all_stages()`
sorted by random UUID filename instead of `start_time_epoch` — fixed to
chronological order. Report reformatted to Input/Output/Total columns +
a `TOTAL WORKFLOW` row.

## 7. Graph routing / signoff policy (dv_harness/policy.py, engine.py)

- `next_stage()` was purely linear; added `graph_next()`, which actually
  consults `main_graph.json` edges (so "Graph is the workflow authority,"
  CLAUDE.md's first core rule, is now true in code) — FAIL now routes to
  `FAILURE_RECOVERY`/`BUILD_DEBUG`/`INFRA_RECOVERY` per real graph edges
  instead of just retrying-then-giving-up.
- `can_signoff()` now returns a `redirect_stage`: a Git-SHA mismatch or
  open findings at signoff time auto-redirects to `SERVER_SYNC` /
  `IMPLEMENT` (not a human decision) rather than just BLOCKING; a
  second-pass-audit gap still BLOCKS for a human.
- `BUILD` and `REGRESSION_MONITOR` failures now triage through
  `BUILD_DEBUG` / `INFRA_RECOVERY` first (cheap-fix-or-escalate) instead
  of jumping straight into full `FAILURE_RECOVERY` RCA.

## 8. Human Control Plane vocabulary (.claude/agents/dv-lead.md)

Added `REVIEW`/`CORRECT`/`REPLAN`/`CONSTRAINT` to the honored verb list
(previously only `STATUS/WHY/EVIDENCE/PAUSE/RESUME/REDIRECT/APPROVE/
REJECT/STOP/TAKEOVER`).

## 9. Directory scaffolding (new, empty except `.gitkeep`)

- `project_input/00_project` … `10_checker` — canonical five(+)-source
  intake layout the user specified (spec/DUT/register/protocol-standard/
  VIP/reference-UVM/existing-tests/command.txt/system-level/existing
  verification IP).
- `generated/00_intake` … `13_reports` — canonical output layout,
  replacing an earlier flat 23-folder scaffold the user later superseded.

## 10. Documentation (additive only — no file bodies rewritten or deleted)

32 root `.md` files got prepended banners: 4 canonical files
(`START_HERE.md`, `SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md`,
`FINAL_PACKAGE_INDEX.md`, `VERIFICATION_ARCHITECTURE_MECHANISM_FIRST.md`)
cross-link each other; 17 legacy/edition files marked superseded; 9
overlapping quick-start docs point to `CREATE_ENVIRONMENT.md`.
`examples/NOTICE_SCAFFOLDING_ONLY.md` and
`generated/NOTICE_SCAFFOLDING_ONLY.md` (new) state plainly that neither
directory contains real simulation/DUT/signoff evidence.

## Explicitly out of scope this session (identified, not touched)

Four separate subsystems with their own existing scaffolding were
identified and deliberately left alone: environment generation
(`CREATE_ENVIRONMENT.md`, `dv_harness/uvm_generator/`, `.dv-harness/
builder/`, `.dv-harness/environment-router/`), the `command.txt` catalog
reorganization tool (`tools/command_catalog/`), new-protocol plugin
onboarding (`.dv-harness/plugins/`), and Remote Control (a Claude Code
platform feature, not something this harness implements).

## Known open items

- No real DUT has been run end-to-end through the engine yet — all
  verification so far is unit-level (`pytest`, direct gate smoke tests,
  a real (non-mocked) local HTTP dashboard server). A live `claude -p`
  subprocess call through a full stage has never been exercised.
- `PROTOCOL_CAPABILITY` and part of `VERIFICATION_ARCHITECTURE`
  (`observability_sufficiency_gate`) remain gate-unwired pending contract
  verification.
- Blackboard topic naming stayed flat (e.g. `findings`, `git_state`)
  rather than adopting a `workflow/`, `jobs/<id>`, `approvals` nested
  namespace the user sketched once — `Blackboard` already supports
  slash-addressed topics, so this is a pure rename if wanted later.
