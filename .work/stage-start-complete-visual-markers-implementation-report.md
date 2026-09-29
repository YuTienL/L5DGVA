# Stage Start/Complete Visual Markers -- Implementation Report

Closes the audit finding: no visual "stage started"/"stage completed" marker
existed anywhere. `dashboard.py`'s status tiles updated silently on a 3s
poll with no distinct "just happened" signal, and `cli.py` printed only the
agent's own free-text reply, after the stage had already finished, with no
stage-transition-specific banner.

## What was built

### 1. `engine.py`: `run_stage()` itself emits both markers

`dv_harness/engine.py` gained two module-level helpers plus a shared prefix
constant:

```python
STAGE_MARKER_PREFIX = "[DV-HARNESS-STAGE]"

def _emit_stage_start_marker(stage: str) -> None: ...
def _emit_stage_done_marker(stage: str, gate_verdict: str, stage_completion_percent) -> None: ...
```

- **Entry marker** -- `_emit_stage_start_marker(stage)` is called inside
  `run_stage()` immediately *after* the existing TAKEOVER short-circuit
  (a takeover'd call never actually starts the stage, so it must not print a
  START it never earns) and *before* any state mutation (`ss["status"] =
  RUNNING`, `attempts += 1`, etc.), so it fires exactly once per real
  attempt:
  ```
  [DV-HARNESS-STAGE] ===== STAGE START: DISCOVERY =====
  ```
- **Exit marker** -- `_emit_stage_done_marker(...)` is called right before
  `run_stage()`'s final `return result`, after `ss["status"]` has reached
  its terminal value and after `self.profiler.end_stage()` has already run:
  ```
  [DV-HARNESS-STAGE] ===== STAGE DONE: DISCOVERY [PASS] (100% gates satisfied) =====
  ```
  The `[verdict]`/`percent%` values are sourced from
  `control_plane.describe_stage(self.root, self.state, stage)` -- the SAME
  read path `dv-harness explain`/`evidence`/`checklist` already use -- rather
  than reusing `run_stage()`'s own local `verdict` variable, because that
  local variable is only ever assigned inside the `result.ok` branch; an
  `ADAPTER_FAIL` (`result.ok is False`) never assigns it at all.
  `describe_stage()` recomputes `gate_verdict`/`stage_completion_percent`
  uniformly from `ss["last_message"]` for every exit path, so the marker is
  byte-consistent with what the CLI would already report for that same
  attempt, on every branch (PASS, FAIL, PARTIAL, WAIT_USER, NEEDS_USER_INPUT,
  exhausted-retries).

Because both calls live inside `run_stage()` itself (not `cli.py`), both the
CLI (`dv-harness run-stage`, `dv-harness start`) and any future direct caller
of `DVHarness.run_stage()` (the dashboard's background runner, a future API
server, a test harness) get the identical visible signal -- no consumer has
to separately notice a silent status change.

**RULING (logging vs. plain print):** grepped `dv_harness/` project-wide for
`logging.getLogger`/`logging.basicConfig` -- zero hits. Every existing
CLI/engine output path already uses plain `print()`. Introducing Python's
`logging` module here alone would create a second, inconsistent output
convention for one feature. Both markers use plain `print(..., flush=True)`
to stdout instead, with the real, greppable, unique prefix
`[DV-HARNESS-STAGE]` (`grep '\[DV-HARNESS-STAGE\]' run.log`) so they are
trivially distinguishable from surrounding agent free-text output.

### 2. `models.py` / `engine.py`: persisted "just transitioned" signal

`HarnessState` gained one new, additive, backward-compatible field:

```python
last_transition: Optional[Dict[str, Any]] = None
```

`run_stage()` sets it right after `ss["status"]` reaches its final terminal
value for this attempt (same spot the exit marker fires):

```python
self.state.last_transition = {"stage": stage, "status": ss["status"], "at": now()}
self.store.save(self.state)
```

`StateStore.save()`/`load()` already round-trip `HarnessState.__dict__`
verbatim via `json.dump`/`HarnessState(**raw)`, so this required no storage
changes -- and because `dashboard.py`'s `GET /api/state` reads `state.json`
and re-serves the dict as-is (plus a bunch of *additional* computed fields),
`last_transition` reaches the frontend with **zero backend dashboard
changes** beyond the field's existence on `HarnessState`.

A `state.json` saved before this field existed has no `last_transition` key
at all -- `HarnessState(**raw)` degrades that to `None` (the dataclass
default), never a `KeyError`, matching the existing `last_evidence_blocks`
convention documented right above it in `models.py`.

### 3. `dashboard.py`: always-visible "Last transition" banner

Added:
- CSS: `.transitionBanner` plus one status-colored variant per status family
  (`PASS`/`CLOSED` green, `FAIL`/`BLOCKED` red, `PARTIAL`/`WAIT_USER`
  amber, `RUNNING`/`RETRY` blue, and a neutral `status-none` for "nothing
  has completed yet").
- HTML: a `<div class="transitionBanner status-none" id="lastTransitionBanner">`
  placed at the very top of `<main>`, above every card (including the Setup
  card), so it is the first thing a viewer sees on any page state.
- JS: `renderLastTransitionBanner(lastTransition)`, called from `load()`
  right after `/api/state` returns, rendering
  `"<stage> → <status> at <time>"` and swapping the banner's status-colored
  CSS class to match.

**RULING (always-visible vs. time-limited flash):** the task explicitly
left this choice open ("your call, document the ruling"). Chose
**always-visible**, not a flash that fades after N seconds, because:
- A flash that auto-hides is invisible to anyone who opens/refreshes the
  dashboard even a few seconds after the transition fired -- which
  reintroduces almost exactly the "silent, no distinct signal" gap this
  feature exists to close, just with a shorter fuse.
- An always-visible banner is trivially correct on every page load (no timer
  bookkeeping, no `localStorage` staleness math, no clock-skew edge cases
  between when the transition happened and when the viewer's browser
  believes "N seconds ago" is).
- It degrades honestly: `last_transition == null` (nothing has ever
  completed in this project) renders a clearly neutral "no stage has
  completed yet this run" state rather than an empty/missing element.

This ruling and its rationale are also recorded as a code comment directly
above `renderLastTransitionBanner()` in `dashboard.py`.

## Files changed

- `dv_harness/engine.py` -- `STAGE_MARKER_PREFIX`, `_emit_stage_start_marker`,
  `_emit_stage_done_marker`; wired at stage entry (after the TAKEOVER check)
  and stage exit (before `return result`); `self.state.last_transition`
  set and persisted at stage exit.
- `dv_harness/models.py` -- `HarnessState.last_transition: Optional[Dict[str, Any]] = None`.
- `dv_harness/dashboard.py` -- `.transitionBanner` CSS, the banner `<div>`,
  and `renderLastTransitionBanner()` wired into `load()`. No backend
  (`do_GET`) changes needed -- `last_transition` flows through the existing
  `state = _read_json_file(state_file, ...)` pass-through.
- `dv_harness_tests/test_stage_transition_visual_markers.py` (new) -- 7 tests,
  see below.

## Tests added

All 7 new tests pass; see `dv_harness_tests/test_stage_transition_visual_markers.py`.

1. `test_run_stage_emits_start_and_done_markers_on_stdout` -- captures real
   stdout (`capsys`) across a real `run_stage()` call and asserts both exact
   marker lines appear, in the correct order (START strictly before DONE).
   Deliberately exercises a stage (`DISCOVERY`) that DOES have mapped
   `STAGE_GATES` entries with no evidence supplied, asserting the DONE
   marker honestly reports `[MISSING_EVIDENCE] (0% gates satisfied)` even
   though `policy.require_stage_gate_evidence=False` let `ss["status"]`
   itself close as PASS -- proving the marker is sourced from
   `describe_stage()`'s independent, unconditional gate recomputation
   (identical to what `dv-harness explain`/`evidence` already show for this
   scenario), not from a value that could be silently gamed by the policy
   flag.
2. `test_run_stage_start_marker_is_suppressed_under_active_takeover` -- a
   TAKEOVER'd `run_stage()` call must print no marker at all (it never
   starts the stage).
3. `test_run_stage_done_marker_reflects_a_real_fail_verdict` -- an
   `ADAPTER_FAIL` path (where `run_stage()`'s own local `verdict` variable
   is never assigned) still emits a well-formed DONE marker, proving the
   `describe_stage()`-sourced fallback covers this branch.
4. `test_last_transition_persisted_into_state_json_after_a_pass` -- asserts
   both the in-memory `h.state.last_transition` dict AND the raw on-disk
   `state.json` carry the correct `{stage, status, at}` shape after a PASS.
5. `test_last_transition_persisted_after_an_adapter_fail_and_reloads_via_state_store` --
   reloads via a *fresh* `StateStore(tmp).load()` (not the in-process
   `h.state` object) to prove this is real on-disk persistence, not just an
   in-memory attribute; covers the `ADAPTER_FAIL` -> `Status.FAIL` path.
6. `test_last_transition_updates_across_successive_stage_runs` -- runs two
   different stages back-to-back and asserts `last_transition` reflects only
   the most recent one, with a distinct timestamp each time.
7. `test_dashboard_get_state_forwards_last_transition_verbatim` -- uses
   `dashboard._read_json_file` (the exact helper `GET /api/state` calls) to
   prove the field reaches that read path with no dedicated dashboard-side
   plumbing required.

## Test results

- New test file: `python -m pytest dv_harness_tests/test_stage_transition_visual_markers.py -q`
  -> **7 passed**.
- Full existing suite: `python -m pytest dv_harness_tests -q`
  -> **1285 passed, 1 failed** in 816.84s.
  - The one failure, `test_engine_gates_and_routing.py::
    test_cli_lsf_reconcile_picks_up_existing_job_state_files`, is
    **pre-existing and unrelated**: verified by `git stash`-ing this
    feature's changes and re-running that single test against the
    unmodified branch tip (`6f61476`) -- it fails identically (`assert 0 ==
    1`, `AssertionError`). It asserts `dv-harness lsf-reconcile --all`
    returns exit code 1 (a CRITICAL discrepancy) on the premise that `bjobs`
    is not on PATH in the test environment; in this environment the
    reconcile instead reports a WARN-severity discrepancy and exits 0 --
    an environment/tooling difference, not anything touched by this
    pass (LSF client, gates, or CLI argument wiring were not modified).

## Residual concerns

- `describe_stage()`'s gate-verdict recomputation is **independent** of
  `policy.require_stage_gate_evidence` (it always re-evaluates
  `STAGE_GATES` against the stage's last message, regardless of that
  policy flag). This means the STAGE DONE marker's `[verdict]`/`percent%`
  can genuinely disagree with `ss["status"]` when that policy flag is
  disabled and the stage has mapped gates with no evidence supplied (see
  test 1 above, deliberately exercising exactly this case). This is
  **pre-existing** `describe_stage()` behavior already relied on by
  `dv-harness explain`/`evidence`/`checklist` -- not introduced or changed
  by this pass -- but is worth flagging since the marker now surfaces it
  more prominently (unconditionally, on every stage exit, not just on an
  explicit `explain`/`evidence` call).
- Two files in the worktree (`.dv-harness/events.jsonl`,
  `.dv-harness/state.json`) picked up incidental writes from running the
  real test suite against this project's own live `.dv-harness/` state
  (self-audit / CLI-invoking tests write real `CLI_ACCESS` events and
  re-save `state.json` with the new `last_transition: null` default). These
  are test-run side effects on the live project state, not part of this
  feature's actual code change, and were deliberately left out of this
  commit's staged files.
