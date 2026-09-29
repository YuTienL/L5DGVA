"""dv_harness/phy_model_behavior_ir.py -- PHY ARCHITECTURE facts extracted
from a real PHY specification/model document, never invented from protocol
knowledge, and never mistaken for a claim about a real PHY implementation.

WHAT THIS CLOSES. `phy_boundary.py` already answers a STRUCTURAL question
from real RTL: at which layer (serial vs. parallel) may a bind mount. It
carries no notion of the PHY's own documented behaviour -- what training/
link-startup states the spec names, what the document actually says about
TX/RX capability, what power states it names. Nothing in this repository
read a PHY spec/model document for those facts before this module.

REUSE OVER REINVENT, on both sides of the fact this module adds:

  * The PHY DOCUMENT is never opened here as a raw PDF/text file scan of an
    arbitrary path. `dv_harness/vip_user_guide_distill.py` is this repo's
    ONE offline document distiller (real pypdf extraction, or a pre-
    extracted .txt), and its own docstring already invites exactly this
    reuse for a PHY document via `doc_kind="protocol_spec"` (or
    `"programming_guide"`). This module consumes the `.reference.json`
    record and the `.fulltext.txt` file that distiller already produced --
    there is one document-opening code path in this package, not two, and
    the Context Budget rule ("never loaded into runtime context") stays
    enforced structurally by keeping this module off that one path too.
  * The RTL-derived serial/parallel BOUNDARY is read, not re-derived.
    `dv_harness/phy_boundary.py` (read-only -- this module never edits it)
    already answers "at which layer may a bind mount"; its own JSON output
    is accepted here, verbatim, as the optional `phy_boundary_doc` input and
    validated with its own `validate_phy_boundary()`. This module adds no
    second RTL/port-width classifier.

WHAT COUNTS AS A "FACT" HERE, and why it cannot be a guess. Every item this
module reports is a LITERAL (possibly truncated) line of the real document's
own text, plus a real `document + fulltext_path + line` citation a reader
can open and check. The scan is STRUCTURAL, not semantic: a small, disclosed
set of marker keywords (e.g. "link training", "power state", "transmitter")
decides which document SECTION a line sits in (exactly the same kind of
structural, non-protocol-specific text-shape reasoning `phy_boundary.py`'s
own `_STRONG_CORE_RE`/`_WEAK_CORE_RE` token matching already uses for RTL
port names), and a small set of line-shape patterns (an "ID: description" or
"ID<spaces>description" line, a bulleted/numbered list item) decides which
lines inside that section are candidate facts. Nothing here asserts what a
training stage, a TX capability or a power state IS for any protocol -- it
only locates where the DOCUMENT ITSELF already says so. A document written
with none of these structural conventions is honestly reported
NO_MARKER_SECTION_DETECTED / MARKER_SECTION_FOUND_NO_ITEMS, never guessed.

PHY MODEL BEHAVIOR IS NOT SILICON -- stated once here and carried onto every
document this module produces via the fixed `disclosure` field, EXTRACTED or
NOT_AVAILABLE alike. A digital PHY model and a specification's prose are
architectural DESCRIPTIONS. Neither is a measurement of a real PHY
implementation's analog/electrical behaviour -- timing margins, signal
integrity, jitter, voltage levels, eye diagrams -- and nothing in this
module tests, measures, or claims any of that. It also never claims the
extracted stage/capability/power-state names are complete or authoritative;
it claims only that the cited line, at the cited citation, really exists in
the real document.

ABSENT PHY DOC/MODEL REPORTS NOT_AVAILABLE FOR EVERY FIELD, NEVER A GUESS.
`extract_phy_model_behavior_ir()` called with no document at all returns a
schema-valid document whose top-level `status` and all four fact fields are
NOT_AVAILABLE with a real reason -- it never falls back to inventing a
generic PHY behaviour model.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from dv_harness import phy_boundary, vip_user_guide_distill

SCHEMA_VERSION = "1.0"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "phy_model_behavior_ir.schema.json"

#: Carried verbatim onto every document this module produces.
PHY_NOT_SILICON_DISCLOSURE = (
    "PHY MODEL BEHAVIOR IS NOT SILICON: every fact in this document is extracted from a PHY "
    "specification/model DOCUMENT's own text (training/link-startup stage names, TX/RX "
    "capability statements, power-state names, each with a real document+line citation), or is "
    "a structural port-width classification of real RTL carried in from dv_harness.phy_boundary. "
    "Neither a digital PHY model nor specification prose demonstrates analog/electrical "
    "correctness of a real PHY implementation: timing margins, signal integrity, jitter, voltage "
    "levels, eye diagrams and other electrical behaviour are NOT verified, measured, or claimed "
    "correct by anything in this artifact. This is an architecture-fact navigation index only."
)

_CAT_TRAINING = "training_link_startup_stages"
_CAT_TX = "tx_capabilities"
_CAT_RX = "rx_capabilities"
_CAT_POWER = "power_states"
_NAMED_CATEGORIES = (_CAT_TRAINING, _CAT_POWER)
_TEXT_CATEGORIES = (_CAT_TX, _CAT_RX)

# Structural section markers. These decide which part of the DOCUMENT a line
# sits in; they assert nothing about what any protocol's training flow, TX/RX
# capability, or power state actually IS. Deliberately generic across a PHY
# spec/model document for any protocol (USB, PCIe, MIPI D-PHY, eDP, eMMC,
# SDIO, ...) rather than naming one protocol's own vocabulary, the same
# genericity discipline phy_boundary.py's own control-token regexes apply to
# RTL port names.
_MARKER_PATTERNS = {
    _CAT_TRAINING: re.compile(
        r"\b(link\s*training|link[\s-]*startup|link[\s-]*state|training\s*sequence|"
        r"initialization\s*sequence|start[\s-]*up\s*sequence|lane\s*state)\b", re.IGNORECASE),
    _CAT_TX: re.compile(r"\b(transmitter|tx\s*characteristics|tx\s*capabilit\w*)\b", re.IGNORECASE),
    _CAT_RX: re.compile(r"\b(receiver|rx\s*characteristics|rx\s*capabilit\w*)\b", re.IGNORECASE),
    _CAT_POWER: re.compile(
        r"\b(power\s*state|power\s*management|power\s*mode|low[\s-]*power)\b", re.IGNORECASE),
}

# A heading-like line: either a numbered spec section ("4.3.1 Title", never a
# bare "1." top-level list-item number, which is why at least one dot is
# required) or a short ALL-CAPS line. Deliberately conservative: a false
# negative here just means content is reported under NO_MARKER_SECTION_
# DETECTED instead of being attributed to a section; a false positive would
# wrongly cut a real section's items off, which is the worse failure mode.
_MAX_HEADING_CHARS = 120
_NUMBERED_HEADING_RE = re.compile(r"^\s{0,8}\d+(?:\.\d+){1,5}\.?\s+\S.{0,110}$")
_ALLCAPS_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 /&\-]{3,79}$")

# "ID: description" / "ID - description" / "ID<2+ spaces>description" --
# covers both prose-style and table-row-style PHY state/power-state listings.
_ID_LINE_RE = re.compile(
    r"^[\-\*•●>]?\s*([A-Za-z][A-Za-z0-9_./]{0,29})"
    r"(?:\s*[:–\-]\s+|\s{2,})(\S.*)$")
_BULLET_RE = re.compile(r"^[\-\*•●]\s+(\S.*)$")
_NUMBERED_ITEM_RE = re.compile(r"^\d{1,3}[.)]\s+(\S.*)$")

DEFAULT_MAX_ITEMS_PER_CATEGORY = 25
DEFAULT_MAX_EVIDENCE_CHARS = 240


class PhyModelBehaviorIRValidationError(ValueError):
    """A phy_model_behavior_ir document fails phy_model_behavior_ir.schema.json
    validation. Raised rather than returning None, matching phy_boundary.py's
    /env_manifest.py's fail-closed discipline -- a caller must never persist
    or act on an invalid PHY-behaviour-IR document."""


def validate_phy_model_behavior_ir(doc: dict) -> None:
    """Validate `doc` against phy_model_behavior_ir.schema.json. Raises
    PhyModelBehaviorIRValidationError on any violation."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise PhyModelBehaviorIRValidationError(
            "jsonschema package is not installed; cannot validate against "
            "phy_model_behavior_ir.schema.json. Install it rather than skipping validation."
        ) from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise PhyModelBehaviorIRValidationError(
            "phy_model_behavior_ir.schema.json validation failed:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# structural text scan -- real doc lines + real citations, never a guess
# ---------------------------------------------------------------------------

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


def _list_item_text(stripped: str) -> Optional[str]:
    m = _BULLET_RE.match(stripped)
    if m:
        return m.group(1)
    m = _NUMBERED_ITEM_RE.match(stripped)
    if m:
        return m.group(1)
    return None


def scan_phy_doc_text(full_text: str, *, document_label: str, fulltext_path: str,
                       max_items_per_category: int = DEFAULT_MAX_ITEMS_PER_CATEGORY,
                       max_evidence_chars: int = DEFAULT_MAX_EVIDENCE_CHARS) -> dict:
    """Scan real document text for structurally-recognizable facts. Returns
    `{"marker_seen": {cat: bool}, "items": {cat: [item, ...]}}` for the four
    categories in `_MARKER_PATTERNS`.

    The current section category is reset at EVERY heading-like line (to the
    matching category, or to None on a non-matching heading) -- never left
    "sticky" across an unrelated section, which is what keeps an unrelated
    later section's prose from being misattributed to an earlier category."""
    items = {cat: [] for cat in _MARKER_PATTERNS}
    marker_seen = {cat: False for cat in _MARKER_PATTERNS}
    current_category = None
    for line_no, raw_line in enumerate(full_text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if _is_heading_like(stripped):
            matched = None
            for cat, pattern in _MARKER_PATTERNS.items():
                if pattern.search(stripped):
                    matched = cat
                    break
            current_category = matched
            if matched is not None:
                marker_seen[matched] = True
            continue
        if current_category is None:
            continue
        if len(items[current_category]) >= max_items_per_category:
            continue
        citation = {"document": document_label, "fulltext_path": fulltext_path, "line": line_no}
        if current_category in _NAMED_CATEGORIES:
            m = _ID_LINE_RE.match(stripped)
            if m:
                items[current_category].append({
                    "name": m.group(1),
                    "evidence_text": stripped[:max_evidence_chars],
                    "citation": citation,
                })
        else:
            content = _list_item_text(stripped)
            if content:
                items[current_category].append({
                    "evidence_text": content[:max_evidence_chars],
                    "citation": citation,
                })
    return {"marker_seen": marker_seen, "items": items}


def _field_status(marker_seen: bool, item_count: int) -> tuple:
    if item_count > 0:
        return "FOUND", None
    if marker_seen:
        return ("MARKER_SECTION_FOUND_NO_ITEMS",
                "a heading matching this category's structural markers was found in the document, "
                "but no line inside that section matched this category's recognized item shape "
                "('ID: description' / 'ID  description' for named facts, a bulleted/numbered list "
                "item for capability text)")
    return ("NO_MARKER_SECTION_DETECTED",
            "no heading in the document matched this category's structural marker keywords -- "
            "this is a real observation about the document's structure, not an extraction failure")


# ---------------------------------------------------------------------------
# phy_boundary.py integration -- read-only reuse of its own bind-location output
# ---------------------------------------------------------------------------

def _empty_boundary_context(reason: str) -> dict:
    return {
        "available": False, "reason": reason,
        "phy_module": None, "controller_module": None, "boundary_status": None,
        "classification_kind": None, "mount_layer": None, "bindable": None,
    }


def _boundary_context(phy_boundary_doc: Optional[dict]) -> dict:
    """Reuses dv_harness.phy_boundary's OWN validated output as a read-only
    input; this module derives no serial/parallel classification of its own.
    `available` reflects whether a schema-valid phy_boundary document was
    supplied at all -- NOT whether that document's own internal `status` was
    EXTRACTED. A supplied NOT_AVAILABLE phy_boundary document is carried
    through honestly via `boundary_status`/`classification_kind`, exactly as
    phy_boundary.py itself reported it."""
    if phy_boundary_doc is None:
        return _empty_boundary_context(
            "no phy_boundary.json document was supplied to this extraction -- see "
            "dv_harness.phy_boundary.extract_phy_boundary() / extract_from_env_manifest()"
        )
    try:
        phy_boundary.validate_phy_boundary(phy_boundary_doc)
    except phy_boundary.PhyBoundaryValidationError as exc:
        return _empty_boundary_context(
            f"supplied phy_boundary document failed its own schema validation, so it is not "
            f"trusted here either: {exc}"
        )
    classification = phy_boundary_doc.get("classification") or {}
    bind_decision = phy_boundary_doc.get("bind_decision") or {}
    return {
        "available": True, "reason": None,
        "phy_module": phy_boundary_doc.get("phy_module"),
        "controller_module": phy_boundary_doc.get("controller_module"),
        "boundary_status": phy_boundary_doc.get("status"),
        "classification_kind": classification.get("kind"),
        "mount_layer": bind_decision.get("mount_layer"),
        "bindable": bind_decision.get("bindable"),
    }


# ---------------------------------------------------------------------------
# top-level assembly
# ---------------------------------------------------------------------------

def _empty_field(reason: str) -> dict:
    return {"status": "NOT_AVAILABLE", "reason": reason, "items": []}


def _not_available_doc(reason: str, boundary_context: dict) -> dict:
    field_reason = "no PHY spec/model document was supplied for this extraction"
    doc = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"tool": "dv_harness.phy_model_behavior_ir", "version": SCHEMA_VERSION},
        "status": "NOT_AVAILABLE",
        "reason": reason,
        "disclosure": PHY_NOT_SILICON_DISCLOSURE,
        "source": None,
        "boundary_context": boundary_context,
        _CAT_TRAINING: _empty_field(field_reason),
        _CAT_TX: _empty_field(field_reason),
        _CAT_RX: _empty_field(field_reason),
        _CAT_POWER: _empty_field(field_reason),
    }
    validate_phy_model_behavior_ir(doc)
    return doc


def extract_phy_model_behavior_ir(*, reference_record: Optional[dict] = None,
                                   reference_record_path=None,
                                   phy_boundary_doc: Optional[dict] = None,
                                   max_items_per_category: int = DEFAULT_MAX_ITEMS_PER_CATEGORY,
                                   max_evidence_chars: int = DEFAULT_MAX_EVIDENCE_CHARS) -> dict:
    """Build a complete, schema-valid phy_model_behavior_ir.json dict.

    `reference_record` / `reference_record_path`: a `.reference.json` record
    (or its path) produced by `vip_user_guide_distill.distill_user_guide()`
    for a REAL PHY specification/model document (pass `doc_kind=
    "protocol_spec"` or `"programming_guide"` when distilling it). Neither
    supplied -> NOT_AVAILABLE for every field, never a guess.

    `phy_boundary_doc`: an OPTIONAL real `phy_boundary.json`-shaped dict
    (dv_harness.phy_boundary's own output), merged in read-only as
    `boundary_context`. phy_boundary.py is read here, never edited and never
    re-implemented -- this module derives no RTL/port-width facts of its
    own."""
    boundary_context = _boundary_context(phy_boundary_doc)

    if reference_record is None and reference_record_path is None:
        return _not_available_doc(
            "no PHY spec/model document was supplied -- distil the real PHY document first with "
            "dv_harness.vip_user_guide_distill.distill_user_guide(source, out_dir, "
            "doc_kind='protocol_spec') and pass its .reference.json record (or path) here",
            boundary_context,
        )

    if reference_record is None:
        try:
            record = vip_user_guide_distill.load_reference_record(reference_record_path)
        except vip_user_guide_distill.UserGuideDistillError as exc:
            return _not_available_doc(
                f"could not load the PHY doc reference record at {reference_record_path!r}: {exc}",
                boundary_context,
            )
    else:
        record = reference_record
        missing = [k for k in ("schema_version", "doc_kind", "title", "source_document",
                                "full_text_extract") if k not in record]
        if missing:
            return _not_available_doc(
                f"supplied reference_record is not a vip_user_guide_distill reference record -- "
                f"missing {missing} -- produce one with distill_user_guide() rather than passing "
                "an arbitrary dict",
                boundary_context,
            )

    fulltext_path = Path(record["full_text_extract"]["path"])
    if not fulltext_path.is_file():
        return _not_available_doc(
            f"the PHY doc's full-text extract is missing on disk: {fulltext_path} -- re-run "
            "dv_harness.vip_user_guide_distill.distill_user_guide() against the real source "
            "document",
            boundary_context,
        )
    full_text = fulltext_path.read_text(encoding="utf-8", errors="replace")
    recomputed_sha256 = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    recorded_sha256 = (record.get("full_text_extract") or {}).get("sha256")
    fulltext_verified = (recomputed_sha256 == recorded_sha256) if recorded_sha256 else None

    document_label = record.get("title") or str(fulltext_path)
    scan = scan_phy_doc_text(
        full_text, document_label=document_label, fulltext_path=str(fulltext_path),
        max_items_per_category=max_items_per_category, max_evidence_chars=max_evidence_chars,
    )

    def _field(cat: str) -> dict:
        status, reason = _field_status(scan["marker_seen"][cat], len(scan["items"][cat]))
        return {"status": status, "reason": reason, "items": scan["items"][cat]}

    doc = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"tool": "dv_harness.phy_model_behavior_ir", "version": SCHEMA_VERSION},
        "status": "EXTRACTED",
        "reason": None,
        "disclosure": PHY_NOT_SILICON_DISCLOSURE,
        "source": {
            "doc_kind": record.get("doc_kind"),
            "title": record.get("title"),
            "reference_record_path": str(reference_record_path) if reference_record_path else None,
            "source_document": record.get("source_document"),
            "fulltext_path": str(fulltext_path),
            "fulltext_sha256_verified": fulltext_verified,
        },
        "boundary_context": boundary_context,
        _CAT_TRAINING: _field(_CAT_TRAINING),
        _CAT_TX: _field(_CAT_TX),
        _CAT_RX: _field(_CAT_RX),
        _CAT_POWER: _field(_CAT_POWER),
    }
    validate_phy_model_behavior_ir(doc)
    return doc


def save_phy_model_behavior_ir(doc: dict, path) -> None:
    """Validate then write deterministically (fixed key order, no timestamp
    field anywhere in the schema), matching phy_boundary.save_phy_boundary()'s
    Diffability contract: regenerating from an unchanged real document
    produces a byte-identical file."""
    validate_phy_model_behavior_ir(doc)
    Path(path).write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_phy_model_behavior_ir(path) -> dict:
    """Load and validate a phy_model_behavior_ir.json from disk. Raises
    PhyModelBehaviorIRValidationError if it is not schema-valid."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_phy_model_behavior_ir(doc)
    return doc
