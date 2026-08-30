---
name: real-dut-interface-extractor
description: Extract candidate DUT modules, ports and parameters as raw evidence for semantic modeling.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# real-dut-interface-extractor

Extract candidate DUT modules, ports and parameters as raw evidence for semantic modeling.

## Rules
- Current DUT/spec/VIP evidence is mandatory.
- No guessed VIP APIs.
- Generated source must be compile/smoke-closed before qualification.
- Generator capability must not be confused with production qualification.
