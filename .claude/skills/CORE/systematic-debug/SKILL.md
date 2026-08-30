---
name: systematic-debug
description: Evidence-driven DV/UVM/protocol root-cause method covering phases, objections, clock/reset, transactions, scoreboards, assertions, timeouts and seed dependence.
allowed-tools: Read Grep Glob PowerShell
---
# Systematic Debug

OBSERVE -> EVIDENCE -> REPRODUCE -> HYPOTHESIS -> FALSIFY/CONFIRM -> ROOT CAUSE -> MINIMUM FIX -> VERIFY

Before fix:
symptom, causal evidence, expected behavior, hypothesis, falsifier, predicted effect.

Check as relevant:
UVM phases/objections/config/factory/sequence flow/monitor/analysis/scoreboard,
clock/reset,
protocol handshake/state,
queues/events/interrupts,
seed/config dependence.

Do not increase timeout or weaken checkers first.
