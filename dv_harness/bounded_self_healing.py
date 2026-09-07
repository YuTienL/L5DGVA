"""Bounded Self-Healing (targeted_hardening, spec section 243): a narrowly
-scoped, human-approval-gated auto-remediation for exactly ONE safe class of
failure -- re-running a flaky test's identical failing action ONCE, when
`loop_budget.classify_failure()` -- this harness's own real trigger fact --
classifies the failure as `FailureType.TRANSIENT`.

WHAT WAS ACTUALLY MISSING, RE-VERIFIED BEFORE THIS FILE WAS WRITTEN
---------------------------------------------------------------------
A repo-wide grep on 2026-09-06 for `self_healing`/`SelfHealing`/
`auto_remediation`/`AutoRemediation` returned ZERO hits. `loop_budget.py`
already computes exactly the retry-vs-stop signal an auto-remediation
mechanism would need (`classify_failure()` / `decide_retry()` /
`RETRYABLE_FAILURE_TYPES`), and `decide_retry()` already lets a RETRYABLE
failure retry within the EXISTING `policy.max_stage_retries` budget -- so a
general auto-retry is not missing. What IS missing is the section-243
mechanism specifically: a bonus, OUT-OF-BAND re-run, authorized specifically
because the failure looked flaky, gated behind a real human decision made
for THAT recurrence -- distinct from an ordinary budgeted attempt, and
distinct from a project-wide policy default nobody has to look at twice.

WHY THIS IS NOT `loop_budget.decide_retry()` WITH ENFORCEMENT TURNED ON
-------------------------------------------------------------------------
`loop_budget.enforce_retry_policy` decides whether an ORDINARY attempt
(spent against `policy.max_stage_retries`) is allowed to proceed for a
NON-retryable classification -- a STOP switch, decided once per project, with
no human decision required to fire. Section 243 asks for the opposite shape:
not "should this normal attempt be blocked", but "should THIS SPECIFIC
recurrence of a flaky failure get a special, narrowly-scoped extra chance" --
and that extra chance must be approved by a human, per instance, the same way
a Bind-Location Rule 5 Tier-3 confirmation or a RESEARCH_CAPABILITY_EVOLUTION
promotion is. This module is that second, narrower mechanism, layered ON TOP
of (never inside of, never a fork of) `loop_budget.py`.

REUSE, NOT PARALLEL INFRASTRUCTURE -- every input names its real producer
---------------------------------------------------------------------------
  * The TRIGGER FACT is `loop_budget.classify_failure()`, CALLED, never
    re-derived. A caller that already classified the failure (e.g. a future
    `engine.loop()` call site, mirroring its own real `_classify_stage_failure()`)
    may hand this module the `FailureClassification` it already computed
    instead of re-classifying the same text a second time.
  * The ELIGIBLE CLASS is `loop_budget.FailureType.TRANSIENT` ONLY -- a
    narrower set than loop_budget's own broader RETRYABLE set. LICENSE /
    RESOURCE / INFRASTRUCTURE / UNKNOWN are also `retryable=True` in
    `loop_budget.RETRYABLE_FAILURE_TYPES`, but each already has its own real
    mechanism (`loop_budget.prioritize_stage()`'s deferral for resource
    pressure; the plain existing retry budget for UNKNOWN) -- silently
    self-healing a resource-pressure failure by re-running it would be
    exactly the "not a SPECIFIC, safe class" scope creep section 243 warns
    against. TRANSIENT is the one class whose own definition in
    `loop_budget.py` ("retrying the identical action can genuinely work") IS
    the flaky-test/dropped-connection circumstance section 243 names.
  * The HUMAN-APPROVAL GATE is the EXISTING `ControlPlane.approve()` /
    `get_approval()` / `clear_approval()` mechanism -- the identical one
    `capability_evolution.assert_human_approval()` (key
    `RESEARCH_CAPABILITY_EVOLUTION`) and `change_blast_radius.py` (key
    `CHANGE_BLAST_RADIUS`) already use. `HUMAN_APPROVAL_STAGE` below is a
    THIRD key on that SAME mechanism, never a new approval store or a new
    control file. `commands.APPROVAL_ONLY_STAGES` admits it (a one-line,
    additive extension of the existing table, mirroring how
    `_RESEARCH_APPROVAL_STAGE`/`_BLAST_RADIUS_APPROVAL_STAGE` were added), so
    the already-wired `dv-harness approve BOUNDED_SELF_HEALING --note ...
    --reviewer-id ... --reviewer-confidence ...` command is how a human
    actually grants it -- no parallel CLI, no new approval file, no new
    graph node.
  * The LEDGER's atomic-write discipline is `storage._atomic_replace()`,
    reused exactly as `loop_budget.BudgetEngine.save()` and `blackboard.py`
    already use it -- never a bare truncate-then-write.

WHAT THIS MODULE DOES NOT DO
-------------------------------
  * It never bypasses ANY existing gate. `ControlPlane.approve()`,
    `policy.can_signoff()`, `capability_evolution.assert_human_approval()`,
    `HumanApprovalRequiredError`, `ProductionWriteNotAuthorizedError` and the
    PR-only main/master governance are untouched and uncalled from here
    (checked against this module's own real code by
    `dv_harness_tests/test_bounded_self_healing.py`, not merely claimed in
    this docstring). The ONE gate this module itself enforces (a live,
    per-signature-cited `BOUNDED_SELF_HEALING` approval) is ADDITIONAL to,
    never a substitute for, `policy.max_stage_retries` /
    `loop_budget.enforce_retry_policy` / the circuit breaker: an AUTHORIZED
    decision here still has to clear every one of those before any real
    re-run actually happens.
  * It never dispatches, retries, submits, or runs anything itself. It
    returns a decision (`AUTHORIZED` / `NOT_ELIGIBLE` / one of the `BLOCKED_*`
    values); acting on `AUTHORIZED` -- actually re-running the failing
    action -- is the caller's job, through the harness's OWN existing
    stage-dispatch path, which still runs every one of ITS OWN gates
    unweakened. This module contains no call to `run_stage`, no subprocess
    invocation, and no LSF/build submission call of any kind -- asserted
    against this module's own real source (tokenized, so a mention inside a
    docstring like this one can never satisfy the check) by
    `dv_harness_tests/test_bounded_self_healing.py`.
  * It never self-authorizes. This module never calls `ControlPlane.
    approve()` -- only a human, through the real `dv-harness approve` verb,
    can create the record `get_approval()` reads here.
  * It never silently re-authorizes a DIFFERENT failure. A
    `BOUNDED_SELF_HEALING` approval must literally NAME the action id or the
    real failure signature it is approving (the same "must NAME the real
    decision" discipline the Waveform Dump User Gate's
    `question_queue.HUMAN_DECISION_SOURCE` already enforces one gate over),
    so a blanket "yes, self-heal everything" note can never authorize a
    signature it was never shown -- reported `BLOCKED_APPROVAL_MISMATCH`
    rather than silently accepted. An approval that DOES authorize an action
    is CONSUMED the moment it does (`ControlPlane.clear_approval()`), so it
    cannot be reused for a later, different signature without a fresh human
    decision.
  * It never heals the same signature twice. A per-(stage, signature) ledger
    row, written ONLY on a real `AUTHORIZED` decision, blocks every future
    attempt at that exact signature with `BLOCKED_ALREADY_HEALED` -- the
    one-time "re-run once" bound section 243's own example names, enforced
    by a persisted record rather than trusted to caller discipline. A
    signature that keeps recurring after being healed once is no longer
    behaving like a flake -- it is exactly the circumstance
    `loop_budget.py`'s own repeated-identical-failure / circuit-breaker
    machinery exists to catch, and this module deliberately defers to that
    rather than healing it again.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .loop_budget import FailureClassification, FailureType, classify_failure

#: ControlPlane approval key. A THIRD key on the EXISTING
#: capability_evolution/change_blast_radius Human Approval mechanism -- see
#: `commands.APPROVAL_ONLY_STAGES`, which this module's own key is added to
#: (additively) so `dv-harness approve BOUNDED_SELF_HEALING ...` is real and
#: already wired, never a parallel approval store.
HUMAN_APPROVAL_STAGE = "BOUNDED_SELF_HEALING"

#: Section 243's own bound: ONE failure class, not every retryable one in
#: `loop_budget.RETRYABLE_FAILURE_TYPES`. See the module docstring's "WHY
#: THIS IS NOT loop_budget.decide_retry() ..." section for why the other
#: retryable types (LICENSE/RESOURCE/INFRASTRUCTURE/UNKNOWN) are excluded.
ELIGIBLE_FAILURE_TYPES = (FailureType.TRANSIENT.value,)

DECISION_AUTHORIZED = "AUTHORIZED"
DECISION_NOT_ELIGIBLE = "NOT_ELIGIBLE"
DECISION_BLOCKED_NO_APPROVAL = "BLOCKED_NO_APPROVAL"
DECISION_BLOCKED_APPROVAL_MISMATCH = "BLOCKED_APPROVAL_MISMATCH"
DECISION_BLOCKED_ALREADY_HEALED = "BLOCKED_ALREADY_HEALED"

#: Every decision this module can reach. Checked disjoint from
#: `dv_harness.models.Status` at import (`assert_no_verification_verdict_
#: vocabulary()`) -- a self-healing DECISION is a statement about whether an
#: extra attempt is authorized, never a verification verdict about the DUT.
DECISIONS = (
    DECISION_AUTHORIZED, DECISION_NOT_ELIGIBLE, DECISION_BLOCKED_NO_APPROVAL,
    DECISION_BLOCKED_APPROVAL_MISMATCH, DECISION_BLOCKED_ALREADY_HEALED,
)

LEDGER_FILENAME = "self_healing_ledger.json"
LEDGER_SCHEMA_VERSION = "1.0"

#: How many characters of a normalized failure signature are cited in an
#: approval note / action id. Long enough to be a real, checkable citation
#: (matching `loop_budget.normalize_failure_text()`'s own truncation
#: discipline in spirit); short enough that a human typing it into `--note`
#: by hand is realistic.
SIGNATURE_CITATION_LENGTH = 16


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's DECISIONS never collide with `models.Status` members --
    a self-healing decision is not a verification verdict, and the two must
    never be readable as the same kind of fact."""
    from .models import Status
    status_values = {s.value for s in Status}
    collisions = sorted(d for d in DECISIONS if d in status_values)
    if collisions:
        raise AssertionError(
            f"bounded_self_healing.DECISIONS collide with models.Status: {collisions}")


assert_no_verification_verdict_vocabulary()


def action_id_for(stage: str, signature: str) -> str:
    """Deterministic id for one (stage, failure-signature) self-healing
    candidacy -- content-derived and RE-DERIVED on every call (never minted
    once and trusted), so re-evaluating the identical circumstance always
    names the same action and a human's approval note can cite it stably."""
    digest = hashlib.sha256(f"{stage}\x00{signature}".encode("utf-8")).hexdigest()
    return f"SH-{digest[:16]}"


@dataclass
class SelfHealingDecision:
    """One evaluation's outcome, carrying enough evidence that a reader never
    has to trust the `decision` field alone."""
    decision: str
    stage: str
    action_id: str
    failure_signature: str
    failure_type: str
    reason: str
    trigger: Dict[str, Any] = field(default_factory=dict)
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def authorized(self) -> bool:
        return self.decision == DECISION_AUTHORIZED


class SelfHealingLedgerError(ValueError):
    """Raised on a malformed ledger use -- e.g. attempting to record a second
    row for an action_id that already has one."""


class SelfHealingLedger:
    """`.dv-harness/self_healing_ledger.json` -- one row per (stage,
    signature) self-healing action that was ever AUTHORIZED (never a row for
    an ineligible or unapproved evaluation -- see `evaluate_self_healing()`'s
    own docstring for why persisting those would be a real bug: it would
    permanently block a signature from ever being healed just because the
    FIRST evaluation happened before a human had approved anything).

    Atomic-write discipline reused from `storage._atomic_replace()` -- the
    same one `loop_budget.BudgetEngine.save()` and `blackboard.py` already
    use -- never a bare truncate-then-write.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def path(self) -> Path:
        return self.root / ".dv-harness" / LEDGER_FILENAME

    def _load(self) -> Dict[str, Any]:
        p = self.path
        if not p.exists():
            return {"schema_version": LEDGER_SCHEMA_VERSION, "actions": {}}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            # An unreadable ledger reads as empty rather than crashing a
            # caller -- but it is NOT silently treated as "nothing was ever
            # healed" without saying so, mirroring loop_budget.BudgetEngine's
            # own `load_error` discipline for its own ledger.
            return {"schema_version": LEDGER_SCHEMA_VERSION, "actions": {},
                    "load_error": "LEDGER_UNREADABLE"}
        if not isinstance(data, dict) or not isinstance(data.get("actions"), dict):
            return {"schema_version": LEDGER_SCHEMA_VERSION, "actions": {},
                    "load_error": "LEDGER_MALFORMED"}
        return data

    def get(self, action_id: str) -> Optional[Dict[str, Any]]:
        return self._load().get("actions", {}).get(action_id)

    def record(self, decision: SelfHealingDecision) -> Dict[str, Any]:
        """Append-only per `action_id`. Refuses (`SelfHealingLedgerError`)
        rather than overwrites an existing row -- the one-time bound this
        ledger exists to enforce would be worthless if a second AUTHORIZED
        decision could silently replace the first."""
        data = self._load()
        actions = data.setdefault("actions", {})
        if decision.action_id in actions:
            raise SelfHealingLedgerError(
                f"action {decision.action_id!r} already has a ledger row; the ledger is "
                f"append-only per action_id -- call get() first.")
        actions[decision.action_id] = decision.to_dict()
        self._save(data)
        return actions[decision.action_id]

    def record_outcome(self, action_id: str, *, outcome: str, evidence: str = "") -> Dict[str, Any]:
        """Optional, best-effort audit closure: did the bonus re-run this
        ledger row authorized actually clear the failure? Never required by
        `evaluate_self_healing()` and never consulted by it either -- adding
        an outcome to an already-recorded action can never reopen or
        re-authorize it."""
        data = self._load()
        actions = data.setdefault("actions", {})
        row = actions.get(action_id)
        if row is None:
            raise SelfHealingLedgerError(
                f"no ledger row for action {action_id!r}; an outcome can only be recorded "
                f"against an action this ledger already authorized.")
        row["outcome"] = {"outcome": outcome, "evidence": evidence[:1000]}
        self._save(data)
        return row

    def _save(self, data: Dict[str, Any]) -> None:
        from .storage import _atomic_replace
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="self_healing.", suffix=".json", dir=str(p.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _atomic_replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def classify_self_healing_eligibility(classification: FailureClassification) -> Optional[str]:
    """`None` when the classification is eligible for bounded self-healing;
    otherwise the honest, real reason it is not.

    Section 243's own bound: ONE safe class, not every retryable one -- see
    the module docstring's "WHY THIS IS NOT loop_budget.decide_retry() ..."
    for why LICENSE/RESOURCE/INFRASTRUCTURE/UNKNOWN (also `retryable=True`
    in `loop_budget.RETRYABLE_FAILURE_TYPES`) are still refused here.
    """
    if classification.failure_type not in ELIGIBLE_FAILURE_TYPES:
        return (
            f"classified {classification.failure_type} by rule {classification.rule} "
            f"(loop_budget.classify_failure()); bounded self-healing covers only "
            f"{list(ELIGIBLE_FAILURE_TYPES)} -- a narrower set than loop_budget's own "
            f"broader retryable set, deliberately, so this mechanism never silently "
            f"expands to a failure class it was not built for.")
    if not classification.retryable:
        # Defensive, not merely decorative: loop_budget.RETRYABLE_FAILURE_TYPES
        # marks TRANSIENT retryable today and loop_budget's own
        # assert_retry_policy_total() keeps that total, but this module never
        # trusts that fact from memory -- it re-reads the real classification.
        return (
            f"classified {classification.failure_type} but the real classification's own "
            f"`retryable` field is False; self-healing defers to that field rather than "
            f"overriding it.")
    return None


def evaluate_self_healing(
    classification: FailureClassification,
    stage: str,
    *,
    root: Path,
    control_plane: Optional[Any] = None,
    ledger: Optional[SelfHealingLedger] = None,
) -> SelfHealingDecision:
    """THE one decision function. Never mutates `state.json`, never
    dispatches or retries anything, and never touches any gate other than
    the one `BOUNDED_SELF_HEALING` `ControlPlane` approval it itself reads
    (and, on a real AUTHORIZED outcome, consumes).

    Order of checks, and why it is this order:
      1. Ledger first -- the one-time bound is the cheapest, most important
         fact to check, and it must never be skippable by any later branch.
      2. Eligibility -- `loop_budget.classify_failure()`'s own real
         classification, never re-derived.
      3. Human approval -- checked LAST, so a caller can tell "this would
         need approval" (`BLOCKED_NO_APPROVAL`) apart from "this would never
         be eligible regardless of approval" (`NOT_ELIGIBLE`).

    Only a real `AUTHORIZED` outcome is ever written to the ledger. Writing
    `BLOCKED_NO_APPROVAL`/`BLOCKED_APPROVAL_MISMATCH` there would be a real
    bug: it would permanently block a signature from ever healing merely
    because the FIRST evaluation happened before a human had approved
    anything -- re-evaluating the identical circumstance after a human
    grants approval must still be able to reach `AUTHORIZED`.
    """
    root = Path(root)
    action_id = action_id_for(stage, classification.signature)
    ledger = ledger or SelfHealingLedger(root)

    prior = ledger.get(action_id)
    if prior is not None:
        return SelfHealingDecision(
            decision=DECISION_BLOCKED_ALREADY_HEALED,
            stage=stage, action_id=action_id,
            failure_signature=classification.signature,
            failure_type=classification.failure_type,
            reason=(
                f"a self-healing action for {action_id} was already AUTHORIZED at "
                f"{prior.get('approved_at')}. Section 243's own bound is ONE re-run per "
                f"flaky failure, enforced by this ledger row rather than trusted to caller "
                f"discipline; a signature that keeps recurring after being healed once is "
                f"no longer behaving like a flake."),
            trigger=classification.to_dict())

    ineligible_reason = classify_self_healing_eligibility(classification)
    if ineligible_reason is not None:
        return SelfHealingDecision(
            decision=DECISION_NOT_ELIGIBLE,
            stage=stage, action_id=action_id,
            failure_signature=classification.signature,
            failure_type=classification.failure_type,
            reason=ineligible_reason,
            trigger=classification.to_dict())

    if control_plane is None:
        from .control_plane import ControlPlane
        control_plane = ControlPlane(root)

    approval = control_plane.get_approval(HUMAN_APPROVAL_STAGE)
    if approval is None:
        return SelfHealingDecision(
            decision=DECISION_BLOCKED_NO_APPROVAL,
            stage=stage, action_id=action_id,
            failure_signature=classification.signature,
            failure_type=classification.failure_type,
            reason=(
                f"no human approval on file for stage {HUMAN_APPROVAL_STAGE}. A human must "
                f"run: dv-harness approve {HUMAN_APPROVAL_STAGE} --note "
                f"'{action_id} {classification.signature[:SIGNATURE_CITATION_LENGTH]}' "
                f"--reviewer-id <you> --reviewer-confidence HIGH|MEDIUM|LOW"),
            trigger=classification.to_dict())

    note = str(approval.get("note") or "")
    sig_citation = classification.signature[:SIGNATURE_CITATION_LENGTH]
    if action_id not in note and (not sig_citation or sig_citation not in note):
        return SelfHealingDecision(
            decision=DECISION_BLOCKED_APPROVAL_MISMATCH,
            stage=stage, action_id=action_id,
            failure_signature=classification.signature,
            failure_type=classification.failure_type,
            reason=(
                f"a {HUMAN_APPROVAL_STAGE} approval exists but its note does not cite "
                f"{action_id} or the real failure signature -- a blanket approval can never "
                f"silently authorize a DIFFERENT failure it was never shown. A human must "
                f"re-approve, naming this action, before this recurrence may be healed."),
            trigger=classification.to_dict())

    decision = SelfHealingDecision(
        decision=DECISION_AUTHORIZED,
        stage=stage, action_id=action_id,
        failure_signature=classification.signature,
        failure_type=classification.failure_type,
        reason=(
            f"loop_budget.classify_failure() classified this failure "
            f"{classification.failure_type} (rule {classification.rule}); a real, "
            f"per-signature human approval is on file; no prior self-healing action exists "
            f"for this signature. One bounded re-run of the identical failing action is "
            f"authorized -- the caller's own existing dispatch path still governs whether it "
            f"actually happens, and every gate that path already enforces still applies."),
        trigger=classification.to_dict(),
        approved_by=approval.get("reviewer_id"),
        approved_at=approval.get("approved_at"))
    ledger.record(decision)
    control_plane.clear_approval(HUMAN_APPROVAL_STAGE, outcome=f"CONSUMED_BY_SELF_HEAL:{action_id}")
    return decision


# ==========================================================================
# Front door
# ==========================================================================
def execute_verb(root: Path, verb: str, *, text: str = "", stage: str = "") -> tuple:
    """Returns (exit_code, payload). One implementation for `python -m
    dv_harness.bounded_self_healing`; there is deliberately no `dv-harness`
    CLI subcommand of its own (approval itself already goes through the
    real, existing `dv-harness approve` verb -- see the module docstring)."""
    root = Path(root)

    if verb == "eligible-types":
        return 0, {"eligible_failure_types": list(ELIGIBLE_FAILURE_TYPES),
                   "human_approval_stage": HUMAN_APPROVAL_STAGE,
                   "approve_command": (
                       f"dv-harness approve {HUMAN_APPROVAL_STAGE} "
                       "--note '<action_id or failure signature>' --reviewer-id <you> "
                       "--reviewer-confidence HIGH|MEDIUM|LOW")}

    if verb == "classify":
        if not text:
            return 1, {"ok": False, "error": "TEXT_REQUIRED",
                       "hint": "pass the failing attempt's blocking_reason / log excerpt"}
        classification = classify_failure(text)
        reason = classify_self_healing_eligibility(classification)
        return 0, {"classification": classification.to_dict(),
                   "self_healing_eligible": reason is None,
                   "ineligible_reason": reason}

    if verb == "evaluate":
        if not text:
            return 1, {"ok": False, "error": "TEXT_REQUIRED"}
        if not stage:
            return 1, {"ok": False, "error": "STAGE_REQUIRED"}
        classification = classify_failure(text)
        decision = evaluate_self_healing(classification, stage, root=root)
        return (0 if decision.authorized else 1), decision.to_dict()

    if verb == "ledger":
        ledger = SelfHealingLedger(root)
        return 0, ledger._load()

    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["eligible-types", "classify", "evaluate", "ledger"]}


def main(argv: Optional[list] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    ap = argparse.ArgumentParser(prog="python -m dv_harness.bounded_self_healing",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("verb", choices=["eligible-types", "classify", "evaluate", "ledger"])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--text", default="")
    ap.add_argument("--stage", default="")
    args = ap.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb,
                                 text=args.text, stage=args.stage)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
