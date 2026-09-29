---
name: git-push-gate
description: Git push 前的 industrial pre-push gate，確保 scope、diff、secret、commit、verification metadata 正確。
allowed-tools: Read Grep Glob PowerShell
---
# Git Push Gate

Push 前必須確認：
- correct repo
- correct remote
- correct branch
- expected upstream
- clean/intended working tree
- diff reviewed
- no secrets/password/token/key
- no generated waveform/huge artifacts accidentally staged
- commit message valid
- required local checks pass
- exact commit SHA captured

標準 push：
git push -u origin <branch>
或 project-defined push command。

禁止自動 force push。

## PR-Only Merge Policy (main/master)

禁止 agent 直接 push 或 merge 進 `main`/`master`。Agent 可以 branch/commit/
開 PR (`gh pr create`)，但合併必須經過 human review 才是最後 gate -- 見
CLAUDE.md「gh CLI + PR-Only Governance Policy」章節。實際 enforcement 是
`tools/git-hooks/pre-push` + `pre-merge-commit`（呼叫 `dv-harness
git-guard`，邏輯在 `dv_harness/git_governance.py`），不是只有這份文件的
文字約束 -- 每次判斷都會記錄到 `.dv-harness/events.jsonl` 的
`GIT_GUARD_DECISION` 事件，供 `audit-change-governance-agent` 事後追溯。
