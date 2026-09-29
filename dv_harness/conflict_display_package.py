"""dv_harness/conflict_display_package.py -- the structured 9-field conflict
DISPLAY package (2026-09-07, structured_conflict_display_9field).

THE GAP THIS CLOSES. `source_authority.py`'s conflict-TYPE taxonomy
(`CONFLICT_TYPES`, `classify_conflict()`/`classify_conflict_type()`) already
labels WHICH TWO SOURCE TYPES a conflict compares, and its `escalate_conflict()`
already files every real mismatch as a real, persisted `question_queue.py`
record carrying both sides' evidence paths. Neither ever assembled the RENDERED
9-field side-by-side view a human reviewer actually reads -- so two renderers of
"the same conflict" could each pick a different subset of the real records and
call it the display. `user_answer_validator.py`'s CONTRADICTED verdict is a
second, structurally different real conflict shape this repo produces (a
user's own unverified claim vs. real, code-derived evidence) that had no
display of any kind either.

DISCLOSED RESIDUAL, stated rather than left to be discovered, mirroring
`question_queue.py`'s own analogous "Question Escalation Package" section:
this repository checkout does not carry the literal source document naming
this 9-field shape (a repo-wide search found no file containing it), so the
9 field NAMES below are this module's own defensible synthesis, built
directly from the task's own listed fields -- Conflict Type, Affected Fact,
Evidence A/B/C, [Source Version], Recommended Authority, Downstream Impact,
Next-Best-Action, User Decision -- reconciled to exactly 9 by folding "Source
Version" into each Evidence side's own record (every evidence entry already
IS one specific source at one specific tier/version -- see `source_version`
below) rather than a tenth, separately-repeated column. What IS load-bearing
regardless of the exact reconciliation, and enforced rather than merely
claimed: every one of the 9 fields is built from a REAL, already-computed
fact -- `source_authority.resolve_conflict()`'s own claims/verdict/rule,
`source_authority.classify_conflict()`'s own taxonomy, a REAL persisted
`question_queue.py` record, or a REAL `user_answer_validator.AnswerValidation`
-- never a fabricated value, and never a second, independently-computed
verdict that could disagree with either of those two real producers.

REUSE OVER REINVENT, on every field:
  - Field 1 (Conflict Type) is `source_authority.classify_conflict()`,
    called, never re-derived -- this module owns no second conflict-type
    taxonomy.
  - Field 6 (Recommended Authority) is `source_authority.resolve_conflict()`'s
    own `rule` string, carried through verbatim (plus, for a RESOLVED
    verdict, the winning claim's own label) -- the exact human-readable
    authority statement that module already computed, never re-worded.
  - Field 8 (Next-Best-Action) is `inference.next_best_action()`, the
    domain-neutral Gap -> Action engine section 10 of the master prompt
    forbids re-implementing, called through its `gap_action_catalog`
    parameter exactly the way `golden_flow_readiness.py` /
    `capability_evolution.py` / `verification_strategy.py` /
    `subsystem_practicality_score.py` already drive it with their own
    catalogs.
  - Field 9 (User Decision) is read directly off a REAL persisted
    `question_queue.py` question record's own `status`/`answer`/
    `decided_by`/`answered_at` fields (or, when a `QuestionQueueStore` is
    supplied, `find_decision()`'s own `current.source`) -- NEVER a machine
    default silently presented as a human decision. `question_queue.py`'s
    own `answer_question()` always persists `source="human_answer"`, so a
    record whose `status == "ANSWERED"` is guaranteed by that module's own
    code to be a real human decision; a `status == "ASSUMED"` record is
    just as certainly a Tier-2 auto-assumption (`add_question()`'s own
    Tier-2 branch), and this module reports that distinction explicitly
    rather than blurring "decided" into one undifferentiated word -- the
    same conflation `question_queue.py`'s own `_sync_decisions_to_blackboard()`
    docstring names as "precisely the conflation the 3-tier protocol exists
    to prevent."

TWO REAL CONFLICT SHAPES, TWO BUILDERS, ONE 9-FIELD RENDER.
  - `build_conflict_display_package_from_source_conflict()` -- a real
    `source_authority.resolve_conflict()` result (RESOLVED or
    UNDECIDABLE_SAME_AUTHORITY only; NO_CONFLICT is refused, mirroring
    `escalate_conflict()`'s own "returns None for NO_CONFLICT: agreement is
    not a question"), optionally joined against the REAL persisted
    `question_queue.py` record `escalate_conflict()` filed for it.
  - `build_conflict_display_package_from_answer_validation()` -- a real
    `user_answer_validator.AnswerValidation` whose `status` is CONTRADICTED
    (any other status is refused: PARTIALLY_VALIDATED/UNVERIFIABLE are not
    conflicts this module renders, and VALIDATED has nothing to display).

WHAT THIS MODULE DOES NOT DO. It arbitrates nothing -- deciding a display
never means the losing side of a conflict is fine to leave wrong, the exact
posture `source_authority.resolve_conflict()` itself already takes.
`escalate_conflict()`/`answer_question()` stay the only real ways a conflict
is filed or answered; this module never calls either. It runs no build, job,
gate, or approval, and holds no stage gate of its own -- it is a pure,
read-only rendering layer over facts other real modules already computed."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import source_authority
from . import inference

try:
    from . import user_answer_validator as _uav
except Exception:  # pragma: no cover -- defensive only; the module is real and ships
    _uav = None

try:
    from . import change_cascade as _change_cascade
except Exception:  # pragma: no cover -- defensive only; best-effort reuse
    _change_cascade = None


class ConflictDisplayError(ValueError):
    """Typed error, matching this codebase's own convention (a short
    SCREAMING_SNAKE_CASE `reason` plus a concrete `detail` dict) -- never a
    silently-dropped conflict or a silently-guessed field."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


#: The 9 named fields of a Conflict Display Package, in a fixed order --
#: every builder's only output shape, mirroring
#: `question_queue.ESCALATION_PACKAGE_FIELDS`'s own convention.
CONFLICT_DISPLAY_FIELDS: tuple = (
    "conflict_type", "affected_fact", "evidence_a", "evidence_b", "evidence_c",
    "recommended_authority", "downstream_impact", "next_best_action", "user_decision",
)

#: This module's own conflict-type constant for the AnswerValidation shape --
#: a user's own unverified claim vs. real code-derived evidence. Deliberately
#: NOT a member of `source_authority.CONFLICT_TYPES` (that taxonomy compares
#: two ranked AUTHORITY_ORDER-shaped sources; a bare user claim carries no
#: rank at all) -- checked disjoint at import time so the two vocabularies can
#: never silently collide.
CONFLICT_TYPE_USER_CLAIM_VS_EVIDENCE = "USER_CLAIM_VS_EVIDENCE_CONFLICT"


def assert_no_conflict_type_vocabulary_collision() -> None:
    """Run at import (below): proves `CONFLICT_TYPE_USER_CLAIM_VS_EVIDENCE`
    never silently collides with a real `source_authority.CONFLICT_TYPES`
    member -- the same "checked, not merely claimed" discipline several
    sibling domain-vocabulary modules in this codebase already apply to
    themselves."""
    if CONFLICT_TYPE_USER_CLAIM_VS_EVIDENCE in source_authority.CONFLICT_TYPES:
        raise AssertionError(
            "CONFLICT_TYPE_USER_CLAIM_VS_EVIDENCE collides with a real "
            "source_authority.CONFLICT_TYPES member -- pick a different name"
        )

#: The honest default when no explicit user decision has been supplied at
#: all -- never silently blank, never silently read as "no decision needed".
USER_DECISION_NOT_ESCALATED = "PENDING_NOT_ESCALATED"

assert_no_conflict_type_vocabulary_collision()


# ---------------------------------------------------------------------------
# Next-Best-Action catalogs, reused through inference.next_best_action()'s
# own `gap_action_catalog` parameter -- never a second gap->action engine.
# ---------------------------------------------------------------------------

_SOURCE_CONFLICT_ACTION_CATALOG: dict = {
    "source": "conflict_display_package.source_conflict",
    "actions": {
        source_authority.VERDICT_RESOLVED: (
            "the higher-authority value is what execution uses today; file/confirm the "
            "escalation via source_authority.escalate_conflict() so a human decides which "
            "artifact (the winning or the losing one) is actually stale or wrong"
        ),
        source_authority.VERDICT_UNDECIDABLE: (
            "the authority order cannot break this tie -- a human must pick a side via "
            "question_queue.QuestionQueueStore.answer_question() on the filed escalation; "
            "no value should be assumed correct until then"
        ),
    },
    "fallback": "review this {gap}-verdict conflict manually; no catalog action is defined for it",
}

_ANSWER_VALIDATION_ACTION_CATALOG: dict = {
    "source": "conflict_display_package.answer_validation_conflict",
    "actions": {
        _uav.CONTRADICTED if _uav is not None else "CONTRADICTED": (
            "correct the intake answer to match the real evidence cited above, then "
            "re-run user_answer_validator.validate_answer() to confirm the correction"
        ),
    },
    "fallback": "review this {gap}-status answer validation manually",
}


# ---------------------------------------------------------------------------
# Evidence-side formatting -- shared by both builders.
# ---------------------------------------------------------------------------

def _evidence_side(*, source: str, source_version: Optional[str], claim: str,
                    evidence_path: Optional[str]) -> Dict[str, Optional[str]]:
    return {"source": source, "source_version": source_version, "claim": claim,
            "evidence_path": evidence_path}


def _evidence_sides_from_claims(claims: List[dict]) -> List[Dict[str, Optional[str]]]:
    """One `_evidence_side()` dict per real `SourceClaim.to_dict()` entry
    (source_authority.py's own already-normalized claim shape), in the
    already-authority-ranked order `resolve_conflict()` produced. `source_version`
    is this module's own reconciliation of the task's "Source Version" field
    into each evidence side -- the tier/doc_phrase that IS this claim's
    source, at this authority-order version, never a fabricated separate
    field."""
    sides = []
    for c in claims:
        qualifier = f" ({c['qualifier']})" if c.get("qualifier") else ""
        sides.append(_evidence_side(
            source=c["source"],
            source_version=f"tier {c['rank']}: {c['doc_phrase']}{qualifier}",
            claim=c["claim"],
            evidence_path=c["evidence_path"],
        ))
    return sides


def _pad_to_three(sides: List[dict]) -> List[Optional[dict]]:
    padded = list(sides[:3])
    while len(padded) < 3:
        padded.append(None)
    return padded


# ---------------------------------------------------------------------------
# Downstream impact -- best-effort reuse of change_cascade.py's own real,
# hand-curated {changed_field -> downstream artifacts} table when the
# affected fact happens to name one of its declared fields; otherwise the
# caller's own declared assessment, or an honest NOT_ASSESSED -- never
# invented here.
# ---------------------------------------------------------------------------

def _derive_downstream_impact(affected_fact: str, override: Optional[str]) -> str:
    if override is not None:
        return override
    if _change_cascade is not None:
        try:
            known = set(_change_cascade.known_changed_fields())
        except Exception:
            known = set()
        if affected_fact in known:
            try:
                cascade = _change_cascade.cascade_for_changed_field(affected_fact)
                if cascade.status == _change_cascade.STATUS_MAPPED and cascade.artifacts:
                    names = "; ".join(
                        f"{a.artifact} ({a.reason})" for a in cascade.artifacts
                    )
                    return f"change_cascade.py ({affected_fact}): {names}"
            except Exception:
                pass
    return ("NOT_ASSESSED -- no downstream-impact evidence was supplied by the caller, and "
            f"{affected_fact!r} is not one of change_cascade.py's own declared changed_fields")


# ---------------------------------------------------------------------------
# User decision -- read directly off a REAL persisted question_queue.py
# record, never a fabricated "decided" value.
# ---------------------------------------------------------------------------

def _derive_user_decision(question_record: Optional[dict], store: Optional[Any]) -> str:
    if question_record is None:
        return USER_DECISION_NOT_ESCALATED

    status = question_record.get("status")
    answer = question_record.get("answer")
    decided_by = question_record.get("decided_by")
    answered_at = question_record.get("answered_at")
    basis = question_record.get("basis")
    qid = question_record.get("id")
    tier = question_record.get("tier")

    if status == "OPEN":
        return (f"PENDING -- Tier-{tier} escalation Q-ID {qid} is still awaiting a real human "
                f"answer (blocking={question_record.get('blocking')})")
    if status == "ANSWERED":
        # question_queue.answer_question() always persists source="human_answer" -- this
        # status can never be reached any other way, so this IS a real human decision.
        return (f"DECIDED_BY_HUMAN: {answer!r} (decided_by={decided_by}, at={answered_at}, "
                f"basis={basis!r})")
    if status == "ASSUMED":
        # add_question()'s Tier-2 branch always persists source="tier2_auto_assumption" --
        # this is a machine default, never a human decision, and must never be presented
        # as one.
        return (f"TIER2_AUTO_ASSUMPTION (not a human decision): {answer!r} -- a real human "
                f"answer via question_queue.answer_question() would overturn it")
    if status == "SELF_RESOLVED":
        if store is not None:
            try:
                prior = store.find_decision(question_record.get("question_key"))
            except Exception:
                prior = None
            if prior is not None:
                current = prior.get("current") or {}
                src = current.get("source")
                label = "DECIDED_BY_HUMAN" if src == "human_answer" else (
                    "TIER2_AUTO_ASSUMPTION (not a human decision)" if src == "tier2_auto_assumption"
                    else f"SELF_RESOLVED (source={src!r})")
                return (f"{label}: {current.get('answer')!r} (decided_by={current.get('decided_by')}, "
                        f"at={current.get('decided_at')})")
        return (f"SELF_RESOLVED: {answer!r} (decided_by={decided_by}) -- the real source of "
                f"the prior decision this self-resolved from was not verified because no "
                f"QuestionQueueStore was supplied to check it")
    return f"UNKNOWN_STATUS:{status}"


# ---------------------------------------------------------------------------
# Builder 1 -- a real source_authority.resolve_conflict()/escalate_conflict()
# conflict.
# ---------------------------------------------------------------------------

def build_conflict_display_package_from_source_conflict(
    conflict: dict, *, subject: str, question_record: Optional[dict] = None,
    store: Optional[Any] = None, downstream_impact: Optional[str] = None,
    root: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the 9-field display package for a real
    `source_authority.resolve_conflict()` result.

    `subject` is REQUIRED and never inferred -- the same "Affected Fact" a
    caller must already name to call `escalate_conflict(..., subject=...)`
    in the first place; inventing one from the conflict's own claim text
    would misrepresent what the conflict is actually about.

    `question_record` is the REAL persisted `question_queue.py` record
    `escalate_conflict()` filed for this exact conflict (via
    `store.get_question(question_id)` or the record `escalate_conflict()`
    itself returned) -- optional, since a conflict may be displayed before
    it has ever been escalated; when supplied, `store` (the
    `QuestionQueueStore` it came from) lets User Decision report the real
    human-vs-auto-assumption `source` for a SELF_RESOLVED record too.

    Raises `ConflictDisplayError` for a `NO_CONFLICT` verdict (there is
    nothing to display -- agreement is not a conflict, mirroring
    `escalate_conflict()`'s own identical refusal) or for a malformed
    `conflict`/`subject`."""
    if not isinstance(conflict, dict):
        raise ConflictDisplayError("CONFLICT_MUST_BE_A_DICT", {"got": type(conflict).__name__})
    if not str(subject or "").strip():
        raise ConflictDisplayError("SUBJECT_REQUIRED", {
            "hint": "the Affected Fact must be named explicitly, never inferred from claim text"})

    verdict = conflict.get("verdict")
    if verdict == source_authority.VERDICT_NO_CONFLICT:
        raise ConflictDisplayError("NO_CONFLICT_HAS_NOTHING_TO_DISPLAY", {
            "hint": "every source stated the same thing; there is no conflict to render"})
    if verdict not in (source_authority.VERDICT_RESOLVED, source_authority.VERDICT_UNDECIDABLE):
        raise ConflictDisplayError("UNKNOWN_CONFLICT_VERDICT", {"verdict": verdict})

    claims = conflict.get("claims") or []
    if len(claims) < 2:
        raise ConflictDisplayError("CONFLICT_NEEDS_AT_LEAST_TWO_CLAIMS", {"claim_count": len(claims)})
    if len(claims) > 3:
        raise ConflictDisplayError("CONFLICT_SIDES_MUST_BE_2_TO_3", {
            "side_count": len(claims),
            "hint": "this 9-field display has exactly 3 evidence slots (A/B/C); a wider "
                    "conflict should be split into pairwise displays, matching "
                    "escalate_conflict()'s own 2-3-sides rule"})

    try:
        conflict_type = source_authority.classify_conflict(conflict)
    except source_authority.SourceAuthorityError as exc:
        # classify_conflict() is a genuinely PAIRWISE classifier -- more than
        # 2 distinct AUTHORITY_ORDER source TYPES (e.g. a real 3-sided
        # dut_rtl/controller_doc/ip_user_guide conflict, which
        # escalate_conflict()'s own 2-3-SIDES rule permits) is a real,
        # disclosed scope boundary of that module, never a bug this module
        # should work around by guessing a pairwise label that does not
        # apply. The rest of the display still builds honestly; only the
        # taxonomy label is reported as genuinely unclassifiable.
        conflict_type = f"UNCLASSIFIED_MULTI_SOURCE_TYPE_CONFLICT ({exc.reason})"

    evidence_a, evidence_b, evidence_c = _pad_to_three(_evidence_sides_from_claims(claims))

    if verdict == source_authority.VERDICT_RESOLVED:
        winner = conflict.get("winner") or {}
        recommended_authority = (
            f"{conflict.get('rule')} Winning side: {winner.get('doc_phrase')} "
            f"(tier {winner.get('rank')}): {winner.get('claim')}"
        )
    else:
        recommended_authority = str(conflict.get("rule"))

    downstream = _derive_downstream_impact(subject, downstream_impact)

    action_results = inference.next_best_action(
        conflict_type, [verdict], root, gap_action_catalog=_SOURCE_CONFLICT_ACTION_CATALOG,
    )
    next_best_action = action_results[0]["suggested_action"] if action_results else "NOT_ASSESSED"

    user_decision = _derive_user_decision(question_record, store)

    return {
        "conflict_type": conflict_type,
        "affected_fact": subject,
        "evidence_a": evidence_a,
        "evidence_b": evidence_b,
        "evidence_c": evidence_c,
        "recommended_authority": recommended_authority,
        "downstream_impact": downstream,
        "next_best_action": next_best_action,
        "user_decision": user_decision,
    }


# ---------------------------------------------------------------------------
# Builder 2 -- a real user_answer_validator.AnswerValidation whose status is
# CONTRADICTED.
# ---------------------------------------------------------------------------

_CLAIM_TYPE_EVIDENCE_SOURCE_LABEL: Dict[str, str] = {
    "MODULE_EXISTENCE": "verible_parser.py (verible-verilog-syntax, real RTL parse)",
    "FILE_BUILD_INCLUSION": "env_manifest.py (dut_facts.rtl, real recorded build facts)",
}


def build_conflict_display_package_from_answer_validation(
    validation: Any, *, downstream_impact: Optional[str] = None,
    user_decision: Optional[str] = None, root: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the 9-field display package for a real
    `user_answer_validator.AnswerValidation` whose `status` is CONTRADICTED
    -- a real intake claim that real, code-derived evidence has already
    proven false.

    `validation` accepts either an `AnswerValidation` instance or its
    `.to_dict()` shape.

    `user_decision` must be supplied by the caller (there is no persisted
    question_queue.py record inherent to an AnswerValidation the way there
    is for a source_authority conflict) -- absent one, the honest
    `USER_DECISION_NOT_ESCALATED` default is used rather than inventing a
    decision nobody made.

    Raises `ConflictDisplayError` for any status other than CONTRADICTED --
    VALIDATED has nothing to display, and PARTIALLY_VALIDATED/UNVERIFIABLE
    are not conflicts this module renders."""
    if hasattr(validation, "to_dict"):
        validation = validation.to_dict()
    if not isinstance(validation, dict):
        raise ConflictDisplayError("VALIDATION_MUST_BE_A_DICT_OR_ANSWERVALIDATION", {
            "got": type(validation).__name__})

    status = validation.get("status")
    contradicted = _uav.CONTRADICTED if _uav is not None else "CONTRADICTED"
    if status != contradicted:
        raise ConflictDisplayError("ONLY_CONTRADICTED_VALIDATIONS_HAVE_A_CONFLICT_TO_DISPLAY", {
            "status": status,
            "hint": "VALIDATED has nothing to display; PARTIALLY_VALIDATED/UNVERIFIABLE are "
                    "not conflicts this module renders"})

    claim_type = validation.get("claim_type")
    target = validation.get("target")
    raw_text = validation.get("raw_text")
    reason = validation.get("reason")
    evidence_list = validation.get("evidence") or []

    affected_fact = f"{claim_type}: {target}"

    evidence_a = _evidence_side(
        source="USER_CLAIM (unverified)", source_version=claim_type, claim=raw_text,
        evidence_path=None,
    )
    evidence_b = _evidence_side(
        source="REAL_EVIDENCE",
        source_version=_CLAIM_TYPE_EVIDENCE_SOURCE_LABEL.get(claim_type, claim_type),
        claim=reason,
        evidence_path="; ".join(evidence_list) if evidence_list else None,
    )
    evidence_c = None

    recommended_authority = (
        "Per the Evidence Truth Rule, real code-derived evidence always outranks an "
        "unverified user claim once real evidence directly contradicts it -- the claim, "
        "not the evidence, must be corrected."
    )

    downstream = _derive_downstream_impact(affected_fact, downstream_impact)

    action_results = inference.next_best_action(
        "user_answer_validation", [status], root, gap_action_catalog=_ANSWER_VALIDATION_ACTION_CATALOG,
    )
    next_best_action = action_results[0]["suggested_action"] if action_results else "NOT_ASSESSED"

    return {
        "conflict_type": CONFLICT_TYPE_USER_CLAIM_VS_EVIDENCE,
        "affected_fact": affected_fact,
        "evidence_a": evidence_a,
        "evidence_b": evidence_b,
        "evidence_c": evidence_c,
        "recommended_authority": recommended_authority,
        "downstream_impact": downstream,
        "next_best_action": next_best_action,
        "user_decision": user_decision if user_decision is not None else USER_DECISION_NOT_ESCALATED,
    }


# ---------------------------------------------------------------------------
# Rendering -- reuses connectivity.render_markdown_table() for the
# side-by-side Evidence A/B/C comparison, this repo's one parameterized
# table renderer, rather than a second hand-rolled table loop.
# ---------------------------------------------------------------------------

def _evidence_column(side: Optional[dict], row_key: str) -> str:
    if side is None:
        return "-"
    v = side.get(row_key)
    return str(v) if v is not None else "-"


def render_conflict_display_markdown(package: Dict[str, Any], *, title: Optional[str] = None) -> str:
    """Render the 9-field package: a summary block for the 6 single-value
    fields, then Evidence A/B/C SHOWN SIDE BY SIDE as one table (this
    module's own literal, disclosed reconciliation of the task's "shown
    side-by-side" instruction -- the fields that genuinely vary per source
    belong next to each other for direct comparison; the fields that are a
    property of the WHOLE conflict do not)."""
    for k in CONFLICT_DISPLAY_FIELDS:
        if k not in package:
            raise ConflictDisplayError("PACKAGE_MISSING_FIELD", {"field": k})

    from . import connectivity

    heading = title or package["affected_fact"]
    lines = [f"### {heading}", ""]
    lines.append(f"- **Conflict Type:** {package['conflict_type']}")
    lines.append(f"- **Affected Fact:** {package['affected_fact']}")
    lines.append(f"- **Recommended Authority:** {package['recommended_authority']}")
    lines.append(f"- **Downstream Impact:** {package['downstream_impact']}")
    lines.append(f"- **Next-Best-Action:** {package['next_best_action']}")
    lines.append(f"- **User Decision:** {package['user_decision']}")
    lines.append("")
    lines.append("**Evidence, side by side:**")
    lines.append("")

    sides = [package.get("evidence_a"), package.get("evidence_b"), package.get("evidence_c")]
    columns = [("row", "")]
    labels = ["Evidence A", "Evidence B", "Evidence C"]
    present_idx = [i for i, s in enumerate(sides) if s is not None]
    for i in present_idx:
        columns.append((f"col{i}", labels[i]))

    row_keys = [("source", "Source"), ("source_version", "Source Version"),
                ("claim", "Claim"), ("evidence_path", "Evidence Path")]
    rows = []
    for key, label in row_keys:
        row = {"row": label}
        for i in present_idx:
            row[f"col{i}"] = _evidence_column(sides[i], key)
        rows.append(row)

    lines.append(connectivity.render_markdown_table(columns, rows))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone front door -- no `dv-harness` CLI verb wired here; `cli.py` and
# `gates.py` are large files under concurrent edit pressure from many other
# items in this same batch, the same disclosed choice several sibling
# same-day modules in this codebase already make.
# ---------------------------------------------------------------------------

def execute_verb(args) -> int:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="conflict-display-package")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_src = sub.add_parser("from-source-conflict",
                            help="build+render a package from a real "
                                 "source_authority.resolve_conflict() JSON result")
    p_src.add_argument("--conflict", required=True, help="path to a resolve_conflict()-shaped JSON file")
    p_src.add_argument("--subject", required=True)
    p_src.add_argument("--question-record", default=None,
                        help="optional path to a real persisted question_queue.py record JSON")
    p_src.add_argument("--json", action="store_true")

    p_av = sub.add_parser("from-answer-validation",
                           help="build+render a package from a real "
                                "user_answer_validator.AnswerValidation JSON result")
    p_av.add_argument("--validation", required=True,
                       help="path to an AnswerValidation.to_dict()-shaped JSON file")
    p_av.add_argument("--user-decision", default=None)
    p_av.add_argument("--json", action="store_true")

    ns = parser.parse_args(args)

    try:
        if ns.verb == "from-source-conflict":
            from pathlib import Path
            conflict = _json.loads(Path(ns.conflict).read_text(encoding="utf-8"))
            qrecord = None
            if ns.question_record:
                qrecord = _json.loads(Path(ns.question_record).read_text(encoding="utf-8"))
            package = build_conflict_display_package_from_source_conflict(
                conflict, subject=ns.subject, question_record=qrecord)
        else:
            from pathlib import Path
            validation = _json.loads(Path(ns.validation).read_text(encoding="utf-8"))
            package = build_conflict_display_package_from_answer_validation(
                validation, user_decision=ns.user_decision)
    except ConflictDisplayError as exc:
        print(_json.dumps({"error": exc.reason, "detail": exc.detail}, indent=2))
        return 2

    if ns.json:
        print(_json.dumps(package, indent=2, default=str))
    else:
        print(render_conflict_display_markdown(package))
    return 0


def main() -> None:
    import sys
    sys.exit(execute_verb(sys.argv[1:]))


if __name__ == "__main__":
    main()
