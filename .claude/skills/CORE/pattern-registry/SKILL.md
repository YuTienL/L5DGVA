---
name: pattern-registry
description: 管理 User/DV Workflow 共同的 Pattern Registry、來源、版本、simulation options、promotion 與 regression enable 狀態。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Pattern Registry

Pattern 來源：
- USER
- DV_WORKFLOW
- REFERENCE_DERIVED

維護：
`.dv-workflow/pattern_registry.csv`
`.dv-workflow/regression_patterns.csv`
`.dv-workflow/promotion_history.csv`

Pattern 至少記錄：
PATTERN_ID,NAME,SOURCE,PROTOCOL,ROLE,COMMAND_FILE,TESTCASE,SIM_OPTIONS,DUT_CONFIG,VIP_CONFIG,SEED_POLICY,REPRO_SEED,REGRESSION_GROUP,PRIORITY,STATUS,SIGNATURE

Pattern signature 用於去重：
protocol + testcase + command/scenario + critical sim options + DUT config + VIP config

相同 signature：
更新 metadata/last-pass，不建立重複 entry。
