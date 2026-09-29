# M5 Cohort 3 — CAP-M5-VIP-001 — Final Report

```
M5_STATUS = IN_PROGRESS (Cohort 3 of 5 closed; Cohorts 4-5 remain)
M5_COHORT_3_STATUS = CLOSED
CAP_M5_VIP_001_STATUS = RESOLVED

START_HEAD = a7b1b998 (canonical/m4-dependency-closure)
END_HEAD = f773f476d8241ebf7b83ba39e90f208ab3434abc (commit f773f47, this Cohort's own commit)

PUBLIC_APIS_ANALYZED = 18 symbols (see M5_COHORT_3_VIP_SYMBOL_API_INVENTORY.csv)
RUNTIME_CALLERS_ANALYZED = 11 (4 real production consumers + 7 test files;
                                see M5_COHORT_3_VIP_CALLER_SWEEP.csv)
UNKNOWN_PUBLIC_APIS = 0
UNKNOWN_RUNTIME_CALLERS = 0

SIGNATURE_BREAKS_FOUND = 1 (classify_by_inheritance() 4-to-5-tuple return, the KNOWN RISK named at Cohort-3 start)
SIGNATURE_BREAKS_RESOLVED = 1 (adopted directly -- 0 real external callers found by the caller sweep, so no adapter was required; see M5_COHORT_3_VIP_COMPATIBILITY_PLAN.md)
COMPATIBILITY_ADAPTERS_ADDED = 0 (none needed -- justified in the Compatibility Plan, not merely skipped)

VIP_PROVIDERS_PRESERVED = 1 (Synopsys SVT -- the only vendor with real evidence anywhere in the 6 sources; provider-identity scope honestly disclosed as evidence-bounded, not extended without evidence -- see M5_COHORT_3_VIP_PROVIDER_MODEL.md)

SOURCE_BEHAVIORS_MERGED = 3 (VIP-04 "transfer" naming suffix; VIP-05/VIP-18 _VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY fallback table + classify_by_inheritance() via_vendor_marker branch; VIPCapabilityRecord.inheritance_via_vendor_marker field + evidence-entry wiring)
SOURCE_DEFECTS_NOT_PROPAGATED = 0 (no defect found in B7B's diff this Cohort -- unlike Cohort 2's ARCH-001/ARCH-003, B7B's own 17/17 tests, including its own 4 new tests, passed clean in its own worktree before any canonical edit)
SOURCE_CAPABILITY_LOSS = 0 (every pre-existing symbol/field/signature preserved; all additions are additive)

REGRESSION_CAUSED_BY_CAP_M5_VIP_001 = 0
UNKNOWN_REGRESSION_FAILURES = 0
  -- test_vip_capability_extraction.py: 17/17 pass (13 pre-existing + 4 new, ported verbatim from B7B)
  -- real downstream callers (test_vip_callback_hook_extraction.py, test_vip_config_field_usage_coverage.py, test_scenario_pattern_command_txt_correspondence.py): 53/53 pass
  -- Cohort 1/2/TOPTB-001 preservation sweep (env_manifest, amba_fabric_generator, create_environment, soc_environment_composer, reference_uvm_dut_top_integration_manifest): 108/108 pass
  -- Constitution/Anti-Drift: PASS
  -- Total this Cohort's own regression evidence: 178/178 pass, 0 failures

N_WAY_TARGETS_COMPLETED_TOTAL = 5 of 8 (CAP-M5-ENV-001, CAP-M5-ARCH-001, CAP-M5-ARCH-002, CAP-M5-ARCH-003, CAP-M5-TOPTB-001, CAP-M5-VIP-001 -- 6 capabilities across Cohorts 1-3, all RESOLVED)
N_WAY_TARGETS_REMAINING = 2 (CAP-M5-COV-001, CAP-M5-DSI-001 -- Cohort 4, both HUMAN_DECISION-flavored contract questions, not pure engineering merges)

AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 5 (down from 6 -- CAP-M5-VIP-001
  downgraded P0->P2 this wave; structurally re-verified via
  csv.DictReader against both MASTER_CAPABILITY_STATUS_MATRIX.csv and
  MASTER_WAVE_OWNERSHIP_MATRIX.csv, CAP-POOL-005's documented
  cross-reference-not-independent-blocker status re-applied as in every
  prior wave)

M6_BLOCKERS = 3 (CAP-M6-DISPATCH-001, CAP-M6-CLARSVC-001, CAP-M5M6-VLEVEL-001 -- unchanged by this Cohort; M5's own scope was never load-bearing for these, per MASTER_END_TO_END_DV_STATUS.md's own cross-level reading)

NEXT_RECOMMENDED_GATE = Cohort 4 (CAP-ATL-004/CAP-ATL-007 OpenSpec contract-migration inputs + CAP-M5-COV-001 + CAP-M5-DSI-001) -- NOT STARTED, awaiting explicit approval per standing instruction
```

## What changed in this Cohort

`dv_harness/vip_capability_extraction.py`: added the "transfer" naming
suffix (VIP-04), the `_VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY` vendor
base-class fallback table (VIP-05/VIP-18, 8 Synopsys SVT entries),
changed `classify_by_inheritance()`'s return arity from 4 to 5 (adds
`via_vendor_marker: bool`), added `VIPCapabilityRecord.
inheritance_via_vendor_marker: bool = False`, and wired the new evidence
entry + field through both `extract_vip_capabilities()` construction
paths (the `NAME_AND_INHERITANCE_DISAGREE` ambiguous path and the normal
classification path). Every change is a single-source adoption from
B7B — Parent/v50/B7A/B8 are byte-identical to canonical for this file, so
this Cohort was not an N-way reconciliation across disagreeing sources
(disclosed honestly rather than manufacturing a merge narrative).

`dv_harness_tests/test_vip_capability_extraction.py`: ported B7B's own 4
new tests verbatim, at the same insertion point B7B itself used (after
`test_naming_suffix_table_is_disjoint`, before
`test_missing_index_file_raises_rather_than_reporting_a_clean_result`).

## Provenance

- **B7B** (`c7c7fa09e9ee8336ba102b4495f4b8808408fe0b`, `D:/wt/b7b`,
  `impl/b7b`): sole source of all new capability content — VIP-04/VIP-05/
  VIP-18 naming/inheritance evidence and their 4 accompanying tests.
  Honest provenance note: this capability lives in B7B's own working
  tree as an uncommitted modification against its own HEAD, not baked
  into that commit itself; the working-tree content was already present,
  unchanged, both before and after this Cohort's own edits (re-verified
  via `git status`/`git diff` at Cohort start and Cohort close) — see
  `M5_COHORT_3_VIP_TEST_EVIDENCE.md` for the full disclosure.
- **Parent, v50, B7A, B8**: confirmed byte-identical to canonical for
  this file (`diff -q`, all 4) — no contribution to this Cohort's merge.
- **This Cohort's own contribution**: the caller sweep proving 0 real
  external callers of the changed function (making the signature change
  safe to adopt directly), the honest provider-identity scope disclosure
  (Synopsys-only, because that is what the evidence supports), and the
  full regression/Constitution verification chain.

## Source integrity re-check (before and after)

Parent `3e9dd736...`, v50 `f3fd1732...`, B7A `7b2a65a4...`, B7B
`c7c7fa09...`, B8 `c9cdd06c...` — all 5 HEAD SHAs unchanged before and
after this Cohort's work. No `Edit`/`Write` tool call in this Cohort
targeted any path outside `D:/DV/Task/L5_DGVA`.

## Required artifacts (all 8 produced)

1. `M5_COHORT_3_VIP_SYMBOL_API_INVENTORY.csv`
2. `M5_COHORT_3_VIP_CALLER_SWEEP.csv`
3. `M5_COHORT_3_VIP_PROVIDER_MODEL.md`
4. `M5_COHORT_3_VIP_SOURCE_BEHAVIOR_MATRIX.csv`
5. `M5_COHORT_3_VIP_COMPATIBILITY_PLAN.md`
6. `M5_COHORT_3_VIP_SEMANTIC_MERGE_PLAN.md`
7. `M5_COHORT_3_VIP_TEST_EVIDENCE.md`
8. `M5_COHORT_3_FINAL_REPORT.md` (this file)

## STOP

Per standing instruction: do not start Cohort 4, M6, or M10.5. Awaiting
explicit review/approval of this Cohort before any further M5 work.
