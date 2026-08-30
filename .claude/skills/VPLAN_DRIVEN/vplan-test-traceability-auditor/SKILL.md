---
name: vplan-test-traceability-auditor
description: Audit Spec→vPlan→testcase→checker→coverage→execution evidence traceability.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# vplan-test-traceability-auditor

Audit Spec→vPlan→testcase→checker→coverage→execution evidence traceability.

Mandatory:
- vPlan first, testcase second.
- Every testcase references one or more vPlan requirement IDs.
- 100% is requirement accounting, not testcase count.
- Unsupported DUT waiver requires explicit current design-spec evidence and approval.
- UNKNOWN gaps cannot be auto-waived.
