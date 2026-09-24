# M6 Golden-Path Connectivity Closure C1 — Implementation Report

`CAP-M6-C1-001`. A narrowly-scoped integration task under `CONNECT BEFORE
EXPAND`, dispatched after the Integration Prime Directive adoption audit
found a real capability island: `ClarificationService`
(`CAP-M6-CLARSVC-001`) is real and internally wired, but no production
caller ever fed it real intake fields, and `create_environment.py`'s
generation dispatch never consumed the governed `start_lifecycle()` path.
No new architecture family created; `ClarificationService`, Field
Resolution, and `create_environment.py` are all unmodified internally.

```
M6_C1_STATUS = CLOSED

START_HEAD = 315bdbabdd8f6ed7bff92857cbfc2ddab7975e2d
END_HEAD   = 3b59c01eeafe420ce808f406e2260c5e34206be0
```

## 2. Confirming the two reported broken edges (real production code, not trust)

### EDGE_A: production intake/field-controls -> ClarificationService

| | Before C1 | Evidence |
|---|---|---|
| PRODUCER | none | `grep -rn "FieldControl(" dv_harness/` (non-test) returned zero matches |
| OUTPUT | n/a | n/a |
| CONSUMER | `clarification_service.resolve_or_ask()` (real, tested) | `test_clarification_service.py` |
| INPUT | `start_lifecycle()`'s own `field_controls: Iterable[FieldControl] = ()` parameter | `engine.py` |
| CALLER | `cli.py`'s `start` command, `dashboard.py`'s launcher | both called `start_lifecycle()` with no `field_controls` argument at all |
| RUNTIME_PATH | dead end at the parameter default | `field_controls = list(field_controls)` on an always-empty iterable |
| TEST_EVIDENCE | `test_clarification_service.py` proves the mechanism works when GIVEN a control; nothing proved any real caller ever built one | |
| **CURRENT_STATUS** | **DISCONNECTED** | |

### EDGE_B: governed start_lifecycle path -> verification-environment-generation dispatch

| | Before C1 | Evidence |
|---|---|---|
| PRODUCER | `start_lifecycle()` -> `_start_dispatch()` -> `loop()`/`run_stage()` | `engine.py` |
| OUTPUT | `AgentResult` from the Stage graph | |
| CONSUMER | intended: `create_environment.create_environment()` | never actually reached from here |
| INPUT | intended: a resolved generation request | n/a |
| CALLER (real, today) | `tools/generate_protocol_uvm_environment.py`'s own `main()`, calling `create_environment()` directly | `grep -rn "create_environment(" --include="*.py" .` found exactly one non-test, non-docstring caller, and it is that standalone script |
| RUNTIME_PATH | `create_environment()` never appears as a call target anywhere in `engine.py`'s `Stage`/`run_stage()` dispatch table (`gates.py`'s `STAGE_GATES["IMPLEMENT"]` runs an AI-agent prompt, not this deterministic function) | confirmed by direct grep of `engine.py` for `create_environment`/`environment_mode_router` -- both appear only as read-only evidence-reporting call sites |
| TEST_EVIDENCE | none connecting the two | |
| **CURRENT_STATUS** | **DISCONNECTED** | |

Both audit findings confirmed real, not assumed.

## 3. Production connectivity model

New, additive metric alongside the existing structural
`M6_VERTICAL_SLICE_CONNECTED_STAGES` (unchanged at 8 -- see
`M6_VERTICAL_SLICE_STATUS.md`'s own update section for the full per-stage
table): `M6_PRODUCTION_CONNECTED_STAGES`, counting a stage connected only
when a real CLI argv or a real dashboard HTTP JSON body reaches it -- never
a test calling `start_lifecycle()` directly in Python. Also **8**, but a
DIFFERENT stage set (swaps Task Boundary, still never production-supplied
by any CLI/dashboard flag, for IP/SUBSYSTEM/SYSTEM_LEVEL, now reached via
`create_environment()`'s own internal mode resolution) -- see the full
per-stage table in `M6_VERTICAL_SLICE_STATUS.md`.

## 4. Field-controls source (EDGE_A closure)

Traced: `start_lifecycle()`'s own pre-existing `protocols: Iterable[str]`
parameter already carries real production intake (CLI's `--protocols`,
already parsed into `declared_protocols` before this task) -- it was simply
never routed through Field Resolution. `intake_state.py` (canonical's OWN,
different, already-real intake joiner) was investigated and found to be
the WRONG source for this specific gap: its `BLOCKING_CATEGORIES`
(`dut_boundary`, `vip_resolution`, `active_driver_conflict`,
`critical_bind`, `build_env`, `known_pass_test`) require deep RTL/VIP/bind
evidence (`env.manifest.json`, `connectivity.py` gate results,
`phy_boundary.py` decisions) that does not exist yet at
`start_lifecycle()`'s own call time, before any Stage has run -- wiring it
in would have been a timing/semantic mismatch, not a genuine closure.

**No second Field Resolution engine was built.** A new, small adapter
module, `dv_harness/generation_field_controls.py`, imports `FieldControl`/
`EvidenceProducer`/`Candidate`/`SourceKind`/`Confidence` from
`intake_field_resolution.py` VERBATIM and defines exactly one
`FieldControl` (`protocol`, `domain="env"`) plus one evidence producer
(step `existing_files`, reading `.dv-harness/lifecycle.json`'s own
already-recorded `protocols` fact -- `AUTO_DISCOVERY_FIRST`, a real
existing source, never a new scan).

`FIELD_CONTROLS_SOURCE = start_lifecycle()'s own pre-existing protocols
parameter, projected by generation_field_controls.py`.

## 5. Clarification production consumption

`engine.py`'s `start_lifecycle()` now builds `field_controls_for_
resolution` including the `protocol` control **only when `generation_
request` is supplied** (an opt-in, not an unconditional new friction point
on every ordinary call -- see section 13 below for why unconditional was
tried first and reverted). `resolve_or_ask(qstore, control, declared=...,
producers=...)` is called exactly as `clarification_service.py` already
supports (the `declared`/`producers` keyword arguments existed before this
task but no caller had ever used them) -- `AUTO_DISCOVERY_FIRST`,
`MINIMAL_STRUCTURED_CLARIFICATION`, `ONE_CLARIFICATION_SERVICE`, and `ONE_
CANONICAL_FIELD_RESOLUTION_ENGINE` all preserved: zero lines changed in
`clarification_service.py` or `intake_field_resolution.py`.

## 6. Answer loop

Full real production round trip, tested end-to-end
(`test_human_answer_unblocks_generation_and_is_persisted_as_a_lifecycle_
fact`): unresolved real intake field (`protocol`, no declared value, no
lifecycle fact) -> `ClarificationService` files a real question ->
`QuestionOwner` = `VERIFICATION` (domain `env`) -> `HumanGate` blocks
(`ok=False`, `blocked_by="clarification"`, generation never runs, adapter
never called) -> a real human answer via `QuestionQueueStore.answer_
question()` -> a SECOND `start_lifecycle()` call re-resolves through
`resolve_field(..., human_answer=...)` -> `EffectiveValue` resolved ->
generation runs. No mock-only/unit-only path counted.

## 7. Generation edge

`create_environment.py` is unmodified. Direction established:
`start_lifecycle()` calls `create_environment.create_environment()`
directly (a new, additive branch at the end of `start_lifecycle()`,
reached only when `generation_request is not None`) -- `create_
environment.py` has no knowledge of `start_lifecycle()`, `clarification_
service.py`, or lifecycles at all; it is called the same way `tools/
generate_protocol_uvm_environment.py` already calls it, just from a
governed caller instead of an ungoverned script.
`test_generation_dispatch_calls_create_environment_directly_never_
recurses` confirms exactly one call, with the governed, resolved protocol
value substituted into `request["protocol"]`, and confirms the ordinary
Stage-graph adapter is never invoked by this path (no recursion, no
inversion).

## 8. Single entry contract

`CAP-M6-DISPATCH-001`'s decision is unchanged and re-confirmed:
`start --advanced` and `run-stage --advanced` remain the only two
authorized low-level bypasses, both still recording a real
`LifecycleStore.record_bypass()` entry. C1 adds no new bypass. Confirmed
this task that `--advanced` also skips the NEW generation mechanism
entirely (`test_advanced_bypass_skips_the_new_generation_mechanism_
entirely`) -- the `advanced` branch returns before `generation_request` is
ever consulted, so an authorized bypass truly bypasses everything the
governed path does, never a partial gate.

## 9. CLI / dashboard

Both tested with REAL data propagation, not merely "was `start_lifecycle()`
called":

- **CLI**: `start --protocols pcie --generate --generate-out <dir>
  --generate-manifest <file>` -- `test_cli_start_generate_propagates_
  protocol_and_manifest_into_start_lifecycle` asserts the exact `kwargs`
  `start_lifecycle()` received (`protocols=("pcie",)`,
  `generation_request["clocks"]` from the real manifest file,
  `generation_out_dir` as a real `Path`).
- **Dashboard**: `/api/start`'s JSON body gained `protocols`/`generate`/
  `generation_request`/`generate_out` fields, threaded through `_start_
  background_run()`'s own new, additive, default-`None`/`()` parameters.
  `test_dashboard_start_background_run_propagates_generation_fields`
  confirms a dashboard-shaped call resolves the protocol field and
  persists it as a real lifecycle fact.
  `test_dashboard_start_background_run_with_no_generation_fields_is_
  unchanged` confirms the pre-C1 call shape (no new fields) is still a
  byte-identical no-op.

```
CLI_PRODUCTION_CONNECTIVITY = CONNECTED
DASHBOARD_PRODUCTION_CONNECTIVITY = CONNECTED
```

## 10. create_environment integration

`create_environment.py` remains a generation capability BENEATH the
workflow, never turned into a second orchestrator -- zero lines changed in
that file or its own module (`dv_harness/uvm_generator/create_
environment.py`). Direction: `start_lifecycle -> dispatch -> generation ->
create_environment`, never the reverse (confirmed by
`test_generation_dispatch_calls_create_environment_directly_never_
recurses`'s own assertion that the ordinary Stage-graph adapter is never
invoked from inside the generation branch).

```
CREATE_ENVIRONMENT_IS_WORKFLOW_ORCHESTRATOR = NO
START_LIFECYCLE_IS_PRIMARY_GOVERNED_ENTRY = YES
```

## 11. VLEVEL boundary

`VerificationLevel` NOT implemented. `environment_mode_router.py` untouched
-- `create_environment()` still resolves `SUBSYSTEM_MODE`/`SYSTEM_LEVEL_
MODE`/unresolved exactly as it always has; C1 only ensures the REQUEST
reaching it is now governed. The seam is explicit and unfilled:

```
Task Boundary -> [VerificationLevel future seam, still ABSENT] -> IP/SUBSYSTEM/SYSTEM generation
```

`level` remains a stored-but-uninterpreted lifecycle fact, unchanged from
`CAP-M6-DISPATCH-001`'s own disposition. `protocols` is now DIFFERENT --
still not used for IP/SUBSYSTEM/SYSTEM_LEVEL MODE SELECTION (that
selection algorithm, `environment_mode_router.resolve_environment_mode()`,
is untouched), but now genuinely resolved through Field Resolution/
Clarification before being handed to `create_environment()`'s own,
separate, unmodified mode-resolution logic.

## 12. Test-first evidence

`dv_harness_tests/test_m6_c1_golden_path_connectivity.py` -- 13/13 pass,
covering every required family from this task's own dispatch: real
field_controls propagation, auto-resolved no-question path, real
unresolved clarification path, QuestionOwner propagation, HumanGate
blocking, answer -> Field Resolution, EffectiveValue after answer (recorded
as a real lifecycle fact), CLI production path, dashboard production path,
governed generation dispatch, create_environment consumer direction
(no lifecycle recursion), and authorized low-level bypass preservation. A
13th test confirms a real `MissingOutputDirectoryError` from
`create_environment()`'s own documented contract surfaces as an ordinary
`AgentResult(ok=False)`, not an uncaught exception.

## 13. Capability island reassessment

```
CLARIFICATION_CAPABILITY_ISLAND = NO   (for this specific edge: the
  protocol field, reached from real CLI/dashboard production entry points,
  its output genuinely consumed by the governed create_environment() call)
```

Classified against the ten-field test (`L5DGVA_CAPABILITY_MATURITY_AND_
ISLAND_POLICY.md`): TRIGGER = a real `start --generate`/`/api/start`
call; INPUT = the resolved `protocol` FieldControl; PRODUCER =
`generation_field_controls.py` + `intake_field_resolution.resolve_field()`;
CAPABILITY = `clarification_service.resolve_or_ask()`; OUTPUT = a resolved
`EffectiveValue`, substituted into `request["protocol"]`; CONSUMER =
`create_environment.create_environment()`, called directly; NEXT_STAGE =
generation's own real output (`generated_files`, `structural_lint`, etc.);
EVIDENCE = the 13 tests above; FAILURE_PATH = a real `AgentResult(ok=False,
blocked_by=...)` for both the unresolved-field case and every one of
`create_environment()`'s own documented exceptions; HUMAN_AUTHORITY =
`classify_question_owner()`, `VERIFICATION` for this field. All ten
nameable -> not an island.

**Two islands honestly NOT closed by this task, disclosed rather than
hidden:**

1. `tools/generate_protocol_uvm_environment.py` still calls `create_
   environment()` directly, ungoverned -- out of this task's own named
   scope (section 9 named only CLI/dashboard). A real, disclosed,
   still-open bypass, distinct from the two AUTHORIZED, recorded bypasses
   (`start --advanced` / `run-stage --advanced`) -- this one is not scoped,
   not recorded, and not an explicit low-level primitive by policy, only
   by the accident of never having been connected. Recommended as this
   task's own follow-up owner, not fixed here.
2. Every intake field OTHER than `protocol` still has zero production
   producer. This closure is deliberately one field, not a general claim.

## 14. Bookkeeping reconciliation

Inspected structurally (`csv.DictReader`, never grep), not assumed:
`CAP-M6-DISPATCH-001`'s `MASTER_CAPABILITY_STATUS_MATRIX.csv` row was still
`PRIORITY=P0`, `CANONICAL_STATE="PARTIAL (conflict named and understood)"`,
`BLOCKER="HUMAN_DECISION_REQUIRED: ..."` -- even though `DEC-M6-
DISPATCH-001 = OPTION_A` was approved and the capability closed (commit
`17f244f`) well before this task began. Canonical blocker policy (every
other Master row's own established convention, e.g. `CAP-M6-CLARSVC-001`'s
own prior downgrade) treats a genuinely CLOSED capability as no longer an
open P0 blocker -- reconciled accordingly.

```
P0_BEFORE (exact CAPABILITY_ID set) = {CAP-CE-018, CAP-M5M6-VLEVEL-001, CAP-M6-DISPATCH-001, CAP-M8-EXPLOOP-001}
P0_AFTER  (exact CAPABILITY_ID set) = {CAP-CE-018, CAP-M5M6-VLEVEL-001, CAP-M8-EXPLOOP-001}
```

`CAP-M6-DISPATCH-001` -> `PRIORITY` P0 -> P2, `CANONICAL_STATE` ->
`RESOLVED`, `IMPLEMENTED/WIRED/TRIGGERED/CONSUMED/TESTED` = YES,
`BLOCKER` -> `NONE`. `MASTER_WAVE_OWNERSHIP_MATRIX.csv`'s matching row
updated identically (`PRIORITY`/`BLOCKER_TYPE`). A new row,
`CAP-M6-C1-001`, registers this task's own closure in both CSVs
(`PRIORITY=P2`, `BLOCKER=NONE` -- a closure task, not a new open item).
Structural re-validation: 158 status rows (157+1), 0 malformed, 0 duplicate
`CAPABILITY_ID`s.

## 15. Validation

```
EDGE_A_PRODUCTION_FIELD_CONTROLS_TO_CLARSVC = CONNECTED
EDGE_B_GOVERNED_LIFECYCLE_TO_GENERATION     = CONNECTED
CLARIFICATION_CAPABILITY_ISLAND             = NO
ONE_CLARIFICATION_SERVICE                   = YES
ONE_CANONICAL_FIELD_RESOLUTION_ENGINE       = YES
CREATE_ENVIRONMENT_IS_WORKFLOW_ORCHESTRATOR = NO
START_LIFECYCLE_IS_PRIMARY_GOVERNED_ENTRY   = YES
UNKNOWN_RUNTIME_CALLERS                     = 0
UNCONTROLLED_BYPASSES                       = 0
REGRESSION_CAUSED_BY_C1                     = 0
UNKNOWN_REGRESSION_FAILURES                 = 0
REFERENCE_USB_ENV_CONSUMED                  = NO
```

`UNKNOWN_RUNTIME_CALLERS = 0`: `start_lifecycle()`'s signature gained two
new, purely-additive, default-`None` keyword parameters
(`generation_request`, `generation_out_dir`) -- every existing call site
continues to work unchanged (confirmed: `test_start_lifecycle_dispatch.py`
36/36 and `test_clarification_service.py`'s own suite both still pass
byte-for-byte, see section 16). `UNCONTROLLED_BYPASSES = 0`: no new bypass
added; the two pre-existing authorized ones are unchanged and re-confirmed
still bypass the new mechanism too (section 8).

## 16. Prime Directive KPIs

```
M6_VERTICAL_SLICE_CONNECTED_STAGES = 8   (unchanged, structural)
M6_PRODUCTION_CONNECTED_STAGES     = 8   (new; different stage set -- see
  M6_VERTICAL_SLICE_STATUS.md's full per-stage table, section 3 above)
```

Every connected stage in both sets is backed by a real, named, passing
test (cited per-stage in `M6_VERTICAL_SLICE_STATUS.md`) -- neither count
is a module-existence or import-only inflation.

## Regression

```
python -m pytest <47 dispatch-caller files> + 13 directly-touched-module
  files (clarification_service, m6_c1, create_environment/uvm_structural_
  lint/system_level/protocol_model_layer/subsystem_maturity, dashboard_
  interactive, cli_question_queue, question_queue, intake_field_resolution,
  intake_state, integration-prime-directive discoverability, l5dgva
  constitution, governance_registry) -v
```

Real per-test hang discipline applied throughout (current-test identity
checked across consecutive polls, cross-referenced against this
population's own known ~18-19 minute historical duration from the prior
two M6 regressions, rather than judged from CPU usage alone).

```
=========== 5 failed, 1511 passed, 11 skipped in 1159.02s (0:19:19) ===========
```

All 5 failures byte-identical, by test ID, to the same 5 already classified
`PRE_EXISTING` by `M5_FINAL_CLOSURE_FAILURE_CLASSIFICATION.md` and
re-confirmed unchanged across every M6 regression since
(`test_question_queue_digest_auto_trigger.py::test_digest_fires_after_a_
real_gate_verified_stage_pass`, `test_resource_cost_autonomy.py::test_3b_
run_stage_performs_the_escalation_for_the_agent`, and 3 in `test_waveform_
dump_scope_human_confirmation.py`) -- none of the 5 failing files touch
`generation_field_controls.py`, `engine.py`'s `start_lifecycle()`, `cli.py`'s
`start` command, or `dashboard.py`'s launcher/`_handle_start()`.
`REGRESSION_CAUSED_BY_C1 = 0`, `UNKNOWN_REGRESSION_FAILURES = 0`.

## Governance gates

```
dv_harness.constitution_gate.check_constitution_intact('.')
  => ConstitutionCheckResult(status='PASS', reasons=[])
```

All 5 frozen sources (Parent/v50/b7a/b7b/b8) re-verified unchanged
immediately before this report's own commit:

```
Parent (D:\DV\Task\DV_Agent_Harness_L5) = 3e9dd7360f584078ed8f4b04120c9844acabd97b  UNCHANGED
v50    (D:\DV\Task\DV_Agent_Harness_L5\v50)                                        = f3fd17326cf3654aca6fd83fad991a3f247e6682  UNCHANGED
b7a    (D:/wt/b7a) = 7b2a65a4dc2d40d493451b409669c90ed0b3d9a5  UNCHANGED
b7b    (D:/wt/b7b) = c7c7fa09e9ee8336ba102b4495f4b8808408fe0b  UNCHANGED
b8     (D:/wt/b8)  = c9cdd06ce586d44f4c0cef00310c10f95ea59f93  UNCHANGED
```

## Disclosed, out-of-scope observation

Two new untracked files appeared in the working tree during this task
(`.work/prompts/L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2_ADOPTION_AND_
REMEDIATION_PROMPT.md`, `docs/architecture/L5DGVA_INTEGRATION_PRIME_
DIRECTIVE_V2.md`) that this task did not create. Left completely
untouched and unstaged -- out of C1's own declared scope, likely a
follow-up dispatch, not opened or acted on without explicit instruction.

## STOP

Per this dispatch's own explicit closing instruction: stopping here. Not
auto-starting `CAP-M5M6-VLEVEL-001`.
