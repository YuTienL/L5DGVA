---
name: simulation-observability-policy
description: Enforce default simulation observability: FSDB dumping OFF by default while VIP trace/report may be enabled for low-overhead protocol evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Simulation Observability Policy

## Default
Every normal simulation/regression starts with:

- FSDB / waveform dump: OFF
- Full waveform dump: OFF
- VIP trace/report: MAY be enabled
- sim.log / UVM report / assertions / scoreboard: enabled as applicable

Do not enable FSDB merely because a simulation is running.

## Preferred evidence escalation
Use the lowest-cost evidence first:

1. sim.log
2. UVM_ERROR / UVM_FATAL / assertions
3. scoreboard / transaction/checker evidence
4. VIP trace/report
5. targeted extra logging
6. FSDB only when waveform evidence is actually needed

## FSDB enable gate
If FSDB is required, invoke `waveform-dump-scope-planner`.

Before running waveform-enabled simulation, ask the user to confirm:
- dump scope
- dump level/depth

Prefer minimum sufficient waveform.

## VIP trace/report
VIP trace/report may be enabled independently of FSDB when supported by the current VIP/project.

The Harness must:
- inspect the current VIP configuration/examples/manual/source before inventing an enable switch
- record which VIP trace/report mechanism was enabled
- preserve trace/report as evidence
- not claim VIP trace is equivalent to signal-level waveform evidence

## Regression
Default regression baseline should remain NO-FSDB unless a specific testcase/job is explicitly promoted to waveform-debug mode.

Do not turn on FSDB globally for all LSF jobs unless explicitly approved.


## Failure Rerun Escalation

Normal run:
FSDB OFF.

If FAILED:
use `first-failure-waveform-rerun`.

The debug rerun should terminate at the first validated relevant failure point instead of completing the full testcase.
