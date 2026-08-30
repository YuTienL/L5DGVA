---
name: first-failure-waveform-rerun
description: When a no-FSDB simulation fails, automatically plan a targeted rerun with waveform enabled and terminate at the first validated failure/error/fatal/missing/mismatch event.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# First-Failure Waveform Rerun

## Trigger
Initial simulation result = FAILED.

Initial run is normally:
- FSDB OFF
- VIP trace/report optional
- normal sim.log/assertion/scoreboard/checker evidence enabled

## Debug Rerun
After FAILED:
1. Analyze first-run evidence.
2. Determine the earliest actionable failure signature.
3. Invoke `waveform-dump-scope-planner`.
4. Ask/confirm dump scope and level/depth.
5. Launch a dedicated debug rerun with waveform enabled.
6. Stop at the first validated failure point.

## First-failure stop conditions
Stop the debug rerun when the first relevant terminal/actionable event is confirmed, including:
- UVM_ERROR
- UVM_FATAL
- explicit FAIL
- assertion failure
- scoreboard mismatch
- transaction mismatch
- expected item missing
- response missing / timeout attributable to the failure
- protocol checker failure
- project-defined fatal/error signature

## Important distinction
Do not stop on benign warnings or allowlisted messages.
The stop condition must be relevant to the target failure being reproduced.

## Timing capture
Record:
- first failure simulation time
- failure signature
- failing component / checker
- exact log line / evidence
- waveform stop time
- optional post-failure margin

## Post-failure margin
Default behavior:
stop at first failure time or a very small configured margin after it.

If protocol/debug context requires a small tail window, use:
FAIL_TIME + POST_FAIL_MARGIN

Do not run the full testcase unless evidence after the first failure is explicitly required.

## Efficiency
Goal:
Minimum sufficient debug rerun duration
+
Minimum sufficient waveform scope
+
Minimum sufficient waveform depth

## Evidence
The rerun must produce:
- sim.log
- failure signature
- failure timestamp
- targeted FSDB
- optional VIP trace/report
- exact Git/Server SHA
- exact testcase/options/config identity
