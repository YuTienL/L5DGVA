from __future__ import annotations
from typing import Any, Dict, Optional
from .control_plane import ControlPlane, replan_stage, now as cp_now
from .models import Stage, Status

# Single, reusable implementation of "what happens when <VERB> is issued" for
# every Human Control Plane command -- extracted from dv_harness/cli.py's
# main() if/elif chain (2026-08-28 dashboard work), which had this logic
# inline and was the ONLY caller. dv_harness/cli.py and dv_harness/dashboard.py
# now both call these functions so there is exactly one implementation of
# each verb's event-logging + ControlPlane/DVHarness mutation, not two
# (cli.py via subprocess-tested argparse handlers, dashboard.py via HTTP
# POST /api/control) that could silently drift apart.
#
# Every function here takes a live `h: DVHarness` (already constructed
# against the target project_root) and returns a plain JSON-serializable
# value -- never prints, never calls sys.exit. Formatting/printing for the
# CLI and status-code selection for the dashboard both stay in their own
# callers. Invalid stage/status values raise ValueError (mirroring
# DVHarness.set_stage's own message); a REDIRECT refused by an active
# cross-stage TAKEOVER raises RuntimeError (DVHarness.human_redirect's own
# exception, unchanged) -- callers decide how to surface that (SystemExit(1)
# for the CLI, HTTP 400/409 for the dashboard).

_VALID_STAGES = {s.value for s in Stage}

# APPROVAL-ONLY stage keys: real, code-owned approval points that are
# deliberately NOT graph stages (2026-09-04).
#
# ControlPlane.approve()/get_approval() key on an arbitrary string -- only
# reviewer_confidence is validated there -- which is exactly why
# capability_evolution.py could reuse the real Human Approval Gate without a
# new graph node. But `dv-harness approve` was reachable only for a
# models.Stage member, on two independent chokepoints (this function, and
# cli.py's `choices=[s.value for s in Stage]`), so
# capability_evolution.human_approval_status()["approve_command"] and
# assert_human_approval()'s error message BOTH instructed a human to run a
# command argparse rejected before it ever reached ControlPlane -- an
# approval gate no human could actually operate. Verified by running it.
#
# Deliberately scoped to cmd_approve() alone via _check_approval_stage():
# `set-stage`/`redirect`/`correct`/`cosign` still accept graph stages ONLY,
# because those verbs drive the real engine loop and a non-graph value there
# would be a broken state, not an approval.
# Imported, never re-typed, so this set and the module that owns the key
# cannot drift apart.
from .capability_evolution import HUMAN_APPROVAL_STAGE as _RESEARCH_APPROVAL_STAGE

APPROVAL_ONLY_STAGES = frozenset({_RESEARCH_APPROVAL_STAGE})


def _check_stage(stage: str) -> None:
    if stage not in _VALID_STAGES:
        raise ValueError(f"Unknown stage: {stage}")


def approval_stage_choices() -> list:
    """Every stage key `dv-harness approve` accepts: the real graph stages
    plus APPROVAL_ONLY_STAGES. Used by cli.py so the parser and this module
    cannot disagree about what is approvable."""
    return [s.value for s in Stage] + sorted(APPROVAL_ONLY_STAGES)


def _check_approval_stage(stage: str) -> None:
    if stage not in _VALID_STAGES and stage not in APPROVAL_ONLY_STAGES:
        raise ValueError(f"Unknown stage: {stage}")


# ---- PAUSE / RESUME --------------------------------------------------------
def cmd_pause(h, reason: str = "") -> Dict[str, Any]:
    ControlPlane(h.root).pause(reason)
    h.store.event({"ts": cp_now(), "cmd": "pause", "reason": reason})
    return {"paused": True, "reason": reason}


def cmd_resume(h) -> Dict[str, Any]:
    ControlPlane(h.root).resume()
    h.store.event({"ts": cp_now(), "cmd": "resume"})
    return {"resumed": True}


# ---- TAKEOVER / RELEASE_TAKEOVER ------------------------------------------
def cmd_takeover(h, message: str = "") -> Dict[str, Any]:
    # NOTE/TODO (2026-08-29, graph-level parallel fan-out/join impact
    # analysis): this command has no stage argument, so it always targets
    # current_stage -- during a live fan-out that's the source node, never
    # one of the concurrently-running branches by name. Confirmed harmless
    # for TAKEOVER specifically: run_stage()'s own TAKEOVER check halts on
    # tk.get("active") alone regardless of which stage name it names, so
    # every concurrent branch thread is still correctly halted. Still a
    # real, pre-existing gap worth closing separately: a human cannot target
    # one specific branch by name via this command today. Out of scope for
    # this pass -- do not add a stage argument here without a separate,
    # deliberate design pass.
    stage = h.state.current_stage
    ControlPlane(h.root).takeover(stage, message)
    h.store.event({"ts": cp_now(), "cmd": "takeover", "stage": stage, "message": message})
    return {"takeover": True, "stage": stage, "message": message}


def cmd_release_takeover(h) -> Dict[str, Any]:
    ControlPlane(h.root).release_takeover()
    h.store.event({"ts": cp_now(), "cmd": "release-takeover"})
    return {"released": True}


# ---- REDIRECT ---------------------------------------------------------------
def cmd_redirect(h, stage: str, reason: str = "") -> str:
    # h.human_redirect() is already the single implementation (it was never
    # duplicated inline in cli.py -- cli.py's `redirect` branch already just
    # calls it) -- this thin wrapper exists only so dashboard.py's dispatch
    # table can reach every verb through dv_harness.commands uniformly.
    # Raises ValueError (unknown stage) or RuntimeError (refused by an
    # active cross-stage TAKEOVER) exactly as h.human_redirect does.
    return h.human_redirect(stage, reason)


# ---- APPROVE ------------------------------------------------------------
def cmd_approve(h, stage: str, note: str = "", reviewer_id: Optional[str] = None,
                 reviewer_confidence: str = "HIGH") -> Dict[str, Any]:
    _check_approval_stage(stage)
    entry = ControlPlane(h.root).approve(stage, note, reviewer_id, reviewer_confidence)
    h.store.event({"ts": cp_now(), "cmd": "approve", "stage": stage,
                    "reviewer_id": entry["reviewer_id"], "reviewer_confidence": entry["reviewer_confidence"],
                    "note": note})
    return {"stage": stage, **entry}


# ---- CORRECT ------------------------------------------------------------
def cmd_correct(h, stage: str, note: str, reset_attempts: bool = False) -> Dict[str, Any]:
    _check_stage(stage)
    cp = ControlPlane(h.root)
    cp.set_correction(stage, note, reset_attempts)
    ss = h.state.stages[stage]
    if reset_attempts:
        ss["attempts"] = 0
    h.store.save(h.state)
    # REPLAN: a human CORRECT is by definition a revision of the plan for
    # this stage -- real reason (the human's note) and real evidence (this
    # stage's actual blocking_reason/attempts), not a placeholder.
    replan_stage(h.root, stage, reason=note,
                 evidence={"stage": stage, "blocking_reason": ss.get("blocking_reason", ""),
                           "attempts": ss.get("attempts")})
    h.store.event({"ts": cp_now(), "cmd": "correct", "stage": stage,
                    "note": note, "reset_attempts": reset_attempts})
    return {"corrected": stage}


# ---- BLACKBOARD -----------------------------------------------------------
def cmd_blackboard_write(h, topic: str, value: Any, source: str = "", confidence: str = "HIGH") -> Dict[str, Any]:
    """Real, CLI-reachable wrapper around Blackboard.write() (dv_harness/
    blackboard.py). Exists specifically so a Workflow-tool script -- plain JS
    with no filesystem/Python access of its own (see workflow-authoring) --
    can have one of its subagents perform a genuine Blackboard write via a
    real PowerShell/Bash tool call (`dv-harness blackboard write <topic>
    --file <json>`), rather than only returning fused evidence as workflow
    return-value text that never actually reaches
    `.dv-harness/blackboard/<topic>.json`. First real caller:
    `.claude/workflows/rca-multi-agent-fusion.js`'s Evidence Fusion stage,
    writing the `rca_evidence_fusion` topic.

    RULING (2026-09-01, multi-agent-rca-orchestrator-implementation task): a
    non-empty topic string is required -- Blackboard._path() would otherwise
    happily write to a nonsensically-named file; every other validation
    (value shape) is left to the caller/agent, matching this module's
    existing lightweight `_check_stage`-style validation rather than
    borrowing the heavier typed-ValueError+evidence-dict convention from
    dv_harness/uvm_generator/generator.py, which is specific to that
    module's manifest-driven content-generation provenance rules, not to
    every state-mutating CLI command in this file (cmd_correct/cmd_approve
    above raise the same plain ValueError shape)."""
    if not topic or not topic.strip():
        raise ValueError("blackboard topic must be a non-empty string")
    payload = h.blackboard.write(topic, value, source=source, confidence=confidence)
    h.store.event({"ts": cp_now(), "cmd": "blackboard-write", "topic": topic,
                    "source": source, "confidence": confidence})
    return payload


def cmd_blackboard_read(h, topic: str) -> Any:
    """Real, CLI-reachable wrapper around Blackboard.read() -- lets a
    Workflow-tool subagent (e.g. the RCA Review stage in
    rca-multi-agent-fusion.js) independently re-read what the Evidence
    Fusion stage actually persisted, instead of trusting its own in-memory
    return value blindly (CLAUDE.md: current evidence wins)."""
    if not topic or not topic.strip():
        raise ValueError("blackboard topic must be a non-empty string")
    return h.blackboard.read(topic)


# ---- CONSTRAINT -----------------------------------------------------------
def cmd_constraint_add(h, text: str) -> Dict[str, Any]:
    entry = ControlPlane(h.root).add_constraint(text)
    h.store.event({"ts": cp_now(), "cmd": "constraint", "action": "add", "constraint": entry})
    return entry


def cmd_constraint_remove(h, constraint_id: str) -> bool:
    removed = ControlPlane(h.root).remove_constraint(constraint_id)
    h.store.event({"ts": cp_now(), "cmd": "constraint", "action": "remove",
                    "constraint_id": constraint_id, "removed": removed})
    return removed


def cmd_constraint_list(h):
    return ControlPlane(h.root).list_constraints()


# ---- COSIGN ---------------------------------------------------------------
def cmd_cosign(h, stage: str, field_path: str, value: Any, reviewer_id: Optional[str] = None,
                reviewer_confidence: str = "HIGH") -> Dict[str, Any]:
    # Durable, human-facing co-sign of a Tier-5 DV_JUDGMENT field (see
    # gates.JUDGMENT_FIELDS / gates._check_judgment_fields). Genuinely
    # gate-affecting: ControlPlane.add_cosign()'s record is consulted by
    # gates._check_judgment_fields on the NEXT evaluate_stage_evidence()
    # call for this stage, matched by exact (gate_id/loc, value) equality --
    # see that function's docstring for the exact matching semantics.
    _check_stage(stage)
    entry = ControlPlane(h.root).add_cosign(stage, field_path, value, reviewer_id, reviewer_confidence)
    h.store.event({"ts": cp_now(), "cmd": "cosign", "stage": stage, "field_path": field_path,
                    "reviewer_id": entry["reviewer_id"], "reviewer_confidence": entry["reviewer_confidence"]})
    return {"stage": stage, **entry}


# ---- Ungated admin/recovery verbs (mark / set-stage / advance) ------------
# All three move state without any gate ever running -- they cannot be
# removed (useful for recovery/admin), but must at minimum be audited like
# every other state-mutating command, and the fact that no gate ran must be
# visible on the resulting stage state (tagged "ungated": True), not
# indistinguishable from a real evidence-verified PASS.
def cmd_mark(h, status: str, message: str = "") -> Dict[str, Any]:
    # NOTE/TODO (2026-08-29, graph-level parallel fan-out/join impact
    # analysis): like cmd_takeover, this command has no stage argument and
    # always targets current_stage -- during a live fan-out a human cannot
    # `dv-harness mark <branch> PASS` to force one stuck branch through by
    # name (only the fan-out's parked source node is reachable this way).
    # Real, pre-existing gap (neither command ever had a stage argument);
    # out of scope for this pass -- do not add one here without a separate,
    # deliberate design pass.
    if status not in {s.value for s in Status}:
        raise ValueError(f"Unknown status: {status}")
    stage = h.state.current_stage
    h.mark(status, message)
    if status in (Status.PASS.value, Status.CLOSED.value):
        h.state.stages[stage]["ungated"] = True
        h.store.save(h.state)
    h.store.event({"ts": cp_now(), "cmd": "mark", "stage": stage,
                    "ungated": True, "status": status, "message": message})
    return {"stage": stage, "status": status}


def cmd_set_stage(h, stage: str) -> Dict[str, Any]:
    from_stage = h.state.current_stage
    # Low-priority/cosmetic gap noted 2026-08-29 active_stages audit: this
    # still only logs the single from_stage, not which branches (if any)
    # were concurrently active at the time -- from_stage itself is correct
    # (set-stage/advance both operate on current_stage by design, matching
    # engine.py), so the trivial addition here is audit-trail context only:
    # also record active_stages_before so a human reading events.jsonl can
    # tell a mid-fan-out set-stage/advance apart from an idle one.
    active_before = list(h.state.active_stages)
    h.set_stage(stage)  # raises ValueError on an unknown stage
    h.store.event({"ts": cp_now(), "cmd": "set-stage", "ungated": True,
                    "from_stage": from_stage, "to_stage": stage,
                    "active_stages_before": active_before})
    return {"stage": stage}


def cmd_advance(h) -> Dict[str, Any]:
    from_stage = h.state.current_stage
    active_before = list(h.state.active_stages)
    n = h.advance()
    h.store.event({"ts": cp_now(), "cmd": "advance", "ungated": True,
                    "from_stage": from_stage, "to_stage": n,
                    "active_stages_before": active_before})
    return {"to_stage": n}


# ---- research front door (master prompt sections 19 / 53) -------------------
# `.claude/commands/` does not exist in this repository and nothing here has
# ever used Claude Code's slash-command convention, so section 19's own
# fallback applies verbatim: "If project command conventions differ, implement
# equivalent behavior using the repository's native mechanism rather than
# forcing this exact syntax." This repo's native front-door mechanism is the
# `dv-harness <verb>` CLI, and this function is that verb's whole
# implementation.
#
# Section 19: "Do NOT place core logic in the command itself. The command is
# only an entry point into installed Skill/Agent orchestration." Held
# literally -- everything below builds an evidence dict and hands it to
# router.resolve_research_intent()/research_route_plan(). This function does
# not read a document, does not build a card, does not score a candidate, and
# does not approve anything. It ROUTES, and the route it returns names the
# real installed assets that do those things.
#
# What it deliberately does NOT do is claim to have RUN the pipeline. A CLI
# process cannot invoke a Claude Skill or Agent; the honest deliverable of a
# front door in this harness is the resolved intent plus the ordered plan an
# agent or human then follows. Saying otherwise would be the "prose describing
# a mechanism nobody executes" failure CLAUDE.md's Methodology Consolidation
# Rule names.
_RESEARCH_FLAG_INTENTS = (
    ("compare", "RESEARCH_COMPARE"),      # section 53: /research --compare
    ("impact", "RESEARCH_ARCHITECTURE_IMPACT"),   # section 53: --impact
    ("deep", "RESEARCH_DEEP_ANALYSIS"),   # section 53: --deep
)


def cmd_research(h, documents=None, compare: bool = False, impact: bool = False,
                 deep: bool = False, focus: Optional[str] = None,
                 request: str = "") -> Dict[str, Any]:
    """`dv-harness research` -- section 19's `/research` front door.

    Intent selection, in this order:
      1. an explicit mode flag (--compare/--impact/--deep), section 53's own
         semantics. More than one is a ValueError rather than a silent
         precedence rule the user cannot see.
      2. more than one document -> RESEARCH_MULTI_DOCUMENT (section 52's
         multi-paper request: one independent card per paper first).
      3. a free-text --request, classified by the SAME
         router.resolve_research_intent() a natural-language request reaching
         the harness any other way goes through -- not a second classifier.
      4. otherwise RESEARCH_ANALYSIS (section 53: "/research <file> = standard
         one-paper research analysis").

    Raises ValueError on conflicting flags, an unknown --focus, or a
    --request that does not read as a research request at all. Never prints;
    the CLI formats.
    """
    from .router import resolve_research_intent, research_route_plan

    docs = [str(d) for d in (documents or [])]
    flags = {"compare": bool(compare), "impact": bool(impact), "deep": bool(deep)}
    chosen = [intent for flag, intent in _RESEARCH_FLAG_INTENTS if flags[flag]]
    if len(chosen) > 1:
        raise ValueError(
            "Choose at most one of --compare / --impact / --deep "
            f"(got {chosen}); master prompt section 53 gives each its own "
            "distinct semantics.")

    if chosen:
        evidence = {"research_intent": chosen[0]}
    elif len(docs) > 1:
        evidence = {"research_intent": "RESEARCH_MULTI_DOCUMENT"}
    elif request.strip():
        evidence = {"protocol_hint": request}
    else:
        evidence = {"research_intent": "RESEARCH_ANALYSIS"}

    decision = resolve_research_intent(evidence)
    if not decision.get("resolved"):
        raise ValueError(
            "Not recognized as a research request: "
            f"{decision.get('evidence')}. Supply a document argument, or one "
            "of --compare/--impact/--deep, to state the intent explicitly.")

    plan = research_route_plan(decision, root=h.root, focus=focus,
                               documents=docs)
    h.store.event({"ts": cp_now(), "cmd": "research", "ungated": True,
                   "intent": plan["intent"], "focus": plan["focus"],
                   "documents": plan["documents"],
                   "route": plan["route"], "agent": plan["agent"],
                   "steps": [s["step"] for s in plan["steps"]]})
    return plan
