---
name: verification-change-impact
description: 將 Git/RTL/spec/config/VIP/UVM 變更映射到 hierarchy、requirements、vPlan、patterns、coverage 與 regression，產生 verification-aware regression selection。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Verification Change Impact Analysis

## 目的
Git change 不應只觸發「全部 regression」或「只跑改到的 testcase」。

建立：
CHANGE
→ DESIGN IMPACT
→ REQUIREMENT IMPACT
→ VPLAN IMPACT
→ PATTERN IMPACT
→ CHECKER/COVERAGE IMPACT
→ REGRESSION SELECTION
→ SIGNOFF IMPACT

## Change Sources
- git diff / commit range
- RTL
- parameters/defines
- register/config
- firmware command
- command.txt
- VIP config/source
- UVM env/sequence/checker
- vPlan/spec
- build/regression scripts

## Impact Dimensions
FILE
MODULE/CLASS
HIERARCHY
SUBSYSTEM
INSTANCE
PORT/INTERFACE
PROTOCOL
SHARED_RESOURCE
REQUIREMENT_ID
VPLAN_ID
PATTERN_ID
COVERAGE_ID
REGRESSION_GROUP

## Regression Selection
輸出至少三層：

TARGETED
直接受影響 testcase/pattern。

DEPENDENCY
共享 hierarchy/resource/protocol/requirement 的相關 regression。

SAFETY
固定 smoke/sanity/critical-path regression，防止 impact model 漏判。

不得因 impact analysis 而移除 project mandatory signoff regression。

## Risk
HIGH：
RTL control/data path、shared resource、DMA、reset、protocol behavior、checker infrastructure。

MEDIUM：
local config/sequence/test changes。

LOW：
純文件/不影響 executable behavior 的變更，但仍需 evidence。

## Git/DevOps Integration
每次 commit/push 記錄：
BASE_SHA
HEAD_SHA
CHANGED_FILES
IMPACTED_REQUIREMENTS
IMPACTED_VPLAN
SELECTED_PATTERNS
SELECTED_REGRESSION
SAFETY_REGRESSION
RESULT

Server exact SHA gate 仍強制。

## Output
`.dv-workflow/change_impact.csv`
`.dv-workflow/regression_selection.csv`
`.dv-workflow/change_impact_report.md`

任何 impact gap / unknown dependency：
CONFIDENCE 降低。
必要時擴大 regression，不得冒險縮小。
