import json
from pathlib import Path

from dv_harness.stats_snapshot import compute_stats, list_agent_files

ROOT = Path(__file__).resolve().parents[1]


def _real_agent_profile_count() -> int:
    """Independently (re-)derives the real agent-profile count without
    calling production code, by requiring YAML frontmatter with a
    `description:` field -- the shape every genuine agent profile has
    (analysis-agent.md, debug-agent.md, dv-lead.md, etc.), which
    `.claude/agents/ROSTER.md` (a plain roster table, no frontmatter) does
    not have."""
    import re
    count = 0
    for path in (ROOT / ".claude" / "agents").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end == -1:
            continue
        if re.search(r"(?m)^description\s*:", text[3:end]):
            count += 1
    return count


def test_agent_count_matches_real_glob():
    """Finding I1 regression test: `.claude/agents/*.md` also contains
    ROSTER.md (Task 2's live-checkable agent roster doc), which is a roster
    document ABOUT the agents, not an agent profile itself, and must be
    excluded from agent_count. Verified on this real repo: 17 total *.md
    files under .claude/agents/, 16 of which are genuine agent profiles
    (have YAML frontmatter with a description: field) and 1 (ROSTER.md)
    which is not -- matching this finding's own "17, not 16" evidence."""
    stats = compute_stats(ROOT)
    all_md = list((ROOT / ".claude" / "agents").glob("*.md"))
    real_count = _real_agent_profile_count()

    # Sanity-check the fixture assumptions this test relies on, so a future
    # repo change that removes/renames ROSTER.md fails loudly here instead
    # of silently passing a stale assertion.
    assert (ROOT / ".claude" / "agents" / "ROSTER.md").is_file()
    assert real_count == len(all_md) - 1, (
        "expected exactly one non-profile file (ROSTER.md) under .claude/agents/")

    assert stats["agent_count"] == real_count
    assert stats["agent_count"] == 16
    assert real_count > 0

    roster_files = [p for p in list_agent_files(ROOT) if p.stem == "ROSTER"]
    assert roster_files == [], "ROSTER.md must never be counted as an agent profile"


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
