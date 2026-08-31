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

## Transport

一旦 `remote-intake`/SSH intake 已確認、且 `remote_exec.py --status` 回報
`READY`，上面每一步的實際指令都透過 `remote_exec.py "<cmd>"` 執行（見
`remote-linux-execution-bridge/SKILL.md` 的 Persistent Relay 段落），不用
再一條條叫使用者手動貼指令。長跑的 BUILD/VERIFY/regression 一樣不能用前景
方式跑，用 `bsub`/`nohup ... &` 送出，再用短的 `remote_exec.py "bjobs <id>"`
輪詢。

## PUSH / Server Sync — 無 git 變體

當 PC 與 Linux workdir 之間沒有 git remote 時（例如 `remote_exec.py "git
rev-parse --is-inside-work-tree"` 回傳失敗），Step 1-2 改用：

1. **PUSH**：整包用 `tar czf` 打包後 `remote_exec.py --put`，再
   `remote_exec.py "tar xzf ... -C <remote-dir>"` 展開；單一檔案直接
   `remote_exec.py --put <local> <remote>`。
2. **Server sync 驗證**：用 `source_identity.py` 的 md5sum 三方比對 +
   `SOURCE_ID = sha256(...)` 取代「verify remote HEAD equals expected
   hash」，記錄到 Blackboard 取代 `git_sha`/`server_sha`（兩者維持 `null`,
   不強塞無意義值）。

有 git remote 的專案維持原本 git-based 流程不變，這是額外的、per-project
選項，不是取代。


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
