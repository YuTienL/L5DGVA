---
name: verdi-debug
description: 在 Linux Server 上使用 Verdi/FSDB 進行深入 debug；不熟悉 Verdi option 時先查本地/官方手冊再查網路。
allowed-tools: Read Grep Glob PowerShell
---
# Verdi Debug

適用：
- fsdbreport evidence 不足
- 需要 trace RTL/UVM/VIP signal/source
- 需要 cross-probing 或 hierarchy/driver trace
- 需要人工/AI 深入 waveform debug

流程：
Representative failing test
→ WAVE=1 rerun
→ FSDB
→ fsdbreport first
→ 必要時 Verdi
→ root cause evidence

Verdi command / option 不清楚：
project usage
→ local Verdi User Guide/help
→ official reference
→ official online docs
→ credible web
→ BLOCKED/user

不要因為 Verdi 可用就跳過 fsdbreport automation。
