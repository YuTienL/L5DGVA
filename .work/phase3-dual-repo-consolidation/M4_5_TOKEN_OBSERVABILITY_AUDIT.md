# M4.5 — Token Usage Observability Audit

```
TOKEN_USAGE_OBSERVABILITY = PARTIAL (real Claude-only telemetry; never combined with multi-model offload)
TOKEN_REDUCTION_MEASURED = NO
```

## Real evidence

`dv_harness/stage_profile.py:39-186` and
`dv_harness/stage_profile_report.py:12-236` (Parent) implement real
per-stage token accounting: `input_tokens`/`output_tokens`/
`cache_read_tokens`/`cache_write_tokens`/`total_tokens`, sourced from the
Claude CLI adapter's own real usage payload (`stage_profile.py:45-48`).
`stage_profile_report.py:41-48` explicitly and honestly notes the SDK
adapter path reports `N/A` for these fields rather than fabricating a
number — the same evidence-grounded discipline seen throughout the
Codex-package modules.

## What was searched for and not found

A repo-wide grep for any file combining token/context telemetry with
`"codex"`/`"chatgpt"` returned **zero hits** on either tree. No file
anywhere:
- compares Claude's own token/context usage before vs. after any
  ChatGPT/Codex handoff,
- records a handoff-packet size, a task-packet size, or a
  files-scanned/files-loaded count tied to a multi-model round,
- reports `CLAUDE_CONTEXT_FILES`, `HANDOFF_SIZE`,
  `GOVERNANCE_DOCS_LOADED`, or `REPEATED_CONTEXT_LOADS` (or any
  equivalent) as the instruction's own requested observability shape.

## Result

```
TOKEN_REDUCTION_MEASURED = NO
TOKEN_REDUCTION_EFFECT = ARCHITECTURALLY_PLAUSIBLE_BUT_NOT_MEASURED
```

Real, working telemetry exists for Claude's own token usage in isolation
— this is a genuine, real building block a future multi-model-efficiency
wave could reuse directly (no need to build token accounting from
scratch). What is missing is entirely the CROSS-MODEL comparison: nothing
today could answer "did routing this task through ChatGPT/Codex actually
reduce what Claude had to read/process" with a real number, because no
handoff round with real before/after measurement has ever been recorded.

No percentage or reduction figure is asserted anywhere in this record,
per instruction.
