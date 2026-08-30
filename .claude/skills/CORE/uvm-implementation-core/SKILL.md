---
name: uvm-implementation-core
description: Protocol-agnostic UVM implementation discipline for VIP integration, agents, sequences, scoreboards, assertions, coverage, config and regression registration.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# UVM Implementation Core

Reuse first:
existing VIP -> existing env/agent -> existing sequence/test -> extend only missing capability.

Map:
test -> virtual sequence -> sequence -> sequencer -> driver/VIP
monitor -> analysis -> scoreboard/reference model
monitor/assertions -> coverage

Follow project config_db/factory/style.
Keep scoreboard expected/actual semantics explicit.
Register tests in the existing regression mechanism.
Coverage must trace to verification-plan intent.
