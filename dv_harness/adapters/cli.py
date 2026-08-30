from __future__ import annotations
import json, subprocess
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING
from .base import ClaudeAdapter, AgentResult

if TYPE_CHECKING:
    from ..agent_profile import AgentProfile

class ClaudeCLIAdapter(ClaudeAdapter):
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config["claude"]

    def run(self, prompt: str, cwd: str, resume_session: Optional[str] = None,
            agent_profile: "Optional[AgentProfile]" = None) -> AgentResult:
        cmd = [self.cfg.get("command","claude"), "-p", prompt,
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

        p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
        stdout = p.stdout.strip()
        stderr = p.stderr.strip()
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
