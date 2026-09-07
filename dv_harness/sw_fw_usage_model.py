"""dv_harness/sw_fw_usage_model.py -- documented SW/FW USAGE-SEQUENCE facts
extracted from a real programming guide, never invented from protocol
knowledge, and shaped directly into `programming_sequence_ir.py`'s own
phase/step vocabulary rather than a second, parallel one.

WHAT THIS CLOSES. `programming_sequence_ir.py` already models the target
SHAPE this project uses for a bring-up/programming sequence: a canonical
PHASE vocabulary (`INIT -> CONFIGURE -> ENABLE -> {RUN/WAIT/VERIFY/DISABLE}
-> RESET`) and a step ACTION vocabulary (`write`/`read`/`wait`), plus a real
ordering/dependency validator over that shape. Nothing in this repository
ever produced one of those documents FROM a real document -- every existing
`ProgrammingSequenceIR` in this codebase (and every one of its own tests) is
hand-authored. A repo-wide grep for `sw_fw_usage_model`/`usage_model`/
"usage-sequence" before this module found nothing. This module is that
missing extractor: it reads a real programming guide's own documented
"do this, then this, then this" procedure text and reports each step's
phase/action/register as an evidence-cited fact, targeted directly at
`programming_sequence_ir.py`'s own shape so the two compose with zero
translation code.

REUSE OVER REINVENT, on both sides of the fact this module adds.

  * The PROGRAMMING GUIDE is never opened here as a raw PDF/text scan of an
    arbitrary path. `dv_harness/vip_user_guide_distill.py` is this repo's
    ONE offline document distiller (real `pypdf` extraction, or a pre-
    extracted `.txt`), and its own `doc_kind` parameter already names
    `"programming_guide"` as a first-class document kind it distils. This
    module consumes the `.reference.json` record and the `.fulltext.txt`
    file that distiller already produced -- there is one document-opening
    code path in this package, not two, and the Context Budget rule
    ("never loaded into runtime context") stays enforced structurally by
    keeping this module off that one path too, exactly as
    `phy_model_behavior_ir.py` (the module this one's shape most closely
    mirrors) already does for a PHY spec/model document.
  * The TARGET SHAPE -- what counts as a phase, what counts as an action --
    is `programming_sequence_ir.py`'s own `PHASE_INIT`/`PHASE_CONFIGURE`/
    `PHASE_ENABLE`/`PHASE_RUN`/`PHASE_WAIT`/`PHASE_VERIFY`/`PHASE_DISABLE`/
    `PHASE_RESET`/`CANONICAL_PHASES` and `ACTION_WRITE`/`ACTION_READ`/
    `ACTION_WAIT`/`STEP_ACTIONS`, imported and used verbatim -- never
    re-typed as a second, drifting vocabulary. A classified step is not
    merely LABELED with one of those tokens; `to_programming_sequence_
    document()`/`build_candidate_programming_sequence_ir()` package a
    sequence's classified steps into the EXACT dict shape
    `programming_sequence_ir.programming_sequence_ir_from_dict()` already
    accepts, and call that real function -- so a caller can hand the
    result straight to `programming_sequence_ir.validate_step_ordering()`
    (with real register facts, once it has them) with no adapter code
    anywhere in between.

WHAT COUNTS AS A "FACT" HERE, and why it cannot be a guess. A candidate
USAGE SEQUENCE is a real, consecutively-numbered ("1. ... 2. ... 3. ...", or
"Step 1: ... Step 2: ...") list of >=2 items found in the document's own
text -- never invented, and never collapsed across an unrelated later list
that happens to restart at "1." (a numbering restart, or a break in strict
ascending order, always starts a NEW candidate sequence). Every step's
PHASE and ACTION classification comes from a small, fixed, literal keyword-
phrase match against that step's own text (word-boundary regex, the same
"structural, not semantic" discipline `arbitration_policy_ir.py`'s
`classify_arbitration_scheme()` and `backpressure_model.py`'s tolerance
classifier already apply to their own domains -- independently re-derived
here, not imported, since neither is a text-structure-scanning module this
one should couple to): a step whose text carries no recognizable phase/
action phrase is honestly UNCLASSIFIED, not defaulted to the "most common"
phase; a step whose text carries phrases for TWO DIFFERENT phases (or, for
action, both a write-shaped and a read-shaped phrase with no wait) is
honestly AMBIGUOUS, naming every phrase it matched, never silently resolved
by picking one. A step's own text is tried first for phase classification;
only when it is UNCLASSIFIED (never when it is AMBIGUOUS -- a real
ambiguity is never quietly resolved by weaker evidence) does the enclosing
section HEADING'S own classification supply a fallback, recorded with a
distinct `evidence_source` so a reader can always tell a step's own words
from a heading's. A register name is extracted only when the step's text
carries a real register-shaped token (`REG.FIELD`, or a bare
`ALL_CAPS_WITH_UNDERSCORE` identifier) -- absent one, `register_status` is
honestly `UNRESOLVED`, never a fabricated name. A step's specific bit/value
operand is never extracted at all (`value` is always `None` on the composed
`programming_sequence_ir` document) -- inferring a numeric value from prose
with no fixed, checkable shape would be exactly the kind of confident guess
the Evidence Truth Rule forbids.

SW/FW USAGE FACTS ARE DOCUMENTED, NOT VERIFIED -- stated once here and
carried onto every document this module produces via the fixed
`disclosure` field, EXTRACTED or NOT_AVAILABLE alike. A programming guide's
own prose is a description of what software/firmware is SUPPOSED to do; it
is not RTL, not a simulation, and nothing in this module checks the
sequence against either. Cross-checking a classified sequence's real
register-access legality/dependency ordering against real register facts
is exactly what `programming_sequence_ir.validate_step_ordering()` already
does -- this module produces the candidate document that function consumes,
it does not itself run that check.

ABSENT PROGRAMMING GUIDE REPORTS NOT_AVAILABLE, NEVER A GUESS.
`extract_sw_fw_usage_model()` called with no document at all returns a
document whose top-level `status` is NOT_AVAILABLE with a real reason and
an empty `sequences` list -- it never falls back to inventing a generic
bring-up sequence for a protocol it recognizes by name.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from dv_harness import programming_sequence_ir, vip_user_guide_distill

SCHEMA_VERSION = "1.0"

#: Carried verbatim onto every document this module produces.
SW_FW_USAGE_NOT_VERIFIED_DISCLOSURE = (
    "SW/FW USAGE FACTS ARE DOCUMENTED, NOT VERIFIED: every step in this document is extracted "
    "from a programming guide's own numbered-procedure text (a real document+line citation on "
    "every step), classified against dv_harness.programming_sequence_ir's own phase/action "
    "vocabulary from literal keyword evidence in that step's own text. An UNCLASSIFIED or "
    "AMBIGUOUS phase/action is an honest classification gap, never resolved by this module. "
    "This is a description of what a document SAYS software/firmware should do -- it is not RTL, "
    "not a simulation, and nothing here checks the sequence's real register-access legality or "
    "dependency ordering. Feed the composed candidate document to "
    "dv_harness.programming_sequence_ir.validate_step_ordering() against real register facts "
    "before treating a sequence as verified."
)

# ---------------------------------------------------------------------------
# classification vocabularies -- honest gap statuses, never a silent default
# ---------------------------------------------------------------------------

STATUS_CLASSIFIED = "CLASSIFIED"
STATUS_CLASSIFIED_FROM_HEADING = "CLASSIFIED_FROM_HEADING"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_UNCLASSIFIED = "UNCLASSIFIED"

REGISTER_STATUS_RESOLVED = "RESOLVED"
REGISTER_STATUS_RESOLVED_WITH_FIELD = "RESOLVED_WITH_FIELD"
REGISTER_STATUS_UNRESOLVED = "UNRESOLVED"

EXCLUDE_PHASE_NOT_RESOLVED = "PHASE_NOT_RESOLVED"
EXCLUDE_ACTION_NOT_RESOLVED = "ACTION_NOT_RESOLVED"
EXCLUDE_REGISTER_UNRESOLVED = "REGISTER_UNRESOLVED_FOR_NON_WAIT_ACTION"

# ---------------------------------------------------------------------------
# structural text-shape regexes -- independently derived, matching (not
# importing) phy_model_behavior_ir.py's own heading-detection convention;
# this module is a text-structure scanner in its own right, not a consumer
# of that unrelated PHY-domain module's private helpers.
# ---------------------------------------------------------------------------

_MAX_HEADING_CHARS = 120
# A real spec/section heading ("4.3.1 Reset Sequence") always carries a dot
# in its number -- deliberately distinct from a bare "1. Item text" list
# entry, which is exactly the shape this module is hunting for as a STEP,
# never as a heading.
_NUMBERED_HEADING_RE = re.compile(r"^\s{0,8}\d+(?:\.\d+){1,5}\.?\s+\S.{0,110}$")
_ALLCAPS_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 /&\-]{3,79}$")

_NUMBERED_ITEM_RE = re.compile(r"^\s{0,4}(\d{1,3})[.)]\s+(\S.*)$")
_STEP_ITEM_RE = re.compile(r"^\s{0,4}[Ss]tep\s+(\d{1,3})\s*[:.)]\s*(\S.*)$")

DEFAULT_MIN_SEQUENCE_LENGTH = 2
DEFAULT_MAX_SEQUENCES = 50
DEFAULT_MAX_STEPS_PER_SEQUENCE = 60
DEFAULT_MAX_EVIDENCE_CHARS = 240


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


# ---------------------------------------------------------------------------
# phase/action/register classification -- literal keyword evidence only
# ---------------------------------------------------------------------------

# Phase keyword phrases, keyed on programming_sequence_ir.py's own phase
# tokens -- imported, never re-typed. Order matches CANONICAL_PHASES so a
# rendered report always lists phases in that same canonical order.
_PHASE_KEYWORD_PATTERNS = {
    programming_sequence_ir.PHASE_INIT: re.compile(
        r"\b(initializ\w*|power[- ]?on reset|cold[- ]?boot|start[- ]?up sequence)\b", re.IGNORECASE),
    programming_sequence_ir.PHASE_CONFIGURE: re.compile(
        r"\b(configur\w*|program the|set up|setup the)\b", re.IGNORECASE),
    programming_sequence_ir.PHASE_ENABLE: re.compile(
        r"\b(enable\w*|assert\w* the enable|turn on)\b", re.IGNORECASE),
    programming_sequence_ir.PHASE_RUN: re.compile(
        r"\b(start\w* the (transfer|operation)|begin\w* (operation|the transfer)|trigger\w*|"
        r"kick[- ]?off|issue\w* the (command|request|transaction))\b", re.IGNORECASE),
    programming_sequence_ir.PHASE_WAIT: re.compile(
        r"\b(wait\w* (for|until)|poll\w* until|delay\w* (for|until))\b", re.IGNORECASE),
    programming_sequence_ir.PHASE_VERIFY: re.compile(
        r"\b(verify\w*|confirm\w* that|read[- ]?back|check\w* that)\b", re.IGNORECASE),
    programming_sequence_ir.PHASE_DISABLE: re.compile(
        r"\b(disable\w*|deassert\w*|turn off|stop\w* the)\b", re.IGNORECASE),
    programming_sequence_ir.PHASE_RESET: re.compile(
        r"\b(reset\w*|soft[- ]?reset|clear\w* the device)\b", re.IGNORECASE),
}

# Action classification is deliberately priority-based rather than
# ambiguity-based between WAIT and the other two: a step whose text says
# "wait"/"poll until" is, by programming_sequence_ir.py's own vocabulary, a
# pure delay/poll-until-condition step (its `wait` action carries no
# register) regardless of what else the sentence mentions. Between WRITE
# and READ, though, a step matching BOTH with no wait phrase genuinely
# describes two different register accesses this module's one-action-per-
# step shape cannot represent honestly -- that case is reported AMBIGUOUS,
# never silently resolved toward one of the two.
_ACTION_WAIT_PATTERN = re.compile(
    r"\b(wait\w* (for|until)|poll\w* until|delay\w* (for|until)|until the)\b", re.IGNORECASE)
_ACTION_WRITE_PATTERN = re.compile(
    r"\b(writ\w*|set\w* the|program\w*|assert\w*|clear\w* the|configur\w*|enable\w*|disable\w*)\b",
    re.IGNORECASE)
_ACTION_READ_PATTERN = re.compile(
    r"\b(read\w*|check\w* the|verify\w* that|confirm\w* that|inspect\w*)\b", re.IGNORECASE)

# Register-name-shaped tokens only -- a bare word with no underscore
# segment is never treated as a plausible register name (too high a false-
# positive rate against ordinary prose); this is a disclosed, narrow
# heuristic, not a claim that every real register name follows this shape.
_REGISTER_DOTTED_RE = re.compile(r"\b([A-Z][A-Z0-9_]{1,31})\.([A-Za-z_][A-Za-z0-9_]{0,31})\b")
_REGISTER_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+){1,5})\b")


def classify_phase(text: str) -> dict:
    """Classify `text` against `programming_sequence_ir.py`'s own phase
    vocabulary from literal keyword evidence. Returns
    `{"phase", "status", "evidence": [...], "matched_phases": [...]}`.
    `status` is CLASSIFIED / AMBIGUOUS / UNCLASSIFIED; `phase` is None
    unless `status == CLASSIFIED`."""
    matches = []
    for phase, pattern in _PHASE_KEYWORD_PATTERNS.items():
        m = pattern.search(text)
        if m:
            matches.append((phase, m.group(0)))
    if not matches:
        return {"phase": None, "status": STATUS_UNCLASSIFIED, "evidence": [], "matched_phases": []}
    distinct_phases = sorted({p for p, _ in matches}, key=programming_sequence_ir.CANONICAL_PHASES.index)
    evidence = [kw for _, kw in matches]
    if len(distinct_phases) > 1:
        return {"phase": None, "status": STATUS_AMBIGUOUS, "evidence": evidence,
                "matched_phases": distinct_phases}
    return {"phase": distinct_phases[0], "status": STATUS_CLASSIFIED, "evidence": evidence,
            "matched_phases": distinct_phases}


def classify_phase_with_heading_fallback(step_text: str, heading_text: Optional[str]) -> dict:
    """`classify_phase()` over `step_text`; when that is honestly
    UNCLASSIFIED (never when it is AMBIGUOUS -- a real ambiguity is never
    quietly resolved by weaker evidence), falls back to classifying the
    enclosing section HEADING's own text, tagged
    `STATUS_CLASSIFIED_FROM_HEADING` and carrying `evidence_source` so a
    reader can always tell a step's own words from a heading's."""
    result = classify_phase(step_text)
    result["evidence_source"] = "step_text" if result["status"] != STATUS_UNCLASSIFIED else None
    if result["status"] != STATUS_UNCLASSIFIED or not heading_text:
        return result
    heading_result = classify_phase(heading_text)
    if heading_result["status"] == STATUS_CLASSIFIED:
        heading_result["status"] = STATUS_CLASSIFIED_FROM_HEADING
        heading_result["evidence_source"] = "heading"
        return heading_result
    result["evidence_source"] = None
    return result


def classify_action(text: str) -> dict:
    """Classify `text` against `programming_sequence_ir.py`'s own action
    vocabulary (`ACTION_WAIT`/`ACTION_WRITE`/`ACTION_READ`). Returns
    `{"action", "status", "evidence": [...]}`."""
    wait_m = _ACTION_WAIT_PATTERN.search(text)
    if wait_m:
        return {"action": programming_sequence_ir.ACTION_WAIT, "status": STATUS_CLASSIFIED,
                "evidence": [wait_m.group(0)]}
    write_m = _ACTION_WRITE_PATTERN.search(text)
    read_m = _ACTION_READ_PATTERN.search(text)
    if write_m and read_m:
        return {"action": None, "status": STATUS_AMBIGUOUS,
                "evidence": [write_m.group(0), read_m.group(0)]}
    if write_m:
        return {"action": programming_sequence_ir.ACTION_WRITE, "status": STATUS_CLASSIFIED,
                "evidence": [write_m.group(0)]}
    if read_m:
        return {"action": programming_sequence_ir.ACTION_READ, "status": STATUS_CLASSIFIED,
                "evidence": [read_m.group(0)]}
    return {"action": None, "status": STATUS_UNCLASSIFIED, "evidence": []}


def extract_register(text: str) -> dict:
    """Extract a register-name-shaped token from `text`, if one is really
    present. Returns `{"register", "field", "status", "evidence"}`; absent a
    real match, `status` is honestly REGISTER_STATUS_UNRESOLVED rather than
    a fabricated name."""
    m = _REGISTER_DOTTED_RE.search(text)
    if m:
        return {"register": m.group(1), "field": m.group(2),
                "status": REGISTER_STATUS_RESOLVED_WITH_FIELD, "evidence": m.group(0)}
    m = _REGISTER_TOKEN_RE.search(text)
    if m:
        return {"register": m.group(1), "field": None,
                "status": REGISTER_STATUS_RESOLVED, "evidence": m.group(0)}
    return {"register": None, "field": None, "status": REGISTER_STATUS_UNRESOLVED, "evidence": None}


# ---------------------------------------------------------------------------
# structural scan: real consecutively-numbered candidate sequences only
# ---------------------------------------------------------------------------

def scan_usage_sequences(full_text: str, *, document_label: str, fulltext_path: str,
                          min_sequence_length: int = DEFAULT_MIN_SEQUENCE_LENGTH,
                          max_sequences: int = DEFAULT_MAX_SEQUENCES,
                          max_steps_per_sequence: int = DEFAULT_MAX_STEPS_PER_SEQUENCE) -> list:
    """Scan real document text for consecutively-numbered candidate usage
    sequences. Returns a list of
    `{"heading", "heading_citation", "items": [{"number","text","line"}]}`
    groups with at least `min_sequence_length` items, in document order.

    A group breaks (and a fresh one may start) at every heading-like line,
    and whenever a numbered item's own number is not exactly the previous
    item's number plus one -- including a numbering RESTART at "1." after a
    prior list, which is exactly the shape of two separate real procedures
    sitting one after another in the document. Blank lines never break a
    group. This is a structural, non-semantic scan: it never asks whether a
    numbered list is really a SW/FW usage procedure versus, say, an
    unrelated feature list -- that risk is bounded downstream, because an
    unrelated list's own steps will honestly classify UNCLASSIFIED and are
    excluded when composing a `programming_sequence_ir` document."""
    groups: list = []
    current_group: Optional[dict] = None
    current_heading: Optional[str] = None
    current_heading_citation: Optional[dict] = None
    prev_number: Optional[int] = None

    def flush() -> None:
        nonlocal current_group, prev_number
        if current_group is not None and current_group["items"]:
            groups.append(current_group)
        current_group = None
        prev_number = None

    for line_no, raw_line in enumerate(full_text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if _is_heading_like(stripped):
            flush()
            current_heading = stripped
            current_heading_citation = {
                "document": document_label, "fulltext_path": fulltext_path, "line": line_no}
            continue
        m = _NUMBERED_ITEM_RE.match(stripped) or _STEP_ITEM_RE.match(stripped)
        if m is None:
            flush()
            continue
        number = int(m.group(1))
        text = m.group(2)
        if not (current_group is not None and prev_number is not None and number == prev_number + 1):
            flush()
            current_group = {
                "heading": current_heading, "heading_citation": current_heading_citation, "items": []}
        if len(current_group["items"]) < max_steps_per_sequence:
            citation = {"document": document_label, "fulltext_path": fulltext_path, "line": line_no}
            current_group["items"].append(
                {"number": number, "text": text, "line": line_no, "citation": citation})
        prev_number = number
    flush()

    groups = [g for g in groups if len(g["items"]) >= min_sequence_length]
    return groups[:max_sequences]


# ---------------------------------------------------------------------------
# fact records
# ---------------------------------------------------------------------------

@dataclass
class SwFwUsageStepFact:
    position: int
    raw_text: str
    citation: dict
    phase: Optional[str]
    phase_status: str
    phase_evidence: List[str]
    action: Optional[str]
    action_status: str
    action_evidence: List[str]
    register: Optional[str]
    register_field: Optional[str]
    register_status: str

    def to_dict(self) -> dict:
        return {
            "position": self.position, "raw_text": self.raw_text, "citation": self.citation,
            "phase": self.phase, "phase_status": self.phase_status, "phase_evidence": self.phase_evidence,
            "action": self.action, "action_status": self.action_status,
            "action_evidence": self.action_evidence,
            "register": self.register, "register_field": self.register_field,
            "register_status": self.register_status,
        }


@dataclass
class SwFwUsageSequenceFact:
    sequence_id: str
    name: Optional[str]
    name_citation: Optional[dict]
    steps: List[SwFwUsageStepFact] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sequence_id": self.sequence_id, "name": self.name, "name_citation": self.name_citation,
            "step_count": len(self.steps), "steps": [s.to_dict() for s in self.steps],
        }


def _build_step_fact(position: int, item: dict, heading: Optional[str], *,
                      max_evidence_chars: int) -> SwFwUsageStepFact:
    text = item["text"]
    citation = item["citation"]
    phase_result = classify_phase_with_heading_fallback(text, heading)
    action_result = classify_action(text)
    register_result = extract_register(text)
    return SwFwUsageStepFact(
        position=position, raw_text=text[:max_evidence_chars], citation=citation,
        phase=phase_result["phase"], phase_status=phase_result["status"],
        phase_evidence=phase_result["evidence"],
        action=action_result["action"], action_status=action_result["status"],
        action_evidence=action_result["evidence"],
        register=register_result["register"], register_field=register_result["field"],
        register_status=register_result["status"],
    )


# ---------------------------------------------------------------------------
# top-level assembly
# ---------------------------------------------------------------------------

class SwFwUsageExtractionResult:
    """The raw, in-process result of a real extraction: real
    `SwFwUsageSequenceFact` objects (never dict-serialized), plus enough of
    the surrounding context (`status`/`reason`/`source`) to render a
    sw_fw_usage_model.json document from them. `extract_sw_fw_usage_model()`
    is a thin JSON-dict wrapper around this; `to_programming_sequence_
    document()`/`build_candidate_programming_sequence_ir()` consume the real
    `sequences` here directly rather than round-tripping through JSON."""

    def __init__(self, *, status: str, reason: Optional[str], source: Optional[dict],
                 sequences: List[SwFwUsageSequenceFact]):
        self.status = status
        self.reason = reason
        self.source = source
        self.sequences = sequences

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "generator": {"tool": "dv_harness.sw_fw_usage_model", "version": SCHEMA_VERSION},
            "status": self.status,
            "reason": self.reason,
            "disclosure": SW_FW_USAGE_NOT_VERIFIED_DISCLOSURE,
            "source": self.source,
            "sequences": [s.to_dict() for s in self.sequences],
            "sequence_count": len(self.sequences),
            "step_phase_vocabulary": list(programming_sequence_ir.CANONICAL_PHASES),
            "step_action_vocabulary": list(programming_sequence_ir.STEP_ACTIONS),
        }


def build_sw_fw_usage_sequences(*, reference_record: Optional[dict] = None,
                                 reference_record_path=None,
                                 min_sequence_length: int = DEFAULT_MIN_SEQUENCE_LENGTH,
                                 max_sequences: int = DEFAULT_MAX_SEQUENCES,
                                 max_steps_per_sequence: int = DEFAULT_MAX_STEPS_PER_SEQUENCE,
                                 max_evidence_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
                                 ) -> SwFwUsageExtractionResult:
    """The real extraction, returning real `SwFwUsageSequenceFact` objects
    (never a JSON-serialized dict) -- the entry point for an in-process
    caller that wants to compose the result straight into
    `programming_sequence_ir.py`'s own shape, e.g. via
    `to_programming_sequence_document()`.

    `reference_record` / `reference_record_path`: a `.reference.json` record
    (or its path) produced by
    `vip_user_guide_distill.distill_user_guide(..., doc_kind=
    "programming_guide")` for a REAL programming guide. Neither supplied ->
    NOT_AVAILABLE, never a guess."""
    if reference_record is None and reference_record_path is None:
        return SwFwUsageExtractionResult(
            status="NOT_AVAILABLE",
            reason=("no programming guide document was supplied -- distil the real programming "
                    "guide first with dv_harness.vip_user_guide_distill.distill_user_guide("
                    "source, out_dir, doc_kind='programming_guide') and pass its .reference.json "
                    "record (or path) here"),
            source=None, sequences=[])

    if reference_record is None:
        try:
            record = vip_user_guide_distill.load_reference_record(reference_record_path)
        except vip_user_guide_distill.UserGuideDistillError as exc:
            return SwFwUsageExtractionResult(
                status="NOT_AVAILABLE",
                reason=(f"could not load the programming guide reference record at "
                        f"{reference_record_path!r}: {exc}"),
                source=None, sequences=[])
    else:
        record = reference_record
        missing = [k for k in ("schema_version", "doc_kind", "title", "source_document",
                                "full_text_extract") if k not in record]
        if missing:
            return SwFwUsageExtractionResult(
                status="NOT_AVAILABLE",
                reason=(f"supplied reference_record is not a vip_user_guide_distill reference "
                        f"record -- missing {missing} -- produce one with distill_user_guide() "
                        "rather than passing an arbitrary dict"),
                source=None, sequences=[])

    fulltext_path = Path(record["full_text_extract"]["path"])
    if not fulltext_path.is_file():
        return SwFwUsageExtractionResult(
            status="NOT_AVAILABLE",
            reason=(f"the programming guide's full-text extract is missing on disk: "
                    f"{fulltext_path} -- re-run "
                    "dv_harness.vip_user_guide_distill.distill_user_guide() against the real "
                    "source document"),
            source=None, sequences=[])

    full_text = fulltext_path.read_text(encoding="utf-8", errors="replace")
    recomputed_sha256 = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    recorded_sha256 = (record.get("full_text_extract") or {}).get("sha256")
    fulltext_verified = (recomputed_sha256 == recorded_sha256) if recorded_sha256 else None

    document_label = record.get("title") or str(fulltext_path)
    groups = scan_usage_sequences(
        full_text, document_label=document_label, fulltext_path=str(fulltext_path),
        min_sequence_length=min_sequence_length, max_sequences=max_sequences,
        max_steps_per_sequence=max_steps_per_sequence,
    )

    sequences: List[SwFwUsageSequenceFact] = []
    for i, group in enumerate(groups, start=1):
        steps = [
            _build_step_fact(pos, item, group["heading"], max_evidence_chars=max_evidence_chars)
            for pos, item in enumerate(group["items"], start=1)
        ]
        sequences.append(SwFwUsageSequenceFact(
            sequence_id=f"SEQ_{i}", name=group["heading"], name_citation=group["heading_citation"],
            steps=steps,
        ))

    source = {
        "doc_kind": record.get("doc_kind"),
        "title": record.get("title"),
        "reference_record_path": str(reference_record_path) if reference_record_path else None,
        "source_document": record.get("source_document"),
        "fulltext_path": str(fulltext_path),
        "fulltext_sha256_verified": fulltext_verified,
    }
    return SwFwUsageExtractionResult(status="EXTRACTED", reason=None, source=source,
                                     sequences=sequences)


def extract_sw_fw_usage_model(*, reference_record: Optional[dict] = None,
                               reference_record_path=None,
                               min_sequence_length: int = DEFAULT_MIN_SEQUENCE_LENGTH,
                               max_sequences: int = DEFAULT_MAX_SEQUENCES,
                               max_steps_per_sequence: int = DEFAULT_MAX_STEPS_PER_SEQUENCE,
                               max_evidence_chars: int = DEFAULT_MAX_EVIDENCE_CHARS) -> dict:
    """Build a complete, JSON-serializable sw_fw_usage_model.json-shaped
    dict -- a thin wrapper over `build_sw_fw_usage_sequences()` for a caller
    that wants the plain-dict artifact rather than the real fact objects."""
    result = build_sw_fw_usage_sequences(
        reference_record=reference_record, reference_record_path=reference_record_path,
        min_sequence_length=min_sequence_length, max_sequences=max_sequences,
        max_steps_per_sequence=max_steps_per_sequence, max_evidence_chars=max_evidence_chars,
    )
    return result.to_dict()


# ---------------------------------------------------------------------------
# composition into programming_sequence_ir.py's own real shape
# ---------------------------------------------------------------------------

def to_programming_sequence_document(sequence: SwFwUsageSequenceFact, *, name: Optional[str] = None):
    """Compose `sequence`'s CLASSIFIED steps into the exact dict shape
    `programming_sequence_ir.programming_sequence_ir_from_dict()` accepts:
    `{"name", "steps": [{"index","phase","action","register","value",
    "description"}, ...]}`.

    A step is included ONLY when its phase is resolved (CLASSIFIED or
    CLASSIFIED_FROM_HEADING), its action is resolved (CLASSIFIED), and --
    for a non-`wait` action -- its register is resolved (RESOLVED or
    RESOLVED_WITH_FIELD). Every excluded step is reported (with its own
    original `position`/`reason`/`raw_text`/`citation`), never silently
    dropped, in the second return value. Included steps are re-indexed
    0..k-1 among themselves (`programming_sequence_ir_from_dict()` requires
    contiguous ascending indices); each included step's ORIGINAL document
    citation is preserved in its own `description` field for traceability.
    `value` (the step's specific bit/operand) is never extracted and is
    always `None` on every included step.

    Returns `(doc_dict, excluded_steps)`."""
    included = []
    excluded = []
    for step in sequence.steps:
        if step.phase_status not in (STATUS_CLASSIFIED, STATUS_CLASSIFIED_FROM_HEADING):
            excluded.append({"position": step.position, "reason": EXCLUDE_PHASE_NOT_RESOLVED,
                              "raw_text": step.raw_text, "citation": step.citation})
            continue
        if step.action_status != STATUS_CLASSIFIED:
            excluded.append({"position": step.position, "reason": EXCLUDE_ACTION_NOT_RESOLVED,
                              "raw_text": step.raw_text, "citation": step.citation})
            continue
        if step.action != programming_sequence_ir.ACTION_WAIT and step.register_status not in (
                REGISTER_STATUS_RESOLVED, REGISTER_STATUS_RESOLVED_WITH_FIELD):
            excluded.append({"position": step.position, "reason": EXCLUDE_REGISTER_UNRESOLVED,
                              "raw_text": step.raw_text, "citation": step.citation})
            continue
        included.append(step)

    steps_out = []
    for idx, step in enumerate(included):
        register = None if step.action == programming_sequence_ir.ACTION_WAIT else step.register
        steps_out.append({
            "index": idx, "phase": step.phase, "action": step.action, "register": register,
            "value": None,
            "description": (
                f"[source: {step.citation.get('document')} line {step.citation.get('line')}] "
                f"{step.raw_text}"),
        })

    doc = {"name": name or sequence.name or sequence.sequence_id, "steps": steps_out}
    return doc, excluded


def build_candidate_programming_sequence_ir(sequence: SwFwUsageSequenceFact, *,
                                             name: Optional[str] = None):
    """`to_programming_sequence_document()`, then a real call into
    `programming_sequence_ir.programming_sequence_ir_from_dict()` -- proving
    this module's output really is `programming_sequence_ir.py`'s own
    consumable shape, not merely a lookalike. Returns
    `(ProgrammingSequenceIR, excluded_steps)`. Raises
    `programming_sequence_ir.ProgrammingSequenceIRError` on a document that
    (despite the inclusion filter above) is somehow still malformed --
    never silently coerced."""
    doc, excluded = to_programming_sequence_document(sequence, name=name)
    ir = programming_sequence_ir.programming_sequence_ir_from_dict(doc)
    return ir, excluded


# ---------------------------------------------------------------------------
# save/load
# ---------------------------------------------------------------------------

def save_sw_fw_usage_model(doc: dict, path) -> None:
    """Write deterministically (fixed key order, no timestamp field), so
    regenerating from an unchanged real document produces a byte-identical
    file."""
    Path(path).write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_sw_fw_usage_model(path) -> dict:
    """Load a sw_fw_usage_model.json from disk."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if "status" not in doc or "sequences" not in doc:
        raise ValueError(f"{path}: not a sw_fw_usage_model.json document")
    return doc


# ---------------------------------------------------------------------------
# ad hoc entry point
# ---------------------------------------------------------------------------

def execute_verb(verb: str, *, reference_record_path: Optional[str] = None,
                  min_sequence_length: int = DEFAULT_MIN_SEQUENCE_LENGTH,
                  as_json: bool = False):
    """Shared implementation for
    `python -m dv_harness.sw_fw_usage_model extract --reference-record
    <file> [--json]`. Returns `(text, exit_code)`. 0 EXTRACTED with >=1
    sequence, 1 EXTRACTED with zero sequences found, 2 NOT_AVAILABLE or a
    usage error. Reads only; runs/submits/approves nothing."""
    if verb != "extract":
        return f"unknown sw-fw-usage-model verb {verb!r}", 2
    if not reference_record_path:
        return "extract requires --reference-record", 2

    doc = extract_sw_fw_usage_model(
        reference_record_path=reference_record_path, min_sequence_length=min_sequence_length)

    if doc["status"] == "NOT_AVAILABLE":
        code = 2
    elif doc["sequence_count"] == 0:
        code = 1
    else:
        code = 0

    if as_json:
        return json.dumps(doc, indent=2), code

    lines = [f"sw/fw usage model: {doc['status']}"]
    if doc.get("reason"):
        lines.append(f"  reason: {doc['reason']}")
    lines.append(f"  sequences found: {doc['sequence_count']}")
    for seq in doc["sequences"]:
        lines.append(f"  [{seq['sequence_id']}] {seq['name'] or '(untitled)'} -- "
                     f"{seq['step_count']} steps")
        for step in seq["steps"]:
            lines.append(f"    #{step['position']} phase={step['phase_status']}"
                         f"({step['phase']}) action={step['action_status']}({step['action']}) "
                         f"register={step['register_status']}({step['register']}): "
                         f"{step['raw_text']!r}")
    return "\n".join(lines), code


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.sw_fw_usage_model",
        description="Extract documented SW/FW usage-sequence facts from a real, distilled "
                    "programming guide, shaped into programming_sequence_ir.py's own phase/"
                    "action vocabulary. Reads only; runs/submits/approves nothing.")
    ap.add_argument("verb", choices=("extract",))
    ap.add_argument("--reference-record", default=None, dest="reference_record_path",
                    help="vip_user_guide_distill .reference.json path (doc_kind='programming_guide').")
    ap.add_argument("--min-sequence-length", type=int, default=DEFAULT_MIN_SEQUENCE_LENGTH)
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.verb, reference_record_path=a.reference_record_path,
                              min_sequence_length=a.min_sequence_length, as_json=a.as_json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
