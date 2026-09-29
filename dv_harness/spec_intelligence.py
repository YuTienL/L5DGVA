"""dv_harness/spec_intelligence.py -- the Spec Intelligence layer's SCHEMA and
its validation/re-derivation gate: a document STRUCTURE index (SpecMap), an
atomic-requirement extraction/relation/dependency SHAPE that lands its facts
in the two vocabularies this repo already owns, and nothing that claims to
"understand" a spec on its own.

THE GAP THIS CLOSES, and why this is a SCHEMA rather than an NLP engine.
Turning protocol prose into requirements is inherently an LLM-reading-a-
document act, not something this module can compute the way `verible_parser.py`
computes RTL facts. Building a fake "spec understander" would be exactly the
fabrication the Evidence Truth Rule forbids. What IS buildable, and what this
module is, is the CONTRACT an extraction result must satisfy to be trusted
downstream: a real, mechanical structure index over the document (never full
body text), and a real, mechanical validation/re-derivation gate over
whatever an agent (or a future extractor) claims it found -- the same
discipline `requirement_contract.py` already applies to a single requirement
record, lifted to a SET of atomic requirements plus the relations between
them.

REUSE, NOT A SECOND VOCABULARY (as required). This module invents exactly two
new vocabularies -- the relation kinds (DUPLICATES/REFINES/EXTENDS/
CONFLICTS_WITH) and the derivation tags (EXPLICIT/IMPLICIT_HIGH_CONFIDENCE/
IMPLICIT_REVIEW_REQUIRED) -- because nothing in this repo names either. Every
other fact lands in a vocabulary this repo already owns:
  * Each atomic requirement IS a `requirement_contract.py` canonical-contract
    record (`contract_schema_version` required), validated by
    `validate_requirement_contract()` and analysed by
    `analyze_requirement_contract()` -- imported and called, never re-typed.
    Its COMPLETE/PARTIAL/AMBIGUOUS/CONTRADICTORY/UNKNOWN status is that
    module's, re-derived by that module's own `derive_status()`.
  * The extraction batch declares `evidence_provenance` in
    `evidence_provenance.py`'s own AGENT_SELF_ATTESTED/TOOL_DERIVED/
    SIMULATION_DERIVED vocabulary, checked with that module's own field name,
    accepted-values tuple and independently-derived set -- imported, never
    re-spelled. Reading a spec is, honestly, almost always
    AGENT_SELF_ATTESTED; the module accepts that for free and charges a real,
    on-disk artifact for anything stronger, exactly as that module's own
    six-gate enforcement does.

SpecMap LAYERS ON `vip_user_guide_distill.py`; IT DOES NOT RE-EXTRACT. That
module is this repo's one real document distiller (PDF via `pypdf`, or a
pre-extracted `.txt`) and already produces a numbered-heading section index
with real page/char-offset evidence. `build_spec_map()` calls it (no second
PDF/text extractor exists here), then reads back its OWN rendered
`.reference.md` section table (never re-runs heading detection) and adds two
NEW mechanical scans over the already-produced full-text extract: `Table N.M`
caption locations, and a keyword flag on which section headings are register
chapters. A SpecMap therefore carries sections/tables/register-chapter
LOCATIONS only -- headings, table captions, page numbers, character offsets --
and never one sentence of the document's own body text, the same discipline
`vip_symbol_index.py` keeps against retaining method bodies.

DEDUP/RELATION VALIDATION IS RE-DERIVATION, NOT TRUST. An agent's claim that
two requirements DUPLICATE or CONFLICT_WITH each other is a judgment, so it is
cross-checked against the requirements' own text (a plain `difflib`
similarity over their RESOLVED `feature`/`stimulus`/`expected_result` fields,
via `requirement_contract.is_resolved()`) the same way `derive_status()`
cross-checks a requirement's own declared status. A declared DUPLICATES pair
whose text barely overlaps is flagged; a pair that looks near-identical with
NO declared relation is flagged the other way. A CONFLICTS_WITH relation is
cross-checked against the underlying contract's own re-derived status: it
should correspond to at least one side deriving CONTRADICTORY, or the
relation is reported as filed nowhere the contract itself would show it.

IMPLICIT-REQUIREMENT FLAGGING RE-USES THE CONTRACT RATHER THAN INVENTING A
SECOND "OPEN QUESTION" CONCEPT. IMPLICIT_REVIEW_REQUIRED requires the
underlying requirement to itself derive AMBIGUOUS or CONTRADICTORY through
`requirement_contract.derive_status()` -- i.e. a real, filed, unresolved
ambiguity/contradiction, not a second free-floating flag nobody else can see.
EXPLICIT requires a real verbatim `source.quote`; the two IMPLICIT_* values
require a `derivation_basis` naming what explicit material the inference
rests on.

DEPENDENCY GRAPH. `build_dependency_graph()` is genuinely new (no generic DAG
utility exists in this repo for this shape): nodes are validated requirement
ids, edges are the four relation kinds, and only the two HIERARCHICAL kinds
(REFINES/EXTENDS) are checked for cycles and given a deterministic
topological order (Kahn's algorithm) -- DUPLICATES/CONFLICTS_WITH are
symmetric facts about a pair, not an ordering, and are reported as edges but
never fed into cycle detection.

WHAT THIS MODULE DOES NOT DO, stated rather than implied closed. It does not
read a spec document and produce requirements -- that is an agent's (or a
future extractor's) act, and this module's tests build the extraction
document BY HAND for exactly that reason: they validate the SCHEMA and the
re-derivation gate, never a claim that this code "understood" a spec. It
arbitrates nothing (a CONTRADICTORY/CONFLICTS_WITH pair stops there, exactly
as `requirement_contract.py`'s own ARBITRATION boundary states) and there is
deliberately no stage gate -- a gate that passed on hand-typed relations
nobody re-derived would be worse than none.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .requirement_contract import (
    STATUS_CONTRADICTORY, STATUS_AMBIGUOUS,
    SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO,
    validate_requirement_contract, analyze_requirement_contract, derive_status,
    declares_contract_shape, is_resolved,
    RequirementContractValidationError,
)
from .evidence_provenance import (
    PROVENANCE_FIELD, DERIVATION_FIELD,
    AGENT_SELF_ATTESTED, TOOL_DERIVED, SIMULATION_DERIVED,
    PROVENANCE_VALUES, INDEPENDENTLY_DERIVED,
    caveat_for as evidence_caveat_for,
)
from .vip_user_guide_distill import distill_user_guide, load_reference_record, UserGuideDistillError

SCHEMA_VERSION = "1.0"

# --------------------------------------------------------------------------
# New vocabulary #1: requirement-pair relations. Nothing in this repo named
# these before; requirement_contract.py's own `ambiguities`/`contradictions`
# are WITHIN one record, not a typed relation BETWEEN two.
# --------------------------------------------------------------------------
RELATION_DUPLICATES = "DUPLICATES"
RELATION_REFINES = "REFINES"
RELATION_EXTENDS = "EXTENDS"
RELATION_CONFLICTS_WITH = "CONFLICTS_WITH"
RELATION_KINDS: Tuple[str, ...] = (
    RELATION_DUPLICATES, RELATION_REFINES, RELATION_EXTENDS, RELATION_CONFLICTS_WITH,
)

#: REFINES/EXTENDS impose an ORDER (a more specific requirement refines/
#: extends a more general one) and are the only two kinds checked for cycles
#: and given a topological order. DUPLICATES/CONFLICTS_WITH are symmetric
#: facts about a pair and carry no direction to order by.
HIERARCHICAL_RELATION_KINDS: frozenset = frozenset({RELATION_REFINES, RELATION_EXTENDS})

# --------------------------------------------------------------------------
# New vocabulary #2: is this requirement's very existence stated outright by
# the spec, or inferred? Distinct from requirement_contract.py's `confidence`
# (how sure the extraction is about the CONTENT of a requirement that is
# already on the table) and from its `status` (is this record internally
# coherent). This is "was this requirement asserted, or derived".
# --------------------------------------------------------------------------
DERIVATION_EXPLICIT = "EXPLICIT"
DERIVATION_IMPLICIT_HIGH_CONFIDENCE = "IMPLICIT_HIGH_CONFIDENCE"
DERIVATION_IMPLICIT_REVIEW_REQUIRED = "IMPLICIT_REVIEW_REQUIRED"
DERIVATION_VALUES: Tuple[str, ...] = (
    DERIVATION_EXPLICIT, DERIVATION_IMPLICIT_HIGH_CONFIDENCE, DERIVATION_IMPLICIT_REVIEW_REQUIRED,
)

#: A declared DUPLICATES relation whose requirement text similarity falls
#: below this is reported, not trusted -- an agent's semantic claim is
#: cross-checked against the text it is supposedly describing, the same
#: discipline STATUS_OVERCLAIMED applies to a declared status.
DUPLICATE_SIMILARITY_LOW_THRESHOLD = 0.5

#: A pair with NO declared relation whose text similarity is at or above this
#: is reported as a possibly-missed duplicate. Deliberately far above the
#: LOW threshold above: this direction risks a false positive (two genuinely
#: distinct but similarly-worded requirements), so the bar is high.
POSSIBLE_UNDECLARED_DUPLICATE_THRESHOLD = 0.92

#: The pairwise undeclared-duplicate scan is O(n^2) text comparisons. Above
#: this many contract-shaped requirements it is skipped and reported as
#: skipped (never silently omitted), rather than silently costing an
#: unbounded amount of time on a very large extraction batch.
MAX_DEDUP_SCAN_SIZE = 200

#: Fields whose RESOLVED (requirement_contract.is_resolved) text is compared
#: for requirement similarity -- the three fields that actually describe
#: requirement BEHAVIOUR, not its bookkeeping (priority/criticality/status/...).
_SIMILARITY_FIELDS: Tuple[str, ...] = ("feature", "stimulus", "expected_result")


class SpecIntelligenceError(RuntimeError):
    """A SpecMap or extraction-document artifact could not be built or
    loaded from a real source -- an unsupported/missing source document, a
    missing distilled artifact it depends on, or a file that is not one of
    this module's own real records. Raised rather than returning a partial
    artifact, the same discipline `vip_user_guide_distill.UserGuideDistillError`
    already applies to its own artifacts."""


def _finding(severity: str, code: str, requirement_id: Any, detail: str, **extra: Any) -> dict:
    out = {"severity": severity, "code": code, "requirement_id": requirement_id, "detail": detail}
    out.update(extra)
    return out


# ==========================================================================
# SpecMap: a document structure index -- sections/tables/register-chapter
# LOCATIONS only, never body text. Layered on vip_user_guide_distill.py.
# ==========================================================================

_SECTION_ROW_RE = re.compile(r"^\|\s*(?P<heading>.+?)\s*\|\s*(?P<page>[^|]*?)\s*\|\s*(?P<offset>\d+)\s*\|\s*$")
_HEADING_NUMBER_RE = re.compile(r"^(?P<number>\d+(?:\.\d+){0,4})\.?\s+(?P<title>.*)$")

#: A table caption line, e.g. "Table 4.2 Register Bit Assignments" or
#: "Table 4.2: Register Bit Assignments". Deliberately a DIFFERENT pattern
#: from vip_user_guide_distill's own numbered-heading regex (that one
#: anchors on a line that STARTS with a bare number; this one requires the
#: literal word "Table" first), so the two detections cannot collide.
_TABLE_CAPTION_RE = re.compile(
    r"^\s*Table\s+(?P<number>\d+(?:[.\-]\d+){0,4})\s*[:.\-]?\s+(?P<caption>\S.{0,110})$",
    re.IGNORECASE,
)
_MAX_TABLE_CAPTION_CHARS = 120

#: Keyword flag for "this heading is a register-map/register-description
#: chapter" -- a mechanical, keyword-based, reproducible property of the
#: heading TEXT already recovered by vip_user_guide_distill, not a semantic
#: judgment about the chapter's content. Longest phrase first (mirrors
#: requirement_contract.AMBIGUOUS_LANGUAGE_PHRASES's own convention) so
#: "register map" is cited whole rather than shadowed by the bare "register"
#: it contains.
_REGISTER_CHAPTER_KEYWORDS: Tuple[str, ...] = tuple(sorted((
    "register map", "register description", "register summary",
    "register set", "programming model", "register",
), key=len, reverse=True))


def _parse_section_table(reference_md_path: Path) -> Tuple[List[dict], List[dict]]:
    """Recover the section list from vip_user_guide_distill's OWN rendered
    `.reference.md` table -- never re-running heading detection. Returns
    (sections, findings); a document with no numbered headings (that
    module's own honest "no headings detected" case) yields ([], [])."""
    lines = reference_md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    sections: List[dict] = []
    findings: List[dict] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped == "| Section | Page | Char offset |":
            in_table = True
            continue
        if not in_table:
            continue
        if stripped.startswith("|---"):
            continue
        if not stripped.startswith("|"):
            in_table = False
            continue
        m = _SECTION_ROW_RE.match(stripped)
        if not m:
            findings.append({"severity": SEVERITY_INFO, "code": "SECTION_ROW_PARSE_SKIPPED",
                              "detail": f"could not parse section-index row: {stripped!r}"})
            continue
        heading = m.group("heading")
        page_raw = m.group("page").strip()
        page = int(page_raw) if page_raw.isdigit() else None
        offset = int(m.group("offset"))
        num_m = _HEADING_NUMBER_RE.match(heading)
        number = num_m.group("number") if num_m else None
        sections.append({"heading": heading, "number": number, "page": page, "char_offset": offset})
    return sections, findings


def _find_tables(fulltext: str) -> List[dict]:
    """Table-caption locations only (number/caption/char_offset) -- never a
    table's own row content. A genuinely new scan; nothing in
    vip_user_guide_distill.py detects tables."""
    tables: List[dict] = []
    offset = 0
    for line in fulltext.splitlines(keepends=True):
        stripped = line.strip()
        m = _TABLE_CAPTION_RE.match(stripped)
        if m and len(stripped) <= _MAX_TABLE_CAPTION_CHARS:
            tables.append({
                "number": m.group("number"),
                "caption": m.group("caption").strip(),
                "char_offset": offset,
            })
        offset += len(line)
    return tables


def _flag_register_chapters(sections: Sequence[dict]) -> List[dict]:
    out: List[dict] = []
    for s in sections:
        lowered = s["heading"].lower()
        matched = next((kw for kw in _REGISTER_CHAPTER_KEYWORDS if kw in lowered), None)
        if matched:
            out.append({**s, "matched_keyword": matched})
    return out


def build_spec_map(reference_json_path, out_dir, *, source_label: Optional[str] = None) -> dict:
    """Build a SpecMap from a `.reference.json` that
    `vip_user_guide_distill.distill_user_guide()` already produced (this
    module performs no PDF/text extraction of its own -- see
    `distill_spec_map()` to do both steps in one call). Writes
    `<stem>.spec_map.json` under `out_dir` and returns the record."""
    record = load_reference_record(reference_json_path)
    reference_md_path = Path(record["distilled_reference"]["path"])
    fulltext_path = Path(record["full_text_extract"]["path"])
    if not reference_md_path.is_file():
        raise SpecIntelligenceError(
            f"{reference_json_path}: distilled_reference path does not exist on disk: {reference_md_path}")
    if not fulltext_path.is_file():
        raise SpecIntelligenceError(
            f"{reference_json_path}: full_text_extract path does not exist on disk: {fulltext_path}")

    sections, section_findings = _parse_section_table(reference_md_path)
    fulltext = fulltext_path.read_text(encoding="utf-8", errors="replace")
    tables = _find_tables(fulltext)
    register_chapters = _flag_register_chapters(sections)

    spec_map = {
        "schema_version": SCHEMA_VERSION,
        "title": source_label or record.get("title"),
        "source_document": record["source_document"],
        "reference_record_path": str(Path(reference_json_path)),
        "sections": sections,
        "section_count": len(sections),
        "tables": tables,
        "table_count": len(tables),
        "register_chapters": register_chapters,
        "register_chapter_count": len(register_chapters),
        "findings": section_findings,
    }

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(reference_json_path).name
    if stem.endswith(".reference.json"):
        stem = stem[: -len(".reference.json")]
    else:
        stem = Path(reference_json_path).stem
    out_path = out / f"{stem}.spec_map.json"
    out_path.write_text(json.dumps(spec_map, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    spec_map["spec_map_path"] = str(out_path)
    return spec_map


def distill_spec_map(source_path, out_dir, *, title: Optional[str] = None) -> dict:
    """Convenience one-call form: run the REAL document distillation
    (`vip_user_guide_distill.distill_user_guide`, `doc_kind="protocol_spec"`
    -- no second document extractor exists or is built here) and layer this
    module's SpecMap on top of its output. Raises `UserGuideDistillError` on
    an extraction failure (missing `pypdf`, unsupported suffix, ...) and
    `SpecIntelligenceError` on a SpecMap-layer failure."""
    record = distill_user_guide(source_path, out_dir, title=title, doc_kind="protocol_spec")
    stem = Path(source_path).stem
    reference_json_path = Path(out_dir) / f"{stem}.reference.json"
    return build_spec_map(reference_json_path, out_dir, source_label=title)


def load_spec_map(path) -> dict:
    """Load a `.spec_map.json` produced by `build_spec_map()`. Raises
    `SpecIntelligenceError` on a record that is not one, mirroring
    `vip_user_guide_distill.load_reference_record()`'s own discipline."""
    p = Path(path)
    try:
        record = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecIntelligenceError(f"{p}: not a readable JSON SpecMap record: {exc}") from exc
    if not isinstance(record, dict):
        raise SpecIntelligenceError(f"{p}: SpecMap record must be a JSON object, got {type(record).__name__}")
    for required in ("schema_version", "source_document", "sections", "tables", "register_chapters"):
        if required not in record:
            raise SpecIntelligenceError(
                f"{p}: not a spec_intelligence SpecMap record -- missing {required!r}. "
                "Produce it with build_spec_map()/distill_spec_map()."
            )
    return record


# ==========================================================================
# Requirement similarity (the re-derivation half of dedup/relation checks)
# ==========================================================================

def _requirement_text_for_similarity(record: dict) -> Optional[str]:
    parts = []
    for field_name in _SIMILARITY_FIELDS:
        value = record.get(field_name)
        if is_resolved(value, field_name):
            parts.append(str(value).strip().casefold())
    return " | ".join(parts) if parts else None


def requirement_similarity(a: dict, b: dict) -> Optional[float]:
    """A [0,1] text-similarity score over two requirement_contract records'
    RESOLVED feature/stimulus/expected_result text, or None when either side
    has nothing resolved to compare -- 'we could not check' is never a 0.0."""
    ta, tb = _requirement_text_for_similarity(a), _requirement_text_for_similarity(b)
    if ta is None or tb is None:
        return None
    return SequenceMatcher(None, ta, tb).ratio()


# ==========================================================================
# evidence_provenance.py reuse -- one field, the module's own vocabulary
# ==========================================================================

def _resolve_under_root(root: Path, raw_path: str) -> Optional[Path]:
    """Same policy as evidence_provenance._resolve_artifact (kept as a
    separate small copy here rather than importing that private helper):
    resolve raw_path under root, refusing a path that escapes it."""
    p = Path(str(raw_path))
    root = Path(root).resolve()
    candidate = p if p.is_absolute() else root / p
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _check_evidence_provenance(document: dict, root: Path) -> List[dict]:
    raw = document.get(PROVENANCE_FIELD)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return [_finding(
            SEVERITY_ERROR, "EVIDENCE_PROVENANCE_MISSING", None,
            f"the extraction document must declare '{PROVENANCE_FIELD}' (one of "
            f"{list(PROVENANCE_VALUES)}); '{AGENT_SELF_ATTESTED}' is always accepted and needs "
            "nothing else -- reading a spec is honestly almost always self-attested.")]
    provenance = raw.strip() if isinstance(raw, str) else raw
    if provenance not in PROVENANCE_VALUES:
        return [_finding(
            SEVERITY_ERROR, "EVIDENCE_PROVENANCE_INVALID", None,
            f"{provenance!r} is not one of {list(PROVENANCE_VALUES)}", declared=provenance)]
    if provenance not in INDEPENDENTLY_DERIVED:
        return []
    derivation = document.get(DERIVATION_FIELD)
    tool = (derivation or {}).get("tool") if isinstance(derivation, dict) else None
    artifact = (derivation or {}).get("artifact_path") if isinstance(derivation, dict) else None
    if not isinstance(derivation, dict) or not str(tool or "").strip() or not str(artifact or "").strip():
        return [_finding(
            SEVERITY_ERROR, "EVIDENCE_PROVENANCE_DERIVATION_MISSING", None,
            f"declaring {provenance!r} claims a real producer, so '{DERIVATION_FIELD}' must name "
            "both a 'tool' and an 'artifact_path' that exists on disk.")]
    resolved = _resolve_under_root(root, str(artifact))
    if resolved is None or not resolved.exists():
        return [_finding(
            SEVERITY_ERROR, "EVIDENCE_PROVENANCE_ARTIFACT_NOT_FOUND", None,
            f"artifact_path {artifact!r} does not exist under the project root.",
            tool=str(tool), artifact_path=str(artifact))]
    return []


# ==========================================================================
# Atomic requirement extraction: requirement_contract.py reuse + this
# module's own two new fields (extraction_id, derivation, derivation_basis).
# ==========================================================================

def _analyze_one_atomic(rec: Any) -> Tuple[List[dict], Optional[dict]]:
    """Validate one atomic-extraction record. Returns (findings, record) where
    `record` is the rec itself when it is schema-valid contract-shaped
    content (usable for relation/similarity/graph checks below), or None
    when it is not (nothing downstream should reason over a record that did
    not even validate)."""
    rid = rec.get("requirement_id") if isinstance(rec, dict) else None
    if not isinstance(rec, dict):
        return [_finding(SEVERITY_ERROR, "ATOMIC_REQUIREMENT_NOT_OBJECT", rid,
                          "atomic requirement record must be a JSON object")], None
    if not declares_contract_shape(rec):
        return [_finding(
            SEVERITY_ERROR, "NOT_CONTRACT_SHAPED", rid,
            "record does not declare contract_schema_version; spec_intelligence lands extraction "
            "results in requirement_contract.py's own field/status vocabulary, never a parallel "
            "one, and refuses to reason over a record that has not adopted it.")], None
    try:
        validate_requirement_contract(rec)
    except RequirementContractValidationError as exc:
        return [_finding(SEVERITY_ERROR, "SCHEMA_VALIDATION_FAILED", rid, str(exc))], None

    findings: List[dict] = list(analyze_requirement_contract(rec))

    extraction_id = rec.get("extraction_id")
    if not isinstance(extraction_id, str) or not extraction_id.strip():
        findings.append(_finding(SEVERITY_ERROR, "MISSING_EXTRACTION_ID", rid,
                                  "atomic requirement carries no non-empty 'extraction_id'"))

    derivation = rec.get("derivation")
    if derivation not in DERIVATION_VALUES:
        findings.append(_finding(
            SEVERITY_ERROR, "INVALID_DERIVATION", rid,
            f"derivation {derivation!r} is not one of {list(DERIVATION_VALUES)}"))
        return findings, rec

    if derivation == DERIVATION_EXPLICIT:
        source = rec.get("source")
        quote = source.get("quote") if isinstance(source, dict) else None
        if not str(quote or "").strip():
            findings.append(_finding(
                SEVERITY_ERROR, "EXPLICIT_REQUIRES_QUOTE", rid,
                "derivation is EXPLICIT but source.quote carries no real verbatim citation"))
    else:
        basis = rec.get("derivation_basis")
        if not str(basis or "").strip():
            findings.append(_finding(
                SEVERITY_ERROR, "IMPLICIT_REQUIRES_DERIVATION_BASIS", rid,
                f"derivation is {derivation} but 'derivation_basis' does not name what explicit "
                "material this requirement was inferred from"))
        if derivation == DERIVATION_IMPLICIT_REVIEW_REQUIRED:
            derived_status, reason = derive_status(rec)
            if derived_status not in (STATUS_AMBIGUOUS, STATUS_CONTRADICTORY):
                findings.append(_finding(
                    SEVERITY_ERROR, "IMPLICIT_REVIEW_REQUIRED_WITHOUT_OPEN_ISSUE", rid,
                    "derivation is IMPLICIT_REVIEW_REQUIRED but the record's own content derives "
                    f"{derived_status}, not AMBIGUOUS/CONTRADICTORY: {reason}. Reusing "
                    "requirement_contract.py's own ambiguities/contradictions is how this "
                    "requirement stays visibly open, rather than a second free-floating flag.",
                    derived_status=derived_status))
        if derivation == DERIVATION_IMPLICIT_HIGH_CONFIDENCE and rec.get("confidence") not in ("HIGH", "MEDIUM"):
            findings.append(_finding(
                SEVERITY_ERROR, "IMPLICIT_HIGH_CONFIDENCE_MISMATCH", rid,
                f"derivation claims IMPLICIT_HIGH_CONFIDENCE but the contract's own 'confidence' "
                f"field is {rec.get('confidence')!r}, not HIGH/MEDIUM"))

    return findings, rec


# ==========================================================================
# Relations: DUPLICATES / REFINES / EXTENDS / CONFLICTS_WITH
# ==========================================================================

def _analyze_relations(relations: Sequence[Any], valid_records: Dict[str, dict]) -> List[dict]:
    findings: List[dict] = []
    seen_pairs: Dict[Tuple[str, str], List[str]] = {}

    for rel in relations:
        if not isinstance(rel, dict):
            findings.append(_finding(SEVERITY_ERROR, "RELATION_NOT_OBJECT", None,
                                      "relation entry must be a JSON object"))
            continue
        frm, to, kind = rel.get("from_requirement_id"), rel.get("to_requirement_id"), rel.get("kind")
        rationale = rel.get("rationale")

        if kind not in RELATION_KINDS:
            findings.append(_finding(SEVERITY_ERROR, "RELATION_INVALID_KIND", frm,
                                      f"kind {kind!r} is not one of {list(RELATION_KINDS)}",
                                      to_requirement_id=to))
            continue
        if not isinstance(frm, str) or not frm or not isinstance(to, str) or not to:
            findings.append(_finding(SEVERITY_ERROR, "RELATION_MISSING_ENDPOINT", frm,
                                      "from_requirement_id/to_requirement_id must both be non-empty strings",
                                      to_requirement_id=to))
            continue
        if frm == to:
            findings.append(_finding(SEVERITY_ERROR, "RELATION_SELF_REFERENCE", frm,
                                      f"a requirement cannot declare a {kind} relation to itself"))
            continue
        if not str(rationale or "").strip():
            findings.append(_finding(SEVERITY_ERROR, "RELATION_MISSING_RATIONALE", frm,
                                      f"{kind} relation to {to!r} carries no rationale",
                                      to_requirement_id=to))

        missing = [x for x in (frm, to) if x not in valid_records]
        if missing:
            findings.append(_finding(
                SEVERITY_ERROR, "RELATION_UNKNOWN_REQUIREMENT", frm,
                f"{kind} relation names requirement id(s) not present as a valid contract-shaped "
                f"record: {missing}", to_requirement_id=to))
            continue

        seen_pairs.setdefault(tuple(sorted((frm, to))), []).append(kind)

        if kind == RELATION_DUPLICATES:
            score = requirement_similarity(valid_records[frm], valid_records[to])
            if score is not None and score < DUPLICATE_SIMILARITY_LOW_THRESHOLD:
                findings.append(_finding(
                    SEVERITY_WARNING, "DUPLICATES_SIMILARITY_LOW", frm,
                    f"declared DUPLICATES of {to!r} but text similarity is only {score:.2f}",
                    to_requirement_id=to, similarity=round(score, 3)))
        if kind == RELATION_CONFLICTS_WITH:
            status_a, _ = derive_status(valid_records[frm])
            status_b, _ = derive_status(valid_records[to])
            if STATUS_CONTRADICTORY not in (status_a, status_b):
                findings.append(_finding(
                    SEVERITY_WARNING, "CONFLICT_RELATION_NOT_FILED_IN_CONTRACT", frm,
                    f"CONFLICTS_WITH {to!r} declared but neither requirement's own contract "
                    f"re-derives CONTRADICTORY (derives {status_a}/{status_b})",
                    to_requirement_id=to))

    for (a, b), kinds in seen_pairs.items():
        kind_set = set(kinds)
        if RELATION_DUPLICATES in kind_set and RELATION_CONFLICTS_WITH in kind_set:
            findings.append(_finding(
                SEVERITY_ERROR, "RELATION_KIND_CONTRADICTION", a,
                f"{a!r} and {b!r} are declared both DUPLICATES and CONFLICTS_WITH, which cannot "
                "both be true of the same pair", to_requirement_id=b))
        counts: Dict[str, int] = {}
        for k in kinds:
            counts[k] = counts.get(k, 0) + 1
        for k, n in counts.items():
            if n > 1:
                findings.append(_finding(
                    SEVERITY_WARNING, "DUPLICATE_RELATION_DECLARATION", a,
                    f"{k} declared {n} times between {a!r} and {b!r}", to_requirement_id=b))

    return findings


def _scan_undeclared_duplicates(valid_records: Dict[str, dict], relations: Sequence[Any]) -> List[dict]:
    declared_pairs = set()
    for rel in relations:
        if isinstance(rel, dict):
            frm, to = rel.get("from_requirement_id"), rel.get("to_requirement_id")
            if isinstance(frm, str) and isinstance(to, str) and frm and to:
                declared_pairs.add(tuple(sorted((frm, to))))

    ids = sorted(valid_records.keys())
    findings: List[dict] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            if (a, b) in declared_pairs:
                continue
            score = requirement_similarity(valid_records[a], valid_records[b])
            if score is not None and score >= POSSIBLE_UNDECLARED_DUPLICATE_THRESHOLD:
                findings.append(_finding(
                    SEVERITY_WARNING, "POSSIBLE_UNDECLARED_DUPLICATE_PAIR", a,
                    f"text similarity with {b!r} is {score:.2f} with no declared relation between "
                    "them", to_requirement_id=b, similarity=round(score, 3)))
    return findings


# ==========================================================================
# Dependency graph over REFINES/EXTENDS (+ DUPLICATES/CONFLICTS_WITH edges,
# not ordered)
# ==========================================================================

def _find_cycle(nodes: Sequence[str], adjacency: Dict[str, List[str]]) -> Optional[List[str]]:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}
    stack: List[str] = []
    result: Optional[List[str]] = None

    def dfs(u: str) -> None:
        nonlocal result
        color[u] = GRAY
        stack.append(u)
        for v in adjacency.get(u, []):
            if result is not None:
                return
            if color.get(v) == GRAY:
                idx = stack.index(v)
                result = stack[idx:] + [v]
                return
            if color.get(v, WHITE) == WHITE:
                dfs(v)
                if result is not None:
                    return
        stack.pop()
        color[u] = BLACK

    for n in sorted(nodes):
        if color[n] == WHITE and result is None:
            dfs(n)
    return result


def _topological_order(nodes: Sequence[str], adjacency: Dict[str, List[str]]) -> List[str]:
    indeg = {n: 0 for n in nodes}
    for u in nodes:
        for v in adjacency.get(u, []):
            indeg[v] += 1
    ready = sorted(n for n in nodes if indeg[n] == 0)
    order: List[str] = []
    while ready:
        ready.sort()
        u = ready.pop(0)
        order.append(u)
        for v in adjacency.get(u, []):
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
    return order


def build_dependency_graph(valid_records: Dict[str, dict], relations: Sequence[Any]) -> dict:
    """Nodes are validated requirement ids; edges are the declared relations
    between them. Only REFINES/EXTENDS edges feed cycle detection and the
    topological order -- DUPLICATES/CONFLICTS_WITH are symmetric facts, not
    an ordering, and are still reported as edges."""
    nodes = sorted(valid_records.keys())
    adjacency: Dict[str, List[str]] = {n: [] for n in nodes}
    edges: List[dict] = []
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        frm, to, kind = rel.get("from_requirement_id"), rel.get("to_requirement_id"), rel.get("kind")
        if kind not in RELATION_KINDS or frm not in valid_records or to not in valid_records or frm == to:
            continue
        edges.append({"from": frm, "to": to, "kind": kind})
        if kind in HIERARCHICAL_RELATION_KINDS:
            adjacency[frm].append(to)

    cycle = _find_cycle(nodes, adjacency)
    topo = None if cycle else _topological_order(nodes, adjacency)
    kind_counts: Dict[str, int] = {}
    for e in edges:
        kind_counts[e["kind"]] = kind_counts.get(e["kind"], 0) + 1

    return {
        "nodes": nodes,
        "edges": edges,
        "edge_count_by_kind": kind_counts,
        "cycle": cycle,
        "topological_order": topo,
    }


# ==========================================================================
# Top-level analysis
# ==========================================================================

def analyze_spec_extraction(document: Any, *, project_root: Optional[Any] = None) -> dict:
    """Validate one spec-intelligence extraction document: its
    `evidence_provenance` declaration (evidence_provenance.py's vocabulary),
    every atomic requirement (requirement_contract.py's schema + status
    re-derivation, plus this module's extraction_id/derivation checks), every
    declared relation (schema + text-similarity re-derivation), the
    dependency graph over REFINES/EXTENDS, and an undeclared-duplicate scan.

    Returns {"schema_version", "status", "reason", "atomic_requirement_count",
    "relation_count", "findings", "dependency_graph"}. `status` is
    NOT_AVAILABLE (nothing to analyze), FAIL (>=1 ERROR finding) or PASS
    (WARNING/INFO findings only)."""
    if not isinstance(document, dict):
        return {
            "schema_version": SCHEMA_VERSION, "status": "NOT_AVAILABLE",
            "reason": f"extraction document must be a JSON object, got {type(document).__name__}",
            "atomic_requirement_count": 0, "relation_count": 0,
            "findings": [], "dependency_graph": None,
        }

    root = Path(project_root) if project_root is not None else Path.cwd()
    findings: List[dict] = list(_check_evidence_provenance(document, root))

    atomic_raw = document.get("atomic_requirements")
    atomic = atomic_raw if isinstance(atomic_raw, list) else []
    relations_raw = document.get("relations")
    relations = relations_raw if isinstance(relations_raw, list) else []

    seen_requirement_ids: Dict[str, int] = {}
    seen_extraction_ids: Dict[str, int] = {}
    valid_records: Dict[str, dict] = {}

    for rec in atomic:
        rec_findings, ok_record = _analyze_one_atomic(rec)
        findings.extend(rec_findings)
        if isinstance(rec, dict):
            rid = rec.get("requirement_id")
            if isinstance(rid, str) and rid:
                seen_requirement_ids[rid] = seen_requirement_ids.get(rid, 0) + 1
            xid = rec.get("extraction_id")
            if isinstance(xid, str) and xid:
                seen_extraction_ids[xid] = seen_extraction_ids.get(xid, 0) + 1
        if ok_record is not None:
            rid = ok_record.get("requirement_id")
            if isinstance(rid, str) and rid and rid not in valid_records:
                valid_records[rid] = ok_record

    for rid, n in seen_requirement_ids.items():
        if n > 1:
            findings.append(_finding(SEVERITY_ERROR, "DUPLICATE_REQUIREMENT_ID", rid,
                                      f"requirement_id {rid!r} appears {n} times"))
    for xid, n in seen_extraction_ids.items():
        if n > 1:
            findings.append(_finding(SEVERITY_ERROR, "DUPLICATE_EXTRACTION_ID", None,
                                      f"extraction_id {xid!r} appears {n} times", extraction_id=xid))

    findings.extend(_analyze_relations(relations, valid_records))

    graph = build_dependency_graph(valid_records, relations)
    if graph["cycle"]:
        findings.append(_finding(
            SEVERITY_ERROR, "RELATION_CYCLE_DETECTED", None,
            "REFINES/EXTENDS relations form a cycle: " + " -> ".join(graph["cycle"]),
            cycle=graph["cycle"]))

    if len(valid_records) <= MAX_DEDUP_SCAN_SIZE:
        findings.extend(_scan_undeclared_duplicates(valid_records, relations))
    else:
        findings.append(_finding(
            SEVERITY_INFO, "DEDUP_SCAN_SKIPPED_TOO_MANY_REQUIREMENTS", None,
            f"{len(valid_records)} valid contract-shaped requirements exceeds {MAX_DEDUP_SCAN_SIZE}; "
            "pairwise undeclared-duplicate scan skipped"))

    errors = [f for f in findings if f["severity"] == SEVERITY_ERROR]
    if not atomic and not relations:
        status, reason = "NOT_AVAILABLE", "no atomic_requirements or relations to analyze"
    elif errors:
        status, reason = "FAIL", None
    else:
        status, reason = "PASS", None

    raw_provenance = document.get(PROVENANCE_FIELD)
    declared_provenance = raw_provenance.strip() if isinstance(raw_provenance, str) else raw_provenance

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "atomic_requirement_count": len(atomic),
        "relation_count": len(relations),
        "findings": findings,
        "dependency_graph": graph,
        PROVENANCE_FIELD: declared_provenance,
        "evidence_provenance_caveat": evidence_caveat_for(declared_provenance),
    }


# --------------------------------------------------------------------------
# CLI (same execute_verb convention as power_intent / golden_scenario /
# requirement_contract; no `dv-harness` verb added here -- see this task's
# structured-output `gates_py_entry_snippet` for the suggested one).
# --------------------------------------------------------------------------

def execute_verb_analyze(extraction_path: str, as_json: bool = False,
                          fail_on_error: bool = False, project_root: Optional[str] = None) -> Tuple[str, int]:
    try:
        document = json.loads(Path(extraction_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = {"status": "NOT_AVAILABLE", "reason": str(exc)}
        return (json.dumps(msg) if as_json else f"NOT_AVAILABLE: {exc}"), 2

    result = analyze_spec_extraction(document, project_root=project_root)
    result["source"] = str(extraction_path)
    if result["status"] == "NOT_AVAILABLE":
        code = 2
    elif result["status"] == "FAIL" or (fail_on_error and result["findings"]):
        code = 1
    else:
        code = 0

    if as_json:
        return json.dumps(result, indent=2), code
    lines = [f"spec-intelligence: {result['status']} "
             f"({result['atomic_requirement_count']} atomic requirement(s), "
             f"{result['relation_count']} relation(s))"]
    if result.get("reason"):
        lines.append(f"  reason: {result['reason']}")
    for f in result["findings"]:
        lines.append(f"  [{f['severity']}] {f['code']} ({f.get('requirement_id')}): {f['detail']}")
    return "\n".join(lines), code


def execute_verb_spec_map(reference_json_path: str, out_dir: str, as_json: bool = False) -> Tuple[str, int]:
    try:
        spec_map = build_spec_map(reference_json_path, out_dir)
    except (UserGuideDistillError, SpecIntelligenceError) as exc:
        msg = {"status": "NOT_AVAILABLE", "reason": str(exc)}
        return (json.dumps(msg) if as_json else f"NOT_AVAILABLE: {exc}"), 2

    if as_json:
        return json.dumps(spec_map, indent=2), 0
    lines = [f"spec-map: built ({spec_map['section_count']} section(s), {spec_map['table_count']} table(s), "
             f"{spec_map['register_chapter_count']} register chapter(s)) -> {spec_map['spec_map_path']}"]
    return "\n".join(lines), 0


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin shell
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.spec_intelligence",
        description="Spec Intelligence: build a SpecMap structure index, or validate an atomic "
                    "requirement extraction/relation/dependency document.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp_map = sub.add_parser("spec-map", help="Build a SpecMap from a vip_user_guide_distill reference record.")
    sp_map.add_argument("--reference", required=True, help="Path to a <stem>.reference.json.")
    sp_map.add_argument("--out", required=True, help="Output directory for <stem>.spec_map.json.")
    sp_map.add_argument("--json", action="store_true")

    sp_analyze = sub.add_parser("analyze", help="Validate an extraction document.")
    sp_analyze.add_argument("--extraction", required=True, help="JSON extraction document.")
    sp_analyze.add_argument("--project-root", default=None)
    sp_analyze.add_argument("--json", action="store_true")
    sp_analyze.add_argument("--fail-on-error", action="store_true")

    a = ap.parse_args(argv)
    if a.cmd == "spec-map":
        text, code = execute_verb_spec_map(a.reference, a.out, as_json=a.json)
    else:
        text, code = execute_verb_analyze(a.extraction, as_json=a.json,
                                           fail_on_error=a.fail_on_error, project_root=a.project_root)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
