# M4.6 — Token/Context Measurement

```
CLAUDE_MD_LINES_BEFORE = 22,461
CLAUDE_MD_LINES_AFTER  = 1,640
CLAUDE_MD_BYTES_BEFORE = 2,067,655   (wc -c, real measurement)
CLAUDE_MD_BYTES_AFTER  = 112,262     (wc -c, real measurement, same tool/method)

CLAUDE_MD_BYTE_REDUCTION = 1,955,393 bytes  (94.57%)
CLAUDE_MD_LINE_REDUCTION = 20,821 lines     (92.70%)

TOKEN_REDUCTION_MEASURED = NO
```

Both `BEFORE` and `AFTER` figures were produced with the identical
method (`wc -l`/`wc -c` on the real file), so the delta is a real,
apples-to-apples measurement, not an estimate.

## Why `TOKEN_REDUCTION_MEASURED` stays `NO`

Per S20's own explicit instruction: a byte/line reduction is not a
Claude-token measurement unless real token telemetry exists. No token
telemetry combining this specific change with real Claude usage was
produced this wave (the pre-existing `stage_profile.py`/
`stage_profile_report.py` telemetry, confirmed present in canonical per
`MASTER_TOKEN_EFFICIENCY_STATUS.md`, records per-stage usage but has
never been run once before this change and once after it to produce a
comparable pair). The byte/line numbers above are reported as exactly
that — measured file-size facts — and nothing more is inferred from
them.

## Residency-budget context (real, pre-existing mechanism, unmodified this wave)

`dv_harness/context_budget.policy.json` declares a 65,536-byte
residency budget for the `claude_md_index` artifact.
`python -m dv_harness.context_budget resident` (unmodified, real,
data-driven) now reports:

```
BEFORE: claude_md_index PRESENT (CLAUDE.md, 2067655 B): exceeds this
        artifact's 65536-byte residency budget by ~2,002,119 bytes (~31.6x over)
AFTER:  claude_md_index PRESENT (CLAUDE.md, 112262 B): exceeds this
        artifact's 65536-byte residency budget by 46,726 bytes (~1.7x over)
```

Honestly disclosed: M4.6 is a real, large, measured improvement against
this declared budget (from ~31.6x over cap to ~1.7x over cap) but does
**not** fully close it. Getting under 65,536 bytes would require either
further-compacting the 24 `ALWAYS_ON_CORE_GOVERNANCE` sections'
own prose (a genuine future task, not attempted here since S4
explicitly forbids removing a universally-required rule merely to hit a
token target) or lowering the declared cap's own semantics — neither
decision is this wave's to make unilaterally, so it is recorded as a
known, disclosed residual rather than silently claimed closed.
