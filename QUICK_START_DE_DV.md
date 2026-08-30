> **See CREATE_ENVIRONMENT.md** for the current, consolidated procedural guide covering this topic.

# DE + DV Ultimate Industrial Workflow v10

## 定位
Generic Any Subsystem → Full SoC Level Verification + Git/DevOps。

## 啟動
```powershell
claude --dangerously-skip-permissions
```

## Git / DevOps Lifecycle
```text
GIT SYNC/PULL
→ BRANCH
→ MODIFY
→ REVIEW
→ COMMIT
→ PUSH
→ Linux Server exact SHA
→ BUILD
→ VERIFY
→ LSF REGRESSION
→ MONITOR
→ FAILURE RECOVERY
→ REPORT
→ SIGNOFF
→ optional TAG/RELEASE
```

## Git 安全原則
- 不自動 reset --hard
- 不自動 clean -fd
- 不自動 force push
- 不丟棄 unrelated user changes
- Server 必須驗證 exact pushed commit
- Submodule SHA 一併追蹤

## DevOps
先找既有：
.gitlab-ci.yml / GitHub Actions / Jenkinsfile / ci scripts / Makefile / LSF wrappers。
已有 pipeline 優先 EXTEND。


## Claude CLI / Superpowers / Workflow 啟動前檢查

PowerShell：

```powershell
.\.claude\tools\check-claude-dv-env.ps1 -ProjectRoot .
```

人工快速確認：

```powershell
claude --version
gci .\.claude\skills -Recurse -Filter SKILL.md | select FullName
gci .\.claude\agents -Filter *.md | select Name
Get-Content .\.claude\settings.json -Raw | ConvertFrom-Json
Get-Content .\.claude\settings.local.json -Raw | ConvertFrom-Json
```

進 Claude Code 後，再使用目前版本提供的 Plugins UI/command 確認：
- Superpowers installed
- Superpowers enabled
- plugin errors = none
- reload 後 agents/skills/hooks 狀態

正式啟動：

```powershell
claude --dangerously-skip-permissions
```

Readiness：
READY → 直接執行 DV Workflow
PARTIAL → 能執行的先執行
BLOCKED → 只修復 minimum required dependency


## Workflow Closure 鐵則

Workflow 結果出來後不能只給報告。

```text
Analyze
  ↓
Find ALL Issues + Recommendations
  ↓
Consolidate ALL Actionable Items
  ↓
Fix ALL In-Scope Items
  ↓
Build / Verify / WAVE / Regression
  ↓
Detailed Re-Check
  ↓
Re-run Original Audit
  ↓
New actionable issue?
 ├─ Yes → Fix Loop
 └─ No  → Signoff
```

最終狀態只允許：
CLOSED
BLOCKED
ACCEPTED_RISK
