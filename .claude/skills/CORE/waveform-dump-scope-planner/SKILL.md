---
name: waveform-dump-scope-planner
description: Before waveform-enabled simulation, ask the user to confirm waveform dump scope and dump level/depth, then record the decision and use the minimum sufficient scope.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Waveform Dump Scope Planner

## Mandatory Gate
Before enabling waveform dumping for VCS/simulation, the Harness must ask the user to confirm:

1. Dump scope
2. Dump level/depth

Do not silently assume full-chip/full-depth dumping.

## User prompt
Present a concise request such as:

「這次需要 dump waveform。請確認：
- Scope：要 dump 哪個 hierarchy / module / instance？
- Level：要 dump 幾層？例如 1 / 2 / 3 / 6 / all。
若不確定，我可以先根據目前 failure cone 建議最小足夠範圍。」

## Scope options
Examples:
- exact failing instance
- DUT block
- interface + DUT block
- protocol subsystem
- selected hierarchy list
- full DUT
- full SoC only when justified

## Level/depth
Treat level/depth as simulator/project dependent.
Never invent a numeric level without checking current project dump mechanism.

## Planning rule
Prefer Minimum Sufficient Waveform:
failure signal
-> driver/source
-> relevant state/FSM
-> handshake/control
-> register/config
-> clock/reset
-> interface/VIP boundary

Expand scope/level only if current evidence is insufficient.

## Record
Save:
- requested scope
- requested level
- reason
- estimated impact if known
- command/config changed
- simulation SHA/config identity
- user confirmation

## Safety / Evidence
LOCAL_ANALYSIS may recommend scope/level but cannot claim waveform was generated or measured.
REMOTE_EXECUTION is required to generate/measure runtime waveform evidence.
