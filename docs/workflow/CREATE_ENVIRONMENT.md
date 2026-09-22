> See START_HERE.md for the canonical entry point and current mechanism overview; this page remains accurate for its specific topic.

# CREATE ENVIRONMENT — AI Agent Harness L5

## Step 1: Choose Mode

### [1] SUBSYSTEM_MODE
Generate a subsystem verification environment.

Supported:
PCIe
USB
Ethernet
MIPI CSI-2
MIPI DSI
CAN / CAN-FD
AMBA4 SoC / Interconnect
eMMC
SD / SDIO
eDP / DisplayPort
UCIe
New Protocol / Interface

Example:
"CREATE ENVIRONMENT: SUBSYSTEM_MODE, PCIe Gen5 EP"

### [2] SYSTEM_LEVEL_MODE
Compose completed subsystem environments into a System-Level / Full-SoC verification environment.

Example:
"CREATE ENVIRONMENT: SYSTEM_LEVEL_MODE.
Use PCIe + USB + Ethernet + AMBA4 + DMA + DDR.
Verify concurrent DMA to shared memory."

## Behavior
SUBSYSTEM_MODE = GENERATE / BUILD / VERIFY / REGISTER

SYSTEM_LEVEL_MODE = SELECT / REUSE / COMPATIBILITY CHECK / COMPOSE / VERIFY

If SYSTEM_LEVEL_MODE needs a subsystem that is not BASELINE_READY:
SYSTEM_LEVEL_MODE
-> missing-subsystem-resolver
-> SUBSYSTEM_MODE
-> build/register missing subsystem
-> return to SYSTEM_LEVEL_MODE
-> compose SoC
