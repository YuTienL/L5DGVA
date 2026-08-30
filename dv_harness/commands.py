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


def _check_stage(stage: str) -> None:
    if stage not in _VALID_STAGES:
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
    _check_stage(stage)
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
