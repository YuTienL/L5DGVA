"""dv_harness/vip_erratum_correlation.py -- extracts VIP erratum / known-
limitation FACTS from a real, offline-distilled VIP document, and correlates
each named limitation to whichever real, evidence-cited project pattern/
config actually exercises the affected feature.

THE GAP THIS CLOSES. No erratum/known-limitations parser or cross-reference
existed anywhere in this repo (confirmed by a repo-wide grep for
`erratum`/`known.limitation`/`KnownLimitation` before this module was
written: zero hits outside this file). `vip_capability_extraction.py`
classifies a VIP's own SOURCE declarations into config/transaction/scenario/
checker/coverage capability shapes; `vip_learning_gate.py` composes four
pre-generation VIP checkpoints (API provability, PHY boundary, bind tier,
env-manifest vip_config status). Neither reads a VIP DOCUMENT for a
documented limitation, and neither asks whether a project's own real usage
of that VIP actually touches the affected feature.

REUSE OVER REINVENT, on both sides of the fact this module adds:

  * The VIP DOCUMENT (a release-notes/errata sheet, or a "Known Limitations"
    chapter of the user guide) is never opened here as a raw PDF/text scan of
    an arbitrary path. `dv_harness/vip_user_guide_distill.py` is this repo's
    ONE offline document distiller (real pypdf extraction, or a pre-
    extracted .txt/.md) -- this module consumes the `.reference.json` record
    and the `.fulltext.txt` file that distiller already produced, exactly
    the same reuse `phy_model_behavior_ir.py` already established for its
    own PHY-spec-behaviour extraction. There is one document-opening code
    path in this package, not two, and the Context Budget rule ("never
    loaded into runtime context") stays enforced structurally by keeping
    this module off that path too.
  * Project usage of a VIP feature is never re-discovered here. It is a
    caller-supplied, evidence-cited fact per pattern/config -- the same
    "accept an explicit caller-declared fact the real evidence store cannot
    supply, rather than invent one" discipline `ip_ownership_conflict.py`'s
    `legacy_bfm_declarations` and `existing_command_reuse_score.py`'s
    `existing_commands` already establish. There is no command.txt parser
    and no config-space reader in this module.

WHAT COUNTS AS AN ERRATUM ENTRY, and why it cannot be a guess. The scan is
STRUCTURAL, not semantic -- the same discipline `phy_model_behavior_ir.py`
already applies one document-family over: a small, disclosed set of section-
marker keywords ("errata", "known issue(s)", "known limitation(s)",
"restriction(s)", "caveat(s)", "workaround(s)") decides which document
SECTION a line sits in, and a line-shape scan (an "ID: description" /
"ID<spaces>description" row, or a bulleted/numbered list item) decides which
lines inside that section are candidate erratum entries. A document written
with none of these structural conventions is honestly reported
NO_MARKER_SECTION_DETECTED / MARKER_SECTION_FOUND_NO_ITEMS, never guessed.
Every entry carries the literal (possibly truncated) source line plus a real
`document + fulltext_path + line` citation a reader can open and check.

WHAT COUNTS AS THE "AFFECTED FEATURE", and why a two-tier extraction. An
erratum row's own text sometimes states its affected feature explicitly
("... affects the LPM sub-state machine.", "This restriction applies to
burst-mode transfers.") -- a small, fixed, literal phrase list
(`_AFFECTS_PHRASE_RE`) recognises that form and extracts the named feature
verbatim, tagged `PHRASE_MATCH`. Absent an explicit phrase, many real errata
tables use the row's own ID/label column AS the feature/area name ("USB3
LPM: exit latency may exceed spec under X"); this module falls back to that
label ONLY when it does not itself look like a bare issue-tracker id
(`_looks_like_pure_id()` -- "ERR-042", "KI3", "Issue #12", "1.2"), tagged
`ID_LABEL_INFERRED` -- a weaker, disclosed tag, never conflated with an
explicit statement. An entry for which neither source yields a feature name
is honestly `NOT_ANNOTATED`: this module never invents one from the
description's general prose.

CORRELATION IS LITERAL, NEVER SEMANTIC. `correlate_entry()` matches an
entry's own extracted `affected_feature` against a usage fact's own declared
`exercises_features` list by normalized (lower-cased, alphanumeric-only)
exact/substring comparison ONLY -- the same discipline
`dut_evidence_correlation.py`'s `_match_kind()` already applies one domain
over. No fuzzy edit-distance, no synonym table, no embedding: either would
risk manufacturing a correspondence the project's own declared facts do not
actually state.

THE FOUR-STATUS VERDICT, and what earns each one:
  CORRELATED                            a supplied usage fact's own declared
                                         `exercises_features` matches the
                                         entry's extracted affected feature.
  NOT_CORRELATED                        usage facts were supplied, and none
                                         of them declares exercising the
                                         entry's affected feature -- a real
                                         negative, not an absence of
                                         evidence.
  NOT_AVAILABLE                         no usage facts were supplied at all
                                         -- "we could not check" is never
                                         collapsed into NOT_CORRELATED.
  UNRESOLVABLE_NO_AFFECTED_FEATURE      the erratum entry itself carries no
                                         extractable affected-feature name
                                         (see above) -- correlation cannot
                                         even be attempted, regardless of how
                                         many usage facts were supplied.

DELIBERATELY BOUNDED, and stated rather than implied closed.
(1) It never mines a golden-reference environment for erratum CONTENT --
    every entry traces to a real document a caller distilled themselves.
(2) It never picks which usage fact is "the" reason a limitation is safe to
    ignore -- CORRELATED only reports that a real declared usage overlaps
    the affected feature; whether that overlap is actually a risk stays a
    human decision.
(3) It decides nothing beyond reporting: no build, no job, no approval, no
    stage gate, no memory write. There is no `dv-harness` CLI verb --
    `cli.py`/`gates.py` are out of this task's file-safety scope, the same
    disclosed choice several sibling same-day modules in this codebase
    already make; the front door is
    `python -m dv_harness.vip_erratum_correlation`.
(4) A usage fact with no citation is refused at construction
    (`VipErratumCorrelationError`) -- an uncited "this pattern exercises
    feature X" claim is exactly the unsupported claim the Evidence Truth
    Rule forbids.
(5) This is a regex line-scan, not a document-structure parser -- the same
    disclosed bound `interrupt_dma_clock_reset_extraction.py`/
    `error_recovery_flow_extraction.py`/`timing_requirement_extraction.py`
    already state for themselves. An erratum row (and its "affects"/
    "applies to" clause) must sit on ONE physical line of the extracted
    full-text; a row whose real PDF extraction happened to wrap across
    multiple lines contributes only what its own single matched line states,
    never a guessed join of the following continuation line.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dv_harness import vip_user_guide_distill

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# status vocabularies -- checked disjoint from a real stage verdict at import
# ---------------------------------------------------------------------------

STATUS_CORRELATED = "CORRELATED"
STATUS_NOT_CORRELATED = "NOT_CORRELATED"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_UNRESOLVABLE_NO_AFFECTED_FEATURE = "UNRESOLVABLE_NO_AFFECTED_FEATURE"
CORRELATION_STATUSES: Tuple[str, ...] = (
    STATUS_CORRELATED, STATUS_NOT_CORRELATED, STATUS_NOT_AVAILABLE,
    STATUS_UNRESOLVABLE_NO_AFFECTED_FEATURE,
)

FEATURE_SOURCE_PHRASE_MATCH = "PHRASE_MATCH"
FEATURE_SOURCE_ID_LABEL_INFERRED = "ID_LABEL_INFERRED"
FEATURE_SOURCE_NOT_ANNOTATED = "NOT_ANNOTATED"


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status words must never collide with a real stage
    verdict -- the same guard several sibling domain-vocabulary modules
    already run against `dv_harness.models.Status` at import time."""
    from dv_harness import models
    stage_verdicts = {s.value for s in models.Status}
    collision = stage_verdicts & set(CORRELATION_STATUSES)
    assert not collision, f"vip_erratum_correlation vocabulary collides with models.Status: {collision}"


assert_no_verification_verdict_vocabulary()


class VipErratumCorrelationError(ValueError):
    """A caller usage error (a malformed usage fact, an unreadable reference
    record) -- never silently downgraded to a NOT_AVAILABLE finding."""


# ---------------------------------------------------------------------------
# structural erratum-section scan -- real doc lines + real citations only
# ---------------------------------------------------------------------------

_ERRATA_SECTION_RE = re.compile(
    r"\b(errata|known\s+issues?|known\s+limitations?|restrictions?|caveats?|workarounds?)\b",
    re.IGNORECASE,
)

_MAX_HEADING_CHARS = 120
_NUMBERED_HEADING_RE = re.compile(r"^\s{0,8}\d+(?:\.\d+){0,5}\.?\s+\S.{0,110}$")
_ALLCAPS_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 /&\-]{3,79}$")

# "ID: description" / "ID - description" / "ID<2+ spaces>description" --
# deliberately permissive on the label side (spaces, '#', digits allowed) so
# a real errata table's own ID/area column ("Known Issue 5", "Issue #12",
# "USB3 LPM") is captured verbatim rather than narrowed to a bare token.
_ID_LINE_RE = re.compile(
    r"^[\-\*•●>]?\s*([A-Za-z][A-Za-z0-9 _./#-]{0,39}?)"
    r"(?:\s*[:–\-]\s+|\s{2,})(\S.*)$")
_BULLET_RE = re.compile(r"^[\-\*•●]\s+(\S.*)$")
_NUMBERED_ITEM_RE = re.compile(r"^\d{1,3}[.)]\s+(\S.*)$")

# A label that itself looks like a bare issue-tracker identifier, never a
# feature/area name -- "ERR-042", "KI3", "Issue #12", "1.2.3", "BUG_00234".
_PURE_ID_RE = re.compile(
    r"^(?:#?\d+(?:\.\d+)*|[A-Za-z]{1,6}[-_]?\#?\d+[A-Za-z]?|issue\s*#?\d+|"
    r"(?:known\s+)?(?:issue|erratum|errata|limitation)\s*#?\d*)$",
    re.IGNORECASE,
)

# A small, fixed, literal phrase list stating an erratum's affected feature
# explicitly. Non-greedy capture, cut at sentence end / line end below.
_AFFECTS_PHRASE_RE = re.compile(
    r"\b(?:this\s+(?:limitation|restriction|issue|erratum|workaround)\s+)?"
    r"(?:affects?|impacts?|applies\s+to)\s+(?:the\s+)?(.+)",
    re.IGNORECASE,
)
_WHEN_USING_RE = re.compile(r"\bwhen\s+using\s+(?:the\s+)?(.+)", re.IGNORECASE)
_IN_MODE_RE = re.compile(r"\bin\s+(.+?)\s+mode\b", re.IGNORECASE)

DEFAULT_MAX_ITEMS = 100
DEFAULT_MAX_EVIDENCE_CHARS = 240
_MIN_FEATURE_LEN = 3


def _is_heading_like(stripped: str) -> bool:
    if not stripped or len(stripped) > _MAX_HEADING_CHARS:
        return False
    if stripped.endswith((".", ",", ";", ":")):
        return False
    if _NUMBERED_HEADING_RE.match(stripped):
        return True
    if _ALLCAPS_HEADING_RE.match(stripped) and any(c.isalpha() for c in stripped):
        return True
    return False


def _looks_like_pure_id(label: str) -> bool:
    return bool(_PURE_ID_RE.match(label.strip()))


def _trim_feature_text(text: str, max_chars: int) -> str:
    text = text.strip()
    # Cut at the first sentence-ending period followed by whitespace/EOL, or
    # a semicolon/comma clause boundary, whichever the real text offers.
    m = re.search(r"[.;]\s|$", text)
    if m:
        text = text[: m.start()]
    text = text.strip(" .,;:\"'()")
    return text[:max_chars]


def _extract_affected_feature(description: str, label: Optional[str],
                               max_chars: int) -> Tuple[Optional[str], str]:
    """Returns (affected_feature, feature_source). PHRASE_MATCH beats
    ID_LABEL_INFERRED beats NOT_ANNOTATED -- an explicit statement in the
    entry's own text is stronger evidence than its ID/area column."""
    for pattern in (_AFFECTS_PHRASE_RE, _WHEN_USING_RE, _IN_MODE_RE):
        m = pattern.search(description)
        if m:
            candidate = _trim_feature_text(m.group(1), max_chars)
            if len(candidate) >= _MIN_FEATURE_LEN:
                return candidate, FEATURE_SOURCE_PHRASE_MATCH
    if label and len(label.strip()) >= _MIN_FEATURE_LEN and not _looks_like_pure_id(label):
        return label.strip(), FEATURE_SOURCE_ID_LABEL_INFERRED
    return None, FEATURE_SOURCE_NOT_ANNOTATED


def scan_erratum_text(full_text: str, *, document_label: str, fulltext_path: str,
                       max_items: int = DEFAULT_MAX_ITEMS,
                       max_evidence_chars: int = DEFAULT_MAX_EVIDENCE_CHARS) -> Dict[str, Any]:
    """Scan real document text for structurally-recognizable erratum/known-
    limitation entries. Returns `{"marker_seen": bool, "entries": [...]}`.

    The current section flag is reset at EVERY heading-like line (set True
    on an errata-marker heading, False on any other heading) -- never left
    "sticky" across an unrelated section, the same discipline
    `phy_model_behavior_ir.scan_phy_doc_text()` already applies."""
    entries: List[Dict[str, Any]] = []
    marker_seen = False
    in_erratum_section = False
    for line_no, raw_line in enumerate(full_text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if _is_heading_like(stripped):
            in_erratum_section = bool(_ERRATA_SECTION_RE.search(stripped))
            if in_erratum_section:
                marker_seen = True
            continue
        if not in_erratum_section or len(entries) >= max_items:
            continue

        citation = {"document": document_label, "fulltext_path": fulltext_path, "line": line_no}
        label: Optional[str] = None
        description: str
        m = _ID_LINE_RE.match(stripped)
        if m:
            label, description = m.group(1), m.group(2)
        else:
            content = None
            bm = _BULLET_RE.match(stripped)
            if bm:
                content = bm.group(1)
            else:
                nm = _NUMBERED_ITEM_RE.match(stripped)
                if nm:
                    content = nm.group(1)
            if content is None:
                continue
            description = content

        affected_feature, feature_source = _extract_affected_feature(
            description, label, max_evidence_chars)
        entries.append({
            "sequence_index": len(entries),
            "erratum_id": label,
            "description": description[:max_evidence_chars],
            "affected_feature": affected_feature,
            "affected_feature_source": feature_source,
            "citation": citation,
        })
    return {"marker_seen": marker_seen, "entries": entries}


# ---------------------------------------------------------------------------
# usage-fact validation -- an uncited "this exercises feature X" is refused
# ---------------------------------------------------------------------------

def validate_usage_facts(usage_facts: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Validates a caller-supplied list of project usage facts. Each fact
    must carry `id`, `exercises_features` (a non-empty list of strings) and a
    non-empty `evidence` citation -- refused at construction, never silently
    dropped or accepted with a guessed citation."""
    if not usage_facts:
        return []
    validated: List[Dict[str, Any]] = []
    for i, fact in enumerate(usage_facts):
        if not isinstance(fact, dict):
            raise VipErratumCorrelationError(f"usage fact #{i} is not an object: {fact!r}")
        fact_id = fact.get("id")
        if not fact_id:
            raise VipErratumCorrelationError(f"usage fact #{i} is missing required field 'id'")
        features = fact.get("exercises_features")
        if not isinstance(features, list) or not features or not all(
                isinstance(f, str) and f.strip() for f in features):
            raise VipErratumCorrelationError(
                f"usage fact {fact_id!r} must declare a non-empty list of string "
                f"'exercises_features' -- an unsupported usage claim is refused, never guessed")
        evidence = fact.get("evidence")
        if not evidence or not str(evidence).strip():
            raise VipErratumCorrelationError(
                f"usage fact {fact_id!r} carries no 'evidence' citation -- an uncited claim that "
                f"a pattern/config exercises a feature is refused outright")
        validated.append({
            "id": fact_id,
            "kind": fact.get("kind") or "unspecified",
            "exercises_features": [f.strip() for f in features],
            "evidence": str(evidence),
        })
    return validated


def _normalize(name: str) -> str:
    return "".join(ch.lower() for ch in (name or "") if ch.isalnum())


def correlate_entry(entry: Dict[str, Any], usage_facts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Correlates ONE erratum entry against an already-validated list of
    project usage facts (see `validate_usage_facts()`)."""
    affected = entry.get("affected_feature")
    if not affected:
        return {
            "status": STATUS_UNRESOLVABLE_NO_AFFECTED_FEATURE,
            "reason": "this erratum entry's own text carries no extractable affected-feature name "
                      "(no explicit 'affects/impacts/applies to' statement, and its ID/area label "
                      "-- if any -- looks like a bare issue-tracker id) -- correlation cannot be "
                      "attempted regardless of how many usage facts were supplied",
            "matches": [],
        }
    if not usage_facts:
        return {
            "status": STATUS_NOT_AVAILABLE,
            "reason": "no project usage facts (patterns/configs) were supplied -- 'we could not "
                      "check' is never collapsed into NOT_CORRELATED",
            "matches": [],
        }

    affected_norm = _normalize(affected)
    matches: List[Dict[str, Any]] = []
    for fact in usage_facts:
        for feature in fact["exercises_features"]:
            feature_norm = _normalize(feature)
            if not feature_norm or len(feature_norm) < _MIN_FEATURE_LEN:
                continue
            if feature_norm == affected_norm:
                match_kind = "EXACT"
            elif affected_norm in feature_norm or feature_norm in affected_norm:
                match_kind = "SUBSTRING"
            else:
                continue
            matches.append({
                "usage_fact_id": fact["id"], "kind": fact["kind"], "matched_feature": feature,
                "match_kind": match_kind, "evidence": fact["evidence"],
            })

    if matches:
        return {
            "status": STATUS_CORRELATED,
            "reason": f"{len(matches)} real project usage fact(s) declare exercising "
                      f"{affected!r} (or a feature name overlapping it)",
            "matches": matches,
        }
    return {
        "status": STATUS_NOT_CORRELATED,
        "reason": f"{len(usage_facts)} project usage fact(s) were supplied and checked; none "
                  f"declares exercising {affected!r} -- a real gap, not an absence of evidence",
        "matches": [],
    }


# ---------------------------------------------------------------------------
# top-level assembly -- distilled document + correlation report
# ---------------------------------------------------------------------------

def build_erratum_correlation(*, reference_record: Optional[Dict[str, Any]] = None,
                               reference_record_path=None,
                               usage_facts: Optional[Sequence[Dict[str, Any]]] = None,
                               max_items: int = DEFAULT_MAX_ITEMS,
                               max_evidence_chars: int = DEFAULT_MAX_EVIDENCE_CHARS) -> Dict[str, Any]:
    """Build the full erratum-correlation report. `reference_record` /
    `reference_record_path` is a `.reference.json` record (or its path)
    produced by `vip_user_guide_distill.distill_user_guide()` for a REAL
    errata sheet / known-limitations document / release notes (pass
    `doc_kind="vip_user_guide"` or the doc's own real kind). Neither
    supplied -> a report whose top-level `status` is NOT_AVAILABLE, never a
    guess. `usage_facts` are validated via `validate_usage_facts()` and may
    raise `VipErratumCorrelationError` on a malformed/uncited one."""
    validated_facts = validate_usage_facts(usage_facts)

    def _not_available(reason: str) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "generator": {"tool": "dv_harness.vip_erratum_correlation", "version": SCHEMA_VERSION},
            "status": STATUS_NOT_AVAILABLE,
            "reason": reason,
            "source": None,
            "usage_facts_supplied": len(validated_facts),
            "entries": [],
            "summary": {s: 0 for s in CORRELATION_STATUSES},
        }

    if reference_record is None and reference_record_path is None:
        return _not_available(
            "no VIP erratum/known-limitations document was supplied -- distil the real document "
            "first with dv_harness.vip_user_guide_distill.distill_user_guide(source, out_dir) "
            "and pass its .reference.json record (or path) here"
        )

    if reference_record is None:
        try:
            record = vip_user_guide_distill.load_reference_record(reference_record_path)
        except vip_user_guide_distill.UserGuideDistillError as exc:
            return _not_available(
                f"could not load the erratum document reference record at "
                f"{reference_record_path!r}: {exc}"
            )
    else:
        record = reference_record
        missing = [k for k in ("schema_version", "doc_kind", "title", "source_document",
                                "full_text_extract") if k not in record]
        if missing:
            return _not_available(
                f"supplied reference_record is not a vip_user_guide_distill reference record -- "
                f"missing {missing} -- produce one with distill_user_guide() rather than passing "
                "an arbitrary dict"
            )

    fulltext_path = Path(record["full_text_extract"]["path"])
    if not fulltext_path.is_file():
        return _not_available(
            f"the erratum document's full-text extract is missing on disk: {fulltext_path} -- "
            "re-run dv_harness.vip_user_guide_distill.distill_user_guide() against the real "
            "source document"
        )
    full_text = fulltext_path.read_text(encoding="utf-8", errors="replace")
    recomputed_sha256 = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    recorded_sha256 = (record.get("full_text_extract") or {}).get("sha256")
    fulltext_verified = (recomputed_sha256 == recorded_sha256) if recorded_sha256 else None

    document_label = record.get("title") or str(fulltext_path)
    scan = scan_erratum_text(
        full_text, document_label=document_label, fulltext_path=str(fulltext_path),
        max_items=max_items, max_evidence_chars=max_evidence_chars,
    )

    entries: List[Dict[str, Any]] = []
    summary = {s: 0 for s in CORRELATION_STATUSES}
    for entry in scan["entries"]:
        correlation = correlate_entry(entry, validated_facts)
        merged = dict(entry)
        merged["correlation"] = correlation
        entries.append(merged)
        summary[correlation["status"]] += 1

    if not scan["entries"]:
        status = STATUS_NOT_AVAILABLE
        reason = (
            "no heading in the document matched the errata/known-limitations structural marker "
            "keywords, or a matching heading was found but no line inside it matched a recognised "
            "erratum item shape ('ID: description' / 'ID  description' / a bulleted or numbered "
            "list item) -- this is a real observation about the document's structure, not an "
            "extraction failure"
        ) if not scan["marker_seen"] else (
            "an errata/known-limitations heading was found in the document, but no line inside "
            "that section matched a recognised erratum item shape"
        )
    else:
        status = "SCANNED"
        reason = None

    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"tool": "dv_harness.vip_erratum_correlation", "version": SCHEMA_VERSION},
        "status": status,
        "reason": reason,
        "source": {
            "doc_kind": record.get("doc_kind"),
            "title": record.get("title"),
            "reference_record_path": str(reference_record_path) if reference_record_path else None,
            "source_document": record.get("source_document"),
            "fulltext_path": str(fulltext_path),
            "fulltext_sha256_verified": fulltext_verified,
            "marker_seen": scan["marker_seen"],
        },
        "usage_facts_supplied": len(validated_facts),
        "entries": entries,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# CLI front door -- python -m dv_harness.vip_erratum_correlation
# (no dv-harness verb: cli.py/gates.py are out of scope for this task, per
# this batch's own house rule against editing either while under concurrent
# edit pressure from other items in the same batch.)
# ---------------------------------------------------------------------------

def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="vip-erratum-correlation")
    parser.add_argument("--reference-record", required=True,
                         help="path to a vip_user_guide_distill .reference.json record")
    parser.add_argument("--usage-facts",
                         help="path to a JSON file: a list of project usage-fact objects "
                              "({id, kind, exercises_features, evidence})")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)

    usage_facts = None
    if args.usage_facts:
        usage_facts = json.loads(Path(args.usage_facts).read_text(encoding="utf-8"))

    try:
        report = build_erratum_correlation(
            reference_record_path=args.reference_record, usage_facts=usage_facts)
    except VipErratumCorrelationError as e:
        print(f"malformed usage fact: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if report["status"] == STATUS_NOT_AVAILABLE:
            print(f"NOT_AVAILABLE: {report['reason']}")
        else:
            for e in report["entries"]:
                label = e["erratum_id"] or f"#{e['sequence_index']}"
                c = e["correlation"]
                print(f"{label:24s} feature={e['affected_feature']!r:40s} "
                      f"{c['status']:35s} {c['reason']}")
            print(f"\nsummary: {report['summary']}")

    if report["status"] == STATUS_NOT_AVAILABLE:
        return 2
    return 1 if report["summary"][STATUS_NOT_CORRELATED] else 0


if __name__ == "__main__":
    sys.exit(execute_verb())
