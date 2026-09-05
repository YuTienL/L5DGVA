# Gap-close pass — AI Engine mechanism #2: Graph Orchestrator

**Result: NO_ACTION_NEEDED**

Audit verdict was WIRED_AND_FIRING with no concrete gap named. Per task rule 1, I
changed no code; I independently re-read every cited piece of evidence against the
*current* working tree (which other concurrent workstreams have moved since the
audit ran) and re-ran the relevant suites.

## Re-verification of the audit's cited evidence

All citations still hold. Line numbers have shifted because `dv_harness/engine.py`
carries an uncommitted concurrent modification (+167/-7); the substance is unchanged.

| Audit claim | Verified at (current tree) | Status |
|---|---|---|
| `GraphDefinition.next_for()` / `next_frontier()` parse the real graph | `dv_harness/graph.py:59-71` | Confirmed, unchanged |
| `graph_next()` is the single edge-matching engine, calling `next_for()` directly | `dv_harness/policy.py:27-59` | Confirmed |
| `advance()` calls `next_frontier(current_stage, PASS)` then `graph_next()` / `next_stage()` fallback, then mutates `current_stage` | `dv_harness/engine.py:3796-3846` (audit said 3747-3775) | Confirmed |
| `loop()`'s dry-run wrapper returns before the `while True:` containing `advance()` | `dv_harness/engine.py:4032-4033` — `if dry_run or bool(self._dry_run_cfg().get("enabled", False)): return self.run_stage(..., dry_run=True)` is the first statement | Confirmed (now also honours the config toggle; still a pure pre-loop wrapper) |
| `run_stage()`'s dry-run branch returns before `_emit_stage_start_marker` / `ss["status"]` / `attempts++` | dry-run return at `engine.py:3125`; marker at `:3153`; `ss["status"]=RUNNING` / `attempts += 1` at `:3168-3169` | Confirmed |
| `_degraded_gate()` sets `ss["status"] = WAIT_USER` so `loop()` parks before `advance()` | `engine.py:2853-2900` (comment block reasoning verbatim as quoted); `loop()`'s `if status in (BLOCKED, WAIT_USER): return` at `:4093` | Confirmed |
| Named regression test for the degraded-advance bug exists | `dv_harness_tests/test_harness_reliability.py:630-652`, `test_loop_does_not_advance_past_a_degraded_stage` | Confirmed |
| `_auto_checkpoint()` is a side call *after* the transition on the one real terminal exit path | `engine.py:3709`, after the verdict branches and immediately before step 7's "ONE real terminal exit point" block | Confirmed |
| Graph is really loaded and driving | `.dv-harness/graph/main_graph.json` = 41 nodes / 58 edges, first node `ENV_CHECK`; `.dv-harness/state.json` `current_stage == "ENV_CHECK"` | Confirmed (read-only; I ran no CLI command that mutates state) |

## Concurrent-edit check (task rule 4)

`dv_harness/engine.py` has an uncommitted concurrent modification from another
workstream in this pass. I inspected its hunk boundaries (`git diff -U0 | grep '^@@'`):
the last hunk starts at line 3673. `advance()` (3796), `_advance_with_fanout`/join
handling (3878-3982) and `loop()` (4013+) are **outside every hunk** — the concurrent
work touches stage-progress/marker emission, not the transition primitive. So the
graph orchestrator's wiring is unaffected by the in-flight edits.

## Tests (no change made, run to confirm the mechanism is green in the live tree)

`python -m pytest dv_harness_tests/test_harness_reliability.py dv_harness_tests/test_graph_parallel_dispatch.py dv_harness_tests/test_graph_runtime_removed.py -q` → **52 passed in 30.85s**.

One earlier combined run showed a single `PermissionError: [Errno 13] ... AppData\Local\Temp\...`
in `test_engine_dispatches_all_three_branches_concurrently_and_joins`. That is a
Windows temp-directory teardown race (`shutil.rmtree` against a dir still held by the
dispatch ThreadPoolExecutor's file handles), not a graph-logic failure: the test passes
6/6 in isolation and the combined run is green on re-run. Flaky teardown, pre-existing,
unrelated to mechanism #2 — not fixed here (out of scope for this gap-close pass), but
flagged for whoever owns test hygiene.

## Why no fix

The three recent additions (dry-run, auto-checkpoint, DEGRADED) all gate the *entry*
to `run_stage()`/`loop()` — they decide **whether** a real stage attempt happens.
None of them touches `advance()`, `graph_next()` or `GraphDefinition.next_frontier()`,
which remain the sole owners of "what happens next" once a real attempt reaches a real
terminal status. The one place that separation could have leaked (a degraded stage
falling through to the unconditional `advance()`) was already found in review, fixed,
and pinned by a named regression test that I ran and watched pass. There is no gap to
close for mechanism #2.

**Files changed: none. Nothing committed.**
