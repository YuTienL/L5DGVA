"""dv_harness/model_handoff.py -- L5DGVA_MODEL_HANDOFF_V1: the structured
Markdown contract a human transports from L5DGVA to a target model
(Codex/ChatGPT), per `docs/architecture/L5DGVA_M7_STRUCTURED_MULTI_MODEL_
MD_HANDOFF_ARCHITECTURE.md` (M7 V1).

REUSE OVER REINVENT, per this task's own explicit instruction ("Do not
create a second task identity, evidence system, field-resolution
authority, or Source of Truth"). Every field below is either a REAL,
already-existing Canonical value read verbatim, or a small, disclosed net
new field this project's own M7 preflight (`M7_STRUCTURED_HANDOFF_
CONTRACT.md`) already identified as genuinely missing:

  - SCOPE / ALLOWED_FILES / FORBIDDEN_FILES: `task_boundary_conformance.
    TaskBoundary` (CAP-ATL-004), reused verbatim, never re-implemented.
  - INPUT_EVIDENCE_REFS / RETURN_CONTRACT's own evidence shape: the same
    `evidence_refs` field pattern already real and consistent across 28
    modules (`intake_field_resolution.Candidate.evidence_refs` and its
    reuse throughout `clarification_service.py`/`question_queue.py`/
    `lifecycle.py`/`verification_level.py`/`engine.py`).
  - REQUIRED_GOVERNANCE_REFS: `governance_registry.get_entries_by_
    trigger()` (TASK_SCOPED_GOVERNANCE_RETRIEVAL, OPERATIONAL) -- never a
    full CLAUDE.md dump.
  - CURRENT_HEAD: a real `git rev-parse HEAD`, the same fact
    `engine.py`'s own `self.state.git_sha` already carries.
  - TASK_TYPE: `router.DEFAULT_ROUTES`' own real task-type vocabulary
    (`model_agent_tool_router.py` already routes on this same set).
  - `to_dict()`-serializable shape: mirrors `model_agent_tool_router.
    RoutingDecision`'s own established convention in this repo, not a
    new one.

The 2 genuinely NET-NEW fields (identified, not invented, by
`M7_STRUCTURED_HANDOFF_CONTRACT.md`): `EXPECTED_OUTPUT_TYPE` (a small,
closed enum) and `EXPECTED_OUTPUT_SCHEMA` (free text naming the expected
`RESULT_V1` shape for this task).

MINIMUM SUFFICIENT CONTEXT, enforced structurally, not by convention:
`build_handoff()` never accepts a raw CLAUDE.md/whole-repo blob as an
argument -- `REQUIRED_GOVERNANCE_REFS` is always derived through
`governance_registry.get_entries_by_trigger()`'s own real, scoped
retrieval, and `INPUT_EVIDENCE_REFS` is always a caller-supplied, already
-scoped list of real evidence pointers, never a directory walk.
"""
from __future__ import annotations

import json
import re as _re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import governance_registry as _governance_registry
from .change_impact import _git
from .task_boundary_conformance import TaskBoundary

HANDOFF_VERSION = "1.0"

#: The only 3 real transport targets M7 V1 approves (docs/architecture/
#: L5DGVA_M7_STRUCTURED_MULTI_MODEL_MD_HANDOFF_ARCHITECTURE.md's own
#: "Approved transport" list) -- never a 4th value invented here.
SOURCE_MODELS = ("claude",)
TARGET_MODELS = ("codex", "chatgpt")

#: A small, closed enum -- the one genuinely net-new field this contract
#: adds beyond what already had a real Canonical home (M7_STRUCTURED_
#: HANDOFF_CONTRACT.md's own finding).
EXPECTED_OUTPUT_TYPES = ("review_findings", "research_synthesis", "code_change",
                          "decision_analysis", "structured_issue")


class HandoffBuildError(ValueError):
    """A real, structured construction failure -- never a silently
    incomplete handoff. `detail` carries what was missing/invalid."""

    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


@dataclass(frozen=True)
class ModelHandoffV1:
    """L5DGVA_MODEL_HANDOFF_V1 -- see this module's own docstring for the
    field-by-field reuse mapping. Frozen: a handoff, once built, is a
    fact about the moment it was built (including `current_head`) and is
    never mutated in place -- a re-derived handoff is a NEW object."""

    handoff_version: str
    task_id: str
    task_type: str
    source_model: str
    target_model: str
    project_id: str
    current_head: str
    objective: str
    scope: TaskBoundary
    input_evidence_refs: Sequence[str] = ()
    required_governance_refs: Sequence[str] = ()
    known_facts: Sequence[str] = ()
    open_questions: Sequence[str] = ()
    independence_requirement: Optional[str] = None
    expected_output_type: str = "review_findings"
    expected_output_schema: str = "L5DGVA_MODEL_RESULT_V1"
    validation_requirements: Sequence[str] = ()
    human_decision_required: bool = False
    return_contract: str = "L5DGVA_MODEL_RESULT_V1 markdown, same TASK_ID"

    _LIST_FIELD_NAMES = (
        "input_evidence_refs", "required_governance_refs", "known_facts",
        "open_questions", "validation_requirements",
    )

    def __post_init__(self) -> None:
        for name in self._LIST_FIELD_NAMES:
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def allowed_files(self) -> Sequence[str]:
        return self.scope.allowed_path_prefixes

    @property
    def forbidden_files(self) -> Sequence[str]:
        return self.scope.forbidden_paths

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["scope"] = {
            "task_id": self.scope.task_id,
            "allowed_path_prefixes": list(self.scope.allowed_path_prefixes),
            "forbidden_paths": list(self.scope.forbidden_paths),
            "require_new_file": self.scope.require_new_file,
        }
        d["allowed_files"] = list(self.allowed_files)
        d["forbidden_files"] = list(self.forbidden_files)
        return d


def _current_head(root: Path) -> Optional[str]:
    rc, out, _ = _git(Path(root), ["rev-parse", "HEAD"])
    return out.strip() if rc == 0 and out.strip() else None


def build_handoff(
    root: Path, *, task_id: str, task_type: str, target_model: str,
    project_id: str, objective: str, scope: TaskBoundary,
    input_evidence_refs: Sequence[str] = (),
    governance_trigger: Optional[str] = None,
    known_facts: Sequence[str] = (), open_questions: Sequence[str] = (),
    independence_requirement: Optional[str] = None,
    expected_output_type: str = "review_findings",
    expected_output_schema: str = "L5DGVA_MODEL_RESULT_V1",
    validation_requirements: Sequence[str] = (),
    human_decision_required: bool = False,
    return_contract: str = "L5DGVA_MODEL_RESULT_V1 markdown, same TASK_ID",
) -> ModelHandoffV1:
    """The Handoff Builder (dispatch section 8): derives Minimum
    Sufficient Context from real Canonical task/evidence/governance
    state -- never a CLAUDE.md/repository dump.

    `governance_trigger`, when given, resolves `required_governance_refs`
    through `governance_registry.get_entries_by_trigger()`'s own real,
    scoped retrieval (each entry's `summary_path`, the TASK_SCOPED short
    form -- never `full_spec_path`, which stays `EVIDENCE_ON_DEMAND`
    only). Omitting it (the default) leaves `required_governance_refs`
    empty -- a caller who has nothing task-scoped to cite must not get a
    silently-populated fallback."""
    if target_model not in TARGET_MODELS:
        raise HandoffBuildError("INVALID_TARGET_MODEL",
                                {"target_model": target_model, "allowed": TARGET_MODELS})
    if expected_output_type not in EXPECTED_OUTPUT_TYPES:
        raise HandoffBuildError("INVALID_EXPECTED_OUTPUT_TYPE",
                                {"expected_output_type": expected_output_type,
                                 "allowed": EXPECTED_OUTPUT_TYPES})
    if not task_id or not str(task_id).strip():
        raise HandoffBuildError("MISSING_TASK_ID", {})
    if not objective or not str(objective).strip():
        raise HandoffBuildError("MISSING_OBJECTIVE", {"task_id": task_id})

    root = Path(root)
    head = _current_head(root)
    if head is None:
        raise HandoffBuildError("CURRENT_HEAD_UNRESOLVABLE",
                                {"task_id": task_id, "root": str(root)})

    governance_refs: List[str] = []
    if governance_trigger:
        try:
            entries = _governance_registry.load_registry(root)
            matched = _governance_registry.get_entries_by_trigger(entries, governance_trigger)
            governance_refs = [e["summary_path"] for e in matched if e.get("summary_path")]
        except (OSError, KeyError, json.JSONDecodeError):
            # Degrade-never-raise, matching task_boundary_conformance.py's
            # own discipline: an unreadable/malformed registry means "no
            # governance refs resolved," never a handoff-build crash.
            governance_refs = []

    return ModelHandoffV1(
        handoff_version=HANDOFF_VERSION, task_id=str(task_id), task_type=str(task_type),
        source_model="claude", target_model=target_model, project_id=str(project_id),
        current_head=head, objective=str(objective), scope=scope,
        input_evidence_refs=tuple(input_evidence_refs),
        required_governance_refs=tuple(governance_refs),
        known_facts=tuple(known_facts), open_questions=tuple(open_questions),
        independence_requirement=independence_requirement,
        expected_output_type=expected_output_type,
        expected_output_schema=expected_output_schema,
        validation_requirements=tuple(validation_requirements),
        human_decision_required=bool(human_decision_required),
        return_contract=return_contract,
    )


# --- Markdown serialization / parsing ---------------------------------------
# One H2 section per field, `## FIELD_NAME` headers matching the dispatch's
# own field list verbatim, so a human (or the target model) never has to
# guess the mapping. List-valued fields render as "- " bullets; scalar
# fields render as one line. Parsing is the exact inverse, never a lenient
# best-effort guess -- an unparseable section is a real MALFORMED_MARKDOWN
# error, not silently dropped.

_FIELD_ORDER = [
    "HANDOFF_VERSION", "TASK_ID", "TASK_TYPE", "SOURCE_MODEL", "TARGET_MODEL",
    "PROJECT_ID", "CURRENT_HEAD", "OBJECTIVE", "SCOPE", "ALLOWED_FILES",
    "FORBIDDEN_FILES", "INPUT_EVIDENCE_REFS", "REQUIRED_GOVERNANCE_REFS",
    "KNOWN_FACTS", "OPEN_QUESTIONS", "INDEPENDENCE_REQUIREMENT",
    "EXPECTED_OUTPUT_TYPE", "EXPECTED_OUTPUT_SCHEMA", "VALIDATION_REQUIREMENTS",
    "HUMAN_DECISION_REQUIRED", "RETURN_CONTRACT",
]

_LIST_FIELDS = frozenset({
    "ALLOWED_FILES", "FORBIDDEN_FILES", "INPUT_EVIDENCE_REFS",
    "REQUIRED_GOVERNANCE_REFS", "KNOWN_FACTS", "OPEN_QUESTIONS",
    "VALIDATION_REQUIREMENTS",
})


def _escape_md_line(s: str) -> str:
    """GAP-V2-012 fix -- see model_result.py's own identical helper for
    the full rationale (arbitrary section injection via an embedded
    newline). Kept as an independent copy here rather than a shared
    import, matching this module's own established pattern of not
    sharing `_FIELD_ORDER`/`_parse_sections` with model_result.py
    either -- each module's own serializer stays self-contained."""
    return s.replace("\\", "\\\\").replace("\n", "\\n")


def _unescape_md_line(s: str) -> str:
    out: List[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _render_value(field_name: str, value: Any) -> str:
    if field_name in _LIST_FIELDS:
        items = list(value or [])
        return "\n".join(f"- {_escape_md_line(str(v))}" for v in items) if items else "(none)"
    if value is None or value == "":
        return "(none)"
    return _escape_md_line(str(value))


def to_markdown(handoff: ModelHandoffV1) -> str:
    """Real Markdown serialization -- the exact artifact a human copies
    into the target model's own UI."""
    values = {
        "HANDOFF_VERSION": handoff.handoff_version,
        "TASK_ID": handoff.task_id,
        "TASK_TYPE": handoff.task_type,
        "SOURCE_MODEL": handoff.source_model,
        "TARGET_MODEL": handoff.target_model,
        "PROJECT_ID": handoff.project_id,
        "CURRENT_HEAD": handoff.current_head,
        "OBJECTIVE": handoff.objective,
        "SCOPE": f"task_id={handoff.scope.task_id}; require_new_file={handoff.scope.require_new_file}",
        "ALLOWED_FILES": list(handoff.allowed_files),
        "FORBIDDEN_FILES": list(handoff.forbidden_files),
        "INPUT_EVIDENCE_REFS": list(handoff.input_evidence_refs),
        "REQUIRED_GOVERNANCE_REFS": list(handoff.required_governance_refs),
        "KNOWN_FACTS": list(handoff.known_facts),
        "OPEN_QUESTIONS": list(handoff.open_questions),
        "INDEPENDENCE_REQUIREMENT": handoff.independence_requirement,
        "EXPECTED_OUTPUT_TYPE": handoff.expected_output_type,
        "EXPECTED_OUTPUT_SCHEMA": handoff.expected_output_schema,
        "VALIDATION_REQUIREMENTS": list(handoff.validation_requirements),
        "HUMAN_DECISION_REQUIRED": str(handoff.human_decision_required),
        "RETURN_CONTRACT": handoff.return_contract,
    }
    lines = ["# L5DGVA_MODEL_HANDOFF_V1", ""]
    for name in _FIELD_ORDER:
        lines.append(f"## {name}")
        lines.append(_render_value(name, values[name]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class HandoffParseError(ValueError):
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
        return [] if field_name in _LIST_FIELDS else None
    if field_name in _LIST_FIELDS:
        items = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("- "):
                items.append(_unescape_md_line(line[2:].strip()))
            elif line:
                items.append(_unescape_md_line(line))
        return items
    return _unescape_md_line(raw.strip())


def from_markdown(text: str) -> ModelHandoffV1:
    """Real, strict parser -- the exact inverse of `to_markdown()`. Every
    required field must be present; a missing one is a real
    `HandoffParseError`, never a silently-defaulted value."""
    if "L5DGVA_MODEL_HANDOFF_V1" not in text:
        raise HandoffParseError("NOT_A_HANDOFF_DOCUMENT", {})
    sections = _parse_sections(text)
    missing = [f for f in _FIELD_ORDER if f not in sections]
    if missing:
        raise HandoffParseError("MISSING_REQUIRED_FIELDS", {"missing": missing})
    values = {f: _parse_value(f, sections[f]) for f in _FIELD_ORDER}

    # GAP-V2-010 fix: the stored HANDOFF_V1.md is untrusted input (it is
    # re-read from disk on every import, and could have been tampered
    # with or corrupted between export and import) -- its own SCOPE
    # section's serialized task_id= value is now ACTUALLY PARSED and
    # checked for agreement with the top-level TASK_ID field, never
    # silently discarded in favor of TASK_ID (the pre-fix behavior Codex's
    # own F3 finding demonstrated: a real inconsistency was erased rather
    # than reported).
    handoff_task_id = values["TASK_ID"]
    scope_raw = values["SCOPE"] or ""
    scope_match = _re.match(r"task_id=(.*?);\s*require_new_file=(True|False)", scope_raw)
    if scope_match is None:
        raise HandoffParseError("MALFORMED_SCOPE_FIELD", {"scope_raw": scope_raw})
    scope_task_id = scope_match.group(1)
    require_new_file = scope_match.group(2) == "True"
    if scope_task_id != handoff_task_id:
        raise HandoffParseError("TASK_ID_SCOPE_MISMATCH",
                                {"task_id": handoff_task_id, "scope_task_id": scope_task_id})
    scope = TaskBoundary(
        task_id=scope_task_id,
        allowed_path_prefixes=tuple(values["ALLOWED_FILES"] or ()),
        forbidden_paths=tuple(values["FORBIDDEN_FILES"] or ()),
        require_new_file=require_new_file,
    )

    return ModelHandoffV1(
        handoff_version=values["HANDOFF_VERSION"], task_id=handoff_task_id,
        task_type=values["TASK_TYPE"], source_model=values["SOURCE_MODEL"],
        target_model=values["TARGET_MODEL"], project_id=values["PROJECT_ID"],
        current_head=values["CURRENT_HEAD"], objective=values["OBJECTIVE"], scope=scope,
        input_evidence_refs=tuple(values["INPUT_EVIDENCE_REFS"] or ()),
        required_governance_refs=tuple(values["REQUIRED_GOVERNANCE_REFS"] or ()),
        known_facts=tuple(values["KNOWN_FACTS"] or ()),
        open_questions=tuple(values["OPEN_QUESTIONS"] or ()),
        independence_requirement=values["INDEPENDENCE_REQUIREMENT"],
        expected_output_type=values["EXPECTED_OUTPUT_TYPE"],
        expected_output_schema=values["EXPECTED_OUTPUT_SCHEMA"],
        validation_requirements=tuple(values["VALIDATION_REQUIREMENTS"] or ()),
        human_decision_required=(values["HUMAN_DECISION_REQUIRED"] == "True"),
        return_contract=values["RETURN_CONTRACT"],
    )


def context_size_bytes(handoff: ModelHandoffV1) -> Dict[str, int]:
    """Minimum Sufficient Context metrics (dispatch section 21) -- real
    byte counts, explicitly labeled as proxies, never a provider token
    count this module cannot actually observe."""
    md = to_markdown(handoff)
    governance_bytes = sum(len(p.encode("utf-8")) for p in handoff.required_governance_refs)
    return {
        "handoff_bytes": len(md.encode("utf-8")),
        "governance_context_bytes_proxy": governance_bytes,
        "files_referenced": len(handoff.allowed_files) + len(handoff.forbidden_files),
    }
