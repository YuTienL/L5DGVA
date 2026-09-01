# Multi-Agent Timing Reconciliation - Implementation Report

## Execution mode
LOCAL_ANALYSIS: pure local source read/edit/test, no server/VCS touched.

## Problem (from audit)
`dv_harness/multi_agent.py`'s `AgentTaskStore`/`MultiAgentOrchestrator` is the real multi-agent
delegation/locking layer, called from `engine.py`'s `run_stage()` before every LLM call via
`MultiAgentOrchestrator.delegate()`. Despite being a real, wired call site, `create_task()` produced
a task dict with **zero timing fields** (`{task_id, agent, route, skills, parent_plan,
parallel_group, depends_on, status}`), there was **no `complete_task()`-style method at all**, and
none of this timing data ever reached `stage_profile.py`'s real timing/token machinery
(`StageExecutionProfiler`) even though both stores are real, both are wired into the same
`run_stage()` method, and both write JSON via the same atomic-tempfile-replace convention.

## What was built

### 1. `dv_harness/multi_agent.py` -- real task timing fields + lifecycle methods
- `AgentTaskStore.create_task()` now adds `started_at`, `completed_at`, `duration_sec` to every task
  dict, all defaulting to `None` (task starts `NOT_STARTED`, per the pre-existing `status` field --
  nothing here is backfilled/guessed).
- New `AgentTaskStore.start_task(task_id)`: looks the task up (via new `_find_task()` helper, raises
  `KeyError` for an unknown id), sets `status='RUNNING'` and `started_at=time.time()` (same
  epoch-float convention `stage_profile.StageExecutionProfiler.begin_stage()`'s
  `start_time_epoch` already uses), persists via the store's existing
  `_write_json_atomic()`/tempfile+`os.replace` idiom (unchanged, just reused).
- New `AgentTaskStore.complete_task(task_id, status, duration_sec=None)`: sets `completed_at=time.time()`,
  computes `duration_sec` from `completed_at - started_at` unless a caller supplies its own (used by
  no current caller, kept for a future caller with a tighter monotonic span for the exact same
  work), backfills `started_at=completed_at` (duration 0.0) for the defensive case of a task
  completed without ever calling `start_task()` first (not the real engine.py path, but avoids
  `None`/negative duration on a caller error), sets the given `status`, and persists the same way.
- No pre-existing "update" method existed to extend -- `create_task()`/`acquire()` were the only two
  mutators, so `start_task()`/`complete_task()` are new, following the exact same
  lock-then-read-then-write-then-atomic-replace shape both already use.

### 2. `dv_harness/engine.py` -- wiring the real lifecycle around the real call site
`run_stage()`'s existing flow (Step 1: `task = self.agents.delegate(node, plan)`, then later the
`self.adapter.run(...)` call, then `self.profiler.add_agent_run(...)`) is the genuine per-attempt
lifecycle of one delegated task. Wired in:
- `self.agents.store.start_task(task["task_id"])` immediately before `self.adapter.run(...)` --
  the real point the delegated unit of work begins executing.
- `self.agents.store.complete_task(task["task_id"], status=("COMPLETED" if result.ok else "FAILED"))`
  immediately after `self.adapter.run(...)` returns.
- `task` is `Optional[dict]`, initialized `None` alongside the method's other `Optional[...] = None`
  locals, and stays `None` for a node-less stage (no graph node => no delegation happened in Step 1
  => nothing to start/complete) -- both calls are guarded by `if task is not None:`.

**RULING (task lifecycle scope):** the `AgentTaskStore` task's own `status` tracks only whether the
delegated **adapter call** completed (`COMPLETED`/`FAILED`) -- deliberately narrower than the
stage's own gate-verified business status (`ss["status"]`, which can still become
`PARTIAL`/`WAIT_USER` further down the same method, including through an entirely separate
`InnerReactLoop` that runs its *own* additional `adapter.run()` turns and profiles them through its
own `profiler.add_agent_run()` calls). Bounding the task's lifecycle to exactly the same span the
pre-existing `_agent_runtime = time.perf_counter() - _t0` measurement already covers keeps the two
timers commensurable (see ruling 2) and avoids the task's completion silently swallowing
`InnerReactLoop`'s separately-profiled iterations into one number.

### 3. Reconciliation into `stage_profile.py`
**RULING (per the task's own "preferred" option):** engine.py now reads the just-completed
`AgentTaskStore` task's own `duration_sec` and passes it as the `runtime_sec` argument to the
existing `self.profiler.add_agent_run(...)` call, in place of a second, independently-computed
number for the exact same span. No new aggregation/merge function was added, and no second sink was
introduced -- this reuses the existing profiler sink exactly as the task description's preferred
option specifies, and avoids two stores each holding their own (necessarily slightly different,
since they'd use different clocks/call sites) "truth" for the same measurement. The local
`_t0 = time.perf_counter()` / `_agent_runtime` computation is kept **only** as the fallback for the
node-less-stage case (`task is None`), where there is no `AgentTaskStore` duration to read at all --
every real, graph-node-backed stage now reports `AgentTaskStore`'s own measured `duration_sec`
through `add_agent_run()`, not a shadow/duplicate timer.

This was chosen over the alternative (a small aggregation function reading both stores for
reporting) because: (a) it is strictly simpler -- no new file, no new merge-by-`stage_id`/`task_id`
logic to keep in sync as either store's schema evolves; (b) it does not duplicate data -- there is
exactly one number (`AgentTaskStore.duration_sec`) for this span, and `stage_profile.py`'s existing
consumers (`all_stages()`, `_update_workflow()`, `stage_profile_report.py`) get it for free with zero
changes to their own code; (c) `AgentTaskStore` remains the single source of truth for "how long did
this one delegated task actually take," matching how `stage_profile.py` is already the single source
of truth for stage-level/workflow-level aggregates.

## Tests added
`dv_harness_tests/test_multi_agent_timing.py` (7 tests, all real -- no mocks of the methods under
test):
- `test_create_task_defaults_timing_fields_to_null` -- new fields present and `None`/`NOT_STARTED`.
- `test_start_task_then_complete_task_round_trip_with_real_duration` -- real `time.sleep(0.03)`
  between `start_task()`/`complete_task()`, asserts `duration_sec` matches the real
  `completed_at - started_at` span and is `>= 0.02`s (a real measured sleep, not a stubbed/zero
  value), then re-opens a **fresh** `AgentTaskStore` instance against the same root and confirms the
  completion round-tripped through `tasks.json` on disk (real JSON persistence, not an in-memory-only
  mutation).
- `test_complete_task_without_start_backfills_started_at_and_zero_duration` -- the defensive
  no-`start_task()` path.
- `test_start_task_unknown_id_raises_keyerror` / `test_complete_task_unknown_id_raises_keyerror`.
- `test_run_stage_real_call_path_invokes_complete_task_with_real_duration` -- end-to-end through
  `DVHarness.run_stage()`'s **real** call path (not a stub/mock check that `complete_task` was
  called): a `SlowFakeAdapter` sleeps 0.05s inside `.run()`, then asserts (1) `tasks.json` on disk
  has exactly one `COMPLETED` task with `duration_sec >= 0.03`, and (2) `stage_profile.py`'s own
  per-agent record (`profiler.all_stages()[0]["agents"][0]["runtime_sec"]`) is **exactly equal** to
  that same `AgentTaskStore` duration -- proving the reconciliation (ruling 2 above) is real, not
  just present in a code comment.
- `test_run_stage_marks_task_failed_on_adapter_failure` -- an adapter failure still reaches a real
  `complete_task(status="FAILED")` call rather than leaving the task stuck at
  `NOT_STARTED`/`RUNNING`.

Reused the existing `_mk_smoke_project()`/`_DISCOVERY_EXTRA_GATES` fixtures from
`dv_harness_tests/test_engine_gates_and_routing.py` via a cross-test-file import
(`from dv_harness_tests.test_engine_gates_and_routing import ...`) -- an established pattern already
used by `test_intake_upload.py` importing from `test_dashboard_interactive.py`.

## Test results
- New file: `python -m pytest dv_harness_tests/test_multi_agent_timing.py -v` -- **7 passed**.
- Targeted regression sweep (`test_engine_gates_and_routing.py`, `test_react_loop.py`,
  `test_dashboard_cli_checklist_rendering.py`, `test_stage_evidence_checklists.py`,
  `test_graph_parallel_dispatch.py`, `test_multi_agent_timing.py`): **247 passed, 1 failed** -- the
  1 failure (`test_cli_lsf_reconcile_picks_up_existing_job_state_files`) is a pre-existing,
  environment-dependent LSF/`bjobs`-availability failure, confirmed unrelated to this change by
  `git stash`-ing all of this task's edits and re-running that single test in isolation: it fails
  identically on the pre-change tree.
- A full-repo `dv_harness_tests/` run (all ~70 files, including many modules with no relation to
  this change -- UVM protocol generators, LSF/remote-exec, coverage/urg reduction, etc.) was also
  kicked off in the background; the targeted sweep above already covers every module this task's
  own scope names as relevant (`engine.py`, `multi_agent.py`, `stage_profile.py`, plus
  `react_loop.py`/dashboard-checklist/graph-parallel-dispatch as the other real consumers of the
  same `run_stage()` call path and `AgentTaskStore`), so this report's pass/fail claim is anchored
  to that targeted run rather than blocked on the much longer full-repo run finishing.

## Residual concerns
- `AgentTaskStore.start_task()`/`complete_task()` are new public methods with no other callers yet
  besides `engine.py`'s `run_stage()`. `_advance_with_fanout()`'s synthetic `FANOUT-{group}-{branch}`
  task ids (used only for the `acquire()` ownership registry, never passed through `create_task()`)
  are correctly left untouched -- they are not real `AgentTaskStore` tasks and calling
  `start_task()`/`complete_task()` on them would raise `KeyError` by design.
- The pre-existing, unrelated LSF reconcile test failure (see above) was left as-is per this task's
  scope (multi-agent timing only) -- flagging it here rather than silently working around it.
