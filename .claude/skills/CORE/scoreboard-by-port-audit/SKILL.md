---
name: scoreboard-by-port-audit
description: Generic scoreboard isolation/concurrency audit for any subsystem or SoC.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Generic Scoreboard By-Port/Interface/Instance Audit

檢查：
- per instance / port / interface expected state
- actual state
- correlation key
- direction/channel/stream/tag/id
- reset/state isolation
- concurrent traffic
- shared-resource exception
- out-of-order semantics where applicable
- cross-port/interface contamination
- legal heterogeneous combinations

單一 testcase/單 port PASS 不代表 generic capability PASS。

輸出：
`.dv-workflow/scoreboard_by_port_audit.csv`
