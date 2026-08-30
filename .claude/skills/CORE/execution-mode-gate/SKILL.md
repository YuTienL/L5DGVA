---
name: execution-mode-gate
description: Require explicit LOCAL_ANALYSIS vs REMOTE_EXECUTION declaration before every workflow and phase transition.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Execution Mode Gate

Before workflow execution, emit exactly one clear mode declaration.

LOCAL_ANALYSIS:
「這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。」

REMOTE_EXECUTION:
「這個需要連伺服器/跑模擬。」

For MIXED workflows, split into phases and redeclare at each transition.

Never present local static analysis as VCS/simulation/waveform evidence.
Never imply server access occurred unless REMOTE_EXECUTION actually performed it.
If mode is ambiguous, stop at PRE-FLIGHT.
