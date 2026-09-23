"""L5DGVA V14 (`L5DGVA/L5_DGVA_Generic_MultiLevel_Verification_Contract_v14_STRICT_AI_Architecture.md`,
section 342) `EightEngineRuntimeProofMatrix` -- read only, over evidence that
already exists.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) WITH ADAPTATION.
Source: Parent (D:\\DV\\Task\\DV_Agent_Harness_L5), commit 3e9dd7360f584078ed8f4b04120c9844acabd97b.

ADAPTATION (dependency-first analysis, real evidence, not assumed transfer of Parent's
own citations): Parent's `five_level_memory_engine` `EngineRule` names 8 `EngineSignal`s.
Canonical's own `dv_harness/engine.py` was independently evolved from Parent's and, as of
this migration, genuinely emits only 5 of those 8 memory-promotion event names -- confirmed
by grepping canonical's real `engine.py` for every literal event string, not by trusting
Parent's citation. `ARCHITECTURE_DISCOVERY_PROMOTED`, `VERIFICATION_ARCHITECTURE_TOPOLOGY_PROMOTED`
and `DE_BASELINE_REPRODUCTION_PROMOTED` have zero matches anywhere in canonical's `engine.py`
today; the corresponding memory-promotion call sites/event producers simply do not exist yet
in this codebase. Rather than silently keep Parent's 8-signal list (which would make this
engine permanently, invisibly `NOT_PROVEN` against evidence that can never appear) or drop
the rule entirely, the `signals` tuple below is honestly reduced to the 5 real, confirmed
event names, disclosed here rather than left implicit. Every other `EngineRule`'s cited event
name was independently confirmed present in canonical's `engine.py` too, and every
`evidence_refs` line below cites REAL canonical file:line locations (re-grepped against this
migration's own canonical tree), never Parent's own line numbers, which do not apply to an
independently-evolved file.

PRIMARY SOURCE, quoted verbatim (section 342, lines 5020-5029 of that file):

    ## 342. EightEngineRuntimeProofMatrix

    For every major pilot/task create `EightEngineRuntimeProofMatrix` with
    EngineId, Defined, Implemented, Wired, Trigger, Invoked,
    InvocationEvidence, ArtifactIds, ConsumerIds, DecisionImpact,
    OutcomeVerified, RegressionIds, Verdict and EvidenceRefs.

    Any applicable missing stage yields PARTIAL/FAIL, never PASS.

    Required: `EightEngineRuntimeProofMatrix_PASS = true`

Section 341 (same file, lines 5011-5019) is the reason this exists at all:
"Class/module/file/CLAUDE.md existence does not prove runtime execution."
This module is the concrete, evidence-only answer to that for the 8 engines
section 339 names (Autonomous Inference, Graph Orchestrator, Multi-Agent
Orchestrator, Route & Skill Resolver, Plan-and-Execute/ReAct, Blackboard/
Evidence, 5-Level Memory, Qualification/Signoff).

WHAT THIS MODULE ACTUALLY DOES. Reads real events already written to
`.dv-harness/events.jsonl` (via `loop_telemetry.read_events()` -- the same
reader `dashboard._tail_events()` and `platform_health.py` reuse, not a new
parser) and, for each of the 8 engines, checks whether a LITERALLY NAMED
event type this codebase's own `engine.py` actually emits appears in the
scanned window. A match is `PROVEN`. No match, for an engine that DOES have a
real producer, is `NOT_PROVEN` (wired, not exercised in this window). An
engine with NO producer at all today is `NO_RUNTIME_SIGNAL_SOURCE` -- a
disclosed, honest gap, never forced to a guess.

WHAT THIS MODULE DELIBERATELY DOES NOT DO.

  * It does not add a single new event producer to `engine.py`. Every event
    name checked below already exists in the real, currently-committed
    `dv_harness/engine.py` (file:line cited per engine); this module is a
    reader over that pre-existing evidence, per this task's own scope.
  * It does not infer an engine fired from a WEAKER signal than a real,
    named event whose call site was actually traced back to that engine's
    own module. Three of the 8 engines (Multi-Agent Orchestrator, Route &
    Skill Resolver, Plan-and-Execute/ReAct) are real, wired, called-on-the-
    production-path modules (traced call sites are in each `EngineRule`'s
    `evidence_refs`/`gap_note` below) that simply have NO events.jsonl
    producer of their own today -- their real invocation evidence lives in
    OTHER files (`.dv-harness/react/<node>/iteration_NNN.json`, the
    `AgentTaskStore` task record, the in-memory prompt payload) that this
    module does not read, because doing so honestly would require a
    different reader than "events.jsonl only" and this task scoped the
    matrix to real, already-emitted EVENTS. These three are reported
    `NO_RUNTIME_SIGNAL_SOURCE` rather than silently upgraded using a nearby
    but unrelated event (e.g. `RCA_EVIDENCE_FANOUT_DISPATCHED` names which
    GRAPH branches were selected for concurrent execution -- a real Graph
    Orchestrator fact -- and is NOT counted as Multi-Agent Orchestrator
    proof, even though multi-agent dispatch typically follows it).
  * It does not compute `ArtifactIds` / `ConsumerIds` / `DecisionImpact` /
    `OutcomeVerified` / `RegressionIds` from anything but the matched
    event's own payload. Where a matched event's payload does carry a
    genuinely relevant sub-value (e.g. `EXPERIENCE_KNOWLEDGE_PROMOTED`'s
    `promotion.destination`), it is surfaced inside `invocation_evidence`,
    never synthesized into a separate field this module cannot back with a
    real per-engine consumption/regression trace. Those five section-342
    columns are honestly `NOT_AVAILABLE` for every engine in THIS module's
    current scope -- a distinct, later gap (linking promotion/task-store/
    react-iteration records into real ArtifactId/ConsumerId/RegressionId
    chains), not something this reader may guess at just because the
    dataclass has room for it.

WHY EVENTS.JSONL SPECIFICALLY. `dv_harness/loop_telemetry.py`'s own writer
half already proves this file is the one append-only place every subsystem
in this harness writes runtime facts to (`storage.StateStore.event()`); this
module reuses its reader (`loop_telemetry.read_events`) rather than adding a
second parser beside it and `dashboard._tail_events()`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import loop_telemetry

#: The three real verdicts. `NO_RUNTIME_SIGNAL_SOURCE` is distinct from
#: `NOT_PROVEN`: the former means this engine has no event producer to check
#: at all (a structural gap in the current instrumentation), the latter means
#: a producer exists but did not fire in the scanned window (a per-run fact).
PROVEN = "PROVEN"
NOT_PROVEN = "NOT_PROVEN"
NO_RUNTIME_SIGNAL_SOURCE = "NO_RUNTIME_SIGNAL_SOURCE"

VERDICTS: Tuple[str, ...] = (PROVEN, NOT_PROVEN, NO_RUNTIME_SIGNAL_SOURCE)

#: What every section-342 column this module cannot honestly compute reports,
#: rather than a fabricated value.
NOT_AVAILABLE = "NOT_AVAILABLE"

EventRecord = Dict[str, Any]
EventPredicate = Callable[[EventRecord], bool]


@dataclass(frozen=True)
class EngineSignal:
    """One (event name, optional extra predicate) pair that counts as real
    invocation evidence for an engine. `predicate` narrows a same-named event
    that several different mechanisms share (e.g. `LOOP_BLOCKED` fires for
    many stop reasons; only `reason == "SIGNOFF_GATE_REFUSED"` is Qualification/
    Signoff Engine evidence)."""
    event_name: str
    predicate: Optional[EventPredicate] = None
    note: str = ""


@dataclass(frozen=True)
class EngineRule:
    engine_id: str
    engine_name: str
    module: str
    trigger: str
    signals: Tuple[EngineSignal, ...]
    evidence_refs: Tuple[str, ...]
    gap_note: str = ""
    caveat: str = ""


def _signoff_gate_refused(rec: EventRecord) -> bool:
    return rec.get("reason") == "SIGNOFF_GATE_REFUSED"


def _route_populated(rec: EventRecord) -> bool:
    return bool(rec.get("route"))


#: The 8 engines section 339/342 name, in that section's own order.
#: `signals == ()` means: real, wired, called-on-the-production-path module
#: (see `gap_note`/`evidence_refs`) with NO events.jsonl producer today.
ENGINE_RULES: Tuple[EngineRule, ...] = (
    EngineRule(
        engine_id="autonomous_inference_engine",
        engine_name="Autonomous Inference Engine",
        module="dv_harness/inference.py",
        trigger="A root_cause_evidence_gate block is scored at a RE_AUDIT/"
                "ANALYSIS-family stage.",
        signals=(EngineSignal("ROOT_CAUSE_CONFIDENCE_SCORED"),),
        evidence_refs=(
            "dv_harness/engine.py:2808 -- emits ROOT_CAUSE_CONFIDENCE_SCORED after "
            "calling inference.score_confidence()/identify_gap()/next_best_action(), "
            "carrying their real output.",
        ),
    ),
    EngineRule(
        engine_id="graph_orchestrator",
        engine_name="Graph Orchestrator",
        module="dv_harness/graph.py",
        trigger="engine.DVHarness.loop() selects the next stage to run.",
        signals=(
            EngineSignal("LOOP_ACTION_SELECTED", predicate=_route_populated,
                         note="route is read off the real GraphDefinition node"),
            EngineSignal("RCA_EVIDENCE_FANOUT_DISPATCHED",
                         note="graph-declared parallel_group branches selected for fan-out"),
        ),
        evidence_refs=(
            "dv_harness/engine.py:1005-1016 (_emit_loop_action_selected) -- "
            "node = self.graph.nodes.get(stage); route/skills read off that real "
            "GraphDefinition node, not a description of it.",
            "dv_harness/engine.py:5682-5719 (_resolve_conditional_fanout_frontier) -- "
            "self.graph.nodes[t].parallel_group real lookup feeds RCA_EVIDENCE_FANOUT_DISPATCHED.",
        ),
    ),
    EngineRule(
        engine_id="multi_agent_orchestrator",
        engine_name="Multi-Agent Orchestrator",
        module="dv_harness/multi_agent.py",
        trigger="run_stage() delegates a graph node to an agent "
                "(self.agents.delegate(node, plan, route_info=route_info)).",
        signals=(),
        evidence_refs=(
            "dv_harness/engine.py:4418 -- task = self.agents.delegate(node, plan, "
            "route_info=route_info), a real MultiAgentOrchestrator.delegate() call "
            "on the production path.",
        ),
        gap_note=(
            "delegate() writes a real AgentTaskStore task record -- but that record "
            "lands in the AgentTaskStore's own file, never in events.jsonl. "
            "RCA_EVIDENCE_FANOUT_DISPATCHED (engine.py:5716) is Graph Orchestrator "
            "evidence (which branches the GRAPH selected), not proof that "
            "MultiAgentOrchestrator.delegate() itself ran for any of them -- citing "
            "it here would be exactly the unrelated-event fabrication this module "
            "must refuse. No events.jsonl event names a delegate()/complete_task() "
            "call today."
        ),
    ),
    EngineRule(
        engine_id="route_skill_resolver",
        engine_name="Route & Skill Resolver",
        module="dv_harness/skill_resolver.py",
        trigger="run_stage() resolves a graph node's route and skills before "
                "delegating it (self.router.resolve(...), self.skills.resolve(...)).",
        signals=(),
        evidence_refs=(
            "dv_harness/engine.py:4385-4388 -- protocol_decision = resolve_protocol(...); "
            "route_info = self.router.resolve(node, protocol_decision=protocol_decision); "
            "resolved_skills = self.skills.resolve(route_info[\"skills\"]) -- real "
            "RouteResolver/SkillResolver calls on the production path.",
        ),
        gap_note=(
            "Both calls' results are folded only into the in-memory prompt/task "
            "payload (plan_section, task[\"route\"]/task[\"skills\"]); no "
            "events.jsonl entry names either call or carries resolved_skills. "
            "LOOP_ACTION_SELECTED's own `skills` field (engine.py:1015) is the "
            "graph node's STATIC declared list (`node.skills`), read BEFORE "
            "SkillResolver.resolve() runs on it -- it is the resolver's INPUT, not "
            "its output, and is deliberately not counted as resolver-invocation "
            "evidence for that reason."
        ),
    ),
    EngineRule(
        engine_id="plan_execute_react_engine",
        engine_name="Plan-and-Execute / ReAct Engine",
        module="dv_harness/react_loop.py",
        trigger="A stage attempt's gate evaluation returns other than PASS and "
                "the inner ReAct loop runs before the next outer retry.",
        signals=(),
        evidence_refs=(
            "dv_harness/engine.py:5353 -- outcome = InnerReactLoop(self.root, "
            "self.adapter, self.react, self.cfg, graph=self.graph, ...).run(...) -- "
            "a real react_loop.InnerReactLoop call on the production retry path.",
        ),
        gap_note=(
            "The real per-turn record this call produces (dv_harness/react.py, "
            "ReactRecorder.record()) is written to "
            ".dv-harness/react/<node>/iteration_NNN.json plus a WorkingMemoryStore "
            "record via memory_router -- both real, both outside events.jsonl. No "
            "section-108 loop event or any other events.jsonl entry names an "
            "InnerReactLoop invocation."
        ),
    ),
    EngineRule(
        engine_id="blackboard_evidence_engine",
        engine_name="Blackboard / Evidence Engine",
        module="dv_harness/blackboard.py",
        trigger="The self-healing topic refresher runs at a stage boundary.",
        signals=(EngineSignal("BLACKBOARD_TOPIC_REFRESH"),),
        evidence_refs=(
            "dv_harness/engine.py:4221-4224 -- if reports: self.store.event({..., "
            "\"event\": \"BLACKBOARD_TOPIC_REFRESH\", \"topics\": reports}).",
        ),
        caveat=(
            "This event covers exactly ONE Blackboard mechanism (the topic "
            "refresher). The far more common self.blackboard.write()/read() calls "
            "elsewhere in engine.py have no dedicated events.jsonl producer of "
            "their own -- PROVEN here means 'the refresher ran', not 'the "
            "Blackboard was written to at all this run'."
        ),
    ),
    EngineRule(
        engine_id="five_level_memory_engine",
        engine_name="5-Level Memory Engine",
        module="dv_harness/memory.py",
        trigger="A stage PASS's evidence block is routed through "
                "memory_router.route_and_store()/promote_to_organizational().",
        signals=(
            # ADAPTATION (see module docstring): Parent names 8 signals here.
            # Canonical's real engine.py, independently grepped, emits only these
            # 5 -- ARCHITECTURE_DISCOVERY_PROMOTED, VERIFICATION_ARCHITECTURE_
            # TOPOLOGY_PROMOTED and DE_BASELINE_REPRODUCTION_PROMOTED have zero
            # producers in this codebase today and are deliberately NOT listed,
            # rather than kept as signals that can never match real evidence.
            EngineSignal("EXPERIENCE_KNOWLEDGE_PROMOTED"),
            EngineSignal("PROJECT_TOPOLOGY_PROMOTED"),
            EngineSignal("VPLAN_SUMMARY_PROMOTED"),
            EngineSignal("VERIFIED_FIX_PROMOTED"),
            EngineSignal("ORGANIZATIONAL_PROMOTION_EVALUATED"),
        ),
        evidence_refs=(
            "dv_harness/engine.py:1907, 3152, 3221, 3397, 3513 -- each calls "
            "memory_router.route_and_store()/promote_to_organizational() then emits "
            "its named *_PROMOTED / ORGANIZATIONAL_PROMOTION_EVALUATED event carrying "
            "the real promotion result (including promotion.destination). Re-grepped "
            "directly against canonical's own engine.py for this migration -- these "
            "line numbers are canonical's, not Parent's (the two files have "
            "independently diverged).",
        ),
        caveat=(
            "The far more common per-stage RECALL call -- "
            "MemoryRetriever(MemoryStore(self.root)).search(...), run on essentially "
            "every stage attempt -- has no events.jsonl producer. PROVEN here means "
            "a PROMOTION happened, not merely that memory was consulted. Separately, "
            "canonical's engine.py does not yet emit ARCHITECTURE_DISCOVERY_PROMOTED, "
            "VERIFICATION_ARCHITECTURE_TOPOLOGY_PROMOTED or "
            "DE_BASELINE_REPRODUCTION_PROMOTED at all (confirmed by grep, zero "
            "matches) -- a real, disclosed 3-signal instrumentation gap relative to "
            "Parent, not modeled by this rule's signals so PROVEN can never be "
            "claimed on the strength of an event that cannot fire."
        ),
    ),
    EngineRule(
        engine_id="qualification_signoff_engine",
        engine_name="Qualification / Signoff Engine",
        module="dv_harness/qualified_conclusion.py + dv_harness/policy.py (can_signoff)",
        trigger="A RE_AUDIT-family stage builds a QualifiedConclusion, a "
                "SIGNOFF bundle is exported, or the SIGNOFF stage's "
                "policy.can_signoff() gate refuses.",
        signals=(
            EngineSignal("QUALIFIED_CONCLUSION_BUILT"),
            EngineSignal("SIGNOFF_BUNDLE_EXPORTED"),
            EngineSignal("LOOP_BLOCKED", predicate=_signoff_gate_refused,
                         note="policy.can_signoff() refused the SIGNOFF stage"),
        ),
        evidence_refs=(
            "dv_harness/engine.py:2876 -- qc = build_qualified_conclusion(verdict, "
            "confidence_result, block); self.blackboard.write(\"qualified_conclusion\", "
            "qc.as_dict(), ...); emits QUALIFIED_CONCLUSION_BUILT.",
            "dv_harness/engine.py:2205 -- signoff_export.collect_signoff_bundle(...); "
            "emits SIGNOFF_BUNDLE_EXPORTED.",
            "dv_harness/engine.py:6140-6145 -- self._end_loop_telemetry(\"LOOP_BLOCKED\", "
            "stage=stage, ..., reason=\"SIGNOFF_GATE_REFUSED\", ...) on a can_signoff() "
            "refusal with no redirect stage.",
        ),
    ),
)

assert {r.engine_id for r in ENGINE_RULES} == {
    "autonomous_inference_engine", "graph_orchestrator", "multi_agent_orchestrator",
    "route_skill_resolver", "plan_execute_react_engine", "blackboard_evidence_engine",
    "five_level_memory_engine", "qualification_signoff_engine",
}, "ENGINE_RULES must name exactly section 339's 8 engines, no more, no fewer."


@dataclass
class EngineProofRow:
    """Section 342's own field list. `artifact_ids`/`consumer_ids`/
    `decision_impact`/`outcome_verified`/`regression_ids` are `NOT_AVAILABLE`
    for every row -- see this module's own docstring for why they are not
    computed rather than guessed."""
    engine_id: str
    engine_name: str
    module: str
    defined: bool
    implemented: bool
    wired: bool
    trigger: str
    invoked: bool
    invocation_evidence: List[Dict[str, Any]]
    artifact_ids: Any
    consumer_ids: Any
    decision_impact: Any
    outcome_verified: Any
    regression_ids: Any
    verdict: str
    evidence_refs: List[str]
    gap_note: str = ""
    caveat: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "EngineId": self.engine_id, "EngineName": self.engine_name,
            "Module": self.module, "Defined": self.defined,
            "Implemented": self.implemented, "Wired": self.wired,
            "Trigger": self.trigger, "Invoked": self.invoked,
            "InvocationEvidence": self.invocation_evidence,
            "ArtifactIds": self.artifact_ids, "ConsumerIds": self.consumer_ids,
            "DecisionImpact": self.decision_impact,
            "OutcomeVerified": self.outcome_verified,
            "RegressionIds": self.regression_ids,
            "Verdict": self.verdict, "EvidenceRefs": self.evidence_refs,
            "GapNote": self.gap_note, "Caveat": self.caveat,
        }


def _trim(rec: EventRecord) -> Dict[str, Any]:
    """The handful of fields worth showing per matched event -- never the
    whole record (some payloads carry large sub-blocks)."""
    keys = ("ts", "event", "stage", "run_id", "reason", "route",
            "branches", "record_kind")
    out = {k: rec[k] for k in keys if k in rec}
    promotion = rec.get("promotion")
    if isinstance(promotion, dict) and "destination" in promotion:
        out["promotion_destination"] = promotion["destination"]
    return out


def _matches(signal: EngineSignal, rec: EventRecord) -> bool:
    if rec.get("event") != signal.event_name:
        return False
    if signal.predicate is None:
        return True
    try:
        return bool(signal.predicate(rec))
    except Exception:
        return False


def build_matrix(root: Path, *, run_id: Optional[str] = None,
                  scan_lines: int = loop_telemetry.DEFAULT_EVENT_SCAN_LINES,
                  max_evidence_per_engine: int = 5,
                  ) -> Dict[str, EngineProofRow]:
    """The real matrix for one project, over the real trailing window of
    `.dv-harness/events.jsonl` (via `loop_telemetry.read_events`, not a new
    parser). `run_id` narrows to one loop session the same way
    `loop_telemetry.read_loop_telemetry(run_id=...)` does."""
    root = Path(root)
    entries, _scanned, _truncated = loop_telemetry.read_events(root, scan_lines=scan_lines)
    if run_id:
        entries = [e for e in entries if e.get("run_id") == run_id]

    rows: Dict[str, EngineProofRow] = {}
    for rule in ENGINE_RULES:
        if not rule.signals:
            rows[rule.engine_id] = EngineProofRow(
                engine_id=rule.engine_id, engine_name=rule.engine_name,
                module=rule.module, defined=True, implemented=True, wired=True,
                trigger=rule.trigger, invoked=False, invocation_evidence=[],
                artifact_ids=NOT_AVAILABLE, consumer_ids=NOT_AVAILABLE,
                decision_impact=NOT_AVAILABLE, outcome_verified=NOT_AVAILABLE,
                regression_ids=NOT_AVAILABLE, verdict=NO_RUNTIME_SIGNAL_SOURCE,
                evidence_refs=list(rule.evidence_refs), gap_note=rule.gap_note,
                caveat=rule.caveat)
            continue
        matched = [e for e in entries if any(_matches(sig, e) for sig in rule.signals)]
        verdict = PROVEN if matched else NOT_PROVEN
        rows[rule.engine_id] = EngineProofRow(
            engine_id=rule.engine_id, engine_name=rule.engine_name,
            module=rule.module, defined=True, implemented=True, wired=True,
            trigger=rule.trigger, invoked=bool(matched),
            invocation_evidence=[_trim(e) for e in matched[:max_evidence_per_engine]],
            artifact_ids=NOT_AVAILABLE, consumer_ids=NOT_AVAILABLE,
            decision_impact=NOT_AVAILABLE, outcome_verified=NOT_AVAILABLE,
            regression_ids=NOT_AVAILABLE, verdict=verdict,
            evidence_refs=list(rule.evidence_refs), gap_note=rule.gap_note,
            caveat=rule.caveat)
    return rows


def matrix_pass(rows: Dict[str, EngineProofRow]) -> bool:
    """`EightEngineRuntimeProofMatrix_PASS` as section 342 actually defines
    it: PASS only if every applicable engine is PROVEN. This harness has 3
    engines with NO current runtime-signal source at all (see module
    docstring) -- so this is always False against real evidence today, which
    is the honest answer, not a bug to work around."""
    return bool(rows) and all(r.verdict == PROVEN for r in rows.values())


def render_matrix_text(rows: Dict[str, EngineProofRow]) -> str:
    header = f"{'Engine':<32} | {'Verdict':<22} | Trigger"
    lines = [header, "-" * len(header)]
    for row in rows.values():
        lines.append(f"{row.engine_name:<32} | {row.verdict:<22} | {row.trigger}")
    lines.append("")
    lines.append(f"EightEngineRuntimeProofMatrix_PASS = {matrix_pass(rows)}")
    return "\n".join(lines)


def execute_verb(root: Path, verb: str, *, run_id: Optional[str] = None
                  ) -> Tuple[int, Any]:
    """Same shared-`execute_verb()` convention `loop_telemetry`/`loop_contract`/
    `loop_budget` already follow."""
    root = Path(root)
    if verb in ("matrix", "show"):
        rows = build_matrix(root, run_id=run_id)
        if verb == "show":
            return (0 if matrix_pass(rows) else 2), render_matrix_text(rows)
        return (0 if matrix_pass(rows) else 2), {
            "rows": {k: v.to_dict() for k, v in rows.items()},
            "EightEngineRuntimeProofMatrix_PASS": matrix_pass(rows),
        }
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["matrix", "show"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    import json
    p = argparse.ArgumentParser(
        prog="python -m dv_harness.eight_engine_runtime_proof_matrix",
        description="L5DGVA V14 section 342's EightEngineRuntimeProofMatrix over "
                    "real .dv-harness/events.jsonl evidence only.")
    p.add_argument("verb", choices=["matrix", "show"])
    p.add_argument("--project-root", default=".")
    p.add_argument("--run-id", default=None)
    args = p.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb, run_id=args.run_id)
    print(payload if isinstance(payload, str)
          else json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
