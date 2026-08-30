---
name: vplan-first-generator
description: Generate the vPlan from current specification evidence before testcase creation.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# vplan-first-generator

Generate the vPlan from current specification evidence before testcase creation.

Mandatory:
- vPlan first, testcase second.
- Every testcase references one or more vPlan requirement IDs.
- 100% is requirement accounting, not testcase count.
- Unsupported DUT waiver requires explicit current design-spec evidence and approval.
- UNKNOWN gaps cannot be auto-waived.
