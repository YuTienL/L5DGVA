---
name: vplan-regeneration-on-spec-change
description: Diff new specification revisions, update vPlan and regenerate/requalify impacted verification artifacts.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# vplan-regeneration-on-spec-change

Diff new specification revisions, update vPlan and regenerate/requalify impacted verification artifacts.

Mandatory:
- vPlan first, testcase second.
- Every testcase references one or more vPlan requirement IDs.
- 100% is requirement accounting, not testcase count.
- Unsupported DUT waiver requires explicit current design-spec evidence and approval.
- UNKNOWN gaps cannot be auto-waived.
