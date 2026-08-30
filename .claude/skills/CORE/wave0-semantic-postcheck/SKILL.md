---
name: wave0-semantic-postcheck
description: Default WAVE=0 post-simulation semantic validation against command.txt and sim.log.
---
# WAVE=0 Semantic Postcheck

Default simulation mode is `WAVE=0`.

After simulation ends:
1. Read the original `command.txt` verification intent.
2. Read `sim.log` completely.
3. Do not accept simulator/UVM `PASSED` alone.
4. Verify that runtime messages and observed semantics satisfy the command intent.
5. Detect contradiction, missing expected evidence, unexpected errors, timeout, UVM_ERROR/UVM_FATAL, protocol mismatch, checker/scoreboard/assertion failure.
6. Record the first meaningful error/divergence simulation timestamp.
7. Produce a semantic result: `TRUE_PASS`, `TRUE_FAIL`, or `NEEDS_DEEP_DEBUG`.
8. If no problem is found, hand off to the normal closure flow.
9. If a problem is found, re-enter the workflow for RCA and correction.

Iron behavior: a WAVE=0 simulation ending cleanly is never sufficient evidence by itself.


## Simulation Completion Recheck Rule

If the simulation has not ended yet:
- schedule/check again after **4 minutes**, OR
- recheck immediately when a background/job completion notification arrives,
- whichever occurs first.

Do not start semantic closure before the simulation is known to have ended.
When completion is confirmed, immediately launch the command.txt ↔ sim.log semantic workflow.
