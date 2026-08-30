---
name: remote-environment
description: 定義 PC 開發端與 Linux Server 驗證端的環境契約、repository、SSH、tool、LSF、waveform 與結果位置。
allowed-tools: Read Grep Glob PowerShell
---
# PC / Linux Server 環境

PC / Windows：
- Claude Code (`claude --dangerously-skip-permissions`)
- source/TB/command/vPlan development
- project model / diff / review / push

Linux Server：
- exact pushed commit checkout
- VCS/Verdi/VIP
- build
- verify
- WAVE=1 run
- fsdbreport
- regression/LSF
- logs/waveforms/results

自動探索或從 local config 取得：
REMOTE_HOST
REMOTE_USER
REMOTE_PROJECT_ROOT
REMOTE_REPO
REMOTE_BRANCH
SSH command
SERVER_ENV_SETUP
BUILD_COMMAND
VERIFY_COMMAND
RUN_COMMAND
FSDBREPORT_COMMAND
LSF/queue settings
wave/result directories

password/private key/token 不寫入 project artifact。


# Remote Context Mandatory Gate

正式 Server 驗證前，Remote Context 必須明確：
SSH host、user、shell、source commands、Linux workdir。

如果 project evidence 無法唯一確定，必須詢問使用者，不可自行挑 server/source/workdir。
Authentication secret 不落盤。
