---
name: dma-scoreboard-by-port-audit
description: Generic DMA/descriptor/ring/TRB/data/completion ownership audit for subsystem-to-SoC verification.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Generic DMA Scoreboard Audit

適用含 DMA / descriptor / ring / TRB / queue / memory movement 的任意 subsystem/SoC。

追蹤：
instance/port/interface
→ request/descriptor identity
→ DMA address/range
→ payload
→ byte count
→ completion/status

確認多 port/interface concurrent DMA 不會因 global state/queue 錯配。

輸出：
`.dv-workflow/dma_scoreboard_by_port_audit.csv`
