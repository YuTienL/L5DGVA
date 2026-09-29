from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# NEW module (2026-08-28, engine/planner/blackboard/react/router wiring pass).
# No prior module in dv_harness parses .claude/agents/<name>.md frontmatter --
# this is the missing piece needed to turn RouteResolver's resolved agent
# *name* (a string) into something ClaudeCLIAdapter.run() can actually act on
# (a concrete --agent value plus that agent's own declared tool scope).
#
# Confirmed frontmatter syntax by reading all 10 agent files main_graph.json's
# node.agent can name (2026-08-28):
#   - The 7 core agents (dv-lead, analysis-agent, implementation-agent,
#     build-agent, regression-agent, debug-agent, review-agent) declare
#     `tools: Read, Grep, Glob, ...` (comma-separated) and most also declare
#     `disallowedTools: Edit, Write`.
#   - The 3 senior-DV specialist agents main_graph.json also names as
#     node.agent (protocol-corner-case-intelligence-agent,
#     waveform-root-cause-agent, failure-triage-attribution-agent) have ONLY
#     `name:`/`description:` in frontmatter -- no tools:/disallowedTools: line
#     at all. For these, `tools` below is correctly None (not an empty list --
#     None means "this agent declared no explicit scope", which the adapter
#     must treat differently from "this agent declared an empty/deny-all
#     scope").

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class AgentProfile:
    name: str
    found: bool
    tools: Optional[List[str]] = None          # None = agent declared no explicit tools: line
    disallowed_tools: List[str] = field(default_factory=list)
    system_prefix: str = ""                     # agent .md body (post-frontmatter), for optional reinforcement
    # model (2026-09-06, model_agent_tool_router.py gap-close): the agent's
    # own declared `model:` frontmatter scalar, e.g. "inherit" -- 17 of this
    # repo's 24 real agent profiles declare it, but nothing before this
    # parsed it. None means the agent's frontmatter carries no `model:` line
    # at all (never guessed/defaulted here -- see model_agent_tool_router.py
    # for the one place a fallback default is applied).
    model: Optional[str] = None


def _parse_frontmatter_list(fm_text: str, key: str) -> Optional[List[str]]:
    for line in fm_text.splitlines():
        line = line.strip()
        if line.lower().startswith(key.lower() + ":"):
            val = line.split(":", 1)[1].strip()
            return [t.strip() for t in val.split(",") if t.strip()] or None
    return None


def _parse_frontmatter_scalar(fm_text: str, key: str) -> Optional[str]:
    """Reads one `key: value` frontmatter line as a bare scalar (not a
    comma-split list) -- e.g. `model: inherit`. Only the first matching line
    counts, mirroring _parse_frontmatter_list's own single-match contract."""
    for line in fm_text.splitlines():
        line = line.strip()
        if line.lower().startswith(key.lower() + ":"):
            val = line.split(":", 1)[1].strip()
            return val or None
    return None


def load_agent_profile(root, agent_name: Optional[str]) -> Optional[AgentProfile]:
    """Reads .claude/agents/<agent_name>.md. Returns None only when
    agent_name itself is falsy (no agent resolved for this node at all) --
    a missing/unreadable file still returns an AgentProfile with found=False
    so callers can fall back to harness-global defaults instead of crashing."""
    if not agent_name:
        return None
    p = Path(root) / ".claude" / "agents" / f"{agent_name}.md"
    if not p.exists():
        return AgentProfile(name=agent_name, found=False)
    text = p.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return AgentProfile(name=agent_name, found=True, system_prefix=text.strip())
    fm, body = m.group("body"), text[m.end():]
    return AgentProfile(
        name=agent_name,
        found=True,
        tools=_parse_frontmatter_list(fm, "tools"),
        disallowed_tools=_parse_frontmatter_list(fm, "disallowedTools") or [],
        system_prefix=body.strip(),
        model=_parse_frontmatter_scalar(fm, "model"),
    )
