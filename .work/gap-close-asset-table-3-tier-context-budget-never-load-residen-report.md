# Gap close: 3-tier context budget (never-load / resident / on-demand) + MCP-only enforcement

**Status: DONE** (2 of the audit's 4 verdicts re-verified as already closed by concurrent work;
2 real residual defects found and closed by this pass.)

Commit: `f2fdaa6` — `fix(context-budget): stop the resident pack reporting real generators as
NOT IMPLEMENTED, and classify the remaining tier-3 artifacts` (2 files, +249/-3).

**Test summary**: 201 passed (`test_context_budget.py` + `test_asset_processing_artifacts.py` +
`test_four_key_judgments_enforcement.py`), including the two real-PowerShell subprocess tests that
drive the actual PreToolUse deny and SessionStart injection.

---

## 1. The audit finding was accurate when written, and is now stale

The audit was gathered against a repo state that no longer exists. Between it and this pass, a
concurrent workflow built the enforcement machinery it correctly reported missing. Re-verified as
real, present, and working right now:

| Thing the audit said did not exist | Current truth |
|---|---|
| The 3-tier rule documented anywhere real | `CLAUDE.md` § "Context Budget: 3 Tiers + MCP-First Routing" |
| Any enforcement of tier 1 | `dv_harness/context_budget.py:382` `evaluate_tool_call()` → `.claude/hooks/context-budget-guard.ps1`, registered in `.claude/settings.json` for `Read|Grep|Bash|PowerShell|NotebookRead` |
| Any residency mechanism | `context_budget.py:561` `session_start_payload()` → `.claude/hooks/context-resident-pack.ps1`, registered under `SessionStart` |
| `.claudeignore` | exists (2832 B) |
| Policy as data + schema | `dv_harness/context_budget.policy.json`, `dv_harness/schemas/context_budget.schema.json` |
| `phy_boundary.json` extractor | `dv_harness/phy_boundary.py` (+ `schemas/phy_boundary.schema.json`) |
| `vip_ref/<protocol>.md` generator | `dv_harness/vip_symbol_index.py` `write_vip_ref()` |
| `intent.md` / `constraints.md` generators | `dv_harness/design_intent.py` `write_intent()` / `write_constraints()` |
| Worked examples | `examples/asset_processing/` (inputs + generated, 13 files) |

Verified by running it, not by reading it:

- Tier-1 deny on the audit's own documented bypasses:
  `python -m dv_harness.context_budget classify "D:/DV/Task/USB/VIP/src/svt_usb_agent.sv"` →
  `never_load` / `NEVER-VIP-SOURCE`; `--command 'pdftotext -layout ".../usb_svt_uvm_user_guide.pdf" ug.txt'`
  → `never_load` / `NEVER-RAW-PDF`.
- End-to-end through the real hook process (how Claude Code invokes it):
  piping `{"tool_name":"Bash","tool_input":{"command":"grep -h ss_vout_model /d/DV/Task/USB/sim/sim.log"}}`
  into `.claude/hooks/context-budget-guard.ps1` returns a real
  `permissionDecision: deny` naming `NEVER-REGRESSION-LOGS` and routing to `query_regression`.

So the audit's **"NEVER into context = BLOCKED"** and **"Everything through MCP = BLOCKED"**
verdicts are both **now READY**, and tier 2 / tier 3 are no longer PARTIAL for the reasons given.

## 2. Two real residual defects, found by this pass and closed

### 2.1 The resident pack was actively misinforming every session (the substantive one)

`build_resident_pack()` (`context_budget.py:469-508`) prints a MISSING artifact's `produced_by`
**verbatim** into every session via the SessionStart hook. Three `produced_by` fields had gone
stale, so the context budget's own resident pack was telling every agent that real generators do
not exist:

- `phy_boundary` — `"NOT IMPLEMENTED -- no extractor exists in this repo as of 2026-09-03"`, while
  `dv_harness/phy_boundary.py` exists.
- `intent` — `"NOT IMPLEMENTED -- no generator exists in this repo as of 2026-09-03"`, while
  `dv_harness/design_intent.py` exists.
- `vip_ref` — cited `dv_harness/vip_distill.py`, which is **the exact miscitation the same policy
  file's `NEVER-VIP-SOURCE` rule already disclaims by name** ("does not read VIP source at all").
  Only the `never_load` half of that 2026-09-04 correction had been applied; the artifact half was
  missed.

Each now names the real producer, its real entry-point function, that these are library-level
modules with no `dv-harness` CLI subcommand, and a worked example under
`examples/asset_processing/`. Confirmed live: the resident pack now prints
`phy_boundary MISSING ... produce with: dv_harness/phy_boundary.py -- extract_from_env_manifest(...)`.

`hierarchy` was deliberately **left** saying it has no non-agent extractor — that is still true
(only `.claude/skills/CORE/hierarchy-discovery/SKILL.md` declares the path), and a test now
protects it from a well-meaning false "correction".

### 2.2 Tier 3 did not classify three artifacts that had become real

`sys_regmap.json`, `init_seq.yaml` and `constraints.md` had real modules
(`dv_harness/sys_regmap.py`, `init_seq.py`, `design_intent.py`), real schemas and real worked
examples, but appeared in **no tier**, so `classify_path()` returned `unclassified` — the budget
had nothing to say about artifacts it exists to route. Added to `load_on_demand`; tier 3 is now
6 entries and all four spec-named on-demand types classify correctly.

## 3. Root cause, and why the fix is a test rather than an edit

The stale text was not bad luck. The suite had a one-sided contract:

- `never_load[].distiller` was guarded **three** ways — the cited file must exist
  (`test_cited_distillers_are_real_files`), must genuinely mention its content class
  (`test_a_cited_distiller_really_handles_that_content_class`), and the `vip_distill.py`
  miscitation is named and refused (`test_vip_source_rule_cites_a_real_vip_source_distiller`).
- `artifact[].produced_by` — the **same** "cite a real producer" contract — was checked only for
  **non-emptiness** (`test_missing_artifact_is_reported_with_the_command_that_produces_it:357`).

That asymmetry is what let `NOT IMPLEMENTED` and the `vip_distill` miscitation survive in
`produced_by` while being fixed in `distiller`. So the durable fix is the guard, not the text.
8 new tests (+15 parametrised cases) close it symmetrically.

**One of those tests was itself broken and was caught by mutation-testing it.** The first version
of `test_no_artifact_claims_unimplemented_while_its_producer_exists` keyed off *which module the
text cites* — but the real stale text cited **no module at all**, so it passed on the exact state
it was written to catch. It now asks the **filesystem** which producers exist (deriving the
candidate from `artifact_id` itself, so a future artifact is checked automatically rather than
escaping until someone extends a list), and
`test_the_unimplemented_guard_really_fires_on_the_real_pre_fix_text` pins that it fires against
the real pre-fix string via `pytest.raises`.

## 4. Honest limits, unchanged and not papered over

- The guard classifies **literal paths only**. `sed -n "1,50p" $M` with `$M` assigned earlier is
  not classifiable at PreToolUse time. This is disclosed in `context_budget.py`'s own docstring
  and covered by named tests. A reduction in bypass surface, not a seal.
- The guard **fails open** if Python is unavailable — deliberate, and separate from
  `block-destructive.ps1`, which must fail closed.
- Tier-2 residency in *this* repo is still only `CLAUDE.md`; the harness has no RTL tree or VIP of
  its own, so `env_manifest`/`run_profile`/`hierarchy`/`phy_boundary` are honestly MISSING here
  (`resident` exits 2). That is correct reporting, not a gap.
- `.claude/settings.json` still lists `Bash(pdftotext:*)` in `permissions.allow`. Not a hole in
  practice — a PreToolUse `deny` outranks a permission allow, and the deny is proven firing on
  `pdftotext` above — but the allow entry is now misleading residue. Left alone deliberately:
  `settings.json` is being edited by concurrent workflows this session, and removing a permission
  entry is a change to the user's harness configuration, not mine to make unasked.

## 5. Concurrency discipline

`git status` was checked before touching anything. Only `dv_harness/context_budget.policy.json`
and `dv_harness_tests/test_context_budget.py` were modified; both were clean beforehand and the
full diff was reviewed line-by-line to confirm it contained no other agent's work.

The index already held **another workflow's** staged changes (`CLAUDE.md`, `env_manifest.py`,
`question_queue.py`, `connectivity_check.py`, `cli.py`, `main_graph.json`, plus a new test and
report). The commit therefore used `git commit --only -- <my two paths>`, which committed only
those two files and **left the other workflow's 8 staged files staged and uncommitted** —
verified after the fact. No broad `git add`, no push (governance forbids agent pushes to
`master`).

## 6. Note on a flaky test (not a defect in the code under test)

The first full-suite run showed
`test_guard_hook_denies_through_real_powershell_process` FAILING on a 120 s
`subprocess.TimeoutExpired`. Investigated rather than assumed: run in isolation it passes in
10.2 s, and the same payload through the real hook by hand returns the correct deny in 8.7 s. The
failure was contention from the many concurrent workflows on this machine, not a hang. The final
full run passed all 201 in 25 s. Flagging it because the 120 s timeout is brittle under heavy
concurrent load; **not** changed here, since raising a timeout to hide load-induced flake is a
judgment call for the suite's owner and no assertion is at fault.

## 7. Verdicts

| Requirement | Audit verdict | Verdict now |
|---|---|---|
| Tier 1 — NEVER into context | BLOCKED | **READY** — real PreToolUse deny, proven end-to-end through the real hook process |
| Tier 2 — ALWAYS resident | PARTIAL→BLOCKED | **READY (mechanism)** — real SessionStart injection, bounded by `MAX_PACK_BYTES`; residency in *this* repo is honestly 1/5 and reported as MISSING with real producing commands, which is correct, not a gap |
| Tier 3 — LOAD ON DEMAND | PARTIAL | **READY** — 6 entries; `vip_ref`/`intent` generators real; `constraints`/`sys_regmap`/`init_seq` added this pass |
| "Everything through MCP" | BLOCKED | **READY as a gate, with disclosed limits** — 5 fixed verbs, no free-text/SQL fallback, and tier-1 denials now route to them. Literal-path and fail-open limits documented and tested, not claimed away |
