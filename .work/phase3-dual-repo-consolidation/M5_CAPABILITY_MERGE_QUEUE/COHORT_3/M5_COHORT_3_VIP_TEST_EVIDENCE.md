# CAP-M5-VIP-001 — Test Evidence

## Correction / honest disclosure on B7B evidence provenance

`git status --porcelain` in `D:/wt/b7b` shows the VIP-04/05/18 capability as
an **uncommitted working-tree modification** against B7B's own HEAD
(`c7c7fa09e9ee8336ba102b4495f4b8808408fe0b`), not a change baked into that
commit itself. `git rev-parse HEAD` for B7B was confirmed identical
(`c7c7fa09e9...`) both before this Cohort's PREFLIGHT and again after all
production edits landed in canonical, and the same uncommitted working-tree
diff was already present and already fully captured (the 175-line diff read
at the start of this Cohort, before any canonical edit) — so nothing in
this session altered B7B's working tree; the capability was already sitting
there, uncommitted, when this Cohort began. Disclosed here because earlier
artifacts in this Cohort described it loosely as "B7B's own source" without
this distinction — the distinction does not change any conclusion (the
evidence is still real, still B7B's own, still independently verified), but
per the project's Evidence Truth Rule it should be stated precisely rather
than left implying a committed state that is not what `git status` shows.

## Step 1 — B7B's own capability, run inside B7B's own frozen worktree (read-only, before trusting the diff)

```
cd D:/wt/b7b
python -m pytest dv_harness_tests/test_vip_capability_extraction.py -k "synopsys or vendor_intermediate or vendor_marker" -v
```
Result: **4 passed** (`test_real_synopsys_usb_svt_naming_convention_classifies_as_transaction`,
`test_inheritance_walks_through_a_fully_indexed_vendor_intermediate_base`,
`test_inheritance_falls_back_to_vendor_marker_when_intermediate_base_is_unindexed`,
`test_vendor_marker_table_covers_the_real_synopsys_intermediate_base_layer`).

```
cd D:/wt/b7b
python -m pytest dv_harness_tests/test_vip_capability_extraction.py -v
```
Result: **17 passed** — B7B's full own suite for this module, no self-regression.
B7B `HEAD = c7c7fa09e9ee8336ba102b4495f4b8808408fe0b` (unchanged before/after).

## Step 2 — merged canonical, focused suite

```
cd D:/DV/Task/L5_DGVA
python -m pytest dv_harness_tests/test_vip_capability_extraction.py -v
```
Result: **17 passed** — identical pass count/names to B7B's own run (9
pre-existing canonical tests + 4 new VIP-04/05/18 tests + 4 other
pre-existing CLI/error-path tests = 17 total, matching exactly).

## Step 3 — real downstream caller regression

```
python -m pytest dv_harness_tests/test_vip_callback_hook_extraction.py dv_harness_tests/test_vip_config_field_usage_coverage.py dv_harness_tests/test_scenario_pattern_command_txt_correspondence.py -v
```
Result: **53 passed, 0 failed** — every real consumer identified in the
caller sweep (`vip_callback_hook_extraction.py`,
`vip_config_field_usage_coverage.py`,
`scenario_pattern_command_txt_correspondence.py`) regresses clean.

## Step 4 — Cohort 1/2/TOPTB-001 preservation regression

```
python -m pytest dv_harness_tests/test_env_manifest_fact_sources.py dv_harness_tests/test_amba_fabric_generator.py dv_harness_tests/test_create_environment_verification_architecture.py dv_harness_tests/test_soc_environment_composer.py dv_harness_tests/test_reference_uvm_dut_top_integration_manifest.py -q
```
Result: **108 passed, 0 failed** — no cross-cohort regression from this
Cohort's edit.

## Step 5 — Constitution/Anti-Drift gate

```
python -c "from dv_harness import constitution_gate; print(constitution_gate.check_constitution_intact('.'))"
```
Result: `ConstitutionCheckResult(status='PASS', reasons=[])`.

## Step 6 — source integrity re-check (all 5 frozen sources)

| Source | HEAD before | HEAD after | Working-tree status | Verdict |
|---|---|---|---|---|
| Parent (`DV_Agent_Harness_L5`) | `3e9dd736...` | `3e9dd736...` | pre-existing untracked/status, unrelated to this file, unchanged | UNCHANGED |
| v50 | `f3fd1732...` | `f3fd1732...` | pre-existing untracked/status, unrelated to this file, unchanged | UNCHANGED |
| B7A | `7b2a65a4...` | `7b2a65a4...` | 1 pre-existing untracked file (`rtl_filelist_parser.py`, unrelated to this Cohort) | UNCHANGED |
| B7B | `c7c7fa09...` | `c7c7fa09...` | 2 pre-existing modified files, both the source of this Cohort's own evidence, present before this Cohort began | UNCHANGED |
| B8 | `c9cdd06c...` | `c9cdd06c...` | 1 pre-existing modified file (`amba_fabric_generator.py`, the already-disclosed Cohort 2 finding, unrelated to this Cohort) | UNCHANGED |

No `Edit`/`Write` tool call in this Cohort touched any path under
`DV_Agent_Harness_L5` (outside `L5_DGVA`), `v50`, `D:/wt/b7a`, `D:/wt/b7b`,
or `D:/wt/b8` — every production edit targeted `D:/DV/Task/L5_DGVA` only,
confirmed via distinct-inode filesystem check (`stat`) on the one file both
canonical and B7B share by name.

## Summary

`UNKNOWN_REGRESSION_FAILURES = 0`. `SIGNATURE_BREAKS_RESOLVED` = 1 (the
`classify_by_inheritance()` return-arity change, resolved by direct
adoption with zero real external callers, not by an adapter — see
Compatibility Plan). `SOURCE_CAPABILITY_LOSS = 0`.
