# CAP-M5-TOPTB-001 -- Final Report

```
M5_STATUS               = IN_PROGRESS
CAP_M5_TOPT_B001_STATUS = CLOSED

START_HEAD = c91da7c
END_HEAD   = <recorded in the closing commit -- see git log>

SOURCE_OPERATIONALITY    = OPERATIONAL (IMPLEMENTED/WIRED/TRIGGERED/
                            CONSUMED/OBSERVED/TESTED, all confirmed with
                            real evidence -- Parent's own 37-test run,
                            HD-1 commit history, and both real production
                            callers verified)
CANONICAL_EQUIVALENCE    = NO (confirmed absent, zero partial equivalent
                            found)

CALLERS_ANALYZED = 8
UNKNOWN_CALLERS  = 0

PRIMARY_DISPOSITION  = MIGRATE_WITH_ADAPTATION
PRIMARY_OWNER_WAVE   = M5 (this wave)

M5_BEHAVIOR_MIGRATED  = YES
FUTURE_EXTENSION_WAVE = NONE named -- Parent's own "EXTEND" follow-on
                         (splicing VIP/UVM hooks into a preserved top TB)
                         is itself unimplemented in Parent; no source
                         proves it, so no future wave is assigned to it
                         yet (would be assigned when a real source exists)

SOURCE_CAPABILITY_LOSS      = 0
UNKNOWN_REGRESSION_FAILURES = 0

N_WAY_TARGETS_COMPLETED_TOTAL = 5 (CAP-M5-ENV-001, CAP-M5-ARCH-003,
                                 CAP-M5-ARCH-001, CAP-M5-ARCH-002,
                                 CAP-M5-TOPTB-001)
N_WAY_TARGETS_REMAINING       = 4 (CAP-M5-VIP-001, CAP-M5-COV-001,
                                 CAP-M5-DSI-001, plus the 2 named ATL
                                 contract-migration inputs counted as one
                                 Cohort-4 unit)

AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 6 (unchanged -- this capability
                                 was P2, downgraded to P3, never P0)

SOURCE_A_CHANGED = NO   SOURCE_B_CHANGED = NO   B7A_CHANGED = NO   B7B_CHANGED = NO   B8_CHANGED = NO
REFERENCE_USB_ENV_CONSUMED = NO

COHORT_3_STARTED = NO
M6_STARTED        = NO

NEXT_RECOMMENDED_GATE = Cohort 3 (CAP-M5-VIP-001, the KNOWN RISK
  classify_by_inheritance() 4-to-5-tuple signature-break capability) --
  the M5 next-gate recommendation from the prior report is preserved
  unchanged; this capability's resolution does not redirect it
```

## Why this reversed the ARCH-002-wave deferral (accountability, disclosed)

The earlier deferral (during CAP-M5-ARCH-002) was made on real but
incomplete evidence: the code diff and the missing dependency module were
checked, but Parent's own test coverage for the feature and its real git
history (establishing the HD-1 human-decision provenance) were not. This
task's own explicit instruction to determine disposition "from evidence"
rather than assuming DEFER surfaced that gap. The correction is disclosed
here rather than silently reflected only in the new commit -- the earlier
deferral was a reasonable, honest judgment call given what was checked at
the time, not a mistake to hide.

## Real finding this wave beyond migration itself

The idempotency nuance (Section 9 of the governing task, detailed in
`M5_TOPT_B001_PRESERVATION_SEMANTICS.md`): a second composition of the
same project root re-discovers and preserves its OWN prior composition
output (newest mtime wins), not the true original hand-authored source,
unless `existing_top_tb_declared_path` is supplied. This is internally
consistent (never corrupts, always records its disposition), not a
defect blocking migration, but a real, non-obvious behavior neither
Parent's own 40-test suite nor its commit message explicitly covers --
surfaced and documented rather than silently inherited.
