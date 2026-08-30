---
name: claude-environment-readiness
description: DV Workflow 啟動前確認 Claude Code CLI、Superpowers、dv-workflow、required skills、agents、hooks、settings 與 project/user scope 是否完整可用。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Claude CLI Environment Readiness Gate

任何 `/dv-workflow` 正式分析/修改前，先做 Claude Environment Readiness。

## 1. Claude CLI
確認：
- `claude --version`
- executable/path 可用
- project root 正確
- `.claude/` 可讀
- 啟動模式符合 project policy

本專案預期啟動：
`claude --dangerously-skip-permissions`

只記錄是否符合，不把 credential/password 寫入檔案。

## 2. Plugin / Superpowers
確認 Claude Code plugin 狀態，至少檢查：
- superpowers 是否 installed
- 是否 enabled
- reload 後是否成功
- plugin errors 是否存在

若 Claude CLI 版本提供 `/plugins` 或對應 plugin UI/command：
使用官方/現有介面確認，不猜 plugin storage path。

若 Superpowers 不存在：
STATUS = PARTIAL/BLOCKED（依 task 是否依賴）
並提供最小安裝/啟用建議。

## 3. Workflow Skill
確認 project scope：
`.claude/skills/CORE/dv-workflow/SKILL.md`

並確認必要 Core Skills 存在。

至少：
dv-workflow
dv-intake
protocol-router
subsystem-to-soc-verification
generic-infrastructure-audit
failure-triage
systematic-debug
verification-signoff
vcs-build
git-workflow
devops-pipeline
claude-environment-readiness

## 4. Protocol Profiles
依 request 需要檢查：
USB
PCIe
Ethernet
AMBA
MIPI CSI-2
MIPI DSI
CAN-FD

不要求每次 task 載入所有 protocol skill；
只要求 task 所需 profile 可用。

## 5. Agents
確認 `.claude/agents/*.md`。

預期 7 Agents：
- dv-lead
- analysis-agent
- implementation-agent
- build-agent
- debug-agent
- regression-agent
- review-agent

檢查：
存在
可讀
名稱不重複
責任分工存在

## 6. Settings
確認：
`.claude/settings.json`
`.claude/settings.local.json`

檢查：
- JSON syntax
- hooks/plugin related config
- project-local overrides
- 不包含 password/token/secret

## 7. Skills Inventory
PowerShell 建議：
`gci .\.claude\skills -Recurse -Filter SKILL.md | select FullName`

並產生：
`.dv-workflow/claude_environment_inventory.csv`

記錄：
TYPE,NAME,SCOPE,PATH,EXPECTED,FOUND,ENABLED,STATUS,NOTES

## 8. Readiness Result

READY:
Claude CLI + required workflow + required agents + task-required skills 都可用。
→ 直接進入 workflow。

PARTIAL:
核心可執行，但 optional plugin/profile/skill 缺少。
→ 能做的先做，缺口最小化處理。

BLOCKED:
Claude CLI / dv-workflow / required agent / task-critical profile 缺失。
→ 只詢問或修復 minimum required information。

## 9. 禁止
- 不因看到 `.claude/skills` 就假設 plugin skill 已安裝
- 不因 plugin enabled 就假設 project workflow skill 完整
- 不把 user scope / project scope skill 混為一談
- 不 invent Claude CLI command；不確定時先查 `claude --help` 或現有官方 CLI help
