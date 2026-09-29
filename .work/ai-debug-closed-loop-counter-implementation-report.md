# AI Debug Closed-Loop Counter Implementation Report

## What was built

The AI-mechanism architecture audit that motivated this task found two real, engine-enforced gaps
in the macro debug loop (Fix -> Push -> Build -> Verify -> RCA, routed via `main_graph.json`'s real
FAIL edges through `dv_harness/policy.py`'s `graph_next()`):

1. No cross-cycle "debug-loop round N" counter existed. `dv_harness/engine.py`'s
   `run_stage()`/`loop()` only ever maintain `state.stages[stage]['attempts']` (`ss['attempts']`),
   a per-graph-node RETRY counter capped by `policy.max_stage_retries` and reset to 0 the moment
   `current_stage` moves on. It cannot answer "how many full Fix->Push->Build->Verify passes has
   this failure gone through across the whole run", because one logical debug-loop round can span
   several different graph nodes (e.g. `BUILD` fails -> `FAILURE_RECOVERY` -> `CHANGE_IMPACT` ->
   ... -> `BUILD` again).
2. "Health Monitor" auto-dispatch on FAIL was not an autonomous engine event. CLAUDE.md's own
   "Background Job/Log Monitor Auto-Start" section is explicit that "there is no Python code path
   that fires automatically" here -- starting/checking the watcher is a protocol instruction the
   agent must remember to follow (`dv-harness lsf-watch-start`), never something
   `dv_harness/engine.py` invokes on its own.

Both are now closed by real, tested, wired code, confirmed by re-reading `engine.py`'s current
`run_stage()`/`advance()`/`loop()`/`_advance_with_fanout()` (the two real call sites that compute
`graph_next(stage, Status.FAIL.value, ...)` are `loop()`'s retry-exhaustion branch and
`_advance_with_fanout()`'s parallel-branch-failure branch) and `blackboard.py` in full before
making any change:

1. **`dv_harness/blackboard.py`** -- a new `"debug_loop_history"` topic plus three real methods,
   mirroring the existing `"findings"` registry pattern exactly (`read_debug_loop_history()`,
   `append_debug_loop_round(entry, source='')`, `debug_loop_round_count(failing_stage=None)`).
   Each entry is `{round_number, timestamp, failing_stage, target_fail_edge, attempt_number,
   node_route, health_monitor_check}`. `debug_loop_round_count()` is the real query that answers
   "how many full passes has this failure gone through" -- uncapped, cross-cycle, and countable
   both across the whole run and per failing stage.

2. **`dv_harness/engine.py`** -- two new `DVHarness` methods and two new call sites:
   - `_record_debug_loop_round(failing_stage, target)`: looks up the real graph node for
     `failing_stage`, appends one `debug_loop_history` entry via the Blackboard method above, and
     (for a remote/LSF-route stage) folds in a real Health Monitor check.
   - `_health_monitor_check(node)`: a real `subprocess.run([sys.executable, "-m", "dv_harness.cli",
     "--project-root", str(self.root), "lsf-watch-status"], cwd=str(self.root), capture_output=True,
     text=True, timeout=30, env=...)` call -- the exact invocation convention
     `dv_harness/gates.py`'s `run_gate()` already uses, and the exact `-m dv_harness.cli` module
     form this project's own CLI subprocess tests (`test_cli_explain_subcommand_prints_de_explainer`
     etc.) already use, rather than the installed `dv-harness` console-script name. `PYTHONPATH` is
     extended (never replaced) with the real `dv_harness` package's own parent directory
     (`_ENGINE_PACKAGE_ROOT = Path(__file__).resolve().parent.parent`), so the module import
     resolves correctly regardless of where `self.root` (the DV project being verified, an
     unrelated directory) happens to be, or whether the package is pip-installed. Its real stdout is
     parsed as JSON (the same shape `regression_reporter.watcher_status()` -> the CLI's
     `lsf-watch-status` handler already prints) and returned verbatim as evidence; a subprocess
     failure is recorded as real negative evidence (`{"ok": false, "error": ...}`), never fabricated
     as a pass, and never raises out of the health check itself.
   - `REMOTE_LSF_ROUTES = {"build-route", "regression-route"}` module-level constant, with the two
     new call sites: `loop()`'s retry-exhaustion branch now calls
     `self._record_debug_loop_round(stage, n)` immediately after computing
     `n = graph_next(stage, Status.FAIL.value, self.root)` (before the react-reroute hint can
     override `n`, so `target_fail_edge` always reflects the graph's own real FAIL edge target, not
     a content-driven override); `_advance_with_fanout()`'s parallel-branch-failure branch calls the
     same method right after its own `graph_next(b, Status.FAIL.value, self.root)` call.

3. **`dv_harness/stage_profile.py`** -- a pre-existing bug fix, found while running the full
   regression suite for this task (see "Tests" below): a new `_read_json_retrying()` helper, the
   read-side counterpart of `storage.py`'s existing `_atomic_replace()` retry-on-`PermissionError`,
   now backs `StageExecutionProfiler._load()`/`all_stages()`.

## Rulings made

- **RULING**: `REMOTE_LSF_ROUTES = {"build-route", "regression-route"}`. `graph.py`'s `Node`
  dataclass carries no explicit "remote"/"lsf" boolean field, so per the task's "do not guess"
  instruction, this was decided from the one real categorical field that actually exists --
  `node.route` -- cross-checked against `main_graph.json`'s real node definitions:
  `DE_BASELINE_REPRODUCTION`/`SERVER_SYNC`/`BUILD`/`BUILD_DEBUG`/`VERIFY` (`build-route`) and
  `REGRESSION_SELECT`/`REGRESSION`/`REGRESSION_MONITOR`/`COVERAGE_CLOSURE`/`INFRA_RECOVERY`
  (`regression-route`) are the only nodes whose real `skills` (`vcs-build`, `devops-pipeline`,
  `verification-signoff`) and templates
  (`dv_harness/uvm_generator/templates/sim_scripts/lsf_run.sh`/`lsf_regress.sh`/`lsf_wait.sh`)
  actually submit or poll a VCS build or LSF regression job. `analysis-route`/`implementation-route`/
  `review-route`/`debug-route`/`lead-route` nodes never submit one themselves (e.g.
  `WAVE_ANALYSIS`/`FAILURE_RECOVERY` only ever read evidence a remote run already produced). Locked
  in by a regression test (`test_remote_lsf_routes_ruling_matches_documented_build_and_regression_nodes`)
  that asserts this exact node-id set from the real graph.
- **RULING**: the Health Monitor dispatch only ever performs the STATUS CHECK
  (`dv-harness lsf-watch-status`, i.e. `regression_reporter.watcher_status()`), never
  `lsf-watch-start`, and never touches the SSH/Telnet remote hop or
  `tools/remote/remote_relay.py`'s invocation restrictions. The Telnet/SSH remote hop and the
  decision to start a watcher remain the deliberate, policy-mandated human/agent step CLAUDE.md's
  "SSH/Remote Transport Connection Intake" gate and "Background Job/Log Monitor Auto-Start" section
  both document; automating either from inside FAIL-edge routing would silently bypass that gate.
  This is explicit in both the engine.py docstrings and a dedicated test assertion
  (`"lsf-watch-start" not in hc["command"]`).
- **RULING**: one `debug_loop_history` entry is appended per retry-exhaustion FAIL-edge routing
  decision (i.e. once per real call to `graph_next(stage, Status.FAIL.value, ...)`), not once per
  individual stage attempt -- `ss['attempts']` already tracks individual attempts within one node;
  this counter answers the different, higher-level question the task asked for ("how many full
  passes"), so double-counting attempts here would conflate the two concepts the task explicitly
  distinguishes.
- **RULING**: `_record_debug_loop_round()` is called with the graph's own real FAIL-edge target
  (`n = graph_next(...)`) in `loop()`, BEFORE the pre-existing react-reroute hint is consulted and
  can override `n`. Per CLAUDE.md's "Graph is the global workflow authority", `target_fail_edge`
  should record what the graph itself says, not a content-driven override -- the hint remains a
  routing preference layered on top, and is not the fact this history entry exists to record.
- **RULING**: `PYTHONPATH` is extended (not replaced, and not relying on `cwd`) for the
  `-m dv_harness.cli` subprocess call. `cwd=str(self.root)` matches `run_gate()`'s own convention,
  but `self.root` is the arbitrary DV project directory being verified -- not necessarily anywhere
  `dv_harness` itself is importable from -- confirmed empirically (`python -c "import dv_harness"`
  fails from an unrelated directory with no `PYTHONPATH`/install). Extending `PYTHONPATH` with
  `_ENGINE_PACKAGE_ROOT` (derived from `engine.py`'s own `__file__`) makes the call correct
  regardless of `self.root`'s location or whether the package is pip-installed, without changing
  `cwd` away from the real project root the CLI is meant to operate on.
- **RULING**: the pre-existing `stage_profile.py` `PermissionError` found during full-suite testing
  (see "Tests" below) was fixed rather than left as a known flake, per the general task rules
  ("if you find a pre-existing bug while testing, fix it and note it"). The fix is scoped narrowly
  to the exact module/functions that actually failed (`StageExecutionProfiler._load()`/
  `all_stages()`), mirroring `storage.py`'s own already-reviewed `_atomic_replace()` retry shape
  (10 attempts, `0.02*(attempt+1)` backoff) rather than inventing a new pattern. `StateStore.load()`
  has the same theoretical read-during-replace exposure but was never observed to fail and was left
  untouched -- see "Concerns" below.

## Tests

Five new tests added to `dv_harness_tests/test_engine_gates_and_routing.py` (existing file and
convention -- this project has no separate `test_blackboard*.py`; Blackboard behavior is already
tested through this file, e.g. the existing `findings_counts()`/`upsert_finding()` tests):

- `test_blackboard_debug_loop_history_round_trip_and_cross_cycle_query` -- direct
  `Blackboard.append_debug_loop_round`/`read_debug_loop_history`/`debug_loop_round_count` unit
  test: round numbering, whole-run count, and per-`failing_stage` count.
- `test_remote_lsf_routes_ruling_matches_documented_build_and_regression_nodes` -- regression-locks
  the `REMOTE_LSF_ROUTES` ruling against the real `main_graph.json` node set.
- `test_record_debug_loop_round_only_health_checks_remote_lsf_route_stages` -- calls
  `DVHarness._record_debug_loop_round()` directly for a non-remote stage (`FAILURE_RECOVERY`,
  `health_monitor_check` must stay `None`) and a remote/LSF stage (`VERIFY`) -- the real subprocess
  call actually runs and its real `{"running": false, "pid": null}` result lands in the entry;
  also asserts `lsf-watch-start` never appears in the invoked command.
- `test_loop_records_debug_loop_history_across_a_full_fail_edge_pass` -- full end-to-end wiring
  test through the real `loop()`: `VERIFY` (`build-route`) fails via `ADAPTER_FAIL` with
  `max_stage_retries=0`, routes via the graph's real FAIL edge to `FAILURE_RECOVERY`
  (`debug-route`), which itself also fails and exhausts immediately (`FAILURE_RECOVERY` has no FAIL
  edge in `main_graph.json`, so `loop()` stops there) -- asserts exactly two real, persisted
  `debug_loop_history` entries, with the Health Monitor check present only on the first
  (`build-route`) entry.
- `test_health_monitor_check_records_real_failure_when_subprocess_errors` -- a broken
  `sys.executable` path (patched) must produce a real `{"ok": false, "error": ...}` record, never
  raise, and never be fabricated as a pass.

**Pre-existing bug found and fixed during testing**: the first full `dv_harness_tests/` run (1553
tests, 655s) surfaced one real failure unrelated to the code above --
`test_graph_parallel_dispatch.py::test_engine_fanout_join_does_not_proceed_when_one_branch_fails`
raised a bare `PermissionError` (WinError 5) inside `StageExecutionProfiler.all_stages()`'s
glob-read, racing a concurrent `ThreadPoolExecutor` branch's own atomic `os.replace()` write --
the read-side counterpart of a Windows `MoveFileEx` race `storage.py`'s `_atomic_replace()`
docstring already documents and already retries on the *write* side. Confirmed as this exact
pre-existing race (not something my change introduced): the failing traceback occurs entirely
inside `_run_branch_to_terminal()`'s call chain, before `_advance_with_fanout()` ever reaches my
new `_record_debug_loop_round()` call site; the same test passed 5/5 in immediate isolated re-runs
(no fix), confirming a narrow concurrency timing window rather than a logic bug triggered by new
code. Fixed with a new `_read_json_retrying()` helper in `dv_harness/stage_profile.py` (see
"Rulings" above), backed by two new regression tests:
`test_stage_profiler_read_retries_transient_windows_permission_error` (a simulated 2x-transient
`PermissionError` is retried past, not swallowed on the first hit) and
`test_stage_profiler_read_eventually_raises_on_persistent_permission_error` (a persistent lock
still raises for real after retries exhaust -- never silently swallowed).

Targeted run: `python -m pytest dv_harness_tests/test_engine_gates_and_routing.py -q` --
**195 passed** (188 pre-existing + 7 new: the 5 debug-loop/health-monitor tests plus the 2
`stage_profile` regression tests), 0 failed.
`python -m pytest dv_harness_tests/test_engine_gates_and_routing.py dv_harness_tests/test_graph_parallel_dispatch.py -q`
-- **201 passed**, 0 failed.

Full existing suite run for regressions, run twice:
- Before the `stage_profile.py` fix: `python -m pytest dv_harness_tests/ -q` -- **1 failed, 1552
  passed** in 655s (the pre-existing `PermissionError` flake described above; every other test,
  including all new ones, passed).
- After the fix: `python -m pytest dv_harness_tests/ -q` -- **1555 passed**, 0 failed, 0 skipped, in
  941s (0:15:41). No pre-existing test needed modification.

## Concerns / residual gaps

- `_advance_with_fanout()`'s call site (`self._record_debug_loop_round(b, n)` right after its own
  `graph_next(b, Status.FAIL.value, self.root)`) is exercised indirectly -- the shared method it
  calls is fully covered by direct unit tests above, and the one-line call site itself is identical
  in shape to `loop()`'s already end-to-end-tested call site -- but no dedicated end-to-end
  `ANALYSIS_G1` fan-out-failure test was added, since standing up a full 3-way parallel-fan-out
  failure scenario (`PROTOCOL_CAPABILITY` -> `REQUIREMENTS_TRACEABILITY`/`SOC_SCENARIO_PLANNER`/
  `INFRASTRUCTURE_AUDIT` -> `ANALYSIS_JOIN`) adds significant fixture complexity for a call site
  that reuses exactly the same, already-tested method with no additional logic of its own.
- The Health Monitor check is a real, best-effort, additive side effect exactly like every other
  post-gate side effect already in this file (`_promote_experience_knowledge`,
  `_persist_subsystem_registry_entry`, etc.) -- a subprocess failure or an unreachable watcher never
  blocks or alters the FAIL-edge routing decision itself, only what gets recorded alongside it. This
  is intentional (per the task's own framing: "this makes the health-check step something the
  engine actually performs on FAIL", not a new precondition for routing) but is worth noting
  explicitly: a stage's FAIL-edge routing behavior is unchanged by this task; only the evidence
  trail around it is new.
- Per the task's explicit instruction, `tools/remote/remote_relay.py`'s invocation restrictions were
  read but not touched, and no code path added here ever invokes `remote_relay.py`, starts a
  watcher, or performs the SSH/Telnet remote hop -- **that hop remains a deliberate,
  policy-mandated human step per CLAUDE.md and was deliberately NOT automated by this task.** The
  only new subprocess call this task adds is a read-only `dv-harness lsf-watch-status` check
  (equivalent to a human/agent typing the same command); it never starts a watcher, never opens or
  assumes an SSH/Telnet session, and never touches credentials.
- `StateStore.load()` (`storage.py`) has the same theoretical Windows read-during-`os.replace()`
  race the `stage_profile.py` fix above closes (it reads `state.json` while `dashboard.py`'s
  background run thread can concurrently `save()` it), but it was never observed to fail in this or
  any prior full-suite run. Left untouched rather than speculatively "fixed" without a reproduced
  failure -- flagging it here as a real, narrow, pre-existing candidate for the same
  `_read_json_retrying()`-style treatment if it is ever observed to fail for real.
