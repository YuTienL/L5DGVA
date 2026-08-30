from __future__ import annotations
import asyncio, json
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING
from .base import ClaudeAdapter, AgentResult

if TYPE_CHECKING:
    from ..agent_profile import AgentProfile

class ClaudeCodeSDKAdapter(ClaudeAdapter):
    """
    Optional adapter for Anthropic's Python Claude Code SDK.
    Install separately:
        pip install claude-code-sdk

    The harness defaults to the CLI adapter because `claude -p` is easy to
    inspect, script, resume, and pin operationally.
    """
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config["claude"]

    def run(self, prompt: str, cwd: str, resume_session: Optional[str] = None,
            agent_profile: "Optional[AgentProfile]" = None) -> AgentResult:
        try:
            from claude_code_sdk import query, ClaudeCodeOptions
        except ImportError as e:
            return AgentResult(False, "claude-code-sdk 未安裝", {"error": str(e)}, is_error=True)

        # Best-effort parity with ClaudeCLIAdapter's per-agent scoping (see
        # cli.py's NOTICE for the confirmed --agent/--allowedTools/
        # --disallowedTools flags this mirrors). The SDK's own option names
        # for agent selection were not verified against an installed
        # claude-code-sdk in this pass -- only allowed_tools narrowing is
        # wired here; agent_profile.name is intentionally NOT forwarded to
        # ClaudeCodeOptions since no verified "agent=" option was confirmed
        # to exist, unlike the CLI's documented --agent flag.
        if prompt and agent_profile and agent_profile.system_prefix:
            prompt = f"[Acting as sub-agent: {agent_profile.name}]\n{agent_profile.system_prefix}\n\n---\n\n{prompt}"

        async def _run():
            messages = []
            opts_kwargs = {
                "cwd": Path(cwd),
                "max_turns": self.cfg.get("max_turns", 40),
            }
            allowed = self.cfg.get("allowed_tools", [])
            if agent_profile is not None and agent_profile.tools is not None:
                allowed = agent_profile.tools
            if allowed:
                opts_kwargs["allowed_tools"] = allowed
            # SDK option names may evolve; keep this adapter intentionally small.
            options = ClaudeCodeOptions(**opts_kwargs)
            async for message in query(prompt=prompt, options=options):
                messages.append(message)
            return messages

        try:
            messages = asyncio.run(_run())
            text = "\n".join(str(m) for m in messages)
            return AgentResult(True, text, {"messages": [str(m) for m in messages]})
        except Exception as e:
            return AgentResult(False, str(e), {"error": repr(e)}, is_error=True)
