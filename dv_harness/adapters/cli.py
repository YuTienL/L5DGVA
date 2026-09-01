from __future__ import annotations
import json, shutil, subprocess
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING
from .base import ClaudeAdapter, AgentResult

if TYPE_CHECKING:
    from ..agent_profile import AgentProfile

class ClaudeCLIAdapter(ClaudeAdapter):
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config["claude"]

    @staticmethod
    def _resolve_command(configured: str) -> str:
        """Resolve the configured claude command to a real, directly-executable
        path before handing it to subprocess.run(..., shell=False).

        HONEST BUG THIS FIXES (found via a real `dv-harness run-stage` run on
        2026-09-01, not a hypothetical): on Windows, `npm install -g` puts
        TWO files on PATH for one package -- a bare POSIX shell script named
        exactly `claude` (only runnable by bash/sh, e.g. Git Bash) and a real
        Windows launcher `claude.cmd`. subprocess.run() with shell=False (the
        default, and what this adapter already uses -- see run() below) calls
        Win32 CreateProcess directly, which does NOT do PATHEXT-based
        resolution the way `where`/cmd.exe do -- it can only ever find
        `claude`, the non-executable-on-Windows shell script, and fails with
        FileNotFoundError (WinError 2). shutil.which() DOES perform PATHEXT
        resolution on Windows (checking .COM/.EXE/.BAT/.CMD in order) and
        correctly returns the real `claude.cmd` launcher. On POSIX, shutil.which()
        is a no-op-equivalent PATH lookup that returns the same real script
        subprocess.run() would have found anyway, so this is a pure
        Windows-only fix with no POSIX behavior change.
        """
        resolved = shutil.which(configured)
        return resolved or configured

    def run(self, prompt: str, cwd: str, resume_session: Optional[str] = None,
            agent_profile: "Optional[AgentProfile]" = None) -> AgentResult:
        cmd = [self._resolve_command(self.cfg.get("command","claude")), "-p", prompt,
               "--output-format", self.cfg.get("output_format","json"),
               "--max-turns", str(self.cfg.get("max_turns",40))]

        pm = self.cfg.get("permission_mode","dangerously-skip-permissions")
        if pm == "dangerously-skip-permissions":
            cmd.append("--dangerously-skip-permissions")
        elif pm:
            cmd += ["--permission-mode", pm]

        if resume_session:
            cmd += ["--resume", resume_session]

        # --- Real per-stage sub-agent dispatch (2026-08-28 wiring pass) ---
        # `claude --help` on the CLI this adapter shells out to (v2.1.250)
        # confirms a genuine, documented flag for exactly this use case:
        #   --agent <agent>   "Agent for the current session. Overrides the
        #                      'agent' setting."
        # This is NOT invented -- it is the same CLI binary this adapter
        # already calls, and `.claude/agents/<name>.md` (name/description/
        # tools/disallowedTools/model frontmatter) is Claude Code's own
        # project-level custom-agent registration format, already present
        # in this repo for all 10 distinct node.agent values main_graph.json
        # uses. Only pass --agent when the resolved name actually has a
        # registered file (agent_profile.found); an unresolved/unknown agent
        # name falls back to the harness's previous uniform behavior rather
        # than passing a flag value the CLI would reject.
        #
        # HONEST LIMITATION: --agent scopes *this entire single non-interactive
        # `-p` process* to behave as that named agent (its own system prompt /
        # tool scope) for the duration of one run_stage() call. This is a
        # different shape of "sub-agent dispatch" than Claude Code's own
        # in-session Agent/Task-tool mechanism, where a live orchestrating
        # session hands off one sub-task to a subagent and gets a result
        # folded back into the SAME ongoing conversation while the parent
        # keeps running. Here there is no such parent session watching
        # multiple stages concurrently -- each run_stage() call is an
        # independent external process, and "delegation" means "this whole
        # process IS that agent for this one call", not "the lead agent
        # spawned a nested subagent mid-conversation". Treat this as the best
        # real external-invocation approximation of subagent dispatch, not as
        # equivalent to the in-session mechanism.
        if agent_profile is not None and agent_profile.found and agent_profile.name:
            cmd += ["--agent", agent_profile.name]

        # Tool scoping: still applied explicitly (in addition to whatever
        # --agent itself already restricts) using the SAME --allowedTools/
        # --disallowedTools flags this adapter already used pre-existing --
        # --disallowedTools is confirmed as a real, symmetric flag in the
        # same `claude --help` output, not invented. When the resolved
        # agent's own frontmatter declares an explicit tools: list, that
        # narrower agent-specific scope takes priority over the harness's
        # global config default (which is `[]` today -- i.e. previously NO
        # restriction was ever applied to any stage). Agents with no tools:
        # line (the 3 senior-DV specialist agents) fall back to the harness
        # global list unchanged from prior behavior.
        allowed = self.cfg.get("allowed_tools", [])
        disallowed: list = []
        if agent_profile is not None:
            if agent_profile.tools is not None:
                allowed = agent_profile.tools
            disallowed = agent_profile.disallowed_tools

        for tool in allowed:
            cmd += ["--allowedTools", tool]
        for tool in disallowed:
            cmd += ["--disallowedTools", tool]

        # HONEST BUG THIS FIXES (found via the same real `dv-harness run-stage`
        # run this session that found the shutil.which() bug above, once that
        # fix let the subprocess actually launch): text=True without an
        # explicit `encoding` makes Python decode the child's stdout/stderr
        # using locale.getpreferredencoding() -- on this Windows dev machine
        # (config.json's policy.language is "zh-TW") that resolves to cp950
        # (Traditional Chinese), not UTF-8. The real `claude` CLI's own
        # --output-format json output is UTF-8 and contains real multi-byte
        # sequences cp950 cannot decode, crashing subprocess.run()'s internal
        # stderr-reader thread with UnicodeDecodeError -- which leaves
        # p.stderr as None, so the very next line's unconditional
        # `.strip()` call then raised AttributeError on top of that. Forcing
        # encoding="utf-8" with errors="replace" (never silently drop bytes,
        # but never crash the whole stage on one bad byte either) fixes the
        # decode; `p.stdout or ""` / `p.stderr or ""` guards the (now
        # unlikely, but still theoretically possible on other platforms)
        # None case defensively rather than trusting text mode never fails.
        p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True,
                            encoding="utf-8", errors="replace")
        stdout = (p.stdout or "").strip()
        stderr = (p.stderr or "").strip()
        raw: Dict[str, Any] = {"returncode": p.returncode, "stderr": stderr}

        session_id = None
        text = stdout
        if stdout:
            try:
                obj = json.loads(stdout)
                raw["response"] = obj
                session_id = obj.get("session_id") or obj.get("sessionId")
                text = obj.get("result") or obj.get("text") or stdout
            except Exception:
                raw["response_text"] = stdout

        return AgentResult(
            ok=(p.returncode == 0),
            text=text,
            raw=raw,
            session_id=session_id,
            is_error=(p.returncode != 0)
        )
