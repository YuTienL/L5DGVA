# dv_harness_tests/test_memory_docs_mirror_source.py
"""Guard the Phase 24 memory docs against content drift that `file:line`
citation checking cannot see.

`dv_harness/doc_citation_check.py` verifies that a doc's `module.py:123`
citations still land on the symbol the prose names. That catches line-number
rot, but it is blind to a doc that *quotes a list* which the source of truth
has since grown: the citation still points at the right symbol while the
copied list beside it is short an entry.

Both of the memory docs' quoted lists really did drift that way:

* `docs/MEMORY_SCHEMA.md` fell behind `MEMORY_NOTE_OPTIONAL_FIELDS` when
  `knowledge_commit_sha` was added (Phase 13, git integration).
* `docs/MEMORY_AGENT.md` fell behind `.claude/agents/memory-agent.md` when
  `CORE/memory-review` was bound to the agent (commit e1d328d).

Each was a silent, human-invisible falsehood in a doc whose whole value is
being checkable against the real thing, and the citation checker reported
`0 drifted` through both. These tests compare the quoted block against the
live source of truth directly, so the next such addition fails a test instead
of quietly making a doc wrong.
"""
import re
from pathlib import Path

import pytest
import yaml

from dv_harness.memory import MEMORY_LEVELS
from dv_harness.memory_vault import (
    MEMORY_NOTE_BODY_SECTIONS,
    MEMORY_NOTE_OPTIONAL_FIELDS,
    MEMORY_NOTE_REQUIRED_FIELDS,
    MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS,
)

ROOT = Path(__file__).resolve().parents[1]

AGENT_PROFILE = ROOT / ".claude" / "agents" / "memory-agent.md"
AGENT_DOC = ROOT / "docs" / "MEMORY_AGENT.md"
SCHEMA_DOC = ROOT / "docs" / "MEMORY_SCHEMA.md"
ARCHITECTURE_DOC = ROOT / "docs" / "MEMORY_ARCHITECTURE.md"

# The frontmatter keys docs/MEMORY_AGENT.md mirrors and therefore must keep
# true. `description` is deliberately excluded: the doc quotes the profile's
# shape (capabilities, tool grants, skill bindings), not its prose blurb.
MIRRORED_FRONTMATTER_KEYS = ("name", "tools", "disallowedTools", "model", "skills")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _agent_profile_frontmatter() -> dict:
    """Parse the real agent profile's YAML frontmatter (between the first
    two `---` fences)."""
    text = _read(AGENT_PROFILE)
    assert text.startswith("---\n"), f"{AGENT_PROFILE} has no YAML frontmatter"
    end = text.index("\n---", 4)
    return yaml.safe_load(text[4:end])


def _doc_yaml_block(doc_text: str) -> dict:
    """Parse the first ```yaml fenced block in a doc."""
    marker = "```yaml\n"
    start = doc_text.index(marker) + len(marker)
    end = doc_text.index("```", start)
    return yaml.safe_load(doc_text[start:end])


def _doc_fenced_list(doc_text: str, heading_marker: str) -> list:
    """Return the comma/newline-separated entries of the plain fenced block
    that follows `heading_marker` in a doc."""
    at = doc_text.index(heading_marker)
    start = doc_text.index("```\n", at) + len("```\n")
    end = doc_text.index("```", start)
    body = doc_text[start:end]
    return [item.strip() for item in body.replace("\n", ",").split(",") if item.strip()]


def test_memory_agent_doc_frontmatter_mirrors_the_live_agent_profile():
    """docs/MEMORY_AGENT.md quotes the agent's frontmatter as "real"; every
    mirrored key must still equal the profile's own value.

    The bound-skill list is the field that drifts: a skill added to the agent
    without touching the doc leaves the doc understating what the agent can
    do, and there is no other machine check on it.
    """
    live = _agent_profile_frontmatter()
    documented = _doc_yaml_block(_read(AGENT_DOC))

    assert set(documented) == set(MIRRORED_FRONTMATTER_KEYS), (
        "docs/MEMORY_AGENT.md's frontmatter block mirrors keys "
        f"{sorted(documented)}, expected {sorted(MIRRORED_FRONTMATTER_KEYS)}; "
        "update MIRRORED_FRONTMATTER_KEYS if the mirror deliberately changed"
    )
    for key in MIRRORED_FRONTMATTER_KEYS:
        assert documented[key] == live[key], (
            f"docs/MEMORY_AGENT.md's mirrored {key!r} says {documented[key]!r} "
            f"but {AGENT_PROFILE.name} really has {live[key]!r}"
        )


def test_memory_agent_doc_names_every_bound_skill_in_its_prose_or_frontmatter():
    """A bound skill the doc never mentions anywhere is undiscoverable to the
    reader the doc exists for."""
    live_skills = _agent_profile_frontmatter()["skills"]
    doc_text = _read(AGENT_DOC)
    missing = [s for s in live_skills if s.split("/")[-1] not in doc_text]
    assert not missing, (
        f"docs/MEMORY_AGENT.md never names bound skill(s) {missing}"
    )


@pytest.mark.parametrize(
    "heading_marker, live_list",
    [
        ("`MEMORY_NOTE_REQUIRED_FIELDS`", MEMORY_NOTE_REQUIRED_FIELDS),
        ("`MEMORY_NOTE_OPTIONAL_FIELDS`", MEMORY_NOTE_OPTIONAL_FIELDS),
        ("`MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS`", MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS),
    ],
)
def test_memory_schema_doc_field_lists_mirror_the_live_vault_constants(
    heading_marker, live_list
):
    """Order included: the doc presents these as the emitted frontmatter field
    order, which `render_note_markdown()` really honours."""
    documented = _doc_fenced_list(_read(SCHEMA_DOC), heading_marker)
    assert documented == list(live_list), (
        f"docs/MEMORY_SCHEMA.md's {heading_marker} block lists {documented} "
        f"but dv_harness.memory_vault really has {list(live_list)}"
    )


def test_architecture_doc_tier_list_mirrors_the_live_memory_levels():
    """MEMORY_ARCHITECTURE.md quotes `MEMORY_LEVELS` inline as the tier order
    the whole doc (routing diagram, tier table, promotion path) is built on."""
    text = _read(ARCHITECTURE_DOC)
    match = re.search(r"`MEMORY_LEVELS\s*=\s*\[(.*?)\]`", text, re.S)
    assert match, "MEMORY_ARCHITECTURE.md no longer quotes MEMORY_LEVELS inline"
    documented = [item.strip().strip('"\'') for item in match.group(1).split(",")]
    assert documented == list(MEMORY_LEVELS), (
        f"docs/MEMORY_ARCHITECTURE.md quotes MEMORY_LEVELS as {documented} but "
        f"dv_harness.memory really has {list(MEMORY_LEVELS)}"
    )


def test_memory_schema_doc_body_sections_mirror_the_live_vault_constant():
    documented = [
        line.strip()[len("## "):]
        for line in _doc_fenced_list(_read(SCHEMA_DOC), "`MEMORY_NOTE_BODY_SECTIONS`")
    ]
    assert documented == list(MEMORY_NOTE_BODY_SECTIONS), (
        f"docs/MEMORY_SCHEMA.md's body-section block lists {documented} but "
        f"dv_harness.memory_vault really has {list(MEMORY_NOTE_BODY_SECTIONS)}"
    )
