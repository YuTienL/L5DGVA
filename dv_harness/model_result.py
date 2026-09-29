"""dv_harness/model_result.py -- L5DGVA_MODEL_RESULT_V1: the structured
Markdown result a human transports back from a target model (Codex/
ChatGPT) into L5DGVA, plus the real round-trip validation chain
(`docs/architecture/L5DGVA_M7_STRUCTURED_MULTI_MODEL_MD_HANDOFF_
ARCHITECTURE.md`'s own "Result Ingestion" pipeline: RESULT_RETURNED ->
PARSED -> TASK_ID_VALIDATED -> PRODUCER_VALIDATED -> SCOPE_VALIDATED ->
SCHEMA_VALIDATED -> EVIDENCE_VALIDATED -> GOVERNANCE_VALIDATED ->
RESULT_CLASSIFIED).

A model result is not evidence merely because a model produced it
(architecture doc, "Evidence and Disagreement"): `ModelResultV1` keeps
`claims`/`findings` distinct from `evidence_refs`/`counter_evidence`/
`unknown_items` -- never collapsed into one undifferentiated text blob.
Model confidence alone is never acceptance authority: `validate_result()`
never reads a "confidence" field to decide PASS/FAIL; it only checks real,
structural round-trip facts (TASK_ID/producer/scope/schema/evidence
presence).
"""
from __future__ import annotations

import re as _re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .task_boundary_conformance import TaskBoundary, classify_path, CLASS_WITHIN_BOUNDARY
from . import md_kv_codec as _codec
from .model_handoff import (ModelHandoffV1, TARGET_MODELS, read_boundary, canonical_repo_path,
                            canonical_boundary, real_repo_relative)

RESULT_VERSION = "1.0"

#: Recommended statuses (architecture doc, "Result Status"). Model
#: confidence is never itself a status -- these are the only real values
#: `validate_result()`/a caller may assert.
RESULT_STATUSES = (
    "PASS", "FAIL", "PARTIAL", "BLOCKED", "HUMAN_DECISION_REQUIRED",
    "INSUFFICIENT_EVIDENCE", "INVALID_SCOPE", "INVALID_RESULT",
)

_RESULT_FIELD_ORDER = [
    "RESULT_VERSION", "TASK_ID", "PRODUCER_MODEL", "TASK_TYPE", "RESULT_STATUS",
    "CLAIMS", "FINDINGS", "EVIDENCE_REFS", "COUNTER_EVIDENCE", "UNKNOWN_ITEMS",
    "FILES_REFERENCED", "VALIDATION_PERFORMED", "RECOMMENDED_ACTIONS",
    "HUMAN_DECISIONS_REQUIRED", "SCOPE_EXCEPTIONS", "RETURNED_ARTIFACTS",
]

_RESULT_LIST_FIELDS = frozenset({
    "CLAIMS", "FINDINGS", "EVIDENCE_REFS", "COUNTER_EVIDENCE", "UNKNOWN_ITEMS",
    "FILES_REFERENCED", "VALIDATION_PERFORMED", "RECOMMENDED_ACTIONS",
    "HUMAN_DECISIONS_REQUIRED", "SCOPE_EXCEPTIONS", "RETURNED_ARTIFACTS",
})


@dataclass(frozen=True)
class ModelResultV1:
    """L5DGVA_MODEL_RESULT_V1. `claims`/`findings` are the model's own
    assertions; `evidence_refs` are what actually backs them;
    `counter_evidence`/`unknown_items` are preserved, never dropped, per
    the architecture doc's own "do not resolve disagreement by majority
    vote; preserve competing claims/evidence" rule."""

    result_version: str
    task_id: str
    producer_model: str
    task_type: str
    result_status: str
    claims: Sequence[str] = ()
    findings: Sequence[str] = ()
    evidence_refs: Sequence[str] = ()
    counter_evidence: Sequence[str] = ()
    unknown_items: Sequence[str] = ()
    files_referenced: Sequence[str] = ()
    validation_performed: Sequence[str] = ()
    recommended_actions: Sequence[str] = ()
    human_decisions_required: Sequence[str] = ()
    scope_exceptions: Sequence[str] = ()
    returned_artifacts: Sequence[str] = ()

    _LIST_FIELD_NAMES = (
        "claims", "findings", "evidence_refs", "counter_evidence", "unknown_items",
        "files_referenced", "validation_performed", "recommended_actions",
        "human_decisions_required", "scope_exceptions", "returned_artifacts",
    )

    def __post_init__(self) -> None:
        # Normalize every Sequence field to a real tuple regardless of
        # what the caller passed (list or tuple) -- a frozen dataclass
        # should compare/hash consistently either way, matching
        # from_markdown()'s own always-tuple output.
        for name in self._LIST_FIELD_NAMES:
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ResultParseError(ValueError):
    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def from_markdown(text: str) -> ModelResultV1:
    """Real, strict parser. A missing required field, or a document that
    is not even a RESULT_V1 document at all, is a real `ResultParseError`
    -- never a silently-defaulted/partially-guessed result. This is what
    makes 'malformed Markdown' (dispatch's own required failure test) a
    real, distinguishable outcome from 'a valid but FAILing result.'"""
    try:
        sections, escaped = _codec.split_sections(text, _RESULT_FIELD_ORDER, "L5DGVA_MODEL_RESULT_V1")
        missing = [f for f in _RESULT_FIELD_ORDER if f not in sections]
        if missing:
            raise ResultParseError("MISSING_REQUIRED_FIELDS", {"missing": missing})
        values = {
            f: (_codec.parse_list(sections[f], escaped) if f in _RESULT_LIST_FIELDS
                else _codec.parse_scalar(sections[f], escaped))
            for f in _RESULT_FIELD_ORDER
        }
    except _codec.MdKvError as exc:
        raise ResultParseError("NOT_A_RESULT_DOCUMENT" if exc.reason == "NOT_THIS_DOCUMENT" else exc.reason, exc.detail) from exc

    if values["RESULT_STATUS"] not in RESULT_STATUSES:
        raise ResultParseError("INVALID_RESULT_STATUS",
                               {"result_status": values["RESULT_STATUS"], "allowed": RESULT_STATUSES})

    return ModelResultV1(
        result_version=values["RESULT_VERSION"], task_id=values["TASK_ID"],
        producer_model=values["PRODUCER_MODEL"], task_type=values["TASK_TYPE"],
        result_status=values["RESULT_STATUS"],
        claims=tuple(values["CLAIMS"] or ()), findings=tuple(values["FINDINGS"] or ()),
        evidence_refs=tuple(values["EVIDENCE_REFS"] or ()),
        counter_evidence=tuple(values["COUNTER_EVIDENCE"] or ()),
        unknown_items=tuple(values["UNKNOWN_ITEMS"] or ()),
        files_referenced=tuple(values["FILES_REFERENCED"] or ()),
        validation_performed=tuple(values["VALIDATION_PERFORMED"] or ()),
        recommended_actions=tuple(values["RECOMMENDED_ACTIONS"] or ()),
        human_decisions_required=tuple(values["HUMAN_DECISIONS_REQUIRED"] or ()),
        scope_exceptions=tuple(values["SCOPE_EXCEPTIONS"] or ()),
        returned_artifacts=tuple(values["RETURNED_ARTIFACTS"] or ()),
    )


def to_markdown(result: ModelResultV1) -> str:
    """The inverse of `from_markdown()` -- used by this module's own
    round-trip tests, and available to a caller building a synthetic
    result for a test fixture (never for fabricating a REAL round trip)."""
    values = {
        "RESULT_VERSION": result.result_version, "TASK_ID": result.task_id,
        "PRODUCER_MODEL": result.producer_model, "TASK_TYPE": result.task_type,
        "RESULT_STATUS": result.result_status, "CLAIMS": list(result.claims),
        "FINDINGS": list(result.findings), "EVIDENCE_REFS": list(result.evidence_refs),
        "COUNTER_EVIDENCE": list(result.counter_evidence),
        "UNKNOWN_ITEMS": list(result.unknown_items),
        "FILES_REFERENCED": list(result.files_referenced),
        "VALIDATION_PERFORMED": list(result.validation_performed),
        "RECOMMENDED_ACTIONS": list(result.recommended_actions),
        "HUMAN_DECISIONS_REQUIRED": list(result.human_decisions_required),
        "SCOPE_EXCEPTIONS": list(result.scope_exceptions),
        "RETURNED_ARTIFACTS": list(result.returned_artifacts),
    }
    return _codec.render_document("L5DGVA_MODEL_RESULT_V1", _RESULT_FIELD_ORDER, values, _RESULT_LIST_FIELDS)


# --- Round-trip validation ---------------------------------------------------

#: Real, per-check status vocabulary -- a validation outcome is never
#: collapsed to a bare True/False, so a caller (or a test) can see exactly
#: which check failed.
V_OK = "OK"
V_TASK_ID_MISMATCH = "TASK_ID_MISMATCH"
V_PRODUCER_MISMATCH = "PRODUCER_MISMATCH"
V_TASK_TYPE_INCOMPATIBLE = "TASK_TYPE_INCOMPATIBLE"
V_SCOPE_VIOLATION = "SCOPE_VIOLATION"
V_MISSING_EVIDENCE = "MISSING_EVIDENCE"
V_UNSUPPORTED_RESULT_VERSION = "UNSUPPORTED_RESULT_VERSION"
V_FABRICATED_EVIDENCE_PATH = "FABRICATED_EVIDENCE_PATH"
V_INVALID_GOVERNANCE_REF = "INVALID_GOVERNANCE_REF"
V_UNSUPPORTED_EXPECTED_SCHEMA = "UNSUPPORTED_EXPECTED_OUTPUT_SCHEMA"
V_NO_VERIFIED_EVIDENCE = "NO_VERIFIED_EVIDENCE_FOR_VERDICT"

#: RESULT_V1 evidence grammar (GAP-V2-009/013, Codex R2/R3).
#:
#: A PATH TOKEN is a repo-style file path with a recognised source/doc
#: extension, optionally followed by ":line" / ":start-end", bounded so it is
#: never a fragment of a longer identifier (`handoff.expected_output_schema`,
#: `e.g.`, `1.0` are not path tokens).
#:
#: An EVIDENCE_REFS entry is a CITATION when, after an optional
#: `EVIDENCE:` / `COUNTER_EVIDENCE:` label, it BEGINS with a path token.
#: Every path token in a citation must exist on disk AND lie inside the
#: handoff's read boundary (ALLOWED_FILES + INPUT_EVIDENCE_REFS - FORBIDDEN).
#: Any other entry is NARRATIVE: its path mentions are disclosed
#: (`evidence_narrative_mentions`) but never verify anything and never
#: reject the result -- a reviewer describing a probe that used a forbidden
#: or nonexistent path is not thereby citing it as evidence.
_EVIDENCE_EXTENSIONS = (
    "py|md|csv|json|jsonl|txt|sv|svh|v|vh|yaml|yml|toml|ps1|sh|tcl|mk|cfg|ini|xml|html|js|ts|log|f|vcs|lst"
)
_PATH_TOKEN = (
    r"(?<![\w./\\-])[\w][\w./-]*\.(?:" + _EVIDENCE_EXTENSIONS + r")(?::\d+(?:-\d+)?)?(?![\w])"
)
_PATH_TOKEN_RE = _re.compile(_PATH_TOKEN)
_CITATION_RE = _re.compile(r"^\s*(?:(?:COUNTER_)?EVIDENCE:\s*)?" + _PATH_TOKEN)

SUPPORTED_EXPECTED_OUTPUT_SCHEMA = "L5DGVA_MODEL_RESULT_V1"

#: Result statuses that assert a verdict about the reviewed subject; such a
#: result must be backed by at least one VERIFIED citation.
_VERDICT_STATUSES = ("PASS", "FAIL", "PARTIAL")


def _evidence_ref_file_claims(evidence_ref: str) -> List[str]:
    """Every path token in one evidence_ref string, path portion only."""
    return [m.group(0).split(":", 1)[0] for m in _PATH_TOKEN_RE.finditer(evidence_ref)]


def _is_citation(evidence_ref: str) -> bool:
    return _CITATION_RE.match(evidence_ref) is not None


CLASS_UNSAFE_PATH = "UNSAFE_PATH"


def _classify_canonical(raw: str, boundary: TaskBoundary, root: Optional[Path]) -> Tuple[str, Optional[str]]:
    """Scope classification on the CANONICAL path (REVIEW-003 N1): `..`
    segments are collapsed first, absolute/escaping paths are UNSAFE_PATH,
    and -- when a real `root` is available and the path exists -- the true
    filesystem identity (case, trailing dots, short names, symlinks) is
    classified too, so an alias of a forbidden file cannot pass on a lexical
    match against an allowed prefix. Fail-closed: either view failing fails."""
    canon = canonical_repo_path(raw)
    if canon is None:
        return CLASS_UNSAFE_PATH, None
    cls = classify_path(canon, boundary, "MODIFIED")
    if cls != CLASS_WITHIN_BOUNDARY:
        return cls, canon
    if root is not None:
        real = real_repo_relative(Path(root), canon)
        if real == "":
            return CLASS_UNSAFE_PATH, canon
        if real is not None and real != canon:
            cls2 = classify_path(real, boundary, "MODIFIED")
            if cls2 != CLASS_WITHIN_BOUNDARY:
                return cls2, real
    return CLASS_WITHIN_BOUNDARY, canon


@dataclass
class ValidationOutcome:
    task_id_validated: bool
    producer_validated: bool
    task_type_validated: bool
    scope_validated: bool
    schema_validated: bool
    evidence_validated: bool
    governance_validated: bool = True
    governance_validation_status: str = "NOT_APPLICABLE"
    findings: List[str] = field(default_factory=list)
    scope_violations: List[Dict[str, str]] = field(default_factory=list)
    evidence_unverifiable: List[str] = field(default_factory=list)
    fabricated_evidence: List[Dict[str, str]] = field(default_factory=list)
    verified_evidence_refs: List[str] = field(default_factory=list)
    evidence_narrative_mentions: List[Dict[str, str]] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return (self.task_id_validated and self.producer_validated
                and self.task_type_validated and self.scope_validated
                and self.schema_validated and self.evidence_validated
                and self.governance_validated)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id_validated": self.task_id_validated,
            "producer_validated": self.producer_validated,
            "task_type_validated": self.task_type_validated,
            "scope_validated": self.scope_validated,
            "schema_validated": self.schema_validated,
            "evidence_validated": self.evidence_validated,
            "governance_validated": self.governance_validated,
            "governance_validation_status": self.governance_validation_status,
            "accepted": self.accepted,
            "findings": self.findings,
            "scope_violations": self.scope_violations,
            "evidence_unverifiable": self.evidence_unverifiable,
            "fabricated_evidence": self.fabricated_evidence,
            "verified_evidence_refs": self.verified_evidence_refs,
            "evidence_narrative_mentions": self.evidence_narrative_mentions,
        }


def validate_result(handoff: ModelHandoffV1, result: ModelResultV1, root: Optional[Path] = None,
                     own_result_path: Optional[str] = None) -> ValidationOutcome:
    """The real round-trip integrity chain (architecture doc: "Round-Trip
    Integrity" + "Result Ingestion"). Untrusted external input (dispatch's
    own "treat returned external-model data as untrusted input"): nothing
    here normalizes a conflicting field into compliance -- every check is
    independent and a failure is recorded, never silently corrected.

    `root` (GAP-V2-009 fix): the real project root evidence-path claims
    are resolved against. `None` (the default) disables file-existence
    verification of evidence_refs entirely -- every claimed path is then
    left unverified (a caller that cannot supply a real root gets the
    pre-fix, disclosed-weaker behavior, never a fabricated PASS).

    `own_result_path` (root-relative, POSIX-style): the real on-disk path
    of THIS result document, as the caller (import_result()) actually
    read it -- never model-declared. A RETURNED_ARTIFACTS entry naming
    exactly this path is transport metadata ("here is where my own reply
    lives"), not a claim about reviewed/modified content, so it is
    exempted from the GAP-V2-010/F2 scope check below. FILES_REFERENCED
    is never exempted this way, and a RETURNED_ARTIFACTS entry naming any
    OTHER out-of-scope path still fails scope_validated -- a model cannot
    use this to launder an unrelated path, since the exemption is keyed
    to a caller-supplied fact, not anything the model itself wrote.

    Model confidence is never read here -- only structural facts."""
    findings: List[str] = []

    task_id_ok = (result.task_id == handoff.task_id)
    if not task_id_ok:
        findings.append(V_TASK_ID_MISMATCH)

    producer_ok = (result.producer_model == handoff.target_model)
    if not producer_ok:
        findings.append(V_PRODUCER_MISMATCH)

    # TASK_TYPE compatibility: the result must claim the SAME task type
    # the handoff declared -- this module never guesses "close enough."
    task_type_ok = (result.task_type == handoff.task_type)
    if not task_type_ok:
        findings.append(V_TASK_TYPE_INCOMPATIBLE)

    # GAP-V2-009/F1 fix: schema_validated now also requires a SUPPORTED
    # RESULT_VERSION -- before this fix, any string (e.g. "9.9") passed
    # silently as long as producer_model matched.
    version_ok = (result.result_version == RESULT_VERSION)
    if not version_ok:
        findings.append(V_UNSUPPORTED_RESULT_VERSION)
    # GAP-V2-009 (R7): the handoff's own EXPECTED_OUTPUT_SCHEMA must be one
    # this ingestion path can actually validate against.
    expected_schema_ok = (handoff.expected_output_schema == SUPPORTED_EXPECTED_OUTPUT_SCHEMA)
    if not expected_schema_ok:
        findings.append(V_UNSUPPORTED_EXPECTED_SCHEMA)
    schema_ok = (result.producer_model in TARGET_MODELS) and version_ok and expected_schema_ok

    # GAP-V2-010/013: two boundaries. FILES_REFERENCED and path citations in
    # EVIDENCE_REFS are READ claims -> the read boundary (ALLOWED_FILES +
    # INPUT_EVIDENCE_REFS - FORBIDDEN_FILES; authorization only from those
    # explicit declarations). RETURNED_ARTIFACTS are OUTPUT claims -> the
    # handoff's own (modification) scope, with one caller-derived exemption:
    # `own_result_path`, the real path of this result document.
    read_scope = read_boundary(handoff)
    write_scope = canonical_boundary(handoff.scope)
    own_result_canon = canonical_repo_path(own_result_path) if own_result_path is not None else None
    scope_violations: List[Dict[str, str]] = []
    for f in result.files_referenced:
        cls, _ = _classify_canonical(f, read_scope, root)
        if cls != CLASS_WITHIN_BOUNDARY:
            scope_violations.append({"field": "FILES_REFERENCED", "path": f, "classification": cls})
    for f in result.returned_artifacts:
        if own_result_canon is not None and canonical_repo_path(f) == own_result_canon:
            continue
        cls, _ = _classify_canonical(f, write_scope, root)
        if cls != CLASS_WITHIN_BOUNDARY:
            scope_violations.append({"field": "RETURNED_ARTIFACTS", "path": f, "classification": cls})

    # EVIDENCE_VALIDATED (see the evidence grammar above).
    has_assertions = bool(result.claims) or bool(result.findings)
    evidence_present_ok = (not has_assertions) or bool(result.evidence_refs)
    if not evidence_present_ok:
        findings.append(V_MISSING_EVIDENCE)

    evidence_unverifiable: List[str] = []
    fabricated_evidence: List[Dict[str, str]] = []
    verified_evidence_refs: List[str] = []
    narrative_mentions: List[Dict[str, str]] = []
    if root is not None:
        for ref in result.evidence_refs:
            claims = _evidence_ref_file_claims(ref)
            if _is_citation(ref):
                missing = []
                for c in claims:
                    canon = canonical_repo_path(c)
                    if canon is not None and not (Path(root) / canon).is_file():
                        missing.append(c)
                if missing:
                    fabricated_evidence.append({"evidence_ref": ref, "claimed_paths": ", ".join(claims),
                                                "missing_paths": ", ".join(missing)})
                    continue
                out_of_scope = False
                for c in claims:
                    cls, _ = _classify_canonical(c, read_scope, root)
                    if cls != CLASS_WITHIN_BOUNDARY:
                        out_of_scope = True
                        scope_violations.append({"field": "EVIDENCE_REFS", "path": c, "classification": cls})
                if not out_of_scope:
                    verified_evidence_refs.append(ref)
            else:
                evidence_unverifiable.append(ref)
                for c in claims:
                    narrative_mentions.append({
                        "evidence_ref": ref[:120], "path": c,
                        "exists": str((Path(root) / (canonical_repo_path(c) or "__unsafe__")).is_file()),
                        "read_scope": _classify_canonical(c, read_scope, root)[0],
                    })
    else:
        evidence_unverifiable = list(result.evidence_refs)

    scope_ok = not scope_violations
    if not scope_ok:
        findings.append(V_SCOPE_VIOLATION)
    if fabricated_evidence:
        findings.append(V_FABRICATED_EVIDENCE_PATH)
    # Acceptance policy for unverifiable free-form evidence: it is disclosed
    # and tolerated, but a result that asserts a verdict (PASS/FAIL/PARTIAL)
    # about real claims must be backed by at least one VERIFIED citation --
    # free-form text alone (e.g. "fabricated:anything") never satisfies it.
    verdict_backed_ok = True
    if root is not None and has_assertions and result.result_status in _VERDICT_STATUSES:
        verdict_backed_ok = bool(verified_evidence_refs)
        if not verdict_backed_ok:
            findings.append(V_NO_VERIFIED_EVIDENCE)
    evidence_ok = evidence_present_ok and not fabricated_evidence and verdict_backed_ok

    # GAP-V2-009 governance-validation fix: represent the condition
    # honestly rather than silently omitting it. Empty REQUIRED_
    # GOVERNANCE_REFS is a real NOT_APPLICABLE (no governance authority
    # was declared as required for this task), never conflated with "ran
    # and passed." Non-empty refs are checked against the real filesystem
    # the SAME way an evidence file-claim is (governance_registry.py's
    # own entries are real repo-relative paths).
    if not handoff.required_governance_refs:
        governance_ok = True
        governance_status = "NOT_APPLICABLE"
    elif root is None:
        governance_ok = True
        governance_status = "UNVERIFIED_NO_ROOT"
    else:
        invalid_refs = [r for r in handoff.required_governance_refs
                        if canonical_repo_path(r) is None or not (Path(root) / canonical_repo_path(r)).is_file()]
        governance_ok = not invalid_refs
        governance_status = "VALIDATED" if governance_ok else "INVALID_REF"
        if invalid_refs:
            findings.append(V_INVALID_GOVERNANCE_REF)

    return ValidationOutcome(
        task_id_validated=task_id_ok, producer_validated=producer_ok,
        task_type_validated=task_type_ok, scope_validated=scope_ok,
        schema_validated=schema_ok, evidence_validated=evidence_ok,
        governance_validated=governance_ok, governance_validation_status=governance_status,
        findings=findings, scope_violations=scope_violations,
        evidence_unverifiable=evidence_unverifiable, fabricated_evidence=fabricated_evidence,
        verified_evidence_refs=verified_evidence_refs, evidence_narrative_mentions=narrative_mentions,
    )
