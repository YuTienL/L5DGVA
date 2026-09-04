# SYS-9..SYS-14 — cross-subsystem resource inventory, duplicate VIP/agent detection, relationship classification, active-driver conflict rule, shared-VIP promotion, ownership preservation

**Verdict: DONE**

Commit `69657a6` on `gap-close/env-manifest-fact-sources`.

## Audit re-verified before building

Re-checked with my own greps rather than trusting the handed-down finding:

- `grep -rn "SAME_PHYSICAL_RESOURCE|SHARED_LOGICAL_RESOURCE|MONITOR_ONLY_DUPLICATE|CONFIGURATION_CONFLICT|DRIVER_CONFLICT|OWNER_SUBSYSTEM|owner_subsystem" --include=*.py .` → **zero hits** repo-wide. SYS-11's seven-class vocabulary and SYS-9's OWNER_SUBSYSTEM field did not exist.
- `dv_harness/connectivity.py:2404-2409` `MATRIX_COLUMNS` — 11 columns, none subsystem-identifying. Confirmed.
- `verify_matrix_self_check_identity()` (`connectivity.py:2796`) takes exactly one `rows` list. Confirmed closed-world.
- `bind_target` in `connectivity.py` is read only for rendering/hierarchy grouping — no uniqueness assertion anywhere. Confirmed.
- `.dv-harness/soc-composer/` still holds only the three `*_template.json` files; the real `subsystem_environment_registry.json` is legitimately absent. Confirmed.
- Prior steps in this sequence: `982b918` (SYS-1..4, `subsystem_discovery.py`) and `22070c1` (SYS-5..8, `subsystem_architecture_analysis.py` + `subsystem_command_contract.py`) are real and are what this step builds on.

## What changed

### New — `dv_harness/system_resource_inventory.py` (1913 lines)

Structurally new because every function in it holds N subsystems' evidence at once and has no single-subsystem home. It **imports and composes** the existing primitives; it copies none of them:

| Reused primitive | What it answers here |
|---|---|
| `connectivity.verify_matrix_self_check_identity()` | the WITHIN-one-subsystem arithmetic, run per subsystem, verdict carried not recomputed |
| `connectivity.find_active_bind_target_collisions()` (new, see below) | SYS-12 within one matrix |
| `connectivity.find_amba_clock_reset_ports()` | SYS-9's CLOCK/RESET and SYS-10's clock/reset signal, from real RTL ports |
| `connectivity.classify_amba_protocol()` output (`protocol` column) + `determine_role_from_port_direction()` output (`role`) | the STRUCTURAL branch of resource-type classification |
| `subsystem_command_contract` resource-id namespace + `required_resources[].access` | SYS-10's driver-ownership signal (the command-behaviour axis) |
| `inference.score_confidence()` | SYS-9's CONFIDENCE — no second scorer |
| `amba_fabric_generator.parse_addr()` | every address, with `compute_address_regions()`'s exclusive-end convention |
| `source_authority.resolve_conflict()` | CONFIGURATION_CONFLICT escalation |
| `subsystem_architecture_analysis.analyze_selected_subsystems()` | the whole SYS-1/SYS-5..8 front half of the front door |

Key design points:

- **SYS-9**: 16 fields, `OWNER_SUBSYSTEM` stamped from the source the row was read from. `SHAREABLE`/`EXCLUSIVE`/`CLOCK`/`RESET`/`ADDRESS DOMAIN` are derived with a recorded basis and three-valued where the third value matters (`SHAREABLE_VIA_SYSTEM_SHARED_AGENT`; a `COARSE` address domain that is reported but never compared across subsystems).
- **SYS-10**: all ten of the requirement's own signals get AGREE/DISAGREE/UNKNOWN with a basis. `NAME_DERIVED_SIGNALS` / `DISCRIMINATING_SIGNALS` make "do not decide duplicates by class names alone" a data structure, and deliberately exclude `role` and `clock_reset` from identification (two values / one subsystem-wide name would make every AXI master pair look duplicated).
- **SYS-11**: seven classes, most-specific-first, with the INDEPENDENT veto restricted to the logical signals (differing hierarchy paths across two independently-named trees are weak evidence of difference; differing protocols or disjoint address domains are not). `SHARED_LOGICAL` requires a real address-range overlap plus a second logical signal.
- **SYS-12**: applies across subsystems and within one. `INTEGRATION_STOPPED` for a proven DRIVER_CONFLICT, `INTEGRATION_HELD` for an unproven-but-both-active pair. `SYS12_PREFERRED_MODEL` is carried as planning text only.
- **SYS-13**: all three of the requirement's clauses gated; every verdict is `recommendation_only: True` with `implementation_phase: "SYS-40"`.
- **SYS-14**: preservation is a per-resource decision with a reason (not vacuous), `refactoring_proposed: False` per resource, and `apply_ownership_preservation()` **raises** if a subsystem-specific protocol VIP ever reaches the promotion set.

### Extended — `dv_harness/connectivity.py` (+45, no deletions)

`find_active_bind_target_collisions(rows)` — every `bind_target` claimed ACTIVE by more than one row of ONE matrix. Placed here (not in the new module) because matrix-row semantics, `NO_VIP_MARKERS` and `ACTIVE_INTERFACE` live here, and every single-subsystem caller can now use it. It **reports** rather than raises: a duplicate active claim is a real finding a human resolves by deciding ownership, and raising would make it unreportable by the cross-subsystem layer that must list them all at once.

### Extended — `dv_harness/cli.py` (+49, no deletions)

`dv-harness system-resource-inventory --select A --select B [--knowledge-center] [--command-inventory CSV] [--json]`. Goes through `subsystem_discovery.require_explicit_selection()`, so SYS-1's refusal is not bypassed. Exits 2 while SYS-12 has stopped or held any resource, or while the selection is inadmissible.

## Scope boundary (SYS-39 / SYS-40) — asserted, not claimed

No System-Level UVM source, System command.txt, System Virtual Sequencer, shared agent or command routing/adapter is generated anywhere; no subsystem environment is modified. Three tests enforce it:

- `test_a_full_run_writes_nothing_anywhere` — byte-for-byte tree snapshot across a full analysis + report.
- `test_the_report_contains_no_uvm_source_or_command_txt_content` — line-anchored SystemVerilog tokens.
- `test_the_soc_composers_cross_subsystem_stubs_still_raise` — `cross_subsystem_scenarios()` / `end_to_end_scoreboard()` / `system_coverage()` still `NotImplementedError`.

## Test summary

**60 new tests in `dv_harness_tests/test_system_resource_inventory.py`, all passing; 440 passing across the nine related suites (connectivity, connectivity_check, subsystem_discovery, subsystem_architecture_and_command_contract, system_level_soc_composition_wiring, environment_mode_router, confidence_vocabulary_separation, source_authority, env_manifest_fact_sources).**

### Full-suite run (4309 tests) — 7 failures, all traced and none caused by this change

The whole `dv_harness_tests` suite was also run. Seven tests failed; each was chased down rather than assumed unrelated:

- `test_cli_pueue.py` — 5 failures, all `assert rc == 0`. `pueue status` on this machine returns *"Failed to connect to the daemon on 127.0.0.1:6924. Did you start it?"* — the `pueued` daemon is not running. An environment condition; the daemon was deliberately not started.
- `test_dashboard_interactive.py::test_start_loop_true_advances_through_multiple_stages_in_background` — `TimeoutError: timed out` on a real HTTP dashboard socket.
- `test_debug_flow_memory.py::test_a_successful_promotion_records_the_sha_and_no_failure_status` — `NOTHING_TO_COMMIT` vs `COMMITTED` on a memory-vault git commit, while a concurrent workstream was actively committing memory-CLI changes into this same repo (`d264449 memory(cli): give the new resync-notes subcommand its just recipe`).

**Both of the last two pass when re-run in isolation** (`2 passed in 93.94s`), so they are concurrent-load flakiness, not regressions. `grep -c "connectivity|system_resource_inventory|system-resource-inventory"` over all three failing test files returns **0, 0, 0** — none of them can reach anything this commit changed. This change is additive only (+3130, −0): a new module, a new test file, one new function in `connectivity.py` with no caller inside that module, and one new CLI subparser plus its dispatch branch.

Every fixture is synthetic and built in a `tmp_path`. The suite is deliberately not a happy path — the cases carrying it:

- two subsystems both ACTIVE on one bind target, **with a test asserting each subsystem's own `verify_matrix_self_check_identity()` passes 1=1 while the duplicate stands** (the audit's exact scenario);
- one active + one passive on one interface → `SAME_PHYSICAL_RESOURCE`, not a conflict;
- two passive monitors → `MONITOR_ONLY_DUPLICATE`, automatic integration still allowed;
- one physical resource configured differently → `CONFIGURATION_CONFLICT`, escalated as `UNDECIDABLE_SAME_AUTHORITY` through the real `source_authority`;
- a driver conflict outranking a simultaneous configuration disagreement (both true, most specific wins, the other carried);
- **genuinely overlapping address ranges** across two independently-declared SoC maps (`0x40000000+0x10000` vs `0x40008000+0x10000`) → `SHARED_LOGICAL_RESOURCE` with the exact overlap interval asserted;
- disjoint ranges → `INDEPENDENT_RESOURCE`, not UNKNOWN;
- a COARSE domain never counted as agreement;
- **a pair whose only agreeing signal is the VIP class name** → `UNKNOWN` / `NAME_EVIDENCE_ONLY`, HELD not integrated, and `BLOCKED_PENDING_EQUIVALENCE` at promotion with "matching names are insufficient";
- two ACTIVE rows inside ONE matrix (the new connectivity primitive), plus the negative cases (active+passive, no-VIP, empty bind target);
- a PCIe VIP that must never be promoted, and the raise when a forged promotion list contains one;
- the real CLI verb driven as a subprocess, exiting 2 with the SYS-12 stop in its output;
- drift guards holding `SYS9_FIELDS` and `IDENTITY_SIGNALS` to the requirement's own 16- and 10-item sentences, the seven SYS-11 classes to their names, `SHARED_SOC_INFRASTRUCTURE_TYPES` to SYS-13's own list, and CONFIDENCE to `inference.score_confidence()` rather than a fourth confidence vocabulary.

## Concurrency note

`dv_harness/engine.py` was found already staged in the index by concurrent work partway through this session; it was `git restore --staged`d out before committing. The commit contains exactly four files (+3130, −0), and `git diff` on `connectivity.py` and `cli.py` was inspected hunk-by-hunk beforehand to confirm each carried only this effort's additions.

## Not in this step (next SYS steps' scope)

SYS-15's `SYSTEM_RESOURCE_REGISTRY`, SYS-16's Subsystem Integration Matrix and SYS-17's VIP/Agent Deduplication Matrix are the next step's deliverables. This step's outputs are shaped to feed them directly (`promotion_evaluation`, `ownership_preservation`, and the per-pair relationship records carry every column SYS-17's table asks for), but no registry file is created and neither mandated table is rendered here.
