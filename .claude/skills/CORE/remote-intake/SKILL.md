---
name: remote-intake
description: 取得並驗證 Linux Server 執行環境；若無可靠 project evidence，向使用者詢問 SSH server、account、shell、source commands 與工作路徑。密碼只供互動登入，不落盤。
allowed-tools: Read Grep Glob PowerShell
---
# Remote Linux Execution Intake

## 目的
PC/Windows 是開發與 Claude orchestration 端；Linux Server 是 build/verify/run/waveform 執行端。

## 先自行搜尋
依序查：
1. project remote/server config
2. build/run/regression scripts
3. README / environment setup docs
4. existing SSH wrappers / aliases / scripts
5. environment scripts
6. recent reliable project evidence

## 無法可靠確定時，必須詢問使用者
集中詢問最少必要資訊：

- `SSH Server`：hostname 或 IP
- `User Account`
- `Remote Shell`：bash / sh / csh / tcsh / zsh
- `Environment Source Commands`：登入後需要 source 哪些檔案，按順序
- `Linux Working Directory`：build / verify / run 所在路徑
- 若 build/run/regression 使用不同目錄，分別詢問
- Authentication 是否已由 SSH key/agent 處理

Password 若登入工具需要，只能互動輸入。
禁止保存 password/token/private key 到：
`.claude`, `.dv-workflow`, settings*.json, logs, scripts, command.txt, Git。

## 不得猜測
若找到多台 server、多個 source flow 或多個可能 workdir，且無法由 evidence 判定，必須讓使用者選擇。

## Preflight
登入後、BUILD 前確認：
- hostname
- whoami
- pwd / workdir exists
- shell
- source commands 成功
- git remote / branch / HEAD
- vcs / verdi / fsdbreport / bsub 等「本次實際需要」的工具是否存在
- 必要 license/VIP environment 是否存在

工具找不到或用法不清楚，套用 iron-rules 的「先手冊，再官方網路/可信網路」規則。

## 非敏感 Context
可保存：
host/user/shell/workdir/source commands/branch/tool paths。
不得保存 authentication secret。


# Reference Environment Intake

如果本次 Workflow 宣告或需要使用既有 USB UVM Reference：

除了 SSH Server / User / Shell / Source Commands / WORK_ENV_PATH 外，
還必須確認：

- `REFERENCE_ENV_PATH`
- reference branch/tag/commit
- reference access mode（預設 READ_ONLY）

如果 reference 與 work environment 位於不同 Linux Server，兩邊 context 都必須分別確認。

不可因為找到一個 USB project path 就自行假設它是 reference。


# Regression Tool Preflight

若本次要跑 regression/debug，preflight 檢查實際需要的：
bsub
bjobs
bqueues / equivalent
VCS runtime
Verdi
fsdbreport

不要求未使用工具一定存在。
