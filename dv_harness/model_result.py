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

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .task_boundary_conformance import TaskBoundary, classify_path, CLASS_WITHIN_BOUNDARY
from .model_handoff import ModelHandoffV1, TARGET_MODELS

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


def _parse_sections(text: str) -> Dict[str, str]:
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _parse_value(field_name: str, raw: str) -> Any:
    if raw == "(none)" or raw == "":
        return [] if field_name in _RESULT_LIST_FIELDS else None
    if field_name in _RESULT_LIST_FIELDS:
        items = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("- "):
                items.append(line[2:].strip())
            elif line:
                items.append(line)
        return items
    return raw.strip()


def from_markdown(text: str) -> ModelResultV1:
    """Real, strict parser. A missing required field, or a document that
    is not even a RESULT_V1 document at all, is a real `ResultParseError`
    -- never a silently-defaulted/partially-guessed result. This is what
    makes 'malformed Markdown' (dispatch's own required failure test) a
    real, distinguishable outcome from 'a valid but FAILing result.'"""
    if "L5DGVA_MODEL_RESULT_V1" not in text:
        raise ResultParseError("NOT_A_RESULT_DOCUMENT", {})
    sections = _parse_sections(text)
    missing = [f for f in _RESULT_FIELD_ORDER if f not in sections]
    if missing:
        raise ResultParseError("MISSING_REQUIRED_FIELDS", {"missing": missing})
    values = {f: _parse_value(f, sections[f]) for f in _RESULT_FIELD_ORDER}

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


def _render_value(field_name: str, value: Any) -> str:
    if field_name in _RESULT_LIST_FIELDS:
        items = list(value or [])
        return "\n".join(f"- {v}" for v in items) if items else "(none)"
    if value is None or value == "":
        return "(none)"
    return str(value)


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
    lines = ["# L5DGVA_MODEL_RESULT_V1", ""]
    for name in _RESULT_FIELD_ORDER:
        lines.append(f"## {name}")
        lines.append(_render_value(name, values[name]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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


@dataclass
class ValidationOutcome:
    task_id_validated: bool
    producer_validated: bool
    task_type_validated: bool
    scope_validated: bool
    schema_validated: bool
    evidence_validated: bool
    findings: List[str] = field(default_factory=list)
    scope_violations: List[Dict[str, str]] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return (self.task_id_validated and self.producer_validated
                and self.task_type_validated and self.scope_validated
                and self.schema_validated and self.evidence_validated)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id_validated": self.task_id_validated,
            "producer_validated": self.producer_validated,
            "task_type_validated": self.task_type_validated,
            "scope_validated": self.scope_validated,
            "schema_validated": self.schema_validated,
            "evidence_validated": self.evidence_validated,
            "accepted": self.accepted,
            "findings": self.findings,
            "scope_violations": self.scope_violations,
        }


def validate_result(handoff: ModelHandoffV1, result: ModelResultV1) -> ValidationOutcome:
    """The real round-trip integrity chain (architecture doc: "Round-Trip
    Integrity" + "Result Ingestion"). Schema validity is already
    guaranteed by `from_markdown()` having succeeded (a required field
    can never be missing at this point) -- `schema_validated` here checks
    the REMAINING schema-level fact `from_markdown()` cannot check alone:
    `result_status` is real (already enforced by `from_markdown()`) AND
    `producer_model` is one of the real `TARGET_MODELS`.

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

    schema_ok = result.producer_model in TARGET_MODELS

    scope_violations: List[Dict[str, str]] = []
    for f in result.files_referenced:
        cls = classify_path(f, handoff.scope, "MODIFIED")
        if cls != CLASS_WITHIN_BOUNDARY:
            scope_violations.append({"path": f, "classification": cls})
    scope_ok = not scope_violations
    if not scope_ok:
        findings.append(V_SCOPE_VIOLATION)

    # EVIDENCE_VALIDATED: a result that makes real CLAIMS/FINDINGS but
    # cites zero evidence_refs is not acceptable -- "a model result is
    # not evidence merely because a model produced it" (architecture
    # doc). A result with no claims/findings at all (e.g. a genuine
    # BLOCKED/INSUFFICIENT_EVIDENCE status) is not required to cite
    # evidence for a claim it never made.
    has_assertions = bool(result.claims) or bool(result.findings)
    evidence_ok = (not has_assertions) or bool(result.evidence_refs)
    if not evidence_ok:
        findings.append(V_MISSING_EVIDENCE)

    return ValidationOutcome(
        task_id_validated=task_id_ok, producer_validated=producer_ok,
        task_type_validated=task_type_ok, scope_validated=scope_ok,
        schema_validated=schema_ok, evidence_validated=evidence_ok,
        findings=findings, scope_violations=scope_violations,
    )
