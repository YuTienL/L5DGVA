"""Research intent routing + the `dv-harness research` front door.

Master prompt sections 17 (RESEARCH INTENT ROUTING), 18 (FUTURE DAILY
RESEARCH INVOCATION), 19/53 (`/research` command interface and its semantics),
and Stage-1 acceptance test F (Future Short Invocation).

Two halves, and the second is the important one:

1. A research request routes to research-ingestion -> research-architect ->
   Human Approval Gate, with no agent named by the user.
2. NOTHING existing changed. Section 17's own non-negotiable is "Do not
   interfere with existing DV/USB/PCIe/Ethernet/AMBA/MIPI/CAN-FD/regression/
   failure-triage/coverage/signoff workflows", so the negative tests here
   replay `test_protocol_router.py`'s OWN evidence strings (not paraphrases of
   them) through both the new classifier and the untouched old one.
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import commands
from dv_harness.capability_evolution import HUMAN_APPROVAL_STAGE
from dv_harness.engine import DVHarness
from dv_harness.models import Stage
from dv_harness.protocol_router import resolve_protocol
from dv_harness.router import (
    DEFAULT_ROUTES,
    PRIOR_EVIDENCE_LOOKUP_INTENTS,
    RESEARCH_FOCUS_DOMAINS,
    RESEARCH_INTENTS,
    RESEARCH_INTENT_FIELDS,
    RESEARCH_ROUTE,
    RouteResolver,
    research_route_plan,
    resolve_research_intent,
)

ROOT = Path(__file__).resolve().parents[1]

# Master prompt section 18's canonical natural-language form, verbatim. This
# exact string is what a future user is promised they can type without
# replaying the master prompt or naming any agent.
SECTION_18_CANONICAL = (
    "Analyze this new paper through the existing DV Agent Harness L5 research "
    "workflow. Extract the evidence, compare it with the current Harness and "
    "prior research, and decide KEEP, ENHANCE, ADD, EXPERIMENT, or REJECT. "
    "Stop before implementation."
)

# Section 17's seven "Examples of qualifying user requests", verbatim.
SECTION_17_EXAMPLES = (
    "Analyze this DV paper.",
    "Extract useful methods from this verification report.",
    "Compare this PSS paper with our current Harness.",
    "Study this regression-triage method.",
    "Determine whether this paper should change L5.",
    "Learn from these new verification papers.",
    "What should we adopt from this standard update?",
)

# Every free-text evidence value dv_harness_tests/test_protocol_router.py
# actually uses, copied from that file rather than invented here. If one of
# these ever starts reading as a research request, this suite fails before the
# real DV routing path can be affected.
EXISTING_DV_ROUTING_CASES = (
    "Investigate a USB3 link training failure on port 0",
    "Investigate a PCIe LTSSM link training failure on port 0",
    "please debug the USB device",
    "the USB controller's register interface uses an AXI backend",
    "verify the AXI4 interconnect fabric",
    "please continue the regression",
    "USB device controller",
    "AMBA fabric",
    "PCI Express link",
    "USB3 SuperSpeed device",
    "MIPI CSI-2 receiver",
    "CAN FD bus-off recovery",
    "AMAB4 fabric review",
    "AIX4 interconnect review",
    "AXI Stream FIFO underflow",
    "MMC boot partition",
    "SDIO interrupt function",
    "USB3 enumeration failure",
    "PCIe LTSSM failure",
    "MMC boot partition failure",
    "please continue",
)


class _Node:
    """Same minimal graph-node stand-in test_route_resolver_protocol_fold_in.py
    uses -- resolve() reads exactly these three attributes."""

    def __init__(self, route, agent, skills):
        self.route = route
        self.agent = agent
        self.skills = list(skills)


def _fresh_project():
    return Path(tempfile.mkdtemp())


def _run_cli(root, *args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(root), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60, encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Stage-1 acceptance test F -- Future Short Invocation
# ---------------------------------------------------------------------------

def test_acceptance_f_canonical_request_routes_to_ingestion_then_architect():
    """Section 18: 'The router must automatically invoke research-ingestion
    -> ... -> research-architect -> Human Gate. No manual agent naming should
    be required for normal use.'

    The input names no agent and no skill; the route does."""
    assert "research-ingestion" not in SECTION_18_CANONICAL
    assert "research-architect" not in SECTION_18_CANONICAL

    decision = resolve_research_intent({"protocol_hint": SECTION_18_CANONICAL})
    assert decision["resolved"] is True
    assert decision["intent"] in RESEARCH_INTENTS
    assert decision["route"] == RESEARCH_ROUTE
    assert decision["agent"] == "research-architect"

    plan = research_route_plan(decision, root=ROOT, documents=["sample_paper.pdf"])
    steps = [s["step"] for s in plan["steps"]]
    assert steps.index("research-ingestion") < steps.index("research-architect")
    assert steps[-1] == "human-approval-gate"
    assert plan["stops_before_implementation"] is True
    assert plan["human_approval_stage"] == HUMAN_APPROVAL_STAGE


def test_acceptance_f_every_routed_step_names_an_asset_that_really_exists():
    """A plan that names a file which is not there is a narrative, not a
    route. `exists` is computed against the real tree, so this fails the day
    the skill or the agent profile is renamed or deleted."""
    decision = resolve_research_intent({"protocol_hint": SECTION_18_CANONICAL})
    plan = research_route_plan(decision, root=ROOT)
    for step in plan["all_steps"]:
        assert step["exists"] is True, (step["step"], step["asset"])
    assert (ROOT / ".claude" / "skills" / "research-ingestion" / "SKILL.md").is_file()
    assert (ROOT / ".claude" / "agents" / "research-architect.md").is_file()


def test_acceptance_f_through_the_real_cli_front_door():
    """The same route, through a real `dv-harness research` subprocess -- the
    `/research sample_paper.pdf` half of acceptance test F."""
    tmp = _fresh_project()
    r = _run_cli(tmp, "research", "sample_paper.pdf")
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout[: r.stdout.rindex("}") + 1])
    steps = [s["step"] for s in plan["steps"]]
    assert steps[0] == "research-ingestion"
    assert steps.index("research-architect") < steps.index("human-approval-gate")
    assert plan["documents"] == ["sample_paper.pdf"]
    assert "research is not implementation" in r.stdout


def test_acceptance_f_natural_language_request_through_the_cli_needs_no_agent_name():
    tmp = _fresh_project()
    r = _run_cli(tmp, "research", "--request", SECTION_18_CANONICAL)
    assert r.returncode == 0, r.stderr
    assert "research-ingestion" in r.stdout and "research-architect" in r.stdout


# ---------------------------------------------------------------------------
# Section 17 -- the five intents, from the master prompt's own examples
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("request_text", SECTION_17_EXAMPLES)
def test_every_section_17_example_request_is_recognized(request_text):
    decision = resolve_research_intent({"protocol_hint": request_text})
    assert decision["resolved"] is True, decision["evidence"]
    assert decision["intent"] in RESEARCH_INTENTS


def test_the_five_intents_are_exactly_section_17s_list():
    assert set(RESEARCH_INTENTS) == {
        "RESEARCH_ANALYSIS", "RESEARCH_COMPARE", "RESEARCH_ARCHITECTURE_IMPACT",
        "RESEARCH_DEEP_ANALYSIS", "RESEARCH_MULTI_DOCUMENT",
    }


@pytest.mark.parametrize("request_text,expected", [
    ("Analyze this DV paper.", "RESEARCH_ANALYSIS"),
    ("Compare this PSS paper with our current Harness.", "RESEARCH_COMPARE"),
    ("Determine whether this paper should change L5.", "RESEARCH_ARCHITECTURE_IMPACT"),
    ("Perform deep research analysis on this paper.", "RESEARCH_DEEP_ANALYSIS"),
    ("Learn from these new verification papers.", "RESEARCH_MULTI_DOCUMENT"),
])
def test_distinct_requests_select_distinct_intents(request_text, expected):
    """Genuinely input-driven: five structurally different requests walk five
    different branches, the same property test_protocol_router.py pins for
    resolve_protocol()."""
    assert resolve_research_intent({"protocol_hint": request_text})["intent"] == expected


def test_prior_evidence_lookup_is_conditional_not_always_on():
    """Section 17 says 'prior evidence lookup IF APPLICABLE' -- so a plan that
    always includes it would not be following the section, it would be
    ignoring the qualifier."""
    single = research_route_plan(
        resolve_research_intent({"protocol_hint": "Analyze this DV paper."}),
        root=ROOT, documents=["a.pdf"])
    assert "prior-evidence-lookup" not in [s["step"] for s in single["steps"]]
    assert "prior-evidence-lookup" in [s["step"] for s in single["skipped_steps"]]

    compare = research_route_plan(
        resolve_research_intent(
            {"protocol_hint": "Compare this PSS paper with our current Harness."}),
        root=ROOT, documents=["a.pdf"])
    assert "prior-evidence-lookup" in [s["step"] for s in compare["steps"]]
    assert compare["intent"] in PRIOR_EVIDENCE_LOOKUP_INTENTS


def test_two_documents_trigger_prior_evidence_lookup_even_for_a_plain_analysis():
    plan = research_route_plan(
        resolve_research_intent({"research_intent": "RESEARCH_ANALYSIS"}),
        root=ROOT, documents=["a.pdf", "b.pdf"])
    assert "prior-evidence-lookup" in [s["step"] for s in plan["steps"]]


# ---------------------------------------------------------------------------
# NON-INTERFERENCE -- section 17's own non-negotiable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dv_request", EXISTING_DV_ROUTING_CASES)
def test_existing_dv_routing_evidence_is_never_read_as_research(dv_request):
    decision = resolve_research_intent({"protocol_hint": dv_request})
    assert decision["resolved"] is False, decision["evidence"]
    assert decision["reason"] == "NOT_A_RESEARCH_REQUEST"
    assert research_route_plan(decision, root=ROOT) is None


@pytest.mark.parametrize("dv_request", EXISTING_DV_ROUTING_CASES)
def test_existing_protocol_routing_answers_are_bit_for_bit_unchanged(dv_request):
    """The strongest form of 'does not interfere': the real protocol router,
    fed the real evidence its own test suite feeds it, is asked twice -- once
    plain, once with the research classifier having run over the same text --
    and must answer identically. resolve_protocol() takes no research input,
    so this also pins that no future edit sneaks one in."""
    evidence = {"protocol_hint": dv_request}
    before = resolve_protocol(dict(evidence))
    resolve_research_intent(dict(evidence))
    after = resolve_protocol(dict(evidence))
    assert before == after


def test_route_resolver_resolve_is_untouched_by_the_research_addition():
    """RouteResolver.resolve() is the function on the real engine.run_stage()
    path. Its signature and its answer for a real graph node must not have
    moved: research routing is a SEPARATE entry point (resolve_intent), not a
    new parameter or a new branch inside resolve()."""
    params = list(inspect.signature(RouteResolver.resolve).parameters)
    assert params == ["self", "node", "protocol_decision"]

    node = _Node("analysis-route", "analysis-agent",
                 ["subsystem-to-soc-verification", "protocol-router"])
    usb = resolve_protocol({"protocol_hint": "USB3 enumeration failure"})
    out = RouteResolver(ROOT).resolve(node, protocol_decision=usb)
    assert out["route"] == "analysis-route"
    assert out["agent"] == "analysis-agent"
    assert out["skills"] == node.skills + ["usb-profile", "usb-vip-lookup"]
    assert out["protocol_skill_routes"] == ["USB/usb-profile", "USB/usb-vip-lookup"]


def test_resolve_intent_returns_no_plan_for_a_dv_request():
    out = RouteResolver(ROOT).resolve_intent(
        {"protocol_hint": "Investigate a PCIe LTSSM link training failure on port 0"})
    assert out["research_decision"]["resolved"] is False
    assert out["research_route_plan"] is None


def test_the_seven_pre_existing_routes_are_unchanged_and_research_is_additive():
    """DEFAULT_ROUTES gained one pair; it lost and changed none."""
    assert DEFAULT_ROUTES["analysis-route"] == "analysis-agent"
    assert DEFAULT_ROUTES["implementation-route"] == "implementation-agent"
    assert DEFAULT_ROUTES["build-route"] == "build-agent"
    assert DEFAULT_ROUTES["debug-route"] == "debug-agent"
    assert DEFAULT_ROUTES["regression-route"] == "regression-agent"
    assert DEFAULT_ROUTES["review-route"] == "review-agent"
    assert DEFAULT_ROUTES["lead-route"] == "dv-lead"
    assert DEFAULT_ROUTES[RESEARCH_ROUTE] == "research-architect"
    assert len(DEFAULT_ROUTES) == 8


def test_no_graph_node_declares_the_research_route():
    """Adding the route must not silently promote research-architect to a
    stage-owning role -- .claude/agents/ROSTER.md records it NOT_DISPATCHED,
    and agent_dispatch.py derives that from the graph, not from
    DEFAULT_ROUTES."""
    graph = json.loads(
        (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"))
    nodes = graph.get("nodes") or []
    assert nodes, "main_graph.json has no nodes -- test cannot prove anything"
    for node in nodes:
        assert node.get("route") != RESEARCH_ROUTE, node
        assert node.get("agent") != "research-architect", node


def test_the_classifier_reads_only_user_intent_fields_never_file_paths():
    """A git-modified file called paper.pdf, a failing test named
    test_paper_analysis, or a subsystem boundary mentioning a standard must
    NOT make a DV run look like a research request. This is the concrete
    mechanism behind 'does not interfere', so it is pinned explicitly."""
    assert RESEARCH_INTENT_FIELDS == ("research_intent", "protocol_hint")
    hijack_attempts = [
        {"modified_files": ["docs/paper.pdf", "analyze_paper.py"]},
        {"failing_test_name": "test_analyze_verification_report"},
        {"subsystem_boundary": "compare this standard update paper"},
        {"active_config": "study the whitepaper method"},
    ]
    for evidence in hijack_attempts:
        evidence = dict(evidence, protocol_hint="Investigate a USB3 link training failure")
        assert resolve_research_intent(evidence)["resolved"] is False, evidence


# ---------------------------------------------------------------------------
# Section 19/53 -- the front door, and its "no business logic" rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag,expected", [
    ("--compare", "RESEARCH_COMPARE"),
    ("--impact", "RESEARCH_ARCHITECTURE_IMPACT"),
    ("--deep", "RESEARCH_DEEP_ANALYSIS"),
])
def test_section_53_mode_flags_select_their_documented_intent(flag, expected):
    tmp = _fresh_project()
    r = _run_cli(tmp, "research", flag, "paper.pdf")
    assert r.returncode == 0, r.stderr
    assert f'"intent": "{expected}"' in r.stdout


def test_multiple_documents_select_multi_document_intent():
    tmp = _fresh_project()
    r = _run_cli(tmp, "research", "a.pdf", "b.pdf", "c.pdf")
    assert r.returncode == 0, r.stderr
    assert '"intent": "RESEARCH_MULTI_DOCUMENT"' in r.stdout


@pytest.mark.parametrize("focus", RESEARCH_FOCUS_DOMAINS)
def test_section_53_focus_narrows_emphasis_without_changing_the_route(focus):
    tmp = _fresh_project()
    h = DVHarness(tmp)
    plain = commands.cmd_research(h, documents=["p.pdf"])
    focused = commands.cmd_research(h, documents=["p.pdf"], focus=focus)
    assert focused["focus"] == focus
    assert [s["step"] for s in focused["steps"]] == [s["step"] for s in plain["steps"]]
    assert focused["route"] == plain["route"] == RESEARCH_ROUTE


def test_the_four_focus_domains_are_section_53s_own_list():
    assert set(RESEARCH_FOCUS_DOMAINS) == {"regression", "pss", "debug", "planning"}


def test_an_unknown_focus_is_refused_rather_than_silently_ignored():
    with pytest.raises(ValueError, match="Unknown research focus"):
        commands.cmd_research(DVHarness(_fresh_project()),
                              documents=["p.pdf"], focus="waveforms")


def test_conflicting_mode_flags_are_refused():
    with pytest.raises(ValueError, match="at most one"):
        commands.cmd_research(DVHarness(_fresh_project()),
                              documents=["p.pdf"], compare=True, deep=True)


def test_a_non_research_free_text_request_is_refused_by_the_front_door():
    tmp = _fresh_project()
    r = _run_cli(tmp, "research", "--request", "please continue the regression")
    assert r.returncode == 2
    assert "Not recognized as a research request" in r.stdout


def test_the_front_door_holds_no_business_logic():
    """Section 19: 'Do NOT place core logic in the command itself. The command
    is only an entry point into installed Skill/Agent orchestration.'

    cmd_research() may build an evidence dict and call the router. It must not
    read a document, build a card, score a candidate or approve anything."""
    src = inspect.getsource(commands.cmd_research)
    for forbidden in ("open(", "read_text", "build_research_evidence_card",
                      "decide_recommendation", "persist_candidate",
                      "ControlPlane", "approve("):
        assert forbidden not in src, f"cmd_research must not do this itself: {forbidden}"
    assert "resolve_research_intent" in src and "research_route_plan" in src


def test_the_front_door_and_a_natural_language_request_share_one_implementation():
    """Section 53: these 'must route into the same installed Skill/Agent logic
    and must not fork a second implementation'."""
    h = DVHarness(_fresh_project())
    via_flag = commands.cmd_research(h, documents=["p.pdf"], compare=True)
    via_text = research_route_plan(
        resolve_research_intent(
            {"protocol_hint": "Compare this paper with our prior research."}),
        root=h.root, documents=["p.pdf"])
    assert [s["step"] for s in via_flag["steps"]] == [s["step"] for s in via_text["steps"]]
    assert via_flag["intent"] == via_text["intent"] == "RESEARCH_COMPARE"


def test_the_front_door_records_a_real_audit_event():
    tmp = _fresh_project()
    h = DVHarness(tmp)
    commands.cmd_research(h, documents=["p.pdf"], impact=True)
    events = [json.loads(line) for line in
              (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    research_events = [e for e in events if e.get("cmd") == "research"]
    assert len(research_events) == 1
    assert research_events[0]["intent"] == "RESEARCH_ARCHITECTURE_IMPACT"
    assert research_events[0]["agent"] == "research-architect"


# ---------------------------------------------------------------------------
# The Human Approval Gate the route ends at must be operable by a human
# ---------------------------------------------------------------------------

def test_the_advertised_approve_command_actually_runs():
    """Regression test for a real defect: capability_evolution.py published an
    approve_command that argparse rejected -- wrong argument form AND a stage
    key excluded by the parser's own `choices`. A gate whose instructions do
    not run is not installed. This executes the real published command."""
    from dv_harness.capability_evolution import human_approval_status

    tmp = _fresh_project()
    DVHarness(tmp)
    status = human_approval_status(tmp)
    assert status["approved"] is False

    published = status["approve_command"]
    assert published.startswith(f"dv-harness approve {HUMAN_APPROVAL_STAGE} ")
    assert "--stage" not in published

    r = _run_cli(tmp, "approve", HUMAN_APPROVAL_STAGE,
                 "--note", "reviewed the candidate", "--reviewer-id", "peter",
                 "--reviewer-confidence", "HIGH")
    assert r.returncode == 0, r.stderr

    after = human_approval_status(tmp)
    assert after["approved"] is True
    assert after["approval"]["reviewer_id"] == "peter"


def test_approval_only_stages_do_not_leak_into_the_engine_driving_verbs():
    """The research approval key is approvable, and ONLY approvable. Letting
    it reach set-stage/redirect/correct would put the engine in a stage the
    graph does not have."""
    assert commands.APPROVAL_ONLY_STAGES == frozenset({HUMAN_APPROVAL_STAGE})
    assert HUMAN_APPROVAL_STAGE not in {s.value for s in Stage}
    with pytest.raises(ValueError, match="Unknown stage"):
        commands._check_stage(HUMAN_APPROVAL_STAGE)
    commands._check_approval_stage(HUMAN_APPROVAL_STAGE)  # must not raise

    tmp = _fresh_project()
    r = _run_cli(tmp, "set-stage", HUMAN_APPROVAL_STAGE)
    assert r.returncode != 0


def test_every_real_graph_stage_is_still_approvable():
    choices = commands.approval_stage_choices()
    for stage in Stage:
        assert stage.value in choices
    assert len(choices) == len(list(Stage)) + len(commands.APPROVAL_ONLY_STAGES)
