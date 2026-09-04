# dv_harness_tests/test_agent_roster_doc.py
import re
from pathlib import Path

import pytest

from dv_harness.agent_dispatch import GRAPH_DISPATCHED, agent_dispatch_map
from dv_harness.stats_snapshot import list_agent_files

ROOT = Path(__file__).resolve().parents[1]

# The seven roles external posters assert about this harness, each keyed by the
# DESCRIPTIVE wording ROSTER.md answers it with -- never by the asserted name,
# which test_roster_doc_does_not_claim_fictional_seven_agent_taxonomy forbids
# from appearing in that file at all.
#
# Four resolve to engine code / library calls (agent None); three resolve to a
# real agent under a different name, and those are checked against the live
# dispatch derivation rather than trusted from the prose.
SEVEN_ROLE_ANSWERS = {
    "A project-management / workflow-control role": None,
    "An architecture-owning role": None,
    "A verification-planning role": None,
    "A knowledge / memory-tier role": None,
    "A code / RTL / script implementation role": "implementation-agent",
    "A simulation / job / regression-execution role": "regression-agent",
    "A qualification / signoff / evidence-closure role": "review-agent",
}

NAME_MAPPED_ROLES = {k: v for k, v in SEVEN_ROLE_ANSWERS.items() if v}


def _roster_text() -> str:
    return (ROOT / ".claude" / "agents" / "ROSTER.md").read_text(encoding="utf-8")


def _role_answer_block(roster: str, marker: str) -> str:
    """The text of one role's numbered answer, up to the next numbered item."""
    start = roster.index(marker)
    nxt = re.search(r"\n\d+\. \*\*", roster[start:])
    return roster[start:start + nxt.start()] if nxt else roster[start:]


def test_roster_doc_exists_and_lists_every_real_agent():
    roster = _roster_text()
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
    roster = _roster_text()
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


@pytest.mark.parametrize("marker", sorted(SEVEN_ROLE_ANSWERS))
def test_roster_answers_all_seven_asserted_roles(marker):
    """Forbidding the seven names is only half the contract.

    The roster must also SAY where each asserted role's work really lives.
    Before 2026-09-04 the section answered only four of the seven, which is
    exactly why that day's re-audit had to rebuild the correspondence by grep --
    the re-litigation the section exists to prevent. Answering four of seven is
    therefore a real failure of this section, not a partial success.
    """
    assert marker in _roster_text(), (
        f"ROSTER.md no longer answers the asserted role {marker!r}; every one of "
        f"the seven must keep a real answer or the section stops being usable as "
        f"the check a poster claim is held against"
    )


@pytest.mark.parametrize("marker,agent", sorted(NAME_MAPPED_ROLES.items()))
def test_name_mapped_roles_point_at_really_dispatched_agents(marker, agent):
    """The three name-mappings are checked against the graph, not the prose.

    ROSTER.md claims these three asserted roles resolve to a real dispatched
    agent. That claim is only worth writing down if it is falsifiable, so it is
    held against `agent_dispatch_map()`'s live derivation from
    `main_graph.json`: repointing one of these nodes at another agent, or
    dropping the agent's profile, fails here instead of quietly leaving the
    roster asserting a mapping the graph stopped backing.
    """
    block = _role_answer_block(_roster_text(), marker)
    assert agent in block, f"{marker!r} must cite its real agent name {agent!r}"

    live = agent_dispatch_map(ROOT)
    assert agent in live, f"{agent} is no longer a real agent profile"
    assert live[agent]["status"] == GRAPH_DISPATCHED, (
        f"ROSTER.md presents {agent} as really performing {marker!r}, but its "
        f"live dispatch status is {live[agent]['status']}"
    )

    # The ownership citation is the parenthetical right after the agent name.
    # Scoped there deliberately: the surrounding prose also names nodes an agent
    # does NOT own (implementation-agent "never reaches SIGNOFF"), and reading
    # those as ownership claims would make the roster unable to state a
    # separation-of-duties fact without tripping its own test.
    tail = block[block.index(agent) + len(agent):]
    paren = re.search(r"\(([^)]*)\)", tail)
    assert paren, f"{marker!r} must cite {agent}'s real nodes in parentheses"
    cited_nodes = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", paren.group(1)))
    real_nodes = set(live[agent]["graph_nodes"])
    assert cited_nodes == real_nodes, (
        f"ROSTER.md credits {agent} with main_graph.json nodes "
        f"{sorted(cited_nodes)}, but the live graph assigns it "
        f"{sorted(real_nodes)}"
    )
