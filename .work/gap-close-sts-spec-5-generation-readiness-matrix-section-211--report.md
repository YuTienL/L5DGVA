# SPEC-5 -- Generation Readiness Matrix (spec section 211)

**Status: DONE**

**Test summary:** `pytest dv_harness_tests/test_generation_readiness.py` -> **28 passed**;
neighbouring suites (`test_golden_flow_readiness.py`, `test_system_level_track_b_gate_crosscheck.py`,
`test_system_resource_inventory.py`, `test_system_topology_analysis.py`, `test_system_build_proof.py`,
`test_subsystem_discovery.py`, `test_qualification.py`) re-run green.

---

## 1. Independent re-verification that the gap was real

Run before writing any code, not taken from the audit hand-off:

```
$ ls dv_harness/generation_readiness.py
ls: cannot access 'dv_harness/generation_readiness.py': No such file or directory

$ grep -rni "generation.readiness" --include=*.py --include=*.md .
(no matches)

$ grep -rn "GF-AT-" --include=*.py --include=*.md .
./.work/gap-close-sts-spec-2-...--report.md:67   (GF-AT-28 ...)
./CLAUDE.md:830                                  (GF-AT-28 ...)
./dv_harness/cli.py:2643                         (GF-AT-28 ...)
./dv_harness/system_build_proof.py:87            (GF-AT-28 ...)
./dv_harness_tests/test_system_build_proof.py:489
```

Section 211 of `CLAUDE_DV_Agent_Harness_L5_SPEC_TO_SYSTEM_UVM_COMPLETE.md` (line 7027) prints a
twenty-row table with the columns `Capability | Status | Existing Reuse | Evidence | Gap | Priority
| Action` and **every cell empty**. Nothing in this repo had ever rendered it. Gap CONFIRMED REAL.

## 2. What was built

### `dv_harness/generation_readiness.py` (new, 1541 lines)

Section 211's matrix as a real artifact, following `golden_flow_readiness.py`'s pattern exactly
(ROWS tuple of frozen row-specs each declaring dotted-path `fact_source` readers, an import-time
check that the declared labels equal the SPECIFICATION's own transcribed list, a separate PROBES
table so no row can exist without a probe and no probe can be orphaned,
`assert_fact_sources_resolvable()`, borrowed status vocabulary, Action via the real
`inference.next_best_action()` catalog branch) -- **as a separate module**, never as a second
differently-shaped matrix inside `golden_flow_readiness.py`.

**Why separate is not a parallel mechanism** (and a test asserts it stays so):

| | `golden_flow_readiness.py` (section 47) | `generation_readiness.py` (section 211) |
|---|---|---|
| Question | did this project's twenty GOLDEN FLOW STAGES connect with evidence | does this FACTORY have the generation capability each Flow A / Flow B rung needs |
| Rows | `models.Stage` values | capabilities |
| Columns | 5 (Stage/Status/Evidence/Gap/Next-Best-Action) | 7 (adds Existing Reuse, Priority) |
| Sources | stage RUN STATE: state.json, gate counts, LSF jobs, coverage summaries, signoff | GENERATION ARTIFACTS: env.manifest.json layers, protocol capability registry, subsystem registry, SYS-1..40 analysis |

`test_this_matrix_is_not_the_section_47_matrix` asserts the column sets differ and that neither
module's rows declare the other's fact sources (section 47 reads `dashboard.*`; section 211 does
not, and reads `system_resource_inventory.*`, which section 47 does not).

**Two axes per row, folded with STRICT worst-wins.** CAPABILITY (does the named mechanism import
here) is decided by resolving the row's own declared dotted paths -- 62 of them, all resolving --
so a row whose backing mechanism has not landed renders BLOCKED naming the missing path, never a
fabricated status. PROJECT EVIDENCE is what the row's real reader returned over this root. The fold
is strict (`worst_readiness()`), NOT the softer many-row mixing rule: a present capability with no
project input reads **UNKNOWN, never PARTIAL** -- GF-AT-28, and PARTIAL would read as progress that
has not happened. This was corrected mid-build: the first version used the mixing rule and produced
17 PARTIAL rows for a repo with no generation artifacts at all, which was misleadingly optimistic.

**Real per-row readers, reused not re-derived:**

| Rows | Real reader |
|---|---|
| 1 Spec Parsing / Requirement IR | `requirement_contract.analyze_requirement_contract_set` / `derive_status`, `doc_extraction.DocumentIndex` |
| 2 DUT Discovery | `env_manifest` `dut_facts.rtl` layer (+ `connectivity.capture_dut_instance_tree`) |
| 3 Protocol / VIP Mapping | `protocol_capability.capability_rows()`, `protocol_router.resolve_protocol` |
| 4 VIP API Retrieval | `vip_api_card.validate_vip_api_usage`, `vip_config.vip_release`/`user_guide_refs` layers |
| 5 UVM Architecture | `uvm_generator.create_environment`, `uvm_structural_lint.lint_uvm_environment`, `verible_parser.get_verible_version`, `env_topology.component_hierarchy` |
| 6 Scenario / Negative / CSR / IRQ | `sys_regmap.mode_determining_bits`, `init_seq.directed_test_steps`, `dut_facts.registers` layer |
| 7 Checker / Coverage / Assertions | `coverage_analysis.identify_holes`, `state_machine_checks`, `env_topology.testplan_correspondence` |
| 8 Config / Build / Compile-Fix | `uvm_generator.run_profile`, `makefile_to_run_profile`, `config_variant_coverage`, `env_topology.config_db_trace` |
| 9 Single-Test Proof | `qualification.tier_index` / `map_to_system_level_state` over the real subsystem registry |
| 10 Subsystem Inventory | `subsystem_discovery.discover_subsystem_candidates`, `environment_mode_router.read_registered_subsystem_entries` |
| 11 Shared Resource / VIP Resolver | `system_resource_inventory.real_cross_subsystem_findings()` |
| 12 Active Driver Ownership | `system_resource_inventory.apply_active_driver_conflict_rule` (via the same front door) |
| 13-16 Topology / Address-Clock-Reset-IRQ / Command Integration / Virtual Sequencer | ONE `system_topology_analysis.analyze_system_topology()` document, run once per report, read four ways |
| 17-19 System Scenario / Correlation Scoreboard / Cross Coverage | `system_scheduling_plan.probe_composer_boundary()` -- CALLS the three `soc_environment_composer` stubs and records that they still raise |
| 20 System Build / Smoke Proof | `system_build_proof.subsystem_source_sets()` + `SMOKE_NOT_PROVEN` |

The `Priority` column is transcribed from section 213 (GENERATION PRIORITIES), not judged: each row
carries a `priority_basis` quoting the P0/P1 line it came from, and where section 213 covers a row
only partly (row 6's CSR/IRQ-automation half is P1 while its Scenario half is P0) the basis says so
rather than the table quietly picking one.

### `dv_harness/cli.py` -- `dv-harness generation-readiness [--json] [--no-deep]`

Added alongside `golden-flow-readiness`, following its exact convention (one shared implementation
with `python -m dv_harness.generation_readiness` via `execute()`, exit 2 unless every row is READY).
Applied as a hand-scoped patch against a file two other concurrent passes were editing; re-checked
`git diff --stat` immediately before and after.

### `dv_harness_tests/test_generation_readiness.py` (new, 566 lines, 28 tests)

The headline test builds a **REAL two-subsystem project on disk** by IMPORTING (not copying) the
fixture `test_system_level_track_b_gate_crosscheck.py` already owns -- whose `b_active=True` form
puts two ACTIVE AXI masters on ONE SoC CPU port -- and asserts:

* the ownership row is **BLOCKED off the REAL SYS-9..SYS-14 analysis**, carrying
  `automatic_integration_allowed=False`, `HUMAN ARBITRATION REQUIRED`, SYS-12's real
  `preferred_model` text, and the explicit "does not pick a winner" statement;
* the **passive-second-driver negative control** reads READY with no gap and no Action, so the
  BLOCKED above is the rule firing and not a fixture artifact;
* rows 13-16 match the REAL `analyze_system_topology()` document field for field
  (`topology_clean`, `address_regions`, `address_conflicts`, `clock_reset_conflicts`,
  `system_commands`, `blocking_collisions`, the selected subsystem names);
* demoting one registry entry to `COMPILE_QUALIFIED` in the REAL registry file flips the
  Single-Test Proof row to PARTIAL naming it, via the real `qualification` ladder;
* env.manifest.json layers surface the **GENERATOR's own** `NOT_AVAILABLE` reason text verbatim
  (generated by a real `env_manifest.generate_and_write()` run);
* an unresolvable `fact_source` renders that row BLOCKED naming the missing dotted path;
* a raising probe still yields its mandatory row (20 rows always);
* `--no-deep` reports NOT_RUN with its reason rather than a guessed Flow-B status;
* both entry points run as **real subprocesses** and emit all twenty of section 211's labels.

Two read-only tests snapshot the filesystem before and after and assert **nothing is written** --
into an empty project (no `.dv-harness/` tree is minted) and into a real two-subsystem project
where the deep SYS-1..SYS-30 chain really runs.

### `CLAUDE.md`

One new `## Generation Readiness Matrix (2026-09-06)` section, following the file's existing
convention (what the gap was, why this is separate from section 47's matrix rather than an
overload, where the rows land, what is deliberately bounded, what the tests prove).

## 3. Human-approval gates: unchanged

* Nothing calls `ControlPlane.approve`, and no `HumanApprovalRequiredError` /
  `ProductionWriteNotAuthorizedError` path is touched.
* SYS-39/40's stop is not crossed: rows 17-19 report the composer boundary as the boundary (that is
  WHY they are BLOCKED), and `system_command_plan.assert_no_emitted_artifacts()` is named in the
  Command Integration row's basis as the boundary in code.
* Active-driver-conflict **ARBITRATION is untouched**. Only DETECTION is reported. The row's own gap
  cell says `HUMAN ARBITRATION REQUIRED ... This harness detects the conflict and does not pick a
  winner`, the Action string says the same, and the matrix-level `authorizes` field states the
  report "never arbitrates an active-driver ownership conflict". A test asserts all of it.
* No build, regression, elaboration, simulation or LSF submission is ever started. The section 206
  ladder is reported as having real sources but explicitly `ladder NOT_RUN by this report`
  (`SMOKE_NOT_PROVEN`), with a test asserting that.
* There is deliberately **no stage gate** for this matrix -- a gate passing on a capability nobody
  exercised would be worse than none.

## 4. What this reports on the real repository today

```
$ dv-harness generation-readiness --no-deep
BLOCKED -- 0 ready / 2 partial / 3 blocked / 15 unknown, of 20 rows.
Flow A (spec -> subsystem UVM): PARTIAL   Flow B: BLOCKED
Registered subsystems: (none)
Cross-subsystem analysis: TRACK_B_ANALYSIS_UNAVAILABLE (FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE)
```

Honest and correct: this harness repo has no multi-subsystem project of its own and no
env.manifest.json at the canonical path, so most rows are UNKNOWN with the real reason. The two
PARTIAL rows are real findings (3 of 11 protocols are `GENERIC_SKELETON_ONLY`; verible resolves but
no component hierarchy has been captured). The three BLOCKED rows are the composer's real,
deliberate NotImplementedError boundary.

## 5. Deferred / not built

Nothing from this gap's brief was dropped. Two bounded choices worth naming:

1. **Row 1 (Spec Parsing / Requirement IR)** has no canonical persisted artifact path in this repo,
   so its project axis is a fixed honest UNKNOWN naming what would make it READY. It deliberately
   does NOT read a stage status and call that requirement evidence -- that would both fabricate the
   row and duplicate section 47's `requirement_extraction` row.
2. **The section 206 ladder is not executed** by this report, by design (see above). The row reports
   whether it HAS real merged sources to run over.

Out of scope by instruction and untouched: `dv_harness/dashboard.py` (section 214's GUI Generation
Center card).
