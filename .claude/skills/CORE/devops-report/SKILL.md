---
name: devops-report
description: 產生 commit-to-signoff DevOps traceability report，連結 Git、Linux Server、LSF regression、waveform/debug evidence。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# DevOps Traceability Report

輸出：
`.dv-workflow/devops_report.md`
`.dv-workflow/devops_trace.csv`

至少記錄：
REPO
REMOTE
BRANCH
COMMIT_SHA
SUBMODULE_SHAS
AUTHOR/WORKFLOW_SOURCE
PUSH_STATUS
SERVER
SERVER_WORKDIR
SERVER_SHA
ENV_SOURCE
BUILD_RESULT
TARGET_VERIFY_RESULT
LSF_REGRESSION_ID/SUMMARY
FAILURE_CLUSTERS
WAVE_FSDB_EVIDENCE
FSDBREPORT
VERDI_USED
REGRESSION_REPORT
SIGNOFF_STATUS

任何 source SHA 不一致 → BLOCKER。
