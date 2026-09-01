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
from __future__ import annotations

import json
import re
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
               graph=None) -> List[MenuOption]:
    """Constructs the constrained option menu -- the ONLY vocabulary the
    reflection call is allowed to choose from. See the module docstring for
    why `graph` is an additive parameter beyond the design spec's illustrative
    signature. Never returns a free-form option; the two CONVERGE_* controls
    are always the fallback."""
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
            protocol = sig.detail.get("protocol")
            gap_source = missing if isinstance(missing, list) else []
            if protocol and gap_source:
                gap = identify_gap(gap_source, [])
                for action in next_best_action(protocol, gap, root):
                    if action.get("source") == "protocol_builder_registry":
                        _add(f"REQUEST_EVIDENCE:{sig.gate_id}:{action['gap']}", "REQUEST_EVIDENCE",
                             sig.gate_id,
                             f"{action['suggested_action']} (gap: {action['gap']}).",
                             "protocol_builder_registry")

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


# --- the inner loop itself ---------------------------------------------------

class InnerReactLoop:
    def __init__(self, root, adapter, react_recorder, cfg, graph=None,
                 profiler=None, profile_id=None, agent_name=""):
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

    def run(self, stage: str, node, attempt: int, first_result, first_verdict: str,
            first_reasons: List[str], first_signatures: List[GateSignature],
            base_prompt: str) -> InnerReactOutcome:
        policy = (self.cfg or {}).get("policy", {})
        max_iterations = policy.get("inner_react_max_iterations", 3)
        max_adapter_calls = policy.get("inner_react_max_adapter_calls", 2)

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

            menu = build_menu(self.root, stage, node, signatures, prior_signatures, graph=self.graph)
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
            iterations=inner_iter,
        )
