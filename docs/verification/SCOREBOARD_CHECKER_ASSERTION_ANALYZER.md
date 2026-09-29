> See START_HERE.md for the canonical entry point and current mechanism overview; this page remains accurate for its specific topic.

# Scoreboard / Checker / Assertion Analyzer

Calibrated DUT Architecture + vPlan + Regression Evidence + Coverage
→ Observability Analysis
→ Placement Plan
→ Implementation Plan
→ Generate Scoreboard / Checker / Assertion Skeletons
→ Integrate
→ Compile / Smoke / Regression
→ Diagnostic/Coverage Review
→ Refine and Rerun.

Decision rule:
- End-to-end data/transaction comparison → Scoreboard
- Protocol/state/config/address semantic correctness → Checker
- Local temporal/handshake/reset/state invariant → Assertion

Every mechanism must trace to real architecture and verification requirements.
