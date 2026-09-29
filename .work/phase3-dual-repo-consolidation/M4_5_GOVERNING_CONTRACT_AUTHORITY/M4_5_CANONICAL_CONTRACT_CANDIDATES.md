# M4.5 — Canonical Contract Candidates

`NEW_VALID_GOVERNANCE_REQUIREMENT` candidates from
`M4_5_CONTRACT_CLAUSE_CLASSIFICATION.csv`: **20** (of 1,348 total
extracted clauses). Per instruction Section 5: "Only
`NEW_VALID_GOVERNANCE_REQUIREMENT` may become a Canonical contract
candidate... Do not promote merely because Parent contains the
requirement."

## Finding: 0 promoted this wave

While verifying the first candidate (`CL-0039`,
`NoMaterialBringupNoopFalsePass_PASS`, corpus section 31 "Material
bring-up completeness guard"), the `DUPLICATION` check surfaced a real
concern the mechanical filename-fuzzy-match used for the other 1,070
`INVARIANT_TOKEN` clauses cannot catch: a parallel LLM-based
cross-check of this same corpus region (an independently dispatched
extraction pass over the same line range) found that
`dv_harness/l5dgva_v5_ss86_understanding_plan_contradiction_taxonomy.py`
already flags the near-identical condition
`REFERENCE_BLOCK_BRINGUP_BUT_GENERATED_NOOP` (a real, tested,
already-migrated-to-canonical module, `CAP-M3-003`) — a case my
filename-keyword matcher missed because the match is in the module's
**content** (an enum value), not its **filename**.

This is exactly the false-new-rule risk Section 5 warns against, caught
before promotion rather than after. Since one of the two directly
spot-checked candidates already had a real, missed
`CANONICAL_EQUIVALENT` match, this reconciliation does not have
sufficient confidence to assert the other 19 are genuinely
duplication-free without the same depth of individual content-level
(not filename-level) verification — which is real, valuable future
work, not something to rush to close this wave.

```
CANONICAL_CONTRACTS_PROMOTED = 0
```

## Disposition: all 20 candidates

| CLAUSE_ID | REQUIREMENT_ID | Section | Disposition |
|---|---|---|---|
| CL-0039 | `NoMaterialBringupNoopFalsePass_PASS` | 31 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- likely `CANONICAL_EQUIVALENT` to `l5dgva_v5_ss86...py`'s `REFERENCE_BLOCK_BRINGUP_BUT_GENERATED_NOOP` (found by cross-check, not the primary fuzzy match) |
| CL-0116 | `AdditionalDirectoryJustification_PASS` | 68 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- filesystem-parity domain already has real canonical coverage (USB_UVM_Handoff "canonical structural template" rule); needs content-level, not filename-level, comparison |
| CL-0247 | `NoUSBDefaultOnUnknown_PASS` | 118 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps the Bind-Location Rules' "never assumed from a module name" discipline; needs individual comparison |
| CL-0346 | `DEProceduralUsability_PASS` | 173 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- no fuzzy match found; genuinely plausible candidate, not yet individually verified |
| CL-0490 | `AutomaticCheckingSynthesis_PASS` | 229 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps `l5dgva_ss211_kc_extraction_composite.py`'s vPlan/Test/Coverage synthesis theme by topic, not by filename |
| CL-0513 | `NoPrematureExternalization_PASS` | 236 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps canonical's "Do not require repeated user prompts"/autonomous-execution discipline by topic |
| CL-0691 | `NoAutomaticDocumentWins_PASS` | 317 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps the Source Authority Order's own conflict-resolution discipline (register file vs. doc) by topic |
| CL-0825 | `NoUnjustifiedBringupDecomposition_PASS` | 399 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps register-map/RTL-trace reconciliation modules by topic |
| CL-0830 | `SilentSimplification_Count` | 404 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps "No Silent Simplification" -- a named theme with several partial-match Parent modules (`generated_code_quality_gate.py` family) |
| CL-0914 | `DuplicateKCCreation_Count` | 467 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps `kc_dead_artifact_census.py` / `kc_contradiction_staleness_gate.py` by topic |
| CL-0916 | `AutomaticKCPersistence_PASS` | 467 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps `memory_router.route_and_store()` by topic |
| CL-0974 | `DirectUnauthorizedM3PlusPromotion_Count` | 519 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps `memory_router.promote_to_organizational()`'s gated-promotion discipline by topic |
| CL-1038 | Heuristic (chain-of-thought exposure) | 565 | `GENUINE_CANDIDATE, HIGHER_CONFIDENCE` -- no existing canonical or Parent mechanism addresses hidden-reasoning/chain-of-thought exposure specifically; the strongest candidate in this batch |
| CL-1120 | `Artifact::ContractConflictMatrix` | 618 | `NOT_A_CANDIDATE_YET` -- `l5dgva_contract_registry.py`'s own docstring already discloses this is deliberately unbuilt (the full 8-value cross-version taxonomy needs semantic judgment); real future work, tracked via that module's disposition (see `M4_5_CONTRACT_REGISTRY_DISPOSITION.md`), not a standalone new rule |
| CL-1190 | `PrematureSummaryStop_Count` | 652 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps autonomous-execution/no-routine-stop discipline by topic |
| CL-1195 | `ExplicitReadOnlyOverride_PASS` | 656 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps the git-guard / Human Override discipline by topic |
| CL-1235 | `UnboundedRelayRestart_Count` | 687 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- likely `CANONICAL_EQUIVALENT` to the Remote Linux Execution section's own bounded-reconnect rule; a probable duplicate the keyword matcher missed for the same content-vs-filename reason as CL-0039 |
| CL-1250 | `PrematureManualRelayRestartRequest_Count` | 699 | `NEEDS_DEEPER_DUPLICATION_CHECK` -- same relay-restart family as CL-1235, same likely duplication |
| CL-1292 | `SpecificationFilenameSpecialCase_Count` | 2 (ExecSpec doc) | `NEEDS_DEEPER_DUPLICATION_CHECK` -- overlaps the No Golden-Reference Content Mining / generic-engine-not-special-cased discipline by topic |
| CL-1293 | `SpecificationVersionBusinessLogicSpecialCase_Count` | 2 (ExecSpec doc) | `NEEDS_DEEPER_DUPLICATION_CHECK` -- same family as CL-1292 |

## Recommendation

A future wave (not this one) should run a **content-level** (not
filename-level) duplication check for these 20 candidates — likely by
having an agent read each candidate's full corpus context alongside the
specific Parent/canonical modules its topic keywords suggest, rather
than a mechanical filename match. `CL-1038` (chain-of-thought exposure)
is the one candidate this pass found no plausible existing counterpart
for at all, making it the best starting point for that future
individual-verification pass — but it is **not promoted here either**,
consistent with "do not promote merely because [no match was found]"
applying with the same rigor as "do not promote merely because Parent
contains it."
