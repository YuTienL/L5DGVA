# Stage-scoped completion percent (2026-09-01)

## Context / gap being closed

An earlier audit this session found: the harness could already show the
current stage (`control_plane.describe_stage()`) and an itemized list of
outstanding gate/field reasons (`gates._evaluate_stage_evidence_core()`),
but had **no numeric completion percentage scoped to the current stage
specifically** — the only numeric progress signal anywhere was
`dashboard.py`'s `_overall_progress()` / `overall_progress_percent`, a
**whole-run** percentage (fraction of all `Stage` enum values at
PASS/CLOSED), computed only inside the dashboard's `GET /api/state`
handler and never exposed via the CLI.

This closes that gap: a real, stage-scoped `stage_completion_percent`
(plus `gates_total`/`gates_passed`) derived from the exact same per-gate
signatures list `_evaluate_stage_evidence_core()` already builds, threaded
through `describe_stage()` and surfaced by `dv-harness explain --stage` /
`evidence --stage` / `evidence` (no `--stage`, batch form).

## What was built

### `dv_harness/gates.py`

- New `_stage_completion_from_signatures(gates, signatures)` helper:
  computes `gates_total = len(gates)`, `gates_passed = sum(1 for _,ok,_ in
  signatures if ok)`, `stage_completion_percent = round(100 *
  gates_passed / gates_total)`, plus a `stage_completion_note` (`None` in
  the normal case). **RULING** (see below) covers the zero-gates case.
- `_evaluate_stage_evidence_core()` now returns a **4-tuple**
  `(verdict, reasons, signatures, completion)` instead of the previous
  3-tuple — `completion` is the dict from the helper above, computed once
  from the same `signatures` list the function already builds (every
  return path, including the early `NO_GATE_REQUIRED` return, now attaches
  it). This is the one non-strictly-additive shape change in the patch;
  see "Ruling on tuple arity" below for why it's safe.
- New public `evaluate_stage_evidence_with_completion(root, stage,
  agent_text)` — same `(verdict, reasons)` semantics as the pre-existing
  `evaluate_stage_evidence()`, plus `completion` as a 3rd return value.
  This is the new real call site `control_plane.describe_stage()` uses.
- `evaluate_stage_evidence()` itself (the pre-existing 2-tuple contract)
  is **unchanged from the outside**: it now unpacks 4 values internally
  from `_evaluate_stage_evidence_core()` but still returns only
  `(verdict, reasons)`.

### `dv_harness/react_loop.py`

- `evaluate_stage_evidence_with_detail()` now unpacks the core function's
  4-tuple internally (`verdict, reasons, raw_signatures, _completion`) but
  **still returns its original 3-tuple** `(verdict, reasons, signatures)`
  unchanged — real existing callers (`engine.py`, this module's own retry
  loop, and 6 call sites across `dv_harness_tests/test_react_loop.py`)
  unpack it positionally at exactly 3 values; changing its arity would
  have broken every one of them. Docstring updated to point at
  `evaluate_stage_evidence_with_completion()` as the real completion call
  site instead.

### `dv_harness/control_plane.py`

- `describe_stage()` now calls `evaluate_stage_evidence_with_completion()`
  instead of `evaluate_stage_evidence()`, and adds `gates_total`,
  `gates_passed`, `stage_completion_percent`, `stage_completion_note` to
  its returned dict, alongside the pre-existing `gate_verdict`/
  `gate_reasons` (and every other pre-existing key, unchanged).
  `describe_stages()` (the batch form) needed no change — it already just
  loops `describe_stage()` per stage.

### `dv_harness/cli.py`

- Print-site audit for `explain --stage` (line ~409) and `evidence
  --stage`/`evidence` (lines ~441/448/450): both just
  `json.dumps(describe_stage(...))`/`json.dumps(describe_stages(...))`
  with **no field allowlist**, so the new fields surface automatically
  once `describe_stage()` carries them — no functional code change was
  needed at these print sites. Added a short comment at each site
  documenting this (naming the 4 new fields explicitly) so a future reader
  doesn't have to re-derive it, and a real end-to-end test
  (`test_cli_evidence_stage_prints_completion_fields`,
  `test_cli_explain_stage_prints_completion_fields`) drives the actual
  `dv-harness explain`/`evidence` CLI commands and asserts the new fields
  appear in the printed JSON.

## Rulings

- **RULING (zero registered gates -> 100%, not 0% or a crash):** a stage
  with zero gates in `STAGE_GATES` has nothing to be "incomplete" about —
  there is no per-gate signature list to divide by, and `NO_GATE_REQUIRED`
  already means the stage's own gate-evidence requirement is trivially
  satisfied. Reporting 0% would misleadingly read as "nothing done" for a
  stage that in fact has no gate blocking it at all. Implemented as an
  explicit `gates_total == 0` branch in `_stage_completion_from_signatures()`
  returning `{"stage_completion_percent": 100, "stage_completion_note":
  "stage has no registered gates; treated as fully complete", ...}` —
  never a `ZeroDivisionError`, never an arbitrary silent 0%. Verified every
  real `Stage` enum value (`Stage` in `dv_harness/models.py`) currently has
  >=1 gate registered in `STAGE_GATES`, so this path is only reachable via
  an unknown/synthetic stage id in practice — tested directly with the
  same `"__NO_SUCH_STAGE__"` sentinel `test_engine_gates_and_routing.py`
  already uses for the `NO_GATE_REQUIRED` case.

- **RULING (tuple arity on the private core function is fair game; the two
  public wrapper functions' arities are not):** `_evaluate_stage_evidence_
  core()` is a leading-underscore internal helper with exactly two known
  callers, both inside this same commit (`gates.evaluate_stage_evidence()`
  and `react_loop.evaluate_stage_evidence_with_detail()`), and no direct
  test imports it by that name for its return shape. Extending it from a
  3-tuple to a 4-tuple and updating both callers in the same change is
  "threading a new field through," not "breaking an existing caller."
  By contrast, `evaluate_stage_evidence()` (2-tuple) and
  `evaluate_stage_evidence_with_detail()` (3-tuple) are genuinely public,
  with real external test callers doing positional tuple-unpacking at
  their current arity (`dv_harness_tests/test_engine_gates_and_routing.py`,
  `dv_harness_tests/test_react_loop.py` x6). Changing either of those
  arities would have been a real break, explicitly forbidden by the task.
  Ruling: keep both public contracts byte-identical, and add the
  completion dict via a **new** function (`evaluate_stage_evidence_with_
  completion()`) instead of overloading either existing one. This is why
  `describe_stage()` calls a function neither `engine.py` nor
  `react_loop.py` needed to change.

- **RULING (rounding):** `round(100 * gates_passed / gates_total)` (Python
  banker's rounding on `.5` ties) rather than `int()`-truncation, since the
  task explicitly specified `round(...)`. 2/3 -> 67%, not 66%.

## Tests added

New file `dv_harness_tests/test_stage_scoped_completion_percent.py`, 12
tests, all against **real** gate scripts (ARCH_CALIBRATION's 3 registered
gates in `STAGE_GATES`, actually subprocess-run via the same
`_mk_smoke_project()` fixture shape `test_react_loop.py` and
`test_engine_gates_and_routing.py` already use — never synthetic
signature tuples for the "N of 3 gates" cases):

- `test_three_of_three_gates_passing_yields_100_percent` — 3/3 -> 100%.
- `test_two_of_three_gates_passing_yields_67_percent` — 2/3 -> 67%
  (`round(100*2/3)`).
- `test_zero_of_three_gates_passing_yields_0_percent` — 0/3 (no evidence
  blocks at all, `MISSING_EVIDENCE`) -> 0%.
- `test_stage_with_zero_registered_gates_defaults_to_100_with_note` — a
  stage absent from `STAGE_GATES` -> 100% with a non-empty note, verdict
  `NO_GATE_REQUIRED`.
- `test_stage_completion_helper_zero_gates_no_zero_division_error` — direct
  unit check of the helper with `gates=None` and `gates=[]`, proving no
  `ZeroDivisionError` either way.
- `test_evaluate_stage_evidence_public_2_tuple_contract_unchanged` /
  `test_evaluate_stage_evidence_with_detail_public_3_tuple_contract_unchanged`
  — regression guards proving the two public wrapper functions' external
  arities are untouched.
- `test_core_function_now_returns_a_4_tuple_with_completion_last` — proves
  the new 4th element on the internal core function.
- `test_describe_stage_surfaces_completion_fields_matching_gate_verdict` /
  `test_describe_stage_zero_gate_stage_reports_100_with_note` —
  `control_plane.describe_stage()` end-to-end, checking the new fields
  agree with `gate_verdict`/`gate_reasons` and pre-existing fields are
  untouched.
- `test_cli_evidence_stage_prints_completion_fields` /
  `test_cli_explain_stage_prints_completion_fields` — real `dv-harness
  evidence --stage`/`explain --stage` CLI invocations (via `cli.main()`
  with a monkeypatched `sys.argv`, same pattern as
  `test_active_stages_read_sites.py`'s `_run_cli()`), asserting the new
  fields appear in the printed JSON.

## Test results

- New file: `pytest dv_harness_tests/test_stage_scoped_completion_percent.py -q`
  -> **12 passed** (run twice for stability, ~87s each — real subprocess
  gate scripts, not mocked).
- Full existing regression sweep across the three files most load-bearing
  for this change: `pytest dv_harness_tests/test_react_loop.py
  dv_harness_tests/test_active_stages_read_sites.py
  dv_harness_tests/test_engine_gates_and_routing.py -q` ->
  **217 passed, 1 failed** (`test_cli_lsf_reconcile_picks_up_existing_job_
  state_files`, `dv_harness_tests/test_engine_gates_and_routing.py`).
  Verified this failure is **pre-existing and unrelated**: reproduced it
  identically (same `assert 0 == 1` on the LSF-reconcile CLI subprocess's
  return code) after `git stash`-ing every change in this patch and
  running that single test alone against the clean tree. It depends on
  whether a real `bjobs` binary is reachable on this machine's `PATH`
  (LSF availability), not on anything this patch touches (`git diff
  --stat` for this patch touches only `cli.py`, `control_plane.py`,
  `gates.py`, `react_loop.py` — never `lsf_client.py` or the
  `lsf-reconcile` subcommand). Zero regressions introduced by this patch.
- `.dv-harness/events.jsonl` picked up incidental `CLI_ACCESS` log lines
  from `test_engine_gates_and_routing.py`'s own CLI-subprocess tests
  (which run against this worktree's real project root, a pre-existing
  property of those tests, not something this patch changed) during the
  first full-suite run; reverted with `git checkout -- .dv-harness/
  events.jsonl` before committing so this commit carries only the real
  source/test changes.

## Files changed

- `dv_harness/gates.py` — `_stage_completion_from_signatures()`,
  `evaluate_stage_evidence_with_completion()`, `_evaluate_stage_evidence_
  core()`'s 4th return element, `typing.Any`/`Dict` import.
- `dv_harness/react_loop.py` — `evaluate_stage_evidence_with_detail()`
  updated to unpack (not return) the 4th element; docstring.
- `dv_harness/control_plane.py` — `describe_stage()` surfaces the 4 new
  fields.
- `dv_harness/cli.py` — explanatory comments at the `explain`/`evidence`
  print sites (no functional change needed there).
- `dv_harness_tests/test_stage_scoped_completion_percent.py` — new, 12
  tests.

## Residual concerns

- `dashboard.py`'s web UI (`GET /api/state`, the `showExplain()` JS
  formatter around line 743) was explicitly out of scope for this task
  (task named `gates.py`, `control_plane.py`, `cli.py` only) and was left
  untouched — it still only displays `gate_verdict`/`gate_reasons`/etc.,
  not the new `stage_completion_percent`. Since `describe_stage()`'s
  dict now carries the new fields, wiring them into that JS template
  string would be a small, low-risk follow-up if stage-scoped completion
  is wanted in the dashboard UI too, alongside the existing whole-run
  `overall_progress_percent` tile.
- None of the currently-registered `Stage` enum values actually reach the
  zero-registered-gates code path in production (every real stage has
  >=1 gate in `STAGE_GATES` today) — that path is real, tested, and
  correct, but currently only exercised via an unknown/synthetic stage id
  in tests, consistent with how `NO_GATE_REQUIRED` itself is already
  tested elsewhere in this codebase.
