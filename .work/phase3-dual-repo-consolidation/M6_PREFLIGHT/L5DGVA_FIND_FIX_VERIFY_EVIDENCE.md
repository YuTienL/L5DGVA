# L5DGVA FIND → FIX → VERIFY Evidence (P5, V2)

One section per gap in `L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv`, following
V2's own P5 ladder: `DISCOVER → CLASSIFY → ROOT CAUSE → FIX/INTEGRATE →
FOCUSED TEST → PRODUCER→CONSUMER TEST → PRODUCTION DATAFLOW TEST → E2E
VALIDATION → REGRESSION → EVIDENCE REVIEW → CORRECTNESS VERIFIED → CLOSE`.

## GAP-V2-001 — uncaught generation-path exceptions (FIX_NOW_CORRECTNESS_BLOCKER, CLOSED)

**DISCOVER.** Re-verifying re-verify-item 2 ("does the governed generation
dispatch actually work correctly for every documented failure mode, not
just the happy path") led to re-reading `create_environment()`'s own
docstring line by line: "Raises `EnvironmentModeUnresolvedError`/
`MissingOutputDirectoryError`/`SubsystemModeRequiredError`/
`StructuralLintFailedError`/`VipApiUnprovableError`/
`VerificationArchitectureConflictError`... `protocol_model_layer.
ProtocolModelLayerError`... `compose_soc_environment()`'s own
`NotImplementedError`". `engine.py`'s own except tuple (written during
CAP-M6-C1-001) had exactly the first 6, plus a bare `NotImplementedError`.

**CLASSIFY.** `FIX_NOW_CORRECTNESS_BLOCKER` — a real, documented,
reachable failure mode of the exact new code this session wrote would
crash the caller instead of returning the same `AgentResult(ok=False)`
shape every other failure mode already returns. `FAILURE_PATH_CORRECTNESS`
violated for 4 of 10 real exception classes.

**ROOT CAUSE.** The except tuple was built by reading only
`create_environment.py`'s own 6 locally-defined exception classes, not the
2 OTHER modules its docstring explicitly names as sources of propagated
exceptions (`protocol_model_layer.py`, `soc_environment_composer.py`).
Confirmed exhaustively: `grep -n "^class.*Error" dv_harness/uvm_generator/
{create_environment,protocol_model_layer,soc_environment_composer}.py`
found exactly 10 classes total, 4 of them outside `create_environment.py`
itself.

**FIX/INTEGRATE.** `engine.py` gained 2 new import statements
(`from .uvm_generator.protocol_model_layer import ProtocolModelLayerError`;
`from .uvm_generator.soc_environment_composer import
CrossSubsystemIntegrationBlockedError, EmptySubsystemRegistryError,
MissingSubsystemNameEvidenceError`) and the except tuple grew from 7
entries (6 named + `NotImplementedError`) to 11 (10 named +
`NotImplementedError`). No other line changed.

**FOCUSED TEST.**
`test_a_rejected_protocol_model_topology_returns_a_real_agent_result_not_
an_uncaught_exception` — reuses `test_protocol_model_layer_wiring.py`'s
own known-good trigger (a PCIe topology with `lane_width=3`, illegal) as
`generation_request`, drives it through the FULL governed path
(`start_lifecycle(protocols=["PCIe"], generation_request=...)`), and
asserts `r.ok is False`, `r.raw["blocked_by"] == "generation"`,
`r.raw["error"] == "ProtocolModelLayerError"`, and that nothing was
written to `out_dir` (matching `create_environment()`'s own direct-call
contract, confirmed unchanged).

**PRODUCER→CONSUMER TEST.** The same test IS the producer→consumer test:
`create_environment()` (producer of the exception) → `start_lifecycle()`'s
except tuple (consumer, now catching it) → `AgentResult` (the real
contract both `cli.py` and `dashboard.py` already handle uniformly for
every OTHER failure mode).

**PRODUCTION DATAFLOW TEST.** Not repeated separately for CLI/dashboard —
the fix is inside `start_lifecycle()` itself, already proven reachable
from both entry points by the EDGE_A/EDGE_B production tests; the failure
path shares the exact same call site.

**E2E VALIDATION.** `test_m6_c1_golden_path_connectivity.py`'s full 14-test
suite re-run together (all pass) confirms this fix did not disturb the
happy-path generation flow (`test_declared_protocol_resolves_silently_no_
question_filed`, `test_generation_dispatch_calls_create_environment_
directly_never_recurses`, etc.).

**REGRESSION.** See the "Regression" section of the Adoption Report — the
same 47+13-file population, plus `test_soc_environment_composer.py` (the
module two of the newly-caught exceptions live in), re-run in full this
task.

**EVIDENCE REVIEW / CORRECTNESS VERIFIED / CLOSE.** `ROOT_CAUSE_COMPLETE=
YES` (exhaustive grep, not partial), `FIX_COMPLETE=YES` (all 10 real
classes now caught, verified by the same grep re-run), `FAILURE_PATH_
VALIDATED=YES` (real test drives a real documented failure mode end to
end). `CAP-M6-C1-002` registered as this gap's own closure identity.

## GAP-V2-002 — legacy ungoverned generation script (HUMAN_DECISION_REQUIRED, OPEN)

**DISCOVER.** Re-verify item 2/3: fresh `grep -rn "create_environment("`
confirmed exactly 2 real callers — the new governed `engine.py` path and
`tools/generate_protocol_uvm_environment.py`'s own `main()`, unchanged.

**CLASSIFY.** Not `FIX_NOW` — see the Gap Register's own `FIX` column for
the full reasoning. This script's own governance model is genuinely
ambiguous (three defensible resolutions, not one), and per this task's own
architecture-constraint instruction ("do not make `create_environment.py`
a second workflow orchestrator... preserve `ONE_CANONICAL_FIELD_
RESOLUTION_ENGINE`") a wrong unilateral choice here risks exactly the kind
of invasive, undirected change this task is scoped to avoid. Classified
`HUMAN_DECISION_REQUIRED`, one of V2's own 8 valid dispositions — not
`REGISTER_AND_DEFER_WITH_OWNER` (which would understate the genuine
architectural fork) and not silently left `DOCUMENT_ONLY` (invalid for a
current-scope finding under V2).

**Remains OPEN.** Per this task's own STOP condition ("If a remaining
current-scope correctness defect exists, report its exact blocker and do
not claim the affected workflow closed"): the GOVERNED generation
workflow (CLI `start --generate` / dashboard `/api/start`) IS closed and
fully verified this task and its predecessor. The LEGACY script's own
governance status is explicitly NOT claimed closed — it remains a real,
disclosed, open item pending a human decision among the three options
named in the Gap Register.

## GAP-V2-003 — no production producer for fields other than `protocol` (REGISTER_AND_DEFER_WITH_OWNER, DEFERRED)

Re-verified (item 1/3): `generation_field_controls.py` governs exactly one
field, by design. Classified `REGISTER_AND_DEFER_WITH_OWNER` per the
explicit test in V2's own "Integration vs Expansion" section — not
required for current Golden-Workflow correctness (the mechanism's own
production-connectivity is proven for one field, closing the capability
island the audit found), and this document does not hide that fact behind
future ownership — it states it plainly.

## GAP-V2-004 — human_gate_state() zero production callers (NOT_APPLICABLE_WITH_EVIDENCE, CLOSED)

Re-verified (item 4, explicit dispatch instruction) with a fresh grep
(`grep -rn "human_gate_state("` — exactly 2 matches, both in
`test_clarification_service.py`) and a fresh confirmation that the
underlying gate MECHANISM (not this projection helper) is production-
consumed: `test_m6_c1_golden_path_connectivity.py`'s
`test_no_declared_protocol_and_no_prior_fact_files_a_real_unresolved_
question` and `test_human_answer_unblocks_generation_and_is_persisted_as_
a_lifecycle_fact` exercise the real block/resume behavior end to end
through a real CLI-shaped and human-answer-shaped path, without ever
calling `human_gate_state()`. Per V2's own explicit allowance, this is not
a defect — classified `NOT_APPLICABLE_WITH_EVIDENCE`, not left
undisclosed.

## GAP-V2-005 — CAP-M6-DISPATCH-001 bookkeeping (SUPERSEDED_WITH_EVIDENCE, CLOSED)

Re-verified (item 5, explicit dispatch instruction) with a fresh
`csv.DictReader` parse of `MASTER_CAPABILITY_STATUS_MATRIX.csv`: the row
already reads `PRIORITY = P2 (downgraded...)`, fixed by the immediately
prior task (`CAP-M6-C1-001`, this same session) — re-confirmed not
regressed, no further action required.

## Summary

```
CURRENT_SCOPE_GAPS_FOUND  = 5  (all 5 either explicitly re-verify-listed, or
  discovered as a direct, evidence-driven by-product of re-verifying them)
CURRENT_SCOPE_GAPS_FIXED  = 1  (GAP-V2-001)
CURRENT_SCOPE_GAPS_OPEN   = 1  (GAP-V2-002, HUMAN_DECISION_REQUIRED)
FUTURE_SCOPE_GAPS_DEFERRED = 1  (GAP-V2-003)
NOT_DEFECTS (re-verified, no action) = 2  (GAP-V2-004 re-verified not a
  defect; GAP-V2-005 already fixed prior to this task, re-confirmed)
```
