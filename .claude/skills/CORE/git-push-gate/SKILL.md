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
