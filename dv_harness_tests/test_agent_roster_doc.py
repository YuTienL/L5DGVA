# dv_harness_tests/test_agent_roster_doc.py
from pathlib import Path

from dv_harness.stats_snapshot import list_agent_files

ROOT = Path(__file__).resolve().parents[1]


def test_roster_doc_exists_and_lists_every_real_agent():
    roster = (ROOT / ".claude" / "agents" / "ROSTER.md").read_text(encoding="utf-8")
    real_agent_stems = {p.stem for p in list_agent_files(ROOT) if p.stem != "ROSTER"}
    for stem in real_agent_stems:
        assert stem in roster, f"{stem} missing from ROSTER.md"


def test_roster_doc_does_not_claim_fictional_seven_agent_taxonomy():
    """Guards the full poster-only seven-role taxonomy, not a subset of it.

    None of these names is a real agent profile, a real `main_graph.json`
    `node.agent` value, or a real dispatch call site anywhere in this repo --
    verified again on 2026-09-04 by `dv_harness.agent_dispatch`. ROSTER.md's
    "Role-shaped work that is deliberately NOT an agent" section records the
    real answer for each of these using descriptive wording instead, so the
    question is documented without the fictional names re-entering the doc.
    """
    roster = (ROOT / ".claude" / "agents" / "ROSTER.md").read_text(encoding="utf-8")
    fictional_taxonomy = (
        "PM Agent", "Architect Agent", "Developer Agent", "Verification Agent",
        "Regression Agent", "QA&Closure", "QA & Closure", "Knowledge Agent",
    )
    for fictional in fictional_taxonomy:
        assert fictional not in roster, (
            f"ROSTER.md reintroduced the poster-only role name {fictional!r}; "
            f"describe the real role instead (see the roster's "
            f"'deliberately NOT an agent' section)"
        )
