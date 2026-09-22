> **See CREATE_ENVIRONMENT.md** for the current, consolidated procedural guide covering this topic.

# DV Agent Harness L5 — Universal Protocol Platform

## Built-in Builder Families
PCIe / USB / Ethernet / MIPI CSI-2 / MIPI DSI /
AMBA4 Multi-Master × Multi-Slave / eDP / eMMC / SD-SDIO / UCIe.

## Future Interfaces
NEW_INTERFACE and NEW_SPECIFICATION_REVISION are first-class flows.

## Subsystem Flow
User requirement
→ choose protocol/new interface
→ current evidence acquisition
→ protocol model
→ VIP adapter or native UVC
→ UVM environment generation
→ compile
→ smoke
→ self-repair
→ protocol qualification
→ registry.

## System-Level Flow
User SoC goal
→ select registered subsystem environments
→ compatibility analysis
→ build/qualify missing subsystem if needed
→ compose SoC integration
→ cross-subsystem sequences
→ end-to-end scoreboard
→ system coverage
→ compile/smoke/regression/closure.

## Important Current-State Statement
This package now contains explicit builder profiles, qualification suites, new-interface learning,
spec-revision upgrade machinery, generator templates and executable qualification helpers.

It does NOT fabricate real qualification results.
A protocol remains BUILDER_AVAILABLE until the Harness is connected to the real DUT/spec/VIP/toolchain
and passes the required execution gates.
