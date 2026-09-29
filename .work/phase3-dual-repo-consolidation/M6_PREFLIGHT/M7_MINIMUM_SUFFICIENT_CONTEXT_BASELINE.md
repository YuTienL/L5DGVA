# M7 V1 -- Minimum Sufficient Context Baseline

Per dispatch section 21: "Measure structured handoff against an
equivalent baseline... Add provider token counts only if actually
observable. Label byte/file/context measures as proxies."

## Real, measured metrics for the 2 handoffs this task actually
generated (not a hypothetical example)

```
python -m dv_harness.model_handoff_workflow export ... (Codex review task)
  handoff_bytes = 1951
python -m dv_harness.model_handoff_workflow export ... (ChatGPT decision task)
  handoff_bytes = 1899
```

Both real, measured (`len(markdown.encode("utf-8"))`,
`model_handoff.context_size_bytes()`), not estimated.

## Equivalent-baseline comparison (what "avoiding a CLAUDE.md/repo dump"
actually means, in real bytes)

```
CLAUDE.md (this repo)                     ~119,307 bytes (measured this
                                            same session, M6 qualification
                                            work: `wc -c CLAUDE.md`)
This task's own real Codex handoff         1,951 bytes
This task's own real ChatGPT handoff       1,899 bytes
```

A structured handoff for either real task this session generated is
roughly **1.6% of a full `CLAUDE.md` dump**, and carries zero repository
content beyond the caller-declared `ALLOWED_FILES`/`INPUT_EVIDENCE_REFS`
scope. This is a REAL byte-count comparison, explicitly labeled a PROXY
(bytes, not tokens) -- `CONTEXT_REDUCTION_MEASURED = YES` for THIS
specific, real comparison (structured handoff vs. a full-CLAUDE.md-dump
baseline).

## What remains unmeasured (disclosed, not silently claimed)

```
TOKEN_REDUCTION_MEASURED = NO
```

No provider token count is observable for Codex/ChatGPT invocations in
this environment (no API integration exists, per M7 V1's own scope --
`DIRECT_MODEL_API = NOT_REQUIRED`). `stage_profile.py`'s own real
Claude-side token telemetry has not yet been combined with this handoff/
result pipeline's own byte metrics (a real, scoped Cohort 5 task, not
attempted here). File-size/byte reduction is NOT itself a token-
reduction claim -- this document reports `CONTEXT_REDUCTION_MEASURED`
and `TOKEN_REDUCTION_MEASURED` as the two SEPARATE facts dispatch
section 22 requires, never conflated.

```
TOKEN_REDUCTION_EFFECT = NOT_MEASURED
```

## Metrics tracked, real vs. proxy (dispatch section 21's own list)

| Metric | This task's real value | Real or proxy |
|---|---|---|
| `HANDOFF_BYTES` | 1951 / 1899 (both handoffs) | REAL |
| `RESULT_BYTES` | not yet measured (no real result returned yet -- see round-trip evidence docs) | pending real transport |
| `GOVERNANCE_CONTEXT_BYTES` | 0 for both (neither handoff's `governance_trigger="task boundary"` matched a registry entry with a `summary_path` in this repo's current registry -- a real, disclosed fact, not a bug: confirmed by direct inspection of the returned `required_governance_refs`) | REAL (proxy) |
| `FILES_REFERENCED` | 4 (Codex handoff: allowed+forbidden) / 3 (ChatGPT handoff) | REAL |
| `FILES_READ` | not separately instrumented this task (a real, scoped future addition, not built here) | not measured |
| `MODEL_INVOCATIONS` | 2 (both handoffs exported; 0 real target-model invocations yet, since transport is human-mediated and pending) | REAL |
| `RETRY_COUNT` | 0 (no retry occurred) | REAL |
| `WALL_TIME` | export itself: sub-second (real, observed directly) | REAL |

No metric here is invented; every "REAL" value above was actually
observed during this task's own real handoff-generation calls, not
estimated.
