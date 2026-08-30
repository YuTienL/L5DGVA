---
name: remote-executor
description: 從 PC 以固定 PUSH→BUILD→VERIFY→WAVE=1→fsdbreport 流程控制 Linux Server 驗證。
allowed-tools: Read Grep Glob PowerShell
---
# Remote Verification Executor

遵守 `iron-rules`。

1. PC PUSH
   - diff review
   - push
   - capture branch + commit hash

2. Server exact-commit sync
   - SSH
   - checkout/pull
   - verify remote HEAD equals expected hash

3. BUILD
   - canonical command
   - Coverage OFF
   - capture command/status/log

4. VERIFY
   - targeted testcase/scenario
   - Coverage OFF
   - capture status/log

5. WAVE=1 RUN
   - same representative scenario
   - Coverage OFF
   - waveform time0 -> simulation end
   - capture FSDB path

6. FSDBREPORT
   - canonical fsdbreport usage
   - verify scenario-critical signals/events/transactions
   - capture report/findings

禁止以 PC 端模擬執行取代 Server 驗證。


# SSH Context Gate

執行前必須取得 `remote-intake` PASS。

固定順序：

PC diff/review
→ PUSH
→ SSH 到使用者確認的 Linux Server
→ 驗證 user/hostname
→ cd 使用者確認的 workdir
→ 按順序 source 使用者確認的 environment
→ tool/environment preflight
→ sync/checkout exact pushed commit
→ BUILD (Coverage OFF)
→ VERIFY (Coverage OFF)
→ WAVE=1 run (time=0 到 simulation end, Coverage OFF)
→ fsdbreport
→ collect evidence
→ review/signoff

若 source command、tool command、workdir 或 remote commit 不正確，立即停止，不得猜。
