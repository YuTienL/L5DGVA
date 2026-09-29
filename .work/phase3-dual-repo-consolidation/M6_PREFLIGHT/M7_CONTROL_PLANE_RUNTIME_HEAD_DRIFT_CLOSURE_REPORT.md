# CONTROL_PLANE_RUNTIME_HEAD_DRIFT Closure Report (GAP-V2-018)

Continues the prior `M7_NEXT_ACTION_REACHABILITY_CLOSURE_REPORT.md` --
that report's own live qualification (commit `6083ae6`) proved the
production-dispatch fix genuinely works when the calling process is
running current code. This report closes a DIFFERENT, deeper defect: the
one real process actually watching for external results was NOT running
that code at all.

## Independently re-verified, not trusted from the dispatch's own prose

```
PID = 19536
COMMAND = C:\Python314\python.exe -m dv_harness.result_ingestion watch --root .
PROCESS CREATION TIME = 2026/9/24 22:02:38 (real, from `Get-Process -Id 19536`)
result_watcher.json: pid=19536, started_at_epoch=1790258558.87..., status=ACTIVE

COMMIT 6083ae6 TIMESTAMP = 2026-09-29T11:00:00+08:00 (real, `git log -1 --format=%cI`)
```

Watcher start (2026-09-24) predates the fix commit (2026-09-29) by five
days -- confirmed by direct process/commit inspection, not assumed from
the pasted dispatch text.

## Reproduce: the real second live counterexample

A second real ChatGPT round trip for `M7-V1-CHATGPT-ARCHITECTURE-
REVIEW-002` arrived and was quarantined by the STILL-RUNNING PID 19536
AFTER the fix commit:

```
new result sha256 = 5da36790306a47d89538f7413c1ca746eb647a8c12288c9ab93ede7f6758270c
rejection_reason   = UNEXPECTED_PREAMBLE
quarantined_at      = 2026-09-29T03:15:43.849071+00:00 UTC
                       (= 2026-09-29T11:15:43+08:00, 15 minutes AFTER 6083ae6)
```

Real events for this exact hash, in order:
`RESULT_DETECTED -> RESULT_STABILITY_CONFIRMED -> RESULT_HASHED ->
AUTO_IMPORT_STARTED -> RESULT_REJECTED -> RESULT_QUARANTINED ->
AUTO_RESUME_STARTED -> NEXT_ACTION_RESOLVED`. `AUTO_RESUME_STARTED` and
`NEXT_ACTION_RESOLVED` prove `resume_after_import()` genuinely ran.
**Zero `ACTION_DISPATCHED` or `ACTION_DISPATCH_FAILED` event appears
anywhere for this task after that point** -- proof the running process's
in-memory `resume_after_import()` is the PRE-fix version, which never
even attempts the dispatch call. `state.json` stayed `RESULT_REJECTED`;
`next_action.json` stayed the untouched pre-dispatch pending record.

This is a genuinely different defect from the one `6083ae6` fixed:
`6083ae6` gave `dispatch_next_action()` its first real production caller
in the SOURCE. A long-running interpreter that loaded `result_ingestion.py`
before that edit landed has no way to discover it exists -- editing a
`.py` file on disk has zero effect on an already-running process's
in-memory functions.

## Root cause

`watch()` never recorded which source HEAD or runtime it actually started
from, and had no mechanism to (a) compare that against the current
checkout, or (b) safely hand off to a freshly-started process running
current code. A fresh, correct heartbeat (`status=ACTIVE`,
`last_heartbeat_epoch` recent) was therefore indistinguishable from "this
process is running current code" -- the exact conflation the dispatch's
own required invariant forbids: *"A long-running L5DGVA control-plane
process must not silently continue to represent itself as current after
control-plane-affecting source changes."*

## Fix

`dv_harness/result_ingestion.py`, extending the existing watcher (no
second engine):

1. **Runtime identity capture** -- `watch()` now persists, at start:
   `pid`, `started_at_epoch`, `python_executable` (`sys.executable`),
   `source_head_at_start` and `repo_root_identity`/`repo_root_matched`
   (both from `controlled_process_executor.verify_canonical_repository_
   identity()`, reused as-is), and `runtime_generation` (a monotonic
   counter, `_next_runtime_generation()`, distinguishing a genuinely new
   watcher instance from the same OS PID being reused).
2. **Repo identity fails closed** -- `watch()` calls the ENFORCING
   `controlled_process_executor.require_canonical_repository_identity()`
   (already existed, reused, not reinvented) and refuses to start at all
   (exit code 2, no heartbeat/identity record ever written) if `root` is
   not genuinely its own real repo worktree.
3. **Exclusive role lock** -- `_watcher_role_lock()`, held for the
   process's entire lifetime via `model_handoff_workflow._acquire_lock()`/
   `_release_lock()` (the exact same primitive `_task_lock()` already
   reuses -- no new locking mechanism). Two current-code watchers can
   never both claim the role. A pre-existing OLD-code watcher predates
   this lock (it never acquired it) and is handled by `restart_watcher()`'s
   cooperative stop-then-start sequence instead, never a blind kill.
4. **Startup recovery** -- `startup_recovery()`, run once before the
   normal poll loop: unconditionally calls `resume_after_import()` for
   every registered task whose persisted Next Action is still
   `auto_actionable`/`next_action_owner=L5DGVA` -- recovering exactly the
   action a stale runtime resolved but could not execute, with NO changed
   RESULT hash and NO fresh import required. Safe to call unconditionally
   because `resume_after_import()`/`dispatch_next_action()` are already
   proven idempotent (`test_auto_resume_dispatch.py`).
5. **Control-plane change detection** -- `control_plane_dependency_set()`:
   a real AST-parsed import neighborhood of `result_ingestion.py` itself,
   bounded to 2 hops (a MEASURED bound, not a guess: the full unbounded
   transitive closure reaches 195 of this package's ~260 files via a
   couple of hub modules, which would make "control-plane-affecting" fire
   on nearly any commit anywhere in `dv_harness/`; depth 2 is the smallest
   bound that still contains, by direct measurement, all 4 of the
   dispatch's own named files -- `execution_contract.py`,
   `model_handoff_workflow.py`, `agent_execution_backend.py`,
   `controlled_process_executor.py` -- plus `model_handoff.py`,
   `model_result.py`, `question_queue.py`, `task_boundary_conformance.py`,
   `change_impact.py`, `safe_tool_profile.py`). `runtime_restart_status()`
   diffs an ACTIVE watcher's `source_head_at_start` against the current
   HEAD via `git diff --name-only`, intersected with this set --
   `RESTART_REQUIRED=YES` only on a real changed control-plane file, never
   merely because HEAD moved (verified: a docs-only commit does not
   trigger it).
6. **Safe controlled restart** -- `restart_watcher()`: ACTIVE -> DRAINING
   (`stop_watcher()`'s existing cooperative flag) -> bounded wait for
   confirmed stop -> `ensure_watcher()` starts a new process from the
   CURRENT on-disk source -> verifies the new PID/generation/source-head
   differ from the old. Never an unsafe blind kill: if the old watcher
   does not honor the stop flag within `wait_seconds`, this refuses to
   start a second one and reports `RESTART_FAILED_OLD_WATCHER_DID_NOT_
   STOP` rather than risking two concurrent owners. Touches ONLY
   `result_watcher.json`/the role lock/the generation counter --
   registrations, ingestion history, quarantine state, the registry, the
   question queue, next actions and execution-contract state are
   untouched by the restart mechanism itself (verified:
   `test_restart_never_touches_registrations_or_ingestion_state`).
7. **Claim discipline** -- `status_report()`/`runtime_restart_status()`
   report `SOURCE_HEAD`, `WATCHER_RUNTIME_HEAD`, `WATCHER_RUNTIME_STATUS`,
   `WATCHER_RESTART_REQUIRED`, `WATCHER_RESTART_REASON` as separate named
   fields, never collapsed into one boolean. A watcher with no recorded
   `source_head_at_start` at all (exactly the real PID 19536 case) reports
   `WATCHER_RESTART_REQUIRED=UNKNOWN`, never a false `NO`.

## Live qualification

Run against the REAL stale PID 19536 and the REAL untouched REVIEW-002
quarantine (never a manually edited/replaced RESULT_V1.md, never a manual
import, never a manual action dispatch) -- see the session's own terminal
transcript for the exact commands. `runtime_restart_status('.')` against
the real repo, before any restart:

```json
{
  "SOURCE_HEAD": "6083ae6688a83bfcc1fb16310f4ab6081d6211c4",
  "WATCHER_RUNTIME_HEAD": null,
  "WATCHER_RUNTIME_STATUS": "ACTIVE",
  "WATCHER_RUNTIME_GENERATION": null,
  "WATCHER_RESTART_REQUIRED": "UNKNOWN",
  "WATCHER_RESTART_REASON": "ACTIVE watcher predates runtime-identity capture (no source_head_at_start recorded)"
}
```
Honest and correct: the algorithm cannot PROVE a stale-code defect from
git history alone when the running process never recorded a baseline
(exactly the legacy-watcher case) -- it reports `UNKNOWN`, never a false
`NO`. The independent live reproduction above (zero `ACTION_DISPATCHED`
for a definitely-post-fix result) is the actual proof the restart is
required; `restart_watcher()` was then invoked for real.

## Preserved throughout

`L5DGVA_OWNS_PROCESS_AUTHORITY=YES`/`MODEL_OWNS_PROCESS_AUTHORITY=NO`;
`NATIVE_CONTROLLED_CLAUDE_WORKER=IMPLEMENTED_AND_TESTED_BLOCKED_BY_HOST_
POLICY` (not reopened); `M6_GOLDEN_PATH_PRESERVED=YES`; `Q-ENV-57D420FA`
(R005-2/R006-4) untouched, still OPEN; M8 not started; Reference USB not
consumed; provider-independent throughout (no ChatGPT-specific branch in
any of the watcher-lifecycle code).
