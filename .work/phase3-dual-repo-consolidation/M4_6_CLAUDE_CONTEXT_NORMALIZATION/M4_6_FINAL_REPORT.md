# M4.6 — CLAUDE Context Normalization — Final Report

## Safety (S1, re-verified)

```
PROCESS_CWD = D:\DV\Task\L5_DGVA
REPO_ROOT   = D:\DV\Task\L5_DGVA
is_l5dgva_repo() = True
CURRENT_BRANCH = canonical/m4-dependency-closure
CURRENT_HEAD (pre-M4.6 commit) = b8a573fb534843389a69097771003ddba0a591e0

SOURCE_A (Parent) HEAD = 3e9dd7360f584078ed8f4b04120c9844acabd97b  UNCHANGED
SOURCE_B (v50) HEAD    = f3fd17326cf3654aca6fd83fad991a3f247e6682  UNCHANGED
B7A HEAD = 7b2a65a4dc2d40d493451b409669c90ed0b3d9a5  UNCHANGED
B7B HEAD = c7c7fa09e9ee8336ba102b4495f4b8808408fe0b  UNCHANGED
B8  HEAD = c9cdd06ce586d44f4c0cef00310c10f95ea59f93  UNCHANGED

Constitution/Anti-Drift gate (run BEFORE editing) = PASS, 0 reasons
Constitution/Anti-Drift gate (run AFTER editing)  = PASS, 0 reasons
```

## What M4.6 did

Split canonical `CLAUDE.md` into a compact `ALWAYS_ON` core (Constitution
+ Core Operating Rules + Evidence Truth Rule + Engineering Memory Policy
+ 21 cross-cutting hard-boundary rules, exact-name-matched against
Parent's own already-compacted equivalent rules) plus a governance
router, while moving 321 detailed, domain-specific sections **verbatim**
(zero content rewritten, zero content deleted) into 7 documents under
`docs/architecture/canonical_detailed_governance/`, each registered in
the existing `dv_harness/governance_registry.json` (no second registry
created). Built and TDD'd `dv_harness/claude_reference_graph.py` to
give `CLAUDE_REFERENCE_GRAPH`/`CLAUDE_AUTHORITY_EXECUTION_GRAPH` a real,
tested answer instead of an assertion.

## Required fields (S25)

```
M4_6_STATUS = READY_FOR_APPROVAL
M4_6_BRANCH = canonical/m4-dependency-closure
M4_6_HEAD = <filled in after commit, see below>

CLAUDE_MD_LINES_BEFORE = 22461
CLAUDE_MD_LINES_AFTER  = 1640
CLAUDE_MD_BYTES_BEFORE = 2067655
CLAUDE_MD_BYTES_AFTER  = 112262
CLAUDE_MD_BYTE_REDUCTION = 1955393 bytes (94.57%)

ALWAYS_ON_SECTIONS = 42
TASK_SCOPED_SECTIONS = 301
EVIDENCE_ON_DEMAND_SECTIONS = 20
  (42 + 301 + 20 = 363, reconciles exactly against
   M4_6_CLAUDE_SECTION_INVENTORY.csv's row count)

AUTHORITY_LOSS = 0
BEHAVIORAL_GOVERNANCE_LOSS = 0
UNRESOLVED_CONTEXT_CLASSIFICATION = 0

TASK_SCOPED_GOVERNANCE_RETRIEVAL = OPERATIONAL
MINIMUM_SUFFICIENT_CONTEXT = PARTIAL
  (real improvement -- 301 sections no longer unconditionally loaded --
   but no per-domain further-distillation exists yet; SUMMARY_PATH ==
   FULL_SPEC_PATH for all 6 new TASK_SCOPED entries, disclosed not hidden)

CLAUDE_REFERENCE_GRAPH = VALID
CLAUDE_AUTHORITY_EXECUTION_GRAPH = VALID
  (disclosed bound: indexes governance docs + agent/skill files; does not
   yet separately index contracts/templates/tools as distinct node types)

TOKEN_REDUCTION_MEASURED = NO

REGRESSION_CAUSED_BY_M4_6 = <filled in after the regression run, see below>
UNKNOWN_REGRESSION_FAILURES = <filled in after the regression run, see below>

M5_STARTED = NO
M6_STARTED = NO
M7_STARTED = NO
REFERENCE_USB_ENV_CONSUMED = NO
PLATFORM_UPGRADE_STARTED = NO
```

## Exit criteria (S24) — checked against real evidence

```
AUTHORITY_LOSS = 0                                    -- YES, verified (M4_6_ALWAYS_ON_AUTHORITY.md)
BEHAVIORAL_GOVERNANCE_LOSS = 0                         -- YES, verified (every section moved verbatim, cited by original line range)
UNRESOLVED_CONTEXT_CLASSIFICATION = 0                  -- YES, all 363 sections decisively classified (14 lower-confidence fallback, still decisive, not UNKNOWN)
ARTICLE_0_REACHABLE = YES                              -- test_claude_reference_graph.py
P1_P5_REACHABLE = YES                                  -- same
ANTI_DRIFT_REACHABLE = YES                             -- same
REPOSITORY_ROOT_CONTRACT_REACHABLE = YES               -- same, with a disclosed naming equivalence (no literal "Repository Root Contract" heading ever existed in canonical; the Canonical Identity heading + l5dgva_repo.py code plays that role)
TASK_SCOPED_GOVERNANCE_RETRIEVAL = OPERATIONAL         -- see MASTER_CAPABILITY_STATUS_MATRIX.csv update
GOVERNANCE_DUMP = PROHIBITED                           -- test_evidence_on_demand_not_selected_by_an_unrelated_scope PASS
CLAUDE_REFERENCE_GRAPH = VALID                         -- test_validate_reference_graph_is_valid_on_the_real_repo PASS
CLAUDE_AUTHORITY_EXECUTION_GRAPH = VALID               -- 5/5 scope-resolution tests PASS
ROOT_LAYOUT_GATE = PASS                                -- test_location_independence_and_root_hygiene_still_hold PASS
LOCATION_INDEPENDENT = YES                             -- same
REGRESSION_CAUSED_BY_M4_6 = <pending>
UNKNOWN_REGRESSION_FAILURES = <pending>
SOURCE_A_CHANGED_SINCE_M0 = NO                         -- re-verified
SOURCE_B_CHANGED_SINCE_M0 = NO                         -- re-verified
B7A_CHANGED = NO                                       -- re-verified
B7B_CHANGED = NO                                       -- re-verified
B8_CHANGED = NO                                        -- re-verified
REFERENCE_USB_ENV_CONSUMED = NO                        -- unchanged
```

**Full closure (`READY_FOR_APPROVAL` with all fields filled) is
contingent on the regression run below completing clean.** This report
is updated in place once that run finishes — see the "Regression
closure" section, appended after the run.

## Known, disclosed limitations (not fabricated as solved)

1. `MINIMUM_SUFFICIENT_CONTEXT` stays `PARTIAL` — no per-domain
   distillation yet, only verbatim relocation.
2. The 65,536-byte `claude_md_index` residency budget is not fully met
   (112,262 bytes, ~1.7x over — down from ~31.6x over before M4.6).
3. `CLAUDE_AUTHORITY_EXECUTION_GRAPH` does not yet separately index
   contracts/templates/tools as distinct node types.
4. 14 of 363 sections were classified via a lower-confidence keyword
   fallback (still decisive, not `UNKNOWN`), disclosed in
   `M4_6_CONTEXT_CLASSIFICATION.csv`.
5. One section (`S063`) was initially keyword-misrouted and manually
   corrected — disclosed in `M4_6_TASK_SCOPED_ROUTING.md`.

None of these block `READY_FOR_APPROVAL` per the exit criteria above,
but none is hidden either.

**STOP. Do not start M5/M6/M7. Waiting for explicit approval.**
