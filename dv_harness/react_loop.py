# dv_harness/react_loop.py -- genuine content-driven Reason-Act-Observe-
# Reflect-RePlan inner loop (2026-08-29, evidence-grounded-react design pass).
#
# Lives INSIDE engine.DVHarness.run_stage(), between "adapter call produced
# result.text" and "assign ss['status']" -- it does NOT replace engine.loop().
# loop() keeps calling run_stage() once per outer attempt and keeps reading
# ss["status"] exactly as before; every other loop()/run_stage() mechanism
# (TAKEOVER/PAUSE, can_signoff(), _advance_with_fanout, max_stage_retries,
# replan_stage() call sites for outer-exhaustion) is untouched.
#
# Opt-in per stage via graph.Node.react (already declared on every Node,
# default True, never read anywhere before this) AND
# cfg["policy"]["enable_inner_react_loop"] (default True, a global escape
# hatch). A stage with react:false, or a stage with no graph node at all,
# never enters this module -- run_stage() keeps its pre-existing
# PARTIAL+replan_stage() path for those, byte-identical.
#
# DEVIATION FROM THE DESIGN SPEC'S ILLUSTRATIVE SNIPPETS, flagged explicitly
# (per the Methodology Consolidation Rule's "worked example" requirement --
# and CLAUDE.md's "current evidence wins" when a spec's own illustrative code
# does not fit the real callable surface): the spec's build_menu()/
# InnerReactLoop.__init__() signatures, and its engine.py integration-diff
# snippet, never thread a `graph` reference through anywhere -- yet the same
# spec's own REROUTE contract ("never accepted unless it is a real key in
# self.graph.nodes", "graph.outgoing(stage) edges") is only checkable against
# DVHarness.self.graph (dv_harness.graph.GraphDefinition). Both build_menu()
# and InnerReactLoop take an ADDITIVE `graph=None` parameter here (engine.py
# passes self.graph at the real call site) so REROUTE validation is against
# real graph data, not guessed. graph=None degrades safely: REROUTE options
# are simply never offered (same "hallucinated target dropped" discipline
# the spec itself specifies for an unknown node.id).
#
# SECOND DEVIATION, same reasoning (2026-09-01, per-agent-attribution audit
# fix): InnerReactLoop.__init__ additionally takes additive `profiler=None,
# profile_id=None, agent_name=""` parameters, absent from the design spec's
# illustrative signature. Before this fix, every real self.adapter.run() call
# this module makes -- the reflect_and_decide() reflection call (and its
# hallucination re-ask) plus each RETRY_TARGETED/REQUEST_EVIDENCE targeted
# retry -- was completely invisible to StageExecutionProfiler: real runtime
# and real token usage for these calls existed but was never recorded,
# silently under-reporting a stage's total_tokens/aggregate runtime whenever
# the inner loop actually iterated. profiler/profile_id are the SAME
# StageExecutionProfiler instance and profile_id engine.py's run_stage()
# already created via self.profiler.begin_stage() -- not a second profiler.
# All three parameters degrade safely to a no-op (see _record_agent_run()
# below) when omitted, so every pre-existing unit test in
# dv_harness_tests/test_react_loop.py that constructs InnerReactLoop directly
# (never passing these) is unaffected.
#
# THIRD DEVIATION (2026-09-04, plan-and-execute/ReAct gap closure): an
# additive `protocol=None` on build_menu() and InnerReactLoop.__init__.
# Motivation is a confirmed real-data gap, not a hypothetical: every
# reflect_*.json this harness had actually persisted showed a 1-option
# CONVERGE_TERMINATE-only menu, because build_menu()'s four original option
# sources all require the failing gate's OWN detail to already enumerate what
# is missing, and the failure shape that actually occurs in practice --
# gates._evaluate_stage_evidence_core()'s synthetic
# {"reason": "NO_EVIDENCE_BLOCK_SUPPLIED"} for a gate the agent supplied no
# evidence block for -- carries no such enumeration and never ran a gate
# script that could have named a protocol. build_menu()'s new source #5
# handles exactly that shape; `protocol` is what lets it still cite a real
# protocol_builder_registry.json item there. Degrades safely to "_general".
#
# FOURTH ADDITION (adversarial_refutation_pass task, 2026-09-07, purely
# additive -- nothing above this point is changed): attempt_hypothesis_
# refutation() below is the real "try to refute this exact hypothesis"
# self-critique mechanism qualified_conclusion.build_qualified_conclusion()'s
# new, optional require_refutation_pass parameter can require before
# is_qualified may be True (see that module's own docstring "ADVERSARIAL
# REFUTATION PASS" section). It mirrors this session's own ad hoc
# Workflow-script "adversarial verify" pattern -- actively try to disprove a
# claim, rather than only checking it looks internally consistent -- as a
# real, callable CORE-engine mechanism instead of a one-off script
# convention no other caller could reuse. It is a standalone function, not
# wired into InnerReactLoop.run()'s own menu/decision cycle: the hypothesis
# under review only exists once RE_AUDIT's root_cause_evidence_gate has
# already produced one (see engine.py's _score_root_cause_confidence), which
# is a different point in the stage lifecycle from the inner loop's own
# pre-PASS gate-failure reflection cycle above. A future pass wiring this
# into engine.py (behind a new, additive policy flag, exactly like
# enable_inner_react_loop above) is a disclosed, deliberate follow-up, not
# done here -- every existing caller of this module is unaffected either
# way, since this is a brand-new function nothing yet calls.
#
# FIFTH ADDITION (adaptive_react_budget gap-close, 2026-09-07, purely
# additive over everything above): compute_adaptive_react_budget() below is
# a new, OPT-IN policy mode where the two existing safety-backstop numbers
# backstop numbers InnerReactLoop.run() reads -- policy.
# inner_react_max_iterations and policy.inner_react_max_adapter_calls -- may
# scale with a real, mechanically-computed complexity signal (the number of
# distinct files, and the distinct top-level subsystem directories those
# files sit under, that `git diff --name-only HEAD` shows as touched by the
# current worktree) instead of always being the two fixed constants above.
# It is declared under a new config.py policy sub-block,
# policy.adaptive_react_budget, defaulting to {"enabled": False, ...} -- see
# config.py's own DEFAULT_CONFIG comment for the full field list. A project
# that never sets adaptive_react_budget.enabled=true gets EXACTLY today's
# fixed-constant behavior (compute_adaptive_react_budget() falls straight
# back to policy.get("inner_react_max_iterations", 3) /
# policy.get("inner_react_max_adapter_calls", 2), the identical two .get()
# calls InnerReactLoop.run() used before this addition), which is why
# InnerReactLoop.run() below now calls it unconditionally rather than
# reading the two policy keys directly -- the call is a safe, byte-identical
# substitution for the default (disabled) case, verified by
# dv_harness_tests/test_react_loop.py's own adaptive-budget test class,
# which re-runs every pre-existing fixed-budget test's own cfg dict through
# this new function and asserts identical (max_iterations, max_adapter_calls)
# output.
#
# Per this task's own rule 3 (no weight/threshold change may be applied
# directly to production scoring without going through a human-approved,
# controlled-experiment-shaped mechanism): this is NOT a silently-applied
# scoring-weight tune. It is an explicit, human-set project config flag --
# the identical opt-in shape every other production-behavior toggle in
# config.py's DEFAULT_CONFIG already uses (self_tuning.enabled,
# escalation.enabled, dry_run.enabled, ...). No code path in this harness
# ever flips adaptive_react_budget.enabled on its own; a human decides that
# by editing .dv-harness/config.json (or dv-harness's config CLI), exactly
# like every other policy flag here.
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .gates import GATE_FAILURE_REROUTE, _evaluate_stage_evidence_core, extract_evidence_blocks
from .inference import identify_gap, next_best_action
from .stage_profile import extract_provider_usage


# --- structured facts -------------------------------------------------------

@dataclass
class GateSignature:
    """One structured, machine-comparable fact about one gate's current
    result -- the unit the loop reflects over and diffs iteration-to-
    iteration. Built from gates.py's own gr.ok/gr.detail, unflattened (never
    the stringified `reasons` list)."""
    gate_id: str
    ok: bool
    detail: dict


@dataclass
class MenuOption:
    """One row of the constrained menu handed to the reflection LLM call.
    Every field is derived from real registry/graph/gate data -- never
    authored by the LLM."""
    option_id: str
    kind: str
    target: Optional[str]
    rationale: str
    source: str


@dataclass
class ReactDecision:
    chosen_option_id: str
    conclusion: str
    params: dict = field(default_factory=dict)
    converged: bool = False


@dataclass
class InnerReactOutcome:
    result: Any                 # AgentResult -- the FINAL adapter result for this outer attempt
    verdict: str
    reasons: List[str]
    evidence_blocks: Dict[str, Any]
    reroute_target: Optional[str] = None   # set only when the chosen action was REROUTE
    iterations: int = 0
    # Additive (adaptive_react_budget gap-close): the real budget dict
    # compute_adaptive_react_budget() computed for this attempt -- always
    # present, "mode" is "fixed" for every project that has not opted in.
    # Never read by any pre-existing caller; purely observability.
    budget_info: Optional[Dict[str, Any]] = None


# Action kinds a MenuOption may carry. ADJUST_PARAM is part of the taxonomy
# (see the design writeup's Action table) but build_menu() below never
# synthesizes one today -- no real-data source for it is specified (unlike
# the four sources build_menu() does implement) -- so it is listed here only
# so reflect_and_decide()'s validation and InnerReactLoop's dispatch both
# recognize it as a legitimate kind if a future build_menu() source adds it,
# rather than silently mis-handling it as "unknown".
ACTION_KINDS = {"RETRY_TARGETED", "REQUEST_EVIDENCE", "REROUTE", "ADJUST_PARAM",
                "CONVERGE_TERMINATE", "CONVERGE_NO_NEW_INFORMATION"}


def evaluate_stage_evidence_with_detail(root: Path, stage: str, agent_text: str):
    """Same verdict/reasons contract as gates.evaluate_stage_evidence(), plus
    the structured GateSignature list -- factored through gates.py's own
    _evaluate_stage_evidence_core() so both call sites see byte-identical
    gate results (same run_gate() invocations, not a second parallel copy).

    _evaluate_stage_evidence_core() also returns a 4th element (a stage-
    scoped completion dict -- see gates._stage_completion_from_signatures())
    that this function deliberately does not add to its own return value:
    this function's (verdict, reasons, signatures) 3-tuple is unpacked
    positionally by real existing callers/tests (engine.py, this module's
    own retry loop, dv_harness_tests/test_react_loop.py), so changing its
    arity here would break them. gates.evaluate_stage_evidence_with_completion()
    is the real call site for the completion dict instead."""
    verdict, reasons, raw_signatures, _completion = _evaluate_stage_evidence_core(root, stage, agent_text)
    signatures = [GateSignature(gate_id=g, ok=ok, detail=detail) for g, ok, detail in raw_signatures]
    return verdict, reasons, signatures


def _signatures_equal(a: List[GateSignature], b: Optional[List[GateSignature]]) -> bool:
    if b is None:
        return False
    if len(a) != len(b):
        return False
    for sa, sb in zip(a, b):
        if sa.gate_id != sb.gate_id or sa.ok != sb.ok:
            return False
        if json.dumps(sa.detail, sort_keys=True) != json.dumps(sb.detail, sort_keys=True):
            return False
    return True


def build_menu(root: Path, stage: str, node, signatures: List[GateSignature],
               prior_signatures: Optional[List[GateSignature]] = None,
               graph=None, protocol: Optional[str] = None) -> List[MenuOption]:
    """Constructs the constrained option menu -- the ONLY vocabulary the
    reflection call is allowed to choose from. See the module docstring for
    why `graph` is an additive parameter beyond the design spec's illustrative
    signature. Never returns a free-form option; the two CONVERGE_* controls
    are always the fallback.

    `protocol` (additive, 2026-09-04): the real resolved protocol name
    engine.py's RouteResolver already produced for this stage attempt
    (route_info["protocol_decision"]["protocol"]), threaded through so
    next_best_action() can cross-reference the real
    protocol_builder_registry.json for a gate whose own detail does NOT
    already name a protocol -- which is every NO_EVIDENCE_BLOCK_SUPPLIED
    signature, since no gate script ever ran to produce one. None degrades to
    "_general", which next_best_action() answers with its generic
    inspect-current-evidence suggestion rather than an invented registry item.
    """
    options: List[MenuOption] = []
    seen_ids = set()

    def _add(option_id, kind, target, rationale, source):
        if option_id in seen_ids:
            return
        seen_ids.add(option_id)
        options.append(MenuOption(option_id=option_id, kind=kind, target=target,
                                   rationale=rationale, source=source))

    graph_nodes = graph.nodes if graph is not None else {}
    outgoing = graph.outgoing(stage) if graph is not None else []
    no_new_information = _signatures_equal(signatures, prior_signatures)

    # Which of this stage's REAL configured gates got no evidence block at
    # all this attempt -- computed once, through the real
    # inference.identify_gap() set difference rather than a hand-rolled
    # comprehension, over the exact gate-id vocabulary
    # gates._evaluate_stage_evidence_core() already emits one signature per
    # (it appends a synthetic NO_EVIDENCE_BLOCK_SUPPLIED signature for a gate
    # the agent never supplied a block for, so `signatures` really is the
    # full configured-gate list, never only the gates that ran).
    all_gate_ids = [s.gate_id for s in signatures]
    supplied_gate_ids = [s.gate_id for s in signatures
                         if s.detail.get("reason") != "NO_EVIDENCE_BLOCK_SUPPLIED"]
    missing_evidence_blocks = identify_gap(all_gate_ids, supplied_gate_ids)

    for sig in signatures:
        if sig.ok:
            continue

        # 1. GATE_FAILURE_REROUTE (gates.py) -- the small, human-curated table.
        reroute_target = GATE_FAILURE_REROUTE.get(sig.gate_id)
        if reroute_target and reroute_target in graph_nodes:
            _add(f"REROUTE:{reroute_target}", "REROUTE", reroute_target,
                 f"{sig.gate_id} failed ({sig.detail.get('reason', sig.detail)}); "
                 f"GATE_FAILURE_REROUTE names {reroute_target} as the upstream stage "
                 f"whose stale fact most likely caused this failure.",
                 "gate_failure_route")

        # 2. Real graph edges whose condition names this exact gate_id.
        for e in outgoing:
            if e.condition == sig.gate_id and e.target in graph_nodes:
                _add(f"REROUTE:{e.target}", "REROUTE", e.target,
                     f"graph edge {stage}->{e.target} is conditioned on gate {sig.gate_id}.",
                     "graph_edge")

        # A retry-worthy action only makes sense if the PRIOR retry (if any)
        # actually changed something -- offering the identical retry again
        # after it demonstrably produced no new information would not be a
        # genuinely different action. Suppressed when no_new_information;
        # REROUTE above is deliberately NOT suppressed (a reroute is a
        # different kind of action from a retry, never yet tried).
        if not no_new_information:
            missing = sig.detail.get("missing")
            if isinstance(missing, list) and missing:
                _add(f"RETRY_TARGETED:{sig.gate_id}:{missing[0]}", "RETRY_TARGETED", sig.gate_id,
                     f"{sig.gate_id} reports missing field(s) {missing} -- retry naming "
                     f"exactly that field, not a bare repeat of the original prompt.",
                     "gate_detail_field")

            unresolved = sig.detail.get("dv_review_unresolved_fields")
            if isinstance(unresolved, list) and unresolved:
                _add(f"RETRY_TARGETED:{sig.gate_id}:{unresolved[0]}", "RETRY_TARGETED", sig.gate_id,
                     f"{sig.gate_id} has unresolved DV-review field(s) {unresolved}.",
                     "gate_detail_field")

            missing_subpayload = sig.detail.get("missing_subpayload") or sig.detail.get("missing")
            if isinstance(missing_subpayload, str) and missing_subpayload:
                _add(f"RETRY_TARGETED:{sig.gate_id}:{missing_subpayload}", "RETRY_TARGETED", sig.gate_id,
                     f"{sig.gate_id} is missing sub-payload '{missing_subpayload}'.",
                     "gate_detail_field")

            # 4. protocol_builder_registry.json cross-reference, generalized
            # from engine.py's post-PASS RE_AUDIT-only call site to run
            # pre-PASS for ANY gate whose detail names a "protocol" AND a
            # concrete "missing" list -- the gap is then trivially that
            # missing list (identify_gap(missing, []) == missing), and
            # next_best_action() cites the real registry item per gap
            # instead of inventing one.
            gate_protocol = sig.detail.get("protocol")
            gap_source = missing if isinstance(missing, list) else []
            if gate_protocol and gap_source:
                gap = identify_gap(gap_source, [])
                for action in next_best_action(gate_protocol, gap, root):
                    if action.get("source") == "protocol_builder_registry":
                        _add(f"REQUEST_EVIDENCE:{sig.gate_id}:{action['gap']}", "REQUEST_EVIDENCE",
                             sig.gate_id,
                             f"{action['suggested_action']} (gap: {action['gap']}).",
                             "protocol_builder_registry")

            # 5. NO_EVIDENCE_BLOCK_SUPPLIED (2026-09-04 gap closure). Sources
            # 1-4 above all require the FAILING GATE'S OWN detail to already
            # enumerate what is missing -- a `missing`/`dv_review_unresolved_
            # fields`/`missing_subpayload` list, or a protocol+missing pair.
            # A gate the agent supplied no evidence block for never ran, so
            # its synthetic detail is only {"status": "FAIL", "reason":
            # "NO_EVIDENCE_BLOCK_SUPPLIED"} and none of those four fire --
            # which is why every real reflect_*.json recorded to date was
            # offered a 1-option CONVERGE_TERMINATE-only menu and trivially
            # "chose" it. The missing thing here is nonetheless completely
            # unambiguous and comes from real data, not a guess: it is this
            # exact gate's own ```dv-harness-evidence:<gate_id>``` block,
            # named by STAGE_GATES[stage] (via the signature list gates.py
            # built from it) and confirmed absent by identify_gap() above.
            # next_best_action() adds the real protocol_builder_registry.json
            # item when the resolved protocol has one, and is simply omitted
            # from the rationale when it does not -- the option is offered
            # either way, because "supply the block this gate requires" is a
            # genuinely actionable next step regardless of registry coverage.
            if sig.gate_id in missing_evidence_blocks:
                registry_hint = next(
                    (a["suggested_action"]
                     for a in next_best_action(protocol or "_general", [sig.gate_id], root)
                     if a.get("source") == "protocol_builder_registry"),
                    "",
                )
                _add(f"REQUEST_EVIDENCE:{sig.gate_id}:evidence_block", "REQUEST_EVIDENCE",
                     sig.gate_id,
                     f"{sig.gate_id} is a configured gate for stage {stage} but this attempt "
                     f"supplied no ```dv-harness-evidence:{sig.gate_id}``` block at all "
                     f"(identify_gap over this stage's real configured gate list reports "
                     f"{missing_evidence_blocks} still missing) -- request exactly that block, "
                     f"naming this gate_id verbatim in the fence."
                     + (f" {registry_hint}." if registry_hint else ""),
                     "stage_gate_missing_evidence_block")

    _add("CONVERGE_TERMINATE", "CONVERGE_TERMINATE", None,
         "Accept the current verdict as final; no further constrained action "
         "is available or warranted given the real evidence gathered so far.",
         "control")
    if no_new_information:
        _add("CONVERGE_NO_NEW_INFORMATION", "CONVERGE_NO_NEW_INFORMATION", None,
             "Gate signatures are identical to the previous inner iteration, "
             "gate-id-for-gate-id and detail-for-detail -- no new information "
             "was produced by the last action.",
             "control")

    return options


def _record_agent_run(profiler, profile_id, agent_name, t0, result, status_override=None):
    """Best-effort StageExecutionProfiler.add_agent_run() call for ONE real
    adapter.run() invocation this module made (a reflection call, its
    hallucination re-ask, or a RETRY_TARGETED/REQUEST_EVIDENCE targeted
    retry) -- see the module docstring's "SECOND DEVIATION" note for why this
    exists. profiler/profile_id are additive: every existing unit test in
    dv_harness_tests/test_react_loop.py constructs InnerReactLoop /
    reflect_and_decide without them, so `None, None` (the default) must stay
    a genuine no-op, exactly like this module's pre-existing graph=None
    degrade-safely precedent. Wrapped in try/except for the same reason
    react_recorder.record_reflection() above already is: observability must
    never break an already-computed decision/result."""
    if profiler is None or profile_id is None:
        return
    runtime_sec = time.perf_counter() - t0
    raw = (getattr(result, "raw", None) or {}) if result is not None else {}
    usage = extract_provider_usage(raw)
    model = (raw.get("response") or {}).get("model", "")
    status = status_override or ("PASS" if result is not None and getattr(result, "ok", False) else "FAIL")
    try:
        profiler.add_agent_run(profile_id, agent_name, runtime_sec, usage=usage,
                                model=str(model), status=status)
    except Exception:
        pass


# --- reflection call ---------------------------------------------------------

_DECISION_RE = re.compile(r"```dv-harness-react-decision\s*\n(?P<body>.*?)```", re.DOTALL)


def _parse_decision_text(text: str) -> Optional[dict]:
    m = _DECISION_RE.search(text or "")
    if not m:
        return None
    try:
        d = json.loads(m.group("body"))
    except Exception:
        return None
    if not isinstance(d, dict) or "chosen_option_id" not in d:
        return None
    return d


def _build_reflection_prompt(stage: str, prompt_context: dict, menu: List[MenuOption]) -> str:
    menu_lines = "\n".join(
        f"- option_id={m.option_id} | kind={m.kind} | target={m.target} | rationale={m.rationale}"
        for m in menu
    )
    return (
        f"[Inner ReAct Reflection -- stage {stage}, inner iteration "
        f"{prompt_context.get('inner_iteration')}]\n"
        f"Current verdict: {prompt_context.get('verdict')}\n"
        f"Reasons:\n" + "\n".join(f"  - {r}" for r in prompt_context.get("reasons") or []) + "\n"
        f"Gate signatures (structured, real gate output):\n"
        f"{json.dumps(prompt_context.get('signatures') or [], ensure_ascii=False, indent=2)}\n\n"
        f"You must choose EXACTLY ONE option from this menu -- do not invent an option_id "
        f"not listed below:\n{menu_lines}\n\n"
        f"Reply with one fenced ```dv-harness-react-decision``` JSON block containing "
        f'{{"chosen_option_id": "<one of the option_id values above, verbatim>", '
        f'"conclusion": "<short factual statement citing the real reasons/signatures above, '
        f'not free-form chain-of-thought>", "params": {{}}}}.'
    )


def reflect_and_decide(adapter, root: Path, stage: str, prompt_context: dict,
                        menu: List[MenuOption], profiler=None, profile_id=None,
                        agent_name: str = "") -> ReactDecision:
    """The genuine reasoning step: one additional adapter.run() call (two if
    the first reply names an option_id outside the real menu -- re-asked
    once, then forced to CONVERGE_TERMINATE, never actioned). This is what
    keeps the LLM from inventing an action outside real registry/gate data.

    profiler/profile_id/agent_name (additive, default None/None/"" -- see
    react_loop.py's module docstring "SECOND DEVIATION" note): when supplied,
    EVERY real adapter.run() call _ask() below makes is recorded via
    _record_agent_run(), so this reflection step's real runtime/token usage
    is no longer invisible to the stage's profile."""
    valid_ids = {m.option_id for m in menu}
    prompt = _build_reflection_prompt(stage, prompt_context, menu)

    def _ask(p):
        _t0 = time.perf_counter()
        result = adapter.run(prompt=p, cwd=str(root))
        _record_agent_run(profiler, profile_id, agent_name, _t0, result)
        if result is None or not getattr(result, "ok", False):
            return None
        return _parse_decision_text(getattr(result, "text", "") or "")

    decision = _ask(prompt)
    if decision is None or decision.get("chosen_option_id") not in valid_ids:
        retry_prompt = (
            prompt + "\n\nYour previous reply did not name a valid option_id from the menu "
                     "above (or was not parseable). Reply again with exactly one of the "
                     "listed option_id values, verbatim, in the same fenced JSON block format."
        )
        decision = _ask(retry_prompt)
        if decision is None or decision.get("chosen_option_id") not in valid_ids:
            return ReactDecision(
                chosen_option_id="CONVERGE_TERMINATE",
                conclusion=(
                    "No valid menu option_id was returned after one re-ask; forcing "
                    "convergence rather than actioning an unlisted/unparseable choice."
                ),
                params={}, converged=True,
            )

    chosen = decision["chosen_option_id"]
    return ReactDecision(
        chosen_option_id=chosen,
        conclusion=str(decision.get("conclusion", "")),
        params=decision.get("params") or {},
        converged=chosen.startswith("CONVERGE"),
    )


# --- adversarial refutation self-critique (structurally-forced) ------------

_REFUTATION_RE = re.compile(r"```dv-harness-refutation\s*\n(?P<body>.*?)```", re.DOTALL)


def _parse_refutation_text(text: str) -> Optional[dict]:
    m = _REFUTATION_RE.search(text or "")
    if not m:
        return None
    try:
        d = json.loads(m.group("body"))
    except Exception:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("refuted"), bool):
        return None
    return d


def _build_refutation_prompt(hypothesis: str, evidence_refs: List[str]) -> str:
    refs = "\n".join(f"  - {r}" for r in evidence_refs) if evidence_refs else "  (none cited)"
    return (
        "[Adversarial Refutation Self-Critique]\n"
        f"Hypothesis under review: {hypothesis}\n"
        f"Evidence currently cited in support of it:\n{refs}\n\n"
        "Your task here is NOT to defend this hypothesis. Actively try to "
        "REFUTE it: look for a real, cited alternative explanation, an "
        "internal contradiction in the cited evidence, or a gap the cited "
        "evidence does not actually close. Do not invent evidence that was "
        "not already gathered -- if you find genuine counter-evidence, cite "
        "only real, already-available sources (a sim.log line, an RTL "
        "file:line, a register/spec citation).\n\n"
        "Reply with exactly one fenced ```dv-harness-refutation``` JSON "
        'block containing {"refuted": <true if you found a real, cited '
        'refutation that undermines the hypothesis, false if it withstands '
        'this scrutiny>, "counter_evidence": ["<citation>", ...], '
        '"rationale": "<short factual statement citing what you found, not '
        'free-form chain-of-thought>"}.'
    )


def attempt_hypothesis_refutation(adapter, root: Path, hypothesis: str,
                                   evidence_refs: Optional[List[str]] = None,
                                   profiler=None, profile_id=None,
                                   agent_name: str = "") -> dict:
    """The real adversarial self-critique step
    qualified_conclusion.build_qualified_conclusion()'s optional
    require_refutation_pass parameter can require before is_qualified may be
    True. See this module's own header docstring "FOURTH ADDITION" note and
    qualified_conclusion.py's "ADVERSARIAL REFUTATION PASS" note for the full
    rationale; this function is the mechanism, that module's function is
    where its result is composed into a verdict.

    Issues one real adapter.run() call instructing the agent to actively try
    to refute `hypothesis` using only the already-cited `evidence_refs` (or
    real, already-available sources) -- never inventing new evidence.
    Re-asks once on an unparseable/invalid reply, the same one-reask-then-
    give-up discipline reflect_and_decide() already uses above; a second
    failure returns an honest attempted=False rather than guessing either
    refuted value in either direction.

    Returns a plain dict -- never a dataclass instance -- so it composes
    directly with build_qualified_conclusion()'s refutation_result parameter
    with no extra conversion step: {"attempted": bool, "refuted": bool,
    "counter_evidence": [str, ...], "rationale": str}. attempted is True only
    when a real, parseable verdict was actually obtained; False means the
    step was skipped by transport failure or two unparseable replies, an
    honest "we tried and could not get a real answer" that
    build_qualified_conclusion()'s require_refutation_pass option treats
    identically to "no pass was run at all" -- never as evidence the
    hypothesis withstood scrutiny.

    profiler/profile_id/agent_name: same additive, degrade-to-a-genuine-no-op
    contract as reflect_and_decide()'s own identical parameters -- see this
    module's header docstring "SECOND DEVIATION" note. Omitting them makes
    this call invisible to StageExecutionProfiler, exactly like every other
    adapter.run() call in this module before that wiring exists for a given
    call site."""
    evidence_refs = list(evidence_refs) if evidence_refs else []
    prompt = _build_refutation_prompt(hypothesis, evidence_refs)

    def _ask(p):
        _t0 = time.perf_counter()
        result = adapter.run(prompt=p, cwd=str(root))
        _record_agent_run(profiler, profile_id, agent_name, _t0, result)
        if result is None or not getattr(result, "ok", False):
            return None
        return _parse_refutation_text(getattr(result, "text", "") or "")

    parsed = _ask(prompt)
    if parsed is None:
        retry_prompt = (
            prompt + "\n\nYour previous reply did not contain a valid "
                     "```dv-harness-refutation``` JSON block with a boolean "
                     '"refuted" field. Reply again in exactly that format.'
        )
        parsed = _ask(retry_prompt)
        if parsed is None:
            return {
                "attempted": False, "refuted": False, "counter_evidence": [],
                "rationale": "No valid refutation verdict was returned after one re-ask.",
            }

    counter_evidence = parsed.get("counter_evidence")
    if not isinstance(counter_evidence, list):
        counter_evidence = []
    return {
        "attempted": True,
        "refuted": bool(parsed["refuted"]),
        "counter_evidence": [str(c) for c in counter_evidence],
        "rationale": str(parsed.get("rationale", "")),
    }


def _build_action_prompt(base_prompt: str, chosen: MenuOption, decision: ReactDecision) -> str:
    """RETRY_TARGETED / REQUEST_EVIDENCE re-invocation prompt: names the exact
    failing gate_id and the exact missing field/registry item -- never a bare
    repeat of the original stage prompt."""
    return (
        base_prompt
        + f"\n\n[Inner ReAct targeted re-attempt]\n"
        + f"Your previous response failed gate `{chosen.target}`.\n"
        + f"Specific issue to address: {chosen.rationale}\n"
        + (f"Reviewer note: {decision.conclusion}\n" if decision.conclusion else "")
        + "Supply a corrected ```dv-harness-evidence:<gate_id>``` block for exactly this gate "
          "(and any other gate that still needs one), addressing the specific issue named above."
    )


# --- adaptive, complexity-sensitive ReAct budget (opt-in) -------------------

def _git_diff_modified_files(root: Path) -> List[str]:
    """Real, best-effort `git diff --name-only HEAD` against the current
    worktree. Mirrors engine.DVHarness._git_modified_files() exactly (same
    command, same cwd, same defensive try/except) but is re-derived here
    rather than imported: react_loop.py must stay importable/testable
    standalone without an engine.DVHarness instance (see this module's own
    "SECOND DEVIATION" precedent for the identical reasoning behind
    profiler/profile_id/agent_name being threaded through as plain
    parameters rather than pulled from an engine object). No git repo, no
    HEAD yet, git not on PATH, or any other failure all degrade to an empty
    list, never a fabricated guess."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD"], cwd=str(root), text=True,
            stderr=subprocess.DEVNULL,
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def _distinct_subsystems(paths: List[str]) -> List[str]:
    """A real, mechanical complexity signal derived from real git-modified
    file paths: the distinct top-level path segment of each one (e.g.
    "dv_harness/engine.py" -> "dv_harness", "tools/remote/x.py" -> "tools").
    This is deliberately a coarse, purely structural grouping used only to
    size a retry/iteration budget -- never a semantic DV protocol/subsystem
    classification (that stays protocol_router.py's/environment_mode_
    router.py's own, separate job), and never a fabricated subsystem name:
    a path with no real top-level segment (e.g. a bare filename at repo
    root) is not counted. Order-preserving, de-duplicated."""
    seen: List[str] = []
    for p in paths:
        norm = p.replace("\\", "/")
        segment = norm.split("/", 1)[0] if "/" in norm else ""
        if segment and segment not in seen:
            seen.append(segment)
    return seen


def compute_adaptive_react_budget(cfg: Optional[dict], root: Path) -> Dict[str, Any]:
    """Returns {"mode", "max_iterations", "max_adapter_calls", ...} for this
    stage attempt's inner ReAct loop.

    DEFAULT (policy.adaptive_react_budget.enabled absent or false, i.e.
    every project that has not explicitly opted in): mode="fixed", and
    max_iterations/max_adapter_calls are read off policy.
    inner_react_max_iterations / policy.inner_react_max_adapter_calls with
    the EXACT SAME (3, 2) fallback defaults InnerReactLoop.run() used before
    this function existed -- byte-identical to today's behavior. No git
    subprocess is ever invoked in this branch.

    OPT-IN (policy.adaptive_react_budget.enabled=true): mode=
    "complexity_scaled". The real complexity signal is the number of
    distinct files `git diff --name-only HEAD` shows as touched in the
    current worktree, and the number of distinct top-level subsystem
    directories those files sit under (_distinct_subsystems() above) -- the
    "number of distinct files/subsystems touched by the current
    investigation" this task names, read from real git evidence exactly the
    way engine.py's own _protocol_router_evidence() already sources
    "modified_files" (see that method's own docstring: "no real git diff
    call in this engine ... fed only" real evidence, never fabricated).

    Each of the two budgets is computed independently, linearly, and
    clamped between a declared floor and a declared ceiling -- never
    unbounded, so this can never turn into a silent, unbounded retry loop:
        max_iterations     = clamp(min_iterations
                                    + floor(distinct_file_count / files_per_iteration_step),
                                    min_iterations, max_iterations_ceiling)
        max_adapter_calls  = clamp(min_adapter_calls
                                    + floor(distinct_subsystem_count / subsystems_per_iteration_step),
                                    min_adapter_calls, max_adapter_calls_ceiling)
    Every one of those six numbers is itself a declared, human-editable
    config.json field (config.DEFAULT_CONFIG's own policy.
    adaptive_react_budget block) with a safe, small built-in default -- this
    function never invents a scaling constant of its own that a human could
    not see or override.

    Per this task's own rule 3 (never apply a weight/threshold change
    directly to production scoring without a human decision): this whole
    mode is dormant until a human sets adaptive_react_budget.enabled=true in
    a project's own config.json -- the identical opt-in convention every
    other production-behavior flag in DEFAULT_CONFIG already uses. Still
    honest even once enabled: the underlying `git diff` in a project with no
    git repo (or with nothing modified) degrades to zero distinct files/
    subsystems, which floors both budgets at their declared min_* values --
    never a crash, and never treated as "unlimited complexity"."""
    policy = (cfg or {}).get("policy", {}) or {}
    fixed_max_iterations = policy.get("inner_react_max_iterations", 3)
    fixed_max_adapter_calls = policy.get("inner_react_max_adapter_calls", 2)

    adaptive_cfg = policy.get("adaptive_react_budget")
    if not isinstance(adaptive_cfg, dict) or not adaptive_cfg.get("enabled"):
        return {
            "mode": "fixed",
            "max_iterations": fixed_max_iterations,
            "max_adapter_calls": fixed_max_adapter_calls,
        }

    # Best-effort from here down, mirroring this module's own established
    # "observability/a new opt-in mode must never break an already-computed
    # verdict" discipline (see e.g. the react_recorder.record_reflection()
    # try/except above): a malformed adaptive_react_budget block (a
    # non-numeric field, an inverted min/max, ...) or a git-invocation
    # surprise this function's own two helpers did not anticipate falls
    # back to the identical fixed-mode result rather than ever raising out
    # of InnerReactLoop.run() and failing a real stage attempt.
    try:
        modified_files = _git_diff_modified_files(root)
        subsystems = _distinct_subsystems(modified_files)

        def _clamp_int(value, lo, hi):
            lo = int(lo)
            hi = int(hi)
            if hi < lo:
                hi = lo
            return max(lo, min(hi, int(value)))

        min_iterations = adaptive_cfg.get("min_iterations", 2)
        max_iterations_ceiling = adaptive_cfg.get("max_iterations", 6)
        files_per_step = max(1, int(adaptive_cfg.get("files_per_iteration_step", 3) or 1))
        scaled_iterations = int(min_iterations) + (len(modified_files) // files_per_step)
        max_iterations = _clamp_int(scaled_iterations, min_iterations, max_iterations_ceiling)

        min_adapter_calls = adaptive_cfg.get("min_adapter_calls", 1)
        max_adapter_calls_ceiling = adaptive_cfg.get("max_adapter_calls", 4)
        subsystems_per_step = max(1, int(adaptive_cfg.get("subsystems_per_iteration_step", 1) or 1))
        scaled_adapter_calls = int(min_adapter_calls) + (len(subsystems) // subsystems_per_step)
        max_adapter_calls = _clamp_int(scaled_adapter_calls, min_adapter_calls, max_adapter_calls_ceiling)

        return {
            "mode": "complexity_scaled",
            "max_iterations": max_iterations,
            "max_adapter_calls": max_adapter_calls,
            "distinct_file_count": len(modified_files),
            "distinct_subsystem_count": len(subsystems),
            "modified_files": modified_files,
            "subsystems": subsystems,
        }
    except Exception as exc:
        return {
            "mode": "fixed",
            "max_iterations": fixed_max_iterations,
            "max_adapter_calls": fixed_max_adapter_calls,
            "adaptive_react_budget_error": repr(exc),
        }


# --- the inner loop itself ---------------------------------------------------

class InnerReactLoop:
    def __init__(self, root, adapter, react_recorder, cfg, graph=None,
                 profiler=None, profile_id=None, agent_name="", protocol=None):
        self.root = Path(root)
        self.adapter = adapter
        self.react_recorder = react_recorder
        self.cfg = cfg or {}
        self.graph = graph  # additive vs. the design spec's signature -- see module docstring
        # profiler/profile_id/agent_name: SECOND DEVIATION, same module
        # docstring -- the same StageExecutionProfiler + profile_id
        # engine.py's run_stage() already holds, threaded through so this
        # loop's own real adapter.run() calls stop being invisible to it.
        self.profiler = profiler
        self.profile_id = profile_id
        self.agent_name = agent_name
        # The real RouteResolver-produced protocol for this stage attempt --
        # forwarded to build_menu() so its NO_EVIDENCE_BLOCK_SUPPLIED source
        # can cross-reference protocol_builder_registry.json. See
        # build_menu()'s own `protocol` docstring paragraph.
        self.protocol = protocol

    def run(self, stage: str, node, attempt: int, first_result, first_verdict: str,
            first_reasons: List[str], first_signatures: List[GateSignature],
            base_prompt: str) -> InnerReactOutcome:
        policy = (self.cfg or {}).get("policy", {})
        # compute_adaptive_react_budget() falls straight back to the exact
        # same two policy.get(..., default) reads used here before this was
        # added whenever policy.adaptive_react_budget.enabled is absent/false
        # (see that function's own docstring) -- byte-identical default
        # behavior for every project that has not explicitly opted in.
        budget_info = compute_adaptive_react_budget(self.cfg, self.root)
        max_iterations = budget_info["max_iterations"]
        max_adapter_calls = budget_info["max_adapter_calls"]

        result = first_result
        verdict = first_verdict
        reasons = first_reasons
        signatures = first_signatures
        evidence_blocks = extract_evidence_blocks(result.text) if getattr(result, "text", None) else {}

        prior_signatures: Optional[List[GateSignature]] = None
        adapter_calls_used = 0
        inner_iter = 0
        reroute_target: Optional[str] = None

        while True:
            # Priority 1: explicit gate closure -- the strongest case.
            if verdict in ("PASS", "NO_GATE_REQUIRED"):
                break

            inner_iter += 1
            # Priority 4 (safety backstop, never the intended path): iteration cap.
            if inner_iter > max_iterations:
                inner_iter -= 1
                break

            menu = build_menu(self.root, stage, node, signatures, prior_signatures,
                              graph=self.graph, protocol=self.protocol)
            prompt_context = {
                "stage": stage, "attempt": attempt, "inner_iteration": inner_iter,
                "verdict": verdict, "reasons": reasons,
                "signatures": [asdict(s) for s in signatures],
            }
            decision = reflect_and_decide(self.adapter, self.root, stage, prompt_context, menu,
                                           profiler=self.profiler, profile_id=self.profile_id,
                                           agent_name=self.agent_name)

            if self.react_recorder is not None and node is not None:
                try:
                    self.react_recorder.record_reflection(stage, attempt, inner_iter, signatures, menu, decision)
                except Exception:
                    pass  # observability must never break an already-computed verdict

            # Priority 2: reflection explicitly concluded no further action.
            if decision.chosen_option_id.startswith("CONVERGE"):
                break

            chosen = next((m for m in menu if m.option_id == decision.chosen_option_id), None)
            if chosen is None:
                # reflect_and_decide() already validated against the menu, so
                # this should be unreachable -- but never action an option
                # this loop itself cannot resolve to real menu data.
                break

            if chosen.kind == "REROUTE":
                # Never accepted unless it is a real key in self.graph.nodes
                # (see module docstring) -- a hallucinated/stale target is
                # silently dropped, same discipline gates.py already applies
                # to malformed evidence. Zero adapter cost.
                if self.graph is not None and chosen.target in self.graph.nodes:
                    reroute_target = chosen.target
                break

            if chosen.kind in ("RETRY_TARGETED", "REQUEST_EVIDENCE"):
                if adapter_calls_used >= max_adapter_calls:
                    break  # safety backstop -- verdict stays the last real evaluation
                adapter_calls_used += 1
                prior_signatures = signatures  # snapshot BEFORE this action overwrites it
                next_prompt = _build_action_prompt(base_prompt, chosen, decision)
                _t0 = time.perf_counter()
                new_result = self.adapter.run(
                    prompt=next_prompt, cwd=str(self.root),
                    resume_session=getattr(result, "session_id", None),
                )
                _record_agent_run(self.profiler, self.profile_id, self.agent_name, _t0, new_result)
                result = new_result
                if getattr(result, "ok", False):
                    verdict, reasons, signatures = evaluate_stage_evidence_with_detail(
                        self.root, stage, result.text)
                    evidence_blocks = extract_evidence_blocks(result.text) if result.text else {}
                # else: transport failure on the retry -- keep the previous
                # verdict/reasons/signatures; the outer loop will see this
                # only through result.ok on the NEXT real evaluation, same as
                # any other adapter-transport-failure path in run_stage().
                continue

            # ADJUST_PARAM or any other kind build_menu() does not currently
            # synthesize: nothing left this loop knows how to action safely.
            break

        return InnerReactOutcome(
            result=result, verdict=verdict, reasons=reasons,
            evidence_blocks=evidence_blocks, reroute_target=reroute_target,
            iterations=inner_iter, budget_info=budget_info,
        )
