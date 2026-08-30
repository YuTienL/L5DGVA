> See START_HERE.md for the canonical entry point and current mechanism overview; this page remains accurate for its specific topic.

# Stage Execution Profile

Second-model telemetry is mandatory:

- Stage Wall Clock = user-observed elapsed time.
- Aggregate Agent Runtime = sum of all agent runtimes inside the stage.
- Parallel Saving = Aggregate Agent Runtime - Stage Wall Clock.
- Parallelism Efficiency = Parallel Saving / Aggregate Agent Runtime.
- Token usage = provider-reported actual usage only; never estimated.

Example:
DUT RTL Agent 180s, PHY 240s, Register 150s, VIP 300s.
Aggregate Agent Runtime = 870s; Stage Wall Clock = 300s; Parallel Saving = 570s; Efficiency = 65.5%.
