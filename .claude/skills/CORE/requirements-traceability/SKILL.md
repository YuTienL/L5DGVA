---
name: requirements-traceability
description: 建立 Spec/Requirement → vPlan → command.txt → Pattern/Scenario → VIP/UVM → Checker/Coverage → Regression Result → Signoff Evidence 的雙向追蹤。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Requirements Traceability

## 目的
Verification Signoff 不能只看 testcase PASS 或 coverage 百分比。
必須能回答：

「每一條 Design Requirement 是否有對應 Verification Evidence？」

## Trace Chain

SPEC / DESIGN REQUIREMENT
→ REQUIREMENT_ID
→ vPlan Item
→ Scenario
→ command.txt
→ Pattern/Testcase
→ branch-B Scenario
→ VIP Sequence/API
→ Checker / Scoreboard
→ Coverage
→ Regression Result
→ Signoff Evidence

並支援 reverse trace：
FAIL/Coverage Hole
→ Pattern
→ vPlan
→ Requirement。

## Requirement Sources
依 evidence priority：
1. Existing project requirement/vPlan files
2. Design specification
3. Programming guide
4. RTL parameters/defines/register behavior
5. Existing tests/commands
6. Git history/comments
7. Ask minimum user question

禁止無 evidence 自創 requirement。

## Required Fields
REQ_ID
SOURCE
SOURCE_LOCATION
SCOPE
SUBSYSTEM
INSTANCE
INTERFACE
PROTOCOL
REQUIREMENT
PRIORITY
VPLAN_ID
SCENARIO_ID
COMMAND_ID
PATTERN_ID
CHECKER_ID
COVERAGE_ID
REGRESSION_GROUP
LATEST_RESULT
EVIDENCE
STATUS
CONFIDENCE

## Gap Types
REQ_NO_VPLAN
VPLAN_NO_TEST
TEST_NO_CHECKER
TEST_NO_COVERAGE
COVERAGE_NO_REQUIREMENT
COMMAND_NO_VPLAN
PASS_NO_EVIDENCE
ORPHAN_TEST
ORPHAN_COVERAGE

所有 actionable gap 必須進 workflow closure loop。

## Signoff Gate
Requirement 狀態只允許：
VERIFIED
PARTIAL
BLOCKED
NOT_COVERED
ACCEPTED_RISK

High/Critical requirement 若非 VERIFIED 或明確 disposition，不得 Signoff。

## Output
`.dv-workflow/requirements_traceability.csv`
`.dv-workflow/requirements_gap_report.md`
