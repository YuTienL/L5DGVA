# L5DGVA Integration Prime Directive V2 — Adoption and Remediation Report

Executed under `.work/prompts/L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2_
ADOPTION_AND_REMEDIATION_PROMPT.md`. Governance reconciliation (V2 adopted,
V1 superseded) plus current-scope remediation (P5 `FIND -> FIX -> VERIFY`)
— not permission to pull future-wave features forward, and none was.

## Preflight

```
PROCESS_CWD    = /d/DV/Task/L5_DGVA
REPO_ROOT      = D:/DV/Task/L5_DGVA
CURRENT_BRANCH = canonical/m4-dependency-closure
CURRENT_HEAD (start of this task) = 21a66b8d50962d13f8c64b653a33b520e7720a95
                 (the CAP-M6-C1-001 report-head commit, immediately prior
                 task in this same session)
WORKING_TREE_STATUS (start) = clean except the two untracked files this
                 task itself was dispatched to adopt
                 (.work/prompts/L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2_
                 ADOPTION_AND_REMEDIATION_PROMPT.md,
                 docs/architecture/L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2.md)
```

Read in full before reconciling/remediating: V2 itself, V1 (for the exact
diff), `CLAUDE.md`'s Integration Prime Directive section, `docs/
architecture/L5DGVA_CONSTITUTION.md`, `MASTER_PROGRAM_STATUS.md`/
`MASTER_BLOCKER_REGISTER.md`/`MASTER_CAPABILITY_STATUS_MATRIX.csv`/
`MASTER_END_TO_END_DV_STATUS.md`, `M6_GOLDEN_PATH_CONNECTIVITY_C1_
IMPLEMENTATION_REPORT.md`, `M6_VERTICAL_SLICE_STATUS.md`,
`M6_DISPATCH_001_IMPLEMENTATION_REPORT.md`,
`M6_CLARSVC_001_IMPLEMENTATION_REPORT.md`, `L5DGVA_GOLDEN_OPERATIONAL_
WORKFLOW.md`, `dv_harness/governance_registry.py`/`.json`.

Frozen sources re-verified UNCHANGED, before and after:

```
Parent (D:\DV\Task\DV_Agent_Harness_L5) = 3e9dd7360f584078ed8f4b04120c9844acabd97b
v50    (D:\DV\Task\DV_Agent_Harness_L5\v50)                                        = f3fd17326cf3654aca6fd83fad991a3f247e6682
b7a    (D:/wt/b7a) = 7b2a65a4dc2d40d493451b409669c90ed0b3d9a5
b7b    (D:/wt/b7b) = c7c7fa09e9ee8336ba102b4495f4b8808408fe0b
b8     (D:/wt/b8)  = c9cdd06ce586d44f4c0cef00310c10f95ea59f93
```

## Adopt / Supersede

```
L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2.md  = ACTIVE_DETAILED_AUTHORITY
L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md (V1) = SUPERSEDED_HISTORICAL
```

V1's file NOT deleted (`docs/architecture/L5DGVA_INTEGRATION_PRIME_
DIRECTIVE.md` still on disk, confirmed a real file this task). Governance
registry: the original `L5DGVA_INTEGRATION_PRIME_DIRECTIVE` entry was
renamed to `L5DGVA_INTEGRATION_PRIME_DIRECTIVE_HISTORICAL`
(`load_policy` downgraded `TASK_SCOPED` -> `EVIDENCE_ON_DEMAND`, pointing
at the same, unmoved V1 file) and a new `L5DGVA_INTEGRATION_PRIME_
DIRECTIVE_V2` entry added (`TASK_SCOPED`, `ACTIVE`). Exactly one active
entry at any time — enforced by a new test,
`test_governance_registry_carries_exactly_one_active_prime_directive_
entry`. No second registry created — the same `dv_harness/governance_
registry.py`/`.json` mechanism, reused. `CLAUDE.md` gained a rewritten
compact `ALWAYS_ON` pointer (P1-P5, `SUPERSEDED_HISTORICAL` stated
explicitly) — still no full-text duplication (checked: the directive's own
Golden Workflow stage list is not present in `CLAUDE.md`).
`docs/architecture/L5DGVA_CONSTITUTION.md`'s cross-reference section
updated identically.

## Governance registry and maturity

`ROADMAP_DEFINED -> FOUNDATION -> IMPLEMENTED -> WIRED -> TRIGGERED ->
CONSUMED -> PRODUCTION_CONNECTED -> OPERATIONAL -> QUALIFIED` reconciled
(the V1 ladder already had 8 of these 9 rungs; V2 inserts
`PRODUCTION_CONNECTED` between `CONSUMED` and `OPERATIONAL`, exactly
matching this task's own structural-vs-production distinction below — no
duplicate taxonomy).

## Re-verify known findings (real production code, not trusted from prior reports)

| # | Finding | PRODUCER | OUTPUT | CONSUMER | INPUT | PRODUCTION_ENTRY_PATH | CALLERS (fresh grep) | RUNTIME/TEST_EVIDENCE | CURRENT_STATUS | DISPOSITION |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Real production `field_controls` reach `ClarificationService`? | `generation_field_controls.py` | a `FieldControl`+producer for `protocol` | `clarification_service.resolve_or_ask()` | `start_lifecycle()`'s `protocols`/`generation_request` params | `cli start --generate`, `/api/start` | 0 literal `field_controls=` call sites in cli.py/dashboard.py (by design -- they never need to know the `FieldControl` type; `start_lifecycle()` builds it internally from `protocols`/`generation_request`) | 14/14 fresh pass, `test_m6_c1_golden_path_connectivity.py` re-run this task | **CONFIRMED CONNECTED** (re-verified fresh) | see GAP-V2-003 for what remains unconnected |
| 2 | Supported generation dispatch consumes governed `start_lifecycle()` path? | `start_lifecycle()`'s generation branch | a direct call to `create_environment()` | `create_environment.create_environment()` | resolved `protocol` + `generation_request` | same as #1 | fresh `grep -rn "create_environment("`: exactly 2 real callers, `engine.py:6687` and `tools/generate_protocol_uvm_environment.py:48` | same 14/14, plus the new failure-path test | **CONFIRMED CONNECTED for the governed path; the 2nd real caller remains ungoverned** | GAP-V2-002 |
| 3 | Is `ClarificationService` still a production capability island? | n/a (re-assessment) | n/a | n/a | n/a | n/a | n/a | ten-field classification, `L5DGVA_CAPABILITY_MATURITY_AND_ISLAND_POLICY.md` | **NO for the `protocol` edge (re-confirmed); YES for every other field (unconnected by design, GAP-V2-003)** | see gap register |
| 4 | `human_gate_state()` 0 production callers -- real gap or projection detail? | `clarification_service.human_gate_state()` | a status string | none in production | a question dict | n/a (helper never called from production) | fresh `grep -rn "human_gate_state("`: 2 matches, both in `test_clarification_service.py` | the underlying block/resume MECHANISM is production-consumed (14/14 above); this helper specifically is not | **PROJECTION DETAIL, NOT A DEFECT** | `NOT_APPLICABLE_WITH_EVIDENCE`, GAP-V2-004 |
| 5 | `CAP-M6-DISPATCH-001` P0 bookkeeping stale after closure? | `MASTER_CAPABILITY_STATUS_MATRIX.csv` | `PRIORITY` field | `AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT` | n/a | n/a | fresh `csv.DictReader` re-parse this task | `PRIORITY = 'P2 (downgraded...)'`, already fixed | **ALREADY FIXED (by C1), re-confirmed not regressed** | `SUPERSEDED_WITH_EVIDENCE`, GAP-V2-005 |

## P5 current-scope gap audit

Full detail: `L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv` (5 rows, 0 malformed,
0 duplicate `GAP_ID`s, 0 `DOCUMENT_ONLY` dispositions — machine-checked,
`test_no_current_scope_gap_is_ever_recorded_as_document_only`).

```
GAP-V2-001  FIX_NOW_CORRECTNESS_BLOCKER      CLOSED    (fixed this task)
GAP-V2-002  HUMAN_DECISION_REQUIRED          OPEN      (not fixed -- see below)
GAP-V2-003  REGISTER_AND_DEFER_WITH_OWNER    DEFERRED
GAP-V2-004  NOT_APPLICABLE_WITH_EVIDENCE     CLOSED    (re-verified, not a defect)
GAP-V2-005  SUPERSEDED_WITH_EVIDENCE         CLOSED    (already fixed prior task)
```

## Remediate current defects (P5 ladder applied to GAP-V2-001)

Full RCA/fix/test narrative for every gap: `L5DGVA_FIND_FIX_VERIFY_
EVIDENCE.md`. Summary for the one real fix:

`start_lifecycle()`'s generation branch (built by `CAP-M6-C1-001`, this
same session's immediately prior task) caught only 6 of
`create_environment()`'s own 10 real, documented exception classes.
Confirmed exhaustively by `grep -n "^class.*Error"` across
`create_environment.py`, `protocol_model_layer.py`, and
`soc_environment_composer.py` (10 classes total). Fixed: `engine.py`
imports `ProtocolModelLayerError`, `EmptySubsystemRegistryError`,
`MissingSubsystemNameEvidenceError`, `CrossSubsystemIntegrationBlockedError`
and adds them to the except tuple. New focused test reuses `test_
protocol_model_layer_wiring.py`'s own known-good failure trigger, driven
through the FULL governed path end to end, confirming a real
`AgentResult(ok=False, error="ProtocolModelLayerError")` instead of an
uncaught exception.

`CAP-M5M6-VLEVEL-001` and every M7-M14 item: **not implemented**, per this
task's own explicit instruction. `GAP-V2-002` (the legacy script) is
likewise **not implemented** — deliberately, because its correct
resolution is `HUMAN_DECISION_REQUIRED`, not a defect this task can
correctly fix without more information (see below).

## Architecture constraints preserved

```
User Entry -> start_lifecycle -> Intake/Field Resolution/HITL -> Dispatch
  -> Task Boundary -> [future VerificationLevel seam] -> Generation capability
```

Unchanged direction, re-confirmed: `create_environment.py` still has zero
lines referencing `start_lifecycle`, lifecycles, or `clarification_
service` (unmodified this task and its predecessor). `ONE_CLARIFICATION_
SERVICE`, `ONE_CANONICAL_FIELD_RESOLUTION_ENGINE`, `AUTO_DISCOVERY_FIRST`,
`MINIMAL_STRUCTURED_CLARIFICATION` all preserved — zero lines changed in
`clarification_service.py` or `intake_field_resolution.py` this task
(only `engine.py`'s except tuple, `dv_harness_tests/test_m6_c1_golden_
path_connectivity.py`, `CLAUDE.md`, `L5DGVA_CONSTITUTION.md`,
`governance_registry.json`, and the 4 required artifacts + Master CSVs
were touched).

## Structural vs production connectivity

Full per-edge evidence table: `L5DGVA_PRODUCTION_CONNECTIVITY_STATUS.md`.

```
M6_VERTICAL_SLICE_CONNECTED_STAGES (STRUCTURAL) = 8   (unchanged)
M6_PRODUCTION_CONNECTED_STAGES                  = 8   (unchanged count;
  re-verified fresh this task with a new focused test, not merely re-read
  from the prior report)
```

## HITL and evidence

DE/DV/SHARED authority: unchanged, `classify_question_owner()` untouched;
re-confirmed via `test_protocol_question_owner_is_verification`. `Evidence
Refs`/`Confidence`/`ValidationState`/`ConfirmationState` separation:
unchanged, `intake_field_resolution.py` untouched (only its module
docstring's stale "zero canonical callers" claim, corrected by `CAP-M6-
C1-001`, remains corrected). Blocking/resume behavior re-verified fresh
this task via the human-answer round-trip test (unchanged from C1,
re-run green).

## Bookkeeping correctness

Structural CSV parsing throughout (`csv.DictReader`, never grep).
`AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT` re-derived fresh, not copied from
the prior report: **3** — `{CAP-CE-018, CAP-M5M6-VLEVEL-001,
CAP-M8-EXPLOOP-001}`, identical set to `CAP-M6-C1-001`'s own closing
count (this task did not need to touch any P0 row; `CAP-M6-DISPATCH-001`
was already corrected). One new row registered,
`CAP-M6-INTPRIME-V2-001` (`PRIORITY = P2`, a closure task, not a new open
item). `MALFORMED_ROWS = 0`, `DUPLICATE_CAPABILITY_IDS = 0`,
`P0_COUNT_AMBIGUITY = 0` (single `PRIORITY.strip() == 'P0'` exact-match
method, consistent with every prior wave).

## Correctness closure (GAP-V2-001, the one fixed gap)

```
ROOT_CAUSE_COMPLETE = YES  (exhaustive grep across all 3 modules, not partial)
FIX_COMPLETE = YES  (all 10 real exception classes now caught, re-grep-verified)
CONTRACT_VALIDATED = YES  (create_environment()'s own documented raise contract, unchanged, now fully honored)
CALLERS_VALIDATED = YES  (0 unknown runtime callers; engine.py's own 2 import lines are the only change)
WIRING_VALIDATED = YES
PRODUCTION_DATAFLOW_VALIDATED = YES  (same governed CLI/dashboard entry points, unchanged)
HITL_VALIDATED = N/A  (a failure-path fix, no HITL interaction)
EVIDENCE_VALIDATED = YES
FAILURE_PATH_VALIDATED = YES  (the new test's own entire point)
E2E_VALIDATED = YES  (test_m6_c1_golden_path_connectivity.py's 14-test suite, full path)
REGRESSION_VALIDATED = YES  (see Regression section below)
UNKNOWN_RUNTIME_CALLERS = 0
UNKNOWN_REGRESSION_FAILURES = 0
SOURCE_CAPABILITY_LOSS = 0
```

`CLARIFICATION_CAPABILITY_ISLAND = NO` for the `protocol` edge, unchanged
and re-confirmed (this task added no new island; GAP-V2-002/003 are
disclosed, not islands of the SAME edge C1 already closed).

## Testing

`dv_harness_tests/test_m6_c1_golden_path_connectivity.py`: 14/14 (13
carried over from C1 + 1 new for GAP-V2-001).
`dv_harness_tests/test_l5dgva_integration_prime_directive_discoverability.py`:
6/6 (4 carried over, rewritten for V2 supersession + 2 new: V1-retained-
as-historical, DOCUMENT_ONLY-is-invalid). Real per-test hang discipline
applied throughout (current-test identity checked across consecutive
polls, cross-referenced against this population's own known ~19-20 minute
historical duration, never judged from CPU usage alone).

## Regression

```
python -m pytest <47 dispatch-caller files> + 13 directly-touched-module
  files (same population as CAP-M6-C1-001) + test_soc_environment_
  composer.py (the module 3 of the 4 newly-caught exception classes live
  in) -v
=> 7 failed, 1536 passed, 11 skipped in 1171.30s (0:19:31)
```

**Disclosed process artifact, not a real regression**: this background run
was launched, per this session's own established pattern, BEFORE the
`CLAUDE.md`/`governance_registry.json`/`test_l5dgva_integration_prime_
directive_discoverability.py` edits (V2 supersession + the 2 new
anti-drift tests) had all landed on disk -- pytest collects a file's
content once, at the start of a run; 2 of the reported "failures"
(`test_governance_registry_carries_the_prime_directive_entry`,
`test_claude_md_keeps_a_compact_always_on_pointer_never_the_full_text`)
are the file's OLD, pre-edit test names, collected before the rewrite
finished, not a real assertion failure against current code. Confirmed by
immediately re-running the actually-current file fresh, together with
`test_m6_c1_golden_path_connectivity.py`/`test_l5dgva_constitution.py`/
`test_governance_registry.py`: **40/40 pass**, including all 6 of the
current (renamed) discoverability tests.

The remaining **5** failures are the same, byte-identical, already-
classified `PRE_EXISTING` failures from every prior M6 regression this
session (`test_question_queue_digest_auto_trigger.py`,
`test_resource_cost_autonomy.py::test_3b_...`, and 3 in `test_waveform_
dump_scope_human_confirmation.py`) — unrelated to `engine.py`,
`generation_field_controls.py`, `governance_registry.json`, or `CLAUDE.md`.

`REGRESSION_CAUSED_BY_REMEDIATION = 0`, `UNKNOWN_REGRESSION_FAILURES = 0`
(both re-derived from the fresh 40/40 re-run, not the stale-collection
numbers above).

## Anti-drift and Master control plane

New anti-drift checks, both machine-checkable, both re-run green this
task: (1) exactly one ACTIVE detailed-directive registry entry at a time
(`test_governance_registry_carries_exactly_one_active_prime_directive_
entry`); (2) no current-scope gap can ever carry `DOCUMENT_ONLY`
(`test_no_current_scope_gap_is_ever_recorded_as_document_only`, enforced
against the real `L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv`). No new
governance subsystem built — both reuse `governance_registry.py`'s
existing `load_registry()`/`check_reachability()` and plain `csv.
DictReader`. No competing control plane created — `MASTER_CAPABILITY_
STATUS_MATRIX.csv`/`MASTER_WAVE_OWNERSHIP_MATRIX.csv` remain the one
program-level control plane, extended (one new row) not replaced.

## Governance gates

```
dv_harness.constitution_gate.check_constitution_intact('.')
  => ConstitutionCheckResult(status='PASS', reasons=[])
```

All 5 frozen sources re-verified unchanged immediately before this
report's own commit (see Preflight section above for the byte-identical
SHAs, re-checked at both start and end of this task).

## Validation

```
PRIME_DIRECTIVE_V2 = ADOPTED
PRIME_DIRECTIVE_V1 = SUPERSEDED_HISTORICAL
CONNECT_BEFORE_EXPAND = YES
OPERATIONAL_BEFORE_CLAIMED = YES
CLOSE_THE_LOOP = YES
NO_CAPABILITY_ISLANDS = TARGET
FIND_FIX_VERIFY = YES
CURRENT_SCOPE_DEFECTS_DOCUMENT_ONLY = 0
CLAUDE_MD_FULL_DIRECTIVE_DUPLICATED = NO
ARTICLE_0_PRESERVED = YES
STRUCTURAL_CONNECTIVITY_TRACKED = YES
PRODUCTION_CONNECTIVITY_TRACKED = YES
UNKNOWN_RUNTIME_CALLERS = 0
UNKNOWN_REGRESSION_FAILURES = 0
SOURCE_CAPABILITY_LOSS = 0
UNCONTROLLED_BYPASSES = 0
REFERENCE_USB_ENV_CONSUMED = NO
```

## Final Report

```
PRIME_DIRECTIVE_V2_ADOPTION_STATUS = READY_FOR_APPROVAL
PRIME_DIRECTIVE_V2 = ADOPTED
PRIME_DIRECTIVE_V1 = SUPERSEDED_HISTORICAL
CURRENT_SCOPE_GAPS_FOUND = 5
CURRENT_SCOPE_GAPS_FIXED = 1
CURRENT_SCOPE_GAPS_OPEN = 1  (GAP-V2-002, HUMAN_DECISION_REQUIRED)
FUTURE_SCOPE_GAPS_DEFERRED = 1  (GAP-V2-003)
CAPABILITY_ISLANDS_BEFORE = 1  (the protocol/generation edge, from C1's own audit)
CAPABILITY_ISLANDS_AFTER = 0  (that same edge; GAP-V2-002 is a disclosed
  ungoverned SECOND path to an already-non-island capability, not a new
  island of the same edge)
STRUCTURAL_CONNECTED_STAGES = 8
PRODUCTION_CONNECTED_STAGES = 8
UNKNOWN_RUNTIME_CALLERS = 0
UNCONTROLLED_BYPASSES = 0
REGRESSION_CAUSED_BY_REMEDIATION = 0
UNKNOWN_REGRESSION_FAILURES = 0
SOURCE_CAPABILITY_LOSS = 0
MASTER_CAPABILITY_MATRIX_ROWS = 159
MASTER_CAPABILITY_MATRIX_MALFORMED_ROWS = 0
MASTER_CAPABILITY_MATRIX_DUPLICATE_IDS = 0
AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 3
CURRENT_PROGRAM_POSITION = M6 IN_PROGRESS (CAP-M6-DISPATCH-001/
  CAP-M6-CLARSVC-001/CAP-M6-C1-001/CAP-M6-INTPRIME-V2-001 all CLOSED;
  CAP-M5M6-VLEVEL-001 open, the real next M6-owned P0; GAP-V2-002 a real,
  disclosed, separately-tracked open item not blocking this closure)
NEXT_RECOMMENDED_GATE = CAP-M5M6-VLEVEL-001 (VerificationLevel/IP_MODE
  foundation) -- held, not auto-started. GAP-V2-002 (the legacy script's
  own governance) is a SEPARATE, smaller human decision that could be
  resolved independently, whenever a human chooses.
REFERENCE_USB_ENV_CONSUMED = NO
```

## STOP

Per this dispatch's own explicit closing instruction: stopping here. Not
auto-starting `CAP-M5M6-VLEVEL-001` or any later wave. The governed
generation workflow (CLI `start --generate`, dashboard `/api/start`) is
closed and fully verified. `GAP-V2-002` (the legacy script's own
governance status) is explicitly **not** claimed closed — it remains its
own, real, disclosed, open item pending a separate human decision.
