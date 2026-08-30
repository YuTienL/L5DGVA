---
name: dut-unsupported-waiver-manager
description: Waive only features explicitly unsupported by current DUT design specification, with evidence and approval.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# dut-unsupported-waiver-manager

Waive only features explicitly unsupported by current DUT design specification, with evidence and approval.

Mandatory:
- vPlan first, testcase second.
- Every testcase references one or more vPlan requirement IDs.
- 100% is requirement accounting, not testcase count.
- Unsupported DUT waiver requires explicit current design-spec evidence and approval.
- UNKNOWN gaps cannot be auto-waived.
