"""Unit tests for dv_harness/router.py's protocol fold-in (2026-09-04,
AI-mechanism re-audit gap #4 "Route & Skill Resolver").

The engine-level proof that this reaches the real delegated task lives in
test_protocol_and_environment_mode_engine_wiring.py; these tests pin
RouteResolver.resolve()'s own contract -- what it adds, what it refuses to
add, and that route/agent stay the graph's answer.
"""
import pathlib

from dv_harness.protocol_router import resolve_protocol
from dv_harness.router import RouteResolver, PROTOCOL_SENSITIVE_SKILLS

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Node:
    """Minimal stand-in for graph.GraphNode -- resolve() reads exactly these
    four attributes and nothing else."""

    def __init__(self, route, agent, skills):
        self.route = route
        self.agent = agent
        self.skills = list(skills)


def _usb():
    return resolve_protocol({"protocol_hint": "USB3 enumeration failure"})


def _pcie():
    return resolve_protocol({"failing_test_name": "test_pcie_link_train"})


def test_same_node_different_evidence_yields_different_skills():
    node = _Node("analysis-route", "analysis-agent",
                 ["subsystem-to-soc-verification", "protocol-router"])
    r = RouteResolver(REPO_ROOT)

    usb = r.resolve(node, protocol_decision=_usb())
    pcie = r.resolve(node, protocol_decision=_pcie())

    assert usb["skills"] != pcie["skills"]
    assert usb["skills"] == node.skills + ["usb-profile", "usb-vip-lookup"]
    assert pcie["skills"] == node.skills + ["pcie-profile"]
    # route/agent deliberately stay the graph's own answer -- see resolve()'s
    # docstring for why a protocol must not silently reassign the agent.
    assert usb["route"] == pcie["route"] == "analysis-route"
    assert usb["agent"] == pcie["agent"] == "analysis-agent"
    # The node's own declared skills are never dropped or reordered.
    assert usb["static_skills"] == pcie["static_skills"] == node.skills
    assert usb["skills"][:len(node.skills)] == node.skills


def test_node_that_did_not_declare_protocol_router_is_untouched():
    node = _Node("implementation-route", "implementation-agent",
                 ["git-pull-sync", "git-workflow"])
    out = RouteResolver(REPO_ROOT).resolve(node, protocol_decision=_usb())
    assert out["skills"] == node.skills
    assert out["protocol_skill_routes"] == []


def test_unresolved_or_absent_decision_changes_nothing():
    node = _Node("analysis-route", "analysis-agent", ["protocol-router"])
    r = RouteResolver(REPO_ROOT)
    unresolved = resolve_protocol({"protocol_hint": "please continue"})
    assert r.resolve(node, protocol_decision=unresolved)["skills"] == node.skills
    assert r.resolve(node)["skills"] == node.skills
    assert r.resolve(node, protocol_decision=None)["protocol_skill_routes"] == []


def test_resolver_without_a_root_still_adds_the_primary_route_only():
    """RouteResolver(None) has no registry to read, so only the SKILL.md
    primary route survives -- degraded, never crashing, and never inventing
    the profile/vip-lookup names it could not look up."""
    node = _Node("analysis-route", "analysis-agent", ["protocol-router"])
    out = RouteResolver().resolve(node, protocol_decision=_usb())
    assert out["skills"] == ["protocol-router", "usb-profile"]
    assert out["protocol_skill_routes"] == ["USB/usb-profile"]


def test_agent_falls_back_to_the_default_route_table_as_before():
    node = _Node("debug-route", None, [])
    assert RouteResolver(REPO_ROOT).resolve(node)["agent"] == "debug-agent"


def test_a_skill_the_node_already_declares_is_not_duplicated():
    node = _Node("analysis-route", "analysis-agent", ["protocol-router", "usb-profile"])
    out = RouteResolver(REPO_ROOT).resolve(node, protocol_decision=_usb())
    assert out["skills"].count("usb-profile") == 1
    # Only the genuinely-new route is reported as added.
    assert out["protocol_skill_routes"] == ["USB/usb-vip-lookup"]


def test_the_sensitivity_trigger_is_the_real_skill_name_the_graph_uses():
    assert "protocol-router" in PROTOCOL_SENSITIVE_SKILLS
    assert (REPO_ROOT / ".claude" / "skills" / "CORE" / "protocol-router" / "SKILL.md").exists()
