# Gap close — AI mechanism #14: Subsystem → System-Level/SoC verification generation

**Status: DONE**

Audit verdict was PARTIALLY_WIRED. Two of the three in-scope items the audit named are closed
for real; item 4 (the `NotImplementedError` protocol-behavior stubs) is confirmed out of scope and
stays open by design, and item 1's "fire it in *this* project's own state" is deliberately NOT
done — see "What was deliberately not done" below.

## What the re-check found (before changing anything)

Every load-bearing claim in the audit re-verified against the current tree:

- `.dv-harness/state.json` → `current_stage: ENV_CHECK`; `ENV_CHECK` is the only stage not
  `NOT_STARTED`. `SYSTEM_LEVEL`, `PROJECT_MODEL`, `SIGNOFF` are all `NOT_STARTED`, `attempts: 0`.
- `.dv-harness/soc-composer/` holds only the four `*_template.json`/policy files. The real
  `subsystem_environment_registry.json` does not exist.
- The call sites are real and unconditional: `engine.py` `begin_stage()` calls
  `resolve_environment_mode(...)`, and `run_stage()`'s PASS branch calls
  `_compose_soc_environment_files(...)`.
- One correction to the audit's own numbers: `STAGE_GATES["SYSTEM_LEVEL"]` has **14** gates, not 3.
  That is what made a genuine `run_stage()`-driven test look prohibitive and is why the existing
  regression test called the private method instead.

Two more findings the audit did not have, both of which changed the shape of the fix:

1. **There is no `CREATE ENVIRONMENT` code path to add a dispatch to** — a repo-wide grep for
   `create_environment` found only a doc reference. The real entry point every
   `.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` (all ten) invokes is
   `tools/generate_protocol_uvm_environment.py` → `ProtocolEnvGenerator.generate()`. That script
   called the generator unconditionally, so the router's decision reached the prompt and nothing
   else. That is the real location of the gap the audit described as item 2.
2. `system_level_validator.py`'s harness-supplied `--registered` cross-check means an agent's
   claimed subsystem list is already verified against the real registry (name **and**
   `release_sha`) before `_compose_soc_environment_files()` ever runs. So the engine-side composer
   input needed no hardening — only proof that the chain actually executes.

## What changed

**1. `dv_harness/uvm_generator/create_environment.py` (new) — the missing dispatch.**
`create_environment(root, request, out_dir)` resolves the mode with the real
`environment_mode_router.resolve_environment_mode()` and branches:
- `SUBSYSTEM_MODE` → the same `ProtocolEnvGenerator(out).generate(m)` call as before.
- `SYSTEM_LEVEL_MODE`, all subsystems registered → `compose_soc_environment()`.
- `SYSTEM_LEVEL_MODE`, something missing → `SubsystemModeRequiredError` naming the missing
  subsystems and the router's own `next_action` (CLAUDE.md: build it through SUBSYSTEM_MODE, then
  return to composition). It never composes the registered subset, and never degrades a
  two-subsystem request into one subsystem environment.
- nothing requested → `EnvironmentModeUnresolvedError`, honoring
  `environment_mode_policy.json`'s `mode_must_be_explicit_before_generation` instead of defaulting.

It reuses the three existing real pieces and reimplements none of them. The composed subsystems are
read from the **real registry**, never from the caller — so this path cannot inject an unregistered
subsystem into a composition, matching the guarantee the SYSTEM_LEVEL stage path already had.

**2. `tools/generate_protocol_uvm_environment.py` — wired to it.** The one official CREATE
ENVIRONMENT entry point now routes through the dispatch. Added `--root` (defaults to cwd, never
this repo's own root) for the registry lookup. A single-protocol manifest — what every builder
skill passes today — still resolves SUBSYSTEM_MODE and produces byte-identical output with the
same `status: OK` stdout shape; the pre-existing `test_cli_shim_generates_environment_from_manifest_file`
passes unchanged.

**3. `dv_harness/environment_mode_router.py`** — added `registry_path()` and
`read_registered_subsystem_entries()` (full gate-validated entries, the shape
`compose_soc_environment()` consumes). `read_registered_subsystem_names()` is now derived from it
rather than parsing the same file a second way, so the two readers cannot disagree.

**4. `dv_harness/uvm_generator/soc_environment_composer.py` + `dv_harness/engine.py`** —
`soc_composition_out_dir()` is now one shared helper; `engine.py`'s
`_compose_soc_environment_files()` uses it instead of its own hardcoded path string, and the
dispatch uses it as its default, so a composition produced by either real path without an explicit
output directory lands where the other looks for it rather than at two independently hardcoded
`generated/soc_composition/...` strings. (The tool always passes an explicit `--out`, which wins.)

**5. `dv_harness_tests/test_system_level_soc_composition_wiring.py` (new)** — 8 tests, the point
of the whole pass.

## Tests

`10 passed` in the new file. Every touched-area suite green, no regressions:
`test_engine_gates_and_routing` 239 passed, `test_hard_gate_script_smoke` 177 passed,
`test_soc_environment_composer` + `test_protocol_env_generator` 22 passed,
`test_generator_wiring_notices` 2 passed. `dv_harness.mcp.claude_md_index` and
`source_authority.assert_doc_matches_code()` (the two CLAUDE.md-parsing checks) still match after
the CLAUDE.md edit.

The one that closes the audit's item 1/3: **`test_real_run_stage_system_level_pass_composes_soc_environment`**
drives a genuine `DVHarness.run_stage("SYSTEM_LEVEL")` — not the private method — on a temp project
carrying the real shipped graph and all 14 real gate scripts, with the registry seeded through the
real production writer `engine.py::_persist_subsystem_registry_entry()`. Evidence payloads for all
14 gates are transcribed from `prompts.py`'s own `STAGE_INSTRUCTIONS[SYSTEM_LEVEL]` examples, i.e.
what a real agent is actually told to produce. It asserts stage PASS, real `soc_tb_top.sv` /
`soc_virtual_sequencer.sv` / `soc_composition_manifest.json` content, the blackboard write, and a
real `SOC_ENVIRONMENT_COMPOSED` event in `events.jsonl`. Nothing is mocked — not a gate, not a
verdict, not the registry.

Its negative twin, `test_real_run_stage_system_level_refuses_unregistered_subsystem`, proves the
registry cross-check is live on that same real path: identical evidence with only USB registered
fails the stage and composes nothing.

## What was deliberately NOT done

- **The audit's item 1 asks for a real firing inside *this project's own* `.dv-harness`.** Doing
  that means writing two subsystem entries into this repo's live
  `subsystem_environment_registry.json` and driving its live `state.json`/`events.jsonl` to a
  SYSTEM_LEVEL PASS. This repo has no real subsystem environments — `usb31_dev_uvm` is a remote,
  single-DUT, single-protocol build worked outside `run_stage()` — so those entries would be
  fabricated, and the resulting `SOC_ENVIRONMENT_COMPOSED` record would be manufactured verification
  evidence in the project's real audit trail. CLAUDE.md's Evidence Truth Rule forbids that, and
  `grep -c SOC_ENVIRONMENT_COMPOSED .dv-harness/events.jsonl ≥ 1` is not worth buying with a fake.
  The proof is instead a real engine, real gates and real generated content on a real temp project.
  **This project's own registry is still legitimately empty, and mechanism #14 has still never
  fired in this project's production history — it now provably fires when a real project supplies
  real registered subsystems.**
- **Item 4 — the `cross_subsystem_scenarios()` / `end_to_end_scoreboard()` / `system_coverage()`
  `NotImplementedError` stubs — remains open and is correctly out of scope.** Closing them needs a
  real system-level topology descriptor (address/interrupt/DMA maps across subsystems), a
  cross-subsystem scoreboard-composition strategy, and multi-IP regression orchestration, all
  sourced from primary per-subsystem VIP/DUT evidence for the specific subsystems composed (No
  Golden-Reference Content Mining). None of that exists yet beyond the manifest schema. The stubs
  raising honestly is the correct current behavior, and both real paths handle it: the engine logs
  `SOC_COMPOSITION_NOT_IMPLEMENTED` and writes nothing; the dispatch propagates it.

## Remaining honest limitation

`create_environment()` is the dispatch at the *tool* entry point. `ProtocolEnvGenerator` remains
importable and directly callable, so a caller that bypasses the tool still bypasses the mode
decision. That is the same disclosed-residual shape as `require_tier`/`require_phy_boundary`: what
is closed is the documented path every builder skill actually uses, not every conceivable import.
