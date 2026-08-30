---
name: vplan-driven-testcase-generator
description: Generate testcases strictly from vPlan requirements with full requirement traceability.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# vplan-driven-testcase-generator

Generate testcases strictly from vPlan requirements with full requirement traceability.

Mandatory:
- vPlan first, testcase second.
- Every testcase references one or more vPlan requirement IDs.
- 100% is requirement accounting, not testcase count.
- Unsupported DUT waiver requires explicit current design-spec evidence and approval.
- UNKNOWN gaps cannot be auto-waived.
