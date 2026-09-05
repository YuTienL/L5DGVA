"""dv_harness/requirement_contract.py -- spec section 184's CANONICAL
REQUIREMENT CONTRACT and its five-value requirement status vocabulary
(COMPLETE / PARTIAL / AMBIGUOUS / CONTRADICTORY / UNKNOWN), as a real
dataclass + JSON schema + analysis, following env_manifest.py's
schema-versioning convention (a module-level SCHEMA_VERSION, a sibling file
in dv_harness/schemas/, a fail-closed `*ValidationError` rather than a
False/None return).

WHY THIS EXISTS RATHER THAN AN EXTENSION OF THE OLD SHAPE. The closest
pre-existing mechanism, tools/verification_flow/spec_to_vplan_requirement_
quality_gate.py, checks five fields (spec_ref / feature / expected_behavior /
verification_method / coverage_goal) plus an ambiguity rule. Section 184 names
fifteen, and the eight it adds are exactly the ones a downstream generator
needs and would otherwise re-invent from prose: Protocol, Configuration,
Precondition, Observability, Checker, Coverage Intent, Priority, Criticality.
That gate had no status vocabulary at all -- a requirement was implicitly
either complete or a gate failure, with no way to persist "this one is
CONTRADICTORY and a human has to decide". This module supplies the richer
contract; the gate is EXTENDED to validate against it (never replaced, and
never for records still in the older shape).

WHAT MAKES THIS MORE THAN A SHAPE CHECK. `status` is a field an agent fills
in about its own extraction work, so per the project's Evidence Truth Rule it
is a judgment, not evidence. `derive_status()` therefore RE-DERIVES the status
from the record's own content and `analyze_requirement_contract()` rejects a
status the content does not support. The two load-bearing rules:

  * STATUS_OVERCLAIMED -- the record says COMPLETE while some contract field
    is still UNRESOLVED (absent, empty, or literally UNKNOWN/TBD/N/A). This is
    the failure mode that matters: a COMPLETE requirement is the only thing
    `downstream_consumable()` lets a generator build from.
  * UNRESOLVED_BLOCKER_HIDDEN -- the record carries an unresolved ambiguity or
    contradiction while declaring a status that is neither AMBIGUOUS nor
    CONTRADICTORY, i.e. a real conflict filed and then quietly stepped over.
    Section 32's "Unresolved requirements remain visible as gaps" as code.

Declaring a status WORSE than derived is never an error (a human marking a
fully-populated requirement PARTIAL because they doubt it is honest
conservatism); it is reported as a WARNING so the disagreement stays visible.

ARBITRATION IS NOT HERE. A CONTRADICTORY requirement STOPS at CONTRADICTORY.
This module names the conflicting sources and refuses to let the requirement
feed a generator; it never picks which source wins. That is the same boundary
system_resource_inventory's driver-conflict DETECTION keeps against ownership
ARBITRATION, for the same reason: choosing between two contradicting spec
statements is a human engineering decision.

VOCABULARY REUSE. `confidence` reuses inference.CONFIDENCE_LEVELS
(HIGH/MEDIUM/LOW) plus UNKNOWN; `priority` reuses
memory.CORNER_CASE_RISK_TIERS (P0..P3). Both are imported, not re-typed, so a
change there cannot silently leave a second vocabulary behind here.
`criticality` is genuinely new -- nothing in this repo had a
consequence-of-failure axis -- and is deliberately a different axis from
priority.

DELIBERATELY BOUNDED. This module reads a requirement RECORD; it does not
parse specifications, does not extract requirements from prose, and does not
check a requirement against RTL, a register map, or a simulation. It answers
"is this requirement internally coherent, honestly statused, and safe to
generate from", which is the question section 184's contract is FOR. It also
DECIDES nothing on its own: the only enforcement point added is the existing
REQUIREMENTS_TRACEABILITY gate, and only for records that declare themselves
in this shape.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .inference import CONFIDENCE_LEVELS
from .memory import CORNER_CASE_RISK_TIERS

SCHEMA_VERSION = "1.0"
CONTRACT_SCHEMA_VERSION = "1.0"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "requirement_contract.schema.json"

#: Section 184's requirement status vocabulary, verbatim and in the
#: document's own order.
STATUS_COMPLETE = "COMPLETE"
STATUS_PARTIAL = "PARTIAL"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_CONTRADICTORY = "CONTRADICTORY"
STATUS_UNKNOWN = "UNKNOWN"
REQUIREMENT_STATUSES: Tuple[str, ...] = (
    STATUS_COMPLETE, STATUS_PARTIAL, STATUS_AMBIGUOUS,
    STATUS_CONTRADICTORY, STATUS_UNKNOWN,
)

#: What each status MEANS, carried with the values so a report can print the
#: definition instead of assuming the reader remembers it.
STATUS_DEFINITIONS: Dict[str, str] = {
    STATUS_COMPLETE: "every contract field resolved, no unresolved ambiguity or "
                     "contradiction; the only status a generator may build from",
    STATUS_PARTIAL: "verifiable (stimulus and expected result are known) but at "
                    "least one contract field is still unresolved",
    STATUS_AMBIGUOUS: "the specification prose admits more than one reading; an "
                      "open question is on file",
    STATUS_CONTRADICTORY: "two or more sources disagree; a human must arbitrate "
                          "before this requirement can be used",
    STATUS_UNKNOWN: "not enough was extracted to say anything -- a visible gap, "
                    "never a silent pass",
}

#: Priority is the SCHEDULING axis. Reused from memory.CORNER_CASE_RISK_TIERS
#: rather than re-typed, so this repo keeps one P0..P3 vocabulary.
PRIORITY_VALUES: Tuple[str, ...] = tuple(CORNER_CASE_RISK_TIERS)

#: Criticality is the CONSEQUENCE-OF-FAILURE axis, deliberately distinct from
#: priority. New here: nothing in this repo expressed it before.
CRITICALITY_BLOCKER = "BLOCKER"
CRITICALITY_MAJOR = "MAJOR"
CRITICALITY_MINOR = "MINOR"
CRITICALITY_UNKNOWN = "UNKNOWN"
CRITICALITY_VALUES: Tuple[str, ...] = (
    CRITICALITY_BLOCKER, CRITICALITY_MAJOR, CRITICALITY_MINOR, CRITICALITY_UNKNOWN,
)

#: HIGH/MEDIUM/LOW come from inference.CONFIDENCE_LEVELS; UNKNOWN is added
#: because "we could not tell" must be expressible and must force status
#: UNKNOWN rather than quietly reading as LOW.
CONFIDENCE_VALUES: Tuple[str, ...] = tuple(CONFIDENCE_LEVELS) + (STATUS_UNKNOWN,)

#: The fifteen fields of section 184's Canonical Requirement Contract, in the
#: document's own order. `requirement_id` is section 184's "ID", spelled to
#: match master_requirement_completeness_gate.py's existing identifier.
CONTRACT_FIELDS: Tuple[str, ...] = (
    "requirement_id", "source", "feature", "protocol", "configuration",
    "precondition", "stimulus", "expected_result", "observability",
    "checker", "coverage_intent", "priority", "criticality",
    "confidence", "status",
)

#: The subset whose content is free text and therefore subject to the
#: RESOLVED/UNRESOLVED test below. `requirement_id`, `priority`,
#: `criticality`, `confidence` and `status` are enumerated or identity
#: fields validated separately; `source` is a provenance object.
CONTRACT_TEXT_FIELDS: Tuple[str, ...] = (
    "feature", "protocol", "configuration", "precondition", "stimulus",
    "expected_result", "observability", "checker", "coverage_intent",
)

#: Without BOTH of these a requirement is not merely incomplete, it is
#: unverifiable -- there is nothing to drive and nothing to compare against.
#: Their absence yields UNKNOWN, not PARTIAL.
VERIFIABILITY_FIELDS: Tuple[str, ...] = ("stimulus", "expected_result")

#: Placeholders that must NOT count as a populated field. Without this, an
#: agent writing "TBD" into `checker` produces a COMPLETE requirement that a
#: generator would then build a checker-less test from.
_UNRESOLVED_SENTINELS = frozenset({"", "unknown", "tbd", "tbd.", "n/a", "na",
                                   "none", "none yet", "?"})

#: The one sentinel that IS a decision: "this requirement genuinely has no
#: configuration dependency / no precondition". Legal only where a real
#: absence is meaningful, never for e.g. `checker`.
EXPLICIT_NONE = "NONE"
_NONE_ALLOWED_FIELDS = frozenset({"configuration", "precondition"})

SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"


class RequirementContractValidationError(ValueError):
    """A requirement contract record (or a set document) fails
    requirement_contract.schema.json validation. Raised rather than returning
    False/None so a caller cannot consume or persist a record that did not
    actually validate -- the same fail-closed discipline as
    env_manifest.EnvManifestValidationError."""


# --------------------------------------------------------------------------
# Schema validation
# --------------------------------------------------------------------------

def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate(doc: Any, schema: dict) -> None:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise RequirementContractValidationError(
            "jsonschema package is not installed; cannot validate against "
            f"{SCHEMA_PATH.name}. Install it rather than skipping validation."
        ) from exc
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
                 for e in errors]
        raise RequirementContractValidationError(
            f"{SCHEMA_PATH.name} validation failed:\n" + "\n".join(lines))


def validate_requirement_contract(record: dict) -> None:
    """Validate ONE requirement record against the schema's
    `#/$defs/requirement_contract`. Raises RequirementContractValidationError."""
    schema = _load_schema()
    sub = dict(schema["$defs"]["requirement_contract"])
    sub["$defs"] = schema["$defs"]          # keep internal $ref targets resolvable
    sub.setdefault("$schema", schema["$schema"])
    _validate(record, sub)


def validate_requirement_contract_set(doc: dict) -> None:
    """Validate a whole {"schema_version", "requirements": [...]} document."""
    _validate(doc, _load_schema())


def declares_contract_shape(record: Any) -> bool:
    """True when a requirement record DECLARES itself to be in the canonical
    contract shape. This is the single discriminator the extended
    spec_to_vplan_requirement_quality_gate uses to decide whether a record
    gets the richer validation or its original code path -- so a project that
    has not migrated is never retroactively failed."""
    return isinstance(record, dict) and "contract_schema_version" in record


# --------------------------------------------------------------------------
# Field resolution
# --------------------------------------------------------------------------

def is_resolved(value: Any, field_name: str = "") -> bool:
    """Is this contract field actually populated?

    A field is UNRESOLVED when it is absent, non-string, empty/whitespace, or
    one of the placeholder strings agents reach for when they do not know
    (UNKNOWN / TBD / N/A / ?). The literal `NONE` is RESOLVED, but only for
    `configuration` and `precondition`, where "there genuinely is no
    dependency" is a real answer rather than an evasion."""
    if isinstance(value, dict):                       # provenance object
        return bool(str(value.get("document", "")).strip())
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if stripped == EXPLICIT_NONE:
        return field_name in _NONE_ALLOWED_FIELDS
    return stripped.lower() not in _UNRESOLVED_SENTINELS


def unresolved_fields(record: dict) -> List[str]:
    """Every contract field of `record` that is not resolved, in the
    document's own field order."""
    out: List[str] = []
    for name in CONTRACT_FIELDS:
        if name in ("priority", "criticality", "confidence", "status"):
            continue                                   # enumerated, checked separately
        if not is_resolved(record.get(name), name):
            out.append(name)
    return out


def _unresolved_ambiguities(record: dict) -> List[dict]:
    return [a for a in (record.get("ambiguities") or [])
            if isinstance(a, dict) and not str(a.get("resolution_or_question", "")).strip()]


def _open_ambiguities(record: dict) -> List[dict]:
    """Ambiguities that exist at all. An ambiguity WITH an open question on
    file is still an ambiguity -- filing the question does not resolve it."""
    return [a for a in (record.get("ambiguities") or []) if isinstance(a, dict)]


def _unresolved_contradictions(record: dict) -> List[dict]:
    return [c for c in (record.get("contradictions") or [])
            if isinstance(c, dict) and not str(c.get("resolution", "")).strip()]


# --------------------------------------------------------------------------
# Status derivation
# --------------------------------------------------------------------------

def derive_status(record: dict) -> Tuple[str, str]:
    """Re-derive section 184's status from the record's own CONTENT, ignoring
    whatever the record's `status` field claims. Returns (status, reason).

    Precedence, worst first -- an unresolved conflict outranks incompleteness
    because it cannot be fixed by filling more fields in:

      1. CONTRADICTORY -- an unresolved contradiction is on file.
      2. AMBIGUOUS     -- an ambiguity is on file and not yet resolved.
      3. UNKNOWN       -- confidence is UNKNOWN (or itself unstated), or both
                          `stimulus` and `expected_result` are unresolved, so
                          there is nothing verifiable to say.
      4. PARTIAL       -- verifiable, but some contract field is unresolved.
      5. COMPLETE      -- everything resolved, nothing outstanding.
    """
    contradictions = _unresolved_contradictions(record)
    if contradictions:
        return STATUS_CONTRADICTORY, (
            f"{len(contradictions)} unresolved contradiction(s) on file: "
            + "; ".join(str(c.get("description", "")) for c in contradictions))

    ambiguities = [a for a in _open_ambiguities(record)
                   if not _ambiguity_is_resolved(a)]
    if ambiguities:
        return STATUS_AMBIGUOUS, (
            f"{len(ambiguities)} unresolved ambiguity(ies) on file: "
            + "; ".join(str(a.get("description", "")) for a in ambiguities))

    confidence = record.get("confidence")
    if confidence == STATUS_UNKNOWN or confidence not in CONFIDENCE_VALUES:
        return STATUS_UNKNOWN, (
            f"confidence is {confidence!r}: the extraction itself is not trusted, "
            "so no stronger status can be claimed")

    missing_verifiability = [f for f in VERIFIABILITY_FIELDS
                             if not is_resolved(record.get(f), f)]
    if len(missing_verifiability) == len(VERIFIABILITY_FIELDS):
        return STATUS_UNKNOWN, (
            "neither stimulus nor expected_result is resolved: there is nothing "
            "to drive and nothing to compare against")

    unresolved = unresolved_fields(record)
    if unresolved:
        return STATUS_PARTIAL, "unresolved contract field(s): " + ", ".join(unresolved)

    return STATUS_COMPLETE, "every contract field resolved; no open ambiguity or contradiction"


def _ambiguity_is_resolved(entry: dict) -> bool:
    """An ambiguity is RESOLVED only when its `resolution_or_question` reads
    as an answer. A question ("which of X or Y applies?") keeps it open --
    that is the whole point of section 32's "unresolved requirements remain
    visible as gaps". The distinction is explicit: an entry may carry
    `resolved: true` only alongside real resolution text."""
    text = str(entry.get("resolution_or_question", "")).strip()
    if not text:
        return False
    return bool(entry.get("resolved")) is True


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def _finding(severity: str, code: str, requirement_id: Any, detail: str, **extra) -> dict:
    out = {"severity": severity, "code": code,
           "requirement_id": requirement_id, "detail": detail}
    out.update(extra)
    return out


def analyze_requirement_contract(record: dict) -> List[dict]:
    """Check ONE contract-shaped requirement record for internal coherence and
    honest statusing. Returns a list of findings, each
    {severity, code, requirement_id, detail}; an empty list means clean.

    Schema shape is NOT re-checked here (call validate_requirement_contract()
    for that) -- this function answers the questions a schema structurally
    cannot: does the declared status match the content, is a filed conflict
    being stepped over, is a placeholder masquerading as a populated field."""
    rid = record.get("requirement_id")
    findings: List[dict] = []

    declared = record.get("status")
    if declared not in REQUIREMENT_STATUSES:
        findings.append(_finding(
            SEVERITY_ERROR, "INVALID_REQUIREMENT_STATUS", rid,
            f"status {declared!r} is not one of section 184's five values "
            + "/".join(REQUIREMENT_STATUSES), declared_status=declared))

    if record.get("priority") not in PRIORITY_VALUES:
        findings.append(_finding(
            SEVERITY_ERROR, "INVALID_PRIORITY", rid,
            f"priority {record.get('priority')!r} is not one of "
            + "/".join(PRIORITY_VALUES)))
    if record.get("criticality") not in CRITICALITY_VALUES:
        findings.append(_finding(
            SEVERITY_ERROR, "INVALID_CRITICALITY", rid,
            f"criticality {record.get('criticality')!r} is not one of "
            + "/".join(CRITICALITY_VALUES)))
    if record.get("confidence") not in CONFIDENCE_VALUES:
        findings.append(_finding(
            SEVERITY_ERROR, "INVALID_CONFIDENCE", rid,
            f"confidence {record.get('confidence')!r} is not one of "
            + "/".join(CONFIDENCE_VALUES)))

    # A field key that is entirely ABSENT is a different, worse defect from a
    # field that is present but still says TBD: the first means the producer
    # does not implement this contract, the second is honest work in progress.
    absent = [f for f in CONTRACT_FIELDS if f not in record]
    if absent:
        findings.append(_finding(
            SEVERITY_ERROR, "MISSING_CONTRACT_FIELD", rid,
            "contract field(s) absent from the record entirely: " + ", ".join(absent),
            missing=absent))

    if not is_resolved(record.get("source"), "source"):
        findings.append(_finding(
            SEVERITY_ERROR, "MISSING_SOURCE_PROVENANCE", rid,
            "source carries no real document: an unsourced requirement cannot be "
            "re-derived, and section 32 forbids generating from unqualified prose"))

    for entry in _open_ambiguities(record):
        if not str(entry.get("resolution_or_question", "")).strip():
            findings.append(_finding(
                SEVERITY_ERROR, "AMBIGUITY_WITHOUT_RESOLUTION_OR_QUESTION", rid,
                "an ambiguity is recorded with neither a resolution nor an open "
                f"question: {entry.get('description')!r}"))
    for entry in (record.get("contradictions") or []):
        if not isinstance(entry, dict):
            continue
        sources = entry.get("conflicting_sources") or []
        if len(sources) < 2:
            findings.append(_finding(
                SEVERITY_ERROR, "CONTRADICTION_WITHOUT_CONFLICTING_SOURCES", rid,
                f"contradiction {entry.get('description')!r} names {len(sources)} "
                "source(s); a contradiction needs at least two disagreeing sources"))

    if declared == STATUS_AMBIGUOUS and not _open_ambiguities(record):
        findings.append(_finding(
            SEVERITY_ERROR, "STATUS_WITHOUT_SUPPORTING_RECORD", rid,
            "status is AMBIGUOUS but no ambiguity is recorded, so nothing says "
            "what is ambiguous or what would resolve it"))
    if declared == STATUS_CONTRADICTORY and not (record.get("contradictions") or []):
        findings.append(_finding(
            SEVERITY_ERROR, "STATUS_WITHOUT_SUPPORTING_RECORD", rid,
            "status is CONTRADICTORY but no contradiction is recorded, so nothing "
            "names the sources a human is being asked to arbitrate between"))

    derived, reason = derive_status(record)
    if declared in REQUIREMENT_STATUSES and declared != derived:
        if declared == STATUS_COMPLETE:
            findings.append(_finding(
                SEVERITY_ERROR, "STATUS_OVERCLAIMED", rid,
                f"status says COMPLETE but the record's own content derives "
                f"{derived}: {reason}",
                derived_status=derived))
        elif derived in (STATUS_CONTRADICTORY, STATUS_AMBIGUOUS) and \
                declared not in (STATUS_CONTRADICTORY, STATUS_AMBIGUOUS):
            findings.append(_finding(
                SEVERITY_ERROR, "UNRESOLVED_BLOCKER_HIDDEN", rid,
                f"status says {declared} while an unresolved "
                f"{'contradiction' if derived == STATUS_CONTRADICTORY else 'ambiguity'} "
                f"is on file, which derives {derived}: {reason}",
                derived_status=derived))
        else:
            findings.append(_finding(
                SEVERITY_WARNING, "STATUS_DISAGREES_WITH_CONTENT", rid,
                f"status says {declared} but the record's own content derives "
                f"{derived}: {reason}. Declaring a weaker status than the content "
                "supports is allowed, but the disagreement is reported rather than "
                "silently accepted.",
                derived_status=derived))

    if declared == STATUS_UNKNOWN:
        findings.append(_finding(
            SEVERITY_WARNING, "UNKNOWN_STATUS_IS_A_VISIBLE_GAP", rid,
            "status UNKNOWN: this requirement stays visible as a gap and must not "
            "feed a generator (section 32)."))

    # The older shape's UNSUPPORTED_BY_DUT rule, carried over unchanged so a
    # record that migrates to the contract shape does not lose it.
    if record.get("support_status") == "UNSUPPORTED_BY_DUT" and \
            not is_resolved(record.get("design_evidence"), "design_evidence"):
        findings.append(_finding(
            SEVERITY_ERROR, "UNSUPPORTED_WITHOUT_DESIGN_EVIDENCE", rid,
            "support_status is UNSUPPORTED_BY_DUT with no design_evidence"))

    return findings


def analyze_requirement_contract_set(records: Sequence[dict]) -> dict:
    """Analyze every contract-shaped record in `records`, plus the one check
    that only exists across a set: duplicate requirement ids. Returns
    {"findings": [...], "status_counts": {...}, "analyzed": n}."""
    findings: List[dict] = []
    seen: Dict[Any, int] = {}
    counts = {s: 0 for s in REQUIREMENT_STATUSES}
    counts["INVALID"] = 0
    analyzed = 0

    for record in records:
        if not declares_contract_shape(record):
            continue
        analyzed += 1
        findings.extend(analyze_requirement_contract(record))
        declared = record.get("status")
        counts[declared if declared in counts else "INVALID"] += 1
        rid = record.get("requirement_id")
        seen[rid] = seen.get(rid, 0) + 1

    for rid, n in seen.items():
        if n > 1:
            findings.append(_finding(
                SEVERITY_ERROR, "DUPLICATE_REQUIREMENT_ID", rid,
                f"requirement_id {rid!r} appears {n} times; requirement identity "
                "must be unique for traceability to mean anything"))

    return {"analyzed": analyzed, "status_counts": counts, "findings": findings}


def downstream_consumable(record: dict) -> Tuple[bool, str]:
    """May a generator (vPlan writer, scenario planner, checker/coverage
    generator) build from this requirement? Returns (ok, reason).

    Only COMPLETE with zero ERROR findings qualifies. This is the decision the
    contract exists to make: section 184 asks downstream generators to consume
    structured IR instead of reinterpreting prose, and section 32 forbids
    turning ambiguous prose into generated verification code."""
    errors = [f for f in analyze_requirement_contract(record)
              if f["severity"] == SEVERITY_ERROR]
    if errors:
        return False, ("record has %d ERROR finding(s): %s"
                       % (len(errors), ", ".join(f["code"] for f in errors)))
    if record.get("status") != STATUS_COMPLETE:
        return False, (f"status is {record.get('status')} "
                       f"({STATUS_DEFINITIONS.get(record.get('status'), 'unrecognised')}); "
                       "only COMPLETE may feed a generator")
    return True, "status COMPLETE with no ERROR findings"


# --------------------------------------------------------------------------
# Dataclass
# --------------------------------------------------------------------------

@dataclass
class RequirementContract:
    """Section 184's fifteen fields as a real dataclass, in the document's own
    order. `ambiguities`/`contradictions`/`support_status`/`design_evidence`/
    `notes` are carriers for the detection output and for the older shape's
    orthogonal DUT-support question -- not part of the fifteen."""
    requirement_id: str
    source: Dict[str, Any]
    feature: str
    protocol: str
    configuration: str
    precondition: str
    stimulus: str
    expected_result: str
    observability: str
    checker: str
    coverage_intent: str
    priority: str
    criticality: str
    confidence: str
    status: str
    ambiguities: List[Dict[str, Any]] = field(default_factory=list)
    contradictions: List[Dict[str, Any]] = field(default_factory=list)
    support_status: Optional[str] = None
    design_evidence: Optional[str] = None
    notes: Optional[str] = None
    contract_schema_version: str = CONTRACT_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, record: dict, validate: bool = True) -> "RequirementContract":
        """Build from a record. Validates against the schema first by default:
        a RequirementContract instance must never exist for content that did
        not validate, or downstream code gains a false guarantee."""
        if validate:
            validate_requirement_contract(record)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in record.items() if k in known})

    def to_dict(self) -> dict:
        """Deterministic key order (contract_schema_version, then the fifteen
        in document order, then the carriers), matching env_manifest.py's
        diffability convention -- never sort_keys."""
        d = asdict(self)
        order = (["contract_schema_version"] + list(CONTRACT_FIELDS)
                 + ["ambiguities", "contradictions", "support_status",
                    "design_evidence", "notes"])
        return {k: d[k] for k in order if d.get(k) is not None or k in CONTRACT_FIELDS}

    def analyze(self) -> List[dict]:
        return analyze_requirement_contract(self.to_dict())

    def derived_status(self) -> Tuple[str, str]:
        return derive_status(self.to_dict())

    def is_downstream_consumable(self) -> Tuple[bool, str]:
        return downstream_consumable(self.to_dict())


# --------------------------------------------------------------------------
# CLI (same execute_verb convention as power_intent / golden_scenario)
# --------------------------------------------------------------------------

def execute_verb(requirements_path: str, as_json: bool = False,
                 fail_on_error: bool = False) -> Tuple[str, int]:
    """Analyze a requirements document. Exit codes: 0 clean, 1 ERROR findings
    present (or, with --fail-on-error, any finding), 2 nothing in the contract
    shape to analyze -- never PASS on an empty analysis."""
    try:
        doc = json.loads(Path(requirements_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return (json.dumps({"status": "NOT_AVAILABLE", "reason": str(exc)})
                if as_json else f"NOT_AVAILABLE: {exc}"), 2

    records = doc.get("requirements", []) if isinstance(doc, dict) else doc
    result = analyze_requirement_contract_set(records)
    result["source"] = str(requirements_path)

    errors = [f for f in result["findings"] if f["severity"] == SEVERITY_ERROR]
    if result["analyzed"] == 0:
        result["status"] = "NOT_AVAILABLE"
        result["reason"] = ("no requirement record declares contract_schema_version; "
                            "nothing to analyze against the canonical contract")
        code = 2
    elif errors or (fail_on_error and result["findings"]):
        result["status"] = "FAIL"
        code = 1
    else:
        result["status"] = "PASS"
        code = 0

    if as_json:
        return json.dumps(result, indent=2), code
    lines = [f"requirement-contract: {result['status']} "
             f"({result['analyzed']} contract-shaped requirement(s) analyzed)"]
    if result.get("reason"):
        lines.append(f"  reason: {result['reason']}")
    for s in REQUIREMENT_STATUSES:
        if result["status_counts"].get(s):
            lines.append(f"  {s}: {result['status_counts'][s]}")
    for f in result["findings"]:
        lines.append(f"  [{f['severity']}] {f['code']} ({f['requirement_id']}): {f['detail']}")
    return "\n".join(lines), code


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin shell
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.requirement_contract",
        description="Validate requirement records against spec section 184's "
                    "Canonical Requirement Contract and its COMPLETE/PARTIAL/"
                    "AMBIGUOUS/CONTRADICTORY/UNKNOWN status vocabulary.")
    ap.add_argument("--requirements", required=True,
                    help="JSON file with a top-level `requirements` list.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-error", action="store_true",
                    help="Also fail on WARNING findings, not only ERROR.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.requirements, as_json=a.json, fail_on_error=a.fail_on_error)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
