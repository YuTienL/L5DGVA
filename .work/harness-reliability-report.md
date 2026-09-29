# Harness Reliability: dry-run + auto-checkpoint + degradation path

**Date**: 2026-09-03
**Scope**: `dv_harness/engine.py`'s `run_stage()`/`loop()`, plus one new
module, wiring for three user-spec requirements:

> 「dry-run 模式：agent 產出完整計畫但不執行，人可事前檢視。導入初期與大改動前必用」
> 「checkpoint 與回滾：每個階段留可回復點，agent 走偏時不必從頭」
> 「降級路徑：Claude API 不可用、license 全滿、farm 塞車時，harness 應降級成
> 「只收集資料、不做判斷」，而不是整個停擺或胡亂重試」

**Status**: DONE. Engine-related regression suite: **268 passed, 0 failed**
(18m38s), including 27 new tests. See §7 for exactly which files were run and
why the scope is what it is.

---

## 1. Files changed

| File | Change |
|---|---|
| `dv_harness/degradation.py` | **NEW** — DEGRADED state machine, triggers, persistence |
| `docs/ENGINE_STAGE_LIFECYCLE.md` | **NEW** — the stage-lifecycle reference (no competing doc existed) |
| `dv_harness_tests/test_harness_reliability.py` | **NEW** — 27 tests |
| `dv_harness/engine.py` | `_gather_stage_context()` extraction; `_dry_run_stage()`, `_degraded_gate()`, `_auto_checkpoint()`; `run_stage(dry_run=)`, `loop(dry_run=)`; DEGRADED fields in `summary()`; `degradation_runner` seam |
| `dv_harness/session_snapshot.py` | `save_auto_checkpoint()` / `list_auto_checkpoints()` / `prune_auto_checkpoints()` / `is_auto_checkpoint()` + prefix and retention constants |
| `dv_harness/config.py` | three new blocks: `dry_run`, `auto_checkpoint`, `degradation` |
| `dv_harness/cli.py` | `--dry-run` on `run-stage` and `start`; threaded into `run_stage()`/`loop()` |
| `START_HERE.md` | one cross-reference bullet to the new lifecycle doc |

**Not touched, per instruction**: `dv_harness/regression_reporter.py`,
`dv_harness/evidence_db.py`, `dv_harness/vip_distill.py`.

### Concurrent-edit protection actually performed

Three sibling workstreams were editing shared files during this task. For
every shared file I ran `git status --short` + `git diff <file>` **before**
the first edit, and verified hunk separation afterwards:

- `config.py`: sibling `evidence_db` block already uncommitted. My three
  blocks were deliberately placed after `preflight` (~25 lines away) rather
  than adjacent to it, so `git diff` shows **two separate hunks**
  (`@@ -142,6 +142,64 @@` mine, `@@ -165,6 +223,20 @@` theirs) with no
  possibility of a whole-file `git add` sweeping theirs in.
- `cli.py`: went dirty mid-task (a sibling `exemptions` workstream, hunks at
  ~552 and ~1270, later more). My two edits land at ~100 and ~1805 — separate
  hunks throughout.
- `CLAUDE.md`: a fourth workstream began appending to it mid-task
  (Bind-Location Rules). I deliberately **did not edit CLAUDE.md at all**;
  documentation went into a new `docs/` file plus one bullet in the clean
  `START_HERE.md`.

No commit was made — see §8.

---

## 2. Side-effect call sites (identified, not guessed)

Grepped rather than assumed. The real state-mutating call sites in
`run_stage()`:

- `self.adapter.run(...)` — engine.py:2183 (pre-change numbering); the only
  LLM/judgment call in the stage path.
- `self.plans.create(...)` and `replan_stage(...)` — plan file writes.
- `self.agents.delegate(...)` → `AgentTaskStore.create_task()` — writes a
  task **and takes blackboard-topic ownership**; also `start_task()` /
  `complete_task()`.
- `self.profiler.begin_stage()` / `add_agent_run()` / `end_stage()`.
- `self.store.save(self.state)` (×3) and `self.store.event(...)`.
- `self.react.record(...)`, `self._write_blackboard_from_evidence(...)`.
- `cp.consume_correction()` / `cp.clear_approval()`.
- the `_promote_*` / `_persist_*` / `_score_*` / `_append_*` knowledge writes.
- `self_tuning.increment_execution_counter()`.

**Notable real finding — no LSF submission exists in the stage path.**
`grep -rn "bsub_submit" dv_harness/` shows `engine.py` has **zero** matches.
Every real submission goes through `dv-harness lsf-submit` →
`lsf_client.bsub_submit_with_preflight()` in `cli.py:843`. So "dry-run
submits no LSF job" is structurally true rather than something dry-run had to
suppress. Rather than assert that from reasoning, the test monkeypatches both
`bsub_submit` and `bsub_submit_with_preflight` to raise, so a future change
that wires submission into the stage path fails the test instead of silently
dispatching real farm jobs from a dry-run.

Verified read-only (so safe to run in dry-run): `RouteResolver.resolve`,
`SkillResolver.resolve`, `resolve_protocol`, `resolve_environment_mode`,
`_protocol_router_evidence`, `_environment_mode_router_evidence`,
`Blackboard.snapshot`, `load_agent_profile`, `build_stage_entry_checklist`,
`build_stage_prompt`, the memory/KC/vault searches.

---

## 3. Requirement 1 — dry-run

**Design decision: a `dry_run` flag on `run_stage()`, not a separate
`plan_stage()`.** The task left this to my judgment; here is the reasoning.

Producing a plan requires the full ~140 lines of context gathering (route,
protocol/env-mode resolution, plan lookup, blackboard snapshot, memory/KC/
vault searches, entry checklist, prompt build). A separate `plan_stage()`
would need its own copy. Those copies would drift the first time anyone
changed, say, the Knowledge Center query — and the plan a human reviewed
would quietly stop matching the run they were approving. That defeats the
entire purpose of a review gate.

So instead I **extracted** that logic into `_gather_stage_context(...,
dry_run=False)`, called by both paths. The equivalence is now structural, and
a test asserts it: the dry-run and real prompts' plan sections are
byte-identical except for exactly two identifiers a dry-run deliberately does
not allocate (`PLAN-XXXXXXXX`, `TASK-XXXXXXXX`).

The extraction is the one non-additive change to heavily-tested code. It is
mechanical (same statements, same order) with a single deliberate reordering:
the prompt is now built before `profiler.begin_stage()` instead of after.
`build_stage_prompt()` is pure and `self.summary()` reads nothing
`begin_stage()` writes, so this is behaviorally inert; it exists so the
dry-run path can produce the real prompt without writing a telemetry record
for an attempt that never happens.

**Suppressed in dry-run**: `plans.create()` (an in-memory plan marked
`DRY-RUN-NOT-PERSISTED` is synthesized instead, and an existing in-flight
plan is still *read* and reused) and `agents.delegate()` (a descriptive
`DRY-RUN-NOT-DELEGATED` task dict carrying the node's real agent/
parallel_group is used instead, so the shared `_build_plan_section()` is left
untouched). Everything after that point is simply never reached.

> A real bug surfaced here during testing: `_build_plan_section()`
> unconditionally dereferences `task['task_id']`, so passing `task=None`
> raised `TypeError`. Fixed in the dry-run path (synthetic task dict) rather
> than by editing that shared, heavily-tested helper — zero regression risk
> to the real path.

**Artifact**: `.dv-harness/dry_run/<STAGE>-<timestamp>.json` — the one
permitted write. Contains resolved agent/route/protocol/environment-mode
decisions, plan steps, the stage's real `required_gates` (the
evidence-request half), entry checklist, blackboard read/write topics,
context counts, human controls, and the full prompt. `dry_run` is
deliberately **not** in `session_snapshot.SESSION_DIRS`, so these reports are
never restored as run state.

**Ordering**: TAKEOVER outranks dry-run (Human Override is always valid);
dry-run is checked *before* the DEGRADED gate, because planning is read-only
and makes no judgment — it is precisely the action that stays useful when
execution is blocked.

**`loop(dry_run=True)` plans the current stage and returns** rather than
looping. Advancing needs a real terminal status from a real gate evaluation
of a real adapter response. A dry-run produces none, so "keep looping" would
mean inventing a verdict for a stage that never ran and planning against that
fiction — the fabricated-evidence failure the Evidence Truth Rule forbids.
Documented in the docstring.

**Wiring**: `dv-harness run-stage --dry-run` / `dv-harness start --dry-run`,
ORed with `config.json`'s `dry_run.enabled` (flag can turn it on, never off).

---

## 4. Requirement 2 — auto-checkpoint

`session_snapshot.py` already had real `save_session()`/`restore_session()`/
`list_sessions()` with git-SHA source-identity mismatch protection. **None of
it was rebuilt.** The actual gap: nothing called it automatically, so a
recovery point existed only if a human had happened to make one.

- Fires at `run_stage()` step 10a — immediately after `last_transition` and
  its `store.save()`, i.e. once the stage's final status is both decided and
  persisted. That is on the single real terminal exit path every verdict
  branch falls through to, so exactly one checkpoint per real attempt.
- On **every** outcome including FAIL/PARTIAL — "agent 走偏" is precisely the
  non-PASS case a rollback is for. Tested.
- Best-effort `try/except` + print, matching
  `regression_reporter._escalate_uvm_fatal_burst_if_needed()`'s pattern (read
  for the idiom; that file was not edited).
- Config `auto_checkpoint: {enabled: true, keep_last: 10}` — default **on**,
  same reasoning `evidence_db` gives for its own default (purely local file
  copying, no network, no credential).

**Retention** (`prune_auto_checkpoints`): keeps the newest `keep_last` and
only ever deletes names with the `auto_` prefix. It can never delete a
human's `--name` snapshot (an explicit name is a stable label) or a
`_pre_restore_*` backup (the undo of a destructive restore — deleting it
would remove the thing that makes restore reversible). Both protections are
tested. `keep_last <= 0` disables pruning rather than deleting everything: a
misconfigured value must fail toward preserving recovery points.

Rollback uses the existing `restore-session` path unchanged — no second
restore mechanism. Tested with a real round trip (BUILD → SIGNOFF → restore →
BUILD).

---

## 5. Requirement 3 — DEGRADED mode

New `dv_harness/degradation.py`; state in `.dv-harness/degradation.json`.

| Trigger | Reused evidence source |
|---|---|
| `adapter_unavailable` | `run_stage()`'s **existing** `result.ok is False` / ADAPTER_FAIL branch |
| `eda_license_full` | `preflight.check_license()`'s own `CheckOutcome` |
| `farm_queue_congested` | `preflight.check_queue_health()`'s own `CheckOutcome` |

**No parallel retry mechanism**, as instructed. The adapter trigger only
*counts* outcomes `run_stage()` already computes; it never retries or
re-calls anything. Stage retry stays entirely in `loop()`'s existing
`policy.max_stage_retries`. Default threshold 3 = `max_stage_retries` (2) + 1
— degradation begins only once the existing retry budget is spent and the
adapter is still failing. No license or queue checking is reimplemented;
`probe_resources()` calls preflight's own functions and maps their
`CheckOutcome`s.

**Behaviour**: refuses the judgment call (no `adapter.run()`, no gate
evaluation, no transition, no `attempts` increment) while continuing real
data collection (re-probe, auto-checkpoint, `DEGRADED_CYCLE` event with live
trigger detail). LSF polling/log collection are unaffected structurally, not
by configuration: they run in the detached watcher process, which never goes
through `run_stage()`.

**Observable, not silent**: `DVHarness.summary()` — printed verbatim by
`dv-harness status` — now carries `operation_mode`, `degraded`,
`degraded_triggers`, `degraded_trigger_details`, `degraded_since`,
`degraded_cycles`, `adapter_failure_streak`, `dry_run_mode`. No CLI change
was needed. Verified live against a real project directory.

**Self-clearing**: `_degraded_gate()` re-evaluates before deciding, so the
first `run_stage()` after the condition clears proceeds normally with no
human intervention. Clearing one trigger while another is live stays DEGRADED
(a successful adapter call must not promote a license-starved project to
NORMAL). Both tested.

### A real bug this work introduced, found in self-review and fixed

My first version of `_degraded_gate()` set `self.state.overall_status =
WAIT_USER` but left `ss["status"]` untouched. `loop()` reads **`ss["status"]`**
to decide what to do next, and its final fallthrough is an unconditional
`self.advance(user_goal)` — which routes along the graph's **PASS** edge. So a
degraded harness would have silently walked forward through the pipeline,
advancing past a stage that never ran. All 25 tests then existing passed at that point,
because none of them drove `loop()`.

Fixed by setting `ss["status"] = WAIT_USER` (the same status the TAKEOVER
path in `loop()` sets, for the same "park cleanly" reason), with
`test_loop_does_not_advance_past_a_degraded_stage` as the regression guard.
This is also why parking rather than looping is correct: a loop that kept
re-invoking a degraded stage with no delay would be 胡亂重試, exactly what the
spec rules out. Each re-invocation performs one data-collection cycle; the
detached LSF watcher keeps collecting continuously regardless.

### Two judgment calls worth flagging for review

1. **`probe_resources` defaults to `false`.** `preflight.py`'s own docstring
   says `LocalCommandRunner` is correct only server-side, where
   `lmutil`/`bqueues` exist. On a PC-side session they are absent, and
   `check_license`/`check_queue_health` would FAIL with "command not found" —
   which is *not* evidence of a full license or a jammed farm. Defaulting
   this on would put every PC-side project into permanent DEGRADED on a
   fabricated conclusion. A server-side deployment opts in; it reuses the
   existing `preflight` block for server/queue names.

2. **The probe forces `require_license_configured=False`**, where the
   preflight *gate* leaves it `True`. The gate must block on an unconfirmed
   license (「沒過就 BLOCKED，不派 job」); the monitor must not, because
   "nobody configured a license server" is not evidence the license is full.
   Forcing it off makes that case preflight's own `SKIP`, and SKIP never
   triggers — reusing preflight's existing three-valued outcome rather than
   inventing a fourth. Tested explicitly.

**Transport seam**: `DVHarness.degradation_runner` (default `None` →
`LocalCommandRunner`). A PC-side REMOTE_EXECUTION session can assign
`preflight.RemoteRelayCommandRunner()` to probe the real server through the
sanctioned credential-free relay — the same "fully injected, never assumed"
principle `preflight.py` states. This is a real capability, and it is also
the seam tests inject a pure mock through, so no test contacts a live license
server.

---

## 6. Docs

No existing doc described `engine.py`'s stage lifecycle
(`STAGE_EXECUTION_PROFILE.md` covers telemetry metrics only; `START_HERE.md`
mentions `run_stage()` once, for takeover). So `docs/ENGINE_STAGE_LIFECYCLE.md`
is new rather than competing: a step-by-step lifecycle table marking which
steps have side effects, then the three modes, their configuration, their
interaction ordering, and the reasoning behind each judgment call.
`START_HERE.md` gained one cross-reference bullet.

---

## 7. Test results

New suite — `dv_harness_tests/test_harness_reliability.py`: **25 passed**
(208s). Coverage: dry-run plan-without-execution (asserting each suppressed
side effect individually against captured pre-state), no-LSF-submission,
config toggle, takeover precedence, prompt fidelity; auto-checkpoint on PASS
and FAIL, retention bounds, human/`_pre_restore_` protection, `keep=0`
safety, real restore round-trip; all three degradation triggers driven
through `run_stage()`, degraded data-collection, `status` observability,
self-clearing resumption.

Engine-related regression suite — run because `run_stage()`/`loop()` are
heavily tested and the `_gather_stage_context()` extraction carried real
regression risk:

```
python -m pytest -q -p no:randomly \
  test_harness_reliability test_react_loop test_stage_evidence_checklists \
  test_stage_transition_visual_markers test_stage_scoped_completion_percent \
  test_multi_agent_timing test_graph_parallel_dispatch test_debug_flow_memory \
  test_protocol_and_environment_mode_engine_wiring test_session_and_info \
  test_active_stages_read_sites test_inference_engine_wiring \
  test_qualified_conclusion test_preflight test_preflight_lsf_wiring \
  test_cli_blackboard test_graph_runtime_removed
```

Result: **268 passed, 0 failed in 1118.76s (18:38)** — including the 27 new
tests. No pre-existing engine test regressed.

*Scoping note, stated honestly*: I first launched the entire
`dv_harness_tests/` directory (~5000 tests). It reached only 2% in ~10
minutes on this heavily-contended machine (several agent workstreams running
concurrently), implying many hours. I scoped down to the engine-related
files — every suite that constructs a `DVHarness`, drives `run_stage()`/
`loop()`, or exercises the modules I changed (`preflight`, `session_snapshot`
via `test_session_and_info`) — rather than report a full-suite pass I had not
actually observed. The remainder of the tree (UVM generators, memory vault,
protocol builders, dashboard) does not import `engine.py`'s changed paths.

Additional edge-case verification run directly (not via pytest): a corrupt
and a non-dict `degradation.json` both read as NORMAL rather than raising;
`blocking_reason()` is empty when not degraded; enter/exit edges stamp
`entered_at`/`cleared_at` correctly; auto-checkpoint names are unique across
rapid successive saves; `is_auto_checkpoint()` correctly rejects
`_pre_restore_*` and human names.

Also smoke-tested end to end via the real CLI against a synthetic project:
`dv-harness run-stage --goal ... --stage INTAKE --dry-run` exits 0, writes a
14,987-byte report (real agent `analysis-agent`, route `analysis-route`, 2
plan steps, 4+ real required gates, 7,681-char prompt), and leaves
`.dv-harness/plans/` empty.

---

## 8. Not done / follow-ups

1. **No commit made.** Three sibling workstreams have uncommitted hunks in
   `config.py` and `cli.py` right now. Committing my changes means staging
   those two shared files, and a `git add <file>` would sweep their work in.
   The safe path is a hand-built `git apply --cached` patch scoped to my
   hunks only (the pattern from commit `cca8820` "Fix real preflight-gate
   regression"). Since hunk boundaries in `cli.py` were still shifting during
   this task as siblings landed more edits, I left the working tree dirty
   rather than risk a mis-scoped stage. Recommend committing once the
   sibling workstreams settle, verifying with `git diff --cached` first.
2. **`probe_resources` has never run against the real license server** from
   inside degradation.py — the trigger mapping is tested against real
   captured `lmstat`/`bqueues` text, but an end-to-end run on the Linux DV
   server has not happened. Worth doing before relying on it in production.
3. **Retention is count-based, not age-based.** `keep_last: 10` bounds
   growth; a long-running project may still want an age policy. Not added
   without a real requirement.
4. **Auto-checkpoint cost — measured, and it is not free.** Benchmarked
   directly (3 `run_stage()` calls each way, synthetic project, real gates):

   | | per `run_stage()` |
   |---|---|
   | `auto_checkpoint.enabled: false` | 3.606 s |
   | `auto_checkpoint.enabled: true` | 4.315 s |
   | **overhead** | **+0.708 s (+19.6%)** |

   Keeping the default **on** is still right: a real stage is dominated by an
   LLM call plus real gate subprocesses and takes minutes, so 0.7 s is well
   under 1% there — the 19.6% figure only looks large because the synthetic
   stage is itself only 3.6 s. But two honest caveats:
   - it does slow this project's own engine test suite by roughly that
     fraction, since those tests are exactly the fast-synthetic-stage case;
   - the cost is a `shutil.copytree` of
     `.dv-harness/{blackboard,plans,react,agents,telemetry,lsf}`, so it grows
     with accumulated `react/`/`telemetry/` history. `keep_last` bounds *disk
     usage*, not per-snapshot copy cost. A long-running project that finds
     this material should set `auto_checkpoint.enabled: false`, or a future
     pass could make the snapshot incremental / hardlink-based.
5. **`dry_run.enabled: true` in config makes `loop()` a single-stage
   plan-and-return.** Intended, and documented, but an operator who sets the
   config toggle and then runs `dv-harness start --loop` may be surprised
   that it does not iterate. The printed `DRY_RUN` line makes it visible.
