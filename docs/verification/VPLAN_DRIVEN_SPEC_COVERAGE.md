> See START_HERE.md for the canonical entry point and current mechanism overview; this page remains accurate for its specific topic.

# vPlan-Driven Test Generation & 100% Spec Coverage

Current Spec → Requirement Extraction → vPlan → Requirement IDs/Support Status
→ Testcase Generation → Checker/Scoreboard/Assertion/Coverage
→ Compile/Smoke/Regression → Evidence → Requirement VERIFIED
→ Coverage Gap Loop → 100% Spec Coverage Accounting.

Coverage credit:
- VERIFIED: credit.
- WAIVED: credit only when DUT is explicitly unsupported in current design spec, waiver has evidence, and waiver is approved.
- NOT_APPLICABLE: credit when validated.
- PLANNED / IMPLEMENTED / BLOCKED / UNKNOWN: zero final credit.

A testcase must never exist without one or more vPlan requirement IDs.
