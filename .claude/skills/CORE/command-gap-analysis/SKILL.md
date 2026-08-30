---
name: command-gap-analysis
description: Compares vPlan-required scenarios against existing DE command capabilities and classifies each as REUSE, EXTEND or GENERATE.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Command Gap Analysis

Source of truth:
Specification + Protocol Profile + DUT/SoC Topology + Verification Boundary + vPlan.

For each vPlan scenario:
1. existing command covers it -> REUSE
2. existing command plus parameter/composition covers it -> EXTEND
3. existing VIP sequence/API supports it but no command -> GENERATE command/mapping
4. lower-level VIP API supports it -> GENERATE sequence + command + mapping
5. capability truly unavailable/ambiguous -> BLOCKED

Reuse first -> Extend second -> Generate last.

Produce `.dv-workflow/command_gap.csv`:
VP_ID,SCENARIO,REQUIRED_CAPABILITY,MATCH,ACTION,COMMAND_ID,STATUS,SOURCE,CONFIDENCE
