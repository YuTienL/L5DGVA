---
name: workflow-report
description: Produces concise DE/DV-facing project/readiness/topology/command/validation summaries from workflow artifacts.
allowed-tools: Read Grep Glob PowerShell
---
# Workflow Report

Report in layers.

## Executive
Protocol(s), DUT instances, readiness, blockers, next action.

## DE view
Supported commands, required parameters, examples, expected results, failing command/test and actionable cause.

## DV view
Hierarchy, DUT ports, VIP type/count/bind, branch topology, vPlan gaps, command REUSE/EXTEND/GENERATE, checker/coverage, regression/signoff.

Never bury a blocking ambiguity inside a long report.
