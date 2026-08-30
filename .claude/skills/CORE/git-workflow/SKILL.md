---
name: git-workflow
description: Generic DV Workflow 的 Git lifecycle：pull/sync、branch、commit、push、tag、rollback、traceability、submodule/superproject consistency。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Git Workflow

Git 是 DV Workflow 的正式 lifecycle，不只是最後 push。

標準順序：

SYNC
→ REVIEW
→ MODIFY
→ LOCAL VERIFY
→ COMMIT
→ PUSH
→ SERVER EXACT-COMMIT VERIFY
→ BUILD / VERIFY / REGRESSION
→ REPORT / SIGNOFF

## Pull / Sync

工作開始前：
- git status
- git remote -v
- git branch --show-current
- git fetch --all --prune
- 依 project policy 執行 pull/rebase/merge
- 檢查 uncommitted user changes
- 禁止覆蓋 unrelated user changes

不得在有未理解 local changes 時直接 pull --rebase 或 reset。

## Branch

支援：
- existing branch checkout
- create branch from current HEAD
- create branch from specific commit/tag
- branch existence check
- branch naming policy
- superproject/submodule branch alignment

禁止默認 force overwrite 已存在 branch。

## Commit

commit 前：
- diff review
- stale/unrelated comment cleanup
- semantic naming check
- generated/unwanted artifact check
- secrets check
- intended file scope check

Commit message 應描述：
scope + change + verification intent。

## Push

push 前強制：
- current branch確認
- upstream確認
- commit hash記錄
- no secrets
- no unrelated changes
- pre-push verification gate pass

禁止自動 `git push --force`。
需要 force push 時必須使用者明確要求。

## Tag / Release

支援：
- create/list/show tag
- annotated tag message
- push tag
- release evidence與regression report綁定

## Rollback

優先使用：
- revert commit
- checkout prior known-good commit
- new recovery branch

禁止自動 destructive：
git reset --hard
git clean -fd
force push
除非使用者明確要求且 scope 已確認。

## Submodule / Superproject

若存在 submodule：
- git submodule status
- git submodule sync --recursive
- git submodule update --init --recursive
- 記錄 superproject commit + submodule commit
- 驗證 branch/commit dependency

Signoff 必須能追溯：
superproject SHA
+ submodule SHA(s)
+ server exact SHA
+ regression report
