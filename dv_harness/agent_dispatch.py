"""dv_harness/agent_dispatch.py -- derives, from the REAL production dispatch
tables, which registered agent profiles actually get dispatched and where.

WHY THIS MODULE EXISTS (2026-09-04, "7 expert agent roles" gap-close pass)
-------------------------------------------------------------------------
`.claude/agents/ROSTER.md` listed all real agent profiles as one flat,
undifferentiated list. That list could not distinguish:

  * `implementation-agent`  -- named by 4 real `main_graph.json` node.agent
    fields, so `engine.run_stage()` -> `multi_agent.delegate()` ->
    `adapters/cli.py`'s `--agent` flag really does dispatch it in production;

  * `verification-risk-experience-agent` -- a real, parseable profile with
    ZERO dispatch call sites anywhere (no graph node, no subgraph node, no
    `.claude/workflows/*.js` caller). The role-shaped work it describes does
    run in production, but as an engine gate script
    (`experience_applicability_gate.py`), not as a dispatched persona.

That ambiguity is exactly what let an unreal role taxonomy (the poster-only
"PM / Architect / Developer / Verification / Regression / QA&Closure /
Knowledge Agent" seven) be asserted about this repo and survive: with a flat
list, "we have an Architect Agent" is unfalsifiable. Making dispatch status
machine-derived from the real tables makes any such claim checkable, and the
accompanying test makes the roster fail CI if it ever drifts from the graph.

NOT A NEW DISPATCH MECHANISM. This module only READS the tables the engine
already dispatches from. It never adds a node, never delegates, never picks
an agent. The real dispatch path is unchanged:
    `.dv-harness/graph/main_graph.json` node.agent
      -> `dv_harness/router.py` RouteResolver.resolve()
      -> `dv_harness/multi_agent.py` MultiAgentOrchestrator.delegate()
      -> `dv_harness/agent_profile.py` load_agent_profile()
      -> `dv_harness/adapters/cli.py` `claude --agent <name> --allowedTools ...`
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

from .stats_snapshot import list_agent_files

# Dispatch-status vocabulary. These exact tokens are what ROSTER.md must
# carry per agent, and what test_agent_dispatch_map.py cross-checks.
GRAPH_DISPATCHED = "GRAPH_DISPATCHED"      # named by >=1 main_graph.json node.agent
SUBGRAPH_DISPATCHED = "SUBGRAPH_DISPATCHED"  # named only by a subgraph node.agent
WORKFLOW_DISPATCHED = "WORKFLOW_DISPATCHED"  # named only by a .claude/workflows/*.js caller
NOT_DISPATCHED = "NOT_DISPATCHED"          # no dispatch call site anywhere

# Precedence when an agent appears in more than one kind of call site: the
# strongest real production path wins, since that is what "does this role
# actually fire in the main flow?" is asking.
_PRECEDENCE = [GRAPH_DISPATCHED, SUBGRAPH_DISPATCHED, WORKFLOW_DISPATCHED, NOT_DISPATCHED]


def _load_graph(path: Path) -> dict:
    """Reads a graph JSON. Explicit utf-8: these files contain non-ASCII text
    and this repo runs on a cp950-default Windows host, where an
    encoding-less open() raises UnicodeDecodeError on them."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _graph_agent_nodes(path: Path) -> Dict[str, List[str]]:
    """agent name -> sorted node ids that name it, for one graph file."""
    out: Dict[str, List[str]] = {}
    for node in _load_graph(path).get("nodes", []):
        agent = node.get("agent")
        if not agent:
            continue
        out.setdefault(agent, []).append(node.get("id") or node.get("name") or "?")
    return {k: sorted(v) for k, v in out.items()}


def _workflow_agent_mentions(root: Path, known: List[str]) -> Dict[str, List[str]]:
    """agent name -> workflow files that name it as a string literal.

    Deliberately conservative: only counts a KNOWN registered agent name that
    appears inside a quoted string literal in a `.claude/workflows/*.js` file.
    A bare prose mention in a comment is not a dispatch call site, and this
    must not over-credit one as if it were."""
    out: Dict[str, List[str]] = {}
    wf_dir = root / ".claude" / "workflows"
    if not wf_dir.is_dir():
        return out
    for js in sorted(wf_dir.glob("*.js")):
        try:
            text = js.read_text(encoding="utf-8")
        except OSError:
            continue
        literals = set(re.findall(r"""['"]([A-Za-z0-9_\-]+)['"]""", text))
        for agent in known:
            if agent in literals:
                out.setdefault(agent, []).append(js.name)
    return out


def agent_dispatch_map(root: Path) -> Dict[str, dict]:
    """For every real registered agent profile, its REAL dispatch status.

    Returns {agent_name: {"status": <one of the four tokens>,
                          "graph_nodes": [...],      # main_graph.json node ids
                          "subgraph_nodes": [...],   # "<file>:<node id>"
                          "workflows": [...]}}       # workflow file names

    Derived fresh from the real files on every call -- nothing hardcoded, so
    repointing a node's `agent` field in main_graph.json immediately changes
    this map (and therefore trips the roster-agreement test until the roster
    is updated to match).
    """
    root = Path(root)
    known = [p.stem for p in list_agent_files(root)]

    main_nodes = _graph_agent_nodes(root / ".dv-harness" / "graph" / "main_graph.json")

    sub_nodes: Dict[str, List[str]] = {}
    sub_dir = root / ".dv-harness" / "graph" / "subgraphs"
    if sub_dir.is_dir():
        for sg in sorted(sub_dir.glob("*.json")):
            for agent, ids in _graph_agent_nodes(sg).items():
                sub_nodes.setdefault(agent, []).extend(f"{sg.name}:{i}" for i in ids)

    workflows = _workflow_agent_mentions(root, known)

    out: Dict[str, dict] = {}
    for agent in sorted(known):
        g = sorted(main_nodes.get(agent, []))
        s = sorted(sub_nodes.get(agent, []))
        w = sorted(workflows.get(agent, []))
        if g:
            status = GRAPH_DISPATCHED
        elif s:
            status = SUBGRAPH_DISPATCHED
        elif w:
            status = WORKFLOW_DISPATCHED
        else:
            status = NOT_DISPATCHED
        out[agent] = {"status": status, "graph_nodes": g,
                      "subgraph_nodes": s, "workflows": w}
    return out


def dispatch_status_counts(root: Path) -> Dict[str, int]:
    """Count of registered agents per dispatch status, strongest first."""
    m = agent_dispatch_map(root)
    counts = {k: 0 for k in _PRECEDENCE}
    for info in m.values():
        counts[info["status"]] += 1
    return counts
