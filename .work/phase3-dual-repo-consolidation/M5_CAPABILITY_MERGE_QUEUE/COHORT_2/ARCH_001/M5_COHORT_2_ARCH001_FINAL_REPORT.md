# CAP-M5-ARCH-001 -- Final Report

```
M5_STATUS               = IN_PROGRESS
M5_COHORT_2_STATUS      = PARTIAL (2 of 3 capabilities closed: CAP-M5-ARCH-003, CAP-M5-ARCH-001;
                           CAP-M5-ARCH-002 remains NOT_STARTED)
CAP_M5_ARCH_001          = CLOSED
CAP_M5_ARCH_002          = NOT_STARTED

CAP_M5_ARCH_001_START_HEAD = 357769a
CAP_M5_ARCH_001_END_HEAD   = <recorded in the closing commit -- see git log>

SYMBOLS_ANALYZED         = 13 (see M5_COHORT_2_ARCH001_SYMBOL_INVENTORY.csv; 0 left UNKNOWN)
CALLERS_ANALYZED         = 17 (see M5_COHORT_2_ARCH001_CALLER_SWEEP.csv)
UNKNOWN_CALLERS          = 0

SOURCE_BEHAVIORS_MERGED  = 2 (Parent's mode-string-literal fix, applied to both branches;
                           B8's verification_architecture wire, minus its schema-breaking
                           synthetic key)

MODE_STRING_DEFECT_STATUS = RESOLVED (both the named SUBSYSTEM_MODE instance and the
                           mirror-image SYSTEM_LEVEL_MODE instance found by this wave's own
                           analysis)
MODE_STRING_DEFECT_OWNER  = M5

PUBLIC_SIGNATURE_BREAKS       = 0
COMPATIBILITY_ADAPTERS_ADDED  = 0

SOURCE_CAPABILITY_LOSS               = 0
REGRESSION_CAUSED_BY_CAP_M5_ARCH_001 = 0
UNKNOWN_REGRESSION_FAILURES          = 0

N_WAY_TARGETS_COMPLETED_TOTAL = 3 (CAP-M5-ENV-001, CAP-M5-ARCH-003, CAP-M5-ARCH-001)
N_WAY_TARGETS_REMAINING       = 5 (CAP-M5-ARCH-002, CAP-M5-VIP-001, CAP-M5-COV-001,
                                 CAP-M5-DSI-001, plus the 2 named ATL contract-migration
                                 inputs in Cohort 4 -- counted as the same 5 previously
                                 reported since ARCH-002 was already counted)

AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 6 (unchanged -- CAP-M5-ARCH-001 was P1, not P0)
M6_BLOCKERS                            = 3 (unchanged -- see UNBLOCKS_M6 below)

SOURCE_A_CHANGED = NO   SOURCE_B_CHANGED = NO   B7A_CHANGED = NO   B7B_CHANGED = NO   B8_CHANGED = NO
REFERENCE_USB_ENV_CONSUMED = NO

CAP_M5_ARCH_002_STARTED = NO
COHORT_3_STARTED        = NO
M6_STARTED               = NO

NEXT_RECOMMENDED_GATE = CAP-M5-ARCH-002 (soc_environment_composer.py -- the only
  genuinely 3-way merge target in Cohort 2, Parent 150 lines / v50 11 lines / B8 103 lines),
  with the same read-fully-before-touching discipline demonstrated on ARCH-003 and ARCH-001.
```

## UNBLOCKS_M6 / REDUCES_M6_RISK / NO_EFFECT_ON_M6 (Section 16)

**NO_EFFECT_ON_M6.** Checked directly against `MASTER_CAPABILITY_STATUS_
STATUS_MATRIX.csv`: no `CAP-M6-*`/`CAP-M5M6-*` row names `CAP-M5-ARCH-001`
in its `SECONDARY_DEPENDENCY` field. The M6-relevant part of this
capability (the dead-code IP_MODE dispatch fragments) was explicitly
**not** merged -- so this capability does not advance, and does not
claim to advance, the M6-owned `verification_level.py`/IP_MODE
foundation (`CAP-M5M6-VLEVEL-001`) in any way. `M6_BLOCKERS_AFTER = 3`,
unchanged.

## Two real defects found and NOT propagated (the "B8 defect lesson," applied twice this wave)

1. **Canonical's own pre-existing defect** (not source-of-truth's fault):
   both `create_environment()` return branches hard-coded their
   `environment_mode` literal instead of using the real resolved value.
   Harmless today (the dispatch conditions currently guarantee the
   literal is always correct), but fragile against any future widened
   dispatch. Fixed in both branches, verified behavior-preserving via the
   full existing regression suite (291 tests unchanged).
2. **B8's own defect**: a synthetic `"status": "ASSEMBLED"` key added to
   the written/returned `verification_architecture.json` document,
   confirmed via a real `jsonschema.Draft202012Validator` run to violate
   `verification_architecture.schema.json`'s `additionalProperties:
   false`. Not propagated -- the document is written exactly as
   `assemble_verification_architecture()` (already byte-identical between
   canonical and B8) produces it, matching the dashboard's own existing
   `_read_verification_architecture_state()` convention for the identical
   document type.

## Known limitations (disclosed)

- `CAP-M5-ARCH-002` (`soc_environment_composer.py`) remains
  `NOT_STARTED` -- Cohort 2 is `PARTIAL`, not `CLOSED`.
- Per this task's own explicit instruction, `CAP-M5-ARCH-002` was not
  started in this session.
