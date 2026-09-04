# dv_harness_tests/test_agent_dispatch_map.py
#
# Proves the "expert agent roles" taxonomy is machine-checkable against the
# REAL production dispatch path, not just prose in a roster doc.
#
# The gap these tests close: `.claude/agents/ROSTER.md` used to list every
# agent profile as one flat list, with no way to tell a role that really
# fires (`implementation-agent`, named by 4 real main_graph.json nodes) from
# a profile with zero dispatch call sites anywhere (`memory-agent`). That
# ambiguity is what let an unreal role taxonomy be asserted about this repo
# and survive an audit. These tests make the roster's per-agent Dispatch
# value fail if it ever disagrees with the real graph.
import json
import shutil
import types
from pathlib import Path

import pytest

from dv_harness.agent_dispatch import (
    GRAPH_DISPATCHED,
    NOT_DISPATCHED,
    agent_dispatch_map,
    dispatch_status_counts,
)
from dv_harness.agent_profile import load_agent_profile
from dv_harness.stats_snapshot import list_agent_files

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / ".claude" / "agents" / "ROSTER.md"
MAIN_GRAPH = ROOT / ".dv-harness" / "graph" / "main_graph.json"

_ALL_STATUSES = ("GRAPH_DISPATCHED", "SUBGRAPH_DISPATCHED",
                 "WORKFLOW_DISPATCHED", "NOT_DISPATCHED")


def _roster_text():
    return ROSTER.read_text(encoding="utf-8")


def _roster_entry(stem: str) -> str:
    """The ROSTER.md block for one agent: from its own `**<stem>** --` heading
    up to the next numbered agent heading."""
    text = _roster_text()
    marker = f"**{stem}** -- Dispatch:"
    start = text.find(marker)
    assert start != -1, f"{stem} has no Dispatch-bearing entry in ROSTER.md"
    nxt = text.find("** -- Dispatch:", start + len(marker))
    end = text.rfind("\n", 0, nxt) if nxt != -1 else len(text)
    return text[start:end]


def test_dispatch_map_covers_every_registered_agent():
    """The map must speak for every real profile -- an agent the map silently
    omits is exactly the blind spot that let an unreal role claim survive."""
    m = agent_dispatch_map(ROOT)
    stems = {p.stem for p in list_agent_files(ROOT)}
    assert set(m) == stems
    for name, info in m.items():
        assert info["status"] in _ALL_STATUSES, (name, info)


def test_every_main_graph_node_agent_resolves_to_a_real_profile():
    """Every `node.agent` the engine can dispatch must have a real
    `.claude/agents/<name>.md`; otherwise `agent_profile.found` is False and
    `cli.py` silently drops the `--agent` flag, losing that role's tool
    scoping without any error."""
    graph = json.loads(MAIN_GRAPH.read_text(encoding="utf-8"))
    named = {n["agent"] for n in graph["nodes"] if n.get("agent")}
    assert named, "main_graph.json declares no node.agent at all"
    for agent in sorted(named):
        profile = load_agent_profile(ROOT, agent)
        assert profile is not None and profile.found, (
            f"main_graph.json dispatches '{agent}' but "
            f".claude/agents/{agent}.md does not exist"
        )


def test_roster_dispatch_status_matches_the_real_graph():
    """The roster's per-agent Dispatch token must equal what the real
    dispatch tables say. Repointing a node's `agent` field without updating
    ROSTER.md fails here."""
    for stem, info in agent_dispatch_map(ROOT).items():
        entry = _roster_entry(stem)
        assert f"Dispatch: `{info['status']}`" in entry, (
            f"ROSTER.md states the wrong dispatch status for {stem}; "
            f"real status is {info['status']}"
        )


def test_roster_lists_the_real_node_ids_for_graph_dispatched_agents():
    """Not just the status token -- the actual node ids each dispatched role
    owns must be the real ones, so 'which role owns SIGNOFF?' is answerable
    from the roster without re-grepping the graph."""
    for stem, info in agent_dispatch_map(ROOT).items():
        if info["status"] != GRAPH_DISPATCHED:
            continue
        entry = _roster_entry(stem)
        for node_id in info["graph_nodes"]:
            assert f"`{node_id}`" in entry, (
                f"ROSTER.md's {stem} entry omits its real node {node_id}"
            )


def test_roster_explains_how_every_non_dispatched_role_really_runs():
    """A NOT_DISPATCHED profile must carry an explicit note saying how its
    role-shaped work actually runs in production. Without it, a reader
    reasonably assumes it is a stage-owning role -- the original defect."""
    for stem, info in agent_dispatch_map(ROOT).items():
        if info["status"] != NOT_DISPATCHED:
            continue
        entry = _roster_entry(stem)
        assert "How this role really runs" in entry, (
            f"{stem} is NOT_DISPATCHED but ROSTER.md does not say how its "
            f"role-shaped work really runs"
        )


def test_separation_of_duties_writer_never_reaches_signoff():
    """The real, enforced claim behind 'distinct expert roles': the writer
    role's node set and the read-only signoff role's node set are disjoint,
    and the signoff role cannot write."""
    m = agent_dispatch_map(ROOT)
    writer = set(m["implementation-agent"]["graph_nodes"])
    reviewer = set(m["review-agent"]["graph_nodes"])
    assert "SIGNOFF" in reviewer
    assert not (writer & reviewer), "writer and signoff roles share a node"

    review_profile = load_agent_profile(ROOT, "review-agent")
    assert "Write" in review_profile.disallowed_tools
    assert "Edit" in review_profile.disallowed_tools
    impl_profile = load_agent_profile(ROOT, "implementation-agent")
    assert "Write" in (impl_profile.tools or [])


def test_dispatch_map_is_derived_from_the_real_graph_not_hardcoded(tmp_path):
    """Repointing a node's `agent` in a COPY of the real graph must change
    the computed map. This is what makes the roster test meaningful: if the
    map were hardcoded, roster/graph agreement would prove nothing."""
    fake = tmp_path / "repo"
    (fake / ".dv-harness" / "graph").mkdir(parents=True)
    shutil.copytree(ROOT / ".claude" / "agents", fake / ".claude" / "agents")

    graph = json.loads(MAIN_GRAPH.read_text(encoding="utf-8"))
    before = agent_dispatch_map(ROOT)
    assert before["memory-agent"]["status"] == NOT_DISPATCHED

    for node in graph["nodes"]:
        if node.get("id") == "IMPLEMENT":
            node["agent"] = "memory-agent"
    (fake / ".dv-harness" / "graph" / "main_graph.json").write_text(
        json.dumps(graph), encoding="utf-8")

    after = agent_dispatch_map(fake)
    assert after["memory-agent"]["status"] == GRAPH_DISPATCHED
    assert "IMPLEMENT" in after["memory-agent"]["graph_nodes"]
    assert "IMPLEMENT" not in after["implementation-agent"]["graph_nodes"]


def test_graph_dispatched_role_really_reaches_the_claude_agent_flag(monkeypatch):
    """End-to-end proof that a roster role is not just prose: feed a real
    agent's profile through the REAL adapter and confirm the argv actually
    handed to subprocess carries `--agent <name>` plus that agent's own
    declared tool scope. This is the wiring the roster is describing."""
    from dv_harness.adapters import cli as cli_mod

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"result": "ok", "session_id": "S1"}),
            stderr="",
        )

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(cli_mod.ClaudeCLIAdapter, "_resolve_command",
                        staticmethod(lambda configured: configured))

    adapter = cli_mod.ClaudeCLIAdapter({"claude": {"command": "claude"}})
    profile = load_agent_profile(ROOT, "review-agent")
    adapter.run("hello", cwd=str(ROOT), agent_profile=profile)

    cmd = captured["cmd"]
    assert "--agent" in cmd
    assert cmd[cmd.index("--agent") + 1] == "review-agent"
    # review-agent's own frontmatter scope really reaches the CLI, so the
    # signoff role cannot write even if the prompt asks it to.
    disallowed = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--disallowedTools"]
    assert "Write" in disallowed and "Edit" in disallowed


def test_dispatch_status_counts_agree_with_the_map():
    counts = dispatch_status_counts(ROOT)
    m = agent_dispatch_map(ROOT)
    assert sum(counts.values()) == len(m)
    assert counts[GRAPH_DISPATCHED] >= 10, "core dispatched roles disappeared"
