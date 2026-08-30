---
name: remote-control-session-manager
description: Start and track Claude Code sessions used through Web/Mobile Remote Control.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Remote Control Session Manager
Start from Harness root with `claude remote-control`.
Persist only non-secret session metadata under `.dv-harness/remote-control/`.
Remote Control is transport; Graph/Blackboard/Memory/Iron Rules remain authoritative.

BUG FIX (2026-08-28, plan-remote-control-wiring): the actual state/audit
binding for this is `dv_harness/remote_control.py`, reachable via
`dv-harness remote-control {bootstrap,status,cmd}` -- there is no other real
code path. When a Web/Mobile Remote Control session starts, run
`dv-harness remote-control bootstrap` once to land the session on RUNNING
(never hand-write `.dv-harness/remote-control/session.json` directly). For
every incoming PAUSE/RESUME/TAKEOVER/REDIRECT/APPROVE/REJECT/STOP/STATUS/WHY/
EVIDENCE/REVIEW instruction, run `dv-harness remote-control cmd <COMMAND>
[--target-stage STAGE] [--reason TEXT]` -- this is the only path that goes
through the real supervisory/transition/audit/replay gates and applies the
matching real ControlPlane effect (PAUSE/RESUME/TAKEOVER/REDIRECT/APPROVE);
REJECT/STOP currently have no ControlPlane effect at all (see
remote_control.py's own docstring "KNOWN GAPS").
