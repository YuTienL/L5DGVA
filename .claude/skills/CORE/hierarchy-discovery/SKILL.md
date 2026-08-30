---
name: hierarchy-discovery
description: Reconstructs DUT/SoC design hierarchy and protocol-instance inventory before VIP or testbench planning.
allowed-tools: Read Grep Glob PowerShell
---
# DUT / SoC Hierarchy Discovery

Do this before final vPlan, VIP binding or TB generation.

Discover:
- top module and relevant subsystem roots
- DUT instances and replicated instances
- protocol controller/PHY/bridge/interconnect instances
- parent/child hierarchy
- generated/parameterized instances
- active design configuration
- DUT-facing external/internal protocol ports

Never infer VIP count from protocol name alone.

Produce:
`.dv-workflow/hierarchy.json`
`.dv-workflow/dut_ports.csv`

For every relevant DUT port record:
PORT_ID,DUT_INSTANCE,HIERARCHY,PORT_OR_IF,PROTOCOL,ROLE,BOUNDARY,CLOCK,RESET,WIDTH,ENABLED,SOURCE,CONFIDENCE

Current RTL/elaboration/configuration evidence outranks stale comments/history.
