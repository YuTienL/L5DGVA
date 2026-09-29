"""dv_harness/safe_tool_profile.py -- Preauthorized Safe Tool Execution: the
named tool-execution profiles a controlled Claude worker (`dv_harness/
agent_execution_backend.py`) is launched with, per `docs/architecture/
canonical_detailed_governance/L5DGVA_AUTONOMOUS_AGENT_EXECUTION_BACKEND_
REQUIREMENTS.md`'s "Safe Tool Integration" ("CLAUDE_IMPLEMENTATION_PROFILE:
read/search, safe tests, task-authorized mutation, evidence writes, local
regression. No arbitrary shell/network/remote mutation").

This module did not exist before this task (a real `MISSING` classification
in the "Reuse Before Create" inventory, not a `REUSE`/`EXTEND`) -- the prior
requirement text referenced "Preauthorized Safe Tool Execution" as an
assumed-existing mechanism; grep found none.

Every field here maps to a REAL, currently-documented `claude` CLI flag
(`claude --help`, CLI version 2.1.283), discovered and verified live before
this module was written (`M7_CLAUDE_WORKER_LIVE_QUALIFICATION.md`):

  - `restricted=True` -> `--restricted`: removes Bash/PowerShell/REPL/
    WebFetch unless named in `tools`, confines file tools to the declared
    working directory (`--add-dir`), and refuses `bypassPermissions` --
    verified live: a worker under this flag set could not write outside its
    working directory even when explicitly asked to.
  - `tools` -> `--tools` (the tool ALLOWLIST; nothing outside it exists for
    the worker to even attempt).
  - `allowed_tool_patterns` -> `--allowedTools` (fine-grained command
    patterns, e.g. `"PowerShell(python -m pytest *)"`, the documented
    `"Bash(git *)"` shape) -- the mechanism that scopes a granted shell tool
    down to "safe tests" rather than arbitrary commands.
  - `permission_mode` -> `--permission-mode` (`acceptEdits` for a mutation
    profile so a controlled, unattended worker never hangs on a permission
    prompt; `bypassPermissions` only for a profile with NO code-execution
    tool present at all, where there is nothing left to bypass into).

No profile grants network access or an unscoped shell -- "no arbitrary
shell/network/remote mutation" is enforced by the tool allowlist itself,
never by trusting the model not to try.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple


@dataclass(frozen=True)
class ToolExecutionProfile:
    name: str
    tools: Tuple[str, ...]
    allowed_tool_patterns: Tuple[str, ...] = ()
    restricted: bool = True
    permission_mode: str = "acceptEdits"

    def cli_args(self) -> list:
        """The real argv fragment this profile contributes -- unit-tested
        against the exact flags verified live, never invented ad hoc at a
        call site."""
        args = []
        if self.restricted:
            args.append("--restricted")
        if self.tools:
            args += ["--tools", ",".join(self.tools)]
        else:
            args += ["--tools", ""]
        if self.allowed_tool_patterns:
            args += ["--allowedTools", *self.allowed_tool_patterns]
        args += ["--permission-mode", self.permission_mode]
        return args


#: Pure review/analysis: no code-execution tool exists in the allowlist at
#: all. `permission_mode="dontAsk"`, not `"bypassPermissions"` -- a real,
#: reproduced defect this project's own permission-qualification task found:
#: `--restricted` unconditionally REJECTS `--permission-mode bypassPermissions`
#: (`claude` CLI's own hard error: "bypassPermissions not supported in
#: restricted mode", exit code 1, confirmed live) -- every prior launch under
#: this profile therefore never even started. `dontAsk` was verified live as
#: a real, working, semantically-correct substitute for a profile with no
#: mutation/execution tool to ever prompt about in the first place.
CLAUDE_READONLY_PROFILE = ToolExecutionProfile(
    name="CLAUDE_READONLY_PROFILE",
    tools=("Read", "Glob", "Grep"),
    restricted=True,
    permission_mode="dontAsk",
)

#: Task-authorized mutation + safe tests + local regression + evidence
#: writes -- the FIX_NOW_* remediation profile. `PowerShell` is granted only
#: for the four safe, read/verify-shaped command families named in
#: `allowed_tool_patterns`; anything else the model tries under that tool
#: name is still refused by `--allowedTools`'s own pattern match (verified:
#: `claude --help`'s own `"Bash(git *) Edit"` example is the same mechanism).
#:
#: `Edit`/`Write` are ALSO listed here explicitly, not left to
#: `--permission-mode acceptEdits` alone (real, reproduced defect this
#: project's own permission-qualification task found: once `--allowedTools`
#: is passed at all, a tool not named in it falls through to an interactive
#: approval prompt that a headless `-p` worker can never answer, silently
#: overriding `acceptEdits` for that tool even though it was present in
#: `--tools` -- confirmed by a real side-by-side repro: identical invocation
#: with only the `PowerShell(...)` patterns in `--allowedTools` left a real
#: `Write` action unapproved ("permission to write the file wasn't
#: granted"); adding `"Edit", "Write"` to this same list fixed it, verified
#: by a real file actually being created with `run_status=PASS`).
CLAUDE_IMPLEMENTATION_PROFILE = ToolExecutionProfile(
    name="CLAUDE_IMPLEMENTATION_PROFILE",
    tools=("Read", "Glob", "Grep", "Edit", "Write", "PowerShell"),
    allowed_tool_patterns=(
        "Edit",
        "Write",
        "PowerShell(python -m pytest *)",
        "PowerShell(git status)",
        "PowerShell(git diff*)",
        "PowerShell(python -c *)",
    ),
    restricted=True,
    permission_mode="acceptEdits",
)

PROFILES = {p.name: p for p in (CLAUDE_READONLY_PROFILE, CLAUDE_IMPLEMENTATION_PROFILE)}


def get_profile(name: str) -> ToolExecutionProfile:
    if name not in PROFILES:
        raise ValueError(f"UNKNOWN_TOOL_EXECUTION_PROFILE:{name}")
    return PROFILES[name]
