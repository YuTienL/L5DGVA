# Gap-close pass: Bind-location 4 hard rules + 3 machine gates

**Verdict: NO_ACTION_NEEDED.** Nothing was modified, nothing was committed.

The one gap the incoming audit flagged (Gate 3 as a standing
`just connectivity-check` recipe) was **already closed for real** before this
pass started, by commit `5e373dc` — *"connectivity: make the 3 machine gates a
standing recipe re-run on every RTL update"*. The incoming audit finding was
stale with respect to the current tree. Every other requirement in this scope
was re-confirmed READY against fresh evidence gathered this pass (line numbers
below are the **current** ones; `connectivity.py` has grown from ~1225 to 2943
lines since the audit was written, so all its cited line numbers had shifted).

---

## 1. The 4 hard rules — re-confirmed READY

The spec's ask for the rules is a *documentation* requirement ("must be in
CLAUDE.md, not left to agent judgment"). Re-read fresh at
`CLAUDE.md:572-680`, section `## Bind-Location Rules (2026-09-03)`. The section
has since grown to **five** rules; all four in scope are present verbatim and
stated as absolutes, not discretion:

| Rule | Location | State |
|---|---|---|
| 1 — bare module name vs. full instance path | `CLAUDE.md:583-587` | READY. "SoC-level work must always bind by full instance path", with the `chip.core.subsys0.usb0` vs `usb3_subsystem` example. Supporting semantics implemented at `dv_harness/connectivity.py:790` `find_existing_bind_for_target()`. |
| 2 — centralized `*_bind.sv` under `tb/`, RTL read-only | `CLAUDE.md:588-591` | READY as stated rule. "RTL files are **read-only**: an agent must never insert a `bind` statement directly into RTL." |
| 3 — clock/reset via the bind's own port list, no XMR | `CLAUDE.md:592-596` | READY as stated rule. |
| 4 — no generate/for-loop bind targets, explicit indices only | `CLAUDE.md:597-603` | READY as stated rule; correctly ties the prohibition to `connectivity.py`'s T3 tier being the most error-prone. |

**Honesty check on the doc itself** (a doc that overclaims enforcement would be
a real gap in this scope — it does not): `CLAUDE.md:641-648` still says plainly
that *"Rules 1–4 (the path rules) are enforced by review, not (yet) by a
standalone lint gate — Rule 5 is the exception and hard-blocks in code"*. That
claim is **true**, verified by reading the generator:

- `dv_harness/uvm_generator/bind_mechanism_generator.py:120-126` —
  `validate_bind_entries()` really does run two hard gates before emitting:
  `assert_phy_boundary_decided_first(...)` (Rule 5) then
  `enforce_bind_tier_policy(...)` (bind-confidence tier), and
  `emit_bind_sv()` (line 130) routes through it.
- No corresponding shape check exists for Rules 2/3/4 — no output-path guard
  into `tb/*_bind.sv`, no XMR scan, no `[*]`/for-generate rejection. Exactly as
  CLAUDE.md discloses. This is a disclosed limitation, not a hidden gap, and it
  is outside the literal documentation ask of this scope.

## 2. The 3 machine gates — all READY

- **Gate 1 (elaboration)** — `dv_harness/connectivity.py:1762`
  `run_gate1_elaboration_check()`. Real `shutil.which` detection of
  `slang`/`vcs` (both injectable), real `slang --ast-json ... --top <top>` /
  `vcs -elab_only -f <filelist> -top <top>` argv, PASS/FAIL from real
  `returncode`, honest `NOT_AVAILABLE` otherwise. Confirmed live below:
  neither tool is on PATH here, and the runner reported `NOT_AVAILABLE` rather
  than fabricating a PASS.
- **Gate 2 (static zero-time connectivity)** — `connectivity.py:1812`
  `evaluate_zero_time_connectivity()`. All three spec checks are really there:
  clock actually toggles, reset actually asserts→deasserts, and every
  `required_nonx_signals` entry is non-X/Z **at t=0 specifically**, over the
  `SignalTrace` contract. `run_gate2_against_live_simv()` (line 1855) is the
  honest NOT_AVAILABLE integration point.
- **Gate 3 (transaction activity)** — `connectivity.py:1875`
  `evaluate_transaction_activity()` flags any monitor with `cnt < 1` as FAIL
  (the spec's "a monitor receiving 0 is a wrong connection"), and
  `evaluate_transaction_activity_status()` (line 1918) keeps PENDING
  ("no pattern completed yet") strictly distinct from FAIL and NOT_AVAILABLE.
- **Pipeline** — `run_machine_gates()` (`connectivity.py:1990`) still runs all
  three, never a subset.
- **Status/checkpoint machinery** — `GateStatus` (line 1699) carries all five
  of PASS/FAIL/NOT_AVAILABLE/PENDING/NOT_YET_RUN;
  `bind_verification_status_block()` (2058),
  `render_bind_verification_status_markdown()` (2076) and
  `assert_bind_gates_checkpoint()` (2096, raises `BindGateCheckpointError`,
  never a silent bool) are all real.

## 3. Gate 3 as a *standing* recipe — the audit's one gap, already closed

The audit said "the recipe does not exist anywhere (no justfile target, no CI
job, no CLI subcommand, no hook)". That is **no longer true**:

- `D:\DV\Task\DV_Agent_Harness_L5\v50\justfile:229` `connectivity-check` and
  `:237` `connectivity-check-status`. Both resolve for real —
  `just --list` lists them, and `just --dry-run connectivity-check-status`
  expands to
  `python -m dv_harness.connectivity_check --project-root "D:\DV\Task\DV_Agent_Harness_L5\v50" --check-only`.
- `.github/workflows/dv-harness-ci.yml:122-123` — CI step
  *"Bind-connectivity staleness check (3 machine gates)"* running the same
  `--check-only` probe.
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\connectivity_check.py` (26 KB)
  is the real runner behind both; it drives `connectivity.run_machine_gates()`
  (all 3 gates) and records the verdicts against a **sha256 content**
  fingerprint of the declared RTL set.
- The audit's "connectivity.py is imported nowhere but itself and
  bind_verification_lint.py" is also stale — it now has four real importers:
  `dv_harness/init_seq.py:49`,
  `dv_harness/uvm_generator/bind_mechanism_generator.py:125`,
  `dv_harness/uvm_generator/bind_verification_lint.py:41`, and
  `dv_harness/connectivity_check.py`.

### End-to-end proof run this pass (not a test, the real CLI)

Against a synthetic project in the scratchpad with one real `.v` file:

| Step | Result |
|---|---|
| `--check-only` before any run | `STALE (NEVER_RUN)`, **exit 2** |
| full gate run, one monitor at 0 txns | `gate3_transaction_activity: FAIL`, **exit 1** |
| `--check-only`, RTL untouched | `UP_TO_DATE`, exit 0 |
| `touch` the RTL (mtime only, content identical) | still `UP_TO_DATE`, exit 0 — content-hash based, a no-op touch does not false-fire |
| add a second real `.v` file (genuine content change) | `STALE (RTL_CHANGED) -- recorded 6513eb69c18e... != current da69783e6cf6...`, **exit 2** |
| re-run gates with the silent monitor fixed | `gate3_transaction_activity: PASS`, exit 0 |

Artifacts written: `connectivity_check_state.json` +
`connectivity_check_report.md`. Gates 1 and 2 reported `NOT_AVAILABLE`
throughout (no `slang`/`vcs`/live trace here) rather than being papered into a
PASS. On this harness repo itself (no RTL tree) the runner honestly reports
`NOT_CONFIGURED`: `--check-only` exits 0, a real gate run exits 3.

## 4. Test suite

Run this pass, unmodified tree:

```
python -m pytest dv_harness_tests/test_connectivity.py \
                 dv_harness_tests/test_connectivity_check.py \
                 dv_harness_tests/test_bind_verification_lint.py \
                 dv_harness_tests/test_bind_mechanism_generator.py -q
-> 225 passed in 15.34s
```

**One-line test summary:** 225 passed across the four bind/connectivity test
modules; no test was added or changed because no code was changed.

## Remaining, disclosed (not closed here, out of this scope's literal ask)

Rules 2, 3 and 4 have no mechanical enforcement — no guard forcing generated
bind output into `tb/*_bind.sv`, no XMR-clock/reset scan, no rejection of a
`target_instance` containing `[*]` or a for-generate path.
`validate_bind_entries()` checks entry *presence* plus the Rule 5 and tier
gates, never target-path *shape*. CLAUDE.md states this limitation itself at
`CLAUDE.md:641-648`, so it is disclosed rather than hidden. Building those
three lints is a genuinely separate, bounded piece of work (a bind-path shape
linter plus its output-path guard) and was deliberately not started here: this
pass was scoped to closing the audit's flagged gap, which was already closed,
and the task instruction for READY items is "do nothing, just re-confirm".
