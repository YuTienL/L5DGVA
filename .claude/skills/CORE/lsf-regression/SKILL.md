---
name: lsf-regression
description: Linux Server 上的 LSF regression manager，負責 testcase/seed/config/job submit、queue/resource 需求、run directory 與 result tracking。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# LSF Regression Manager

執行位置：已確認的 Linux Server / WORK_ENV_PATH。

預設：
Coverage=OFF
WAVE=0

每個 regression item 記錄：
TESTCASE,SEED,PROTOCOL,CONFIG,COMMAND_FILE,QUEUE,CORES,MEMORY,JOB_ID,RUN_DIR,LOG,WAVE,COVERAGE,STATUS

流程：
Regression Plan
→ resource request
→ bsub submit
→ job id capture
→ monitor
→ result classify

不要把 infrastructure failure 當 DUT FAIL。
若 bsub/LSF option 不清楚，遵守 tool knowledge gate：
project usage → local manual/help → official docs → credible web → BLOCKED/user。
