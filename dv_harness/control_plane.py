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
    "suspicious_flags": {},  # stage -> {"<target>": {"target","reason","severity","status","flagged_by","flagged_at","resolved_by","resolved_at","resolution_note"}}
    "bundle_reviews": {},  # stage -> {"<bundle_hash>": [{"bundle_hash","reviewer_id","note","reviewer_confidence","reviewed_at","reviewed_by"}, ...]} -- see ControlPlane.add_bundle_review()
    "next_constraint_seq": 1,
}

# ---- FLAG_SUSPICIOUS vocabulary --------------------------------------------
# See ControlPlane.flag_suspicious()'s docstring for what this verb is and,
# just as importantly, what it deliberately is NOT (it is neither CORRECT nor
# COSIGN). Kept as real, checked constants -- not free-text -- the same
# discipline REVIEWER_CONFIDENCE_LEVELS already applies to approve()/
# add_cosign()'s own reviewer_confidence field.
SUSPICION_SEVERITY_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
SUSPICION_STATUS_OPEN = "OPEN"
SUSPICION_STATUS_RESOLVED = "RESOLVED"
SUSPICION_STATUSES = (SUSPICION_STATUS_OPEN, SUSPICION_STATUS_RESOLVED)


class SecondReviewerRequiredError(ValueError):
    """Raised by `ControlPlane.assert_bundle_second_review_satisfied()` when
    no real, independent second reviewer is on file for a (stage,
    bundle_hash) pair -- see `add_bundle_review()`'s docstring for the real
    gap this closes (2026-09-07, item id
    "no-second-reviewer-mechanism-at-signoff-scope"). Carries the stage,
    bundle_hash and the intended approver so a caller can report exactly
    what is missing rather than a bare refusal."""

    def __init__(self, stage: str, bundle_hash: str, approver_id: Optional[str]):
        self.stage = stage
        self.bundle_hash = bundle_hash
        self.approver_id = approver_id
        super().__init__(
            f"stage {stage!r} bundle {bundle_hash!r} has no independent second "
            f"reviewer on file"
            + (f" (distinct from approver {approver_id!r})" if approver_id else "")
            + " -- call ControlPlane.add_bundle_review() with a real second "
              "human's reviewer_id before this bundle may be treated as "
              "dual-reviewed"
        )


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

    def clear_approval(self, stage: str, outcome: str = "CONSUMED_BY_PASS") -> None:
        """Retire the active approval for `stage`, archiving it first.

        `outcome` names WHY it stopped being active and defaults to the
        original single caller's reason (a PASS consumed it). A second real
        reason exists since 2026-09-05: commands.cmd_research_hold() withdraws
        the RESEARCH_CAPABILITY_EVOLUTION approval as WITHDRAWN_BY_HUMAN_HOLD.
        The two must stay distinguishable in approval_history -- "a human took
        this authorization back" and "the stage it authorized passed" are
        different facts about the same record, and collapsing them into one
        label would make the audit trail say something untrue.
        """
        data = self.load()
        if stage in data.get("approvals", {}):
            self._archive_approval(data, stage, outcome)
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

    # ---- FLAG_SUSPICIOUS ----------------------------------------------------
    # A real gap this closes (2026-09-07): before this, a reviewer had no way
    # to mark ONE specific already-produced gate result or evidence citation
    # as suspicious/needing re-verification. The only two nearby mechanisms
    # both answer a different question:
    #   - CORRECT (set_correction() above) resets the WHOLE STAGE -- a human
    #     telling the harness "redo this stage's work", consuming attempts
    #     and triggering a replan. It cannot target one gate result inside an
    #     otherwise-fine stage without discarding everything else.
    #   - COSIGN (add_cosign() above) is AGREEMENT: a reviewer accepting a
    #     PENDING judgment value so gates._check_judgment_fields will accept
    #     it, and it is opt-in and scoped ONLY to gates.JUDGMENT_FIELDS
    #     (Tier-5 DV_JUDGMENT fields). It has no way to express the opposite
    #     stance (doubt), and no way to target a non-judgment-field citation
    #     (e.g. a specific evidence artifact path, or an already-PASSed gate
    #     whose result a human now suspects).
    # flag_suspicious() is neither: it is a durable, out-of-band DOUBT record
    # against one named `target` -- resets nothing, requires no agreement
    # value, and is not restricted to JUDGMENT_FIELDS. `target` is a free
    # string the caller chooses to identify what is being doubted; two
    # conventions already exist elsewhere in this codebase and are safe to
    # reuse here: add_cosign()'s own "<gate_id>/<loc>" shape for one judgment
    # field, or evidence_provenance.suspicion_target_for_gate(gate_id) (that
    # module's own "gate:<gate_id>" convention) for a whole gate result --
    # see that module for how a flag against one of its six dynamic-behaviour
    # gates is surfaced next to that gate's own provenance caveat. Any other
    # citation string (an evidence artifact path, a doc section) is equally
    # valid; this method does not interpret `target`, only stores it.
    def flag_suspicious(self, stage: str, target: str, reason: str,
                         flagged_by: Optional[str] = None, severity: str = "MEDIUM",
                         context: Optional[str] = None) -> Dict[str, Any]:
        if not target or not str(target).strip():
            raise ValueError("target is required to flag something suspicious")
        if not reason or not str(reason).strip():
            raise ValueError("reason is required to flag something suspicious")
        if not flagged_by or not str(flagged_by).strip():
            raise ValueError("flagged_by is required to flag something suspicious")
        if severity not in SUSPICION_SEVERITY_LEVELS:
            raise ValueError(f"invalid severity: {severity!r} "
                              f"(must be one of {SUSPICION_SEVERITY_LEVELS})")
        data = self.load()
        entry = {
            "target": target,
            "reason": reason,
            "severity": severity,
            "context": context,
            "status": SUSPICION_STATUS_OPEN,
            "flagged_by": flagged_by,
            "flagged_at": now(),
            "resolved_by": None,
            "resolved_at": None,
            "resolution_note": None,
        }
        data.setdefault("suspicious_flags", {}).setdefault(stage, {})[target] = entry
        self.save(data)
        return entry

    def get_suspicious_flag(self, stage: str, target: str) -> Optional[Dict[str, Any]]:
        return self.load().get("suspicious_flags", {}).get(stage, {}).get(target)

    def list_suspicious_flags(self, stage: Optional[str] = None,
                               open_only: bool = False) -> Dict[str, Any]:
        """All suspicion-flag records for `stage` ({target: entry}), or the
        whole stage->{target: entry} map when stage is None. `open_only`
        filters out RESOLVED entries at every level, mirroring
        get_active_correction()'s "consumed" filter above."""
        data = self.load().get("suspicious_flags", {})
        scoped = data.get(stage, {}) if stage else data
        if not open_only:
            return scoped
        if stage:
            return {k: v for k, v in scoped.items() if v.get("status") == SUSPICION_STATUS_OPEN}
        return {s: {k: v for k, v in flags.items() if v.get("status") == SUSPICION_STATUS_OPEN}
                for s, flags in scoped.items()}

    def resolve_suspicious_flag(self, stage: str, target: str, resolution_note: str,
                                 resolved_by: Optional[str] = None) -> Dict[str, Any]:
        """Mark a suspicion flag RESOLVED. Never deletes the record -- like
        the approval/correction history elsewhere in this file, a flag that
        was raised and then resolved must stay on the audit trail rather than
        vanish, so `list_suspicious_flags(open_only=False)` can still show it
        was raised and how it was resolved."""
        if not resolution_note or not str(resolution_note).strip():
            raise ValueError("resolution_note is required to resolve a suspicion flag")
        data = self.load()
        entry = data.get("suspicious_flags", {}).get(stage, {}).get(target)
        if entry is None:
            raise ValueError(f"no suspicion flag on file for stage={stage!r} target={target!r}")
        entry["status"] = SUSPICION_STATUS_RESOLVED
        entry["resolved_by"] = resolved_by or _default_user()
        entry["resolved_at"] = now()
        entry["resolution_note"] = resolution_note
        self.save(data)
        return entry

    # ---- SIGNOFF BUNDLE SECOND REVIEW ----------------------------------
    # Real gap this closes (2026-09-07, item id
    # "no-second-reviewer-mechanism-at-signoff-scope"): `approvals` above
    # holds exactly ONE reviewer entry per stage -- a fresh approve() call
    # OVERWRITES it (archived into approval_history via _archive_approval(),
    # never lost, but never CONCURRENT either: two reviewers cannot both
    # have a live record for one stage at once). add_cosign() is opt-in
    # AGREEMENT with a single PENDING gates.JUDGMENT_FIELDS value inside
    # one stage's evidence block -- a narrow, per-field mechanism, not a
    # whole-bundle review. question_queue.QuestionQueueStore.
    # add_decision_cosign() is the nearest-looking real mechanism and was
    # deliberately NOT extended or duplicated here (REUSE OVER REINVENT
    # was checked first): it co-signs one already-recorded Tier-3 INTAKE
    # DECISION, keyed on that decision's own exact answer TEXT -- a
    # different object entirely from a whole `signoff_export.py` evidence
    # BUNDLE, and that module's own store (decisions.json) has no bundle
    # concept at all. Neither existing mechanism covers "a second human
    # independently reviewed the WHOLE signoff evidence bundle before it
    # is approved".
    #
    # add_bundle_review() is that missing mechanism, modelled directly on
    # add_decision_cosign()'s own real, tested discipline (same reasoning,
    # a different store) rather than inventing a new one from scratch:
    # additive, never overwritten -- a real second (third, fourth, ...)
    # reviewer's record must never silently replace an earlier one, since
    # the whole point is that MORE THAN ONE human looked at the SAME
    # bundle; keyed to the EXACT content the review covers
    # (`signoff_export.compute_bundle_hash()`'s own real, content-derived
    # hash over the bundle's manifest -- reused, never invented here, and
    # never a bare bundle directory PATH, which says nothing about whether
    # the bundle's own CONTENT changed since a prior review, the same
    # exact-value discipline `ControlPlane.add_cosign()`'s own docstring
    # states: "a value that later changes ... is NOT covered by a stale
    # co-sign; a fresh one ... is required again"); and refuses to let the
    # SAME person be their own second reviewer -- a co-sign is a second,
    # INDEPENDENT review, not the same person re-affirming their own look,
    # exactly the check `add_decision_cosign()` already makes for a Tier-3
    # decision.
    #
    # This module intentionally makes NO call site out of
    # `assert_bundle_second_review_satisfied()` (approve() itself is
    # untouched, so every existing caller's behaviour is byte-identical) --
    # wiring a stage gate / CLI verb / dashboard action that actually
    # BLOCKS a SIGNOFF approval on it is future work outside control_plane.
    # py's own file scope (commands.py/cli.py/dashboard.py were not part
    # of this change), the same REACHED-vs-WIRED disclosure this project's
    # gui_action_safety.py already makes for FLAG_SUSPICIOUS the same day.
    def add_bundle_review(self, stage: str, bundle_hash: str, reviewer_id: str,
                           note: str = "", reviewer_confidence: str = "HIGH",
                           reviewed_by: Optional[str] = None) -> Dict[str, Any]:
        """Record ONE independent human reviewer's review of the signoff
        evidence bundle identified by `bundle_hash` for `stage`. Additive
        -- appended to `bundle_reviews[stage][bundle_hash]`, never
        overwriting an earlier reviewer's record the way `approve()`
        overwrites `approvals[stage]`. See this method's own governing
        comment above for the real gap this closes and why it is not a
        duplicate of `add_cosign()`/`add_decision_cosign()`."""
        from .gates import REVIEWER_CONFIDENCE_LEVELS  # see approve()'s identical lazy-import note
        if not stage or not str(stage).strip():
            raise ValueError("stage is required to record a bundle review")
        if not bundle_hash or not str(bundle_hash).strip():
            raise ValueError(
                "bundle_hash is required to record a bundle review -- use "
                "signoff_export.compute_bundle_hash() over the real bundle "
                "manifest; never invent one"
            )
        if not reviewer_id or not str(reviewer_id).strip():
            raise ValueError("reviewer_id is required to record a bundle review")
        if reviewer_confidence not in REVIEWER_CONFIDENCE_LEVELS:
            raise ValueError(f"invalid reviewer_confidence: {reviewer_confidence!r} "
                              f"(must be one of {REVIEWER_CONFIDENCE_LEVELS})")
        bundle_hash = str(bundle_hash).strip()
        data = self.load()
        entry = {
            "bundle_hash": bundle_hash,
            "reviewer_id": str(reviewer_id).strip(),
            "note": note,
            "reviewer_confidence": reviewer_confidence,
            "reviewed_at": now(),
            "reviewed_by": reviewed_by or reviewer_id,
        }
        (data.setdefault("bundle_reviews", {})
             .setdefault(stage, {})
             .setdefault(bundle_hash, [])
             .append(entry))
        self.save(data)
        return entry

    def get_bundle_reviews(self, stage: str, bundle_hash: str) -> List[Dict[str, Any]]:
        """Every review recorded for `(stage, bundle_hash)`, in the order
        recorded. Empty when nobody has reviewed this exact bundle content
        yet -- a bundle re-exported with different content gets a
        different `bundle_hash` and therefore an honestly EMPTY review
        list, never a stale reviewer list left over from a prior,
        different bundle."""
        return list(self.load().get("bundle_reviews", {})
                    .get(stage, {}).get(str(bundle_hash).strip(), []))

    def has_independent_bundle_review(self, stage: str, bundle_hash: str,
                                       approver_id: Optional[str] = None) -> bool:
        """True iff at least one recorded review of `(stage, bundle_hash)`
        was made by a reviewer whose id differs from `approver_id`
        (case/whitespace-insensitive, mirroring `add_decision_cosign()`'s
        own same-person check) -- a real second, INDEPENDENT human. With
        `approver_id=None` (caller has not named the intended approver
        yet), True iff at least one review exists at all."""
        reviews = self.get_bundle_reviews(stage, bundle_hash)
        if not reviews:
            return False
        if approver_id is None:
            return True
        approver_norm = str(approver_id).strip().casefold()
        return any(str(r.get("reviewer_id", "")).strip().casefold() != approver_norm
                   for r in reviews)

    def assert_bundle_second_review_satisfied(self, stage: str, bundle_hash: str,
                                               approver_id: Optional[str] = None) -> None:
        """Raise `SecondReviewerRequiredError` unless a real, independent
        second reviewer is on file for `(stage, bundle_hash)` -- the real
        enforcement point a caller (a stage gate, a CLI verb, a dashboard
        action -- none of which this module dispatches itself) uses to
        actually BLOCK an approval until this project's own dual-review
        requirement is genuinely met, rather than merely reportable via
        `has_independent_bundle_review()` alone."""
        if not self.has_independent_bundle_review(stage, bundle_hash, approver_id):
            raise SecondReviewerRequiredError(stage, bundle_hash, approver_id)


# ---- WHY / EVIDENCE shared read path ---------------------------------------
def _latest_stage_checklists(root: Path, stage: str) -> Dict[str, Optional[Dict[str, Any]]]:
    """The most recent .dv-harness/telemetry/stages/STAGE-*.json record's
    entry_checklist/exit_checklist for `stage` -- the same real,
    presence-checked reports engine.build_stage_entry_checklist()/
    build_stage_exit_checklist() computed and StageExecutionProfiler
    persisted (stage_profile.py), read back here rather than recomputed.

    Both keys are None when `stage` has no telemetry record at all (never
    run yet this project) -- distinct from a real record whose checklist is
    a zero-item dict (node declared no expected_evidence/expected_outputs;
    see _run_checklist()'s "zero items -> 100%, not an error" convention),
    which is forwarded as-is. StageExecutionProfiler.all_stages() already
    sorts oldest -> newest by start_time_epoch, so the last element is the
    most recent attempt."""
    from .stage_profile import StageExecutionProfiler
    records = [r for r in StageExecutionProfiler(root).all_stages() if r.get("stage_id") == stage]
    if not records:
        return {"entry_checklist": None, "exit_checklist": None}
    latest = records[-1]
    return {"entry_checklist": latest.get("entry_checklist"), "exit_checklist": latest.get("exit_checklist")}


def describe_stage(root: Path, state, stage: str) -> Dict[str, Any]:
    """The real, current-run answer to both WHY and EVIDENCE: this stage's
    actual blocking_reason, the evidence blocks its last response actually
    contained, and the gate verdict/reasons evaluate_stage_evidence derives
    from that same text -- as opposed to prompts.STAGE_DE_EXPLAINER's static,
    generic per-stage description (which cli.py's `explain` still prints
    first, unchanged, for backward compatibility).

    Also surfaces a stage-SCOPED completion fraction (gates_total,
    gates_passed, stage_completion_percent, stage_completion_note) derived
    from the same per-gate signatures gate_verdict/gate_reasons come from
    (gates.evaluate_stage_evidence_with_completion() -> gates.
    _evaluate_stage_evidence_core()). This is distinct from dashboard.py's
    GET /api/state overall_progress_percent, which is a whole-RUN percentage
    (fraction of all Stage enum values at PASS/CLOSED) and was, before this,
    the only numeric completion signal exposed anywhere -- never scoped to
    the one stage actually in progress, and never exposed via the CLI.

    Also surfaces entry_checklist/exit_checklist (2026-09-01, runtime-
    progress-visibility pass): the same per-item presence report
    engine.build_stage_entry_checklist()/build_stage_exit_checklist()
    computed for this stage's most recent attempt and StageExecutionProfiler
    persisted into telemetry -- previously readable only by opening the raw
    .dv-harness/telemetry/stages/STAGE-*.json file by hand, now surfaced
    through this SAME shared read path dashboard.py's GET /api/state
    (current_stage_detail/active_stages_detail) and cli.py's explain/
    evidence/checklist all already go through, so both UIs render it
    identically and neither has to re-read telemetry itself."""
    from .gates import extract_evidence_blocks, evaluate_stage_evidence_with_completion
    from .evidence_provenance import summarize_evidence_blocks

    root = Path(root)
    ss = (state.stages or {}).get(stage, {}) if hasattr(state, "stages") else (state.get("stages", {}).get(stage, {}))
    last_message = ss.get("last_message", "") or ""
    verdict, reasons, completion = evaluate_stage_evidence_with_completion(root, stage, last_message)
    cp = ControlPlane(root).load()
    checklists = _latest_stage_checklists(root, stage)
    evidence_blocks = extract_evidence_blocks(last_message)
    return {
        "stage": stage,
        "status": ss.get("status"),
        "attempts": ss.get("attempts"),
        "blocking_reason": ss.get("blocking_reason", ""),
        "gate_verdict": verdict,
        "gate_reasons": reasons,
        "gates_total": completion["gates_total"],
        "gates_passed": completion["gates_passed"],
        "stage_completion_percent": completion["stage_completion_percent"],
        "stage_completion_note": completion["stage_completion_note"],
        "entry_checklist": checklists["entry_checklist"],
        "exit_checklist": checklists["exit_checklist"],
        "evidence_blocks": evidence_blocks,
        # EVIDENCE PROVENANCE (2026-09-06, TH-9): who actually produced the
        # headline dynamic-behaviour claims this stage's evidence carries
        # (dv_harness/evidence_provenance.py). Computed here rather than in
        # each UI because this is the ONE shared read path the dashboard's
        # "Why (current stage)" card and the CLI's explain/evidence/checklist
        # verbs both already go through -- two renderers, one answer, so a
        # self-attested deadlock-freedom claim cannot be caveated in one
        # surface and presented bare in the other.
        "evidence_provenance": summarize_evidence_blocks(
            evidence_blocks, suspicious_flags=cp.get("suspicious_flags", {}).get(stage, {})),
        "human_correction": cp.get("corrections", {}).get(stage),
        "human_approval": cp.get("approvals", {}).get(stage),
        "takeover": cp.get("takeover") if cp.get("takeover", {}).get("stage") == stage else None,
        # FLAG_SUSPICIOUS (2026-09-07): every suspicion-flag record on file
        # for this stage, regardless of whether it also matches one of
        # evidence_provenance.PROVENANCE_REQUIRED_GATES (the subset already
        # folded into "evidence_provenance" above) -- so a flag against a
        # non-provenance-required gate result, or against an evidence
        # citation string that is not a gate id at all, is still visible
        # through this same shared read path.
        "suspicious_flags": cp.get("suspicious_flags", {}).get(stage, {}),
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
