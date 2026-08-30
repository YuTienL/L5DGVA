---
name: user-role-router
description: Adapts workflow behavior for DE, DV or mixed DE+DV users without requiring them to understand UVM/VIP internals.
allowed-tools: Read Grep Glob PowerShell
---
# DE / DV User Role Router

Default audience is mixed DE + DV.

Do not require the user to declare a role unless the requested action is genuinely ambiguous.

## DE experience
Expose primarily:
- command.txt/scenario usage
- DUT behavior
- configuration
- expected result
- pass/fail and actionable error
Hide by default:
- UVM class internals
- sequencer/factory/config_db details
- VIP implementation APIs

## DV experience
May expose:
- vPlan/traceability
- command gap
- VIP topology/binding
- branch topology
- UVM sequence/checker/coverage
- regression/debug evidence

## Mixed team
Keep one stable command API.
Mark advanced negative/error-injection commands DV_ONLY when appropriate.
Never fork incompatible DE and DV command languages.
