---
name: save-session
description: Snapshot DV Agent Harness L5's current run-state layer (state/control/blackboard/plans/react/agents/telemetry/config) to a named, restorable checkpoint before ending a session or trying something risky.
allowed-tools: Read Grep Glob PowerShell Skill
---
# save-session

Use this before ending a Claude Code session, or before any risky action
(a REDIRECT, a CORRECT, a stage retry after a bad PARTIAL), so the current
run can be returned to exactly if it goes wrong.

**What gets captured** (`dv_harness/session_snapshot.py::save_session`):
`.dv-harness/state.json`, `control.json`, `project_meta.json`, `config.json`,
`events.jsonl` (copied for reference only, never restored back -- see
`restore-session`), and the `blackboard/`, `plans/`, `react/`, `agents/`,
`telemetry/`, `lsf/` directories.

**What deliberately does NOT get captured**: the Memory Hierarchy
(`.dv-harness/memory/`, all 5 levels) and Corner-Case Library. Those are
durable, verified engineering knowledge (CLAUDE.md: "Verification Memory
stores historical verified engineering knowledge") -- a session
save/restore must never let an old snapshot regress knowledge accumulated
since. Static policy config (`graph/`, `workflow/`, `governance/`,
`inference/`, `qualification/`) is also excluded -- it defines how the
harness behaves, not what state a run is in.

**How to invoke:**
- CLI: `dv-harness save-session [--name NAME] [--note NOTE]` (omit `--name`
  for an auto timestamp name).
- Web GUI: the "Session Save / Restore" card's Save button.
- Both call the exact same `session_snapshot.save_session()` -- no
  behavior difference between entry points.

A name that already exists is refused (`FileExistsError`), not silently
overwritten -- pick a new name, or use `restore-session --list` / the GUI
table first to see what already exists.
