# SPEC-1 — Wire Track A / Track B into the real SYSTEM_LEVEL gates

Status: **DONE** (with one honestly-scoped deferral, section 6)

## 1. Independent re-verification of the gap (before building anything)

Every claim in the task brief was re-checked with my own commands, not taken
from the audit:

| Claim | Command | Result |
|---|---|---|
| No SYSTEM_LEVEL gate imports any dv_harness analysis | `grep -rln "dv_harness" tools/verification_flow/system_level_*.py` | **exit 1, zero matches** — all 11 gate scripts were pure JSON-shape checks |
| Track A composes blind | `grep -n "^import\|^from" dv_harness/uvm_generator/soc_environment_composer.py` | only `json`, `pathlib`, `typing`, `.generator` — no Track-B import |
| The contention gate trusts the agent's own list | read `tools/verification_flow/system_level_resource_contention_gate.py` | 9 lines; `shared = set(d.get('shared_resources',[]))` — a hand-typed `[]` made every check vacuous |
| The composition gate trusts agent-typed compatibility | read `tools/verification_flow/system_level_composition_gate.py` | `interface_compatibility`/`clock_reset_compatibility` checked only for the literal string `"PASS"` |
| Track B is real and CLI-only | `grep -rn "analyze_selected_subsystem_resources\|build_cross_subsystem_resource_analysis\|apply_active_driver_conflict_rule" --include=*.py .` | callers were `cli.py:2543`, `system_resource_registry.py:1219`, and tests — nothing in `engine.py`, nothing in `tools/` |

Gap confirmed real on all five points.

## 2. What was built

### The wire (one function, no parallel mechanism)

`dv_harness/system_resource_inventory.py` gained
`real_cross_subsystem_findings(root, selected=None)`. It adds **no new
analysis**: it calls the existing `analyze_selected_subsystem_resources()`
front door (which itself goes through `subsystem_discovery.
require_explicit_selection()`, so SYS-1's refusal to analyze an unselected set
is not bypassed) and flattens the SYS-9..SYS-14 result to the facts a verdict
needs — `driver_conflicts`, `automatic_integration_allowed`,
`stopped_resource_ids`, `held_resource_ids`, `blocking_decisions`,
`shared_resource_ids`, and SYS-12's `preferred_model` text.

Subsystem names default to the **real registered set**
(`environment_mode_router.read_registered_subsystem_names()`) — harness
evidence, never the agent's claim.

Alongside it, two pure comparison functions:
`crosscheck_declared_contention_plan()` and
`crosscheck_declared_composition()`.

### (b) The two gates now call it

`tools/verification_flow/system_level_resource_contention_gate.py`
— layer 1 (the original 9-line shape check, exit codes 2/3) is unchanged and
still runs first. Layer 2 runs the real analysis and FAILs (exit 4) on:
- `ACTIVE_DRIVER_CONFLICT_UNRESOLVED` — the real analysis STOPPED or HELD
  automatic integration. No arbitration policy an agent can type gets past
  this; ownership is a human decision.
- `SHARED_RESOURCES_CONTRADICTED` — the plan declares **no** shared resources
  while the real analysis found SAME_PHYSICAL / SHARED_LOGICAL relationships
  between the composed subsystems. This is the hand-typed "all clear" case.

`tools/verification_flow/system_level_composition_gate.py`
— layer 1 (exit codes 2..10) unchanged and still first. Layer 2 runs the real
analysis over the subsystems **this composition names** and FAILs (exit 11)
with `ACTIVE_DRIVER_CONFLICT_UNRESOLVED` when they carry an unresolved
active-driver ownership conflict, whatever the agent's
`interface_compatibility: "PASS"` strings say.

Both scripts reach `dv_harness` via `DV_HARNESS_PACKAGE_ROOT` (which
`gates.run_gate()` already sets on every gate subprocess) with the
`parents[2]` fallback, and resolve the **project** root from the CWD (which
`run_gate()` already sets to the real project root, `cwd=str(root)`). **No
change to `dv_harness/gates.py` was needed** — deliberately, since three
concurrent passes are editing that file.

**Bounded so a gate can never crash a stage.** `run_gate()` runs every gate
with `subprocess.run(..., timeout=30)` and does **not** catch the resulting
`TimeoutExpired` — an unbounded analysis inside a gate would turn a stage
evaluation into a crash rather than a FAIL. (This is not theoretical: the
full-suite run caught exactly that shape of failure on an *unrelated* gate,
`vplan_writer_validation_gate.py`, under load.) Both gates therefore pass
`budget_seconds=sri.GATE_CROSSCHECK_BUDGET_SECONDS` (20s); overrunning it
yields `ANALYSIS_TIMED_OUT`, which the cross-checks treat as SKIPPED — never
as a clean result. The composer passes no budget on purpose: it is not on a
gate's clock, and skipping the check that stops it composing over a driver
conflict would be the worse failure.

### (a) The composer consults Track B before composing

`compose_soc_environment(entries, manifest, root=None)` gained the optional
`root`. When supplied it calls the **same** `real_cross_subsystem_findings()`
the gates use — one analysis, not two — *before* emitting any file, and raises
the new `CrossSubsystemIntegrationBlockedError` rather than generating a
`soc_tb_top.sv` that instantiates two subsystems whose ACTIVE agents both
drive one SoC port. What the analysis said (including an explicit
`TRACK_B_ANALYSIS_UNAVAILABLE` + reason, or `NOT_CONSULTED` when no root was
given) is written into `soc_composition_manifest.json`'s
`cross_subsystem_analysis`, so a composition is never silently blind again.

Both real call sites now pass their project root:
- `dv_harness/engine.py::_compose_soc_environment_files()` → `self.root`, with
  a new `SOC_COMPOSITION_BLOCKED_PENDING_HUMAN_ARBITRATION` event; logged and
  skipped exactly like every other composition failure there, so it never
  downgrades an already-earned stage PASS.
- `dv_harness/uvm_generator/create_environment.py` SYSTEM_LEVEL_MODE dispatch
  → `root`, error propagating to the caller like `SubsystemModeRequiredError`.

`root=None` (every pre-existing caller and unit fixture) composes byte-
identically apart from the new audit key.

### Documentation

`dv_harness/prompts.py` — both gates' STAGE_INSTRUCTIONS blocks now state the
new FAIL reasons and that a driver conflict is a human decision, not something
to re-word the evidence past. `CLAUDE.md` "Environment Generation Mode" gained
a dated subsection recording the two-track finding and what closed it.

## 3. Human-approval gates: all preserved

- **Active-driver ARBITRATION is untouched.** DETECTION was wired into the
  gates; nothing added picks a winner between two conflicting drivers. Every
  blocking payload carries `human_arbitration_required: true` and SYS-12's
  `SYS12_PREFERRED_MODEL` as text for the human to read. A drift-guard test
  (`test_nothing_here_arbitrates_a_driver_conflict`) greps the new section for
  `resolve_conflict`/`winner`/`arbitrate(`/`auto_resolve` and fails if any
  appears.
- **SYS-39/40's boundary is untouched.** Nothing here generates a system
  `command.txt`, a scenario body, a shared agent or a routing adapter; the new
  code only reads and refuses.
- `HumanApprovalRequiredError`, `ProductionWriteNotAuthorizedError`,
  `ControlPlane.approve` and `_persist_subsystem_registry_entry`'s SIGNOFF
  precondition were not touched.
- No build, regression or LSF submission is triggered anywhere. Every test
  runs against `tmp_path` synthetic fixtures.

## 4. Tests

`dv_harness_tests/test_system_level_track_b_gate_crosscheck.py` — **21 tests,
all passing**. Nothing is mocked: the REAL gate scripts run as subprocesses
(same temp-file/CWD/env shape `run_gate()` uses) against REAL synthetic
subsystem environments whose `env.manifest.json` is written by the REAL
`env_manifest` generator.

The headline test the task asked for:
`test_hand_typed_all_clear_is_rejected_by_the_real_contention_gate` — an
evidence block declaring `"shared_resources": []` and a scenario needing no
policy (a block layer 1 alone accepts, proven by the companion test
`test_the_same_all_clear_block_passes_layer_one_alone`, which runs the
identical block with no project to analyze and gets PASS) is **REJECTED** with
`ACTIVE_DRIVER_CONFLICT_UNRESOLVED` when the real Track-B analysis over the
same two subsystems finds two ACTIVE `svt_axi_master_agent`s bound to
`chip.soc.cpu_axi_m`.

Supporting coverage, all real:
- the fixture really does produce a Track-B conflict through the root-based
  front door (so no gate test can pass vacuously), plus a **passive-second-
  driver negative control** proving the FAILs come from the rule, not the
  fixture;
- a fully-populated plan with an arbitration policy and contention tests
  **still** stops at BLOCKED;
- both gates' original shape checks and their exact exit codes (2/3 and
  2/4/6/7) are unchanged and still fire first;
- UNAVAILABLE is reported as an explicit "not checked" with its reason, never
  a silent clear — including `ANALYSIS_TIMED_OUT` on an impossible budget, plus
  a drift guard that neither gate may call the analysis unbounded;
- the composer refuses over a conflict and leaves **nothing** on disk; records
  the real findings when it does compose; and is unchanged without a root;
- drift guards asserting both gate scripts really import
  `system_resource_inventory`, and that both real composer call sites pass
  their project root.

### Suite runs

- `test_system_level_track_b_gate_crosscheck.py` — 21 passed
- `test_system_level_soc_composition_wiring.py`, `test_system_resource_inventory.py`,
  `test_system_resource_registry.py`, `test_system_topology_analysis.py`,
  `test_subsystem_architecture_and_command_contract.py`,
  `test_subsystem_discovery.py` — **255 passed**
- `test_stage_instructions_gate_completeness.py` — 2 passed
- `test_soc_environment_composer.py` + `test_engine_gates_and_routing.py` —
  255 passed, 1 failed: `test_newly_wired_orphan_gates_pass_with_valid_evidence`
  hit a 30s `TimeoutExpired` on `vplan_writer_validation_gate.py` — a gate this
  pass does not touch, while a second full-suite run was loading the same
  machine. **Re-run in isolation: passed.** Unrelated load flake, not a
  regression from this change; it is, however, what prompted the
  `GATE_CROSSCHECK_BUDGET_SECONDS` guard above.
- the full `dv_harness_tests/` suite — see section 7.

## 5. Files changed

- `dv_harness/system_resource_inventory.py` (the wire + two cross-checks)
- `tools/verification_flow/system_level_resource_contention_gate.py`
- `tools/verification_flow/system_level_composition_gate.py`
- `dv_harness/uvm_generator/soc_environment_composer.py`
- `dv_harness/uvm_generator/create_environment.py`
- `dv_harness/engine.py`
- `dv_harness/prompts.py`
- `CLAUDE.md`
- `dv_harness_tests/test_system_level_track_b_gate_crosscheck.py` (new)

`dv_harness/dashboard.py` was **not** touched (explicitly out of scope), and
neither was `dv_harness/gates.py` — the CWD/`DV_HARNESS_PACKAGE_ROOT`
mechanics `run_gate()` already provides made a change there unnecessary.
Staging was hand-scoped: `dv_harness/cli.py` and the non-mine hunks of
`CLAUDE.md` belong to concurrent passes and were left unstaged.

## 6. Honestly scoped down / deferred

- **Only 2 of the 11 `system_level_*` gates were wired**, as the task
  specified (the two most directly relevant). The other nine remain
  shape-only. Wiring them needs different Track-B outputs
  (`system_topology_analysis` for cross-domain/dependency-graph,
  `system_failure_triage` for deadlock/livelock) and is a separate pass.
- **`system_topology_analysis.reconcile_address_maps()` /
  `compare_clock_reset_domains()` were NOT wired into the composition gate.**
  Reaching them means running `analyze_system_topology()`, i.e. the whole
  SYS-1..SYS-30 pipeline (selection → resources → registry → commands →
  scheduling → topology) inside a gate subprocess that `run_gate()` gives 30
  seconds. That is a real cost/timeout risk I was not willing to take on
  speculation, so this pass wired the resource/ownership half — the half that
  detects the conflict the audit named — and left the address/clock-reset half
  for a pass that can measure it against a real project. Stated here rather
  than implied closed.
- **`shared_resources` name matching stays advisory.** An agent names
  resources in project vocabulary ("DDR", "APB_BUS") while a Track-B resource
  id is `SUBSYS::hierarchy::interface`. A *non-empty* declared list whose names
  do not line up is reported as `unmatched_shared_resource_ids` and does not
  FAIL — failing on that would be a naming heuristic pretending to be evidence.
  Only the flat contradiction (declared **empty** vs. real shared resources
  found) fails.
- **`system_readiness.derive_system_readiness()` was not called from a gate.**
  It needs the SYS-18..38 plan documents as inputs, none of which exist at
  SYSTEM_LEVEL gate time. Its subsystem-readiness half is already reached
  through `require_explicit_selection()` inside the front door this pass uses
  (an environment that is not really on disk makes the cross-check report
  UNAVAILABLE rather than a false clear).

## 7. Commits

- `95d7181` system-level: wire the real cross-subsystem analysis into the gates
  and composer
- `3cbd75c` system-level: name the gate cross-check's import-failure reason
  concretely

Both hand-scoped. `CLAUDE.md`'s other 70 lines (another pass), `dv_harness/cli.py`,
`tools/dut_architecture/build_architecture_model.py` and
`.dv-harness/dut-architecture/architecture_model.schema.json` were left
unstaged, using `git diff > patch` → trim to my hunk →
`git apply --cached --check` → `git apply --cached`.

## 8. Test summary

21/21 new cross-check tests pass; 255/255 across the six directly-related
suites; 132/132 across five adjacent suites (signoff e2e, gate package-root
env, protocol/environment-mode wiring, scheduling plan, regression readiness);
2/2 stage-instruction completeness; 255/256 on
`test_soc_environment_composer.py` + `test_engine_gates_and_routing.py` with
the single failure being an unrelated `vplan_writer_validation_gate.py`
30s-timeout flake under concurrent load that passes in isolation.

A whole-repo `dv_harness_tests/` run (5887 tests) reached 67% before being cut
short by the session's background-task limit. Its progress stream carried
**zero `F` markers and exactly 6 `E`s**, all in one contiguous block around
65%. Those six were tracked down rather than waved off: re-running the
alphabetical band they fall in gives **224 passed, 6 errors**, and the six are
`test_pueue_client.py::TestRealPueueIntegration::*` failing at setup with
`AssertionError: real pueued did not come up` — the external `pueued` daemon is
not running on this machine. Environmental, pre-existing, and unrelated to
anything this pass touched. No `F` anywhere in the 3900+ tests that did run.
