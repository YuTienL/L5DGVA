---
name: evidence-truth-gate
description: Enforce that CLAUDE.md, memory, summaries and guesses are only priors; current RTL, waveform, log, register and document evidence determine truth.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Evidence Truth Gate

## Core Principle
CLAUDE.md != Evidence
Memory != Evidence
Previous Agent Conclusion != Evidence
Plausible Guess != Evidence

## Allowed Use
These sources may guide search direction or hypothesis priority only.

## Verified Root Cause Gate
A root cause may be promoted to VERIFIED only after direct current-project evidence is acquired.

Preferred evidence:
1. Current RTL/source inspection
2. Current waveform/FSDB measurement
3. Current sim.log/assertion/scoreboard/transaction evidence
4. Register readback/programming sequence
5. Versioned PHY/Programming/VIP documentation
6. Reproducible rerun evidence

## Conflict Rule
Current source/waveform/log/register evidence wins over CLAUDE.md or memory.
Conflicting memory must be marked STALE or CONFLICTED.
