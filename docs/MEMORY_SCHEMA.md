> See MEMORY_ARCHITECTURE.md for the system this schema belongs to.

# AI Agent Harness L5 — Memory Schema Reference

Field-level reference for every record shape the Memory system writes.
Source of truth is the code — this doc mirrors `dv_harness/memory.py` and
`dv_harness/memory_vault.py` exactly; if they ever disagree, the code
wins (Evidence Truth Rule).

## 1. MemoryStore record (all 5 tiers — `.dv-harness/memory/<level>/<memory_id>.json`)

Fields `add()` (`memory.py:185`) always fills in (via `setdefault`, so a
caller may override any of them):

| Field | Type | Default | Notes |
|---|---|---|---|
| `memory_id` | str | `MEM-<10 hex upper>` | stable identity; passing an existing one overwrites in place (the only "update" mechanism) |
| `level` | str | (set by `add()`'s `level` arg) | one of `MEMORY_LEVELS` |
| `created_at` | float (epoch) | `time.time()` | |
| `last_used_at` | float\|None | `None` | set by `mark_used()` |
| `reuse_count` | int | `0` | incremented by `mark_used()` |
| `confidence` | str | `"UNKNOWN"` | free-form in practice; `inference.CONFIDENCE_LEVELS = ["HIGH","MEDIUM","LOW"]` is the canonical vocabulary for anything gate-checked |
| `status` | str | `"ACTIVE"` | `ACTIVE`/`DEPRECATED`/`SUPERSEDED`/`RETRACTED`/`STALE` — see `MemoryGC` |
| `provenance` | any\|None | `None` | who/where a shared record came from |
| `confirmation_count` | int | `0` | incremented ONLY by `MemoryGC.confirm()` |
| `last_confirmed_at` | float\|None | `None` | set by `MemoryGC.confirm()` |

Caller-supplied fields commonly present (not enforced by `MemoryStore`
itself — enforcement is at the router/gate layer):
`kind`, `verified`, `protocol`, `scope`, `title`, `symptoms` (list),
`root_cause`, `fix`, `evidence`, `verification` (dict — see the two real
shapes below), `JOB_ID`/pattern/etc. for job-tier records, `project`,
`rtl_sha`, `tb_sha`, `vip_vendor`, `vip_version`, `simulator`.

### The two real `verification` shapes (checked by `_verification_is_gate_validated()`)

**`finding_consolidation_shape`** (`MemoryConsolidator.from_closed_finding()`):
```json
{"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"}
```
(`regression` may also be `"NOT_REQUIRED"`.)

**`re_audit_gate_shape`** (`engine.py`'s `_promote_verified_fix_knowledge()`):
```json
{
  "targeted_reproducer_passed": true, "broader_regression_passed": true,
  "new_failures_introduced": false, "target_pre_fix_result": "FAIL",
  "target_post_fix_result": "PASS", "replay_equivalent": true
}
```
No third shape is recognized — do not invent one.

## 2. Corner Case Library record (`.dv-harness/memory/corner_case_library/<ccl_id>.json`)

`CornerCaseLibrary.add()` (`memory.py:576`), a separate class/store from
the 5 tiers.

| Field | Type | Required / Default |
|---|---|---|
| `ccl_id` | str | `CCL-<10 hex upper>`, generated if absent |
| `category` | str | **required**, one of `CORNER_CASE_CATEGORIES` (`reset_power`, `concurrency`, `ordering`, `backpressure`, `resource_limit`, `cdc_timing`, `error_fault`, `recovery`, `cross_feature`, `cross_protocol`, `traffic_pattern`, `state_transition`) — raises `ValueError` otherwise |
| `risk_tier` | str | **required**, one of `P0`/`P1`/`P2`/`P3` — raises `ValueError` otherwise |
| `corner_id`, `protocol`, `description` | | caller-supplied, indexed |
| `applicability_conditions` | list | `[]` |
| `resolution` | dict | `{}` |
| `evidence` | dict | `{}` |
| `current_evidence_required` | bool | `True` on a bare `add()`; set `False` only by `CornerCaseLibraryConsolidator.from_resolved_corner_case()` — this is the real flag `gates._ccl_reuse_verified()` reads before allowing a `REUSED_CCL:<id>` citation |
| `revalidate_by` | float (epoch)\|None | `None` (no auto-expiry) |
| `provenance` | any\|None | `None` |
| `confirmation_count`, `last_confirmed_at` | int, float\|None | `0`, `None` |
| `confidence`, `status`, `created_at`, `last_used_at`, `reuse_count` | | same defaults as `MemoryStore` |

## 3. DV-Knowledge Vault note (`.dv-harness/vault/06_Agent_Memory/<Level>/<id>.md`)

A note is a YAML-frontmatter block + a fixed set of `##` body sections —
see `render_note_markdown()`/`parse_note_markdown()`.

### Frontmatter fields

`MEMORY_NOTE_REQUIRED_FIELDS` (a note missing ANY of these is written with
`schema_status: PARTIAL`, baked visibly into the note itself — never
silently marked complete):
```
id, memory_level, protocol, status, confidence, created, updated
```

`MEMORY_NOTE_OPTIONAL_FIELDS` (always emitted, as `null` when absent, so
the schema shape is always visible):
```
subsystem, category, failure, project, rtl_sha, tb_sha,
vip_vendor, vip_version, simulator, tags
```

Bookkeeping fields the adapter always adds itself (never caller-supplied):
`schema_status` (`COMPLETE`/`PARTIAL`), plus carried-through
`confirmation_count`/`last_confirmed_at` when the source record has them.
Any OTHER key on the frontmatter dict is still written, just appended
after the fixed field order — no data is ever silently dropped.

### Body sections (`MEMORY_NOTE_BODY_SECTIONS`, fixed order)

```
## Symptom
## Context
## Hypothesis
## Evidence
## Root Cause
## Fix
## Verification
## Confidence
## Reusability
## Known Limitations
## Related Knowledge
```
An empty section renders as `_Not yet documented._`. A partial
`sections_patch` on `update()` overwrites only the named section(s) —
every other section's existing content is preserved (`_body_to_sections()`).
`Related Knowledge` is where `[[WikiLink]]`-style cross-references live —
see MEMORY_OPERATIONS.md and the `memory-link` skill.

### Example rendered note

```markdown
---
id: MEM-A1B2C3D4E5
memory_level: engineering
protocol: USB
subsystem: branch_b0
category: branch_b0
failure: "scoreboard off-by-one on split transactions"
status: ACTIVE
confidence: HIGH
project: null
rtl_sha: null
tb_sha: null
vip_vendor: null
vip_version: null
simulator: null
created: "2026-09-03T10:15:00+00:00"
updated: "2026-09-03T10:15:00+00:00"
tags:
  - usb
  - branch_b0
  - engineering
  - high
schema_status: COMPLETE
confirmation_count: 1
last_confirmed_at: "2026-09-03T14:02:11+00:00"
---

## Symptom
- UVM_ERROR scoreboard mismatch on split-transaction reassembly

## Context
branch_b0

## Hypothesis
_Not captured (see Root Cause)._

## Evidence
- sim.log:1204: UVM_ERROR scoreboard mismatch

## Root Cause
scoreboard off-by-one on split transactions

## Fix
scoreboard.sv:142 -- compare against post-split expected length

## Verification
- single_sim: PASS
- regression: PASS
- reaudit: CLEAN

## Confidence
HIGH

## Reusability
Reusable

## Known Limitations
_None documented._

## Related Knowledge
_None linked yet._
```

## 4. Router destination reference (`memory_router.route_memory()`)

| Destination | Trigger (`kind`) | `verified` required |
|---|---|---|
| `REJECT` | `credential`/`password`/`token`/`secret` | n/a |
| `CLAUDE_PROJECT_MEMORY` | `project_instruction`/`coding_convention`/`workflow_rule`/`user_preference` | no |
| `BLACKBOARD` | `current_state`/`active_hypothesis`/`graph_state`/`plan_state` | no |
| `JOB_MEMORY` | `job_result`/`job_failure`/`job_rerun` | no |
| `WORKING_MEMORY` | `react_reasoning_step`, or anything unmatched | no |
| `PROJECT_MEMORY` | `project_fact`/`project_topology`/`tool_flow`/`known_issue` | **yes** |
| `ENGINEERING_MEMORY` | `root_cause`/`verified_fix`/`debug_lesson` | **yes**, plus `engineering_admission_gate()`'s evidence + confidence + reusable bar — a record clearing `verified` but failing that gate is demoted to `WORKING_MEMORY` (see MEMORY_ARCHITECTURE.md) |
| `ORGANIZATIONAL_MEMORY` | `cross_project_lesson`/`methodology`/`best_practice` | **yes**, and only reachable directly if you bypass `promote_to_organizational()` — don't; see MEMORY_ARCHITECTURE.md |
| `CORNER_CASE_LIBRARY` | `corner_case` | **yes** |

## 5. Job Memory record fields (`lsf_client._upsert_job_tier_memory_record()`)

One record per LSF job, keyed `JOB-<job_id>-TERMINAL-RECONCILE` (a stable id,
so repeat polls of the same stuck job upsert rather than duplicate). Written
on `reconcile_job()`'s CRITICAL `sim_status`→`ANALYSIS_OWED` discrepancy, and
re-upserted with better evidence by
`regression_reporter.run_reconciliation_cycle()` once a real sim.log epilogue
has been parsed.

**Always present** — every one carries a real value, so absence would itself
be misleading:

| Field | Source |
|---|---|
| `kind` | `job_failure` when `lsf_status=="EXIT"`, `uvm_fatal_count>0`, an assertion failure, a simulator crash, or `sim_status=="FAIL"`; else `job_result` |
| `job_id`, `pattern`, `lsf_status`, `terminal_signature` | `JobState` |
| `uvm_error_count`, `uvm_fatal_count` | `JobState` (real sim.log-derived counts) |
| `dv_analysis_status` | always `ANALYSIS_OWED` at this trigger |
| `dv_result` | `JobState.sim_status` — the DV verdict, deliberately separate from `lsf_status` per CLAUDE.md's "LSF DONE is not equal to DV PASS" |
| `root_cause_status`, `fix_proposal_status` | `JobState` — the spec's "fix attempt" fields; `NOT_STARTED` is itself informative |

**Present only when genuinely captured** (omitted, never written as `null` —
so a reader can tell "not captured" from "captured as null"):

| Field | Source |
|---|---|
| `command` | the exact command handed to `bsub` (`dv-harness lsf-submit`, or `register_external_job(command=…)`) |
| `runlimit_minutes` | the `bsub -W <minutes>` limit actually requested (`--runlimit-min`) — this job's real timeout budget |
| `submit_time`, `run_time` | LSF's own `bjobs -json` `SUBMIT_TIME`/`RUN_TIME`, stored verbatim as LSF's strings |
| `observed_terminal_at` | ISO-8601 UTC, when THIS harness first observed a terminal status; set once, never refreshed by later polls. Named for what it is — LSF's own finish time is not requested by this module, and calling a poll timestamp the job's end time would be dressed-up inference |
| `seed`, `fsdb_path` | first-class `JobState` fields, else extracted from `options` text when it carries a documented marker |
| `run_dir`, `sim_log`, `regression_id` | `JobState` |
| `early_kill`, `kill_reason` | only when an early kill actually fired |
| `failure_signature`, `prior_related_knowledge` | only on a real failure signal, via `memory_vault.build_failure_signature()`/`search_related_memory_for_debug()` — candidate prior evidence for the Debug Agent, never an assumed root cause |
