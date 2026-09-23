# USB Excel KC-to-Regeneration Contract (V1 -> V2)

Status: registration only.

## KC_STORED / KC_RETRIEVED / KC_CONSUMED — three distinct, separately-evidenced states

```
KC_STORED     -- the KC exists in the Knowledge Brain. Nothing more.
KC_RETRIEVED  -- a real MemoryRetriever.search() call, with a recorded
                 query/context, returned this KC as applicable to the
                 current task. Retrieved-but-ignored is NOT learning
                 success.
KC_CONSUMED   -- real evidence that generation/planning ACTUALLY USED
                 the retrieved KC -- the generated V2 item differs from
                 what V1 (or a KC-free baseline) would have produced,
                 in the specific way the KC predicts.
```

`KC_STORED = YES` alone cannot satisfy any learning claim. This is the
literal operationalization of `KC_STORED != CLOSED_LOOP_LEARNING` and
`KC_PROMOTED != KC_CONSUMED` from the qualification principle.

## V1 -> V2 regeneration requirement

M11 must run a SECOND, sufficiently independent generation session after
KC promotion — never a claim based on hidden session memory (e.g. the
same conversation simply "remembering" what it did in V1 and repeating
it with cosmetic changes). "Sufficiently independent" means a fresh
generation invocation that can only have access to the promoted KC
through the real retrieval mechanism (`MemoryRetriever.search()`), not
through conversational continuity with the V1 generation session.

## Required recorded identifiers

```
V1_GENERATION_ID
V1_QUALIFICATION_ID
KC_IDS_PROMOTED           -- every KC promoted from V1's own gap/RCA findings
V2_GENERATION_ID
KC_IDS_RETRIEVED          -- every KC the V2 session's own retrieval calls returned
KC_IDS_CONSUMED           -- the subset of KC_IDS_RETRIEVED with real consumption evidence
```

`KC_IDS_CONSUMED ⊆ KC_IDS_RETRIEVED ⊆ KC_IDS_PROMOTED` is expected but
not assumed — each subset relationship must be independently verified
from real evidence, not asserted.

## No undocumented manual edits

Any manual edit to V2's own output during the qualification run (to
"help" V2 look better than an honest KC-driven regeneration would have
produced) must be disclosed explicitly, with a reason, or not made at
all. An undisclosed manual edit invalidates the V1/V2 comparison for
every field it touched — this is a hard integrity requirement, not a
style preference.

## Consumption evidence (what actually counts)

Acceptable consumption evidence includes: a generation-time log entry
citing the specific `KC_ID` at the specific decision point it
influenced; a diff between what a KC-free baseline generation would
produce (or did produce, in V1, for the same gap) and what V2 actually
produced, at exactly the location the KC's own `proposed_knowledge`
predicts; or an explicit generation-planning trace showing the KC was
read and acted on. A KC merely appearing in a retrieval result list is
NOT consumption evidence on its own.
