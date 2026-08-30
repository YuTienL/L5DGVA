> **Superseded.** This document describes an earlier edition. See START_HERE.md for the current canonical entry point and SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md for the current architecture.

# DV Agent Harness Edition v15

## 定位

v15 = v14 Generic DV Workflow + Persistent Agent Harness。

```text
DV Agent Harness
  ├─ State Machine
  ├─ Resume / Retry
  ├─ Project State
  ├─ Findings / Requirements
  ├─ Git / Server SHA
  ├─ Regression State
  └─ Dashboard
          ↓
Claude Code / Claude Code SDK
          ↓
7 DV Agents + Existing Skills
          ↓
Git / SSH / Linux
          ↓
VCS / VIP / Verdi / fsdbreport / LSF
```

## 安裝

Python 3.10+。

Harness core 不需要額外 Python package：

```powershell
python -m dv_harness --help
```

若要使用 Python SDK adapter：

```powershell
pip install claude-code-sdk
```

預設 adapter 是 `cli`，透過 Claude Code headless mode：

```text
claude -p ... --output-format json
```

## 一鍵啟動

```powershell
.\START_DV_HARNESS.ps1 `
  -ProjectRoot . `
  -Goal "詳細分析並完成目前 subsystem verification" `
  -Loop
```

不加 `-Loop` 時，只執行目前 stage，適合人工 gate。

## 查看狀態

```powershell
.\DV_HARNESS_STATUS.ps1
```

或：

```powershell
python -m dv_harness --project-root . status
```

## Dashboard

```powershell
.\START_DV_HARNESS_DASHBOARD.ps1
```

瀏覽：

```text
http://127.0.0.1:8765
```

Dashboard v15 為 read-only，避免 UI 直接進行危險 Git/Server 操作。

## 切換 SDK Adapter

`.dv-harness/config.json`：

```json
{
  "adapter": "sdk"
}
```

SDK adapter 為 optional。若企業環境要求固定 CLI 版本、proxy、SSO 或既有 Claude Code login，建議維持 `cli`。

## Persistent State

`.dv-harness/`

- state.json
- events.jsonl
- project.json
- findings.csv
- requirements.csv
- soc_scenarios.csv
- change_impact.csv
- regression_selection.csv

## Stage State Machine

ENV_CHECK
→ INTAKE
→ DISCOVERY
→ PROJECT_MODEL
→ REQUIREMENTS_TRACEABILITY
→ SOC_SCENARIO_PLANNER
→ INFRASTRUCTURE_AUDIT
→ VPLAN
→ COMMAND_PATTERN
→ IMPLEMENT
→ CHANGE_IMPACT
→ GIT_SYNC
→ GIT_PUSH
→ SERVER_SYNC
→ BUILD
→ VERIFY
→ WAVE_ANALYSIS
→ REGRESSION_SELECT
→ REGRESSION
→ REGRESSION_MONITOR
→ FAILURE_RECOVERY
→ RE_AUDIT
→ REQUIREMENT_CLOSURE
→ SIGNOFF
