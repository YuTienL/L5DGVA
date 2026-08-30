---
name: generic-dv-environment-builder
description: Build a generic UVM verification environment from DUT/source/spec/VIP evidence, then compile, smoke-test and repair it to a baseline-ready state.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Generic DV Environment Builder
Inputs: DUT RTL, interfaces, protocol/spec, programming/register guide, VIP docs/examples/source/class reference.
Outputs: UVM top, env, agents, adapters, config, virtual sequencer, sequence library, scoreboard/reference model, RAL, assertions, coverage, error injection, smoke tests.
Must pass Evidence Truth Gate and Independent Synthesis before generation.
