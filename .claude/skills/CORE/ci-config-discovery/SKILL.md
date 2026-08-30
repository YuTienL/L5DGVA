---
name: ci-config-discovery
description: 發現 project 既有 GitLab CI/GitHub Actions/Jenkins/其他 CI 與 DV regression scripts，避免另造一套衝突 pipeline。
allowed-tools: Read Grep Glob PowerShell
---
# CI / DevOps Discovery

先搜尋：
.gitlab-ci.yml
.github/workflows/*
Jenkinsfile
azure-pipelines.yml
ci/
scripts/ci*
scripts/regression*
Makefile targets
LSF wrappers
project docs

分析：
- trigger
- branch policy
- build stage
- verification stage
- regression stage
- report/artifact path
- secret handling
- runner/server model

如果已有 pipeline：
優先 EXTEND，不重造。

如果沒有：
產生 minimal integration plan，不假設 organization-specific server/token。
