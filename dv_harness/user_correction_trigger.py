"""User-Correction-Triggered Capability-Evolution Gap Detection.

Research_Capability_Evolution_Master_Prompt sections 64/66: file a
capability-evolution candidate when a human has REPEATEDLY corrected the
SAME KIND of agent mistake. Same DISCOVERED-only, human-approval-gated
posture as the existing repeated-failure auto-filer
(`capability_evolution.file_repeated_failure_candidate()` /
`repeated_unresolved_failure_patterns()`, see that module's "Cross-Loop
Coupling" section) -- this module reuses that machinery's real
candidate-construction functions (`build_candidate()`, `persist_candidate()`,
`read_candidate()`) rather than a second, parallel constructor. No edit was
made to `capability_evolution.py` itself: it is a large, heavily-referenced
module, and every fact this module needs from it (`L5_SEARCH_SLOTS`,
`RESEARCH_GAP_ACTION_CATALOG`, `BLACKBOARD_TOPIC`, `build_candidate`,
`persist_candidate`, `read_candidate`, `IllegalPromotionTransitionError`) is
already public.

REUSE OVER REINVENT -- checked before writing a line of this module
---------------------------------------------------------------------------
`capability_evolution.py`'s own "Cross-Loop Coupling" already closes the
FAILURE-repetition half of section 64 (Job Memory `job_failure` records ->
capability candidate, closed only by a gate-verified `verified_fix`). Nothing
in this repository closes the CORRECTION-repetition half -- a repo-wide grep
for `user_correction`/`correction_trigger`/`repeated.*correction` before
writing this module returned nothing executable.

The evidence this module reuses is `dv_harness/memory.py`'s OWN,
ALREADY-CODED correction lifecycle -- `MemoryGC.retract()` ("the record was
found to be wrong outright") and `MemoryGC.supersede()` ("a newer, CORRECTED
record replaces this one", verbatim from that method's own docstring). Both
set a real, persisted `status` (`RETRACTED`/`SUPERSEDED`) plus a real cited
reason (`retraction_reason`/`supersede_reason`) on the SAME per-tier record
files `MemoryStore.add()` already writes -- there is NO second correction log
anywhere in this module, and none is invented. `dv_harness/
confidence_calibration.py` already treats both statuses as "a rejected
outcome" for its own domain (tier reliability); this module reuses the
identical two real methods for a different question (repetition of the SAME
mistake, not tier reliability).

`kind in ("debug_lesson", "root_cause")` -- this codebase's own real "lesson"
vocabulary (`engine._promote_experience_knowledge()`'s own comment: a
`debug_lesson` "captures what this class of problem looks like / why / when
it applies") -- is the LESSON half named in this item's own title. A filed
candidate carries, purely as informational context, whether any such lesson
record already discusses the identical normalized text (see
`captured_lesson_claim_texts()` below) -- but unlike the failure-pattern
filer's `verified_fix`, this is NOT a closure gate (see "NO CLOSURE CONCEPT"
below).

WHAT "REPEATEDLY CORRECTED THE SAME KIND OF MISTAKE" MEANS HERE
---------------------------------------------------------------------------
Two or more INDEPENDENT memory records (distinct `memory_id`s -- each one IS
one correction event, since `MemoryGC.retract()`/`supersede()` mutate one
record file in place and `MemoryStore.add()` mints a fresh uuid-based
`memory_id` for anything not already carrying one) whose cited correction
reason (`retraction_reason` for RETRACTED, `supersede_reason` for SUPERSEDED)
normalizes to the SAME text. Matching is EXACT equality after
whitespace/case normalization, never fuzzy or keyword-overlap -- the same
"exact equality ... never fuzzy" discipline
`capability_evolution.failure_resolution_claims()`'s own docstring states the
reason for: a fuzzy join would quietly group unrelated corrections as "the
same kind of mistake", which is the more expensive error of the two (it
would manufacture a pattern, not merely miss one). This is a real,
disclosed limitation: unlike a `build_failure_signature()` dict (built by one
shared function specifically so two occurrences of the SAME failure produce
byte-identical fields), `retraction_reason`/`supersede_reason` are free text
a caller writes fresh each time, so two occurrences of what a human would
call "the same kind of mistake" worded even slightly differently will NOT be
grouped together. Under-detection, never fabricated over-detection, is the
accepted trade.

HONESTLY DISCLOSED: retract()/supersede() ARE REACHABLE, NOT YET WIRED
---------------------------------------------------------------------------
Confirmed by direct search before writing this module: `MemoryGC.retract()`
and `MemoryGC.supersede()` have ZERO production callers anywhere in
`dv_harness/*.py` today. `memory_cli.py`'s only human-facing lifecycle verb
is `deprecate` (a DIFFERENT status, `DEPRECATED` -- "retired, not refuted",
per that method's own docstring, and `confidence_calibration.py` deliberately
does NOT count it as a rejected outcome for exactly that reason). The one CLI
surface that DOES name RETRACTED (`dv-harness knowledge deprecate`) calls
into the REMOTE, opt-in Knowledge Center broker (`knowledge_center.py`), not
this project's LOCAL `.dv-harness/memory` tree this module reads, and
requires a live server connection this module neither establishes nor
depends on. So THIS repository's own real answer today is that zero
repeated-correction patterns exist to detect -- the same honest "no
production result exists yet" disclosure `cross_project_mining.py` and
`syoscb_source_audit.py` already make for their own domains. The mechanism
below is proven against REAL `MemoryGC.retract()`/`supersede()` calls (never
hand-written JSON files), and fires the moment any real caller anywhere in
this codebase -- a future local CLI verb, or a human using the existing
remote one against a mirrored local store -- starts producing them.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
---------------------------------------------------------------------------
  * It never decides which correction was right, never resolves a
    disagreement, and never edits a memory record -- detection only, exactly
    like `repeated_unresolved_failure_patterns()`.
  * It never advances a candidate past DISCOVERED, never approves anything,
    and touches no human-approval gate: `assert_legal_transition()` /
    `assert_human_approval()` / `HumanApprovalRequiredError` /
    `ProductionWriteNotAuthorizedError` in `capability_evolution.py` are
    untouched and uncalled from this module.
  * It never re-implements `build_candidate()`/`persist_candidate()`: every
    filed candidate goes through those exact functions, so the recommendation
    stays DERIVED and the confidence stays recomputed through the real
    `inference.score_confidence()`, never self-reported by this module.
  * NO CLOSURE CONCEPT. Unlike the failure-pattern filer's `verified_fix`
    (a gate-verified "this specific failure was fixed"), nothing in this
    codebase gate-verifies "this class of correction can no longer happen" --
    inventing one here would be exactly the fabrication the Evidence Truth
    Rule forbids. The only thing that stops a pattern from being re-filed on
    the next cycle is `file_user_correction_candidate()`'s own
    ALREADY_BEYOND_DISCOVERED guard -- a human (or a `research-architect`
    pass) moving the candidate off DISCOVERED -- mirroring the failure
    filer's identical guard exactly.
  * It writes nothing outside `<root>/.dv-harness/` (the one Blackboard topic
    and the one Working Memory audit record `persist_candidate()` already
    writes for every other candidate) and touches no memory record's own
    `status`/`retraction_reason`/`supersede_reason` fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .capability_evolution import (
    BLACKBOARD_TOPIC,
    L5_CHECK_QUESTIONS,
    L5_QUESTION_FIELD,
    L5_SEARCH_SLOTS,
    RESEARCH_GAP_ACTION_CATALOG,
    IllegalPromotionTransitionError,
    build_candidate,
    persist_candidate,
    read_candidate,
)
from .evidence_db import signature_key

# Matching REPEAT_FAILURE_MIN_OCCURRENCES' own reasoning (capability_evolution.py):
# two INDEPENDENT corrections, never one correction reported twice, is the
# smallest observation that is not one event dressed up as a pattern.
REPEAT_CORRECTION_MIN_OCCURRENCES = 2

# The two real dv_harness.memory.MemoryGC statuses that mean "a human found
# this stored conclusion wrong and corrected it" -- see module docstring.
# Deliberately excludes "DEPRECATED" (MemoryGC.deprecate(): retired, not
# refuted) and "NEEDS_REVALIDATION" (MemoryGC.flag_stale(): needs a fresh
# look, not a confirmed mistake) -- neither means a correction happened.
CORRECTION_STATUSES = ("RETRACTED", "SUPERSEDED")

# This codebase's own "lesson" vocabulary (engine._promote_experience_
# knowledge()'s comment names debug_lesson/root_cause/verified_fix as the
# three kinds routed to Engineering Memory; only the first two are genuinely
# "a lesson", the third is a closure record for a DIFFERENT loop).
LESSON_KINDS = ("debug_lesson", "root_cause")

AUTO_DISCOVERY_TRIGGER_TYPE = "USER_CORRECTION"  # a real value the
# candidate schema's own trigger_type enum already declares (checked before
# writing this module) -- not invented here.
AUTO_DISCOVERY_BY = "user-correction-loop"

# Which of section 14's ten questions each of the six search slots answers --
# recomputed locally from the same public constants
# capability_evolution.py's own private _SLOT_QUESTION derives from, so the
# auto-filed search_basis can quote that question's real next-best-action
# text out of RESEARCH_GAP_ACTION_CATALOG instead of inventing a parallel one.
_SLOT_QUESTION = {
    L5_QUESTION_FIELD[q]: q
    for q in L5_CHECK_QUESTIONS
    if L5_QUESTION_FIELD[q] in L5_SEARCH_SLOTS
}


def _norm_text(value: Any) -> str:
    """Lowercased, whitespace-collapsed text -- the same normalization
    `capability_evolution._norm_text()` applies, reimplemented locally
    (rather than importing a leading-underscore private symbol) since this
    module joins a different pair of fields and owes that join no shared
    state with capability_evolution.py's own."""
    return " ".join(str(value or "").strip().lower().split())


def correction_reason_text(record: Dict[str, Any]) -> str:
    """The real cited correction reason for one memory record, or "" if this
    record does not carry one of the two recognized correction statuses.

    Deliberately reads the field MemoryGC's own method for that status writes
    -- `retraction_reason` for RETRACTED, `supersede_reason` for SUPERSEDED --
    never a generic "reason" field neither method actually sets."""
    status = str(record.get("status") or "").upper()
    if status == "RETRACTED":
        return str(record.get("retraction_reason") or "")
    if status == "SUPERSEDED":
        return str(record.get("supersede_reason") or "")
    return ""


def correction_signature_key(reason_text: str) -> str:
    """Stable dedup key for one normalized correction reason.

    Reuses evidence_db.signature_key() -- the SAME stable-hash utility
    capability_evolution.repeated_unresolved_failure_patterns() already
    depends on -- rather than a second hashing definition in this codebase."""
    return signature_key({"correction_reason": _norm_text(reason_text)})


def captured_lesson_claim_texts(root) -> List[str]:
    """Every normalized claim text a debug_lesson/root_cause Engineering (or
    any-tier) Memory record names.

    Purely informational context carried onto a filed candidate's evidence --
    see the module docstring's "NO CLOSURE CONCEPT": unlike
    resolved_failure_claim_texts()/verified_fix for the failure-pattern
    filer, a match here never suppresses filing. Reused pattern: reads
    through the shared MemoryStore.find(), never a hand-rolled index scan."""
    from .memory import MemoryStore

    texts = set()
    store = MemoryStore(Path(root))
    for kind in LESSON_KINDS:
        for record in store.find(None, kind=kind):
            for field in ("root_cause", "title", "fix"):
                text = _norm_text(record.get(field))
                if text:
                    texts.add(text)
    return sorted(texts)


def repeated_user_correction_patterns(
    root, *, min_occurrences: int = REPEAT_CORRECTION_MIN_OCCURRENCES
) -> List[Dict[str, Any]]:
    """Every distinct correction reason that at least `min_occurrences`
    INDEPENDENT memory records (real MemoryGC.retract()/supersede() calls,
    never hand-written) cite.

    A pure read: opens no file for writing and files nothing. The returned
    dicts carry the whole basis of the finding -- the normalized reason, the
    correction status, the contributing memory_ids and their tiers, and
    whether any lesson record already discusses the identical text (purely
    informational; see module docstring) -- so a reader can re-derive the
    decision by hand rather than trusting the count.
    """
    from .memory import MemoryStore

    min_occurrences = int(min_occurrences)
    if min_occurrences < 2:
        raise ValueError(
            f"min_occurrences must be at least 2, got {min_occurrences}: a single "
            "correction is one event, not a repeated pattern, and filing a "
            "capability proposal from it is what section 64 forbids"
        )

    store = MemoryStore(Path(root))
    groups: Dict[str, Dict[str, Any]] = {}
    for status in CORRECTION_STATUSES:
        for record in store.find(None, status=status):
            reason = correction_reason_text(record)
            normalized = _norm_text(reason)
            if not normalized:
                continue
            key = correction_signature_key(reason)
            group = groups.setdefault(key, {
                "signature_key": key,
                "correction_reason": normalized,
                "correction_status": status,
                "contributions": [],
            })
            memory_id = str(record.get("memory_id") or "").strip()
            if memory_id and not any(
                c["memory_id"] == memory_id for c in group["contributions"]
            ):
                level = str(record.get("level") or "").strip() or "project"
                group["contributions"].append({"memory_id": memory_id, "level": level})

    lesson_texts = set(captured_lesson_claim_texts(root))

    patterns: List[Dict[str, Any]] = []
    for key in sorted(groups):
        group = groups[key]
        group["contributions"].sort(key=lambda c: c["memory_id"])
        group["memory_ids"] = [c["memory_id"] for c in group["contributions"]]
        group["occurrence_count"] = len(group["memory_ids"])
        group["min_occurrences"] = min_occurrences
        group["referenced_by_lesson"] = group["correction_reason"] in lesson_texts
        if group["occurrence_count"] < min_occurrences:
            continue
        patterns.append(group)
    return patterns


def _auto_filed_search_slot(slot: str) -> Dict[str, Any]:
    """A search slot that honestly records that no search happened.

    Mirrors capability_evolution._auto_filed_search_slot() exactly in
    intent: `matches` empty with `search_conclusive` FALSE is the whole
    point -- an empty conclusive search would be a claim of absence this
    code has no basis for, and MISSING is what licenses an ADD."""
    return {
        "matches": [],
        "search_basis": (
            "NOT SEARCHED -- filed automatically from repeated user-correction "
            "evidence in memory.py, with no repository search performed, so "
            "absence is not established and this candidate cannot leave "
            "EVIDENCE_GATHERING. Run: "
            + RESEARCH_GAP_ACTION_CATALOG["actions"][_SLOT_QUESTION[slot]]
        ),
        "search_conclusive": False,
    }


def _pattern_summary(pattern: Dict[str, Any]) -> str:
    reason = pattern.get("correction_reason") or ""
    return reason[:400] if reason else "no correction reason recorded"


def build_user_correction_candidate(
    root, pattern: Dict[str, Any], *,
    status_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble the DISCOVERED candidate for one repeated user-correction
    pattern.

    Goes through the ordinary build_candidate(), so the recommendation is
    DERIVED (it comes out UNKNOWN, because no search was performed), the
    confidence is recomputed through the real inference.score_confidence(),
    and the whole thing is schema-validated before it exists -- nothing here
    is a second candidate constructor.

    `evidence_refs_verified` is true because every memory_id in evidence_refs
    was read off disk by repeated_user_correction_patterns() a moment ago,
    which is what that flag means; it is not a claim about which side of the
    correction was right. `evidence_strength` is 2 (a real observation, not a
    controlled experiment), which by itself keeps ADD unreachable even if
    every search later came back conclusive and empty.
    """
    from .doc_extraction import evidence_ref

    key = pattern["signature_key"]
    summary = _pattern_summary(pattern)
    contributions = list(pattern["contributions"])

    fields: Dict[str, Any] = {
        "trigger_source": f"memory:user_correction_signature:{key}",
        "trigger_type": AUTO_DISCOVERY_TRIGGER_TYPE,
        "source_provenance": [
            evidence_ref(
                document=str(
                    Path(root) / ".dv-harness" / "memory" / c["level"] / f"{c['memory_id']}.json"
                ),
                version=key[:12],
                page="",
                section=f"status={pattern['correction_status']} correction reason",
                location=c["memory_id"],
            )
            for c in contributions
        ],
        "evidence_refs": [c["memory_id"] for c in contributions],
        "affected_capability": "agent-behavior-self-correction",
        "hypothesis": (
            f"Correction pattern {key[:12]} ({summary}) recurs across "
            "independently corrected memory records, and nothing in this "
            "harness prevents the agent from making the same kind of mistake "
            "again -- a human keeps having to correct the same class of "
            "error by hand. The recurrence is evidence about a capability "
            "this harness does not have (a check/guard that would have "
            "caught it before a human had to), not about one correction's "
            "circumstances. Deliberately depends only on the correction "
            "signature's own text, never on how many times it has been "
            "seen or which real MemoryGC status recorded it -- either would "
            "make candidate_id (minted from this exact string) drift across "
            "cycles instead of accumulating evidence on one record, exactly "
            "the property capability_evolution._failure_signature_summary()'s "
            "own docstring states the reason for."
        ),
        "proposed_action": (
            "No production change is proposed. Run the mandatory current-L5 "
            "check over this correction pattern -- the six existing_* "
            "searches this candidate filed as NOT SEARCHED -- and let "
            "decide_recommendation() derive KEEP/ENHANCE/ADD/EXPERIMENT from "
            "the real result. `dv-harness research` is the human entry point "
            "that operates that machinery."
        ),
        "exact_gap": "",
        "expected_verification_benefit": (
            "The same class of agent mistake stops needing a human to catch "
            "and correct it by hand every time it recurs, and the recurrence "
            "stops being visible only inside individual retracted/superseded "
            "memory records nobody has cross-referenced."
        ),
        "evidence_strength": {
            "scale": 2,
            "rationale": (
                f"{len(contributions)} independently corrected memory records "
                "cite the identical normalized correction reason. That is a "
                "real repeated observation of a human correcting the same "
                "mistake, not a controlled experiment comparing a change "
                "against a baseline."
            ),
        },
        "confidence": {
            "inputs": {
                "independent_sources_count": len(contributions),
                "evidence_refs_verified": True,
                "counter_evidence_count": 0,
                "multi_agent_consensus_count": 0,
            }
        },
        "implementation_difficulty": "UNKNOWN",
        "integration_risk": "UNKNOWN",
        "maintenance_cost": "UNKNOWN",
        "experiment_required": False,
        "experiment_plan": "",
        "benchmark_plan": "",
        "acceptance_criteria": [
            "All six existing_* searches are re-run with search_conclusive "
            "true, so overlap_status stops being UNKNOWN.",
            f"Either a documented guard/check now catches correction pattern "
            f"{key[:12]} before a human has to, or a named harness capability "
            "is shown to be the thing that is missing.",
            "The recommendation is derived by decide_recommendation() from "
            "those searches, never asserted by an agent.",
        ],
        "rollback_plan": (
            f"Filing applies nothing: one Blackboard entry under "
            f"'{BLACKBOARD_TOPIC}' and one Working Memory audit record, no "
            "production file touched. The undo is a REJECTED transition, "
            "which is legal directly from DISCOVERED. Any concrete change a "
            "later architect proposes must author its own rollback_plan "
            "before it may leave EVIDENCE_GATHERING."
        ),
        "approval_level": "HUMAN_APPROVAL_REQUIRED",
        "discovered_by": AUTO_DISCOVERY_BY,
    }
    for slot in L5_SEARCH_SLOTS:
        fields[slot] = _auto_filed_search_slot(slot)
    if status_history is not None:
        fields["status_history"] = [dict(entry) for entry in status_history]

    candidate = build_candidate(**fields)
    if candidate["current_status"] != "DISCOVERED":
        raise IllegalPromotionTransitionError(
            f"an auto-filed candidate was assembled at {candidate['current_status']!r}; "
            "the user-correction loop may only ever file at DISCOVERED"
        )
    return candidate


def file_user_correction_candidate(
    root, pattern: Dict[str, Any], *, cfg: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """File (or refresh) ONE candidate for a repeated user-correction pattern.

    Never transitions. Three outcomes, and the first two write nothing --
    identical shape to capability_evolution.file_repeated_failure_candidate():

      * ALREADY_BEYOND_DISCOVERED -- a human or a research-architect has
        already moved this candidate on. Re-filing would drag it backwards
        and overwrite their work, so this returns instead.
      * ALREADY_ON_FILE_UNCHANGED -- same candidate, same contributing
        records. Re-persisting would append a duplicate Working Memory audit
        record for no new information.
      * filed -- new, or the same candidate with genuinely new contributing
        records. The existing status_history is carried forward untouched:
        no state changed, so no transition entry is owed and none is
        invented.
    """
    candidate = build_user_correction_candidate(root, pattern)
    candidate_id = candidate["candidate_id"]
    existing = read_candidate(root, candidate_id)

    if existing is not None:
        current = existing.get("current_status")
        if current != "DISCOVERED":
            return {
                "filed": False, "reason": "ALREADY_BEYOND_DISCOVERED",
                "candidate_id": candidate_id, "current_status": current,
                "signature_key": pattern["signature_key"],
            }
        if list(existing.get("evidence_refs") or []) == candidate["evidence_refs"]:
            return {
                "filed": False, "reason": "ALREADY_ON_FILE_UNCHANGED",
                "candidate_id": candidate_id, "current_status": current,
                "signature_key": pattern["signature_key"],
            }
        candidate = build_user_correction_candidate(
            root, pattern, status_history=list(existing.get("status_history") or [])
        )

    persisted = persist_candidate(root, candidate, source=AUTO_DISCOVERY_BY, cfg=cfg)
    return {
        "filed": True,
        "reason": "NEW_EVIDENCE" if existing is not None else "DISCOVERED",
        "candidate_id": candidate_id,
        "current_status": candidate["current_status"],
        "signature_key": pattern["signature_key"],
        "occurrence_count": pattern["occurrence_count"],
        "evidence_refs": list(candidate["evidence_refs"]),
        "persisted": persisted,
    }


def file_candidates_for_user_corrections(
    root, *, min_occurrences: int = REPEAT_CORRECTION_MIN_OCCURRENCES,
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """The whole coupling, as one call a future engine hook (or a scheduled
    human-run pass) can make.

    Detect every repeated user-correction pattern, file a DISCOVERED
    candidate for each, and report what happened to every one -- including
    the ones deliberately left alone. Raises nothing it can help; a caller
    wiring this into an engine hook should treat any failure as best-effort,
    exactly as engine.py's own `_file_capability_evolution_candidates_from_
    repeated_failures()` treats `repeated_unresolved_failure_patterns()`.
    """
    return [
        file_user_correction_candidate(root, pattern, cfg=cfg)
        for pattern in repeated_user_correction_patterns(root, min_occurrences=min_occurrences)
    ]


# ---------------------------------------------------------------------------
# Standalone front door. No `dv-harness` CLI verb was added and cli.py/gates.py
# were not touched, per this item's own instruction to prefer a standalone
# "python -m dv_harness.<module>" door and disclose the CLI-wiring as a
# residual -- the same disclosed choice several sibling 2026-09-06 modules in
# this codebase already make.


def execute_verb(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.user_correction_trigger")
    parser.add_argument("--root", default=".", help="Project root (default: current directory).")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_detect = sub.add_parser("detect", help="List repeated user-correction patterns; files nothing.")
    p_detect.add_argument("--min-occurrences", type=int, default=REPEAT_CORRECTION_MIN_OCCURRENCES)

    p_file = sub.add_parser("file", help="Detect and file a DISCOVERED candidate for each pattern found.")
    p_file.add_argument("--min-occurrences", type=int, default=REPEAT_CORRECTION_MIN_OCCURRENCES)

    args = parser.parse_args(argv)
    root = Path(args.root)

    if args.verb == "detect":
        patterns = repeated_user_correction_patterns(root, min_occurrences=args.min_occurrences)
        print(json.dumps(patterns, ensure_ascii=False, indent=2))
        return 1 if patterns else 0

    if args.verb == "file":
        results = file_candidates_for_user_corrections(root, min_occurrences=args.min_occurrences)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 1 if any(r.get("filed") for r in results) else 0

    parser.error(f"unknown verb {args.verb!r}")
    return 2  # pragma: no cover -- parser.error() already raises SystemExit


def main() -> None:
    sys.exit(execute_verb())


if __name__ == "__main__":
    main()
