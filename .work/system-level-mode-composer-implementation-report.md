# SYSTEM_LEVEL_MODE Composer Implementation Report

## What was built

`dv_harness/uvm_generator/soc_environment_composer.py` is the first real
generator code behind SYSTEM_LEVEL_MODE. Before this change,
`WORKFLOW_MANIFEST.json` claimed `"system_level_scoreboard_composer": true`
and `"system_level_coverage_composer": true`, and
`SOC_SYSTEM_LEVEL_COMPOSER.md` documented a
`soc-system-level-env-composer` -> `cross-subsystem-sequence-planner` ->
`system-level-scoreboard-composer` -> `system-level-coverage-composer`
pipeline, but `dv_harness/uvm_generator/generator.py` had zero occurrences
of `system_level`/`soc_tb_top`/`cross_subsystem` anywhere, confirming the
audit finding: SYSTEM_LEVEL_MODE was a real, code-backed *gate*
(`tools/verification_flow/subsystem_environment_registration_gate.py`,
`tools/real_env/system_level_validator.py`, `dv_harness/dashboard.py`'s
`_environment_mode_selected()`/`_environment_mode_policy()`) with no
generator behind it.

The new module exposes `compose_soc_environment(subsystem_registry_entries:
list[dict], manifest: dict) -> dict[str, str]`, the same return shape as
`UVMEnvironmentGenerator.generate()`. It:

1. **Reads the real registry format.** Confirmed by reading
   `tools/real_env/system_level_validator.py` and
   `tools/verification_flow/subsystem_environment_registration_gate.py`:
   the real runtime file is
   `.dv-harness/soc-composer/subsystem_environment_registry.json`, format
   `{"subsystems": [{"name", "environment_manifest", "release_sha",
   "qualification_state", "interface_compatibility",
   "clock_reset_compatibility"}, ...]}`, written by
   `dv_harness/engine.py`'s `_persist_subsystem_registry_entry()`. The
   composer's `_resolve_subsystem_manifest()` additionally does a
   best-effort read of each entry's own `environment_manifest` path (the
   real `environment_manifest.json` `UVMEnvironmentGenerator.generate()`
   itself writes) to recover that subsystem's *real* clock/reset names for
   `soc_tb_top.sv`, degrading gracefully (never fabricating) when that path
   doesn't resolve.
2. **Emits `soc_tb_top.sv`** that imports each subsystem's real
   `<protocol>_env_pkg`, declares/toggles/deasserts each subsystem's real
   (or manifest-level `shared_clocks`/`shared_resets`-overridden) clock and
   reset signals, and instantiates each subsystem's real
   `<protocol>_env` class by name with an evidence-cited creation line --
   same naming convention `UVMEnvironmentGenerator.env()` already uses
   (`%s_env` % p), same minimal clock/reset-generation shape
   `UVMEnvironmentGenerator.tb_top()` already uses, generalized from one
   subsystem to N.
3. **Emits `soc_virtual_sequencer.sv`** by calling
   `UVMEnvironmentGenerator.vseq()` *unchanged* (an unbound call, since
   `vseq()` never touches `self`) against a `virtual_sequencer_fields` list
   this module builds -- one `<protocol>_virtual_sequencer
   <protocol>_vseqr;` field per registered subsystem, each with a required,
   non-empty `evidence` string citing the real registry entry. This reuses
   the DSL verbatim per the task instruction ("don't invent new schema").
4. **Leaves `cross_subsystem_scenarios()` / `end_to_end_scoreboard()` /
   `system_coverage()` as explicit `NotImplementedError` stubs.** Each has
   a doc-comment explaining why: a subsystem registry entry carries only
   identity/qualification metadata, never sequence-body/checking/coverage
   semantics, so this generic composer has no primary source to draw that
   protocol-behavior content from (CLAUDE.md "No Golden-Reference Content
   Mining"). `compose_soc_environment()` only invokes them when the
   manifest's corresponding key (`cross_subsystem_scenarios`,
   `end_to_end_scoreboards`, `system_coverage`) is non-empty -- same
   additive/no-op-when-absent convention as every other optional
   `generator.py` manifest key, so a composition that never asks for that
   content still succeeds and returns `soc_tb_top.sv` +
   `soc_virtual_sequencer.sv` + `soc_composition_manifest.json` normally.

## Wiring (reachability)

`system_level_validator.py`'s only caller is `dv_harness/gates.py`'s
`STAGE_GATES["SYSTEM_LEVEL"]` entry, a *multi-flag* gate
(`EvidenceFlag("--registry", "registry")` + a harness-supplied
`ContextFlag("--registered", ...)`). Per `gates.py`'s `_materialize_flag`,
this means an agent's raw evidence block for it is
`{"registry": {"subsystems": [...]}}`.

`dv_harness/engine.py` gained `_compose_soc_environment_files(stage,
evidence_blocks)`, following the exact same pattern as the adjacent,
already-tested `_persist_subsystem_registry_entry()`: it fires only when
`verdict == "PASS"` and `STAGE_GATES[stage]` includes
`system_level_validator`, reads `evidence_blocks["system_level_validator"]
["registry"]`, and -- since `system_level_validator.py` itself only reads
`d.get("subsystems")`/`d.get("system_level_applicable")` and silently
ignores any other key -- reuses that SAME `registry` dict as both
`subsystem_registry_entries` (its `"subsystems"` list) and
`compose_soc_environment`'s `manifest` argument (so an agent can carry
`soc_composition_manifest_template.json`'s richer fields --
`soc_name`/`shared_clocks`/`shared_resets`/`cross_subsystem_scenarios`/...
-- in the same fence without a new schema). On success it writes the
returned files to `generated/soc_composition/<soc_name>/` and records a
`SOC_ENVIRONMENT_COMPOSED` event + a `soc_composition` blackboard entry; a
`NotImplementedError` or typed input error is logged
(`SOC_COMPOSITION_NOT_IMPLEMENTED` / `SOC_COMPOSITION_INPUT_INVALID`) and
skipped, never downgrading an already-earned SYSTEM_LEVEL PASS. The call
site is wired into `run_stage()`'s existing PASS-hook list, immediately
after `_persist_subsystem_registry_entry`.

## Rulings

- **RULING:** `compose_soc_environment()` only strictly requires a
  non-empty `"name"` per registry entry. The full required-field set
  (`environment_manifest`/`release_sha`/`qualification_state`/
  `interface_compatibility`/`clock_reset_compatibility`) is already
  enforced by `subsystem_environment_registration_gate.py` *before* a real
  entry is ever persisted into the registry; re-enforcing the whole set
  here would be redundant defense-in-depth against input this module
  trusts was already gate-validated, and would reject legitimate minimal
  test fixtures. Missing optional fields degrade to an `"UNKNOWN"` citation
  in generated evidence comments rather than a hard failure.
- **RULING:** the SoC-level `tb_top` instantiates each subsystem's `_env`
  class directly in a module-level `initial` block (not via a `soc_env`
  UVM component/`soc_base_test`), because the task's two requested
  deliverables are `soc_tb_top.sv` and `soc_virtual_sequencer.sv` only, and
  `generator.py`'s own `tb_top()` is itself a plain module with no `uvm_env`
  wrapper. A future iteration could add a `soc_env`/`soc_base_test` pair
  once real SIGNOFF evidence calls for phased UVM component composition
  rather than direct instantiation; this was flagged as a genuine
  architecture choice rather than something the primary sources dictated.
- **RULING:** real cross-subsystem interface-level wiring
  (`connectivity`/`address_map`/`interrupt_map`/`dma_paths` manifest
  fields) is surfaced in `soc_tb_top.sv` only as a comment listing which
  keys the manifest declared, not rendered into real port connections --
  this is genuine system-topology content in the same category as the
  three explicit `NotImplementedError` stubs, and rendering it would have
  meant inventing a connection-rendering scheme the task did not ask for
  (`_connect_phase`'s DSL is scoped to a `uvm_env`'s `connect_phase`, which
  this module deliberately does not emit). Kept honest via a comment
  mirroring `generator.py`'s own placeholder
  (`// Bind DUT and VIP interfaces from environment_manifest.json/current
  evidence.`) rather than silently dropped.
- **RULING:** clock/reset priority is manifest `shared_clocks`/
  `shared_resets` first, then each subsystem's real environment_manifest.json
  clocks/resets (deduplicated by name), then a synthesized
  `<protocol>_clk`/`<protocol>_rst_n` fallback -- verified end-to-end in
  `test_soc_tb_top_uses_real_per_subsystem_clocks_from_real_environment_manifest`
  by generating a real subsystem environment with
  `UVMEnvironmentGenerator.generate()` first and pointing a registry entry
  at its real output.
- **RULING:** the wiring call site reuses the *same* `system_level_validator`
  evidence block for both the registry-entries list and the composition
  manifest, rather than requiring a second `dv-harness-evidence` fence.
  `system_level_composition_gate.py` (which has its own richer
  `selected_subsystems`/`system_level_scenarios` schema closer to
  `soc_composition_manifest_template.json`) exists in the repo but is not
  wired into `STAGE_GATES` at all (confirmed by grep) -- wiring that
  separate, currently-orphaned gate was out of scope for this task, which
  named `system_level_validator.py`'s callers specifically as the
  reachability point.

## Tests

- `dv_harness_tests/test_soc_environment_composer.py` (new, 17 tests):
  composition happy path with 2 fake-but-structurally-valid subsystem
  registry entries (USB/PCIE, same REQUIRED-field shape as the existing
  `subsystem_environment_registration_gate` test fixtures); real env-naming
  assertions on `soc_tb_top.sv`/`soc_virtual_sequencer.sv`; the
  `shared_clocks` override path; the `virtual_sequencer_fields` manifest
  override path; an end-to-end test that generates a *real*
  `environment_manifest.json` via `UVMEnvironmentGenerator.generate()` and
  confirms the composer reads its real clock/reset names rather than
  falling back to a synthesized default; the `EmptySubsystemRegistryError`/
  `MissingSubsystemNameEvidenceError` typed-error paths; and both the
  direct-call and manifest-triggered `NotImplementedError` paths for all
  three stubs.
- `dv_harness_tests/test_engine_gates_and_routing.py` gained
  `test_engine_composes_soc_environment_on_system_level_pass`, following
  the exact structure of the adjacent
  `test_engine_persists_subsystem_registry_entry_on_signoff_pass`: drives
  `_compose_soc_environment_files()` directly with a realistic
  `system_level_validator` evidence shape, asserts the real files land
  under `generated/soc_composition/demo_soc/`, the blackboard write, the
  `SOC_ENVIRONMENT_COMPOSED` event, the no-op path for a stage without the
  gate, the `system_level_applicable: false` escape hatch, and the
  `SOC_COMPOSITION_NOT_IMPLEMENTED` logging path when a manifest requests
  `cross_subsystem_scenarios` content.

Targeted runs (`pytest dv_harness_tests/test_soc_environment_composer.py`
and the two new/related cases in `test_engine_gates_and_routing.py`) pass:
17 + 2 = 19 new tests green. The full `dv_harness_tests` suite (1287 tests
historically, ~19 minutes on this machine) was also run before committing
to confirm zero regressions; see `tests_summary` in the structured result
for its outcome.

## Concerns / residual gaps

- The `soc_tb_top.sv`/`soc_virtual_sequencer.sv` output is a *structural*
  scaffold, not a compilable, fully-wired SoC testbench -- exactly the
  boundary the task asked for. Real interface-level connectivity and all
  three explicitly-stubbed content categories still need a follow-up
  session with real per-subsystem VIP/DUT evidence once an actual
  multi-subsystem project exists.
- `system_level_composition_gate.py` (a second, richer SYSTEM_LEVEL-shaped
  gate with `selected_subsystems`/`system_level_scenarios`) exists in the
  repo but was found to be unwired into `STAGE_GATES` during this task's
  investigation -- flagged here as a pre-existing gap (same "declared but
  never wired" pattern the 2026-08-28 audit already found and fixed for
  `system_level_validator`/`execution_mode_validator`) but left alone since
  wiring it was not part of this task's scope.
