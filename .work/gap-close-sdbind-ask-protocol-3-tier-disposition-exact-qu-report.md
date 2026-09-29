# Gap-close: Ask-protocol — 3-tier disposition + exact question JSON schema + routing/batching

**Verdict: DONE** (one real, bounded gap closed; one divergence deliberately NOT closed, with evidence)

Scope: `dv_harness/question_queue.py`, `dv_harness/schemas/question.schema.json`, real call sites
in `cli.py` / `connectivity.py` / `uvm_generator/run_profile_to_justfile.py`, and
`dv_harness_tests/test_question_queue.py`.

Audit-only re-verification first; then implementation. **All line numbers in the incoming audit
were stale** — the files grew from concurrent workstreams during this session (the audit cited
`connectivity.py:1436-1443` and `cli.py:797-799`; the real current sites are
`connectivity.py:2698+` and `cli.py:2156/2170`). Every verdict below is re-cited against the
current code, not the audit's line numbers.

## Re-confirmation of the 5 READY items

Baseline before any change: `python -m pytest dv_harness_tests/test_question_queue.py
dv_harness_tests/test_cli_question_queue.py -q` → **48 passed**. Re-confirmed, no action taken:

1. **3-tier logic — READY.** `classify_tier()` / `hard_triggers()` / `is_cannot_assume()` are a
   pure boolean OR over the 3 literal flags, evaluated *first*, ahead of both Tier-1 shortcuts,
   with the ordering documented as the security property itself (F3-a / F3-b regression tests
   present and passing). Tier-2's admission bar (`blast_radius == "single_regression"`) is real
   code, not prose.
2. **Options-required (never open-ended) — READY.** Enforced at three independent layers
   (schema `minItems:2/maxItems:3`; `validate_question()`'s recommendation-in-labels cross-check;
   the real T4 caller's own hard length check). Re-verified working.
3. **Owner-routing — READY.** `route_owner()` is a literal table raising on an unknown domain,
   called *inside* `add_question()` (not caller-supplied), and independently pinned per-domain by
   the schema's `allOf` block.
4. **Digest-batching — READY.** `build_digest()` has no call site inside `add_question()`; three
   explicit trigger windows; all covered by passing tests.
5. **Answer-format symmetry — READY.** `answer_question()` writes back into the same record and
   the same `decisions.json`/`decisions.md`, which is what makes `classify_tier()` step 2
   self-resolve a repeat ask.

## The PARTIAL item, split into two divergences

The audit's single PARTIAL ("exact schema match") is really two independent divergences from the
spec's verbatim JSON example. They have opposite correct dispositions, so I treated them
separately rather than as one verdict.

### (a) `options` flat-string shape — **CLOSED, this was a real gap**

The spec's literal example is `["...", "..."]`. This was not merely a cosmetic divergence — the
module's own public API **crashed** on the spec's shape:

```
>>> store.add_question(..., options=['keep 8b10b', 'switch to 128b130b'], ...)
TypeError : string indices must be integers, not 'str'
```

`add_question()` indexed `o["label"]` directly, so a plain-string list died on a raw `TypeError`
— not a `QuestionValidationError` a caller could act on. Worse, **three separate call sites each
carried their own hand-rolled workaround copy** of the same normalization
(`o if isinstance(o, dict) else {"label": str(o)}` in `connectivity.py:2736` and
`run_profile_to_justfile.py:137`, plus `[{"label": o} for o in args.options]` in `cli.py:2171`),
precisely *because* the module itself would not accept the plain form. Those copies also passed
any dict straight through unchecked, so a `{"lable": ...}` typo surfaced as a schema traceback
from deep inside validation instead of at the caller's own boundary.

**Change:** added `question_queue.normalize_options()` as the single definition, called at the top
of `add_question()`. It accepts both the plain-string and object forms (and a mix), coerces to the
one canonical persisted shape, and raises `QuestionValidationError` — never `TypeError`/`KeyError`
— for a malformed element, unknown key, non-string label, empty label, or non-list. The three
hand-rolled copies now call it instead of re-implementing it.

**The schema was deliberately NOT loosened to accept bare strings.** A stored record keeps exactly
one options shape, so every reader (`validate_question()`'s label cross-check,
`_render_decisions_md`, `build_digest`) parses one thing rather than branching per element.
Allowing bare strings in storage would push that branch into every reader forever to buy nothing —
the string form is an ergonomic *input* convenience, not a second storage format. Normalization
happens once, at the door. That reasoning is recorded in both the helper's docstring and the
schema's own `options.description`, so the asymmetry is not mistaken for an oversight later.

Verified end-to-end through the real CLI (`--option "keep 8b10b" --option "switch to 128b130b"`
→ persisted `[{"label": "keep 8b10b"}, {"label": "switch to 128b130b"}]`, tier 2, owner
`DV-owner/Synopsys-AE`) and through the real T4 connectivity path (plain strings accepted,
tier 3 / blocking, and the `{"lable":...}` typo now caught as
`options[0] has unknown key(s) ['lable']`).

### (b) `id` date-sequence format — **deliberately NOT closed** (would be a real regression)

The spec's example is `"Q-20260903-007"`; the implementation mints `Q-VIP-8HEXDIGEST` from a
content hash of `question_key`. I did **not** change this, because the hash derivation is
load-bearing in three separate modules — matching the illustrative string would break real,
tested guarantees:

- `connectivity.py:2712` — "its `id` is DERIVED by `make_question_id()` from the question key (a
  caller cannot supply one, which is what keeps the repeat-question-rate=0 id-derivation
  guarantee intact)".
- `source_authority.py:599` — "two asks of the same key mint the same Q-ID"; its dedup comment
  records a **real caught incident**: running `audit_directory(question_store=...)` twice over the
  reference corpus took the queue from 12 questions to 24.
- `reference_pattern_audit.py:353` — the id is "derived from the question text, which is derived
  from the finding's own" content, which is what makes a detector re-run idempotent.

A date-plus-sequence id is allocation-ordered, not content-derived, so the same question asked
twice would mint two different ids and every one of those idempotency properties would fail. I
also did not add the spec's pattern as an accepted schema alternative: nothing mints that form, so
it would be dead schema surface. This is a case where the implementation is strictly better than
the spec's illustrative example, and the right action is to report it rather than regress to it.

The `owner` casing point (`"dv-owner"` vs `"DV-owner"`) is immaterial and was left alone — the
literal values are pinned in three places (routing table, schema `allOf`, tests) and changing the
casing would churn all three for no semantic gain.

## Tests

Added 10 tests to `dv_harness_tests/test_question_queue.py` covering: the spec's flat-string shape
accepted and persisted in canonical form (including a real store round-trip); the object form with
`rationale` still working; a mixed string/object list; the helper's standalone contract; a
parametrized set of 5 malformed inputs each asserting `QuestionValidationError` (never
`TypeError`); and that a malformed options list persists **nothing** (`store.list_questions() == []`).

**Test summary:** `dv_harness_tests/test_question_queue.py` + `test_cli_question_queue.py` →
**58 passed** (48 baseline + 10 new), plus the broader
`-k "question or connectivity or run_profile or source_authority or coverage or cli or bind or
blackboard"` suite across every file touched.

## Files changed

- `dv_harness/question_queue.py` — added `normalize_options()` + `_OPTION_KEYS`; called it in
  `add_question()`; replaced the inline options comprehension.
- `dv_harness/schemas/question.schema.json` — `options.description` records the input/storage
  asymmetry and why.
- `dv_harness/connectivity.py`, `dv_harness/uvm_generator/run_profile_to_justfile.py`,
  `dv_harness/cli.py` — three hand-rolled normalization copies replaced by the shared definition.
- `dv_harness_tests/test_question_queue.py` — 10 new tests.
