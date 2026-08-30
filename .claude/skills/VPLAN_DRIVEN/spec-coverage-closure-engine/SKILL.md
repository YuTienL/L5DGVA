---
name: spec-coverage-closure-engine
description: Drive requirement-level coverage gaps to closure until 100% Spec Coverage Accounting is reached.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# spec-coverage-closure-engine

Drive requirement-level coverage gaps to closure until 100% Spec Coverage Accounting is reached.

Mandatory:
- vPlan first, testcase second.
- Every testcase references one or more vPlan requirement IDs.
- 100% is requirement accounting, not testcase count.
- Unsupported DUT waiver requires explicit current design-spec evidence and approval.
- UNKNOWN gaps cannot be auto-waived.
