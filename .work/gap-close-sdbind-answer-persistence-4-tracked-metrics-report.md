# Gap-close: Answer persistence + 4 tracked metrics

**Result: NO_ACTION_NEEDED** — all 5 items re-verified READY against current code. No file modified, no commit made.

Scope: answer persistence + the 4 named tracking metrics. Audit-only outcome; the incoming audit found no BLOCKED or PARTIAL items in this scope and re-verification confirms that against the *current* tree.

## Re-verification method

The incoming audit's line numbers were **stale** — `question_queue.py` grew since it was written (a 2026-09-04 "Blackboard mirror" block was added to the module docstring and a `_sync_decisions_to_blackboard()` call was added inside `_save_decisions()`). Every citation below is re-derived from the current file, and every behavioural claim was re-proven by running code, not by reading it.

## Verdicts

### Answer persistence — READY (re-confirmed)

- Write-back chain re-located and re-read in full: `answer_question()` (`dv_harness/question_queue.py:780-813`) → `_persist_decision()` (`:614-646`) → `_save_decisions()` (`:453-456`) → `_render_decisions_md()` (`:520-568`).
- `decisions.md` is **regenerated in full** from `decisions.json` on every write (`:520-524` docstring + `:568` `write_text`), never hand-appended — so it cannot drift from the JSON store the repeat-check actually reads.
- Each entry renders **Answer, Basis, Decided by, Decided at, Source**, plus `ever_tier2_assumed` / `overturned` flags (`:542-551`).
- Live proof of the "never asked again" guarantee (fresh temp root): first ask returned `tier=2 status=ASSUMED`; after `answer_question(... answer='legal' ...)`, re-asking the identical `question_key` returned **`tier=1 status=SELF_RESOLVED answer=legal`** — resolved from the decisions store, not re-escalated. `decisions.md` assertion for `**Answer:** legal` / `**Basis:** Confirmed against spec section 4.2` / `**Decided at:**` returned `True`.
- Separation from the fact layer re-confirmed: `grep -n "decision|question_queue" dv_harness/env_manifest.py` → **no matches**. Deliberate and documented (`question_queue.py:1-25`): env.manifest.json is the re-derivable FACT file; a human answer is a DECISION. Spec said "manifest **or** a decisions.md" — the disjunction is satisfied.
- Real CLI wiring: `dv_harness/cli.py:2162-2225` (`question-queue` add/answer/revoke/digest, each emitting an event).
- Second real caller: `dv_harness/connectivity.py:1401-1495` (T4 bind path renders a question-queue artifact from this same store).

### Metric 1 — Self-resolve rate (target >90%) — READY

`compute_metrics()` at `:877-956`; computed `:908-910`, emitted with `"self_resolve_rate_target_percent": 90.0` (`:945-946`). Live run returned `50.0` on a 2-question store (1 of 2 Tier-1) — a real computation that tracks the data, not a stub.

### Metric 2 — Blocking questions/week — READY

`:911-913` — Tier-3 `blocking=True` asks inside a trailing `window_days`, normalized to a 7-day rate. Live run with one hard-trigger Tier-3 question (`tier=3 blocking=True status=OPEN`) returned **`blocking_questions_per_week = 1.0`**.

### Metric 3 — Repeat-question rate (>0 = persistence broken) — READY

`:915-938` — walks each `question_key`'s asks in creation order, counts any ask *after* a human answer exists that failed to resolve at Tier 1. Correctly excludes revoked keys (`:920`, `:931-932`) and deliberately does **not** treat a Tier-2 auto-assumption as "already decided" (documented `:889-898`), so a correct Tier-3 escalation past a provisional guess is not miscounted as a persistence bug. Live run returned **`0.0`**, correctly zero because the persistence path above genuinely works.

### Metric 4 — Assumption-overturn rate — READY

`:940-943` over the decisions store; `overturned` is set only when a later real human answer **differs in value** from the Tier-2 auto-assumption (`_persist_decision:632-637`, case-insensitive compare). Live run: a Tier-2 `ASSUMED` question with assumption `default`, later answered `custom` by a human, returned `overturned=True` and **`assumption_overturned_rate_percent = 100.0`**. The metric responds to a real overturn, not merely to the presence of Tier-2 entries.

## Test summary

`python -m pytest dv_harness_tests/test_question_queue.py -q` → **47 passed in 5.68s** (up from the audit's 37; concurrent work added tests). Suite includes dedicated coverage for this scope: `test_decisions_md_is_generated_and_contains_the_answer`, `test_repeat_question_rate_is_nonzero_if_prior_decision_is_ignored`, `test_assumption_overturned_rate_reflects_a_real_overturn`, `test_assumption_confirmed_unchanged_is_not_counted_as_overturned`, `test_metrics_on_empty_store_are_well_defined`, `test_prior_HUMAN_decision_overrides_hard_triggers`, `test_prior_decision_without_a_source_is_not_treated_as_human`.

## Concurrency note

Per the multi-agent warning, `git status` was checked before any work. `dv_harness/question_queue.py` and `dv_harness_tests/test_question_queue.py` were **clean** (unmodified) throughout, and remain unmodified — no patch was needed, so no `git apply` staging was performed. Concurrently-modified files in the tree (`cli.py`, `engine.py`, `signoff_export.py`, and others) were **read only**, never written.

## Non-defect observed

Passing `blackboard=False` (my own API misuse — the parameter expects a blackboard object or `None`) printed `blackboard decisions sync failed: 'bool' object has no attribute 'write'` and **still completed the decisions.json + decisions.md write**. That is the documented best-effort contract (`_sync_decisions_to_blackboard` docstring, `:466-479`: "Never raises: a blackboard write failure must not turn an already-written decisions.json into a failed `question-queue answer`"). Correct behaviour, not a gap.
