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

For the internal block/branch_a*/branch_fw/branch_b* task-composition shape a
generated (or hand-authored) pattern file's SystemVerilog must follow -- fork/join
semantics, join-vs-join_any, and the recurring trap classes -- see
`pattern-architecture`. This skill covers WHICH command IDs must exist; that one
covers HOW a pattern's internal task composition must be built.
