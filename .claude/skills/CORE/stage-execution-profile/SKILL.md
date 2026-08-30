---
name: stage-execution-profile
description: Record wall clock and aggregate agent runtime separately, plus provider-reported token/tool/retry/finding telemetry.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Stage Execution Profile
Stage Wall Clock != Aggregate Agent Runtime.
Provider token usage must not be guessed.
Unavailable token usage must be N/A/null.
