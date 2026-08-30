---
name: single-sim-promotion
description: Single simulation 正式 PASS 後自動將 pattern + simulation options 加入或更新 Regression List。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Single Simulation Promotion

Promotion Gate：

Single Simulation PASS
+ no unexpected UVM_ERROR/UVM_FATAL
+ expected scenario complete
+ checker PASS
+ WAVE=1 representative run PASS
+ fsdbreport evidence PASS
+ reproducibility/review PASS
→ AUTO PROMOTE

自動保存：
pattern
command/scenario
simulation options
DUT/VIP config
seed policy
reproduce seed
timeout
regression group
priority
source

Regression defaults：
Coverage=OFF
WAVE=0
PA=0（除非 pattern/project 要求）

新 pattern：add。
既有 signature：update/re-enable。

vPlan traceability：
VP_ID → SCENARIO → COMMAND_ID → PATTERN_ID → REGRESSION_ENTRY
