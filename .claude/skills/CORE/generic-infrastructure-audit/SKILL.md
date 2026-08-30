---
name: generic-infrastructure-audit
description: 通用任何 subsystem/SoC 的 verification infrastructure audit，固定檢查 scoreboard、DMA scoreboard、performance、coverage 的 by-port/by-interface/by-instance 能力。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Generic Verification Infrastructure Audit

固定四大 Generic Audit：

1. Scoreboard By-Port / By-Interface / By-Instance
2. DMA Scoreboard By-Port / By-Interface / By-Instance
3. Performance Calculator By-Port / By-Interface / By-Instance
4. Coverage Collector By-Port / By-Interface / By-Instance

Generic Capability Matrix：

SCOPE
× SUBSYSTEM
× INSTANCE
× PORT / INTERFACE
× PROTOCOL
× MODE / SPEED / GEN / RATE / WIDTH / LANE
× ROLE
× TRAFFIC / TRANSFER / TRANSACTION TYPE
× DIRECTION / CHANNEL / STREAM
× RESOURCE
× CONCURRENCY
× ERROR / RESET / POWER / STATE

Protocol-specific legality 由各 protocol profile 提供。
Core audit 禁止硬編碼 USB 或 AMBA assumptions。

輸出：
PASS / PARTIAL / BLOCKED / FAIL
+ evidence
+ missing dimensions
+ cross-contamination risk
+ minimal fix recommendation


# Audit-to-Fix Closure

Generic Audit 結果不是最終報告終點。

Scoreboard / DMA Scoreboard / Performance / Coverage 的所有 actionable gaps：
→ workflow_findings.csv
→ consolidated fix
→ implementation
→ full re-verify
→ re-run Generic Audit
→ closure。
