# 3-Tier Ask-a-Human Protocol + Question-Queue Mechanics (Spec Part B)

Date: 2026-09-03
Scope: Part B only (the 3-tier self-resolve/safe-assume/escalate decision logic, Q-ID schema,
decisions.md persistence, owner routing, digest batching, 4 tracking metrics). Part A
(env.manifest.json + MCP server) and Part C (bind-location/connectivity) are separate workstreams
and out of scope here; this module is written to consume Part A once it exists (`manifest_lookup`
injection point) without depending on it today.

## What was built

- **`dv_harness/question_queue.py`** (new module) -- `classify_tier()` / `is_cannot_assume()`
  (hard-coded Tier-3 predicate), `route_owner()` (literal domain->owner table), and
  `QuestionQueueStore` (add/list/answer/build_digest/compute_metrics), all backed by
  `.dv-harness/question_queue/{questions.json,decisions.json,decisions.md}` under the project
  root -- same per-project `.dv-harness/**` layout convention as `storage.StateStore`/
  `memory.MemoryStore`/`evidence_db.default_db_path`.
- **`dv_harness/schemas/question.schema.json`** -- Draft 2020-12 JSON Schema, same rigor/style as
  `dv_harness/uvm_generator/schemas/run_profile.schema.json` (per-field descriptions, `$defs`-free
  since this schema doesn't need them, `allOf`/`if`/`then` pinning the exact domain->owner literal
  per Part B). Required fields exactly as specified: `id`, `blocking`, `domain`, `owner`,
  `question`, `context_path`, `options[]` (`minItems: 2`, `maxItems: 3`), `recommendation`,
  `assumption_if_unanswered` -- plus lifecycle bookkeeping fields (`tier`, `tier_reason`, `status`,
  timestamps, digest/decision linkage) needed to make the queue itself functional.
  `validate_question()` (mirrors `run_profile.py`'s own `validate_run_profile()` pattern exactly)
  also enforces the one cross-field rule JSON Schema alone can't express: `recommendation` must be
  one of `options[].label`.
- **Tier classification** (`classify_tier`) -- Tier-3 (`is_cannot_assume`) is a pure boolean OR
  over 3 literal flags (`affects_pass_fail_verdict`, `affects_spec_intent`,
  `affects_read_only_file_change`), no scoring/weighting, exactly the "hard-coded trigger, not a
  judgment call" the spec asks for. Tier-2 admission additionally requires `blast_radius ==
  "single_regression"` (Part B's own bar: "worst case = one wasted regression") -- a wider blast
  radius escalates to Tier 3 even with no named trigger tripped. **A persisted prior decision
  always overrides everything else**, including a context that would otherwise re-trip a Tier-3
  hard trigger -- this one rule is what makes the repeat-question-rate=0 guarantee provable rather
  than merely likely.
- **Owner routing** (`route_owner`) -- literal table: `vip -> DV-owner/Synopsys-AE`, `dut ->
  designer`, `env -> DV-owner`; unknown domain raises `ValueError`. Also pinned redundantly at the
  schema level via `allOf`/`if`/`then`.
- **decisions.json + decisions.md persistence** -- a **dedicated decisions store**, not a record
  folded into env.manifest.json. Documented rationale (also in the module's own docstring):
  env.manifest.json is Part A's generated/diffable FACT file (re-derivable from VIP/DUT/env
  sources); a human's answer+basis+owner is a DECISION, a different kind of record, and mixing the
  two would make env.manifest.json's regeneration diff noisy with content no regeneration would
  ever reproduce. This store works standalone today (Part A doesn't exist yet) and is written so
  Part A's future MCP `get_*` verbs can consult it as one more fact source with no format change.
  `decisions.md` is **regenerated in full** from `decisions.json` on every `answer` call (never
  hand-appended), so it can never drift from what a repeat-check actually reads.
- **Digest batching** (`build_digest`) -- never fires from `add_question()` itself (Part B: "never
  real-time pings" -- confirmed by a test that adding a question produces zero stdout/side-channel
  output). Three explicit trigger windows: `manual` (an explicit end-of-run/daily-cron call, always
  emits if anything is pending), `stage_boundary` (fires only when the passed `stage` is one of
  `DIGEST_BOUNDARY_STAGES = {REGRESSION_MONITOR, COVERAGE_CLOSURE, RE_AUDIT, SIGNOFF}` --
  `dv_harness.models.Stage` values reused as the natural regression-cycle boundary this harness
  already tracks, per the task's own hint, rather than inventing a timer), and `scheduled` (fires
  once `min_hours_since_last` has elapsed since the last real emission -- the literal daily
  cadence for a caller with no stage context). **Not wired into `engine.py`'s own stage-transition
  code in this change** -- `engine.py` is owned by the concurrent "exemptions + harness
  reliability" workstream this session and was explicitly off-limits to edit. The integration point
  for a future pass is one call, `build_digest(store, trigger="stage_boundary", stage=new_stage)`,
  right after that code's own stage-transition point.
- **4 tracking metrics** (`compute_metrics`) -- `self_resolve_rate_percent` (target field included:
  90.0), `blocking_questions_per_week` (Tier-3 asks in a trailing window, normalized to 7 days),
  `repeat_question_rate_percent` (percent of re-asks of an already-decided `question_key` that did
  **not** resolve at Tier 1 -- structurally provable 0 given the persistence guarantee, and also
  independently verified nonzero-when-broken via a synthetic-bad-data unit test), and
  `assumption_overturned_rate_percent` (percent of question_keys that were ever given a Tier-2
  auto-assumption whose value a later real human answer genuinely changed).
- **CLI**: `dv-harness question-queue {add, list, answer, digest, status}`, added to
  `dv_harness/cli.py` following the existing `knowledge`/`memory` subcommand-group convention
  (`sub.add_parser` + `add_subparsers(dest=...)`, one `elif args.qq_cmd == ...` branch per verb,
  `h.store.event(...)` audit logging on every mutating verb, same as `cmd_correct`/`cmd_approve`
  in `commands.py`). `add` validates `>= 2` options before calling into the store; `answer` defaults
  `--decided-by` to the CLI's own `_access_user()` fallback chain, matching every other
  human-attribution field in this CLI.

## Concurrency discipline followed

`git status --short` / `git diff --stat` were run on every shared file (`cli.py`, `config.py`,
`engine.py`) before and after editing. `config.py` and `engine.py` were **never edited** by this
change (both are owned by the concurrent "exemptions + harness reliability" workstream, confirmed
untouched at the end: `git diff --stat -- dv_harness/cli.py` shows exactly 256 insertions / 0
deletions, all additive and all mine; `config.py`/`engine.py` show sibling-workstream diffs this
change never touched). No `question_queue`-specific config block was added to `config.py`'s
`DEFAULT_CONFIG` -- the module needs no global config (it only ever reads/writes its own
`.dv-harness/question_queue/**` path), so there was no need to touch that off-limits file at all.
This change was **not committed** -- left for the user/orchestrator to fold in alongside the other
concurrent workstreams' own commits, since `cli.py` in particular is being edited by more than one
effort this session.

## Files

- `dv_harness/question_queue.py` (new)
- `dv_harness/schemas/question.schema.json` (new)
- `dv_harness/cli.py` (edited -- additive only, +256/-0: `question-queue` argparse block +
  dispatch `elif`)
- `dv_harness_tests/test_question_queue.py` (new, 26 tests)
- `dv_harness_tests/test_cli_question_queue.py` (new, 7 tests)

## Test results

```
python -m pytest dv_harness_tests/test_question_queue.py dv_harness_tests/test_cli_question_queue.py -q
.................................
33 passed in 10.05s
```

Coverage against the task's explicit test requirements:
- Tier-classification predicate, both directions: `test_tier3_fires_on_*` (3 hard triggers) +
  `test_tier3_fires_when_blast_radius_exceeds_single_regression` for a genuine Tier-3;
  `test_genuine_tier2_case_no_triggers_low_blast_radius` and
  `test_genuine_tier1_case_resolvable_from_manifest` for genuine Tier-1/2 cases;
  `test_prior_decision_always_overrides_hard_triggers` for the override rule itself.
- Repeat-question-rate=0 guarantee: `test_asking_the_same_question_twice_self_resolves_the_second_time`
  asks the identical question twice (answering it in between), asserts the second ask is Tier 1 /
  `SELF_RESOLVED` (found via decisions.json) rather than a fresh Tier-3 escalation, and asserts
  `compute_metrics()["repeat_question_rate_percent"] == 0.0`; mirrored end-to-end through the CLI in
  `test_answer_then_repeat_add_self_resolves_via_cli`. A companion test
  (`test_repeat_question_rate_is_nonzero_if_prior_decision_is_ignored`) hand-crafts a broken-
  persistence scenario to confirm the metric is a real computation, not a hardcoded 0.
- Owner routing: `test_owner_routing_literal_table` + `test_owner_routing_rejects_unknown_domain`.
- Digest batching: `test_digest_manual_trigger_emits_pending_and_groups_by_owner`,
  `test_digest_does_not_reemit_already_batched_questions`,
  `test_digest_stage_boundary_trigger_only_fires_on_known_boundary_stages`,
  `test_digest_scheduled_trigger_respects_min_hours_since_last`.
- Also: schema/`validate_question` structural rule tests, assumption-overturned-rate tests (both a
  real overturn and a confirmed-unchanged non-overturn), self-resolve-rate/blocking-per-week
  metric tests, and a "never real-time pings" test asserting `add_question()` produces no stdout.

A spot-check regression run of unrelated pre-existing CLI test files
(`test_cli_memory_commands.py`, `test_cli_blackboard.py`, `test_cli_git_guard.py` -- 32 tests) was
also run clean after the `cli.py` edit, confirming the new subcommand group did not disturb
existing argparse wiring.

## DONE

Test summary: 33/33 new tests passing (26 module-level + 7 CLI-level); a 32-test spot-check of
pre-existing CLI tests remains green after the `cli.py` edit.
