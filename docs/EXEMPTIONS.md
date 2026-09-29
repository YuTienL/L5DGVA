# exemptions.yaml -- structured, expiring records of deliberate check exemptions

## The problem this solves

"This check is off because of an IP restriction" is real engineering
knowledge. If it only lives in a code comment or gets passed down by word of
mouth, an agent re-reading the code later has no way to distinguish a
deliberate, still-valid exemption from stale dead code -- so it either
re-litigates the same question every session, or "helpfully" re-enables /
deletes the check and silently regresses whatever the exemption was
protecting against.

A structured `exemptions.yaml` fixes the knowledge-loss half of that
problem: every exemption is a record with an id, exactly what is being
exempted, the actual reason, a citable basis, and an accountable owner.

The second half of the problem -- a temporary workaround quietly becoming a
permanent, never-revisited fact -- is what makes `valid_until` the key
field. It is **required** on every entry; the schema has no "no expiry"
escape hatch. An exemption whose `valid_until` has passed is a fact the
harness surfaces for human re-review, not something that silently stays in
force forever.

## Where it lives

| What | Path |
|---|---|
| Entries file (per project) | `.dv-harness/exemptions/exemptions.yaml` |
| JSON Schema | `dv_harness/schemas/exemptions.schema.json` |
| Implementation | `dv_harness/exemptions.py` |
| Review-queue output (see below) | `.dv-harness/exemptions/review_queue.json` |
| Tests | `dv_harness_tests/test_exemptions.py` |

## Entry shape

Every entry requires all six fields:

| Field | Meaning |
|---|---|
| `id` | Stable id for this exemption record (`EXEMPT-0001`, auto-generated if omitted). |
| `check_id` | The exact thing being exempted -- a static-check rule id, a coverage bin/covergroup name, an assertion/property name, or a gate id. Concrete, not a category. |
| `reason` | Free text: the actual engineering *why*. |
| `basis_document` | A citation an agent or reviewer can actually go open -- a file path (optionally with a line range), a doc reference, or a ticket id. Never empty. |
| `owner` | Accountable person/team, not a role placeholder. |
| `valid_until` | ISO date (`YYYY-MM-DD`). **Required.** After this date the entry is expired. |

Optional fields: `created_at` (stamped automatically on `add`), `status`
(`active`/`retired` -- a `retired` entry is kept for history and is never
reported as expired), `protocol` (scope the exemption to one IP), `notes`.

`additionalProperties: false` on both the document and each entry means an
unrecognized field is a hard validation failure, not a silently-ignored typo.

## A real worked example from this repo

`dv_harness/uvm_generator/templates/sim_scripts/Makefile` (lines 1501-1508,
1506-1508, and the guard at line 3614) documents that unreachability
coverage analysis (`UNR`) is compiled/elaborated **separately** from the
default build:

```
# Unreachability analysis. Reports coverage bins no stimulus can reach, so
# they can be excluded rather than chased. Needs a separate licence and
# does not support partition compile, hence its own elaboration.
```

and later, the run-time guard:

```
echo "UNR does not support partition compile."; \
```

That is a genuine, already-documented deliberate restriction: UNR is not
folded into the default `-partcomp` partitioned-compile build because (a) it
needs a separate VCS license and (b) it does not support partition compile
at all. As a structured exemption entry:

```yaml
schema_version: "1.0"
exemptions:
  - id: EXEMPT-0001
    check_id: coverage_unreachability_analysis_partcomp
    reason: >
      UNR (unreachability coverage analysis) requires a separate VCS
      license (-unr) and does not support -partcomp partition-compile
      mode, so it runs as its own non-partitioned elaboration rather than
      being folded into the default partitioned build.
    basis_document: "dv_harness/uvm_generator/templates/sim_scripts/Makefile:1501-1508,3614"
    owner: dv-infra-team
    valid_until: "2099-01-01"
    protocol: GENERIC
    status: active
```

Add it with the CLI:

```
dv-harness exemptions add \
  --check-id coverage_unreachability_analysis_partcomp \
  --reason "UNR needs a separate VCS license and does not support -partcomp; runs as its own non-partitioned elaboration." \
  --basis-document "dv_harness/uvm_generator/templates/sim_scripts/Makefile:1501-1508,3614" \
  --owner dv-infra-team \
  --valid-until 2099-01-01
```

## CLI

```
dv-harness exemptions list  [--path P] [--expired-only] [--as-of YYYY-MM-DD]
dv-harness exemptions add   --check-id ID --reason R --basis-document B --owner O --valid-until YYYY-MM-DD
                             [--id ID] [--protocol P] [--notes N] [--path P]
dv-harness exemptions check [--path P] [--as-of YYYY-MM-DD]
dv-harness exemptions expire-report [--path P] [--out P] [--as-of YYYY-MM-DD]
dv-harness exemptions escalate      [--path P] [--as-of YYYY-MM-DD]
```

- `add` schema-validates the whole document (not just the new entry) before
  writing -- a missing/malformed field, `valid_until` included, refuses the
  write instead of persisting a bad record.
- `check` prints a JSON summary (`active`/`expired` entry lists +
  `active_count`/`expired_count`/`retired_count`) and **exits 1 if anything
  is expired**, 0 otherwise -- the same CI-friendly nonzero-on-failure
  convention the generated environment's own `dv-check`/`run_all.sh`
  already uses (`dv_harness/uvm_generator/templates/sim_scripts/`).
- `expire-report` does the same expiry evaluation as `check`, additionally
  writes the review-queue file (see below), and also exits 1 if anything
  expired. It REPORTS only.
- `escalate` (2026-09-04) goes one step further: it files each expired entry
  as a real Tier-3 blocking question in the real `QuestionQueueStore`, with
  a Q-ID and an owner, so an expiry reaches a human through the same queue
  as anything else the harness cannot assume its way past -- rather than
  waiting in a JSON file for someone to run `expire-report` by hand. It is
  idempotent (the question_key is derived from the exemption id, so a rerun
  files nothing new) but still **exits 1 while any entry is expired**, not
  just when it filed something: the exemption is still lapsed and still
  unanswered, so a CI step must not start passing on the second run.

## The expiry check function

`dv_harness.exemptions.check_expiry(path, as_of=None)` is a real, callable
function: given the exemptions file and an as-of date (defaults to today),
it returns which entries are expired vs. still active as of that date.
`is_expired()`/`find_expired()`/`find_active()` are the primitives it is
built from -- an entry is expired once `as_of` is strictly after its
`valid_until` day (the `valid_until` day itself is still the last valid
day), and a `retired` entry is never reported expired regardless of date.

## The review queue -- and what it deliberately is *not*

`build_review_queue(path, as_of=None)` returns one record per currently
expired entry:

```json
{
  "exemption_id": "EXEMPT-0002",
  "check_id": "lapsed_check",
  "reason": "...",
  "owner": "alice",
  "basis_document": "TICKET-4242",
  "valid_until": "2026-01-01",
  "expired_since": "2026-01-01",
  "days_expired": 245,
  "as_of": "2026-09-03"
}
```

`write_review_queue(queue, out_path)` persists that list as JSON to
`.dv-harness/exemptions/review_queue.json` (wrapped with a `generated_at`
timestamp), **always writing the file even when the queue is empty** -- an
empty file is itself a meaningful, current fact ("nothing is expired as of
the last check"), not an absence a downstream reader has to special-case.

## Who reads this store (2026-09-04)

This section used to say the review queue had no consumer -- that
`grep -n "review_queue\|exemption" dv_harness/question_queue.py` returned
no matches, and that wiring one up was left as future work. That was true
when written and is no longer. Until 2026-09-04 the only readers were the
`exemptions list/check/expire-report` CLI handlers, i.e. a human typing a
command, so neither of this store's two guarantees ("an agent never
re-litigates an exemption", "a temporary workaround never becomes
permanent") actually held on any automatic path.

`dv_harness/question_queue.py` is now the real automated consumer, on both
halves:

| when | what reads the store | effect |
|---|---|---|
| every `add_question()` whose `context` carries a `check_id` | `QuestionQueueStore.find_exemption()` -> `exemptions.find_active_exemption()` | an **active** exemption self-resolves the question at Tier 1, answering with its own reason/basis_document/owner. Nobody is asked. |
| `dv-harness exemptions escalate` | `QuestionQueueStore.escalate_expired_exemptions()` -> `build_review_queue()` | each **expired** exemption becomes a real Tier-3 blocking question with a Q-ID, idempotently (question_key derived from the exemption id). |

Two boundaries are deliberate:

- **An expired exemption suppresses nothing.** `find_active_exemption()`
  filters by expiry, so the day an exemption lapses the questions it was
  answering come back on their own. That is what `valid_until` is for.
- **An exemption does not override a Tier-3 hard trigger.** It is matched on
  `check_id` alone, which establishes that a question is *about* the check,
  not that this exemption *answers* it -- "the check is off due to an IP
  restriction" does not answer "is this PASS real". Such a question still
  escalates, but it arrives carrying the exemption's citation
  (`tier_reason` gains `;covered_by_active_exemption:<id>`, and the
  question record carries an `exemption` block), so the human is not
  re-deriving what an owner already decided and cited.

The exemption-backed answer is **not** persisted into the decisions store.
A decision there is permanent until revoked; this exemption expires. Minting
one from the other would outlive the exemption and keep suppressing the
question past its owner's own re-review date -- exactly the permanent,
never-revisited fact `valid_until` exists to prevent. `exemptions.yaml`
stays the single source for that answer.

`review_queue.json`'s shape is unchanged and still written, so any further
consumer still integrates by reading one file at a stable path.

Proven end-to-end (real store, real exemptions.yaml, real CLI subprocess,
never a mock) by `dv_harness_tests/test_exemptions_read_path.py`.

**This module still does not build a review-queue UI or ticketing system.**

## Relationship to `dv_harness/waiver_store.py`

`waiver_store.py` already exists in this repo and solves a related but
different problem: a human-approved sign-off on one specific gate/coverage
item *instance*, with attached evidence, consumed directly by the six gate
scripts under `tools/verification_flow/`. It has no expiry.

`exemptions.py` is about a different question: "is this check itself
deliberately off/relaxed for this project, and why" -- an expiry-driven,
knowledge-preservation concern, not a per-instance evidence sign-off. The
two modules are deliberately not merged; a project may use either or both.
