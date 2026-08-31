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
    roster = (ROOT / ".claude" / "agents" / "ROSTER.md").read_text(encoding="utf-8")
    for fictional in ("PM Agent", "Architect Agent", "QA&Closure", "Knowledge Agent"):
        assert fictional not in roster
