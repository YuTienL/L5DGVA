# Gap close: 3-tier context budget (never-load / resident / on-demand) + MCP-only enforcement

**Status: DONE** (with two scoped `NEEDS_SEPARATE_EFFORT` carve-outs, named below).

**Test summary:** `python -m pytest dv_harness_tests/test_context_budget.py -q` -> **69 passed**;
plus `test_mcp_verbs / test_mcp_manifest_and_schema / test_mcp_read_only_boundary /
test_mcp_query_regression / test_mcp_server_transport / test_mcp_env_manifest_integration /
test_env_manifest / test_connectivity / test_agent_checkpoint_check` -> **329 passed** (4m39s), the
suites covering everything this change touches or cites.

Commits: `2c79eea` (the mechanism) and `53f8324` (a real miscitation found while verifying it).

---

## Verdict per requirement

| Requirement | Before | After |
|---|---|---|
| Tier 1 — NEVER into context | BLOCKED | **READY** — documented + enforced as a real PreToolUse deny |
| Tier 2 — ALWAYS resident | PARTIAL | **READY as a mechanism** / artifacts 1-of-5 PRESENT, reported not hidden |
| Tier 3 — LOAD ON DEMAND | PARTIAL | **READY for regmap**; `vip_ref/` + `intent.md` = NEEDS_SEPARATE_EFFORT |
| "Everything routes through MCP" | BLOCKED | **READY as a gate**, with three named residual gaps |

---

## What was built

All four pieces are real and wired; none is a stub.

**Policy as data** — `dv_harness/context_budget.policy.json` (189 lines), validated against
`dv_harness/schemas/context_budget.schema.json` (124 lines). A project extends its own DUT/VIP
roots there, never in Python. Four `NEVER-*` rules matching the spec's four content classes
exactly: `NEVER-VIP-SOURCE`, `NEVER-RAW-PDF`, `NEVER-WHOLE-CHIP-DB`, `NEVER-REGRESSION-LOGS`.

**Logic** — `dv_harness/context_budget.py` (666 lines). Path normalisation across the three
spellings of the same file (`context_budget.py:144`), glob translation where `**` spans separators
and `*` does not (`:160` — `fnmatch` would have conflated them), tier classification (`:234`),
command-string scanning (`:324`), the PreToolUse decision (`:382`), and the bounded tier-2 pack
(`:469`, `:525`). CLI: `hook` / `session-start` / `classify` / `resident`.

**The gate** — `.claude/hooks/context-budget-guard.ps1`, registered at
`.claude/settings.json:55` for `Read|Grep|Bash|PowerShell|NotebookRead`. This is the specific thing
the audit said did not exist: `block-destructive.ps1` matches only `Bash|PowerShell` and inspects
for destructive patterns, never firing on `Read` and never looking at *what* is read.

**The residency mechanism** — `.claude/hooks/context-resident-pack.ps1` at
`.claude/settings.json:32` (`SessionStart`), emitting `hookSpecificOutput.additionalContext` with
the size-capped pack (`MAX_PACK_BYTES = 24_000`, `context_budget.py:96`; JSON summarised by shape,
never inlined). Before this, only `CLAUDE.md` was resident, and only because the agent harness
auto-loads it — an accident of the tool, not something this project engineered.

**Documentation** — `CLAUDE.md:655`, "Context Budget: 3 Tiers + MCP-First Routing". The original
finding was that the 3-tier text existed nowhere in the repo except a workflow prompt;
`test_context_budget_is_documented_in_claude_md` is the drift guard.

---

## Evidence that it actually fires

Every tier-1 test case is a tool call `.claude/settings.local.json`'s own allow history records as
having really happened in this project — not invented scenarios:

```
$ echo '{"tool_name":"Bash","tool_input":{"command":"grep -h ss_vout_model .../sim.log"}}' \
    | powershell -NoProfile -File .claude/hooks/context-budget-guard.ps1
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
 "permissionDecisionReason": "CONTEXT BUDGET tier-1 (NEVER into context) violation:
  NEVER-REGRESSION-LOGS ... Use the fixed MCP verb `query_regression` instead ..."}}
```

Run as a real subprocess with the payload on real process stdin — the way Claude Code invokes a
PreToolUse hook. That path found a genuine never-fires bug the Python-level tests could not:
PowerShell 5.1 prepends a UTF-8 BOM when piping a string into a native command, so `json.loads`
failed and the guard failed open on *every* call. Fixed at `context_budget.py:575`
(`read_hook_stdin`, utf-8-sig), with `test_hook_cli_tolerates_a_utf8_bom` pinning it.

`python -m dv_harness.context_budget resident` exits 2 while any tier-2 artifact is MISSING and
prints the real command that produces it.

---

## A real miscitation, found and fixed (commit `53f8324`)

The policy first cited `dv_harness/vip_distill.py` as the VIP-source distiller — purely because
the name looked right. Reading it showed it is an **evidence-envelope normaliser for sim logs, job
records and fsdb reports** (`distill_sim_log` / `distill_job_record` / `distill_fsdbreport`); it
never reads VIP source. A denied agent would have been sent after a script that does not do the
job. There is no VIP-source distiller in this repo, so the rule now carries `distiller: null` plus
a `distiller_note` saying exactly that, printed in the deny message.
`test_a_cited_distiller_really_handles_that_content_class` asserts each cited distiller's source
actually mentions the class it claims (`.pdf` / `.fsdb` / `sim.log`) — that check fails on
`vip_distill.py`, which is how this was caught. The other three citations verified real:
`doc_extraction.py` (handles `.pdf` in its `SUPPORTED` set, though its own 2026-08-28 notice says
it is standalone — recorded), `fsdb_report.py`, `sim_log_analysis.py`.

---

## Deliberate carve-outs (a gate that gets switched off enforces nothing)

- VIP `Examples/` reference testbenches and `.f` filelists stay readable — they are the sanctioned
  reference material and already have a real `Read` allow entry.
- `ls`/`find`/`stat`/`wc`/`file` may *name* a tier-1 file without reading it. Disabled the moment
  any pipe/redirect/chaining metacharacter appears, so `ls x && cat sim.log` is not an `ls`
  (`test_a_chained_command_is_not_treated_as_a_bare_listing`).
- `Edit`/`Write` are untouched — a context budget has nothing to say about them; the existing
  `settings.json` deny rules and `block-destructive.ps1` own that.
- A genuinely necessary tier-1 read takes a reasoned `exemptions` entry; the rule still fires and
  is recorded in the decision, so the audit trail shows it was consciously waived.

## Residual gaps, stated rather than papered over

Each has a named test so it cannot be quietly forgotten:

1. **Shell-variable indirection.** `sed -n "1,50p" $M` cannot be classified — at PreToolUse time
   the shell has not expanded `$M`. `test_variable_indirected_read_is_a_known_residual_gap`.
2. **Directory indirection.** `ls <dir> | xargs cat` names no tier-1 *file*. The alternative —
   marking every `sim/` directory tier-1 — would deny grepping a build dir for its Makefile, a
   worse trade. `test_directory_indirection_is_a_known_residual_gap`.
3. **Fail-open.** Both hooks exit 0 silently if Python is unavailable. Deliberate: a context budget
   that bricks every `Read` when an interpreter moves is worse than one that occasionally misses.
   The destructive-operation guard, which must fail closed, is a separate hook.

This is a large reduction in bypass surface, **not a seal**, and `CLAUDE.md` says so.

**Not changed, and why:** `.claude/settings.json`'s `allow` list still contains
`Bash(pdftotext:*)`, which contradicts `NEVER-RAW-PDF`. I attempted to remove it and the action was
correctly refused — a subagent must not edit permission settings. It is harmless in practice (a
PreToolUse deny outranks a permission allow, and `test_tier1_violation_is_denied` covers exactly
that command), but **a human should delete that one line** for consistency.

---

## NEEDS_SEPARATE_EFFORT (out of this scope, precisely bounded)

Two tier-2 and two tier-3 artifact **types** genuinely do not exist, and building them is the
asset-processing-table workstream's own scope, not a bounded completion of the budget rule:

| Artifact | Real status |
|---|---|
| `.dv-workflow/hierarchy.json` | Path is really declared by `.claude/skills/CORE/hierarchy-discovery/SKILL.md:22`, but no non-agent extractor exists |
| `.dv-workflow/phy_boundary.json` | No extractor at all; only real reference is `critical_fields` at `.claude/skills/USB/usb-profile/PROFILE.yaml:8` |
| `docs/vip_ref/<protocol>.md` | No producer (see the `vip_distill.py` correction above) |
| `docs/intent.md` | No generator |

I did **not** stub these. Instead the policy declares each one's canonical path and real
`produced_by` string, and `build_resident_pack()` reports them as MISSING with that command
attached — so the gap is machine-visible and closeable rather than silently absent
(`test_missing_artifact_is_reported_with_the_command_that_produces_it`). Current residency is
**1 of 5 PRESENT** (`CLAUDE.md`); `env.manifest.json` and `run_profile.json` have real, tested
generators but no project instance on disk yet, which is project data rather than a harness gap.

Tier 3's third item needs no work: single-register lookup via `get_register`
(`dv_harness/mcp/verbs.py:134-184`) was already READY and is re-confirmed.

---

## Concurrency note

Several workflows were editing this repo throughout. `CLAUDE.md` carried other workstreams'
uncommitted hunks, and the shared git index held another workflow's staged files
(`engine.py`, `gates.py`, `prompts.py`, `models.py`, two SKILL.md files, their tests). Both commits
were therefore made through an **isolated index** (`GIT_INDEX_FILE` + `read-tree HEAD` +
`write-tree`/`commit-tree`/`update-ref`) after trimming the `CLAUDE.md` diff to my own hunk — so
nothing of theirs was swept in, and their staging was left exactly as found. Verified after each
commit: my files clean, their 12 staged files still staged.

## Files

- `dv_harness/context_budget.py` (new, 666 lines)
- `dv_harness/context_budget.policy.json` (new, 189 lines)
- `dv_harness/schemas/context_budget.schema.json` (new, 124 lines)
- `dv_harness_tests/test_context_budget.py` (new, 539 lines, 69 tests)
- `.claude/hooks/context-budget-guard.ps1` (new)
- `.claude/hooks/context-resident-pack.ps1` (new)
- `.claude/settings.json` (hooks registered: `SessionStart` :32, `PreToolUse` :55)
- `CLAUDE.md` (new section at :655)
