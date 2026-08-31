"""dv_harness/stats_snapshot.py -- live-computed repo statistics, replacing
hand-written poster/doc numbers that drift as the repo changes. Every value
here is computed fresh from the real filesystem/graph on every call, never
cached or hardcoded.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List


def _is_real_agent_profile(path: Path) -> bool:
    """A real agent profile is a `.claude/agents/*.md` file with YAML
    frontmatter carrying a `description:` field -- the shape every real
    agent profile in this project has (analysis-agent.md, debug-agent.md,
    etc.). `ROSTER.md` (added by Task 2's live-checkable agent roster doc)
    is a plain Markdown table with no frontmatter at all -- it lists agents,
    it is not one -- and must not be counted as one itself."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    frontmatter = text[3:end]
    return re.search(r"(?m)^description\s*:", frontmatter) is not None


def list_agent_files(root: Path) -> List[Path]:
    """Real agent profile files under .claude/agents/ -- excludes non-profile
    Markdown files such as ROSTER.md (a roster/index document about the
    agents, not an agent profile itself; see _is_real_agent_profile)."""
    return sorted(
        p for p in (root / ".claude" / "agents").glob("*.md")
        if _is_real_agent_profile(p)
    )


def _skill_md_files(root: Path) -> List[Path]:
    skills_dir = root / ".claude" / "skills"
    if not skills_dir.is_dir():
        return []
    return [p for p in skills_dir.rglob("SKILL.md") if "_deprecated" not in p.parts]


def _iron_rule_count(root: Path) -> int:
    path = root / ".claude" / "skills" / "CORE" / "iron-rules" / "SKILL.md"
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8")
    return len(re.findall(r"(?m)^## 鐵則 \d+", text))


def _graph_counts(root: Path) -> tuple[int, int]:
    path = root / ".dv-harness" / "graph" / "main_graph.json"
    if not path.is_file():
        return 0, 0
    graph = json.loads(path.read_text(encoding="utf-8"))
    return len(graph.get("nodes", [])), len(graph.get("edges", []))


def compute_stats(root: Path) -> dict:
    node_count, edge_count = _graph_counts(root)
    return {
        "agent_count": len(list_agent_files(root)),
        "skill_count": len(_skill_md_files(root)),
        "iron_rule_count": _iron_rule_count(root),
        "graph_node_count": node_count,
        "graph_edge_count": edge_count,
    }
