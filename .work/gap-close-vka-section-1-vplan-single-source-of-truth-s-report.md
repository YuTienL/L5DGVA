# Gap-close report — VKA Section 1: vPlan single-source-of-truth + structured exemptions

Date: 2026-09-04
Scope: exactly Section 1 of the "把驗證知識變成可執行的資產" audit — items 1a and 1b.
Mode: LOCAL_ANALYSIS (pure local read/edit/test; no server, no VCS, no simulation).

## Verdict

| Item | Audit verdict | This pass |
|---|---|---|
| 1b — structured exemptions actually READ in a real flow | PARTIAL | **DONE** |
| 1a — gate pipeline never surfaces the per-item gap list | PARTIAL (sub-gap #2) | **DONE** |
| 1a — derive `covered_by` from real regression/testlist evidence | PARTIAL (sub-gaps #1, #4) | **NEEDS_SEPARATE_EFFORT** |

Test summary: **1234 passed, 0 failed** over the full 26-file affected-suite
sweep (every test file mentioning question_queue / exemptions / vplan, plus
the engine gate-routing and blackboard-wiring suites) — `1234 passed in
2173.03s (0:36:13)`. 29 of those are new: `test_exemptions_read_path.py` (23,
new file) and 6 added to `test_vplan_writer_validation_gate.py` (12 → 18).

---

## Re-verification of the audit's claims, before changing anything

Every claim below was re-run this session, not taken from the audit text.

- `grep -rn "covered_by" dv_harness tools --include=*.py | grep -v vplan_writer`
  → **zero hits**. Confirmed: nothing derives an item's covered-by state from
  real data.
- `grep -rn "load_exemptions_document|list_exemptions|check_expiry|build_review_queue|find_expired|find_active" --include=*.py .`
  → matched only `dv_harness/cli.py` (its own `exemptions` handlers),
  `dv_harness/exemptions.py` itself, and `dv_harness/design_intent.py:251`
  (a *writer*: `write_exemptions_from_constraints()` calls `list_exemptions`
  only to dedupe before adding). Confirmed: **no automatic reader existed.**
- `grep -n "review_queue\|exemption" dv_harness/question_queue.py` → no
  matches. Confirmed.
- `tools/vplan/vplan_writer_validation_gate.py` printed exactly
  `{"status": "PASS", "item_count": N}`. `tools/vplan/spec_coverage_audit.py`
  printed only `total`/`credited`/`coverage_percent`/`invalid`. Confirmed:
  the VPLAN stage gate could not answer "which item has no test".
- Baseline before any edit: `pytest test_exemptions.py test_question_queue.py
  test_vplan_writer.py -q` → `109 passed in 42.46s`.

---

## Item 1b — structured exemptions: DONE

The store was real and expiry-driven, but write-plus-manual-CLI-read only.
Both guarantees the spec asks for ("an agent doesn't re-litigate a check an
exemption covers", "a temporary workaround doesn't become permanent") were
therefore unenforced on every automatic path. Closed by giving the store two
real readers on the ask path, extending existing modules rather than adding a
parallel mechanism.

### `dv_harness/exemptions.py` — the lookup verb that was missing

`find_active_exemption(path, check_id, as_of=None) -> Optional[dict]`
(`exemptions.py:319`). `find_active()` returned every active entry and left
check_id matching to each caller — the per-caller re-implementation this
module exists to prevent. Deliberate properties, each tested:

- literal, case-sensitive `check_id` equality — never prefix/substring, because
  the schema defines `check_id` as "the concrete real check, never a vague
  category", and a fuzzy match would let one exemption silently cover checks
  nobody exempted;
- an **expired** entry is never returned, even though it is still on file —
  that is what `valid_until` is for;
- `retired` excluded;
- when two active entries name one check (the schema's own
  "superseded/re-approved" case), the latest `valid_until` wins, ties broken
  on `id` so the result is deterministic.

### `dv_harness/question_queue.py` — reader #1: the ask path

`QuestionQueueStore.__init__` gained `exemptions_path`, **defaulted ON** to
the project's real `exemptions.yaml` (`question_queue.py:531`). Opt-in would
have reproduced exactly the gap being closed — the same reasoning the
blackboard mirror above it already uses. A project with no file costs nothing:
`load_exemptions_document()` treats a missing file as an empty valid document.

`find_exemption()` (`question_queue.py:536`) is consulted by `add_question()`
on every question whose `context` carries a `check_id` — a caller assertion
that this question is about that check, the same honest-flag discipline the
three Tier-3 hard triggers already run on. No `check_id`, no lookup; this never
guesses which check a question concerns from its free text.

`classify_tier()` takes a new `exemption=` argument. **Placement was the real
design decision**, and it is not at the top:

- A decisions-store hit is keyed on `question_key` — a digest of the exact
  question text plus context_path — so it is a precise match: the human
  answered *this* question. That is why it may override a hard trigger.
- An exemption is matched on `check_id` alone, which establishes only that the
  question is *about* the check. "The check is off because of an IP
  restriction" does not answer "is this PASS real". Letting a coarse key
  resolve a hard-trigger ask is precisely review defect F3-b, and nicer
  provenance does not make it safe.

So: an active exemption self-resolves at Tier 1 (reason `active_exemption`,
ahead of the manifest shortcut, since it carries a named owner, a cited basis
document and an expiry where a manifest lookup carries only a value found at a
path), but a hard-trigger question **still escalates** — carrying the
exemption. `tier_reason` gains `;covered_by_active_exemption:<id>` and the
question record carries a full `exemption` citation block on *every* tier. That
is "never re-litigate" at Tier 3: carry the prior decision into the escalation,
as distinct from suppressing it.

`EXEMPTION_TIER1_REASON = "active_exemption"` is deliberately **not**
`decisions_store_hit`: anyone auditing why a question never reached a human
must be able to tell an exemption-backed self-resolve (expires on its own
`valid_until`, owned by the exemption's owner) from a persisted human answer
(never expires, lives in `decisions.json`).

**The exemption-backed answer is deliberately NOT persisted as a decision.**
A decision is permanent until revoked; this exemption expires. Minting one from
the other would outlive the exemption and go on suppressing the question past
its owner's own re-review date — converting the temporary workaround into the
permanent, never-revisited fact `valid_until` exists to prevent.
`exemptions.yaml` stays the single source for that answer. Tested.

`find_exemption()` swallows store errors and returns None. A schema-invalid or
hand-edited-broken `exemptions.yaml` must not take down an unrelated question,
and the swallow **fails toward asking the human** — the worst case is one
question that could have been suppressed getting asked, never a suppression
granted by a store nobody could read. `dv-harness exemptions check` is where a
broken store is meant to be surfaced loudly. Tested.

### `dv_harness/question_queue.py` — reader #2: expiry becomes a real question

`escalate_expired_exemptions()` (`question_queue.py:980`) consumes
`exemptions.build_review_queue()` — the hand-off shape `exemptions.py`'s own
docstring had shaped for this module and that nothing had ever read — and files
each expired entry as a real Tier-3 blocking question with a Q-ID, an owner and
a digest slot. Tier 3 is not asserted here: an expired exemption means a check
is currently disabled with no live sanction, which is `affects_pass_fail_verdict`
in the literal sense of that flag, so `classify_tier()` reaches Tier 3 on its
own rules. The exemption is expired, so `find_exemption()` returns None for its
check_id and nothing suppresses the escalation it just triggered.

Idempotent: `question_key = "exemption-expiry:<exemption_id>"`, so a rerun over
an unchanged file re-mints the same key and files nothing — the same discipline
`source_authority.escalate_conflict()` uses. It still refreshes
`review_queue.json`, so the documented hand-off path stays current for any
further consumer.

Routed to domain `env` because `route_owner()` is a literal 3-domain table and
the schema pins `owner` per domain; the exemption's own free-text `owner` rides
in the question text and the citation block rather than being smuggled into a
field the schema constrains.

### `dv_harness/cli.py` — `dv-harness exemptions escalate`

`expire-report` wrote `review_queue.json` and stopped, so an expiry reached a
human only if someone ran that command by hand. `escalate` files the questions
for real. It exits nonzero on **expired**, not on newly-filed: a second run
files nothing (idempotent) but the exemption is still lapsed and still
unanswered, so a CI step must not start passing just because the question
already exists. Tested both ways.

### `dv_harness/schemas/question.schema.json`

Added the optional `exemption` property (the schema is
`additionalProperties: false`). Additive and optional — every pre-existing
question record still validates.

---

## Item 1a — vPlan single source of truth

### Sub-gap #2 (gate never surfaces the gap list): DONE

`write_vplan_workbook()` had always computed the per-item gap list
(`_rank_gaps()`/`_deferred_rows()`), but only as a side effect of producing an
.xlsx — so the only way to obtain it was to write a file. That left the VPLAN
stage transition able to report PASS plus an aggregate `coverage_percent` and
nothing else: exactly the "answer a number of unhit bins, never which feature
has zero tests" shape this work exists to replace.

`vplan_writer.summarize_coverage_gaps(items)` (`writer.py:813`) is that same
computation with no file involved, exported from the package, and now included
in `tools/vplan/vplan_writer_validation_gate.py`'s JSON — which `gates.py:1188`
parses straight into `GateResult.detail`, so it really reaches the agent at the
stage transition.

It does **not** change the gate's verdict. An open gap mid-project is a normal
reportable fact, not a validation failure, and failing here would only teach
people to mark items covered to get past the stage. Tested
(`test_open_gaps_do_not_fail_the_gate`).

`test_summarize_coverage_gaps_matches_what_the_workbook_writer_computes`
asserts the gate is not a second, parallel computation — it is the same
`_rank_gaps()` output the .xlsx's "Table B — Gaps ranked" is rendered from, so
the gate's answer and the exported vPlan's answer cannot disagree.

### Sub-gaps #1 and #4 (evidence-derived `covered_by`): NEEDS_SEPARATE_EFFORT

The audit's primary finding on 1a — that `covered_by` is caller-asserted and
nothing derives it from real regression/testlist pass data — is **not closed
here, and should not have been attempted here.** It is a genuinely separate
effort, not a bounded completion:

- it needs a persistent vPlan-item store (today items are a transient argument
  to `write_vplan_workbook()`, never persisted under `.dv-harness/`);
- it needs a stable item↔test↔coverage-bin identity join against
  `evidence_db` / `regression_list_manager` results, which is the same
  three-way join `env_manifest`'s `testplan_correspondence` contract already
  models but does **not** feed back into `covered_by`;
- it needs a policy decision this pass has no mandate to make: whether a
  derived state may overwrite, or only contradict, a human's asserted one
  (a human asserting `NOT COVERED` on an item whose test happens to pass is
  information, not necessarily an error);
- the two unread schemas (`.dv-harness/vplan/{feature_mapping,testcase_manifest}.schema.json`,
  audit sub-gap #4) are readers-of-nothing precisely *because* that chain does
  not exist — they are a symptom of #1, not an independent gap.

Building any of it inside this scope would have been the gold-plating the task
brief explicitly warns against. The gate's own output now carries an honest
inline disclosure of this limit
(`vplan_writer_validation_gate.py`, the comment above the `print`), and so does
`summarize_coverage_gaps()`'s docstring: it reports the gaps the vPlan *itself
admits to*, never gaps discovered by comparing the plan against what actually
ran.

---

## Files changed

| File | Change |
|---|---|
| `dv_harness/exemptions.py` | `find_active_exemption()`; module docstring's "no consumer exists" section replaced with what actually reads the store now |
| `dv_harness/question_queue.py` | `exemptions_path` (default-on), `find_exemption()`, `_exemption_citation()`, `escalate_expired_exemptions()`, `classify_tier(exemption=)` + step-3 ordering rationale, `EXEMPTION_TIER1_REASON`, `EXEMPTION_EXPIRY_KEY_PREFIX`, `add_question()` consult + Tier-1 branch + citation attach |
| `dv_harness/schemas/question.schema.json` | optional `exemption` citation property |
| `dv_harness/cli.py` | `dv-harness exemptions escalate` (parser + handler) |
| `dv_harness/vplan_writer/writer.py` | `summarize_coverage_gaps()` |
| `dv_harness/vplan_writer/__init__.py` | export it |
| `tools/vplan/vplan_writer_validation_gate.py` | emit `coverage_gaps` in the gate's JSON |
| `docs/EXEMPTIONS.md` | corrected the now-false "no consumer" section; documented `escalate` |
| `dv_harness_tests/test_exemptions_read_path.py` | **new**, 23 tests |
| `dv_harness_tests/test_vplan_writer_validation_gate.py` | +6 tests |

Stale-comment hygiene (Engineering Discipline Rules + Evidence Truth Rule): the
"question_queue.py does not consume this module" disclosure in
`exemptions.py`'s docstring and in `docs/EXEMPTIONS.md` was true when written
and is now false. Both were rewritten to state what actually reads the store,
rather than left behind as a stale explanation.

## Tests

All end-to-end against real artifacts — a real `exemptions.yaml` written by the
real `add_exemption()`, a real `QuestionQueueStore` on a real temp filesystem,
the real gate script as a real subprocess, the real `dv-harness` CLI as a real
subprocess. No mocks, no hand-built dicts standing in for a store.

```
pytest <26 affected test files> -q                               -> 1234 passed in 2173.03s
pytest dv_harness_tests/test_exemptions_read_path.py -q          ->   23 passed  (new file)
pytest dv_harness_tests/test_vplan_writer_validation_gate.py -q  ->   18 passed  (12 pre-existing + 6 new)
pytest dv_harness_tests/test_question_queue.py test_exemptions.py -q ->  81 passed  (unchanged suites)
```

Baseline for comparison, taken before any edit:
`test_exemptions.py + test_question_queue.py + test_vplan_writer.py` →
`109 passed in 42.46s`. Same three suites after the change: still green.

Notable behaviours proven, not merely asserted:

- an active exemption self-resolves a question and the answer carries the real
  `reason`, the openable `basis_document`, and the accountable `owner`;
- the same ask comes back once `valid_until` passes;
- a hard-trigger question still blocks, but arrives carrying the exemption;
- a broken `exemptions.yaml` fails toward asking, never toward suppressing;
- the full lapse→escalate→renew→honour-again loop;
- the gate names USB2-CTRL-001 / USB2-BULK-002 / USB2-ISO-001 individually in
  close-first order with an actionable `why` for each — not a percentage;
- the gap list survives the real `gates.run_gate()` wrapper into
  `GateResult.detail`, which is what an agent at a VPLAN stage transition
  actually sees — not merely the script's own stdout
  (`test_gap_list_survives_the_real_gates_run_gate_wrapper`).

## Not touched, deliberately

`CLAUDE.md`, `dv_harness/engine.py` and `dv_harness/gates.py` are unmodified.
CLAUDE.md has no section describing the exemptions store (its only two
"exemption" hits are the connectivity-matrix identity and the context-budget
policy array, neither related), so there was nothing stale there to correct
and no reason to contend for a file three other concurrent workflows are
editing. `dv_harness/cli.py` was hand-checked before staging: `git diff -U0`
showed exactly the three hunks this pass wrote and nothing from a concurrent
workflow.
