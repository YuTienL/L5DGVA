import json
from pathlib import Path

from dv_harness.stats_snapshot import compute_stats, list_agent_files

ROOT = Path(__file__).resolve().parents[1]


def test_agent_count_matches_real_glob():
    stats = compute_stats(ROOT)
    real_count = len(list((ROOT / ".claude" / "agents").glob("*.md")))
    assert stats["agent_count"] == real_count
    assert real_count > 0


def test_skill_count_excludes_deprecated():
    stats = compute_stats(ROOT)
    all_skill_md = list((ROOT / ".claude" / "skills").rglob("SKILL.md"))
    deprecated_count = len([p for p in all_skill_md if "_deprecated" in p.parts])
    non_deprecated_count = len(all_skill_md) - deprecated_count
    assert stats["skill_count"] == non_deprecated_count
    assert deprecated_count > 0  # sanity: the _deprecated tree exists in this repo


def test_iron_rule_count_matches_regex_scan():
    import re
    text = (ROOT / ".claude" / "skills" / "CORE" / "iron-rules" / "SKILL.md").read_text(encoding="utf-8")
    expected = len(re.findall(r"(?m)^## 鐵則 \d+", text))
    stats = compute_stats(ROOT)
    assert stats["iron_rule_count"] == expected
    assert expected > 0


def test_graph_counts_match_real_json():
    graph = json.loads((ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"))
    stats = compute_stats(ROOT)
    assert stats["graph_node_count"] == len(graph.get("nodes", []))
    assert stats["graph_edge_count"] == len(graph.get("edges", []))


def test_list_agent_files_returns_real_paths():
    files = list_agent_files(ROOT)
    assert all(p.suffix == ".md" for p in files)
    assert all(p.parent.name == "agents" for p in files)
