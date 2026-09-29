# CAP-M5-ARCH-001 -- Semantic Merge Plan

## Behavior union (Section 9)

```
CANONICAL_CURRENT_BEHAVIOR = create_environment() dispatches SUBSYSTEM_MODE
  (exact-match) with a hard-coded "SUBSYSTEM_MODE" return literal, then
  unconditionally falls through to a SYSTEM_LEVEL_MODE block with its own
  hard-coded "SYSTEM_LEVEL_MODE" return literal. No verification_architecture
  wiring.

PARENT_VERIFIED_BEHAVIOR = fixes the SUBSYSTEM_MODE hard-coded literal;
  widens the dispatch condition to accept "IP_MODE"; passes
  request["verification_level"] through as router evidence; guards
  requested_subsystems[0] against IndexError. The latter three all
  presuppose Parent's own verification_level.py (CAP-M5M6-VLEVEL-001,
  M6-owned, absent from canonical) and are provably dead code against
  canonical's real router today.

V50_VERIFIED_BEHAVIOR = byte-identical to canonical (0-line diff) -- no
  behavior to contribute.

B8_VERIFIED_BEHAVIOR = adds VerificationArchitectureConflictError +
  _run_verification_architecture() + wires it into both return dicts,
  exactly mirroring the existing _run_structural_lint/_run_vip_api_
  validation opt-in/NOT_AVAILABLE/strict_* pattern. verification_
  architecture.py itself already byte-identical between canonical and
  B8. B8's own call adds a synthetic "status": "ASSEMBLED" key to the
  written/returned document that is NOT part of verification_architecture
  .schema.json's declared properties -- confirmed this wave, empirically,
  to raise a real jsonschema additionalProperties violation.

OTHER_APPROVED_BEHAVIOR = none this capability (no B7A/B7B contribution
  identified for create_environment.py).

VERIFIED_BEHAVIOR_UNION =
  1. Parent's SUBSYSTEM_MODE hard-coded-literal fix (decision["environment_mode"])
  2. The SAME fix applied to the SYSTEM_LEVEL_MODE branch (found by this
     wave's own analysis, not present in Parent's diff, but the identical
     defect class in the same function -- disclosed explicitly, not silent)
  3. B8's real verification_architecture wire, minus the synthetic "status"
     key that would have broken schema compliance

SEMANTIC_CONFLICTS =
  - Parent's IP_MODE dispatch widening / verification_level evidence
    pass-through / requested_subsystems empty-guard vs. canonical's total
    absence of any IP_MODE/verification_level.py foundation -- resolved by
    NOT merging (M6_VERIFICATION_LEVEL_SEMANTICS, deferred)
  - B8's synthetic "status" key vs. verification_architecture.schema.json's
    additionalProperties:false -- resolved by NOT adding that key (matches
    the schema's own declared contract and the dashboard's own established
    convention for the identical document type)

CANONICAL_TARGET_BEHAVIOR = both mode-string literals replaced with the
  real decision value; verification_architecture wired into both dispatch
  branches, producing a schema-compliant document with no synthetic keys.

PRESERVED_BEHAVIOR = every existing SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE
  return-dict key, unchanged in value for every real input canonical can
  construct today (proven by 291 pre-existing + this-wave tests passing
  unchanged).

SUPERSEDED_BEHAVIOR = none.

DEFECTS_NOT_TO_PROPAGATE =
  - B8's synthetic "status" key (schema violation, empirically confirmed)
  - Parent's dead-code IP_MODE dispatch/evidence/guard additions (not a
    "defect" in Parent itself, but not mergeable without its own M6-owned
    foundation -- propagating it into canonical would be inert-but-
    misleading scaffolding, and Section 15 forbids introducing M6
    architecture prematurely)

DEFERRED_FUTURE_BEHAVIOR = IP_MODE dispatch support itself -- belongs to
  the M6 wave that migrates/builds verification_level.py
  (CAP-M5M6-VLEVEL-001).
```

## M6 Verification Level boundary (Section 7)

```
M5_COMPATIBILITY_BEHAVIOR:
  - Both mode-string literal fixes (return the REAL resolved mode, never a
    literal) -- this does not name "IP_MODE" anywhere, does not add a
    third dispatch branch, and does not create a competing
    VerificationLevel authority. It simply stops a return value from being
    wrong the moment a future dispatch condition is widened -- removing an
    obstacle to IP_MODE support, not implementing it.
  - The verification_architecture wire -- orthogonal to mode/level
    entirely; runs identically regardless of which mode was dispatched.

M6_VERIFICATION_LEVEL_SEMANTICS (deferred):
  - IP_MODE as a literal dispatch value
  - request["verification_level"] evidence pass-through to the router
  - the requested_subsystems[0] empty-guard (only reachable once IP_MODE
    dispatch exists)
```

## DE/DV generic-workflow compatibility (Section 8)

`create_environment()` branches only on `environment_mode`
(SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE), never on any DE/DV/role concept --
unchanged by this wave. `verification_architecture_inputs` is evidence
about VIP bind/checker/scoreboard/assertion placement, not about who
(DE/DV/human role) supplied it -- no role-branching introduced.
`ONE_GENERIC_DE_DV_WORKFLOW = YES`, preserved.

## OpenSpec field-resolution compatibility (Section 12)

`create_environment()` does not read or write any
`DeclaredValue`/`AutoDiscoveredValue`/`DerivedValue`/`EffectiveValue`/
`Confidence`/`ValidationState`/`ConfirmationState`/`EvidenceRefs`-shaped
field anywhere in its request/response contract, before or after this
wave's change -- no dependency to document, no second model invented.

## Location independence (Section 13)

No new path/host/username dependency introduced. `_run_verification_
architecture()` writes only to the caller-supplied `out_dir`, exactly
like the two pre-existing `_run_*` helpers. `LOCATION_INDEPENDENT = YES`.
