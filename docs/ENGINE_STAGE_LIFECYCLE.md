# Engine Stage Lifecycle: `DVHarness.run_stage()` / `loop()`

Scope: what actually happens inside `dv_harness/engine.py` when one stage
runs, which of those steps have real side effects, and the three reliability
modes layered on top of that lifecycle (dry-run, auto-checkpoint, DEGRADED).

This is the lifecycle reference. It does **not** restate:
- stage *telemetry metrics* -- see `STAGE_EXECUTION_PROFILE.md`;
- the *memory tiers* a stage reads/writes -- see `docs/MEMORY_ARCHITECTURE.md`
  and CLAUDE.md's Engineering Memory Policy;
- the *human control plane* verbs (PAUSE/TAKEOVER/APPROVE/...) -- see
  `START_HERE.md` and `dv_harness/control_plane.py`.

---

## 1. The lifecycle of one `run_stage()` call

Ordered as the code runs. Steps marked **[W]** have real, persisted side
effects; steps marked **[R]** are read-only.

| # | Step | |
|---|------|---|
| 0 | **TAKEOVER short-circuit** -- any active takeover returns `BLOCKED_BY_TAKEOVER` immediately. Human Override outranks everything, including a dry-run. | [R] |
| 0a | **dry-run branch** -- if enabled, `_dry_run_stage()` runs and returns. See §2. | [R]+1 report |
| 0b | **DEGRADED gate** -- `_degraded_gate()` re-probes the triggers, then either returns a DEGRADED result or falls through. See §4. | [W] |
| 1 | Stage-entry marker; `ss["status"]=RUNNING`, `attempts+=1`, `started_at`, `git_sha`; `store.save()`. | [W] |
| 2 | **`_gather_stage_context()`** -- everything needed to decide *what* to execute (see §1a). | mixed |
| 3 | `profiler.begin_stage()` -- telemetry record for this attempt. | [W] |
| 4 | `agents.store.start_task()` -- marks the delegated task RUNNING. | [W] |
| 5 | **`adapter.run(prompt=...)`** -- the one LLM/judgment call. | [W] |
| 6 | `agents.store.complete_task()`, `profiler.add_agent_run()`. | [W] |
| 6a | **Degradation bookkeeping** -- `record_adapter_success/failure()` on this call's real outcome. See §4. | [W] |
| 7 | Gate evaluation (`evaluate_stage_evidence_with_detail`) -> PASS / NEEDS_USER_INPUT / GATE_FAIL / ADAPTER_FAIL. | [R] |
| 8 | On PASS: blackboard write, knowledge promotions, `consume_correction()`/`clear_approval()`. On GATE_FAIL: inner ReAct loop (more adapter calls), then `replan_stage()`. | [W] |
| 9 | `react.record()`, `store.event()`, `store.save()`, `profiler.end_stage()`. | [W] |
| 10 | `last_transition` + stage-done marker. **This is the real stage transition point.** | [W] |
| 10a | **Auto-checkpoint** -- `_auto_checkpoint()`. See §3. | [W] |
| 11 | `self_tuning.increment_execution_counter()`, self-tuning review. | [W] |

`run_stage()` has exactly one early `return` other than steps 0/0a/0b: none.
Every verdict branch falls through to step 10-11, which is why the
auto-checkpoint at 10a fires exactly once per real attempt regardless of
outcome.

### 1a. `_gather_stage_context()` -- the shared "what would we execute" step

Extracted (2026-09-03) so the real path and the dry-run path cannot drift.
Formerly inline steps 1 / 1b / 1b-2 / 1b-3 / 1c of `run_stage()`:

| Sub-step | What | Side effect |
|---|---|---|
| route/skills | `RouteResolver.resolve()`, `SkillResolver.resolve()` | none (pure) |
| protocol/env mode | `resolve_protocol()`, `resolve_environment_mode()` -- real per-run evidence | none (pure) |
| plan | `_find_latest_plan()`, else **`plans.create()`** | **writes `plans/PLAN-*.json`** |
| delegation | **`agents.delegate()`** | **writes a task + takes blackboard-topic ownership** |
| blackboard | `blackboard.snapshot(node.blackboard_read)` | read-only |
| memory | `MemoryRetriever.search()` -- local per-project tier | read-only |
| knowledge center | `KnowledgeCenterClient.search()` (FAILURE_RECOVERY/RE_AUDIT only) | read-only |
| vault | `search_related_memory_for_debug()` (FAILURE_RECOVERY/RE_AUDIT only) | read-only |
| checklist | `build_stage_entry_checklist()` | read-only |
| prompt | `build_stage_prompt()` + `_build_plan_section()` | pure |

The two bolded rows are **the only writes**, and they are exactly what
dry-run suppresses.

---

## 2. Dry-run mode

> 「dry-run 模式：agent 產出完整計畫但不執行，人可事前檢視。導入初期與大改動前必用」

**How to use**

```bash
dv-harness run-stage --goal "..." --stage VERIFY --dry-run
dv-harness start --goal "..." --dry-run          # plans the current stage
```

or, for an onboarding / large-change period where *every* stage should be
reviewed first, in `.dv-harness/config.json`:

```json
"dry_run": { "enabled": true }
```

The CLI flag **ORs** with the config toggle: the flag can turn dry-run on,
never off.

**What you get**: `.dv-harness/dry_run/<STAGE>-<timestamp>.json`, containing
the resolved agent/route/protocol/environment-mode decisions, the plan steps,
the stage's real `required_gates`, the entry checklist, the
blackboard-read/write topics, the context counts, and **the byte-exact prompt
that would have been sent**.

**What provably does not happen** (asserted by
`dv_harness_tests/test_harness_reliability.py::TestDryRun`):
no `adapter.run()`; no plan file; no delegated task or topic lock; no
telemetry, react, event, or `state.json` write; no `attempts` increment; no
auto-checkpoint; no knowledge promotion; no LSF submission.

**On LSF specifically**: `run_stage()` contains no `bsub` call site at all.
Every real submission in this codebase goes through `dv-harness lsf-submit`
-> `lsf_client.bsub_submit_with_preflight()`, a separate command a stage run
never reaches. `test_dry_run_submits_no_lsf_job` monkeypatches both
`bsub_submit*` functions to raise, so a future change that wires submission
into the stage path cannot silently make dry-run dispatch real farm jobs.

**Fidelity**: the dry-run and real prompts are produced by the same
`_gather_stage_context()` call, and the test asserts their plan sections are
byte-identical except for exactly two identifiers a dry-run deliberately does
not allocate (`PLAN-XXXXXXXX`, `TASK-XXXXXXXX` -> `DRY-RUN-NOT-PERSISTED`,
`DRY-RUN-NOT-DELEGATED`). The embedded `dv-harness status` snapshot also
differs honestly: `NOT_STARTED` at plan time vs `RUNNING` at execution time.

**Why a `dry_run` flag rather than a separate `plan_stage()` entry point**: a
separate entry point would need its own copy of the ~140 lines of context
gathering above. The two copies would drift the first time anyone changed
(say) the Knowledge Center query, and the plan a human reviewed would quietly
stop matching the run they were approving. One code path with one flag makes
the equivalence structural rather than aspirational.

**`loop(dry_run=True)` plans the current stage and returns** rather than
looping. Advancing requires a real terminal status from a real gate
evaluation of a real adapter response; a dry-run produces none of those, so
"keep looping" would mean inventing a verdict for a stage that never ran and
planning against that fiction -- exactly the fabricated-evidence failure the
Evidence Truth Rule forbids. Reviewing a whole pipeline is therefore
iterative: dry-run a stage, review, run it for real, dry-run the next.

---

## 3. Automatic stage-transition checkpoints

> 「checkpoint 與回滾：每個階段留可回復點，agent 走偏時不必從頭」

`dv_harness/session_snapshot.py` already implemented real
`save_session()`/`restore_session()`/`list_sessions()` with git-SHA
source-identity mismatch protection (`SourceIdentityMismatchError`, enforcing
CLAUDE.md's "Same regression batch must use the same source/build/config
identity"). **None of that is rebuilt.** The gap was that nothing ever called
it automatically -- it fired only on an explicit `dv-harness save-session`,
so an agent that went off the rails had a recovery point only by luck.

`run_stage()` step 10a now calls `save_auto_checkpoint()` at every real stage
transition, on **every** outcome -- PASS, FAIL, PARTIAL, WAIT_USER -- since
"agent 走偏" is precisely the non-PASS case a human needs to roll back from.

```json
"auto_checkpoint": { "enabled": true, "keep_last": 10 }
```

Default **on**, following the same reasoning `evidence_db` uses for its own
default: purely local file copying, no network call, no credential, and the
whole value of a recovery point is that it already exists when you find out
you need it.

**Retention**. Snapshots are named `auto_<STAGE>_<attempt>_<timestamp>` and
`prune_auto_checkpoints()` keeps the newest `keep_last`. It will only ever
delete names matching `AUTO_CHECKPOINT_PREFIX`, never:
- a human's `save-session --name foo` (an explicit name is a stable label);
- a `_pre_restore_*` backup (the undo of a destructive restore -- deleting it
  would remove the very thing that makes a restore reversible).

`keep_last <= 0` disables pruning rather than deleting everything: a
misconfigured value must fail toward preserving recovery points.

**Rolling back** uses the existing path unchanged -- no second restore
mechanism exists:

```bash
dv-harness list-sessions
dv-harness restore-session <auto_VERIFY_2_20260903-181500>
```

Best-effort throughout: a snapshot failure prints and continues, following
`regression_reporter._escalate_uvm_fatal_burst_if_needed()`'s established
pattern. Failing to take a convenience snapshot must never break the real
cycle.

**Measured cost**: **+0.708 s per stage transition** (3.606 s → 4.315 s per
`run_stage()`, benchmarked on a synthetic project with real gates). Against a
real stage — an LLM call plus gate subprocesses, i.e. minutes — that is under
1%. It is a `shutil.copytree` of the current-run directories, so it grows
with accumulated `react/`/`telemetry/` history; `keep_last` bounds disk usage,
not per-snapshot copy cost. Set `auto_checkpoint.enabled: false` if a
long-running project finds it material.

---

## 4. DEGRADED mode

> 「降級路徑：Claude API 不可用、license 全滿、farm 塞車時，harness 應降級成
> 「只收集資料、不做判斷」，而不是整個停擺或胡亂重試」

State lives in `.dv-harness/degradation.json`; logic in
`dv_harness/degradation.py`.

### The three triggers, and what each reuses

| Trigger | Condition | Evidence source (reused, never reimplemented) |
|---|---|---|
| `adapter_unavailable` | N consecutive ADAPTER_FAIL outcomes | `run_stage()`'s **existing** `result.ok is False` branch |
| `eda_license_full` | license starvation | `preflight.check_license()`'s own `CheckOutcome` |
| `farm_queue_congested` | queue not `Open:Active` | `preflight.check_queue_health()`'s own `CheckOutcome` |

**No parallel retry mechanism is introduced.** The adapter trigger only
*counts* outcomes `run_stage()` already computes. Stage retry stays entirely
in `loop()`'s existing `policy.max_stage_retries`. The default threshold (3)
is deliberately `max_stage_retries` (2) + 1: degradation begins only once the
existing retry budget has been spent and the adapter is *still* failing.

### What DEGRADED changes

**Refused** (不做判斷): no `adapter.run()` proposing a verdict or next
action, no gate evaluation, no stage transition, no `attempts` increment.

**Still done** (只收集資料): the triggers are re-probed, a real
auto-checkpoint is written, and a real `DEGRADED_CYCLE` event carrying the
live trigger detail is appended to `events.jsonl`.

**Unaffected, and for a better reason than configuration**: LSF job-status
polling and log collection run in the detached watcher process
(`regression_reporter.ensure_watcher_running()`), which never goes through
`run_stage()` at all -- a DEGRADED engine structurally cannot stop them.

**Dry-run still works while degraded**: planning is read-only and makes no
judgment, so it is precisely the action that remains safe and useful when
execution is not.

### Observability -- explicit, never a silent branch

`dv-harness status` (i.e. `DVHarness.summary()`) reports:

```json
"operation_mode": "DEGRADED",
"degraded": true,
"degraded_triggers": ["eda_license_full"],
"degraded_trigger_details": {"eda_license_full": "license feature(s) fully checked out (starvation): [VCSRuntime]"},
"degraded_since": 1788269755.4,
"degraded_cycles": 3,
"adapter_failure_streak": 0,
"dry_run_mode": false
```

### Exiting DEGRADED

Self-clearing. `_degraded_gate()` re-evaluates the license/queue triggers
against real current evidence *before* deciding to degrade, so the first
`run_stage()` after the condition clears falls straight through to normal
operation with no human un-sticking it. A successful adapter call clears the
adapter trigger. Clearing one trigger while another is live stays DEGRADED --
a successful adapter call must not promote a license-starved project back to
NORMAL.

### Configuration

```json
"degradation": {
  "enabled": true,
  "adapter_failure_threshold": 3,
  "probe_resources": false,
  "probe_min_interval_sec": 60
}
```

`probe_resources` is **off by default** and this is deliberate. Per
`preflight.py`'s own transport docstring, `LocalCommandRunner` is correct
only when `dv_harness` runs server-side on the Linux DV server, where
`lmutil`/`bqueues` are on PATH. On a PC-side session those commands are
simply absent, and turning "command not found" into a DEGRADED verdict would
fabricate a farm problem that does not exist. Turn it on for a server-side
deployment; it reuses the `preflight` block for the license server and queue
names, so there is no second place to configure them.

A PC-side session in REMOTE_EXECUTION mode can instead inject
`preflight.RemoteRelayCommandRunner()` via `DVHarness.degradation_runner` to
probe the real server through the sanctioned credential-free relay -- the
same "transport fully injected, never assumed" principle `preflight.py`
states, and the seam the tests inject a pure mock through.

**One deliberate asymmetry**: the probe forces
`require_license_configured=False`, where the preflight *gate* leaves it
True. The gate must block on an unconfirmed license (「沒過就 BLOCKED，不派
job」); the monitor must not, because "nobody configured a license server" is
not evidence that the license is full. Forcing the flag off makes that case
preflight's own `SKIP`, and SKIP never triggers degradation -- reusing
preflight's existing three-valued outcome rather than inventing a fourth.

---

## 5. Interaction ordering

1. **TAKEOVER** -- outranks everything, including dry-run. Human Override is
   always valid.
2. **dry-run** -- before the DEGRADED gate, because planning is read-only and
   stays useful precisely when execution is blocked.
3. **DEGRADED** -- before any state mutation.
4. normal execution.

## 6. Tests

`dv_harness_tests/test_harness_reliability.py` (27 tests): dry-run
plan-without-execution and no-LSF-submission, config toggle, takeover
precedence, prompt fidelity; auto-checkpoint on PASS and on FAIL, retention
bounds, protection of human/`_pre_restore_` snapshots, `keep=0` safety, and a
real round-trip restore; all three degradation triggers driven through
`run_stage()`, degraded data-collection behaviour, `status` observability,
and self-clearing resumption.

License/queue fixtures are the real captured `lmutil lmstat`/`bqueues` output
imported from `test_preflight.py`, so the two suites cannot drift and no test
contacts a live license server or scheduler.
