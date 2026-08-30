---
name: verification-signoff
description: Evidence gate for PASS/PARTIAL PASS/BLOCKED/FAIL using readiness, project-model confidence, vPlan traceability, compile, test, regression, review and residual risk.
allowed-tools: Read Grep Glob PowerShell
---
# Verification Signoff

PASS requires evidence appropriate to scope:
- blocking project-model fields resolved
- root cause or implementation intent established
- intended diff reviewed
- compile/elaboration PASS
- original/representative targeted test PASS
- relevant regression PASS
- no unexplained blocker
- traceability/coverage impact understood

PARTIAL PASS:
targeted validation passes but broader evidence remains.

BLOCKED:
authoritative decision/dependency/tool/license/resource/server/access prevents safe completion.

FAIL:
validation remains failing or root cause unresolved.

Never convert BLOCKED to PASS by assumption.


# LSF/Verdi Signoff Requirements

適用時 PASS 還必須滿足：
- LSF regression completed
- lsf_jobs.csv 完整
- regression_results.csv 完整
- failure_clusters.csv 完整
- regression_report.md 已產生
- infra failures 已處理
- representative WAVE=1/fsdbreport 完成
- 必要時 Verdi debug 完成
