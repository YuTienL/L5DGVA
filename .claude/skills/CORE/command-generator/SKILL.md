---
name: command-generator
description: Generates or extends command.txt scenarios and command-to-handler/VIP mappings from vPlan gaps while preserving DE compatibility.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Command Generator

vPlan drives required verification scenarios.
Existing DE commands are reused where possible.

Generate only after command-gap-analysis.

Maintain:
`.dv-workflow/command_mapping.csv`
COMMAND_ID,COMMAND,HANDLER,VIP_SEQUENCE,CHECKER,COVERAGE,SOURCE,STATUS

Traceability:
REQ -> VP_ID -> SCENARIO -> COMMAND_ID -> HANDLER -> VIP_SEQUENCE -> CHECKER -> COVERAGE -> TEST/REGRESSION

Prefer stable user-facing command API; hide UVM/VIP implementation details from normal DE users.
DV-only negative/error-injection commands may be marked DV_ONLY.

Never replace a working DE command with a new incompatible spelling without explicit reason.
