# Gap fix: question-queue Tier-3 bypass (F3-a / F3-b)

**Status: DONE.** `48 passed` — `dv_harness_tests/test_question_queue.py` +
`dv_harness_tests/test_cli_question_queue.py` (was 32 before this change; 16 new tests,
1 existing test rewritten because it asserted the defect).

Both reviewer repros are reproduced literally below, with real before/after output captured
from the same shipped code path (`QuestionQueueStore.add_question`) an agent actually uses,
plus the CLI equivalents.

## What was broken

`classify_tier()` could be bypassed two independent ways, each letting a genuine Tier-3
(cannot-assume, must-escalate) question resolve silently at Tier 1 with a machine-generated
answer that no human ever saw. Neither bypass surfaced in a digest (`build_digest()` only
batches `OPEN`/`ASSUMED`, and both resolved as `SELF_RESOLVED`), and neither was reversible.

## Files changed

| File | Change |
|---|---|
| `dv_harness/question_queue.py` | Reordered `classify_tier()`; `HUMAN_DECISION_SOURCE` / `_is_human_decision()` / `hard_triggers()`; gated the manifest consult in `add_question()`; new `QuestionQueueStore.revoke_decision()`; `decisions.md` revoked section; `repeat_question_rate` semantics |
| `dv_harness/schemas/question.schema.json` | New enforced `allOf`/`if`/`then`: `tier == 3 => blocking == true` |
| `dv_harness/cli.py` | New `question-queue revoke` verb (parser + handler + `GIT`-style event log entry) |
| `dv_harness_tests/test_question_queue.py` | 12 new tests incl. both repros; `test_prior_decision_always_overrides_hard_triggers` rewritten |
| `dv_harness_tests/test_cli_question_queue.py` | 4 new tests: both repros at the CLI boundary + `revoke` |

---

## Defect F3-a — a Tier-2 auto-assumption permanently suppressed a later genuine Tier-3

`classify_tier()` returned Tier 1 for **any** prior decision found in `decisions.json`,
without checking whether it came from a human or from the harness's own earlier Tier-2
auto-assumption (`add_question` persists a machine decision for every Tier-2 case, with
`source="tier2_auto_assumption"`).

**Repro:** ask a low-risk-looking question (no risk flags) → Tier 2, auto-assumed, decision
persisted. Ask the *same* `question_key` again with every Tier-3 hard trigger set.

### BEFORE

```
ask#1 (no risk flags): tier=2 status=ASSUMED reason=no_hard_trigger_low_blast_radius
  persisted decision source=tier2_auto_assumption
ask#2 (ALL Tier-3 hard triggers set): tier=1 status=SELF_RESOLVED blocking=False reason=decisions_store_hit
  answer='Assume legal drop per spec.' decided_by='dv_harness.question_queue(auto)'
  digest emitted=True n_questions=1
```

A question flagged `affects_pass_fail_verdict` + `affects_spec_intent` +
`affects_read_only_file_change` + `blast_radius=unbounded` was answered with the harness's
own earlier guess, attributed to `dv_harness.question_queue(auto)`, and the digest carried
only 1 question (ask#1's `ASSUMED` record) — the escalation itself was invisible.

### AFTER

```
ask#1 (no risk flags): tier=2 status=ASSUMED reason=no_hard_trigger_low_blast_radius
  persisted decision source=tier2_auto_assumption
ask#2 (ALL Tier-3 hard triggers set): tier=3 status=OPEN blocking=True reason=hard_trigger:affects_pass_fail_verdict,affects_spec_intent,affects_read_only_file_change;overrides_prior_non_human_decision
  answer=None decided_by=None
  digest emitted=True n_questions=2
```

Tier 3, `OPEN`, `blocking=True`, no machine answer, and now `n_questions=2` — the escalation
genuinely reaches a human through the digest.

**Fix:** the hard-trigger check runs first, and a prior decision only shortcuts to Tier 1 when
`current.source == "human_answer"`. A non-human prior decision that is overridden is recorded
in `tier_reason` as `;overrides_prior_non_human_decision`, so the override is auditable rather
than silent. A *human's* answer still wins over a hard trigger — that is the intended
"once a human answers, never ask again" guarantee, and it is safe precisely because a human
supplied it.

**Fail-closed detail:** a decision entry with no recorded `source` (hand-written or legacy) is
**not** treated as a human answer
(`test_prior_decision_without_a_source_is_not_treated_as_human`).

---

## Defect F3-b — `manifest_lookup` resolved before the hard-trigger check, and never verified relevance

The `resolvable_from_manifest` check ran **before** the hard-trigger block, and the lookup is
keyed only on `context_path` — it never checks whether the fact it found actually answers the
question being asked.

**Repro:** a pure spec-intent question against a store with a `manifest_lookup` wired in that
returns an unrelated register dict.

### BEFORE

```
pure spec-intent question: tier=1 status=SELF_RESOLVED blocking=False reason=resolvable_from_manifest
  answer="{'TX_ERR': {'offset': '0x40', 'width': 32, 'access': 'RW'}}"
  decided_by='env.manifest.json'
```

"Is a dropped packet flagged in TX_ERR a legal drop per spec, or a real DUT failure?" —
a pass/fail-verdict, spec-intent, unbounded-blast-radius question — was answered with a
register's offset/width/access.

### AFTER

```
pure spec-intent question: tier=3 status=OPEN blocking=True reason=hard_trigger:affects_pass_fail_verdict,affects_spec_intent
  answer=None
  decided_by=None
```

**Fix:** three layers, deliberately redundant.

1. The hard-trigger check runs first, so the manifest shortcut can no longer preempt it.
2. The shortcut inside `classify_tier()` is additionally gated on
   `is_cannot_assume(context) == False`, so the guarantee survives any future reordering.
3. `add_question()` **skips the lookup call entirely** for a cannot-assume question — the
   test asserts `lookups == []`, i.e. the manifest is not merely overruled but never
   consulted.

Layer 3 matters for the finish report's recommended next step (wiring `manifest_lookup` into
every `QuestionQueueStore` caller): with the old ordering that would have made this bypass
live in production immediately.

The legitimate Tier-1 manifest path is unaffected —
`test_manifest_lookup_still_resolves_a_genuinely_low_risk_question` proves a low-risk question
still self-resolves from the manifest.

---

## Schema rule: `tier == 3 => blocking == true`

`blocking`'s description already said "true iff tier == 3", but a description is not a
constraint, so a hand-built `{tier: 3, blocking: false, status: "SELF_RESOLVED"}` record —
a cannot-assume question that never stops for a human — validated cleanly.

**BEFORE:** `validate_question() ACCEPTED tier=3/blocking=false  <-- DEFECT`

**AFTER:** `validate_question() REJECTED: question failed schema validation:  - at blocking: True was expected`

The new `allOf` entry is **one-directional on purpose**: tier 3 pins `blocking` to true, while
tier 1/2 are left to the `blocking` boolean itself rather than being pinned to false. The
constraint can therefore only ever add escalation, never suppress it.

---

## New `question-queue revoke` verb

Previously there was no way to undo an auto-assumed decision short of hand-editing
`decisions.json`, which `decisions.md` itself tells its reader not to do.

```
dv-harness question-queue revoke <question_key> --reason "<why>" [--revoked-by <who>]
```

Backed by `QuestionQueueStore.revoke_decision(question_key, *, reason, revoked_by=None)`.
The entry is **moved** to the store's `revoked` list with who/when/why attached, never
deleted: `find_decision()` stops seeing it (so it can no longer shortcut anything) while the
record of what the harness once believed, and who withdrew it, survives — and is rendered as
a "Revoked decisions" section in the generated `decisions.md`. Unknown keys raise `KeyError`
(CLI: `{"ok": false, ...}`, exit 1). Each revoke logs a `question-queue-revoke` event to
`.dv-harness/events.jsonl`, same audit trail as `add`/`answer`/`digest`.

---

## One consequential judgment call, flagged for review

`repeat_question_rate` previously treated **any** of `SELF_RESOLVED`/`ASSUMED`/`ANSWERED` as
"this key is now decided", so every later ask of that key had to be Tier 1 or it counted as a
persistence failure. Under the F3-a fix, a later Tier-3-triggering ask of a Tier-2-assumed key
is *supposed* to escalate — so leaving the metric alone would have made it report 100%
("persistence is broken") on exactly the behavior this fix introduces, i.e. fire on the fix
rather than on a real bug.

The metric now counts a key as decided only once a **human** answer exists (`status ==
"ANSWERED"`), and excludes keys deliberately withdrawn via `revoke_decision()`. The existing
tests that prove the metric measures something real (0.0 on a correct repeat, 100.0 on the
hand-built broken-persistence scenario) both still pass unchanged.

---

## Verification

```
$ python -m pytest dv_harness_tests/test_question_queue.py dv_harness_tests/test_cli_question_queue.py -q
48 passed
```

Related suites also re-run green to confirm no collateral damage
(`test_connectivity.py`, `test_env_manifest.py`, `test_exemptions.py`, `test_mcp_verbs.py`,
`test_mcp_manifest_and_schema.py`): **242 passed**.

`connectivity.py`'s `build_t4_question_queue_entry()` was checked and is unaffected — it emits
no `tier` field and is never run through `validate_question()`; its reconciliation against the
real Part-B schema remains that workstream's own open flag.

### The two most important tests

- `test_F3a_tier2_auto_assumption_does_not_suppress_a_later_genuine_tier3` (unit) /
  `test_F3a_tier2_assumption_does_not_suppress_a_later_tier3_via_cli` (CLI)
- `test_F3b_manifest_lookup_cannot_resolve_a_hard_trigger_question` (unit) /
  `test_F3b_manifest_flags_cannot_resolve_a_hard_trigger_question_via_cli` (CLI)
