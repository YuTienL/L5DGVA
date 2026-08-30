---
name: devops-pipeline
description: 將 Git commit/push 與 Linux Server build、target verify、LSF regression、monitor、report、signoff 連成 DevOps pipeline。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# DV DevOps Pipeline

Pipeline：

Developer/AI Change
→ Git Sync
→ Branch
→ Modify
→ Review
→ Commit
→ Push
→ CI/Preflight
→ Linux Server exact commit checkout
→ Environment source
→ BUILD
→ Target VERIFY
→ LSF Regression
→ Monitor
→ Failure Recovery
→ Regression Report
→ Signoff
→ optional Tag/Release

## Pipeline Stages

1. SOURCE
   repo/branch/SHA/submodule SHA

2. STATIC GATES
   syntax/config/schema/comment/naming/secret/artifact checks

3. BUILD
   Coverage OFF

4. TARGET VERIFY
   selected patterns

5. REGRESSION
   LSF; WAVE=0, PA=0, Coverage OFF

6. FAILURE CLOSURE
   log + WAVE=1 + fsdbreport + Verdi if needed + fix + rerun

7. REPORT
   build + verify + regression + failure cluster + environment identity

8. SIGNOFF
   exact source SHA + exact server SHA + reports + residual risk

## Trigger Model

支援：
- manual developer invocation
- push-triggered CI
- merge-request/pull-request validation
- nightly regression
- release/tag regression

若 project 沒有實際 CI server/tool config，不得 invent。
先讀 existing CI files/scripts，再補。
