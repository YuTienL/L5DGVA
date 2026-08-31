---
name: canfd-environment-builder
description: Build a production-oriented CAN / CAN-FD UVM verification environment from current DUT/spec/VIP evidence and integrate it into the common Harness lifecycle.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# CAN / CAN-FD Environment Builder

## Evidence Inputs
Must inspect current DUT RTL/source, applicable specification, PHY documentation, programming/register guides,
VIP manual/examples/source/class reference, and current project configuration.

## Discover Before Generate
- node/controller role
- Classical CAN/CAN-FD
- ISO/non-ISO
- nominal/data bit timing

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

For arbitration/BRS/ESI/error-state content specifically, use
`dv_harness/uvm_generator/canfd_arbitration_generator.py` instead of
hand-authoring arbitration or error-state logic — it already implements
the mechanics this section's "arbitration", "BRS/ESI", and "error frames"
bullets ask for.
- multi-node topology
- arbitration
- BRS/ESI
- CRC
- ACK
- error frames
- bus-off/recovery
- fault injection
- scoreboard
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
