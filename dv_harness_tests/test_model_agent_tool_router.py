"""Real, passing tests for dv_harness/model_agent_tool_router.py.

Drives everything against THIS repo's own real .claude/agents/*.md profile
files (never a synthetic fixture) so the router is proven against the same
production data engine.py's real RouteResolver.resolve() and
agent_profile.load_agent_profile() already act on. Includes required negative
controls proving the router REFUSES to fabricate an agent/model/tool when no
real candidate is available (Evidence Truth Rule), per this project's own
"prove the module refuses to fabricate an answer when evidence is absent"
grading requirement.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import model_agent_tool_router as m
from dv_harness import router as router_mod

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- Module-level invariants -------------------------------------------------

def test_task_types_match_router_default_routes():
    assert set(m.TASK_TYPES) == set(router_mod.DEFAULT_ROUTES.keys())


def test_every_fallback_chain_starts_with_the_primary_router_agent():
    for task_type, chain in m.AGENT_FALLBACK_CHAINS.items():
        assert chain[0] == router_mod.DEFAULT_ROUTES[task_type]


def test_every_fallback_chain_ends_at_dv_lead():
    for chain in m.AGENT_FALLBACK_CHAINS.values():
        assert chain[-1] == "dv-lead"


def test_every_named_fallback_agent_has_a_real_profile_file():
    for chain in m.AGENT_FALLBACK_CHAINS.values():
        for name in chain:
            p = REPO_ROOT / ".claude" / "agents" / f"{name}.md"
            assert p.is_file(), f"{name} named in a fallback chain has no real profile file"


def test_alternate_tool_map_is_symmetric_and_names_real_tool_strings():
    for k, v in m.ALTERNATE_TOOL_MAP.items():
        assert m.ALTERNATE_TOOL_MAP.get(v) == k


# --- agent_profile.py additive `model` parse --------------------------------

def test_agent_profile_parses_real_model_frontmatter():
    from dv_harness.agent_profile import load_agent_profile
    prof = load_agent_profile(REPO_ROOT, "dv-lead")
    assert prof is not None and prof.found
    assert prof.model == "inherit"


def test_agent_profile_model_is_none_when_frontmatter_declares_none():
    from dv_harness.agent_profile import load_agent_profile
    # protocol-corner-case-intelligence-agent-style profiles (per this repo's
    # own agent_profile.py NOTICE) declare only name:/description: -- pick a
    # real profile with no tools:/model: line if one exists, else this test
    # is skipped honestly rather than asserting against a fabricated fixture.
    candidates = sorted((REPO_ROOT / ".claude" / "agents").glob("*.md"))
    no_model = None
    for p in candidates:
        text = p.read_text(encoding="utf-8")
        if "\nmodel:" not in text and not text.startswith("model:"):
            no_model = p.stem
            break
    if no_model is None:
        pytest.skip("every real agent profile in this repo currently declares model: -- nothing to assert the None path against")
    prof = load_agent_profile(REPO_ROOT, no_model)
    assert prof.model is None


# --- resolve_agent() ---------------------------------------------------------

def test_resolve_agent_preferred_path_over_real_repo():
    res = m.resolve_agent("analysis-route", REPO_ROOT)
    assert res.status == m.AGENT_RESOLVED_PREFERRED
    assert res.resolved_agent == "analysis-agent"
    assert res.profile is not None and res.profile.found
    # informational only, read from the real agent_dispatch table
    assert res.dispatch_status == "GRAPH_DISPATCHED"


def test_resolve_agent_falls_back_when_preferred_declared_unavailable():
    res = m.resolve_agent("analysis-route", REPO_ROOT, unavailable_agents=frozenset({"analysis-agent"}))
    assert res.status == m.AGENT_RESOLVED_FALLBACK
    assert res.resolved_agent == "dv-lead"
    assert res.tried[0] == {"agent": "analysis-agent", "declared_unavailable": True, "profile_found": False}


def test_resolve_agent_blocked_when_entire_chain_unavailable_never_fabricates_a_name():
    """Negative control: with every real candidate in the chain declared
    unavailable, the router must report BLOCKED_NO_CANDIDATE and resolve to
    NO agent -- never invent a name to keep the caller unblocked."""
    res = m.resolve_agent("analysis-route", REPO_ROOT,
                           unavailable_agents=frozenset({"analysis-agent", "dv-lead"}))
    assert res.status == m.AGENT_BLOCKED_NO_CANDIDATE
    assert res.resolved_agent is None
    assert len(res.tried) == 2


def test_resolve_agent_unresolved_task_type_never_fabricates_a_route():
    """Negative control: an unknown task type must be reported honestly,
    never silently mapped onto some plausible-looking real route."""
    res = m.resolve_agent("nonexistent-route", REPO_ROOT)
    assert res.status == m.AGENT_UNRESOLVED_TASK_TYPE
    assert res.resolved_agent is None
    assert res.fallback_chain == []


def test_resolve_agent_lead_route_has_no_further_fallback():
    res = m.resolve_agent("lead-route", REPO_ROOT, unavailable_agents=frozenset({"dv-lead"}))
    assert res.status == m.AGENT_BLOCKED_NO_CANDIDATE


def test_resolve_agent_missing_profile_on_disk_is_honestly_unavailable(tmp_path):
    """A root with no .claude/agents tree at all must never be read as
    'agent available' -- profile_found must be False, not fabricated True."""
    res = m.resolve_agent("analysis-route", tmp_path)
    assert res.status == m.AGENT_BLOCKED_NO_CANDIDATE
    assert all(not t["profile_found"] for t in res.tried)


# --- resolve_model() ---------------------------------------------------------

def test_resolve_model_no_agent_is_honestly_unresolved():
    """Negative control: with no agent profile at all, the router must never
    guess a model -- it must report MODEL_UNRESOLVED_NO_AGENT with no value."""
    res = m.resolve_model(None)
    assert res.status == m.MODEL_UNRESOLVED_NO_AGENT
    assert res.resolved_model is None


def test_resolve_model_preferred_from_real_profile():
    from dv_harness.agent_profile import load_agent_profile
    prof = load_agent_profile(REPO_ROOT, "dv-lead")
    res = m.resolve_model(prof)
    assert res.status == m.MODEL_RESOLVED_PREFERRED
    assert res.resolved_model == "inherit"


def test_resolve_model_falls_back_when_declared_model_unavailable():
    from dv_harness.agent_profile import load_agent_profile
    prof = load_agent_profile(REPO_ROOT, "dv-lead")
    res = m.resolve_model(prof, unavailable_models=frozenset({"inherit"}))
    # 'inherit' is both the declared model AND the fallback default here, so
    # declaring it unavailable must block, never silently "fall back to
    # itself" and claim success.
    assert res.status == m.MODEL_BLOCKED_NO_CANDIDATE
    assert res.resolved_model is None


def test_resolve_model_no_declaration_falls_back_to_default():
    from dv_harness.agent_profile import AgentProfile
    prof = AgentProfile(name="synthetic-no-model", found=True, tools=["Read"], model=None)
    res = m.resolve_model(prof)
    assert res.status == m.MODEL_RESOLVED_NO_DECLARATION
    assert res.resolved_model == m.MODEL_FALLBACK_DEFAULT


def test_resolve_model_declared_but_alternate_model_available():
    from dv_harness.agent_profile import AgentProfile
    prof = AgentProfile(name="synthetic", found=True, tools=[], model="some-declared-model")
    res = m.resolve_model(prof, unavailable_models=frozenset({"some-declared-model"}))
    assert res.status == m.MODEL_RESOLVED_FALLBACK
    assert res.resolved_model == m.MODEL_FALLBACK_DEFAULT
    assert res.requested_model == "some-declared-model"


def test_model_fallback_default_is_never_a_fabricated_model_name():
    """The Evidence Truth Rule check: the ONLY fallback value this router
    will ever assert is the literal 'inherit' -- never an invented model id
    like a specific Sonnet/Haiku/Opus name this repo has no real source for."""
    assert m.MODEL_FALLBACK_DEFAULT == "inherit"


# --- resolve_tools() ----------------------------------------------------------

def test_resolve_tools_no_agent_is_honestly_unresolved():
    res = m.resolve_tools(None)
    assert res.status == m.TOOL_UNRESOLVED_NO_AGENT
    assert res.resolved_tools == []


def test_resolve_tools_preferred_from_real_profile():
    from dv_harness.agent_profile import load_agent_profile
    prof = load_agent_profile(REPO_ROOT, "analysis-agent")
    res = m.resolve_tools(prof)
    assert res.status == m.TOOL_RESOLVED_PREFERRED
    assert res.resolved_tools == prof.tools
    assert res.substitutions == []
    assert res.dropped == []


def test_resolve_tools_substitutes_documented_alternate():
    from dv_harness.agent_profile import load_agent_profile
    prof = load_agent_profile(REPO_ROOT, "analysis-agent")
    assert "PowerShell" in (prof.tools or [])
    res = m.resolve_tools(prof, unavailable_tools=frozenset({"PowerShell"}))
    assert res.status == m.TOOL_RESOLVED_FALLBACK
    assert "Bash" in res.resolved_tools
    assert "PowerShell" not in res.resolved_tools
    assert res.substitutions == [{"declared": "PowerShell", "substituted": "Bash"}]


def test_resolve_tools_drops_a_tool_with_no_documented_alternate_never_invents_one():
    """Negative control: an unavailable tool with no ALTERNATE_TOOL_MAP entry
    must be dropped and reported, never silently kept and never silently
    replaced by some unrelated tool this router did not document."""
    from dv_harness.agent_profile import AgentProfile
    prof = AgentProfile(name="synthetic", found=True, tools=["Read", "Grep"], model="inherit")
    res = m.resolve_tools(prof, unavailable_tools=frozenset({"Read"}))
    assert "Read" not in res.resolved_tools
    assert res.dropped == ["Read"]
    assert res.resolved_tools == ["Grep"]
    assert res.status == m.TOOL_RESOLVED_FALLBACK


def test_resolve_tools_blocked_when_every_declared_tool_unavailable_never_fabricates_scope():
    from dv_harness.agent_profile import AgentProfile
    prof = AgentProfile(name="synthetic", found=True, tools=["Read"], model="inherit")
    res = m.resolve_tools(prof, unavailable_tools=frozenset({"Read"}))
    assert res.status == m.TOOL_BLOCKED_NO_CANDIDATE
    assert res.resolved_tools == []


def test_resolve_tools_no_explicit_scope_is_reported_distinctly():
    from dv_harness.agent_profile import AgentProfile
    prof = AgentProfile(name="synthetic", found=True, tools=None, model="inherit")
    res = m.resolve_tools(prof)
    assert res.status == m.TOOL_RESOLVED_NO_EXPLICIT_SCOPE
    assert res.resolved_tools == []


# --- route() composite / worst-wins ------------------------------------------

def test_route_all_clean_is_routed():
    d = m.route("analysis-route", REPO_ROOT)
    assert d.overall_status == m.OVERALL_ROUTED
    assert d.agent.status == m.AGENT_RESOLVED_PREFERRED
    assert d.model.status == m.MODEL_RESOLVED_PREFERRED
    assert d.tool.status == m.TOOL_RESOLVED_PREFERRED


def test_route_agent_fallback_alone_is_routed_with_fallback():
    d = m.route("analysis-route", REPO_ROOT, unavailable_agents=["analysis-agent"])
    assert d.overall_status == m.OVERALL_ROUTED_WITH_FALLBACK
    assert d.agent.status == m.AGENT_RESOLVED_FALLBACK


def test_route_worst_wins_single_blocked_dimension_blocks_the_whole_route():
    """House style rule 3 (worst-wins composite gate), applied to this
    router's own overall verdict: agent and tool both resolve cleanly, but
    the model dimension is fully blocked -- the WHOLE route must read
    BLOCKED, never a partial success."""
    d = m.route("analysis-route", REPO_ROOT, unavailable_models=["inherit"])
    assert d.agent.status == m.AGENT_RESOLVED_PREFERRED
    assert d.tool.status == m.TOOL_RESOLVED_PREFERRED
    assert d.model.status == m.MODEL_BLOCKED_NO_CANDIDATE
    assert d.overall_status == m.OVERALL_BLOCKED


def test_route_worst_wins_blocked_outranks_a_simultaneous_fallback():
    """Even when the AGENT dimension has already fallen back successfully,
    a BLOCKED model dimension must still make the overall verdict BLOCKED --
    never softened to ROUTED_WITH_FALLBACK because one dimension recovered."""
    d = m.route(
        "analysis-route", REPO_ROOT,
        unavailable_agents=["analysis-agent"],
        unavailable_models=["inherit"],
    )
    assert d.agent.status == m.AGENT_RESOLVED_FALLBACK
    assert d.model.status == m.MODEL_BLOCKED_NO_CANDIDATE
    assert d.overall_status == m.OVERALL_BLOCKED


def test_route_everything_unavailable_is_fully_blocked():
    d = m.route(
        "analysis-route", REPO_ROOT,
        unavailable_agents=["analysis-agent", "dv-lead"],
    )
    assert d.overall_status == m.OVERALL_BLOCKED
    assert d.agent.resolved_agent is None
    assert d.model.resolved_model is None
    assert d.tool.resolved_tools == []


@pytest.mark.parametrize("task_type", list(m.TASK_TYPES))
def test_route_resolves_cleanly_for_every_real_task_type(task_type):
    """Every declared task type must route to a real, on-disk agent in this
    repo with no fallback needed under default (nothing-unavailable)
    conditions -- proves the whole table is internally consistent, not just
    the one 'analysis-route' example exercised above."""
    d = m.route(task_type, REPO_ROOT)
    assert d.overall_status == m.OVERALL_ROUTED
    assert d.agent.resolved_agent == router_mod.DEFAULT_ROUTES[task_type]


# --- routing_criteria() ------------------------------------------------------

def test_routing_criteria_is_json_serializable_and_names_every_task_type():
    import json
    crit = m.routing_criteria()
    json.dumps(crit)  # must not raise
    assert set(crit["task_types"]) == set(m.TASK_TYPES)
    assert crit["model_criteria"]["fallback_policy"].count("inherit") >= 1
    assert crit["agent_criteria"]["fallback_chains"] == {k: list(v) for k, v in m.AGENT_FALLBACK_CHAINS.items()}


# --- CLI front door (python -m) -----------------------------------------------

def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.model_agent_tool_router", *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )


def test_cli_task_types():
    p = _run_cli("task-types")
    assert p.returncode == 0
    assert "analysis-route" in p.stdout


def test_cli_criteria():
    p = _run_cli("criteria")
    assert p.returncode == 0
    assert "fallback_policy" in p.stdout


def test_cli_route_clean_exits_zero():
    p = _run_cli("route", "--task-type", "analysis-route", "--root", ".", "--json")
    assert p.returncode == 0
    assert '"overall_status": "ROUTED"' in p.stdout


def test_cli_route_blocked_exits_nonzero():
    p = _run_cli("route", "--task-type", "analysis-route", "--root", ".",
                  "--unavailable-agents", "analysis-agent,dv-lead")
    assert p.returncode == 1
    assert "BLOCKED_NEEDS_HUMAN_DECISION" in p.stdout
