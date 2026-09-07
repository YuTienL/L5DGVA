"""dv_harness/prior_decision_reevaluation.py -- flag a PRIOR capability-evolution
decision for human RECONSIDERATION when new real evidence has accumulated
against it (Research-Capability Evolution master prompt section 77).

GAP THIS CLOSES
---------------
`capability_evolution.file_repeated_failure_candidate()` already refuses to
drag a candidate backwards once a human (or `research-architect`) has moved it
off DISCOVERED -- CLAUDE.md's own "Cross-Loop Coupling" section documents this
exactly: "A candidate a human has already moved on is never dragged back... if
that record has left DISCOVERED, the auto-filer reports
`ALREADY_BEYOND_DISCOVERED` and writes nothing." That refusal is correct and
this module does not touch it. But it leaves a real, named gap: once a
candidate reaches REJECTED (or a human records `final_decision: "HOLD"`),
`ALREADY_BEYOND_DISCOVERED` is the LAST thing anyone hears about it -- forever,
even if the same root cause goes on to recur across five more independent runs,
or a second and third project independently confirm it. Nothing in this
codebase ever tells a human "the evidence behind a REJECTED/HOLD decision has
grown since you decided it." A repo-wide grep (2026-09-06) for
`reconsider`/`re-evaluat`/`REJECTED.*evidence` confirmed no such mechanism
existed anywhere in `dv_harness/`.

This module is that mechanism, and only that: DETECTION. It compares a
persisted `CapabilityEvolutionCandidate`'s already-recorded evidence against
freshly-computed real evidence and, when the fresh evidence is a strict
superset, writes ONE flagged-reconsideration record. It never calls
`capability_evolution.transition()`, never edits `current_status`,
`promotion_status` or `final_decision` on the candidate it is examining, and
never files a new candidate. Reconsideration is a human's move, exactly like
every other capability-evolution state change in this codebase --
`assert_human_approval()`'s discipline one level up.

REUSE OVER REINVENT (2026-09-06 grep across dv_harness/)
---------------------------------------------------------
Every piece of "is this the same failure, and is it still open" logic is
IMPORTED, never re-derived:

  * failure identity and "still unresolved" -- verbatim
    `capability_evolution.repeated_unresolved_failure_patterns()`, the SAME
    function `file_candidates_for_repeated_failures()` already calls. This
    module adds no second definition of "the same root cause" or "closed by a
    verified fix".
  * cross-project recurrence -- the caller's own, already-computed
    `cross_project_mining.mine_cross_project_patterns(...)["cross_project_patterns"]`.
    This module runs no cross-project mining itself and registers no project:
    doing so honestly requires the caller's own `ProjectRegistry`, which is
    project-specific, and `cross_project_mining.py` already owns that
    machinery end to end.
  * persistence -- the same `memory_router.route_and_store()` /
    `memory.MemoryStore.find()` pair `capability_evolution.py` itself uses for
    its candidate audit trail, with a distinct `kind` so a flag record is never
    confused with a candidate record.
  * candidate identity -- `capability_evolution.read_candidates()`/
    `read_candidate()`, the one live Blackboard topic every other reader of a
    candidate already uses. No second candidate store.

WHY A NEW MODULE RATHER THAN EXTENDING capability_evolution.py
----------------------------------------------------------------
`capability_evolution.py` is 3000+ lines and is exactly the kind of "large
file under heavy edit pressure" file this project's convention is to leave
alone for a standalone front door instead (see e.g. `design_source_inventory.py`,
`intake_state.py`). Nothing here needed to be added there: every function this
module calls on that module (`repeated_unresolved_failure_patterns`,
`read_candidates`, `read_candidate`) already existed unchanged before this file
was written.

WHAT "SUPERSEDED" HONESTLY MEANS HERE
--------------------------------------
The task names three prior-decision statuses: REJECTED, HOLD, SUPERSEDED.
REJECTED is `capability_evolution.PROMOTION_STATES`' own terminal state.
HOLD is the candidate schema's own `final_decision` enum value
(`["PROMOTE", "REVISE", "HOLD", "REJECT", "PENDING"]`) -- real, but currently
has no producer anywhere in this codebase beyond `build_candidate()`'s
`PENDING` default, so a HOLD only ever appears on a candidate a human edited by
hand or through a future reviewing tool. SUPERSEDED, by contrast, is NOT a
value either `PROMOTION_STATES` or `final_decision` defines anywhere in this
codebase today (checked: `grep -n SUPERSEDED dv_harness/capability_evolution.py
dv_harness/schemas/capability_evolution_candidate.schema.json` -- zero hits).
The nearest real precedent, `doc_extraction.prior_research_relations()`'s
SUPERSEDES relation label for research documents, is deliberately NEVER
DERIVED by `capability_evolution.py` itself (see that module's own comment:
"It never derives SUPPORTS or SUPERSEDES... a comparator that guessed them
would fabricate exactly the kind of agreement section 28 warns about").
This module follows the identical discipline one level over: it never invents
that a candidate was superseded. `prior_decision_status()` reports SUPERSEDED
ONLY when the candidate itself already carries a caller-declared
`superseded_by` reference (a real fact someone else recorded), and reports the
honest `NOT_A_PRIOR_DECISION` status for anything else -- never a silent guess.

WHAT THIS MODULE NEVER DOES
----------------------------
  * Never reverses, transitions, or edits the candidate it examines.
  * Never mines cross-project stores or registers a project itself.
  * Never invents a `decided_at` timestamp: REJECTED's is the real
    `status_history` entry that made the transition; HOLD/SUPERSEDED have no
    such entry anywhere in this codebase today, so `decided_at` is honestly
    `None` for those two, with `decided_at_basis` saying why.
  * Writes nothing beyond ONE flagged-reconsideration record per genuinely new
    piece of evidence -- re-detecting the SAME evidence a second time reports
    `ALREADY_FLAGGED_UNCHANGED` and writes nothing, mirroring
    `file_repeated_failure_candidate()`'s own `ALREADY_ON_FILE_UNCHANGED`.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# The three prior-decision statuses this mechanism acts on (task-specified).
# Ordered most-terminal-first: a candidate could in principle carry more than
# one signal (e.g. current_status REJECTED on a record that also happens to
# carry a stale final_decision HOLD from an earlier review pass); REJECTED is
# reported because it is the state machine's own authoritative terminal fact,
# never averaged or blended with the other two.
RECONSIDERABLE_PRIOR_STATUSES = ("REJECTED", "HOLD", "SUPERSEDED")

# The one honest "this is not a concluded decision" status. Never silently
# skipped -- callers can see exactly why a candidate did not participate.
NOT_A_PRIOR_DECISION = "NOT_A_PRIOR_DECISION"

# The Working Memory `kind` a flagged-reconsideration record carries. Distinct
# from CANDIDATE_MEMORY_KIND so a flag can never be mistaken for a candidate
# by any reader of the Working Memory store.
RECONSIDERATION_FLAG_MEMORY_KIND = "capability_decision_reconsideration_flag"

_JOB_MEMORY_FAILURE_SIGNATURE_PREFIX = "job_memory:failure_signature:"


class ReconsiderationFlagRoutingError(RuntimeError):
    """Raised if a flag record ever routed anywhere but WORKING_MEMORY. A
    flagged reconsideration is exactly as unverified as the candidate it
    concerns and must never land on a higher memory tier by accident."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _last_transition_at(candidate: Dict[str, Any], to_status: str) -> Optional[str]:
    """The `at` of the MOST RECENT status_history entry that made this exact
    transition, or None if no such entry exists. Never guesses a time from
    anything else."""
    for entry in reversed(list(candidate.get("status_history") or [])):
        if isinstance(entry, dict) and entry.get("to_status") == to_status:
            at = entry.get("at")
            if isinstance(at, str) and at:
                return at
    return None


def prior_decision_status(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a persisted CapabilityEvolutionCandidate's own already-recorded
    fields into one of REJECTED/HOLD/SUPERSEDED/NOT_A_PRIOR_DECISION.

    Never inspects free text (hypothesis/proposed_action/rationale) and never
    infers a status this codebase's own vocabularies do not define. Returns
    {"status", "basis", "decided_at", "decided_at_basis"} -- `basis` names the
    exact field(s) that decided it, so a reader can verify the classification
    without trusting this function's word for it.
    """
    current = candidate.get("current_status")
    promotion = candidate.get("promotion_status")
    final_decision = candidate.get("final_decision")
    superseded_by = candidate.get("superseded_by")

    if current == "REJECTED" or promotion == "REJECTED":
        return {
            "status": "REJECTED",
            "basis": (
                f"current_status={current!r} promotion_status={promotion!r} -- "
                "capability_evolution.PROMOTION_STATES' own terminal REJECTED state"
            ),
            "decided_at": _last_transition_at(candidate, "REJECTED"),
            "decided_at_basis": "the most recent status_history entry with to_status==REJECTED",
        }
    if final_decision == "HOLD":
        return {
            "status": "HOLD",
            "basis": "final_decision=='HOLD' (capability_evolution_candidate.schema.json final_decision enum)",
            "decided_at": None,
            "decided_at_basis": (
                "no status_history entry type records when final_decision was set in "
                "this codebase today -- final_decision has no producer beyond build_candidate()'s "
                "PENDING default, so a real timestamp for a HOLD decision does not exist to report"
            ),
        }
    if isinstance(superseded_by, str) and superseded_by.strip():
        return {
            "status": "SUPERSEDED",
            "basis": (
                f"caller-declared superseded_by={superseded_by!r}. This module never derives "
                "SUPERSEDED itself -- it only relays a declaration already on the record, the same "
                "discipline capability_evolution.py applies to never deriving SUPERSEDES for "
                "research documents"
            ),
            "decided_at": None,
            "decided_at_basis": "superseded_by carries no timestamp of its own on this schema",
        }
    return {
        "status": NOT_A_PRIOR_DECISION,
        "basis": (
            f"current_status={current!r} promotion_status={promotion!r} "
            f"final_decision={final_decision!r} superseded_by={superseded_by!r} -- none of these "
            "match a reconsiderable prior-decision status"
        ),
        "decided_at": None,
        "decided_at_basis": "not a concluded decision",
    }


def repeated_failure_signature_key(candidate: Dict[str, Any]) -> Optional[str]:
    """The Job Memory failure-signature identity a candidate concerns, read
    ONLY from `trigger_source` (the exact field
    `capability_evolution.build_repeated_failure_candidate()` sets to
    `job_memory:failure_signature:<signature_key>`). A human-authored candidate
    naming no such trigger_source returns None -- honestly refusing to guess a
    signature out of free-text hypothesis prose."""
    trigger_source = str(candidate.get("trigger_source") or "")
    if trigger_source.startswith(_JOB_MEMORY_FAILURE_SIGNATURE_PREFIX):
        key = trigger_source[len(_JOB_MEMORY_FAILURE_SIGNATURE_PREFIX):].strip()
        return key or None
    return None


def known_evidence_refs(candidate: Dict[str, Any]) -> List[str]:
    """The memory_ids this candidate's decision was actually made from."""
    return sorted({str(x) for x in (candidate.get("evidence_refs") or []) if str(x).strip()})


def detect_new_repeated_failure_evidence(
    root, candidate: Dict[str, Any], *, min_occurrences: int = 2,
) -> Optional[Dict[str, Any]]:
    """None unless `capability_evolution.repeated_unresolved_failure_patterns()`
    now reports, for this candidate's own cited signature, at least one
    memory_id the candidate's `evidence_refs` did not already carry.

    A pure read: opens nothing for writing. Runs the real, unmodified
    `repeated_unresolved_failure_patterns()` -- no second failure-grouping
    logic exists in this module.
    """
    key = repeated_failure_signature_key(candidate)
    if key is None:
        return None
    from .capability_evolution import repeated_unresolved_failure_patterns

    known = set(known_evidence_refs(candidate))
    patterns = {
        p["signature_key"]: p
        for p in repeated_unresolved_failure_patterns(root, min_occurrences=min_occurrences)
    }
    pattern = patterns.get(key)
    if pattern is None:
        return None
    new_ids = sorted(set(pattern["memory_ids"]) - known)
    if not new_ids:
        return None
    return {
        "signature_key": key,
        "new_memory_ids": new_ids,
        "independent_run_count": pattern["independent_run_count"],
        "total_memory_ids": list(pattern["memory_ids"]),
    }


def detect_new_cross_project_evidence(
    candidate: Dict[str, Any],
    cross_project_patterns: Optional[Sequence[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """None unless one of the CALLER-SUPPLIED, already-mined
    `cross_project_mining.mine_cross_project_patterns(...)["cross_project_patterns"]`
    entries names this candidate's own cited signature and carries at least one
    memory_id the candidate's `evidence_refs` did not already carry.

    This module mines nothing itself: `cross_project_patterns` is exactly the
    list `mine_cross_project_patterns()` already returned, unmodified. A
    `None`/empty list (no cross-project mining run) is answered honestly with
    None, never treated as "no cross-project evidence exists".
    """
    key = repeated_failure_signature_key(candidate)
    if key is None or not cross_project_patterns:
        return None

    known = set(known_evidence_refs(candidate))
    for pattern in cross_project_patterns:
        if pattern.get("signature_key") != key:
            continue
        all_ids: set = set()
        for per_project in (pattern.get("per_project") or {}).values():
            all_ids.update(per_project.get("memory_ids") or [])
        new_ids = sorted(all_ids - known)
        if not new_ids:
            return None
        return {
            "signature_key": key,
            "new_memory_ids": new_ids,
            "project_count": pattern.get("project_count"),
            "project_ids": list(pattern.get("project_ids") or []),
        }
    return None


def mint_flag_id(candidate_id: str, repeated_evidence: Optional[Dict[str, Any]],
                 cross_project_evidence: Optional[Dict[str, Any]]) -> str:
    """RCF-<12 hex>, content-derived exactly like
    `capability_evolution.mint_candidate_id()` -- so re-detecting the IDENTICAL
    new evidence a second time lands on the SAME flag_id rather than minting a
    duplicate, and genuinely new evidence (different new_memory_ids) mints a
    genuinely different one."""
    rep_ids = tuple(sorted((repeated_evidence or {}).get("new_memory_ids") or []))
    cross_ids = tuple(sorted((cross_project_evidence or {}).get("new_memory_ids") or []))
    payload = "\x1f".join([str(candidate_id), repr(rep_ids), repr(cross_ids)])
    return "RCF-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def build_reconsideration_flag(
    candidate: Dict[str, Any],
    status: Dict[str, Any],
    repeated_evidence: Optional[Dict[str, Any]],
    cross_project_evidence: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Assemble one flagged-reconsideration record. Pure data assembly -- no
    file I/O, no memory write. `recommended_action` states the boundary in the
    record itself, not only in this module's docstring, so a human reading the
    record off disk sees the same guarantee."""
    candidate_id = candidate.get("candidate_id")
    flag_id = mint_flag_id(candidate_id, repeated_evidence, cross_project_evidence)
    evidence_reasons = []
    if repeated_evidence is not None:
        evidence_reasons.append("NEW_REPEATED_FAILURE_EVIDENCE")
    if cross_project_evidence is not None:
        evidence_reasons.append("NEW_CROSS_PROJECT_EVIDENCE")
    return {
        "kind": RECONSIDERATION_FLAG_MEMORY_KIND,
        "flag_id": flag_id,
        "candidate_id": candidate_id,
        "affected_capability": candidate.get("affected_capability"),
        "prior_decision_status": status["status"],
        "prior_decision_basis": status["basis"],
        "decided_at": status.get("decided_at"),
        "decided_at_basis": status.get("decided_at_basis"),
        "evidence_reasons": evidence_reasons,
        "new_evidence": {
            "repeated_failure": repeated_evidence,
            "cross_project": cross_project_evidence,
        },
        "flagged_at": _now(),
        "recommended_action": (
            f"Route {candidate_id!r} ({status['status']}) to a human for reconsideration. "
            "This record is detection-only: it never reverses, transitions, or edits the "
            "candidate. Any actual reversal is a separate human-authored "
            "capability_evolution.transition() call, exactly like every other "
            "capability-evolution state change."
        ),
    }


def detect_reconsiderations(
    root,
    candidates: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    cross_project_patterns: Optional[Sequence[Dict[str, Any]]] = None,
    min_occurrences: int = 2,
) -> List[Dict[str, Any]]:
    """Every flagged-reconsideration record this real evidence currently
    supports. A pure read: nothing is written, nothing is transitioned.

    `candidates` defaults to every live candidate on this project's own
    `capability_evolution` Blackboard topic (`read_candidates()`). Pass an
    explicit list to examine candidates from elsewhere (e.g. a snapshot, or
    another project's exported set) without touching this project's own
    Blackboard.
    """
    if candidates is None:
        from .capability_evolution import read_candidates

        candidates = list(read_candidates(root).values())

    flags: List[Dict[str, Any]] = []
    for candidate in candidates:
        status = prior_decision_status(candidate)
        if status["status"] not in RECONSIDERABLE_PRIOR_STATUSES:
            continue
        repeated_evidence = detect_new_repeated_failure_evidence(
            root, candidate, min_occurrences=min_occurrences
        )
        cross_evidence = detect_new_cross_project_evidence(candidate, cross_project_patterns)
        if repeated_evidence is None and cross_evidence is None:
            continue
        flags.append(build_reconsideration_flag(candidate, status, repeated_evidence, cross_evidence))
    return flags


def existing_reconsideration_flags(root, candidate_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every flagged-reconsideration record already on Working Memory, through
    the same shared `MemoryStore.find()` `capability_evolution.
    candidate_audit_records()` already uses for its own audit trail."""
    from .memory import MemoryStore

    filters: Dict[str, Any] = {"kind": RECONSIDERATION_FLAG_MEMORY_KIND}
    if candidate_id is not None:
        filters["candidate_id"] = candidate_id
    return MemoryStore(Path(root)).find("working", **filters)


def file_reconsideration_flag(root, flag: Dict[str, Any], *,
                              cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Persist ONE flagged-reconsideration record to Working Memory through
    the real `memory_router.route_and_store()` -- and nothing else. Asserts
    the routed destination is WORKING_MEMORY, mirroring
    `capability_evolution.persist_candidate()`'s own assertion: a flag is
    exactly as unverified as the candidate it concerns and must never reach a
    higher tier."""
    from .memory_router import route_and_store

    routed = route_and_store(Path(root), dict(flag), cfg={} if cfg is None else cfg)
    if routed.get("destination") != "WORKING_MEMORY":
        raise ReconsiderationFlagRoutingError(
            f"a reconsideration flag routed to {routed.get('destination')!r}; it must land in "
            "WORKING_MEMORY"
        )
    return {"memory": routed}


def file_reconsiderations(
    root,
    candidates: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    cross_project_patterns: Optional[Sequence[Dict[str, Any]]] = None,
    min_occurrences: int = 2,
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Detect, then persist every genuinely new flag -- skipping any whose
    identical `flag_id` (same candidate, same new-evidence memory_ids) is
    already on Working Memory, mirroring
    `file_repeated_failure_candidate()`'s own `ALREADY_ON_FILE_UNCHANGED`
    outcome so a repeated call never appends a duplicate audit record."""
    flags = detect_reconsiderations(
        root, candidates,
        cross_project_patterns=cross_project_patterns,
        min_occurrences=min_occurrences,
    )
    existing_ids = {
        rec.get("flag_id") for rec in existing_reconsideration_flags(root)
        if rec.get("flag_id")
    }

    results: List[Dict[str, Any]] = []
    for flag in flags:
        if flag["flag_id"] in existing_ids:
            results.append({
                "filed": False, "reason": "ALREADY_FLAGGED_UNCHANGED",
                "flag_id": flag["flag_id"], "candidate_id": flag["candidate_id"],
            })
            continue
        persisted = file_reconsideration_flag(root, flag, cfg=cfg)
        results.append({
            "filed": True, "reason": "NEW_EVIDENCE",
            "flag_id": flag["flag_id"], "candidate_id": flag["candidate_id"],
            "prior_decision_status": flag["prior_decision_status"],
            "evidence_reasons": flag["evidence_reasons"],
            "persisted": persisted,
        })
    return results


# ---------------------------------------------------------------------------
# Standalone front door. Not wired into cli.py -- see module docstring's
# "WHY A NEW MODULE" section and this project's own disclosed-residual
# convention for CLI wiring on a file its own convention keeps unedited.


def _load_json(path: Optional[str]):
    if not path:
        return None
    import json

    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=(
            "Detection-only: flag a PRIOR capability-evolution decision "
            "(REJECTED/HOLD/SUPERSEDED) for human reconsideration when new "
            "real evidence has accumulated. Never reverses a decision."
        )
    )
    parser.add_argument("verb", choices=("detect", "file"))
    parser.add_argument("--root", required=True, help="project root (.dv-harness lives under it)")
    parser.add_argument("--candidates", help=(
        "optional JSON file: a list of CapabilityEvolutionCandidate dicts to examine "
        "instead of this project's own live Blackboard candidates"
    ))
    parser.add_argument("--cross-project-patterns", help=(
        "optional JSON file: the 'cross_project_patterns' list from a prior "
        "cross_project_mining.mine_cross_project_patterns() call"
    ))
    parser.add_argument("--min-occurrences", type=int, default=2)
    args = parser.parse_args(argv)

    candidates = _load_json(args.candidates)
    cross_project_patterns = _load_json(args.cross_project_patterns)

    if args.verb == "detect":
        result = detect_reconsiderations(
            args.root, candidates,
            cross_project_patterns=cross_project_patterns,
            min_occurrences=args.min_occurrences,
        )
    else:
        result = file_reconsiderations(
            args.root, candidates,
            cross_project_patterns=cross_project_patterns,
            min_occurrences=args.min_occurrences,
            cfg={},
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
