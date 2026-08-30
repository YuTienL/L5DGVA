---
name: performance-by-port-audit
description: Generic performance calculator audit across any subsystem or SoC ports/interfaces/instances.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Generic Performance Calculator Audit

檢查：
- per instance/port/interface counters
- start/end time window
- bytes/packets/transactions
- throughput/bandwidth
- latency
- utilization
- stall/backpressure/wait-state
- protocol mode/speed/gen/rate/width/lane
- mixed concurrent traffic

禁止只有 global aggregate 就宣稱 by-port support 完整。

輸出：
`.dv-workflow/performance_by_port_audit.csv`
