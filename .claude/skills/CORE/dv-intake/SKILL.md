---
name: dv-intake
description: Zero-knowledge-user project discovery. Automatically inventories RTL, parameters, UVM/VIP, tests, docs, vPlan, build/regression scripts and Git evidence before asking the user.
allowed-tools: Read Grep Glob PowerShell
---
# DV Intake

The user should not need to know what to provide.

## Mandatory discovery order

① Existing project files
↓
② RTL / parameters / defines
↓
③ Existing UVM / VIP config
↓
④ Existing tests / sequences
↓
⑤ Design documentation
↓
⑥ vPlan / testcase spreadsheet
↓
⑦ Build / regression scripts
↓
⑧ Git history / comments
↓
⑨ Ask user

## Authority rules

Prefer current executable/configuration evidence over stale documentation.
Prefer current RTL/config over Git history/comments.
Use comments/history to explain intent, not override current behavior without corroboration.

## Project scan

Run when available:

`.claude/tools/dv-project-scan.ps1`

Output:
`.dv-workflow/inventory.json`

Do not read the entire repository or huge logs. Use path/name/search discovery first.

## Classify artifacts

- DUT/RTL
- interfaces/packages/defines
- VIP/BFM
- UVM TB
- tests/sequences
- scoreboards/checkers/assertions
- coverage
- docs/spec
- vPlan/testplan
- build
- regression/testlist
- logs/results
- tool/environment
- Git evidence

Return an evidence-backed intake summary and missing categories.
