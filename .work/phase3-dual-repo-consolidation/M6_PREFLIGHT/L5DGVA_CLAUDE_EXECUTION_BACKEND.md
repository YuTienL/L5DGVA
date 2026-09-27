# L5DGVA Claude Execution Backend

Real facts, discovered live before implementation (`M7_CLAUDE_WORKER_LIVE_QUALIFICATION.md`
has the full transcripts):

```
CLAUDE_CLI_VERSION = 2.1.283 (Claude Code)
SUPPORTED_WORKER_INVOCATION = claude -p <objective> --output-format json
  --json-schema <AgentRunResult schema> --restricted --tools <profile tools>
  --allowedTools <profile patterns> --permission-mode <profile mode>
  --add-dir <working_directory>   (subprocess.Popen, cwd=working_directory)
AUTHENTICATION_MODE_USED = existing claude.ai OAuth session (claude auth status)
WORKER_OUTPUT_MODE = single JSON envelope on stdout; is_error / subtype /
  terminal_reason / permission_denials; structured_output holds the
  schema-shaped result when --json-schema was satisfied
EXIT_STATUS_BEHAVIOR = 0 on success; non-zero on real failure (1 observed),
  with is_error/terminal_reason inspectable in the same JSON even when the
  exit code alone is ambiguous; a subprocess-level wall-clock timeout (this
  module's own, not a CLI flag) cleanly terminates a runaway worker
```

## Why `--json-schema` + `--output-format json`, not free text

The requirements doc's own Worker Output contract names 13 structured
fields. `--json-schema` is a real, documented flag ("JSON Schema for
structured output validation") -- passing our `AGENT_RUN_RESULT_SCHEMA`
gets a genuinely validated, machine-parseable result without inventing any
protocol of our own or asking the worker to format Markdown we would then
have to re-parse ourselves (the exact class of fragility M7's own
`md_kv_codec.py` work spent two remediation rounds closing). "No human
stdout interpretation is required" (requirements doc) is satisfied
literally: `structured_output` is a real dict, not text a human reads.

## Why `--restricted` + a named tool profile, not `--dangerously-skip-permissions`

`--restricted` is documented to remove Bash/PowerShell/REPL/WebFetch unless
`--tools` names them, confine file tools to the declared working
directory, and refuse `bypassPermissions` outright. Verified live (Q5/Q6 in
the qualification doc): a worker under `--restricted` could not write
outside its working directory even when explicitly instructed to try.
`--dangerously-skip-permissions` was never used for a mutation-capable
profile -- `CLAUDE_IMPLEMENTATION_PROFILE` instead uses `acceptEdits` (a
real, named, narrower permission mode: it auto-approves the SPECIFIC edits
the granted tools can make, never a blanket bypass) combined with a
CLOSED tool allowlist, which is the actual safety boundary
(`safe_tool_profile.py`).

## Failure classification (`classify_worker_output()`)

```
exit_code != 0            -> FAILED (never PASS)
envelope["is_error"]      -> FAILED (never PASS)
no `structured_output`    -> FAILED (a worker that didn't even report is not a PASS)
structured but scope-violating FILES_CHANGED -> FAILED, regardless of the worker's own claimed run_status
```

Confirmed with 4 mutation controls (removing each check independently
fails a real test each time): "no exit_code/is_error check", "no
duplicate/idempotency check", "no scope enforcement", "no Human Gate
check".

## Authentication

Reused exactly as instructed: the SAME already-logged-in `claude.ai`
session this very Claude Code session runs under. No `ACCESS_AUTHORIZATION_
REQUIRED` HumanGate was needed because no new/separate access was
required -- `claude auth status` confirmed an existing, working login
before any worker was designed.

## Status

`CLAUDE_EXECUTION_BACKEND=IMPLEMENTED_AND_LIVE_QUALIFIED` (6 real
subprocess qualifications, including a real mutation-capable run that
created a file, and a real sandbox-escape probe that was correctly
refused).
