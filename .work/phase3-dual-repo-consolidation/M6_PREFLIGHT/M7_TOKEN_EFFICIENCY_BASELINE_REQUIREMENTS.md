# M7 Preflight -- Token Efficiency Baseline Requirements

Per this task's own explicit instruction: "Measure rather than
speculate... Do not invent token counts if the provider does not expose
them. Use proxy metrics explicitly labeled as proxies." This document
defines what a REPRODUCIBLE baseline would need, using only metrics this
environment can actually produce -- it does not itself run that baseline
(PREFLIGHT scope only).

## What is already real and measurable (reuse, confirmed this pass)

`dv_harness/stage_profile.py`/`stage_profile_report.py` (confirmed
present in canonical): real, per-stage Claude CLI adapter token telemetry
-- in/out/cache token counts sourced from the CLI adapter's own real
usage payload, not estimated. This is a genuine, non-proxy metric wherever
the adapter actually reports it.

## Metrics this environment can actually produce today

| Metric | Real or proxy | Source |
|---|---|---|
| `INPUT_CONTEXT_SIZE` (tokens) | REAL where the Claude CLI adapter reports it | `stage_profile.py`'s own usage payload |
| `PROMPT_BYTES` | REAL, trivially measurable | `len()` of the assembled prompt string before dispatch |
| `GOVERNANCE_CONTEXT_BYTES` | REAL | `governance_registry.py`'s own resolved-section byte count vs. the full `CLAUDE.md` byte count -- a real, computable ratio |
| `FILES_READ` | REAL | a real, countable fact per task (this session's own tool-call log, or a wrapped `Read`/`Grep` call counter) |
| `HANDOFF_BYTES` | REAL, once a real handoff exists (M7's own future cohort work) | `len()` of the assembled `M7_STRUCTURED_HANDOFF_CONTRACT.md`-shaped payload |
| `MODEL_INVOCATIONS` | REAL | a real, countable fact (this session alone: 4 dispatched tasks, each with its own real regression-run counts already logged) |
| `RETRY_COUNT` | REAL | already tracked informally via `LIFECYCLE_BYPASS`/`TASK_BOUNDARY_BLOCKED`-style event logging; a dedicated retry counter would be additive, not new infrastructure |
| `WALL_TIME` | REAL | already observed directly (e.g. this session's own qualification regressions: 447.91s / 438.88s, real, logged) |

**No metric here is invented.** Where the underlying provider does not
expose a true token count for a given call shape, `PROMPT_BYTES`/
`GOVERNANCE_CONTEXT_BYTES` stand in as explicitly-labeled PROXIES (bytes,
not tokens) -- never presented as a token count.

## Baseline requirement (per section 13, distinct from M14's own
Junior-DV productivity benchmark)

`M7 measures orchestration efficiency, not Junior-vs-L5DGVA
productivity` (already an established, correct distinction in
`MASTER_PROGRAM_STATUS.md`, re-confirmed here, not reopened).

A reproducible M7 baseline needs, at minimum:

1. **A fixed set of representative task shapes** (e.g. "one CAP-sized
   implementation task," "one independent-review task," "one research-
   synthesis task") -- not yet defined; a real M7 Cohort 1 deliverable,
   not invented here.
2. **The CURRENT Claude-only workflow's own real numbers** for each task
   shape, using the metrics table above -- reusing `stage_profile.py`'s
   real telemetry plus the proxy metrics, never estimated.
3. **A frozen candidate/checkpoint discipline**, matching the SAME
   freeze pattern this M6 qualification just used (a stable SHA, no
   drift during measurement) -- so a later multi-model comparison run is
   measuring the same real work, not a moving target.
4. **A published before/after methodology BEFORE any multi-model claim
   is made** -- so `TOKEN_REDUCTION_MEASURED` can honestly flip from
   `NO` to `YES` only once a real comparison exists, never asserted from
   architecture alone.

## Result

```
TOKEN_USAGE_OBSERVABILITY = PARTIAL (Claude-side telemetry real and
  confirmed present in canonical; no cross-model combination exists)
TOKEN_REDUCTION_MEASURED = NO (unchanged from the M4.5 finding --
  re-confirmed, not re-derived from scratch, since nothing that would
  change this finding was built between M4.5 and this preflight)
TOKEN_REDUCTION_EFFECT = ARCHITECTURALLY_PLAUSIBLE_BUT_NOT_MEASURED
  (same honest classification the M4.5 audit used -- no evidence this
  pass changes that)
```

This document does not itself measure anything -- it defines what a real
measurement would require, per this task's own PREFLIGHT (not
implementation) scope.
