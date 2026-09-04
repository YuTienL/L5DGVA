---
name: pcie-environment-builder
description: Build a production-oriented PCIe UVM verification environment from current DUT/spec/VIP evidence and integrate it into the common Harness lifecycle.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# PCIe Environment Builder

## Evidence Inputs
Must inspect current DUT RTL/source, applicable specification, PHY documentation, programming/register guides,
VIP manual/examples/source/class reference, and current project configuration.

## Discover Before Generate
- RC/EP/Switch role
- Gen2-Gen6
- lane width
- Serial/PIPE/controller boundary

## Generate / Integrate

**Use the real generic scaffolding generators -- do not hand-write directory layout,
pattern registry, bind skeleton, or regression bookkeeping from scratch.**
`dv_harness/uvm_generator/protocol_env_generator.py` (`ProtocolEnvGenerator`) emits
the USB_UVM_Handoff-shaped subdirectory layout (`tb/agents,env,seq,tests,top,filelist`)
from a manifest JSON (`tools/generate_protocol_uvm_environment.py --manifest <m.json> --out <dir>`);
`dv_harness/uvm_generator/pattern_registry_generator.py` + `pattern_registry_completeness_gate.py`
build/validate the pattern-suite registry + Makefile dispatch
(`tools/generate_pattern_registry.py`); `dv_harness/uvm_generator/bind_mechanism_generator.py`
emits the DV_UVM two-hook bind/bridge skeleton from evidence-supplied `bind_entries`
(`tools/generate_bind_mechanism.py`); `dv_harness/uvm_generator/regression_list_manager.py`
maintains the regression.list PASS/FAIL bookkeeping. All four are protocol-agnostic
scaffolding only -- none invent protocol-specific register maps, VIP class names, or
checker/scoreboard semantics; those must still come from current evidence (previous
section), supplied into the manifest/topology JSON, never fabricated. Read each
module's own docstring "WHAT THIS DOES NOT DO" section before assuming more than this.

For LTSSM/link-training content specifically, use
`dv_harness/uvm_generator/pcie_ltssm_generator.py` (a real LTSSM
transition model) instead of hand-authoring link-training state logic — it
already implements the transition model this section's "LTSSM/link training"
bullet asks for.

**Since 2026-09-04 that model is layered by the SAME
`tools/generate_protocol_uvm_environment.py` run, not a second command.**
Add a `protocol_model_topology` block to the manifest and the LTSSM package,
its state-register module and a real transition-legality SVA in
`tb/env/pcie_assertions.sv` are generated with the skeleton (see
`dv_harness/uvm_generator/protocol_model_layer.py`):

```json
"protocol_model_topology": {
  "name": "pcie_ep",
  "lane_width": 4,
  "gen_speed": "Gen3",
  "role": "EP",
  "ltssm_state_signal": "u_pcie_ctrl.ltssm_state_q"
}
```

Every field is DUT evidence from the "Discover Before Generate" list above and
none is defaulted: omit the block and the tool reports
`PROTOCOL_MODEL_TOPOLOGY_NOT_SUPPLIED` in its `protocol_model` output (and in
the generated `environment_manifest.json`) rather than quietly producing a
skeleton that looks modelled; omit only `ltssm_state_signal` and the model
still layers but no assertion is emitted against an unconfirmed signal. The
standalone `tools/generate_pcie_ltssm_environment.py` still exists for
generating the LTSSM model on its own, outside an environment.
- VIP topology
- LTSSM/link training
- configuration space
- BAR
- TLP/completion scoreboard
- MSI/MSI-X
- AER/error injection
- ASPM/LTR
- SR-IOV/ATS/PASID/PRI where applicable
- coverage/assertions/smoke tests

## Mandatory Gates
- protocol_builder_registry_conformance_gate (discover/build checklist coverage)
- Evidence Truth Gate
- Multi-Agent Evidence Consensus
- Independent Synthesis
- Environment Manifest approval when topology is uncertain/high impact
- Compile PASS
- Smoke Simulation PASS
- Exact SHA / evidence provenance

Never reuse protocol-specific USB/PCIe/Ethernet/etc. content as truth for another protocol.
Only common UVM infrastructure/patterns may be reused.
