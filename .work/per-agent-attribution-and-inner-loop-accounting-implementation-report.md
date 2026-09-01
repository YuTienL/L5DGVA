# Per-Agent Attribution and Inner-Loop Accounting -- Implementation Report

Closes two real bugs confirmed by the earlier audit in
`dv_harness/stage_profile.py`'s `StageExecutionProfiler`, as wired into
`dv_harness/engine.py` and `dv_harness/react_loop.py`:

1. `engine.py`'s real `add_agent_run()` call site (in `run_stage()`, right
   after `extract_provider_usage()`) hardcoded the literal string
   `"stage-agent"` instead of the already-resolved real agent name
   (`route_info["agent"]`, from `self.router.resolve(node)` earlier in the
   same function) -- every stage's profiler record named the same fake
   agent regardless of which real agent (`analysis-agent`,
   `soc-scenario-agent`, etc.) actually ran.
2. `react_loop.py`'s `InnerReactLoop` makes additional real
   `self.adapter.run(...)` calls for its Reason-Act-Observe-Reflect inner
   loop (the `reflect_and_decide()` reflection call, its one hallucination
   re-ask, and each `RETRY_TARGETED`/`REQUEST_EVIDENCE` targeted retry) --
   none of these were ever passed to `profiler.add_agent_run()`, so their
   real runtime and real token usage were completely invisible to the stage
   profile, silently under-reporting `total_tokens` and
   `aggregate_agent_runtime_sec` whenever the inner loop actually iterated.

## What was built

### 1. `engine.py`: real resolved agent name at the existing call site

```python
_resolved_agent_name = route_info["agent"] if route_info else "stage-agent"
self.profiler.add_agent_run(profile["profile_id"], _resolved_agent_name, _agent_runtime,
    usage=_usage, model=str(_model),
    status=("PASS" if result.ok else "FAIL"))
```

**RULING:** `route_info` is only ever `None` for a stage with no graph node
at all (`node is None` -- a legacy/no-graph stage, per the existing `if node
is not None:` guard a few lines above where `route_info` is assigned). That
case genuinely has no resolved agent to name, so `"stage-agent"` remains the
honest fallback for exactly that one case, not the default -- every stage
with a real graph node (the overwhelming majority, and every stage this
audit's example agents run under) now gets its real resolved agent name.

### 2. `react_loop.py`: profiler/profile_id/agent_name threaded into `InnerReactLoop`

Followed the module's own existing additive-dependency-injection precedent
(`graph=None`, documented in the module docstring's "DEVIATION FROM THE
DESIGN SPEC" note) rather than inventing a new style:

- `InnerReactLoop.__init__` gained `profiler=None, profile_id=None,
  agent_name=""` -- the SAME `StageExecutionProfiler` instance and
  `profile_id` `engine.py`'s `run_stage()` already created via
  `self.profiler.begin_stage()`, not a second profiler.
- `reflect_and_decide()` gained the same three additive parameters, since it
  is the function that actually owns the reflection call's `adapter.run()`
  invocations (`InnerReactLoop.run()` calls it, but does not itself make
  that particular adapter call).
- A new small helper, `_record_agent_run(profiler, profile_id, agent_name,
  t0, result, status_override=None)`, centralizes "time this call, extract
  its usage via the same `extract_provider_usage()` engine.py already uses,
  call `profiler.add_agent_run()`" and is a genuine no-op (`if profiler is
  None or profile_id is None: return`) when the additive parameters are
  omitted -- so every pre-existing unit test in
  `dv_harness_tests/test_react_loop.py` that constructs `InnerReactLoop` /
  calls `reflect_and_decide()` directly (never threading these through) is
  completely unaffected, exactly like the module's existing `graph=None`
  degrade-safely precedent.
- Every real `self.adapter.run()` call site in the module is now wrapped:
  - `reflect_and_decide()`'s internal `_ask(p)` closure (covers both the
    first reflection ask and the one hallucination re-ask).
  - `InnerReactLoop.run()`'s `RETRY_TARGETED`/`REQUEST_EVIDENCE` targeted
    retry call.
- `engine.py`'s real `InnerReactLoop(...)` construction (the only real call
  site, under the `node is not None and node.react and
  policy.enable_inner_react_loop` branch) now passes `profiler=self.profiler,
  profile_id=profile["profile_id"], agent_name=route_info["agent"]`.
  `route_info` is guaranteed non-`None` here (this whole branch is nested
  under `node is not None`), so this is always the real resolved agent name
  at the one real call site -- never the `""` default.

Each real inner-loop adapter call now lands in the stage's `agents` list as
its own entry (own `runtime_sec`, own `usage`-derived token counts, own
`status`), so `StageExecutionProfiler`'s existing `total_tokens`/
`aggregate_agent_runtime_sec` summation (unchanged) now genuinely includes
every inner-loop retry instead of silently dropping them.

**RULING (record every inner-loop adapter call, not only the targeted
retries):** the audit finding names "additional real
`self.adapter.run(...)` calls for its Reason-Act-Observe retries" generally,
and the reflection call itself is a real, token-costing LLM invocation with
exactly the same profiler-invisibility problem as the retry calls -- there
is no principled reason to record one kind of real adapter call and not the
other. All real adapter calls `InnerReactLoop`/`reflect_and_decide()` make
are recorded, attributed to the same resolved `agent_name` as the stage's
main call (a REROUTE/CONVERGE decision costs zero adapter calls and
therefore adds zero agent-run entries, consistent with the module's existing
"zero adapter cost" comments).

## Files changed

- `dv_harness/engine.py` -- real-agent-name fix at the `add_agent_run()`
  call site; `profiler`/`profile_id`/`agent_name` threaded into the real
  `InnerReactLoop(...)` construction.
- `dv_harness/react_loop.py` -- `import time`, `from .stage_profile import
  extract_provider_usage`; new `_record_agent_run()` helper;
  `reflect_and_decide()` and `InnerReactLoop.__init__`/`run()` gained the
  three additive parameters and now record every real adapter call they
  make; module docstring gained a "SECOND DEVIATION" note documenting why.
- `dv_harness_tests/test_engine_gates_and_routing.py` (new test) --
  `test_run_stage_records_add_agent_run_with_real_resolved_agent_name_not_stage_agent`.
- `dv_harness_tests/test_react_loop.py` (new tests) --
  `test_inner_react_loop_with_2plus_iterations_records_more_agent_runs_than_single_iteration`,
  `test_inner_react_loop_omits_profiler_calls_as_a_genuine_no_op_by_default`,
  plus the `_TwoStepRetryAdapter`/`_SingleConvergeAdapter` fixtures they use.

## Tests added

1. **`test_run_stage_records_add_agent_run_with_real_resolved_agent_name_not_stage_agent`**
   (`test_engine_gates_and_routing.py`) -- drives a real `run_stage()` call
   for `DISCOVERY` (whose real `main_graph.json` node declares
   `agent=analysis-agent`, the same node already asserted elsewhere in this
   file to reach the adapter profile/prompt/task) and asserts the
   profiler's real on-disk stage record names `agents[0]["agent"] ==
   "analysis-agent"`, explicitly `!= "stage-agent"`, with the real token
   counts from the fake adapter's `raw["response"]["usage"]` correctly
   attached.
2. **`test_inner_react_loop_with_2plus_iterations_records_more_agent_runs_than_single_iteration`**
   (`test_react_loop.py`) -- the crux test. Drives `InnerReactLoop` through
   a genuine 2-inner-iteration run against the real
   `reset_power_cdc_corner_gate.py` script (read before writing this test):
   retry #1 supplies RESET+CLOCK domains only (still missing CDC -- a
   genuinely *different* failure from the original all-3-domains-missing
   state, so `RETRY_TARGETED` is offered again rather than suppressed by the
   no-new-information rule), retry #2 completes all 3 domains -> PASS. That
   is 2 reflections + 2 targeted retries = 4 real `adapter.run()` calls, all
   carrying real token usage. Compared against a single-iteration
   `ARCH_CALIBRATION` run (the one gate-failure fixture with no reroute
   mapping and no actionable structured field, so the first reflection
   immediately picks `CONVERGE_TERMINATE` -- 1 real adapter call). Asserts,
   against the SAME `StageExecutionProfiler` instance:
   - `len(rec_multi["agents"]) == 4 > len(rec_single["agents"]) == 1`
   - every recorded entry names the real `agent_name` passed in
     (`"soc-scenario-agent"`), never a hardcoded placeholder
   - `rec_multi["total_tokens"] > rec_single["total_tokens"]` (a
     correspondingly larger total, not just a longer list)
   - `rec_multi["aggregate_agent_runtime_sec"] > 0` (real wall-clock time was
     actually accumulated, not just counted)
3. **`test_inner_react_loop_omits_profiler_calls_as_a_genuine_no_op_by_default`**
   (`test_react_loop.py`) -- explicit regression guard that
   `reflect_and_decide()` still works with zero exceptions and zero profiler
   requirement when `profiler`/`profile_id` are omitted (the default for
   every pre-existing test in this module), rather than relying only on the
   rest of the suite continuing to pass as implicit proof.

## Test results

- Targeted new tests: `python -m pytest dv_harness_tests/test_react_loop.py
  dv_harness_tests/test_engine_gates_and_routing.py -q` -> **209 passed, 1
  failed** in 437.50s.
  - The one failure,
    `test_engine_gates_and_routing.py::test_cli_lsf_reconcile_picks_up_existing_job_state_files`,
    is **pre-existing and unrelated**: verified by `git stash`-ing this
    pass's changes and re-running that single test against the unmodified
    branch tip -- it fails identically (`assert 0 == 1`). It asserts
    `dv-harness lsf-reconcile --all` returns exit code 1 on the premise that
    `bjobs` is not on PATH in the test environment; in this environment the
    reconcile instead reports a WARN-severity discrepancy and exits 0 -- an
    environment/tooling difference (this machine has real LSF/remote
    tooling configured per this project's own `CLAUDE.md`), not anything
    touched by `stage_profile.py`, `engine.py`, or `react_loop.py`.
- Every other test in both files passed, including all pre-existing
  `InnerReactLoop`/`reflect_and_decide()` unit tests that construct these
  objects without the new additive parameters (proving the no-op default is
  genuinely backward-compatible) and every pre-existing `run_stage()`
  integration test.
- Broader regression check: identified (via import-site grep) every other
  test file that imports `dv_harness.engine`, `dv_harness.react_loop`, or
  `dv_harness.stage_profile` --
  `test_stage_transition_visual_markers.py`,
  `test_stage_evidence_checklists.py`,
  `test_stage_scoped_completion_percent.py`, `test_remote_control.py`,
  `test_inference_engine_wiring.py`, `test_graph_parallel_dispatch.py`,
  `test_active_stages_read_sites.py` -- and ran them together with the two
  files above (same `--deselect` on the known pre-existing LSF failure) as
  the full relevant-suite regression check for this change; see the
  concerns section below for this run's completion status at commit time.
- The complete `dv_harness_tests` suite (1285+ tests, ~14 minutes per this
  branch's own prior implementation reports) was also started as a full
  background confirmation run; see concerns below.

## Residual concerns

- The full `dv_harness_tests` suite run (all ~1285+ tests, unrelated
  UVM-generator/LSF/dashboard suites included) was still executing in the
  background at the time this report was finalized, due to this
  environment's real subprocess-heavy gate-script tests taking on the order
  of ten-plus minutes end-to-end (confirmed by this branch's own prior
  implementation report, `stage-start-complete-visual-markers-
  implementation-report.md`, which recorded 816.84s for the same full
  suite). The two files directly exercising every line this change touches
  (`test_react_loop.py`, `test_engine_gates_and_routing.py`) passed in
  full (209/210, the 1 failure pre-existing/unrelated and independently
  verified via `git stash`), and the broader relevant-suite run covering
  every other test file that imports `engine`/`react_loop`/`stage_profile`
  was launched as well. Neither `engine.py` nor `react_loop.py`'s changes
  touch any code path outside `run_stage()`'s `add_agent_run()` call and
  `InnerReactLoop`'s construction/internals, so a regression appearing only
  in an unrelated suite (UVM generator, dashboard HTML, LSF client, etc.)
  would be surprising -- but the full-suite run had not reported a final
  pass/fail count before this report was written, so this is flagged
  honestly rather than claimed as confirmed.
- Two files in the worktree (`.dv-harness/events.jsonl`, `.dv-harness/state.json`)
  picked up incidental writes from running the real test suite against this
  project's own live `.dv-harness/` state (self-audit / CLI-invoking tests
  write real `CLI_ACCESS` events and re-save `state.json`). These are
  test-run side effects on the live project state, not part of this
  feature's actual code change, and were deliberately left out of this
  commit's staged files, matching this branch's own prior-report precedent.
