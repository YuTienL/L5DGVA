from __future__ import annotations
import json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from .storage import _atomic_replace

# Real, minimal Human Control Plane -----------------------------------------
#
# Prior to this module, the 12-verb "Human Control Plane" documented for this
# harness was mostly aspirational: STATUS was real; WHY/REVIEW existed in
# weaker forms; REPLAN existed but was never called; EVIDENCE, APPROVE,
# REDIRECT, PAUSE, RESUME, TAKEOVER, CORRECT, CONSTRAINT had no executable
# form at all -- no CLI subcommand, no engine.py check, nothing a human could
# actually do that the running pipeline would notice.
#
# This module is the single persisted state file (.dv-harness/control.json)
# that closes that gap: dv_harness/cli.py's new subcommands WRITE to it,
# dv_harness/engine.py's loop()/run_stage() READ and RESPECT it every
# iteration/call, and dv_harness/prompts.py folds the human-facing fields
# (constraints, correction notes, approvals) into the next stage prompt so
# the agent actually sees them. Nothing here is a parallel bookkeeping
# system a human edits and the harness ignores.
#
# Human Override principle (CLAUDE.md: "Human Override is always valid"):
# TAKEOVER is the strongest override -- engine.py checks it first, in both
# loop() (every iteration, before run_stage() is even called) and inside
# run_stage() itself (so a direct `dv-harness run-stage` bypass of the loop
# still can't quietly run an LLM turn against a stage a human is holding).
# PAUSE is checked immediately after, in loop() only (a single manual
# run-stage call while paused is a deliberate, explicit human action, not the
# thing PAUSE exists to stop -- PAUSE stops the *autonomous* loop).

CONTROL_VERSION = 1

DEFAULT_TAKEOVER = {
    "active": False,
    "stage": None,
    "message": "",
    "taken_at": None,
    "taken_by": None,
}

DEFAULT_CONTROL = {
    "version": CONTROL_VERSION,
    "paused": False,
    "paused_reason": "",
    "paused_at": None,
    "takeover": dict(DEFAULT_TAKEOVER),
    "constraints": [],   # [{"id","text","added_at","added_by"}]
    "corrections": {},   # stage -> {"note","at","reset_attempts","consumed","corrected_by"}
    "approvals": {},     # stage -> {"note","reviewer_id","reviewer_confidence","approved_at"}
    "approval_history": {},  # stage -> [archived approvals, oldest first, each tagged "outcome"]
    "cosigns": {},       # stage -> {"<gate_id>/<loc>": {"value","reviewer_id","reviewer_confidence","cosigned_at","cosigned_by"}}
    "next_constraint_seq": 1,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_user() -> str:
    return os.environ.get("USER") or os.environ.get("USERNAME") or "human"


class ControlPlane:
    """Read/write access to .dv-harness/control.json -- the persisted
    Human Control Plane state. Every mutating method loads, mutates, and
    atomically saves; there is no long-lived in-memory state to go stale,
    since engine.py re-loads it at the top of every loop() iteration and at
    the top of every run_stage() call."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir = self.root / ".dv-harness"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "control.json"

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            data = json.loads(json.dumps(DEFAULT_CONTROL))
            self._write(data)
            return data
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        # Forward-fill any keys missing from an older control.json (e.g. a
        # file written by an earlier version of this module) rather than
        # erroring or silently dropping fields the caller expects.
        merged = json.loads(json.dumps(DEFAULT_CONTROL))
        merged.update(data)
        if not isinstance(merged.get("takeover"), dict):
            merged["takeover"] = dict(DEFAULT_TAKEOVER)
        else:
            tk = dict(DEFAULT_TAKEOVER)
            tk.update(merged["takeover"])
            merged["takeover"] = tk
        return merged

    def _write(self, data: Dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(prefix="control.", suffix=".json", dir=str(self.dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # See storage._atomic_replace's docstring -- same Windows
            # concurrent-reader-vs-os.replace race, now reachable here too
            # since dashboard.py's POST /api/control handlers run on
            # ThreadingHTTPServer's per-request threads and every command
            # does its own load()-then-save() round trip against this same
            # control.json.
            _atomic_replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def save(self, data: Dict[str, Any]) -> None:
        self._write(data)

    # ---- PAUSE / RESUME ----------------------------------------------
    def pause(self, reason: str = "") -> Dict[str, Any]:
        data = self.load()
        data["paused"] = True
        data["paused_reason"] = reason
        data["paused_at"] = now()
        self.save(data)
        return data

    def resume(self) -> Dict[str, Any]:
        data = self.load()
        data["paused"] = False
        data["paused_reason"] = ""
        data["paused_at"] = None
        self.save(data)
        return data

    def is_paused(self) -> bool:
        return bool(self.load().get("paused"))

    # ---- TAKEOVER -------------------------------------------------------
    def takeover(self, stage: str, message: str = "", taken_by: Optional[str] = None) -> Dict[str, Any]:
        data = self.load()
        data["takeover"] = {
            "active": True,
            "stage": stage,
            "message": message,
            "taken_at": now(),
            "taken_by": taken_by or _default_user(),
        }
        self.save(data)
        return data["takeover"]

    def release_takeover(self) -> Dict[str, Any]:
        data = self.load()
        data["takeover"] = dict(DEFAULT_TAKEOVER)
        self.save(data)
        return data["takeover"]

    def takeover_status(self) -> Dict[str, Any]:
        return self.load().get("takeover", dict(DEFAULT_TAKEOVER))

    def is_takeover_active_for(self, stage: str) -> bool:
        tk = self.takeover_status()
        return bool(tk.get("active")) and tk.get("stage") == stage

    # ---- CONSTRAINT -------------------------------------------------
    def add_constraint(self, text: str, added_by: Optional[str] = None) -> Dict[str, Any]:
        data = self.load()
        seq = data.get("next_constraint_seq", 1)
        entry = {
            "id": f"CN{seq}", "text": text,
            "added_at": now(), "added_by": added_by or _default_user(),
        }
        data.setdefault("constraints", []).append(entry)
        data["next_constraint_seq"] = seq + 1
        self.save(data)
        return entry

    def list_constraints(self) -> List[Dict[str, Any]]:
        return self.load().get("constraints", [])

    def remove_constraint(self, constraint_id: str) -> bool:
        data = self.load()
        before = data.get("constraints", [])
        after = [c for c in before if c.get("id") != constraint_id]
        data["constraints"] = after
        self.save(data)
        return len(after) != len(before)

    # ---- CORRECT ------------------------------------------------------
    def set_correction(self, stage: str, note: str, reset_attempts: bool = False,
                        corrected_by: Optional[str] = None) -> Dict[str, Any]:
        data = self.load()
        entry = {
            "note": note, "at": now(), "reset_attempts": bool(reset_attempts),
            "consumed": False, "corrected_by": corrected_by or _default_user(),
        }
        data.setdefault("corrections", {})[stage] = entry
        self.save(data)
        return entry

    def get_active_correction(self, stage: str) -> Optional[Dict[str, Any]]:
        entry = self.load().get("corrections", {}).get(stage)
        if entry and not entry.get("consumed"):
            return entry
        return None

    def consume_correction(self, stage: str) -> None:
        data = self.load()
        entry = data.get("corrections", {}).get(stage)
        if entry and not entry.get("consumed"):
            entry["consumed"] = True
            self.save(data)

    # ---- APPROVE --------------------------------------------------------
    def _archive_approval(self, data: Dict[str, Any], stage: str, outcome: str) -> None:
        """Move the CURRENT active approval for `stage` (if any) into a
        permanent, append-only approval_history list before it is replaced
        or consumed. Regression for the multi-persona interaction review
        (2026-08-28): DE Manager and DV Manager independently found approve()
        silently overwrote a prior reviewer's record with setdefault(...)[stage]=,
        and DV Manager independently found clear_approval() (added earlier
        this session to make APPROVE single-use) then deleted that record
        outright -- "the one human-authored SIGNOFF record vanishes with no
        trace anywhere on disk." Neither replacement nor consumption may ever
        again destroy the record without a permanent trace."""
        prior = data.get("approvals", {}).get(stage)
        if prior is None:
            return
        archived = dict(prior)
        archived["outcome"] = outcome
        archived["outcome_at"] = now()
        data.setdefault("approval_history", {}).setdefault(stage, []).append(archived)

    def approve(self, stage: str, note: str = "", reviewer_id: Optional[str] = None,
                reviewer_confidence: str = "HIGH") -> Dict[str, Any]:
        # BUG FIX (2026-08-28, GUI/CLI end-to-end confirmation audit): the
        # CLI's argparse choices=["HIGH","MEDIUM","LOW"] was the ONLY thing
        # rejecting an invalid reviewer_confidence -- dashboard.py's HTTP
        # path had no equivalent check and would silently persist e.g.
        # "SUPER_SURE" into control.json, corrupting a value gates.py's
        # Tier-5 DV-review co-sign mechanism (REVIEWER_CONFIDENCE_LEVELS)
        # assumes is always one of the three real levels. Validating here,
        # in the one method every caller (CLI and HTTP) goes through,
        # protects both regardless of caller.
        from .gates import REVIEWER_CONFIDENCE_LEVELS
        if reviewer_confidence not in REVIEWER_CONFIDENCE_LEVELS:
            raise ValueError(f"invalid reviewer_confidence: {reviewer_confidence!r} "
                              f"(must be one of {REVIEWER_CONFIDENCE_LEVELS})")
        data = self.load()
        self._archive_approval(data, stage, "OVERWRITTEN_BY_NEW_APPROVAL")
        entry = {
            "note": note,
            "reviewer_id": reviewer_id or _default_user(),
            "reviewer_confidence": reviewer_confidence,
            "approved_at": now(),
        }
        data.setdefault("approvals", {})[stage] = entry
        self.save(data)
        return entry

    def get_approval(self, stage: str) -> Optional[Dict[str, Any]]:
        return self.load().get("approvals", {}).get(stage)

    def get_approval_history(self, stage: str) -> List[Dict[str, Any]]:
        """Every approval this stage has ever had, in the order it stopped
        being the active one (overwritten by a fresh APPROVE, or consumed by
        the PASS it authorized) -- the permanent audit trail get_approval()
        alone cannot provide once an approval is no longer current."""
        return self.load().get("approval_history", {}).get(stage, [])

    def clear_approval(self, stage: str) -> None:
        data = self.load()
        if stage in data.get("approvals", {}):
            self._archive_approval(data, stage, "CONSUMED_BY_PASS")
            del data["approvals"][stage]
            self.save(data)

    # ---- COSIGN -----------------------------------------------------------
    # Real, durable, out-of-band satisfaction of gates.py's Tier-5
    # JUDGMENT_FIELDS wrapper requirement (2026-08-28 GUI/CLI gap-closure
    # pass). Before this, the ONLY way to satisfy a {"value","reviewer_id",
    # "reviewer_confidence"} wrapper was for the AGENT to emit it inline in
    # its next evidence block -- there was no human-facing action to
    # directly co-sign a pending judgment field. add_cosign() persists a
    # record keyed by (stage, "<gate_id>/<loc>") that gates._check_judgment_fields
    # (see its docstring) actually consults on the NEXT evaluate_stage_evidence()
    # call for that stage: an unwrapped field whose bare value EXACTLY
    # matches a stored cosign's "value" is accepted without an inline
    # wrapper. Matching is intentionally exact-value, not just
    # exact-location -- a value that later changes at the same location is
    # NOT covered by a stale cosign; a fresh one (or an inline wrapper) is
    # required again. This is a genuine gate-affecting mechanism, not merely
    # a visibility/logging record -- see gates.py's Tier-5 section and
    # commands.cmd_cosign for the full path.
    def add_cosign(self, stage: str, field_path: str, value: Any, reviewer_id: Optional[str] = None,
                    reviewer_confidence: str = "HIGH", cosigned_by: Optional[str] = None) -> Dict[str, Any]:
        from .gates import REVIEWER_CONFIDENCE_LEVELS  # see approve()'s identical lazy-import note
        if reviewer_confidence not in REVIEWER_CONFIDENCE_LEVELS:
            raise ValueError(f"invalid reviewer_confidence: {reviewer_confidence!r} "
                              f"(must be one of {REVIEWER_CONFIDENCE_LEVELS})")
        if not reviewer_id or not str(reviewer_id).strip():
            raise ValueError("reviewer_id is required for a co-sign")
        if not field_path or not str(field_path).strip():
            raise ValueError("field_path is required for a co-sign")
        data = self.load()
        entry = {
            "field_path": field_path,
            "value": value,
            "reviewer_id": reviewer_id,
            "reviewer_confidence": reviewer_confidence,
            "cosigned_at": now(),
            "cosigned_by": cosigned_by or _default_user(),
        }
        data.setdefault("cosigns", {}).setdefault(stage, {})[field_path] = entry
        self.save(data)
        return entry

    def get_cosign(self, stage: str, field_path: str) -> Optional[Dict[str, Any]]:
        return self.load().get("cosigns", {}).get(stage, {}).get(field_path)

    def list_cosigns(self, stage: Optional[str] = None) -> Dict[str, Any]:
        """All cosign records for `stage` ({field_path: entry}), or the
        whole stage->{field_path: entry} map when stage is None."""
        data = self.load().get("cosigns", {})
        return data.get(stage, {}) if stage else data


# ---- WHY / EVIDENCE shared read path ---------------------------------------
def describe_stage(root: Path, state, stage: str) -> Dict[str, Any]:
    """The real, current-run answer to both WHY and EVIDENCE: this stage's
    actual blocking_reason, the evidence blocks its last response actually
    contained, and the gate verdict/reasons evaluate_stage_evidence derives
    from that same text -- as opposed to prompts.STAGE_DE_EXPLAINER's static,
    generic per-stage description (which cli.py's `explain` still prints
    first, unchanged, for backward compatibility)."""
    from .gates import extract_evidence_blocks, evaluate_stage_evidence

    root = Path(root)
    ss = (state.stages or {}).get(stage, {}) if hasattr(state, "stages") else (state.get("stages", {}).get(stage, {}))
    last_message = ss.get("last_message", "") or ""
    verdict, reasons = evaluate_stage_evidence(root, stage, last_message)
    cp = ControlPlane(root).load()
    return {
        "stage": stage,
        "status": ss.get("status"),
        "attempts": ss.get("attempts"),
        "blocking_reason": ss.get("blocking_reason", ""),
        "gate_verdict": verdict,
        "gate_reasons": reasons,
        "evidence_blocks": extract_evidence_blocks(last_message),
        "human_correction": cp.get("corrections", {}).get(stage),
        "human_approval": cp.get("approvals", {}).get(stage),
        "takeover": cp.get("takeover") if cp.get("takeover", {}).get("stage") == stage else None,
    }


def describe_stages(root: Path, state, stages: List[str]) -> Dict[str, Dict[str, Any]]:
    """Batch form of describe_stage() for a live parallel fan-out, where more
    than one stage is concurrently active (state.active_stages) and the
    single-stage signature above would only show one branch. Existing
    single-stage callers are unaffected -- this loops calling describe_stage()
    per stage rather than changing its signature. Returns {stage: describe_stage(...)}
    keyed by stage id so callers (cli.py's explain/evidence with no --stage
    given during a fan-out) can print/serialize one block per active branch."""
    return {s: describe_stage(root, state, s) for s in stages}


# ---- REPLAN real call site --------------------------------------------------
def _find_latest_plan(plans_dir: Path, node_id: str) -> Optional[Dict[str, Any]]:
    if not plans_dir.exists():
        return None
    candidates = []
    for f in plans_dir.glob("PLAN-*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("node_id") == node_id:
            candidates.append((f.stat().st_mtime, data))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return candidates[-1][1]


def replan_stage(root: Path, stage: str, reason: str, evidence: Dict[str, Any],
                  new_steps: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The real call site for planner.PlanStore.replan(), previously
    orphaned (never invoked by any executing code path). Called from two
    places: dv_harness.cli's `correct` subcommand (a human providing a
    correction is, by definition, revising the plan for that stage) and
    engine.DVHarness.loop()'s retry-exhaustion branch (an automatic
    FAIL/PARTIAL routing decision is likewise a real replan event, with the
    stage's actual attempts/blocking_reason as evidence -- not a placeholder).
    Real reason/evidence in both cases: the human's --note text, or the
    stage's own recorded blocking_reason and attempt count.
    """
    from .planner import PlanStore

    root = Path(root)
    ps = PlanStore(root)
    existing = _find_latest_plan(ps.dir, stage)
    if existing is None:
        steps = new_steps or [{"step_id": "P01", "name": stage, "status": "NOT_STARTED"}]
        plan = ps.create(stage, reason, steps)
        # create() already persisted revision 1; replan on top of it so the
        # reason/evidence for *this* correction is recorded in replans.jsonl
        # too, not silently absorbed into the initial creation.
        plan = ps.replan(plan, reason, evidence, new_steps or steps)
    else:
        plan = ps.replan(existing, reason, evidence, new_steps or existing.get("steps", []))
    return plan
