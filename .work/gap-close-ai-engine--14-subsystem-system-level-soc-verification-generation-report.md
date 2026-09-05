# Gap-close pass: AI mechanism #14 — Subsystem -> System-Level/SoC verification generation

**Verdict: NEEDS_SEPARATE_EFFORT**

**Files modified: none.** No code, test, doc or config file was touched by this pass. This report
is the only artifact written.

## Why not DONE, and why not NO_ACTION_NEEDED

The audit's finding splits cleanly into two independent gaps, and they resolve differently:

1. **The code-wiring gap (mode decision computed but nothing branched on it) is genuinely CLOSED.**
   Re-verified below against the CURRENT tree, not accepted from the audit text. Nothing for this
   pass to close.
2. **A second, structural gap remains** — `cross_subsystem_scenarios()` / `end_to_end_scoreboard()` /
   `system_coverage()` raise `NotImplementedError` because no cross-subsystem topology descriptor
   exists anywhere in the repo. That is a new capability (schema + gate + generator + fixtures),
   not a wiring fix, and the task framing explicitly instructs it not be attempted in this pass.

Reporting NO_ACTION_NEEDED would have hidden (2); reporting DONE would have been false. Hence
NEEDS_SEPARATE_EFFORT, scoped below.

## Re-verification of the audit's evidence (the tree moved twice since it ran)

The audit's cited tip commit for `create_environment.py` was `2c0e841`. The tree has since advanced
through two more commits that touch exactly these files, so the wiring claim was re-checked rather
than assumed to have survived:

- `984d75e` — "signoff: the human-approval hard-stop must govern the subsystem registry too"
- `79031e7` — "protocol-model-layer: reach the five protocol models from the one CREATE ENVIRONMENT
  entry point" (gap #13's fix, which edited both `create_environment.py` and
  `tools/generate_protocol_uvm_environment.py`)

Result: **the #14 dispatch survived both intact and was extended, not displaced.**

| Claim | Status | Evidence re-checked now |
|---|---|---|
| Dispatch code is real and branches on the router | CONFIRMED | `dv_harness/uvm_generator/create_environment.py:197-282` — resolves via `resolve_environment_mode()`, branches to `ProtocolEnvGenerator` (line 242) or `compose_soc_environment()` (line 269) |
| The one official entry point calls it | CONFIRMED | `tools/generate_protocol_uvm_environment.py:29-31,47` imports and calls `create_environment()`; no direct `ProtocolEnvGenerator` call remains |
| All builder skills invoke that script | CONFIRMED | 11 files under `.claude/skills/PROTOCOL_BUILDERS/` reference `generate_protocol_uvm_environment.py` (audit said 10; one more has since been added — same conclusion) |
| Composition reads the REAL registry, not the caller | CONFIRMED | `create_environment.py:199,266-267` via `read_registered_subsystem_entries()` (`dv_harness/environment_mode_router.py:64-88`), written only by `engine.py:1234` `_persist_subsystem_registry_entry()`, called at `engine.py:3751` on a gate-validated PASS |
| Real `SOC_ENVIRONMENT_COMPOSED` emitter on the stage path | CONFIRMED | `dv_harness/engine.py:1451`, reached from `_compose_soc_environment_files()` (`engine.py:1370`, called at `engine.py:3753`) |
| Three `NotImplementedError` stubs are real | CONFIRMED | `soc_environment_composer.py:333, 354, 374` |
| The stub boundary is narrow, not a hidden bypass | CONFIRMED | `soc_environment_composer.py:443-474` — `soc_virtual_sequencer.sv`, `soc_tb_top.sv` and `soc_composition_manifest.json` are always produced; the stubs fire only at lines 463-468, i.e. only when the manifest explicitly requests that content |
| This project's registry is empty | CONFIRMED (with a correction) | The file does not exist at all — `.dv-harness/soc-composer/` holds only the four templates plus the new `system_resource_registry_template.json`. `read_registered_subsystem_entries()` degrades a missing file to `[]` (`environment_mode_router.py:80-83`), so the audit's "empty" and the real "absent" reach the same result: zero registered subsystems, nothing fabricated |
| Zero real compositions in production history | CONFIRMED | `grep -c SOC_ENVIRONMENT_COMPOSED .dv-harness/events.jsonl` → 0; `find . -type d -name soc_composition` → no match anywhere in the tree |

### Test suite: passes, with one load-induced flake identified

`python -m pytest dv_harness_tests/test_system_level_soc_composition_wiring.py`

- Full-file run under this session's heavy concurrent load: **9 passed, 1 failed in 307s**.
  `test_real_run_stage_system_level_refuses_unregistered_subsystem` died on
  `subprocess.TimeoutExpired`.
- Re-run of that single test in isolation: **1 passed in 60.25s**.

So the failure is **not a regression in #14**. It is `dv_harness/gates.py:1152`'s fixed
`timeout=30` per gate subprocess: this test drives a real `run_stage("SYSTEM_LEVEL")` through all
14 real `STAGE_GATES["SYSTEM_LEVEL"]` scripts, and under contention from the other concurrent
workstreams in this tree one gate subprocess exceeded 30s. The audit saw 10/10 in 133s on a quieter
machine.

**Deliberately not fixed here.** `gates.py` is a heavily contended shared file in this pass, and
raising a global gate timeout is a test-infrastructure change unrelated to mechanism #14 — making
it from this workstream would be exactly the out-of-scope edit to a shared file the task warns
about. Flagged for whoever owns test-suite stability: the wall-clock budget for gate-driving tests
is not load-proof.

## What the follow-up effort should cover

**Title:** Cross-subsystem topology descriptor, so SoC composition can generate behavior content
instead of refusing it.

**Why it is a separate effort, not a wiring fix.** The three stubs are not unwired code — there is
no code to wire. They refuse because a registry entry carries only identity/qualification metadata
(name, `environment_manifest`, `release_sha`, `qualification_state`, interface/clock-reset
compatibility) and never sequence-body semantics, so a generic composer has no primary source for
cross-subsystem behavior. Fabricating it is precisely what CLAUDE.md's "No Golden-Reference Content
Mining" forbids. The missing input — an address map, interrupt routing and DMA ownership model
spanning composed subsystems — does not exist anywhere in the repo in any form.

**Scope, four parts:**

1. **Schema** — a `cross_subsystem_topology.json` contract (shared address ranges, interrupt lines,
   DMA channels per composed subsystem pair) under `dv_harness/schemas/`, following the existing
   input-contract convention of `soc_arch_map.schema.json` / `register_map.schema.json`: a
   documented contract this repo consumes, not an extractor, since this repo owns no SoC.
2. **Gate** — a new script under `tools/verification_flow/` validating that descriptor against each
   composed subsystem's own real `environment_manifest.json` interface/interrupt declarations.
   `fabric_topology_completeness_gate.py` (exists, verified on disk) is the right structural
   precedent — it already does address-decode completeness for AMBA.
3. **Generator** — extend `compose_soc_environment()` to consume the descriptor when present and
   generate real `end_to_end_scoreboard()` / `cross_subsystem_scenarios()` / `system_coverage()`
   content from it. The refusal must remain the behavior when no descriptor is supplied: absence of
   the topology fact stays an honest `NotImplementedError`, never a degraded placeholder.
4. **Verification** — a `dv_harness_tests/test_*` fixture with two really-registered subsystems plus
   a real topology descriptor, asserting the generated scoreboard/scenario content references both
   subsystems' real interface signals (not their names alone).

**Separately, and not code work at all:** mechanism #14 has still never fired in this repo's own
production history, because this harness repo has never had a second subsystem to register. That
residual retires only when a real project registers >= 2 subsystems through a real SIGNOFF PASS and
runs `SYSTEM_LEVEL` for real, producing a genuine `SOC_ENVIRONMENT_COMPOSED` record outside test
fixtures. It must not be retired by writing fabricated registry entries into this project's real
audit trail.

## Commit

None. No file other than this report changed, so there is nothing to commit for this mechanism.
