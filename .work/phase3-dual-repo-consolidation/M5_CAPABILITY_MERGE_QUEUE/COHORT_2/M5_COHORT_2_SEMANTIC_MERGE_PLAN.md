# M5 Cohort 2 -- Semantic Merge Plan

## CAP-M5-ARCH-003 (`amba_fabric_generator.py`) -- EXECUTED this wave

1. **Identify source behavior** -- B8's real, additive ARCH-04/ARCH-12 wire:
   `cross_check_fabric_graph()` + `FabricGraphMismatchError` + two new
   `environment_manifest.json`/`fabric_topology.json` fields. Confirmed via
   full unified diff read (not summarized/assumed).
2. **Identify Canonical behavior** -- unchanged prior to this wave; Parent/
   v50 both byte-identical to canonical for this file.
3. **Semantic conflict found before writing any test**: B8's own call site
   (`self.env(t, fabric, fabric_graph_info)`) does not match B8's own
   `env(self, t, fabric)` signature. Confirmed as a REAL defect (not a
   misreading) by running B8's own unmodified test suite inside B8's own
   worktree -- 4/15 tests fail with `TypeError`, reproducibly.
4. **Write/update focused tests expressing the verified union** -- 5 new
   tests authored (B8 shipped none): `test_generate_without_fabric_graph_
   reports_not_supplied` (regression safety net for the pre-existing path),
   `test_cross_check_fabric_graph_succeeds_when_endpoints_match`,
   `test_cross_check_fabric_graph_raises_on_missing_endpoint`,
   `test_generate_with_fabric_graph_end_to_end` (the test that would have
   caught B8's own defect), `test_generate_with_fabric_graph_mismatch_
   raises_before_writing_files`.
5. **Implement semantic merge** -- code applied via 3 surgical edits
   (import block; `FabricGraphMismatchError`/`cross_check_fabric_graph`
   inserted before `ScoreboardMatrixError`; `generate()`'s body extended)
   with the call-site defect corrected: `env(t, fabric)` kept at 2 args.
6. **Run focused tests** -- `test_amba_fabric_generator.py`: 20/20 pass.
7. **Run affected caller tests** -- `test_amba_fabric_analysis.py`,
   `test_amba_port_registry.py`, `test_amba_route_transform_predictor.py`:
   192/192 pass. Full keyword sweep `-k "amba_fabric or amba_port or
   address_map_integrity or system_resource_inventory"`: 262/262 pass.
8. **Run schema/contract tests** -- N/A this capability (no JSON Schema
   file backs `environment_manifest.json`'s ad-hoc structure the way
   `env_manifest.schema.json` did in Cohort 1 -- confirmed by absence, not
   assumed: no `amba_fabric_*.schema.json` exists under `dv_harness/schemas/`).
9. **Run Constitution/Anti-Drift** -- PASS, 0 reasons.

Result: CLOSED. See `M5_COHORT_2_TEST_EVIDENCE.md` for the full run log
and `M5_COHORT_2_FINAL_REPORT.md` for the closure summary.

## CAP-M5-ARCH-001 / CAP-M5-ARCH-002 -- NOT executed this wave

Diffs generated and sized (see `M5_COHORT_2_SOURCE_BEHAVIOR_MATRIX.csv`)
but steps 1-9 above not yet performed. `create_environment.py` carries
the instruction's own explicitly-flagged high-risk status (known
hard-coded mode-string defect, `M1_KNOWN_SOURCE_B_DEFECT_DISPOSITION.md`)
and deserves the same read-fully-before-touching discipline just applied
to ARCH-003, not a rushed pass. `soc_environment_composer.py` is a
genuine 3-way merge (Parent 150 lines, v50 11 lines, B8 103 lines) --
the largest and most contested target in this cohort. Both deferred to
a follow-up Cohort-2 session, disclosed rather than silently skipped.
