# CAP-M5-ARCH-002 -- Final Report

```
M5_STATUS               = IN_PROGRESS
M5_COHORT_2_STATUS      = CLOSED (all 3 named capabilities resolved: CAP-M5-ARCH-003,
                           CAP-M5-ARCH-001, CAP-M5-ARCH-002)

CAP_M5_ARCH_001 = CLOSED
CAP_M5_ARCH_002 = CLOSED
CAP_M5_ARCH_003 = CLOSED

CAP_M5_ARCH_002_START_HEAD = e21e155
CAP_M5_ARCH_002_END_HEAD   = <recorded in the closing commit -- see git log>

SYMBOLS_ANALYZED              = 15 (0 UNKNOWN)
CALLERS_ANALYZED              = 9 (0 UNKNOWN)
UNKNOWN_CALLERS                = 0

THREE_WAY_BEHAVIORS_ANALYZED  = 5 (BHV-001..BHV-005; see three-way matrix)
PARENT_BEHAVIORS_MERGED       = 0 (top-TB preservation deferred -- see CAP-M5-TOPTB-001)
B8_BEHAVIORS_MERGED           = 1 (the virtual-sequencer evidence-annotation wire)
SOURCE_DEFECTS_NOT_PROPAGATED = 0 this capability (B8's contribution verified clean via
                                 its own tests, run in its own worktree, this time)

PUBLIC_SIGNATURE_BREAKS       = 0
COMPATIBILITY_ADAPTERS_ADDED  = 0

SOURCE_CAPABILITY_LOSS               = 0
REGRESSION_CAUSED_BY_CAP_M5_ARCH_002 = 0
UNKNOWN_REGRESSION_FAILURES          = 0

N_WAY_TARGETS_COMPLETED_TOTAL = 4 (CAP-M5-ENV-001, CAP-M5-ARCH-003, CAP-M5-ARCH-001,
                                 CAP-M5-ARCH-002)
N_WAY_TARGETS_REMAINING       = 4 (CAP-M5-VIP-001, CAP-M5-COV-001, CAP-M5-DSI-001, plus
                                 the 2 named ATL contract-migration inputs counted as one
                                 Cohort-4 unit -- unchanged count convention from prior
                                 reports; CAP-M5-TOPTB-001, newly discovered this wave, is
                                 an ADDITION to the total inventory, not previously counted
                                 in "5 remaining" -- see NEXT_RECOMMENDED_GATE)

AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 6 (unchanged -- CAP-M5-ARCH-002 was P1, not P0;
                                 CAP-M5-TOPTB-001 registered as P2, not P0)
M6_BLOCKERS                            = 3 (unchanged)

SOURCE_A_CHANGED = NO   SOURCE_B_CHANGED = NO   B7A_CHANGED = NO   B7B_CHANGED = NO   B8_CHANGED = NO
REFERENCE_USB_ENV_CONSUMED = NO

COHORT_3_STARTED = NO
M6_STARTED        = NO

NEXT_RECOMMENDED_GATE = Cohort 3 (CAP-M5-VIP-001, vip_capability_extraction.py --
  the KNOWN RISK classify_by_inheritance() 4-to-5-tuple signature-break capability),
  OR closing the newly-registered CAP-M5-TOPTB-001 first if the top-TB preservation
  feature is judged higher priority -- both are legitimate next steps; this report
  does not choose between them, per instruction ("Do not start Cohort 3
  automatically").
```

## Newly discovered migration input this wave (Section 13 -- Parent capability validation)

Parent's `compose_soc_environment()` delta is real, dated, human-approved
capability (V11 SS247, 2026-09-20) -- **not** dormant code migrated
merely because it exists (Section 13's own prohibition). It was
evaluated on its real merits: real caller/consumer (both production
`compose_soc_environment()` call sites), real behavioral purpose
(preserve, don't regenerate, a qualified existing top TB), and a real,
explicit scope boundary in its own docstring (PRESERVE only, EXTEND
explicitly deferred by Parent's own designers too). It was **not**
merged this wave for one concrete, disclosed reason: its dependency
module (`reference_uvm_dut_top_integration_manifest.py`) is confirmed
absent from canonical, and merging the wire without it is impossible --
this is a missing-foundation situation, not a quality judgment against
Parent's work. Registered as `CAP-M5-TOPTB-001` for its own future
dedicated analysis.

## B8 defect lesson -- this time, no defect found (Section 12)

Unlike `CAP-M5-ARCH-003` (a confirmed runtime `TypeError` in B8's own
`env()` call) and `CAP-M5-ARCH-001` (a confirmed schema-violating
synthetic key), this wave's B8 contribution was verified clean: its own
3 tests were run in B8's own frozen worktree before any merge decision
and all 20 tests in that file passed. The discipline still applied --
verification happened, it simply confirmed correctness rather than
finding a defect. Both outcomes are real findings of the same process,
not evidence the process is unnecessary.

## Known limitations (disclosed)

- `CAP-M5-TOPTB-001` (Parent's top-TB preservation feature) remains
  unmerged -- a real, disclosed gap, not silently dropped.
