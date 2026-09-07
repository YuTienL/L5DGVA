"""dv_harness/model_agent_tool_router.py -- Model/Agent/Tool Router with a
documented Routing Criteria + Fallback Policy.

WHY THIS MODULE EXISTS (2026-09-06, "Model/Agent/Tool Router" gap-close)
--------------------------------------------------------------------------
`dv_harness/router.py`'s `RouteResolver` answers a narrower pair of
questions: "this graph node is running, which agent/skills does it get"
(`resolve()`, a STATIC `DEFAULT_ROUTES` table lookup) and "the user typed a
free-text request, is it a research request and what is the route"
(`resolve_intent()`). Neither ever asks whether the resolved agent is
actually AVAILABLE right now, neither has any notion of a MODEL, and neither
decides a TOOL SCOPE beyond copying whatever the resolved agent's own
`.claude/agents/<name>.md` frontmatter already declares. There is no
documented fallback for "the preferred agent/model/tool is unavailable" --
`RouteResolver.resolve()` simply returns whatever the static table names,
found or not.

A repo-wide search before writing this confirmed the gap is real: no module
named `fallback_policy`/`FALLBACK_POLICY`/`ModelRouter`/`ToolRouter` existed,
`.claude/agents/*.md` frontmatter carries a real `model:` field (`inherit`,
on 17 of this repo's 24 real agent profiles) that no code parsed before this
change, and nothing anywhere resolved model/tool availability with a
documented fallback chain.

REUSE OVER REINVENT -- every real fact this router needs already has a real
producer, imported rather than re-derived:
  * the TASK-TYPE -> preferred-AGENT mapping is `router.DEFAULT_ROUTES`
    itself, imported verbatim -- this module adds no second, possibly
    drifting copy of that table;
  * "does this agent have a real, parseable profile" is
    `agent_profile.load_agent_profile()`'s own `AgentProfile.found`;
  * the agent's declared MODEL and TOOL scope are that same `AgentProfile`'s
    own `model`/`tools`/`disallowed_tools` fields -- `model` is a small,
    additive parse this change adds to `agent_profile.py` (mirroring the
    existing `tools:`/`disallowedTools:` parse, nothing rewritten);
  * whether the resolved agent is actually wired into the production graph
    is `agent_dispatch.agent_dispatch_map()`'s own real dispatch-status
    vocabulary, carried through as INFORMATIONAL context on the result
    (never used to block a route -- `research-architect` is a real,
    intentionally `NOT_DISPATCHED` agent per ROSTER.md, and this router must
    not treat "not a graph node" as "unavailable").

EVIDENCE TRUTH RULE, applied to a domain with real fabrication risk. This
router never probes a live model registry (none exists in this repo to
probe) and never invents a specific model identifier: the only two model
values this policy will ever assert are (a) an agent's own REAL declared
`model:` frontmatter value, read verbatim, or (b) the literal string
"inherit" -- the SAME value 17 of this repo's own 24 real agent profiles
already use, meaning "use whatever model the invoking session/CLI already
provides" -- as the one, honest, non-fabricated fallback. It never invents a
tool name either: a substituted tool must come from a small, DOCUMENTED
`ALTERNATE_TOOL_MAP` naming a real Claude Code built-in tool this repo's own
agent frontmatter already uses elsewhere (PowerShell<->Bash), and an
unavailable tool with no documented alternate is DROPPED and reported, never
silently kept or silently replaced by a guess.

"Availability" here is never a live probe (this module makes no
subprocess/network call) -- it is either a real, on-disk fact (`.claude/
agents/<name>.md` existing and parsing) or a caller-declared fact
(`unavailable_agents`/`unavailable_models`/`unavailable_tools`, standing in
for "I already know, from some other real signal outside this module's
scope, that this candidate cannot be used right now"). A caller with no such
signal passes nothing, and every routing decision resolves to its preferred
candidate.

WORST-WINS COMPOSITE VERDICT (house style rule 3). `route()`'s
`overall_status` is never averaged across the three sub-decisions: any one
of agent/model/tool resolving to a real BLOCKED (no available candidate at
all) makes the whole decision `BLOCKED_NEEDS_HUMAN_DECISION`, regardless of
how clean the other two are.

SCOPE. This module DECIDES nothing beyond a routing recommendation: it never
dispatches, never shells out to `claude`, never writes state, and is not
wired into `engine.py`'s real `run_stage()` path -- that path's own
`RouteResolver.resolve()` / `MultiAgentOrchestrator.delegate()` /
`ClaudeCLIAdapter.run()` chain is UNCHANGED by this module. This is a
REACHED capability (a real importable/CLI caller exists), not a WIRED one,
matching the disclosed-scope convention several other same-day additions in
this repo already use. Front door: `python -m
dv_harness.model_agent_tool_router task-types|route|criteria` -- no
`dv-harness` CLI verb was added and `cli.py`/`gates.py` were not touched
(both are large files under heavy concurrent-edit pressure in this repo as
of this pass; see CLAUDE.md's own repeated same-day disclosure of that
choice for several sibling modules).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence

from .router import DEFAULT_ROUTES
from .agent_profile import AgentProfile, load_agent_profile
from .agent_dispatch import agent_dispatch_map

# --- Task-type vocabulary: reused verbatim from router.DEFAULT_ROUTES ------
# The primary routing criterion (task type -> preferred agent) is that same
# table, imported rather than re-typed, so the two can never silently drift
# apart -- adding a route to router.py automatically extends what this
# router can resolve, with no edit needed here.
TASK_TYPES: tuple = tuple(sorted(DEFAULT_ROUTES.keys()))

# --- Documented per-task-type AGENT fallback chain --------------------------
# Each task type's chain is ordered preferred-first. Every chain's LAST entry
# is 'dv-lead' -- the one real agent profile in this repo whose own
# description ("Top-level industrial DV orchestrator ... using command-driven
# SoC-aware verification") and declared tool scope (Read/Grep/Glob/PowerShell/
# Agent/Skill -- the broadest read+delegate scope any agent profile in this
# repo declares) makes it the one legitimate universal fallback: it can
# always read evidence and delegate further work, even when a task-type's own
# specialist agent is unavailable. 'lead-route' already names dv-lead as its
# preferred agent, so its own chain has no further fallback to offer.
AGENT_FALLBACK_CHAINS: Dict[str, List[str]] = {
    "analysis-route": ["analysis-agent", "dv-lead"],
    "implementation-route": ["implementation-agent", "dv-lead"],
    "build-route": ["build-agent", "dv-lead"],
    "debug-route": ["debug-agent", "dv-lead"],
    "regression-route": ["regression-agent", "dv-lead"],
    "review-route": ["review-agent", "dv-lead"],
    "lead-route": ["dv-lead"],
    "research-route": ["research-architect", "dv-lead"],
}
assert set(AGENT_FALLBACK_CHAINS) == set(TASK_TYPES), (
    "AGENT_FALLBACK_CHAINS must declare exactly router.DEFAULT_ROUTES' own "
    "task types -- add/remove a chain entry whenever a route is added/removed "
    "there, so the two tables can never silently drift apart")
assert all(chain and chain[0] == DEFAULT_ROUTES[t] for t, chain in AGENT_FALLBACK_CHAINS.items()), (
    "each chain's first (preferred) entry must equal router.DEFAULT_ROUTES' "
    "own agent for that task type -- the fallback chain must never disagree "
    "with the one already-real primary routing table")

# --- Model fallback policy ---------------------------------------------------
# The only fallback model value this router will ever assert. See the module
# docstring's Evidence Truth Rule paragraph for why no other value is used.
MODEL_FALLBACK_DEFAULT = "inherit"

# --- Tool fallback policy ----------------------------------------------------
# A small, DOCUMENTED substitution table over real Claude Code built-in tool
# names this repo's own agent frontmatter already uses (see the `tools:`
# lines surveyed across .claude/agents/*.md). Symmetric on purpose: either
# platform tool may stand in for the other when the declaring agent's own
# platform lacks it. No other substitution is ever invented.
ALTERNATE_TOOL_MAP: Dict[str, str] = {
    "PowerShell": "Bash",
    "Bash": "PowerShell",
}

# --- Status vocabularies -----------------------------------------------------
# Deliberately distinct spellings from dv_harness.models.Status (a stage-gate
# VERDICT vocabulary) -- this router never renders a PASS/FAIL/BLOCKED-style
# verification verdict, only a routing recommendation.
AGENT_RESOLVED_PREFERRED = "AGENT_RESOLVED_PREFERRED"
AGENT_RESOLVED_FALLBACK = "AGENT_RESOLVED_FALLBACK"
AGENT_BLOCKED_NO_CANDIDATE = "AGENT_BLOCKED_NO_CANDIDATE"
AGENT_UNRESOLVED_TASK_TYPE = "AGENT_UNRESOLVED_TASK_TYPE"

MODEL_RESOLVED_PREFERRED = "MODEL_RESOLVED_PREFERRED"
MODEL_RESOLVED_NO_DECLARATION = "MODEL_RESOLVED_NO_DECLARATION"
MODEL_RESOLVED_FALLBACK = "MODEL_RESOLVED_FALLBACK"
MODEL_BLOCKED_NO_CANDIDATE = "MODEL_BLOCKED_NO_CANDIDATE"
MODEL_UNRESOLVED_NO_AGENT = "MODEL_UNRESOLVED_NO_AGENT"

TOOL_RESOLVED_PREFERRED = "TOOL_RESOLVED_PREFERRED"
TOOL_RESOLVED_NO_EXPLICIT_SCOPE = "TOOL_RESOLVED_NO_EXPLICIT_SCOPE"
TOOL_RESOLVED_FALLBACK = "TOOL_RESOLVED_FALLBACK"
TOOL_BLOCKED_NO_CANDIDATE = "TOOL_BLOCKED_NO_CANDIDATE"
TOOL_UNRESOLVED_NO_AGENT = "TOOL_UNRESOLVED_NO_AGENT"

OVERALL_ROUTED = "ROUTED"
OVERALL_ROUTED_WITH_FALLBACK = "ROUTED_WITH_FALLBACK"
OVERALL_BLOCKED = "BLOCKED_NEEDS_HUMAN_DECISION"

_AGENT_BLOCKING = frozenset({AGENT_BLOCKED_NO_CANDIDATE, AGENT_UNRESOLVED_TASK_TYPE})
_MODEL_BLOCKING = frozenset({MODEL_BLOCKED_NO_CANDIDATE})
_TOOL_BLOCKING = frozenset({TOOL_BLOCKED_NO_CANDIDATE})
_AGENT_FALLBACK_STATUSES = frozenset({AGENT_RESOLVED_FALLBACK})
_MODEL_FALLBACK_STATUSES = frozenset({MODEL_RESOLVED_FALLBACK})
_TOOL_FALLBACK_STATUSES = frozenset({TOOL_RESOLVED_FALLBACK})


@dataclass
class AgentResolution:
    task_type: str
    fallback_chain: List[str]
    resolved_agent: Optional[str]
    status: str
    tried: List[dict] = field(default_factory=list)
    dispatch_status: Optional[str] = None
    profile: Optional[AgentProfile] = None

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if k != "profile"}
        if self.profile is not None:
            d["profile"] = {
                "found": self.profile.found,
                "model": self.profile.model,
                "tools": self.profile.tools,
                "disallowed_tools": self.profile.disallowed_tools,
            }
        else:
            d["profile"] = None
        return d


@dataclass
class ModelResolution:
    requested_model: Optional[str]
    resolved_model: Optional[str]
    status: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ToolResolution:
    requested_tools: List[str]
    resolved_tools: List[str]
    substitutions: List[dict] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)
    status: str = TOOL_UNRESOLVED_NO_AGENT

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RoutingDecision:
    task_type: str
    agent: AgentResolution
    model: ModelResolution
    tool: ToolResolution
    overall_status: str

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "agent": self.agent.to_dict(),
            "model": self.model.to_dict(),
            "tool": self.tool.to_dict(),
            "overall_status": self.overall_status,
        }


def resolve_agent(task_type: str, root, unavailable_agents: FrozenSet[str] = frozenset()) -> AgentResolution:
    """Resolves which agent should handle `task_type`, walking
    AGENT_FALLBACK_CHAINS[task_type] preferred-first.

    An agent is "available" here iff (a) its name is not in
    `unavailable_agents` (a caller-declared fact -- this function makes no
    live probe of its own) AND (b) `agent_profile.load_agent_profile()`
    reports a real, parseable profile file (`AgentProfile.found`). The FIRST
    available candidate wins; every earlier, unavailable candidate is
    recorded in `tried` so the fallback decision is auditable rather than
    merely asserted. Exhausting the whole chain with nothing available
    reports AGENT_BLOCKED_NO_CANDIDATE and resolves to no agent at all --
    this function never fabricates a name to keep a caller unblocked.
    """
    if task_type not in AGENT_FALLBACK_CHAINS:
        return AgentResolution(
            task_type=task_type, fallback_chain=[], resolved_agent=None,
            status=AGENT_UNRESOLVED_TASK_TYPE, tried=[],
        )
    chain = list(AGENT_FALLBACK_CHAINS[task_type])
    dispatch_map = agent_dispatch_map(Path(root)) if root is not None else {}
    tried: List[dict] = []
    for idx, name in enumerate(chain):
        declared_unavailable = name in unavailable_agents
        profile = None if declared_unavailable or root is None else load_agent_profile(root, name)
        found = bool(profile and profile.found)
        tried.append({
            "agent": name,
            "declared_unavailable": declared_unavailable,
            "profile_found": found,
        })
        if declared_unavailable or not found:
            continue
        return AgentResolution(
            task_type=task_type, fallback_chain=chain, resolved_agent=name,
            status=(AGENT_RESOLVED_PREFERRED if idx == 0 else AGENT_RESOLVED_FALLBACK),
            tried=tried,
            dispatch_status=(dispatch_map.get(name, {}) or {}).get("status"),
            profile=profile,
        )
    return AgentResolution(
        task_type=task_type, fallback_chain=chain, resolved_agent=None,
        status=AGENT_BLOCKED_NO_CANDIDATE, tried=tried,
    )


def resolve_model(profile: Optional[AgentProfile], unavailable_models: FrozenSet[str] = frozenset()) -> ModelResolution:
    """Resolves which model should be used, given the AGENT this call already
    resolved (or None, when no agent could be resolved at all).

    Fallback policy, in order:
      1. No agent resolved at all -> MODEL_UNRESOLVED_NO_AGENT (there is no
         profile to read a model preference off of).
      2. The agent declares no explicit `model:` frontmatter line at all
         (`profile.model is None`) -> MODEL_RESOLVED_NO_DECLARATION,
         resolving to MODEL_FALLBACK_DEFAULT ("inherit") -- an agent with no
         explicit preference is, by construction, already asking to inherit
         whatever model the invoking session/CLI provides.
      3. The agent's declared model is not in `unavailable_models` ->
         MODEL_RESOLVED_PREFERRED, resolving to that declared value verbatim.
      4. The agent's declared model IS in `unavailable_models` ->
         MODEL_RESOLVED_FALLBACK, resolving to MODEL_FALLBACK_DEFAULT,
         UNLESS that fallback value is itself declared unavailable, in which
         case MODEL_BLOCKED_NO_CANDIDATE with no resolved model at all.
    """
    if profile is None or not profile.found:
        return ModelResolution(requested_model=None, resolved_model=None, status=MODEL_UNRESOLVED_NO_AGENT)
    declared = profile.model
    if declared is None:
        if MODEL_FALLBACK_DEFAULT in unavailable_models:
            return ModelResolution(requested_model=None, resolved_model=None, status=MODEL_BLOCKED_NO_CANDIDATE)
        return ModelResolution(requested_model=None, resolved_model=MODEL_FALLBACK_DEFAULT, status=MODEL_RESOLVED_NO_DECLARATION)
    if declared not in unavailable_models:
        return ModelResolution(requested_model=declared, resolved_model=declared, status=MODEL_RESOLVED_PREFERRED)
    if MODEL_FALLBACK_DEFAULT not in unavailable_models and MODEL_FALLBACK_DEFAULT != declared:
        return ModelResolution(requested_model=declared, resolved_model=MODEL_FALLBACK_DEFAULT, status=MODEL_RESOLVED_FALLBACK)
    return ModelResolution(requested_model=declared, resolved_model=None, status=MODEL_BLOCKED_NO_CANDIDATE)


def resolve_tools(profile: Optional[AgentProfile], unavailable_tools: FrozenSet[str] = frozenset()) -> ToolResolution:
    """Resolves the effective tool scope for the resolved agent's own
    declared `tools:` list, applying the documented ALTERNATE_TOOL_MAP
    substitution policy.

    Every declared tool not in `unavailable_tools` passes through unchanged.
    An unavailable declared tool is replaced by its ALTERNATE_TOOL_MAP entry
    when one exists AND that alternate is itself available; otherwise it is
    DROPPED and reported in `dropped` -- this function never silently keeps
    an unavailable tool and never invents a substitute outside the
    documented map, so the resolved scope is never wider than what the
    agent's own frontmatter plus a documented alternate already authorizes.
    """
    if profile is None or not profile.found:
        return ToolResolution(requested_tools=[], resolved_tools=[], status=TOOL_UNRESOLVED_NO_AGENT)
    declared = list(profile.tools or [])
    if not declared:
        return ToolResolution(requested_tools=[], resolved_tools=[], status=TOOL_RESOLVED_NO_EXPLICIT_SCOPE)
    resolved: List[str] = []
    substitutions: List[dict] = []
    dropped: List[str] = []
    for t in declared:
        if t not in unavailable_tools:
            if t not in resolved:
                resolved.append(t)
            continue
        alt = ALTERNATE_TOOL_MAP.get(t)
        if alt and alt not in unavailable_tools:
            if alt not in resolved:
                resolved.append(alt)
            substitutions.append({"declared": t, "substituted": alt})
        else:
            dropped.append(t)
    if not resolved:
        status = TOOL_BLOCKED_NO_CANDIDATE
    elif substitutions or dropped:
        status = TOOL_RESOLVED_FALLBACK
    else:
        status = TOOL_RESOLVED_PREFERRED
    return ToolResolution(
        requested_tools=declared, resolved_tools=resolved,
        substitutions=substitutions, dropped=dropped, status=status,
    )


def route(
    task_type: str,
    root,
    unavailable_agents: Sequence[str] = (),
    unavailable_models: Sequence[str] = (),
    unavailable_tools: Sequence[str] = (),
) -> RoutingDecision:
    """The one entry point: resolves agent, then model and tool scope off
    that resolved agent's own real profile, then folds a WORST-WINS overall
    verdict (house style rule 3) -- a single BLOCKED sub-decision makes the
    whole route BLOCKED_NEEDS_HUMAN_DECISION regardless of how clean the
    other two sub-decisions are; a real fallback anywhere (and only when
    nothing is BLOCKED) makes it ROUTED_WITH_FALLBACK; otherwise ROUTED.
    """
    agent_res = resolve_agent(task_type, root, unavailable_agents=frozenset(unavailable_agents))
    model_res = resolve_model(agent_res.profile, unavailable_models=frozenset(unavailable_models))
    tool_res = resolve_tools(agent_res.profile, unavailable_tools=frozenset(unavailable_tools))

    blocked = (
        agent_res.status in _AGENT_BLOCKING
        or model_res.status in _MODEL_BLOCKING
        or tool_res.status in _TOOL_BLOCKING
    )
    fell_back = (
        agent_res.status in _AGENT_FALLBACK_STATUSES
        or model_res.status in _MODEL_FALLBACK_STATUSES
        or tool_res.status in _TOOL_FALLBACK_STATUSES
        or bool(tool_res.substitutions)
        or bool(tool_res.dropped)
    )
    overall = OVERALL_BLOCKED if blocked else (OVERALL_ROUTED_WITH_FALLBACK if fell_back else OVERALL_ROUTED)
    return RoutingDecision(task_type=task_type, agent=agent_res, model=model_res, tool=tool_res, overall_status=overall)


def routing_criteria() -> dict:
    """A machine-readable statement of the routing criteria + fallback
    policy this module implements -- the "documented fallback policy" the
    task requires, kept as data rather than only as this file's own prose so
    a caller (or a test) can print/compare it without parsing comments."""
    return {
        "task_types": list(TASK_TYPES),
        "agent_criteria": {
            "primary": "router.DEFAULT_ROUTES[task_type] -- the static task-type -> agent table reused verbatim from dv_harness/router.py",
            "availability": "a real, parseable .claude/agents/<name>.md profile file (agent_profile.load_agent_profile().found), and not named in the caller-supplied unavailable_agents set",
            "fallback_policy": "walk AGENT_FALLBACK_CHAINS[task_type] preferred-first; the first available candidate wins; every chain ends at 'dv-lead'; exhausting the chain reports AGENT_BLOCKED_NO_CANDIDATE rather than fabricating an agent name",
            "fallback_chains": {k: list(v) for k, v in AGENT_FALLBACK_CHAINS.items()},
        },
        "model_criteria": {
            "primary": "the resolved agent's own real `model:` frontmatter value (AgentProfile.model), read verbatim -- never a value this router invents",
            "fallback_policy": f"an unavailable declared model, or an agent declaring no explicit model at all, falls back to the literal value {MODEL_FALLBACK_DEFAULT!r} (use whatever model the invoking session/CLI already provides) -- the only fallback value this policy asserts; if that value is itself unavailable, MODEL_BLOCKED_NO_CANDIDATE",
        },
        "tool_criteria": {
            "primary": "the resolved agent's own real declared `tools:` list (AgentProfile.tools), read verbatim",
            "fallback_policy": "an unavailable declared tool is substituted per ALTERNATE_TOOL_MAP when a documented alternate exists and is itself available; otherwise dropped and reported -- never silently kept, never silently widened beyond what is declared or documented",
            "alternate_tool_map": dict(ALTERNATE_TOOL_MAP),
        },
        "overall_verdict": "worst-wins: any one of agent/model/tool resolving BLOCKED makes the whole route BLOCKED_NEEDS_HUMAN_DECISION regardless of the other two; otherwise any real fallback anywhere makes it ROUTED_WITH_FALLBACK; otherwise ROUTED",
    }


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    """Shared CLI/`python -m` implementation. Verbs: task-types | criteria |
    route --task-type <t> --root <dir> [--unavailable-agents a,b]
    [--unavailable-models m,n] [--unavailable-tools t,u] [--json]."""
    import argparse

    parser = argparse.ArgumentParser(prog="model_agent_tool_router")
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("task-types")
    sub.add_parser("criteria")
    p_route = sub.add_parser("route")
    p_route.add_argument("--task-type", required=True)
    p_route.add_argument("--root", default=".")
    p_route.add_argument("--unavailable-agents", default="")
    p_route.add_argument("--unavailable-models", default="")
    p_route.add_argument("--unavailable-tools", default="")
    p_route.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.verb == "task-types":
        print(json.dumps(list(TASK_TYPES), indent=2))
        return 0
    if args.verb == "criteria":
        print(json.dumps(routing_criteria(), indent=2))
        return 0

    def _split(s: str) -> List[str]:
        return [x.strip() for x in s.split(",") if x.strip()]

    decision = route(
        args.task_type, args.root,
        unavailable_agents=_split(args.unavailable_agents),
        unavailable_models=_split(args.unavailable_models),
        unavailable_tools=_split(args.unavailable_tools),
    )
    if args.json:
        print(json.dumps(decision.to_dict(), indent=2))
    else:
        print(f"task_type={decision.task_type} overall_status={decision.overall_status}")
        print(f"  agent: {decision.agent.resolved_agent} ({decision.agent.status})")
        print(f"  model: {decision.model.resolved_model} ({decision.model.status})")
        print(f"  tools: {decision.tool.resolved_tools} ({decision.tool.status})")
    return 0 if decision.overall_status != OVERALL_BLOCKED else 1


if __name__ == "__main__":
    sys.exit(execute_verb())
