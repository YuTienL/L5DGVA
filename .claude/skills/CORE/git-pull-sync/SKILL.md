---
name: git-pull-sync
description: 安全同步 remote Git 狀態，避免覆蓋 local/user changes，並處理 branch/upstream/submodule。
allowed-tools: Read Grep Glob PowerShell
---
# Git Pull / Sync Gate

執行前：
git status --porcelain
git branch --show-current
git remote -v
git fetch --all --prune

若 local changes：
- 分析是否為本次 workflow changes
- 不得擅自 stash/drop/reset user changes
- 若會衝突，標示 BLOCKED 或建立安全策略

依 project policy：
git pull --ff-only
或
git rebase origin/<branch>
或
project-defined sync script

禁止猜 project pull policy。

Submodule：
git submodule sync --recursive
git submodule update --init --recursive

輸出：
branch
local SHA
remote SHA
ahead/behind
submodule SHA
sync status
