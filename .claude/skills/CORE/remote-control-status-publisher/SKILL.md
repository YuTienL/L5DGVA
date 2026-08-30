---
name: remote-control-status-publisher
description: Publish Web-friendly Harness status from Blackboard, jobs, findings, evidence and telemetry.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Remote Control Status Publisher
Publish workflow_id, execution_mode, stage, agents, server target, SHA, FSDB/VIP trace state, job summary, findings, approvals, next action, wall-clock and aggregate runtime.
Never claim server/VCS/waveform execution without runtime evidence.

BUG FIX (2026-08-28, plan-remote-control-wiring): `dv-harness remote-control
status` (dv_harness/remote_control.py's `get_status()`) is the real, read-only
source for the session/audit half of this publish -- current session.json
state plus the most recent audit entry. It does not by itself carry
workflow_id/stage/findings/etc.; combine it with the existing `dv-harness
status`/`dv-harness audit` output for the rest of what this skill publishes.
