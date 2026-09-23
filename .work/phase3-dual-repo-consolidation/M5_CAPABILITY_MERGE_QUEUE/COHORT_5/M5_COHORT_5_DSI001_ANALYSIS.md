# CAP-M5-DSI-001 — design_source_inventory.py — Analysis

## The exact accepted contract (from `M4_M5_PREREQUISITE_MATRIX.csv`, not inferred from the ID/name)

The original M4-wave finding: "contract question identified: rank
value's source expression differs; `authority_order_used` key presence
differs" — `CANONICAL_STATE = PARTIAL (contract question identified)`,
`UNRESOLVED`.

## What "DSI" is (never expanded from the acronym without evidence)

`design_source_inventory.py`'s own module docstring (read in full this
Cohort): "a SOURCE REGISTRY for the design sources a project actually
has on disk: `{source_id, type, version, hash, authority, status,
last_checked}`, plus a DISCOVERY-order table." `DSI` is not expanded
anywhere in the repository — treated here strictly as the capability ID,
never guessed as an acronym.

## Real direction of the diff (the reverse of CAP-M5-COV-001)

Full read of the real diff (`diff --strip-trailing-cr
dv_harness/design_source_inventory.py <Parent's copy>`) shows canonical
is the LARGER, MORE ADVANCED file (491 lines vs. Parent's 441) —
opposite direction from COV-001. Canonical already has a real,
evidenced, tested feature Parent's copy lacks entirely: **per-fact-type
contextual authority** (`dv_harness/contextual_source_precedence.py`, a
real, separate, additive override module — confirmed present in
canonical, confirmed absent from Parent). Canonical's
`_resolve_authority()` accepts an optional `fact_type` parameter; when
given, it routes the rank through
`contextual_source_precedence.contextual_rank()` instead of the base
`source_authority.authority_rank()` directly, and reports which order
actually decided it via the `authority_order_used` key
(`"PER_FACT_TYPE_OVERRIDE"` or `"BASE_AUTHORITY_ORDER"`). Passing no
`fact_type` (every pre-existing caller) is byte-identical to the
pre-feature behavior except for gaining the new
`authority_order_used: None` key.

This is EXACTLY the "rank value's source expression + `authority_order_
used` key-presence differ" contract question the original M4 finding
named — now resolved with full evidence: canonical's version is not a
competing, equally-valid alternative to Parent's; it is a strict
superset. Parent's `design_source_inventory.py` is simply an OLDER
snapshot, predating this feature.

## SOURCE_INPUTS / CANONICAL_CURRENT_BEHAVIOR / SOURCE_VERIFIED_BEHAVIOR

| Field | Value |
|---|---|
| `SOURCE_INPUTS` | Parent HEAD `3e9dd736`; v50 confirmed content-identical to canonical (diff was pure CRLF/LF) |
| `CANONICAL_CURRENT_BEHAVIOR` | Real, tested, richer model: `SourceEntry.fact_type` (optional), `_resolve_authority(authority_hint, fact_type=None)`, `authority_order_used` key on every result, real `contextual_source_precedence.py` override layer |
| `SOURCE_VERIFIED_BEHAVIOR` (Parent) | Older, simpler model: `_resolve_authority(authority_hint)` only, no `fact_type`, no `authority_order_used` key, no contextual-precedence dependency |

## CALLERS / SCHEMAS / TESTS / DEPENDENCIES / PUBLIC_CONTRACTS / OWNER_BOUNDARY

- `CALLERS`: not re-swept for this file — no code change is made, so no new caller-compatibility risk is introduced. Canonical's existing callers of `design_source_inventory.py` are unaffected by this analysis (confirmed by the fact that no file under `dv_harness/` was touched for DSI-001).
- `SCHEMAS`: not applicable — no schema change.
- `TESTS`: canonical's existing `dv_harness_tests/test_design_source_inventory.py` +
  `dv_harness_tests/test_contextual_source_precedence.py` re-run this
  Cohort to confirm current health: **58/58 pass**, unchanged, unmodified.
- `DEPENDENCIES`: `contextual_source_precedence.py` (pre-existing, unmodified, confirmed real and tested).
- `PUBLIC_CONTRACTS`: unchanged — no production code touched.
- `OWNER_BOUNDARY`: N/A — no migration performed.

## Disposition: SUPERSEDED, not CLOSED

Because nothing is migrated FROM Parent (there is nothing left to
migrate — canonical already has the richer, evidenced capability),
`CLOSED` would misstate this as "work done this Cohort" when the real
finding is "canonical was already ahead; the contract question resolves
in canonical's favor once fully evidenced." `SUPERSEDED` is used instead,
with the full evidence trail above as the citation, per instruction item
9's `SUPERSEDED` classification option and the Verified Behavior Union
table below.

## Verified Behavior Union (instruction item 9)

```
CANONICAL_CURRENT_BEHAVIOR = per-fact-type contextual authority (real, tested)
PARENT_VERIFIED_BEHAVIOR   = base-order-only authority resolution (older, real, tested in Parent's own right, but superseded)
V50_VERIFIED_BEHAVIOR      = content-identical to canonical (confirmed via diff --strip-trailing-cr)
WORKTREE_VERIFIED_BEHAVIOR = not applicable -- B7A/B7B/B8 were never registered as contributing sources for this file (M4_M5_PREREQUISITE_MATRIX.csv's own SOURCE_INPUTS column lists only PARENT_HEAD, V50_HEAD)
VERIFIED_BEHAVIOR_UNION    = canonical's current behavior IS the union -- it is a strict superset of Parent's
SEMANTIC_CONFLICTS         = none once evidence is complete -- the apparent conflict was an artifact of incomplete Cohort-4-era-M4 investigation, not a real disagreement about intended behavior
CANONICAL_TARGET_BEHAVIOR  = unchanged (already correct)
PRESERVED_BEHAVIOR         = 100% -- no canonical behavior touched
SUPERSEDED_BEHAVIOR        = Parent's simpler model (explicitly, with evidence, not silently)
SOURCE_DEFECTS_NOT_PROPAGATED = N/A -- no defect found in Parent, just an earlier feature snapshot
DEFERRED_FUTURE_BEHAVIOR   = none -- fully resolved this Cohort
```
