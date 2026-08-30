---
name: coverage-by-port-audit
description: Generic functional coverage audit across subsystem-to-SoC ports/interfaces/instances and protocol dimensions.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Generic Coverage Collector Audit

Coverage 應能表達：
instance
port/interface
protocol
mode/speed/gen/rate
role
traffic/transfer/transaction type
direction/channel/stream
resource
error/state/power/reset
concurrency

重要 cross 由 design topology + protocol profile 推導。
不能只有 global aggregate coverage。

輸出：
`.dv-workflow/coverage_by_port_audit.csv`
