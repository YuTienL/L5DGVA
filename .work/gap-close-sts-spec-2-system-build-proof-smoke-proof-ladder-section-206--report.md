# SPEC-2 — System Build & Proof smoke-proof ladder (spec section 206)

**Status: DONE**
**Tests: 476 passed / 0 failed** (`test_system_build_proof.py` 43 new, plus
`test_uvm_structural_lint`, `test_system_level_track_b_gate_crosscheck`,
`test_system_regression_readiness_and_phase1_report`, `test_connectivity`,
`test_fsdb_report`, `test_system_resource_inventory`,
`test_system_level_soc_composition_wiring`).
**Commit:** `6351788` — `feat(system): drive spec section 206's smoke-proof ladder + system merge check`

---

## 1. Gap re-verified independently (not restated from the audit)

- `grep -rn "smoke_proof\|smoke-proof\|SMOKE_PROOF\|system_smoke" --include=*.py --include=*.md .`
  → **no matches**. Nothing anywhere executed the ladder.
- `dv_harness/system_readiness.py:485` `_build_system_readiness_input()` docstring, read in full:
  *"Build integration at Phase 1 is a question about INPUTS, not about a build: no System-Level
  filelist exists to compile, because writing one is SYS-40."* Confirmed a static metadata rollup.
- `dv_harness/uvm_structural_lint.py` module docstring lists *"package/import dependencies,
  duplicate definitions, duplicate active drivers"* among the concerns it does **not** implement;
  it lints one environment at a time, so a cross-environment duplicate is invisible by construction.
- Tool inventory on this machine, checked live: `verible-verilog-syntax` **present**
  (`C:\Users\peter.lin\bin\verible-verilog-syntax.EXE`); `slang`, `vcs`, `simv`, `fsdbreport`
  **absent**. This is what decides which rungs can really run here.

Gap confirmed real.

## 2. What was built

`dv_harness/system_build_proof.py` (new), plus a CLI verb and a small additive extension to
`uvm_structural_lint.py`.

### 2a. The system merge-collision check — REAL, runs here, needs no simulator

`analyze_system_merge(sources)` parses the merged source set through the **same** verible front end
(`uvm_structural_lint.parse_uvm_file()`); there is no second SystemVerilog parser. Five rules,
matching section 206's own responsibility list:

| Rule | Severity | What it proves |
|---|---|---|
| `DUPLICATE_PACKAGE_DECLARATION` | ERROR | same `package X;` in ≥2 files across the merged set |
| `DUPLICATE_TYPE_DEFINITION` | ERROR | same class / interface / module name in ≥2 files |
| `FACTORY_TYPE_NAME_COLLISION` | ERROR | two differently-named classes registering one factory string |
| `CONFIG_DB_SET_SCOPE_COLLISION` | ERROR | two subsystems `set` one field at overlapping GLOBAL scope |
| `VIRTUAL_INTERFACE_CONFLICT` | ERROR | the same, where a virtual interface type is involved |
| `CONFIG_DB_SET_SCOPE_NOT_STATICALLY_RESOLVABLE` | INFO | a run-time-built scope, disclosed not dropped |

Sources come from the **real** registry (`environment_mode_router.read_registered_subsystem_entries()`),
never a caller's claim, via `subsystem_source_sets(root, names)`.

### 2b. The ladder — each rung calls an existing real mechanism

| Rung | Real mechanism called | Status in THIS environment |
|---|---|---|
| BUILD | `analyze_system_merge()` | **really runs** |
| ELABORATE | `connectivity.run_gate1_elaboration_check()` | NOT_AVAILABLE (no slang/vcs); PASS/FAIL against an injected runner in tests |
| BOOT_RESET_INIT | `connectivity.evaluate_zero_time_connectivity()` / `run_gate2_against_live_simv()` | **really runs** given a `SignalTrace`; else honest NOT_AVAILABLE |
| SHARED_RESOURCE_ACCESS | `system_resource_inventory.real_cross_subsystem_findings()` | **really runs** |
| ONE_SUBSYSTEM | `connectivity.evaluate_transaction_activity_status()` | **really runs** given counts; PENDING when no pattern completed |
| TWO_SUBSYSTEM_INTERACTION | same, + a ≥2-subsystem precondition | same |
| END_TO_END_SCENARIO | caller-supplied completed-scenario evidence | NOT_AVAILABLE by default, naming the SYS-40 boundary |
| WAVE_FSDBREPORT | `fsdb_report.run_fsdbreport()` + `parse_fsdbreport_output()` | **really runs** given an fsdb + binary |
| SCOREBOARD_ASSERTION | `evidence_db` `normalized_evidence` + `golden_scenario.PASS_VERDICTS` | **really runs** |

Aggregate: `SYSTEM_READY` needs **every** rung PASS. Any NOT_AVAILABLE/PENDING →
`SMOKE_NOT_PROVEN` (GF-AT-28: UNKNOWN never becomes READY). Any FAIL → `SMOKE_FAIL`, which
**halts** the ladder — later rungs are `NOT_YET_RUN`, spec section 209's `SMOKE_FAIL → TRIAGE` edge.
Fewer than two source sets, or none on disk, is NOT_AVAILABLE — never a clean merge of nothing
(this repo's own subsystem registry is legitimately EMPTY; the verb correctly exits 2 here).

### 2c. Extended rather than duplicated

Two additive pieces in `dv_harness/uvm_structural_lint.py`, both so the merge check reuses one
parse and one notion of a `uvm_config_db` call:

- `UvmFileInfo.top_declarations` (`TopDeclInfo`: package / interface / module names off the same
  already-parsed tree, using `verible_parser`'s own extraction helpers).
- `config_db_call_sites()` made **public**, returning the `cntxt` / `inst_name` / type / field /
  value slots. The existing private `_config_db_sites()` was refactored onto it — no behaviour
  change, and its 32 tests still pass.

### 2d. CLI

`dv-harness system-smoke-proof [--subsystem N] [--composed-dir D] [--filelist F] [--merge-only]
[--db …] [--system-job-id N] [--fsdb …] [--json]`, and `python -m dv_harness.system_build_proof`,
sharing one `execute_verb` (the `power-intent`/`golden-scenario` convention). Exit 0 SYSTEM_READY,
1 SMOKE_FAIL, 2 SMOKE_NOT_PROVEN.

## 3. Human-approval gates preserved (and asserted, not asserted-in-prose)

- **Generates nothing.** `test_this_module_generates_no_system_artifacts` parses the module's AST
  and asserts it calls none of `compose_soc_environment`, `write_text`, `open`, `mkdir`,
  `submit_job`, `cross_subsystem_scenarios`, `end_to_end_scoreboard`, `system_coverage`.
  SYS-39/40's stop-before-generating boundary is untouched; where a rung needs an artifact only
  SYS-40 may write, the rung says NOT_AVAILABLE *naming that boundary*.
- **Arbitrates nothing.** `test_this_module_never_arbitrates_a_driver_conflict` asserts no
  `resolve_conflict`/`choose_owner`/`select_owner`/`set_owner`/`arbitrate` call and that
  `automatic_integration_allowed` is never written. A DRIVER_CONFLICT FAILS the rung carrying
  `human_arbitration_required: True` and SYS-12's `preferred_model` as text for the human.
  `test_an_unresolved_active_driver_conflict_stops_the_ladder_and_is_not_arbitrated` drives the
  REAL Track-B analysis over a real injected conflict and asserts it STOPS.
- **No production build / regression / LSF / waveform.** Nothing imports `lsf_client`; the WAVE
  rung READS an existing fsdb and its NOT_AVAILABLE reason names the Waveform Dump User Gate.
  All tests run against synthetic fixtures in `tmp_path` and a fake tool on disk.
- `test_it_reuses_the_existing_gates_rather_than_reimplementing_them` asserts each of the nine
  real call sites is still present, so a rung cannot silently grow a parallel implementation.

## 4. Tests (43 new)

Same discipline as `test_uvm_structural_lint.py`: one clean synthetic REGISTERED two-subsystem
project with real, verible-parseable UVM sources, then **one mutation at a time**.

- Clean merge → PASS with 2 real global config_db sets analysed (not "nothing to check").
- Duplicate package / duplicate class / factory-string collision — each injected separately.
- **The headline case:** both subsystems `set` `"pcie_vif"` at global scope `"*"` with different
  virtual interface types → `VIRTUAL_INTERFACE_CONFLICT`, asserted by subject, subsystems and both
  type names in the message. A wildcard-vs-literal overlap (`"*"` vs `"uvm_test_top.env"`) is also
  caught.
- Negative controls that matter: a component-relative `set(this, …)` is **never** reported (a parse
  cannot prove it), two sets inside ONE subsystem are not a merge collision, a run-time-built scope
  is an INFO disclosure not an ERROR, verible unavailable is NOT_AVAILABLE not PASS.
- Ladder: NOT_PROVEN with no tooling; SMOKE_FAIL halting every later rung; the real Track-B
  conflict stopping it; Track-B unavailable reading as "not checked" not "clear"; two-subsystem
  interaction not proven by one subsystem's traffic; a silent monitor FAILing; no completed pattern
  being PENDING not FAIL; the real `connectivity` gate-1 argv reaching an injected runner; a real
  reset-never-deasserts FAIL; a real `fsdbreport` subprocess against a real fake binary written to
  disk; real DuckDB `EvidenceStore` rows for clean / uvm_error / assertion-failure-despite-PASS.
- **Full ladder to SYSTEM_READY**, and then withdrawing exactly one rung's evidence drops it back
  to SMOKE_NOT_PROVEN — so the aggregate is not decorative.
- **Against real generator output:** merging `examples/generated_pcie_uvm_env` and
  `examples/generated_usb_real_evidence_v12` finds exactly **one** collision — both generators emit
  `module tb_top`, a genuine system-merge defect and exactly why Track A's composer emits
  `soc_tb_top.sv` instead — and the composition Track A actually performs (each subsystem's
  env/tests plus one composed top) is reported clean.
- Both CLI entry points driven, `python -m dv_harness.system_build_proof` as a real subprocess.

## 5. Scoped down / deliberately NOT built

| Not built | Why |
|---|---|
| A real system compile/elaborate | needs slang/vcs, absent here. Reported NOT_AVAILABLE by the existing `connectivity` gate, per this project's own convention. |
| Duplicate-VIP and address-conflict detection inside this module | already real elsewhere (SYS-9..SYS-14 `system_resource_inventory`, SYS-28 `system_topology_analysis`). Re-implementing them would be exactly the parallel mechanism the Methodology Consolidation Rule forbids. The SHARED_RESOURCE_ACCESS rung consumes the former. |
| config_db collisions rooted at `this` | a parse cannot resolve where that component is instantiated. Reporting it would make this check's ERROR level untrustworthy; ERROR is reserved for what the sources prove. |
| An engine stage gate / graph node for the ladder | out of the named scope, and `engine.py`/`gates.py`/`tools/verification_flow/*.py` are being modified by concurrent passes this session. The mechanism is reachable from the CLI, from `create_environment`-adjacent code, and as a library call; wiring it into `STAGE_GATES["SYSTEM_LEVEL"]` is a clean, separable follow-up. |
| A Generation Center GUI card | explicitly deferred by the task (`dashboard.py` out of scope). |

## 6. Concurrency handling

`git status` / `git diff` checked before every shared-file edit. `dv_harness/cli.py` and `CLAUDE.md`
were re-inspected immediately before staging and confirmed to contain **only** this pass's hunks
(the concurrent `benchmark-dataset` work had already committed its own). Staged file-by-file, never
a broad `git add`; `.dv-harness/events.jsonl` and other passes' `.work/` reports were left
untouched. `dv_harness/dashboard.py` was not opened.

## 7. Files

- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/system_build_proof.py` (new, ~760 lines)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness_tests/test_system_build_proof.py` (new, 43 tests)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/uvm_structural_lint.py` (additive: `TopDeclInfo`,
  `UvmFileInfo.top_declarations`, public `config_db_call_sites()`)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/cli.py` (`system-smoke-proof` verb)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/CLAUDE.md` (new "System Build & Smoke Proof (2026-09-06)"
  section, including its stated bounds)
