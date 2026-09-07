"""dv_harness/evidence_integrity_states.py -- Evidence Integrity state
classifier: VALID / STALE / SUPERSEDED / CONTRADICTED / CORRUPT (2026-09-07).

THE GAP THIS CLOSES
--------------------
Two real, independently-tested mechanisms already decide whether a piece of
recorded evidence is still trustworthy, and each answers a NARROWER question
than a human auditing "is this evidence still good" actually needs:

  * `golden_scenario.evaluate_freshness()` -- FRESH / STALE / UNKNOWN for one
    golden-scenario capsule, derived from the real `change_impact` git diff
    and VIP/tool version drift since the capsule's own `verified_sha`.
  * `signoff_export.evaluate_freeze_invalidation()` -- VALID / INVALIDATED /
    UNKNOWN for one frozen signoff baseline, derived from three real
    comparisons (per-field digest divergence, post-freeze git impact
    analysis, bundle content-hash integrity).

Neither speaks the vocabulary an evidence-integrity AUDIT needs: "did the
world just move past this evidence (STALE)", "did a NEWER, more complete
record appear where this one had nothing (SUPERSEDED)", "does the evidence
we can still see actively DISAGREE with what was recorded (CONTRADICTED)",
or "is the evidence artifact itself gone, unreadable, or altered
(CORRUPT)" -- four genuinely different findings that both FRESH/STALE/UNKNOWN
and VALID/INVALIDATED/UNKNOWN currently compress into one bit of "trouble".

WHAT THIS MODULE IS -- AND IS NOT
----------------------------------
A pure FOLD, nothing else. `classify_capsule_integrity()` and
`classify_freeze_integrity()` call the two real functions above and reuse
their own output verbatim as `underlying_fact` -- this module derives NO
freshness fact, runs no git diff, and recomputes no bundle hash of its own.
Its entire job is translating the REAL facts those two functions already
computed into the five-value `EVIDENCE_INTEGRITY_STATES` vocabulary:

  * a capsule's FRESH/STALE/UNKNOWN maps onto VALID/STALE/UNKNOWN -- a bare
    freshness check has no way to distinguish CONTRADICTED/CORRUPT/SUPERSEDED
    from a still-fresh or now-stale capsule, and this module never invents
    that distinction where the reused function does not supply it;
  * a freeze's per-finding `code` (`BASELINE_FIELD_CHANGED`,
    `BASELINE_EVIDENCE_DISAPPEARED`, `NEW_EVIDENCE_AFTER_FREEZE`,
    `POST_FREEZE_MATERIAL_CHANGE`, the three `FROZEN_BUNDLE_*` codes, ...)
    folds into CONTRADICTED / CORRUPT / SUPERSEDED / STALE / UNKNOWN
    per-code, worst-wins across every finding on the record.

HONESTY RULES, enforced in code
--------------------------------
  * The five named states are never the whole vocabulary. `UNKNOWN` is a
    sixth, deliberately-separate sentinel: a capsule with no `verified_sha`,
    a freeze with no recorded git HEAD, a record this module cannot even
    recognize the shape of -- none of these mean "the evidence is fine" and
    none of them are guessed into one of the five named states. "We could
    not check" must never read as VALID.
  * A freeze finding `code` this module has not been taught (an older or a
    future `signoff_export.py`) is never silently ignored and never folded
    to a state weaker than its own real `severity` warrants: an
    unrecognized INVALIDATING code still folds to CONTRADICTED (not the
    softer UNKNOWN), and an unrecognized INDETERMINATE code folds to
    UNKNOWN -- see `_UNRECOGNIZED_FALLBACK`. A silently-ignored future
    finding code would be exactly the "confidently wrong because nobody
    updated the mapping" failure this rule exists to prevent.
  * A record this module cannot identify as a golden_scenario capsule or a
    signoff freeze (a bare `normalized_evidence` row with no capsule or
    freeze wrapping it, an unrelated dict) reports UNKNOWN naming exactly
    why -- never a fabricated state, because neither reused function can be
    run against it at all.
  * Reading is never a mutating act: every classifier here only calls the
    two REUSED functions (both read-only) and, for the by-reference/
    project-wide conveniences, opens the real evidence store/freeze
    directory READ-ONLY. Nothing here approves, freezes, revalidates, or
    records anything -- there is deliberately no stage gate.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import golden_scenario
from . import signoff_export

SCHEMA_VERSION = "1.0"


# --- the five-state vocabulary (+ the honest UNKNOWN sentinel) -------------

VALID = "VALID"
STALE = "STALE"
SUPERSEDED = "SUPERSEDED"
CONTRADICTED = "CONTRADICTED"
CORRUPT = "CORRUPT"
UNKNOWN = "UNKNOWN"

#: The five named states this module reports "for", in the order the item's
#: own title lists them.
EVIDENCE_INTEGRITY_STATES: Tuple[str, ...] = (
    VALID, STALE, SUPERSEDED, CONTRADICTED, CORRUPT)

#: Every value a classification result's `state` field can actually hold.
ALL_STATES: Tuple[str, ...] = EVIDENCE_INTEGRITY_STATES + (UNKNOWN,)

#: Worst-wins fold order (most severe first), used whenever more than one
#: real finding contributes to a single record's classification.
#: CORRUPT > CONTRADICTED > STALE: the evidence artifact itself being gone
#: or altered is worse than the recorded claim merely disagreeing with a
#: still-present artifact, which is in turn worse than the world having
#: simply moved past a still-intact, still-agreeing record.
#: UNKNOWN sits ABOVE the merely-informational SUPERSEDED (a confirmed "we
#: could not verify this" must never be presented as a lesser concern than
#: a confirmed, benign "newer evidence appeared") and BELOW every confirmed
#: problem -- the same "an unresolved Critical UNKNOWN must never silently
#: read as clean, but a confirmed defect still outranks not knowing" rule
#: `platform_health.py`/`golden_flow_readiness.py` already apply one domain
#: over.
_STATE_SEVERITY: Dict[str, int] = {
    CORRUPT: 5, CONTRADICTED: 4, STALE: 3, UNKNOWN: 2, SUPERSEDED: 1, VALID: 0,
}


def _worse(a: str, b: str) -> str:
    return a if _STATE_SEVERITY[a] >= _STATE_SEVERITY[b] else b


class EvidenceIntegrityError(Exception):
    """A caller-usage error -- an argument this module cannot make sense of
    at all. Never raised for an honestly-absent fact, which reports
    `UNKNOWN` naming the reason instead of raising."""


# --- capsule (golden_scenario) folding --------------------------------------

#: golden_scenario.evaluate_freshness()'s own three-value vocabulary,
#: mapped onto this module's states. A bare freshness check cannot
#: distinguish CONTRADICTED/CORRUPT/SUPERSEDED from FRESH/STALE/UNKNOWN, so
#: this module never claims one of those three states for a capsule.
_FRESHNESS_TO_STATE: Dict[str, str] = {
    golden_scenario.FRESH: VALID,
    golden_scenario.STALE: STALE,
    golden_scenario.UNKNOWN: UNKNOWN,
}


def classify_capsule_integrity(root, capsule: "golden_scenario.GoldenScenario", *,
                                head: str = "HEAD",
                                current_vip_versions: Optional[Dict[str, str]] = None,
                                diff: Optional[dict] = None) -> Dict[str, Any]:
    """One golden-scenario capsule's evidence integrity state, folded from
    the REAL `golden_scenario.evaluate_freshness()` verdict alone -- never a
    second, independently-derived freshness check.

    `head`/`current_vip_versions`/`diff` are passed straight through to
    `evaluate_freshness()`, the same injectable seam that function already
    offers for batching and for testing its UNKNOWN branches without
    breaking a repository.
    """
    freshness_report = golden_scenario.evaluate_freshness(
        root, capsule, head=head, current_vip_versions=current_vip_versions, diff=diff)
    freshness = freshness_report.get("freshness")
    state = _FRESHNESS_TO_STATE.get(freshness, UNKNOWN)
    reasons = list(freshness_report.get("reasons") or [])
    if freshness not in _FRESHNESS_TO_STATE:
        reasons = reasons + [
            f"UNRECOGNIZED_FRESHNESS_VALUE:{freshness!r} -- treated as UNKNOWN "
            "rather than guessed"]
    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "GOLDEN_SCENARIO_CAPSULE",
        "capsule_id": getattr(capsule, "capsule_id", None),
        "evidence_id": getattr(capsule, "evidence_id", None),
        "state": state,
        "reasons": reasons,
        "fact_source": "golden_scenario.evaluate_freshness",
        "underlying_fact": freshness_report,
    }


# --- freeze (signoff_export) folding ----------------------------------------

#: Which of `evaluate_freeze_invalidation()`'s real finding codes fold onto
#: which integrity state. A code absent from BOTH this table and
#: `_IGNORED_FREEZE_FINDING_CODES` below is UNRECOGNIZED and folded in via
#: its own real `severity` instead (see `_fold_freeze_findings` /
#: `_UNRECOGNIZED_FALLBACK`) -- never silently dropped.
_FREEZE_FINDING_STATE: Dict[str, str] = {
    # The evidence ARTIFACT itself is gone, unreadable, or its content no
    # longer matches what was recorded at freeze time -- integrity of the
    # artifact, not merely of the claim.
    "FROZEN_BUNDLE_NOT_FOUND": CORRUPT,
    "FROZEN_BUNDLE_MANIFEST_MALFORMED": CORRUPT,
    "FROZEN_BUNDLE_CHANGED": CORRUPT,
    "BASELINE_EVIDENCE_DISAPPEARED": CORRUPT,
    # A field that WAS captured at freeze time now re-derives to a
    # different value -- the current, still-computable truth actively
    # disagrees with the recorded claim.
    "BASELINE_FIELD_CHANGED": CONTRADICTED,
    # The design/RTL/testbench moved since the freeze -- the recorded
    # evidence itself is untouched and un-contradicted, but the world has
    # moved past it.
    "POST_FREEZE_MATERIAL_CHANGE": STALE,
    # A field that had NO evidence at freeze time now has some -- the
    # earlier absence is superseded by a newer, more complete record.
    "NEW_EVIDENCE_AFTER_FREEZE": SUPERSEDED,
    # We could not even run the comparison (no recorded git HEAD, a broken
    # diff) -- an honest "could not check", never a clean pass.
    "POST_FREEZE_IMPACT_ANALYSIS_UNAVAILABLE": UNKNOWN,
}

#: A code whose own meaning is benign schema evolution ("the frozen record
#: predates this baseline field, so nothing about it can be compared") --
#: never a fact about integrity, and deliberately excluded from the fold
#: rather than falling into the "unrecognized" bucket, which would
#: misclassify it via its SEV_INDETERMINATE severity.
_IGNORED_FREEZE_FINDING_CODES = frozenset({"FIELD_NOT_IN_FROZEN_BASELINE"})

#: An unrecognized finding code (an older or a future `signoff_export.py`)
#: folds in by its own real severity rather than being silently dropped: an
#: INVALIDATING code we do not have a specific bucket for is still at least
#: as bad as CONTRADICTED (never the softer UNKNOWN); an INDETERMINATE code
#: we do not recognize is UNKNOWN, matching every other honestly-unresolved
#: fact this module reports.
_UNRECOGNIZED_FALLBACK: Dict[str, str] = {
    signoff_export.SEV_INVALIDATING: CONTRADICTED,
    signoff_export.SEV_INDETERMINATE: UNKNOWN,
}


def _fold_freeze_findings(findings: Sequence[dict]) -> Dict[str, Any]:
    """Worst-wins fold of `evaluate_freeze_invalidation()`'s own `findings`
    list into one state, plus the per-finding contribution that produced
    it. A pure function over already-computed findings -- it recomputes
    nothing about git, digests, or bundles."""
    state = VALID
    contributions: List[Dict[str, Any]] = []
    for f in findings or []:
        code = f.get("code")
        if code in _IGNORED_FREEZE_FINDING_CODES:
            continue
        mapped = _FREEZE_FINDING_STATE.get(code)
        if mapped is None:
            severity = f.get("severity")
            mapped = _UNRECOGNIZED_FALLBACK.get(severity, UNKNOWN)
            note = (f"UNRECOGNIZED_FREEZE_FINDING_CODE:{code} "
                    f"(severity={severity!r}, folded via its own severity)")
        else:
            note = code
        contributions.append({
            "code": code, "field": f.get("field"), "mapped_state": mapped,
            "note": note, "detail": f.get("detail"),
        })
        state = _worse(state, mapped)
    return {"state": state, "contributions": contributions}


def classify_freeze_integrity(root, frozen: dict, *, head: str = "HEAD",
                               diff: Optional[dict] = None,
                               declared: Optional[dict] = None,
                               current_baseline: Optional[dict] = None
                               ) -> Dict[str, Any]:
    """One signoff freeze record's evidence integrity state, folded from the
    REAL `signoff_export.evaluate_freeze_invalidation()` findings alone --
    never a second, independently-derived invalidation check.

    `head`/`diff`/`declared`/`current_baseline` are passed straight through
    to `evaluate_freeze_invalidation()`, the same injectable seam that
    function already offers.
    """
    invalidation_report = signoff_export.evaluate_freeze_invalidation(
        root, frozen, head=head, diff=diff, declared=declared,
        current_baseline=current_baseline)
    fold = _fold_freeze_findings(invalidation_report.get("findings") or [])
    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "SIGNOFF_FREEZE_RECORD",
        "freeze_id": (frozen or {}).get("freeze_id"),
        "state": fold["state"],
        "reasons": [c["note"] for c in fold["contributions"]] or
                   ["NO_FINDINGS: evaluate_freeze_invalidation() reported nothing"],
        "contributions": fold["contributions"],
        "fact_source": "signoff_export.evaluate_freeze_invalidation",
        "underlying_fact": invalidation_report,
    }


# --- generic dispatch over "a real evidence record" -------------------------


def _looks_like_freeze(record: Any) -> bool:
    return isinstance(record, dict) and bool(record.get("freeze_id"))


def _looks_like_capsule_dict(record: Any) -> bool:
    return isinstance(record, dict) and "capsule_id" in record


def _insufficient_context(record: Any, *, reason: Optional[str] = None) -> Dict[str, Any]:
    """The honest report for a record this module cannot classify at all:
    neither `golden_scenario.evaluate_freshness()` nor
    `signoff_export.evaluate_freeze_invalidation()` can be run against it,
    so reporting anything but UNKNOWN would be an invented answer -- the
    negative control this module's own house style requires."""
    evidence_id = record.get("evidence_id") if isinstance(record, dict) else None
    capsule_id = record.get("capsule_id") if isinstance(record, dict) else None
    freeze_id = record.get("freeze_id") if isinstance(record, dict) else None
    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "UNRECOGNIZED_RECORD_SHAPE",
        "evidence_id": evidence_id,
        "capsule_id": capsule_id,
        "freeze_id": freeze_id,
        "state": UNKNOWN,
        "reasons": [reason or (
            "INSUFFICIENT_CONTEXT: this record carries neither a "
            "golden_scenario capsule_id nor a signoff_export freeze_id, so "
            "neither golden_scenario.evaluate_freshness() nor "
            "signoff_export.evaluate_freeze_invalidation() can be run "
            "against it -- reporting any of VALID/STALE/SUPERSEDED/"
            "CONTRADICTED/CORRUPT for it would be an invented answer")],
        "fact_source": None,
        "underlying_fact": None,
    }


_CAPSULE_KWARG_NAMES = ("head", "current_vip_versions", "diff")
_FREEZE_KWARG_NAMES = ("head", "diff", "declared", "current_baseline")


def classify_evidence_integrity(root, record: Any, **kwargs: Any) -> Dict[str, Any]:
    """Dispatch ONE real evidence record -- a `golden_scenario.GoldenScenario`
    capsule (or its plain-dict shape), a `signoff_export` freeze record
    dict, or anything else -- to whichever reused classifier actually
    applies, never guessing a state for a shape neither reused function can
    evaluate.

    A `freeze_id` key wins over a `capsule_id` key when a record somehow
    carried both (it should not: the two real producers never emit an
    overlapping shape), because a freeze record is the richer claim and
    `signoff_export`'s own field names are otherwise unambiguous.
    """
    if isinstance(record, golden_scenario.GoldenScenario):
        capsule_kwargs = {k: v for k, v in kwargs.items() if k in _CAPSULE_KWARG_NAMES}
        return classify_capsule_integrity(root, record, **capsule_kwargs)

    if _looks_like_freeze(record):
        freeze_kwargs = {k: v for k, v in kwargs.items() if k in _FREEZE_KWARG_NAMES}
        return classify_freeze_integrity(root, record, **freeze_kwargs)

    if _looks_like_capsule_dict(record):
        try:
            capsule = golden_scenario.capsule_from_json(record)
        except (golden_scenario.CapsuleValidationError, TypeError) as exc:
            # `capsule_from_json()` only raises `CapsuleValidationError` for
            # an unknown field -- a record missing one of the dataclass's
            # own REQUIRED fields (project/subsystem/test_name/evidence_id)
            # surfaces as a plain `TypeError` from `GoldenScenario(**data)`
            # itself, since that check normally lives in `validate_capsule()`,
            # a separate call this dispatcher does not make. Both are the
            # same real fact -- "this is not a usable capsule record" -- so
            # both are reported the same way rather than one of them
            # crashing this classifier.
            return _insufficient_context(
                record, reason=f"MALFORMED_CAPSULE_RECORD: {exc}")
        capsule_kwargs = {k: v for k, v in kwargs.items() if k in _CAPSULE_KWARG_NAMES}
        return classify_capsule_integrity(root, capsule, **capsule_kwargs)

    return _insufficient_context(record)


# --- by-reference convenience: capsule_id / freeze_id / bare evidence_id ----


def classify_evidence_by_reference(root, *, capsule_id: Optional[str] = None,
                                    freeze_id: Optional[str] = None,
                                    evidence_id: Optional[str] = None,
                                    evidence_db_path: Optional[str] = None,
                                    head: str = "HEAD",
                                    current_vip_versions: Optional[Dict[str, str]] = None
                                    ) -> Dict[str, Any]:
    """Classify by real identifier rather than by an already-loaded record --
    the one place this module ties `evidence_db.py`'s `normalized_evidence`
    table, `golden_scenario.py`'s capsule store and `signoff_export.py`'s
    freeze store together, per this item's own scope. Exactly one of
    `capsule_id` / `freeze_id` / `evidence_id` must be supplied.

    A bare `evidence_id` naming a real `normalized_evidence` row that no
    capsule or freeze cites is reported UNKNOWN naming the row's own real
    verdict/pattern for transparency -- never a fabricated freshness/
    invalidation verdict for evidence neither reused function has a capsule
    or freeze context to evaluate.
    """
    root = Path(root)
    named = [n for n in (capsule_id, freeze_id, evidence_id) if n]
    if len(named) != 1:
        raise EvidenceIntegrityError(
            "classify_evidence_by_reference requires exactly one of "
            "capsule_id, freeze_id, evidence_id "
            f"(got {len(named)} of them)")

    if freeze_id is not None:
        frozen = signoff_export.load_freeze(root, freeze_id)
        if frozen is None:
            return _insufficient_context(
                {"freeze_id": freeze_id},
                reason=f"FREEZE_NOT_FOUND: no freeze record named {freeze_id!r}")
        return classify_freeze_integrity(root, frozen, head=head)

    store = golden_scenario._open_store(root, evidence_db_path, read_only=True)
    if store is None:
        return _insufficient_context(
            {"evidence_id": evidence_id, "capsule_id": capsule_id},
            reason="NO_EVIDENCE_STORE: this project has no evidence.duckdb yet")
    try:
        if capsule_id is not None:
            capsule = golden_scenario.load_golden_scenario(store, capsule_id)
            if capsule is None:
                return _insufficient_context(
                    {"capsule_id": capsule_id},
                    reason=f"CAPSULE_NOT_FOUND: no golden scenario named {capsule_id!r}")
            return classify_capsule_integrity(
                root, capsule, head=head, current_vip_versions=current_vip_versions)

        # evidence_id: exactly one capsule citing it is the unambiguous case.
        matches = [c for c in golden_scenario.load_golden_scenarios(store)
                   if c.evidence_id == evidence_id]
        if len(matches) == 1:
            return classify_capsule_integrity(
                root, matches[0], head=head, current_vip_versions=current_vip_versions)
        if len(matches) > 1:
            return _insufficient_context(
                {"evidence_id": evidence_id},
                reason=(f"AMBIGUOUS_EVIDENCE_ID: {len(matches)} golden scenario "
                        f"capsules cite evidence_id {evidence_id!r}; call "
                        "classify_capsule_integrity() with a specific capsule "
                        "instead of resolving one by guess"))
        row = golden_scenario._fetch_normalized_evidence(store, evidence_id)
        if row is None:
            return _insufficient_context(
                {"evidence_id": evidence_id},
                reason=(f"EVIDENCE_ID_NOT_FOUND: no normalized_evidence row for "
                        f"{evidence_id!r}"))
        return _insufficient_context(
            {"evidence_id": evidence_id},
            reason=("EVIDENCE_ID_HAS_NO_CAPSULE_OR_FREEZE_CONTEXT: a real "
                    f"normalized_evidence row exists (verdict={row.get('verdict')!r}, "
                    f"pattern={row.get('pattern')!r}) but no golden_scenario capsule "
                    "or signoff freeze cites it, so neither reused freshness nor "
                    "invalidation fact can be computed for it"))
    finally:
        store.close()


# --- project-wide rollup ----------------------------------------------------


def classify_project_evidence_integrity(root, *, evidence_db_path: Optional[str] = None,
                                         head: str = "HEAD",
                                         current_vip_versions: Optional[Dict[str, str]] = None
                                         ) -> Dict[str, Any]:
    """Every recorded golden-scenario capsule AND every recorded signoff
    freeze in this project, each classified through the SAME two reused
    functions above. The report's own `status` is the WORST state present
    -- one CORRUPT/CONTRADICTED/STALE record makes the report read that
    way -- because a caller asking "is this project's evidence still good"
    must not read a mostly-clean set as an all-clear. A project recording
    neither a capsule nor a freeze is `NOT_AVAILABLE`, never a vacuous
    VALID over nothing.
    """
    root = Path(root)
    capsule_reports: List[Dict[str, Any]] = []
    freeze_reports: List[Dict[str, Any]] = []

    store = golden_scenario._open_store(root, evidence_db_path, read_only=True)
    if store is not None:
        try:
            for capsule in golden_scenario.load_golden_scenarios(store):
                capsule_reports.append(classify_capsule_integrity(
                    root, capsule, head=head, current_vip_versions=current_vip_versions))
        finally:
            store.close()

    for frozen in signoff_export.list_freezes(root):
        freeze_reports.append(classify_freeze_integrity(root, frozen, head=head))

    all_reports = capsule_reports + freeze_reports
    if not all_reports:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "NOT_AVAILABLE",
            "reason": ("NO_EVIDENCE_RECORDED: no golden scenario capsules and no "
                       "signoff freezes exist for this project"),
            "capsule_count": 0, "freeze_count": 0, "counts": {},
            "capsules": [], "freezes": [],
        }
    counts: Dict[str, int] = {s: 0 for s in ALL_STATES}
    overall = VALID
    for r in all_reports:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        overall = _worse(overall, r["state"])
    return {
        "schema_version": SCHEMA_VERSION,
        "status": overall,
        "capsule_count": len(capsule_reports),
        "freeze_count": len(freeze_reports),
        "counts": counts,
        "capsules": capsule_reports,
        "freezes": freeze_reports,
    }


# --- rendering / CLI ---------------------------------------------------------


def format_report(report: Dict[str, Any]) -> str:
    if "status" in report:
        lines = [f"EVIDENCE INTEGRITY (project): {report['status']}"]
        counts = report.get("counts") or {}
        lines.append("  " + "  ".join(f"{s}={counts.get(s, 0)}" for s in ALL_STATES))
        if not (report.get("capsules") or report.get("freezes")):
            lines.append(f"  {report.get('reason', 'no evidence recorded')}")
        for r in report.get("capsules", []):
            lines.append(f"  capsule {r.get('capsule_id')}: {r['state']}")
        for r in report.get("freezes", []):
            lines.append(f"  freeze  {r.get('freeze_id')}: {r['state']}")
        return "\n".join(lines)
    lines = [f"EVIDENCE INTEGRITY: {report.get('state')} "
             f"({report.get('record_kind')}"
             + (f", capsule_id={report['capsule_id']}" if report.get("capsule_id") else "")
             + (f", freeze_id={report['freeze_id']}" if report.get("freeze_id") else "")
             + ")"]
    for reason in report.get("reasons") or []:
        lines.append(f"  {reason}")
    return "\n".join(lines)


def execute_verb(argv: Sequence[str]) -> int:
    """Shared implementation for `python -m dv_harness.evidence_integrity_states
    <verb>`. Exit 0 the classified record(s) are VALID, 1 a real finding
    (STALE/SUPERSEDED/CONTRADICTED/CORRUPT), 2 UNKNOWN / NOT_AVAILABLE /
    usage error. Nothing here approves, freezes, revalidates or runs
    anything -- a reporting signal, never an approval signal."""
    import argparse
    ap = argparse.ArgumentParser(
        prog="evidence-integrity-states",
        description="Evidence Integrity state classifier "
                    "(VALID/STALE/SUPERSEDED/CONTRADICTED/CORRUPT).")
    ap.add_argument("verb", choices=["states", "capsule", "freeze", "evidence", "project"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--db-path", default=None)
    ap.add_argument("--capsule-id", default=None)
    ap.add_argument("--freeze-id", default=None)
    ap.add_argument("--evidence-id", default=None)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv))
    root = Path(args.root).resolve()

    if args.verb == "states":
        print(json.dumps({
            "evidence_integrity_states": list(EVIDENCE_INTEGRITY_STATES),
            "all_states": list(ALL_STATES),
        }, indent=2))
        return 0

    if args.verb == "project":
        report = classify_project_evidence_integrity(
            root, evidence_db_path=args.db_path, head=args.head)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
              else format_report(report))
        if report["status"] == VALID:
            return 0
        if report["status"] in (UNKNOWN, "NOT_AVAILABLE"):
            return 2
        return 1

    if args.verb == "capsule":
        if not args.capsule_id:
            print(json.dumps({"state": UNKNOWN, "reasons": ["--capsule-id is required"]}))
            return 2
        report = classify_evidence_by_reference(
            root, capsule_id=args.capsule_id, evidence_db_path=args.db_path, head=args.head)
    elif args.verb == "freeze":
        if not args.freeze_id:
            print(json.dumps({"state": UNKNOWN, "reasons": ["--freeze-id is required"]}))
            return 2
        report = classify_evidence_by_reference(root, freeze_id=args.freeze_id, head=args.head)
    else:  # evidence
        if not args.evidence_id:
            print(json.dumps({"state": UNKNOWN, "reasons": ["--evidence-id is required"]}))
            return 2
        report = classify_evidence_by_reference(
            root, evidence_id=args.evidence_id, evidence_db_path=args.db_path, head=args.head)

    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else format_report(report))
    if report["state"] == UNKNOWN:
        return 2
    return 0 if report["state"] == VALID else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys
    return execute_verb(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    import sys
    sys.exit(main())
