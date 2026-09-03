# Gap-close: Checker/Scoreboard Planning Table (3-category + 7 required fields)

**Verdict: DONE**

Scope: `dv_harness/connectivity.py`'s checker/scoreboard planning-table generator.
Commit `656c8c6`, 2 files, +679/-20. Audit-only phase re-verified first; every
BLOCKED item closed, every bounded PARTIAL completed.

**Test summary**: 19 new tests in `dv_harness_tests/test_connectivity.py`
(120 -> 139 in that module); **358 passed** across every module that imports
`connectivity` (`test_connectivity`, `test_question_queue`,
`test_connectivity_check`, `test_bind_verification_lint`, `test_env_manifest`,
`test_amba_fabric_generator`, `test_bind_mechanism_generator`,
`test_context_budget`, `test_soc_environment_composer`). No pre-existing test
was modified or deleted.

---

## Re-verification of the audit's own findings (before changing anything)

The audit's line numbers had drifted (a concurrent workstream landed
`GateStatus.PENDING`/`assert_bind_gates_checkpoint()` above this section), so
every claim was re-confirmed against current code, not accepted on cited
line numbers. All of them held. The decisive one, live:

```
$ python -c "from dv_harness import connectivity as conn; print(conn.generate_scoreboard_entry('sb0', endpoint_pairs=[], matching_key=''))"
{'kind': 'data_integrity_scoreboard', 'scoreboard_id': 'sb0',
 'endpoint_pairs': [], 'matching_key': '',
 'ordering': 'REQUIRED_HUMAN_INPUT', 'transformation_rules': [], ...}
```

Empty endpoints and empty matching key accepted silently; `transformation_rules`
resolved to `[]`. Repo-wide grep confirmed `REQUIRED_HUMAN_INPUT` appeared
nowhere outside `connectivity.py` and its test file, and `confirm_row()` had no
sentinel check.

## READY items — re-confirmed, not touched

- **3-category classification**: `build_checker_scoreboard_plan()` still takes
  exactly the three lists, tagged `protocol_check` / `data_integrity_scoreboard`
  / `system_level`. `generate_protocol_check_entry()` still hard-errors
  `DISABLED_CHECK_NOT_IN_BUILTIN_LIST` / `DISABLED_CHECK_MISSING_REASON`.
- **Legal drop/backpressure**, **reset-time flush**, **orphan threshold +
  detection timing** (correctly two fields): sentinel defaults intact and still
  covered by their existing tests.

## BLOCKED items — built for real

### 1. `transformation_rules` silently defaulted to `[]`

`transformation_rules or []` meant an omitted input READ AS the positive claim
"this path performs no width conversion, no packetization and no byte-enable
remapping" — a claim no generator can derive, and precisely the setup for a
scoreboard that compares two differently-shaped payloads and passes anyway.

Now `transformation_rules if transformation_rules is not None else REQUIRED_HUMAN_INPUT`.
One deliberate distinction preserved: an **explicitly passed `[]`** still means
"a human looked and confirmed no transform" and stays `[]`. `None` and `[]` are
different claims and the table no longer conflates them.

### 2. "An empty field automatically becomes a question-queue entry"

The sentinel was a string nobody read. Closed by extending the existing modules,
not a parallel mechanism — this routes through the **same**
`question_queue.QuestionQueueStore` the T4 bind path (`build_t4_question_queue_entry()`)
already uses:

- `unfilled_plan_fields(entry)` — the fields still holding the sentinel.
- `SCOREBOARD_FIELD_QUESTIONS` — one pre-researched question per field, each with
  2-3 real options plus rationale and a recommendation. `domain` is a real claim
  about who knows the answer, not a catch-all: DUT reorder/drop/flush/transform
  behavior -> `dut` (designer); the transaction field tying request to response
  -> `vip`; where the scoreboard sits and how long it waits -> `env` (DV-owner).
- `route_unfilled_fields_to_question_queue(store, entry)` — persists each as a
  real question. All classify **Tier 3 / blocking**, and that tier is *derived*
  rather than hardcoded: every entry sets `affects_pass_fail_verdict`, which is
  honest — each of these fields decides whether the scoreboard reports a mismatch
  at all.
- `apply_answered_questions(store, entry)` — the read-back half. Gated on
  `question_queue.HUMAN_DECISION_SOURCE`, deliberately reusing `classify_tier()`'s
  own gate so the harness can never fill a mandatory-human-review field with its
  own tier-2 auto-assumption.
- `build_checker_scoreboard_plan(..., question_store=...)` — **always** reports
  `unfilled_fields` on the plan artifact (with or without a store, so a reader of
  the JSON never has to grep for the sentinel), and records `open_questions` when
  a store is supplied.

Live end-to-end, before the tests were written:

```
UNFILLED: ['ordering','ordering_tolerance_depth','transformation_rules',
           'legal_drop_conditions','reset_flush_behavior',
           'orphan_unmatched_threshold','orphan_unmatched_timeout']
  Q-DUT-E2CF95EA tier 3 blocking True owner designer  | OPEN
  ...
  Q-ENV-FC1089F9 tier 3 blocking True owner DV-owner  | OPEN
OPEN blocking count: 7
ordering after human answer: Strictly in-order
re-ask ordering -> tier 1 SELF_RESOLVED  same id: True
decisions.md written: .dv-harness/question_queue/decisions.md
```

The re-ask self-resolving at Tier 1 with the *same* Q-ID is the queue's own
"once a human answers, never ask again" guarantee holding through this path —
regenerating a plan re-asks nothing, so repeat-question-rate stays 0. Answer
persistence to `decisions.md` comes free from the existing store.

### 3. `confirm_row()` could lock a row still holding the sentinel

`RowLockStore.confirm_row()` now raises
`CANNOT_CONFIRM_ROW_WITH_UNFILLED_REQUIRED_HUMAN_INPUT` with the exact dotted
paths. This matters because confirming such a row marks it reviewed-and-locked,
after which `diff_rows_needing_reconfirmation()` stops re-surfacing it and the
unanswered field is never seen again. The scan
(`find_required_human_input_paths()`) is deliberately generic and recursive, so
it also catches e.g. a connectivity row whose `vip_type` is still unresolved.

## PARTIAL items — completed (all bounded; none needed a separate effort)

- **Comparison endpoints**: empty now resolves to the sentinel instead of passing
  silently, and each endpoint is validated as a full instance hierarchy path —
  a bare port name raises `ENDPOINT_NOT_A_HIERARCHY_PATH`. This is the
  Bind-Location rule-1 failure mode one level up: a bare name in a
  multi-instance SoC silently designates the wrong instance. Both `(source, sink)`
  tuples and `{"source":..., "sink":...}` dicts accepted; anything else raises
  `ENDPOINT_PAIR_MALFORMED`.
- **Matching key**: empty/whitespace resolves to the sentinel.
- **Ordering tolerance window depth**: now `ordering_tolerance_depth`, its own
  column in `SCOREBOARD_PLAN_FIELDS` with its own sentinel default and its own
  pre-researched question. Previously depth was captured only if a human happened
  to write it into the free-text `ordering` string.

Net: the table went from 5-of-7 fields sentinel-gated to **all 9 columns**
gated, with no field carrying a computed default.

## Concurrency handling

Several other workflows are live in this repo. `dv_harness/connectivity.py` and
`dv_harness_tests/test_connectivity.py` were verified clean before editing and
after. At commit time another agent had 13 unrelated files staged in the index,
so this used a path-scoped partial commit (`git commit --only <my two paths>`)
rather than any broad `git add` — verified afterwards that all 13 remained
staged and untouched. Another agent's commit (`0d1129e`) landed in between; the
full suite was re-run after it, still 358 passed.

## Note for whoever picks up the surrounding scope

Not a gap in *this* scope, but worth recording: this generator is still called
by no other module (`generator.py`, `soc_environment_composer.py`, no CLI). The
mechanism is now real, wired to the question queue, and tested end-to-end, but
the pipeline does not yet *invoke* it to produce a planning table for a real
build — the same "real but unwired" shape CLAUDE.md's Methodology Consolidation
Rule warns about. Wiring it into the generator pipeline is a separate, larger
effort than this scope covers.
