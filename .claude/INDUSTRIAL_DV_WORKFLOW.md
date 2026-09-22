# Final Industrial DV Workflow

Designed for DE and general DV engineers.

## User-facing model
Normal users drive verification through `command.txt`.
They do not need to understand UVM internals, VIP sequence classes or required project artifacts.

## Verification source of truth
Specification + DUT/SoC topology + protocol profile + vPlan.

Existing DE `command.txt` is reusable baseline/reference.

## Core topology
DUT hierarchy -> DUT ports -> interface topology -> VIP topology/binding ->
BLOCK(branch_a*, branch_fw, branch_b*) -> vPlan -> command gap ->
REUSE/EXTEND/GENERATE -> command.txt -> VIP sequence -> DUT ->
checker/coverage -> regression -> signoff.

## Branch model
branch_a0..N: number derives from DUT ports.
branch_b0..M: number derives from VIP ports/instances.
branch_fw: N:M mapping/routing/adaptation/command dispatch/synchronization.

## Protocol defaults
USB Host/Device: USB2 FS/HS, USB3 Gen1/Gen2
PCIe Gen2-Gen6
MIPI CSI-2
MIPI DSI
Ethernet
CAN-FD
AMBA: APB2/APB3/AHB/AHB-Lite/AXI3/AXI4/ACE-Lite/AXI-Stream

## Core dispatched agents

This harness has 23 real agents total -- see `.claude/agents/ROSTER.md` for
the full roster and each one's real dispatch status. The 7 named below are
the core `GRAPH_DISPATCHED` agents most directly involved in the
command.txt-driven workflow described in this document; they are not the
complete agent population.

dv-lead
analysis-agent
implementation-agent
build-agent
regression-agent
debug-agent
review-agent
