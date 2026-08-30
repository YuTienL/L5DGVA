---
name: real-smoke-closure-engine
description: Run protocol smoke tests, stop at first meaningful failure, gather evidence and repair/rerun.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# real-smoke-closure-engine

Run protocol smoke tests, stop at first meaningful failure, gather evidence and repair/rerun.

## Rules
- Current DUT/spec/VIP evidence is mandatory.
- No guessed VIP APIs.
- Generated source must be compile/smoke-closed before qualification.
- Generator capability must not be confused with production qualification.
