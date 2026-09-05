# Gap 2 — Question-Queue Digest Auto-Trigger + the 4 Tracked Metrics

**Scope**: self_check_list.md items #11-14 (question-queue digest auto-triggering,
and whether the 4 tracked metrics are real computations or design prose).

**Execution mode**: LOCAL_ANALYSIS. No network call, no SSH, no remote server was
touched. Everything below is local read/edit/test.

**Verdict**: **DONE** — the digest half was really DORMANT and is now
`WIRED_AND_FIRING`; the metrics half needed no code (it was already real) and is
now additionally auto-recorded on the same boundary.

**Test summary**: `python -m pytest dv_harness_tests/test_question_queue_digest_auto_trigger.py -q`
→ **7 passed**; the related engine/queue/graph suites
(`test_question_queue.py`, `test_engine_gates_and_routing.py`,
`test_graph_parallel_dispatch.py`, `test_rca_multi_agent_fanout.py`,
`test_active_stages_read_sites.py`,
`test_waveform_dump_scope_human_confirmation.py`,
`test_blackboard_subsystem_wiring.py`) → **341 passed in 701s**;
`dv-harness self-audit` → exit 0. The full `dv_harness_tests/` run reached
3782/5210 before its background-task lifetime expired, with 11 non-passing
markers, all of them the live-`pueued`-daemon tests ("real pueued did not come
up") reproduced in isolation and unrelated to this change — see "Full suite"
below.

---

## 1. What the re-check confirmed before changing anything

The incoming audit finding was re-verified against the real files, not accepted
from the report.

### Digest auto-trigger — **DORMANT** (confirmed)

`grep -rn "build_digest\|compute_metrics" --include=*.py --include=*.yml --include=*.js --include=*.md --include=justfile .`
(excluding `.work/`) returned, for non-test non-docstring hits, exactly two real
call sites in the whole repo:

- `dv_harness/cli.py:2874` — `digest = qq.build_digest(trigger=args.trigger, ...)`,
  the hand-typed `dv-harness question-queue digest` verb.
- `dv_harness/cli.py:2880` — `print(json.dumps(qq.compute_metrics(), ...))`.
  **Correction to the incoming finding**: this verb is `question-queue status`
  (`args.qq_cmd == "status"`, argparse at `cli.py:1348`), not
  `question-queue metrics`. The finding's substance (manual-CLI-only) was right;
  the verb name was not.

`dv_harness/engine.py`'s only `build_digest` hit was line 1792, inside
`_file_waveform_dump_scope_question()`'s prose — not executable code. A
re-run grep for a scheduler naming the queue
(`--include=*.yml --include=*.yaml --include=*.service --include=*.timer
--include=justfile --include=*.ps1 --include=*.cmd --include=*.sh`, excluding
`.work/`) returned **zero files**. `question_queue.py`'s own docstring said so
outright: *"not wired into engine.py itself in this change — engine.py's
stage-transition path is owned by a concurrent workstream this session"*.

### The 4 metrics — real computations (confirmed, no code needed)

All four are genuine computations in `QuestionQueueStore.compute_metrics()`
(`dv_harness/question_queue.py:1190-1268` after this change), each with its own
passing assertions in `dv_harness_tests/test_question_queue.py`. Re-read line by
line and re-run here; nothing about them is a stub or a design goal. **No change
was made to any metric's math.**

---

## 2. What was built

One wiring change, extending existing code. No parallel mechanism: no new
scheduler, no new store, no new concurrency primitive, no second notion of
"a stage completed".

### `dv_harness/engine.py` — `DVHarness._emit_question_digest_at_stage_boundary()`

A new private method (+ one call at the top of `advance()`), 66 added lines
total. It calls the EXISTING `question_queue.QuestionQueueStore.build_digest(
trigger="stage_boundary", stage=completed_stage)` and `compute_metrics()` — the
exact call shape `build_digest()`'s own docstring specified for a future
integration.

**Why `advance()`**: it is the single canonical "the current stage finished
successfully, move on" transition. `loop()` delegates to it on every PASS
(`engine.py`'s `n = self.advance(user_goal)`), and `commands.cmd_advance()`
(`dv-harness next`) calls it directly. `set_stage()` / `human_redirect()` were
deliberately NOT used: they also fire on human reroutes and on `loop()`'s
FAIL-edge routing, which are not stage-completion boundaries and would emit a
digest in the middle of a failure recovery.

Behaviour:

- **Still never real-time.** Only `question_queue.DIGEST_BOUNDARY_STAGES`
  (`REGRESSION_MONITOR`, `COVERAGE_CLOSURE`, `RE_AUDIT`, `SIGNOFF`) do any work.
  The membership check is re-done in the engine before the store is even
  constructed, so an ordinary stage transition does not pay to load the queue.
  Part B's "batched into a daily/end-of-run digest, never real-time pings" is
  unchanged — what changed is that the batch happens without a human
  remembering to type the verb.
- **One `QUESTION_QUEUE_DIGEST` event per boundary crossing** in
  `.dv-harness/events.jsonl`, carrying `emitted` / `batch_id` /
  `question_count` / per-owner counts **and the full metrics dict**. Recorded on
  every crossing including `emitted: false` — a metrics series with datapoints
  only on the cycles that happened to have pending questions is not a series,
  and "this cycle had nothing to escalate" is itself citable evidence. This is
  what closes the metrics half: they are now computed and recorded
  automatically, not only when a human types `question-queue status`.
- **Best-effort**, mirroring the neighbouring
  `_file_waveform_dump_scope_question()`: an unreadable queue records
  `QUESTION_QUEUE_DIGEST_FAILED` and never turns a completed stage transition
  into a crash.
- **It batches; it never answers.** Only `answer_question()`, i.e. a human,
  writes a decision. The human checkpoint is unchanged.

### `dv_harness/question_queue.py` — docstring corrected (comment hygiene)

`build_digest()`'s docstring said the engine wiring did not exist. That sentence
is now false, so it was replaced with the real call site rather than left as a
stale explanation (Engineering Discipline Rules → comment hygiene). No logic
changed in this file; `git diff` is 16 lines, all inside one docstring.

### `CLAUDE.md` — new dated section

"Question-Queue Digest: Auto-Fired at Regression-Cycle Boundaries (2026-09-05)",
appended at the end of the file (lowest-conflict placement, since four sibling
gap-close workstreams are live in this session). States what was dormant, what
is wired, the four boundary stages, the event contract, and the disclosed
residual below.

---

## 3. Disclosed residual — the `scheduled` trigger has no scheduler

This closes the `stage_boundary` trigger only. `build_digest(trigger="scheduled",
min_hours_since_last=24.0)` — the daily cadence for a caller that polls without
knowing the stage — still has no scheduler anywhere in this repo (grep above:
zero cron/systemd/Windows-Task/justfile/CI hits). It was deliberately NOT wired
into `.github/workflows/dv-harness-ci.yml`'s existing `cron: "17 3 * * *"`: a
fresh CI checkout carries no `.dv-harness` question store, so that step could
only ever record an empty no-op — an honest-looking artifact asserting "nothing
to escalate" about a project whose queue was never present. A project wanting
the daily cadence runs `dv-harness question-queue digest --trigger scheduled`
from its own scheduler. Stated here rather than implied closed.

---

## 4. Tests

New file: `dv_harness_tests/test_question_queue_digest_auto_trigger.py`, 7 tests,
driving a real `QuestionQueueStore` on disk and the real shipped
`.dv-harness/graph/main_graph.json` — no mock of either.

1. `test_every_digest_boundary_stage_is_a_real_node_in_the_shipped_graph` — a
   hook keyed on stage names the real graph never reaches would be dead wiring
   that still passes every behavioural test below (which set the stage by hand).
2. `test_advance_past_a_boundary_stage_emits_a_real_digest_and_the_4_metrics` —
   asserts the event AND that the question on disk really carries the
   `digest_batch_id`/`digest_emitted_at` (a real `build_digest()` ran, not a
   summary being logged), plus real computed metric values
   (`blocking_questions_per_week == 1.0`, `self_resolve_rate_percent == 0.0`).
3. `test_an_ordinary_stage_transition_emits_nothing` — `DISCOVERY →
   COMMAND_PATTERN` leaves the queue completely untouched.
4. `test_a_boundary_with_nothing_pending_still_records_a_metrics_datapoint`.
5. `test_a_second_boundary_does_not_re_batch_an_already_digested_question` —
   two crossings in one run; the second is `emitted: false` and the batch id on
   disk is unchanged, so a question a human is already sitting on is not
   re-armed.
6. `test_a_question_queue_failure_never_breaks_the_stage_transition` — a raising
   `build_digest` still advances the stage and records
   `QUESTION_QUEUE_DIGEST_FAILED`.
7. `test_digest_fires_after_a_real_gate_verified_stage_pass` — the autonomous
   path: a real `run_stage("REGRESSION_MONITOR")` to a real `Status.PASS`,
   then the same `advance()` `loop()` calls.

Commands and results:

```
$ python -m pytest dv_harness_tests/test_question_queue_digest_auto_trigger.py -q
7 passed in 4.94s

$ python -m pytest dv_harness_tests/test_question_queue.py \
    dv_harness_tests/test_graph_parallel_dispatch.py \
    dv_harness_tests/test_rca_multi_agent_fanout.py \
    dv_harness_tests/test_active_stages_read_sites.py \
    dv_harness_tests/test_engine_gates_and_routing.py \
    dv_harness_tests/test_waveform_dump_scope_human_confirmation.py \
    dv_harness_tests/test_blackboard_subsystem_wiring.py -q
341 passed in 701.47s (0:11:41)
```

Post-commit re-run of the two queue suites together:
`test_question_queue_digest_auto_trigger.py` + `test_question_queue.py` →
**54 passed in 5.77s**.

`python -m dv_harness.cli --project-root . self-audit` → **exit 0** (the same
gate `.github/workflows/dv-harness-ci.yml` runs).

### Full suite — reported honestly, not rounded up to "green"

`python -m pytest dv_harness_tests/ -q --tb=no -rEf` was started twice. Both
runs were killed by the session's background-task lifetime before printing a
summary line; the second reached **3782 of 5210 collected tests (~72%)**. Its
progress stream carried exactly **11 non-passing markers (6 E, 5 F)** and
nothing else. Mapping each marker's index against
`pytest --collect-only -q`'s deterministic order (no `pytest-randomly` is
installed, so collection order is stable) identified all 11 as
`dv_harness_tests/test_pueue_client.py::TestRealPueueIntegration::*` and
`dv_harness_tests/test_cli_pueue.py::TestPueue*`.

Re-run in isolation to confirm the attribution:

```
$ python -m pytest dv_harness_tests/test_pueue_client.py dv_harness_tests/test_cli_pueue.py -q --tb=line -rEf
ERROR ...TestRealPueueIntegration::test_real_version - AssertionError: real pueued did not come up
  (and 5 more, all the same assertion)
FAILED ...TestPueueAddAndStatus::test_add_then_status_shows_the_task - assert 1 == 0
  (and 4 more)
5 failed, 31 passed, 6 errors in 238.72s
```

These are the live-`pueued`-daemon integration tests. The daemon will not come
up on this machine right now — several sibling gap-close workstreams were
running their own heavy suites against the same single local daemon
concurrently with this one. **Pre-existing and environmental, not caused by
this change**: nothing in this change touches `pueue_client.py`, `cli.py`'s
pueue verbs, or any process/daemon path — it adds one method to
`engine.DVHarness` and edits one docstring. Every suite that does exercise the
code paths this change touches (engine routing/gates, graph fan-out, the
question queue, the blackboard subsystem wiring, the waveform-dump gate) is in
the 341-passing run above.

**Concurrency caveat, stated rather than hidden**: three other gap-close
workstreams committed to this branch and had uncommitted edits to
`dv_harness/engine.py`, `dv_harness/capability_evolution.py` and `CLAUDE.md` in
the working tree during these runs. This commit was therefore staged with the
hand-scoped-patch technique (`git diff > patch`, trimmed to this workstream's
single hunk, `git apply --cached --check` then `--cached`), so the committed
`engine.py` delta is exactly the +66 lines of this change and none of theirs.

---

## 5. Files changed

- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\engine.py` (+66)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\question_queue.py` (docstring only, +10/-6)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\CLAUDE.md` (+55, new dated section)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_question_queue_digest_auto_trigger.py` (new)
