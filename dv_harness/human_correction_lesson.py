"""Human Correction Learning (section 227 of the Research_Capability_Evolution
master prompt): capture and structure a human's correction of an agent
mistake as a REUSABLE lesson record, so a future session can query "has a
human corrected this exact mistake before" instead of re-deriving the same
wrong answer and needing a second human correction.

REUSE OVER REINVENT -- checked before writing a line of this module
---------------------------------------------------------------------------
`dv_harness/memory.py` already has a `kind="debug_lesson"` route
(`memory_router.route_memory()`: `kind in ("root_cause","verified_fix",
"debug_lesson") and verified -> ENGINEERING_MEMORY`), and
`engine._promote_experience_knowledge()`'s own comment already names what a
`debug_lesson` is for: it "captures what this class of problem looks like /
why / when it applies". What that route has never had is a STRUCTURED
before/after correction shape -- every existing `debug_lesson` writer stores
free text only (`root_cause`/`fix`/`lesson` strings), so nothing could ever
answer "was this SPECIFIC agent mistake, as stated, already corrected by a
human once" without a human re-reading prose. This module is exactly that
extension: it builds and validates a `kind="debug_lesson"` record whose
`correction` field is schema-shaped (before/after, section 227's own
vocabulary), and it is the ONLY code in this repository that writes that
shape -- `route_and_store()`/`route_memory()`/`engineering_admission_gate()`
in `memory_router.py` are called, not duplicated, so a record this module
builds is admitted to the Engineering tier by the exact same real gate every
other `debug_lesson`/`root_cause`/`verified_fix` record already goes through.

Distinct from `dv_harness/user_correction_trigger.py` (also 2026-09-06, in
this same batch) -- checked by direct reading before this module was
written, so the two are not a collision under two names. That module
detects REPETITION of a correction (two or more independent
`MemoryGC.retract()`/`supersede()` events citing the identical normalized
reason) and, on repetition, files a capability-evolution candidate asking
"should this harness grow a guard against this class of mistake". It never
structures a single correction's own before/after content -- its own
docstring names `debug_lesson`/`root_cause` only as "the LESSON half...
purely as informational context", explicitly NOT the mechanism it builds.
This module is that missing mechanism: it captures ONE correction, structured,
the moment it happens (no repetition required), and answers a query about
ONE exact mistake ("has this happened before") rather than filing a
capability-evolution proposal about a recurring pattern. The two compose
naturally -- `user_correction_trigger.py` could, in a future change, read
`kind="debug_lesson"` records this module writes as its own "captured lesson"
context (it already reads that kind's `root_cause`/`title`/`fix` fields via
`captured_lesson_claim_texts()`) -- but this module does not depend on that
one, or vice versa, and neither imports the other.

WHAT "THIS EXACT MISTAKE" MEANS HERE
---------------------------------------------------------------------------
`mistake_signature_key()` hashes {`mistake_category`, normalized
`before.claim` text} with `evidence_db.signature_key()` -- the SAME stable
hash utility `capability_evolution.repeated_unresolved_failure_patterns()`
and `user_correction_trigger.correction_signature_key()` already use, rather
than a second hashing definition. Matching is EXACT equality on normalized
text, never fuzzy -- the identical "exact equality... never fuzzy" discipline
those two modules' own docstrings state the reason for: a fuzzy join would
silently group two unrelated mistakes as "the same one", manufacturing a
false sense that a mistake class was already handled and closing the door on
a genuinely new correction being captured. This is a real, disclosed
limitation, not an oversight: two occurrences of what a human would call
"the same mistake" worded even slightly differently will NOT be matched by
`find_prior_corrections()`. Under-detection, never fabricated
over-detection, is the accepted trade -- exactly the trade
`user_correction_trigger.py`'s own docstring makes for the identical reason.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
---------------------------------------------------------------------------
  * It never decides whether the human's correction is itself correct --
    Evidence Truth Rule discipline stops at "a human, cited, corrected this";
    it is not a second verification pass over the human's own claim.
  * It never re-implements `memory_router`'s tier routing or admission gates
    -- `record_human_correction_lesson()` calls `route_and_store()` exactly
    once and returns whatever it decides (including the honest demotion-to-
    Working-Memory outcome, should a caller somehow build a record that
    fails `engineering_admission_gate()` -- unreachable through this
    module's own constructor today, since every required field the gate
    checks is also a required field of `build_human_correction_lesson()`,
    but the demotion path is still surfaced rather than hidden).
  * It never fabricates a match. `find_prior_corrections()`/
    `has_prior_correction()` return an honestly empty result when nothing
    matches -- never a guessed "probably yes".
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .evidence_db import signature_key
from .memory import MemoryStore

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "human_correction_lesson.schema.json"

CORRECTION_SOURCE = "human"

# memory_router.ENGINEERING_ADMISSION_CONFIDENCE_LEVELS is ("HIGH","CONFIRMED");
# restated here rather than imported so this module's own schema/CLI validation
# does not have to import memory_router just to read one tuple -- the schema's
# own enum is the real source of truth this constant is checked against by the
# test suite, exactly the way `phy_boundary.py` keeps its own small constants
# next to the schema they back rather than importing a sibling module's.
DEFAULT_CONFIDENCE = "HIGH"


class HumanCorrectionLessonValidationError(ValueError):
    """A human-correction-lesson record fails human_correction_lesson.schema.json
    validation. Raised rather than returning None/False, matching
    phy_boundary.PhyBoundaryValidationError's / env_manifest.py's fail-closed
    discipline -- a caller must never persist an invalid correction record."""


def validate_human_correction_lesson(record: Dict[str, Any]) -> None:
    """Validate `record` against human_correction_lesson.schema.json. Raises
    HumanCorrectionLessonValidationError on any violation."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise HumanCorrectionLessonValidationError(
            "jsonschema package is not installed; cannot validate against "
            "human_correction_lesson.schema.json. Install it rather than skipping validation."
        ) from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise HumanCorrectionLessonValidationError(
            "human_correction_lesson.schema.json validation failed:\n" + "\n".join(lines)
        )


def _norm_text(value: Any) -> str:
    """Lowercased, whitespace-collapsed text -- the same normalization
    `user_correction_trigger._norm_text()`/`capability_evolution._norm_text()`
    apply, reimplemented locally rather than importing a leading-underscore
    private symbol from either (the same choice `user_correction_trigger.py`
    itself already made for the identical reason: this module owes those two
    no shared state)."""
    return " ".join(str(value or "").strip().lower().split())


def mistake_signature_key(before_claim: str, mistake_category: Optional[str] = None) -> str:
    """Stable, EXACT-match dedup key for one mistake -- see this module's
    docstring ("WHAT 'THIS EXACT MISTAKE' MEANS HERE") for the reasoning.
    Reuses `evidence_db.signature_key()`, the same stable-hash utility this
    codebase's other exact-equality dedup keys already depend on."""
    return signature_key({
        "mistake_category": _norm_text(mistake_category),
        "before_claim": _norm_text(before_claim),
    })


def _require_nonblank(field_name: str, value: Any) -> str:
    """Refuse a caller-supplied argument that is empty or whitespace-only.
    The schema's own `minLength: 1` catches an empty STRING; it cannot catch
    "   ", so this is checked here, before the record is even assembled --
    the same fail-closed posture, one call earlier, that
    validate_human_correction_lesson() applies to the assembled record."""
    text = str(value or "")
    if not text.strip():
        raise HumanCorrectionLessonValidationError(
            f"{field_name!r} must be real, non-blank text -- a human-correction "
            "lesson record must never be built from an empty/placeholder claim, "
            "evidence citation, corrected-by identity, or mistake category."
        )
    return text


def build_human_correction_lesson(
    *,
    before_claim: str,
    after_claim: str,
    correction_evidence: str,
    corrected_by: str,
    mistake_category: str,
    before_reasoning: Optional[str] = None,
    protocol: Optional[str] = None,
    scope: Optional[str] = None,
    title: Optional[str] = None,
    corrected_at: Optional[float] = None,
    confidence: str = DEFAULT_CONFIDENCE,
) -> Dict[str, Any]:
    """Build (never persist) one structured human-correction `debug_lesson`
    record. Validated against human_correction_lesson.schema.json before it
    is returned -- an empty/whitespace-only `before_claim`, `after_claim`,
    `correction_evidence`, `corrected_by`, or `mistake_category` fails that
    schema's own `minLength: 1` and raises
    HumanCorrectionLessonValidationError rather than silently accepting a
    placeholder correction (the negative control this module's Evidence
    Truth Rule test proves: it refuses to fabricate a lesson record when the
    human's own evidence is absent)."""
    corrected_at = time.time() if corrected_at is None else float(corrected_at)
    before_claim_norm = _require_nonblank("before_claim", before_claim)
    after_claim_norm = _require_nonblank("after_claim", after_claim)
    evidence_norm = _require_nonblank("correction_evidence", correction_evidence)
    corrected_by_norm = _require_nonblank("corrected_by", corrected_by)
    mistake_category_norm = _require_nonblank("mistake_category", mistake_category)

    lesson = (
        f"Agent incorrectly asserted/did: {before_claim_norm}. "
        f"Human correction ({corrected_by_norm}): {after_claim_norm}"
    )

    record: Dict[str, Any] = {
        "kind": "debug_lesson",
        "title": title or f"Human correction: {mistake_category_norm}",
        "protocol": protocol,
        "scope": scope,
        "mistake_category": mistake_category_norm,
        "mistake_signature_key": mistake_signature_key(before_claim_norm, mistake_category_norm),
        "lesson": lesson,
        "evidence": evidence_norm,
        "confidence": confidence,
        "verified": True,
        "reusable": True,
        "correction": {
            "correction_source": CORRECTION_SOURCE,
            "before": {
                "claim": before_claim_norm,
                "reasoning": before_reasoning,
            },
            "after": {
                "claim": after_claim_norm,
                "evidence": evidence_norm,
                "corrected_by": corrected_by_norm,
                "corrected_at": corrected_at,
            },
        },
    }
    validate_human_correction_lesson(record)
    return record


def record_human_correction_lesson(
    root,
    *,
    before_claim: str,
    after_claim: str,
    correction_evidence: str,
    corrected_by: str,
    mistake_category: str,
    before_reasoning: Optional[str] = None,
    protocol: Optional[str] = None,
    scope: Optional[str] = None,
    title: Optional[str] = None,
    corrected_at: Optional[float] = None,
    confidence: str = DEFAULT_CONFIDENCE,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a structured human-correction lesson and persist it through the
    REAL, existing `memory_router.route_and_store()` -- no parallel write
    path. `kind="debug_lesson"` + `verified=True` routes to ENGINEERING_MEMORY
    per `route_memory()`, gated by the real, unmodified
    `engineering_admission_gate()` exactly like every other engineering-tier
    record in this codebase; every field that gate checks (evidence,
    confidence, a reusable claim) is guaranteed present by
    `build_human_correction_lesson()`'s own required arguments, so the
    ordinary outcome is a clean ENGINEERING_MEMORY write -- but the
    honest demotion-to-Working-Memory result `route_and_store()` returns on
    a rejection is passed through unchanged rather than hidden, should a
    future edit to either module's gates ever disagree.

    `cfg` is forwarded to `route_and_store()` unmodified -- omit it for this
    project's normal auto-loaded-config behavior, or pass `cfg={}` for a
    local-only write with no Knowledge Center push attempt, exactly as
    `route_and_store()`'s own docstring documents."""
    # Deferred import: this module has no other reason to load memory_router.py
    # (a large module) except when it is actually about to write -- every
    # read-only function above (build_human_correction_lesson(),
    # mistake_signature_key(), find_prior_corrections(), has_prior_correction())
    # needs only memory.py/evidence_db.py.
    from .memory_router import route_and_store

    record = build_human_correction_lesson(
        before_claim=before_claim,
        after_claim=after_claim,
        correction_evidence=correction_evidence,
        corrected_by=corrected_by,
        mistake_category=mistake_category,
        before_reasoning=before_reasoning,
        protocol=protocol,
        scope=scope,
        title=title,
        corrected_at=corrected_at,
        confidence=confidence,
    )
    return route_and_store(Path(root), record, cfg=cfg)


def find_prior_corrections(
    root,
    *,
    before_claim: str,
    mistake_category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Every persisted human-correction-lesson record whose `mistake_signature_key`
    exactly matches the one this exact (mistake_category, before_claim) pair
    would produce -- across every memory tier (a rejected/demoted record
    still lands in Working Memory, and this must still find it). Newest
    first, matching `MemoryStore.find()`'s own default. An honestly empty
    list, never a guessed match, when nothing on file matches (see this
    module's docstring, "WHAT THIS MODULE DELIBERATELY DOES NOT DO")."""
    key = mistake_signature_key(before_claim, mistake_category)
    store = MemoryStore(Path(root))
    return store.find(None, kind="debug_lesson", mistake_signature_key=key)


def has_prior_correction(
    root,
    *,
    before_claim: str,
    mistake_category: Optional[str] = None,
) -> Dict[str, Any]:
    """The direct answer to section 227's own question -- "has a human
    corrected this exact mistake before" -- as a small, honest report rather
    than a bare bool: `found`, how many independent corrections are on file,
    the real matching records (each carrying its own real `corrected_by`/
    `evidence`/`corrected_at`), and the exact signature key that was queried
    (so a caller can see precisely what was and was not matched)."""
    key = mistake_signature_key(before_claim, mistake_category)
    matches = find_prior_corrections(root, before_claim=before_claim, mistake_category=mistake_category)
    return {
        "found": bool(matches),
        "count": len(matches),
        "mistake_signature_key": key,
        "matches": matches,
    }


# ---------------------------------------------------------------------------
# Standalone front door. No `dv-harness` CLI verb was added and cli.py was
# not touched, per this item's own instruction to prefer a standalone
# "python -m dv_harness.<module>" door and disclose the CLI-wiring as a
# residual -- the same disclosed choice several recent modules in this
# codebase already make.


def execute_verb(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.human_correction_lesson")
    parser.add_argument("--root", default=".", help="Project root (default: current directory).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_record = sub.add_parser("record", help="Capture one structured human correction as a debug_lesson.")
    p_record.add_argument("--before-claim", required=True)
    p_record.add_argument("--after-claim", required=True)
    p_record.add_argument("--correction-evidence", required=True)
    p_record.add_argument("--corrected-by", required=True)
    p_record.add_argument("--mistake-category", required=True)
    p_record.add_argument("--before-reasoning", default=None)
    p_record.add_argument("--protocol", default=None)
    p_record.add_argument("--scope", default=None)
    p_record.add_argument("--title", default=None)
    p_record.add_argument("--confidence", default=DEFAULT_CONFIDENCE)

    p_query = sub.add_parser("query", help="Ask whether a human has corrected this exact mistake before.")
    p_query.add_argument("--before-claim", required=True)
    p_query.add_argument("--mistake-category", default=None)

    args = parser.parse_args(argv)
    root = Path(args.root)

    if args.verb == "record":
        result = record_human_correction_lesson(
            root,
            before_claim=args.before_claim,
            after_claim=args.after_claim,
            correction_evidence=args.correction_evidence,
            corrected_by=args.corrected_by,
            mistake_category=args.mistake_category,
            before_reasoning=args.before_reasoning,
            protocol=args.protocol,
            scope=args.scope,
            title=args.title,
            confidence=args.confidence,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"{result.get('destination')} {result.get('level')} {result.get('memory_id')}")
        return 0 if result.get("destination") == "ENGINEERING_MEMORY" else 1

    if args.verb == "query":
        report = has_prior_correction(
            root, before_claim=args.before_claim, mistake_category=args.mistake_category,
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"found={report['found']} count={report['count']} key={report['mistake_signature_key']}")
        return 0 if report["found"] else 1

    parser.error(f"unknown verb {args.verb!r}")
    return 2  # pragma: no cover -- parser.error() already raises SystemExit


def main() -> None:
    sys.exit(execute_verb())


if __name__ == "__main__":
    main()
