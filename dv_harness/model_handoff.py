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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import governance_registry as _governance_registry
from . import md_kv_codec as _codec
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


#: Canonical statement of what each list authorizes (GAP-V2-013). Carried
#: verbatim into every handoff's RETURN_CONTRACT so the target model is told
#: the same rule `model_result.validate_result()` enforces.
DEFAULT_RETURN_CONTRACT = (
    "L5DGVA_MODEL_RESULT_V1 markdown, same TASK_ID; FILES_REFERENCED and "
    "path citations in EVIDENCE_REFS may cite only ALLOWED_FILES and "
    "INPUT_EVIDENCE_REFS (never FORBIDDEN_FILES); RETURNED_ARTIFACTS may "
    "name only ALLOWED_FILES or this result document itself"
)

_LINE_SUFFIX_RE = _re.compile(r":\d+(?:-\d+)?$")


def _strip_line_suffix(ref: str) -> str:
    return _LINE_SUFFIX_RE.sub("", ref)


_DRIVE_RE = _re.compile(r"^[A-Za-z]:")
_BAD_COMPONENT_CHARS = frozenset('<>:"|?*\x00')


def canonical_repo_path(ref: str) -> Optional[str]:
    """Canonical root-relative POSIX form of a repository path, or None when
    the path is unsafe (REVIEW-003 N1/N5). Scope comparison must always be
    done on THIS form, never on the raw string: `dv_harness/../README.md`
    and `dv_harness/model_result.py/../../dv_harness/engine.py` begin with an
    allowed prefix lexically but denote something else.

    Rejected (None): empty, NUL/other invalid Windows filename characters in
    a component (incl. NTFS `name:stream`), absolute paths (leading `/`,
    `\\`, drive letter, UNC), and any path that escapes the root after `.`/
    `..` collapsing. Windows semantics are applied conservatively: trailing
    dots/spaces of a component are dropped (`engine.py.` == `engine.py`
    there), which can only make a classification stricter for forbidden
    paths; case is compared literally here and re-checked against the real
    filesystem identity by `real_repo_relative()`."""
    s = str(ref).strip().replace("\\", "/")
    if not s or _DRIVE_RE.match(s) or s.startswith("/"):
        return None
    stack: List[str] = []
    for part in s.split("/"):
        part = part.rstrip(". ") if part not in (".", "..") else part
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                return None
            stack.pop()
            continue
        if any(c in _BAD_COMPONENT_CHARS for c in part):
            return None
        stack.append(part)
    return "/".join(stack) if stack else None


def real_repo_relative(root: Path, canonical: str) -> Optional[str]:
    """For a path that EXISTS under `root`: its true-cased, symlink-resolved,
    root-relative POSIX form (defeats case/short-name/symlink aliases of a
    forbidden file). Returns "" if the real target lies outside `root`
    (symlink escape) and None if the path does not exist."""
    p = Path(root) / canonical
    if not p.exists():
        return None
    try:
        return p.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return ""


def canonical_boundary(scope: TaskBoundary) -> TaskBoundary:
    """`scope` with every declared path canonicalized. An unsafe ALLOWED
    entry is dropped (nothing is authorized by it); an unsafe FORBIDDEN entry
    cannot match any in-root path and is dropped."""
    def canon(paths: Sequence[str]) -> Tuple[str, ...]:
        out: List[str] = []
        for p in paths:
            c = canonical_repo_path(_strip_line_suffix(p))
            if c is not None and c not in out:
                out.append(c)
        return tuple(out)
    return TaskBoundary(task_id=scope.task_id, allowed_path_prefixes=canon(scope.allowed_path_prefixes),
                        forbidden_paths=canon(scope.forbidden_paths), require_new_file=scope.require_new_file)


def unsafe_declarations(scope: TaskBoundary, input_evidence_refs: Sequence[str]) -> List[Dict[str, str]]:
    """Boundary declarations that are unsafe (absolute / escaping / invalid
    characters) OR not already in canonical form (`..`/`.` segments, doubled
    slashes, trailing dots). They are rejected rather than silently rewritten:
    a reader of the handoff must see exactly the path that is enforced."""
    bad: List[Dict[str, str]] = []
    for name, values in (("ALLOWED_FILES", scope.allowed_path_prefixes), ("FORBIDDEN_FILES", scope.forbidden_paths),
                         ("INPUT_EVIDENCE_REFS", input_evidence_refs)):
        for v in values:
            declared = _strip_line_suffix(str(v)).strip().replace("\\", "/").rstrip("/")
            if canonical_repo_path(declared) != declared:
                bad.append({"field": name, "value": v})
    return bad


def read_boundary(handoff: "ModelHandoffV1") -> TaskBoundary:
    """READ authorization = ALLOWED_FILES + INPUT_EVIDENCE_REFS (the files
    the handoff explicitly shares with the model), minus FORBIDDEN_FILES
    (forbidden always wins). ALLOWED_FILES alone remains the MODIFICATION
    boundary. Authorization comes only from these explicit declarations --
    never from a file merely being relevant to the task. Every declared path
    is canonicalized first (N5)."""
    base = canonical_boundary(handoff.scope)
    allowed = list(base.allowed_path_prefixes)
    for ref in handoff.input_evidence_refs:
        p = canonical_repo_path(_strip_line_suffix(ref))
        if p is not None and p not in allowed:
            allowed.append(p)
    return TaskBoundary(
        task_id=handoff.scope.task_id,
        allowed_path_prefixes=tuple(allowed),
        forbidden_paths=base.forbidden_paths,
        require_new_file=False,
    )


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
    return_contract: str = DEFAULT_RETURN_CONTRACT

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
    return_contract: str = DEFAULT_RETURN_CONTRACT,
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
    # GAP-V2-010 (R4): the identity inside SCOPE must agree with TASK_ID at
    # construction time too, not only when a stored document is re-parsed.
    if scope.task_id != str(task_id):
        raise HandoffBuildError("TASK_ID_SCOPE_MISMATCH",
                                {"task_id": str(task_id), "scope_task_id": scope.task_id})
    # REVIEW-003 N5: every boundary declaration must be a safe, canonical
    # repository path -- traversal-bearing declarations are rejected, never
    # silently normalized into a different authorization.
    bad = unsafe_declarations(scope, input_evidence_refs)
    if bad:
        raise HandoffBuildError("UNSAFE_PATH_DECLARATION", {"task_id": str(task_id), "declarations": bad})
    # GAP-V2-013: a handoff that both shares a file as input evidence and
    # forbids it contradicts itself -- rejected at build time, on CANONICAL
    # paths (`a.py/../engine.py` is `engine.py`).
    from .task_boundary_conformance import classify_path, CLASS_FORBIDDEN
    canon_scope = canonical_boundary(scope)
    contradictory = [r for r in input_evidence_refs
                     if classify_path(canonical_repo_path(_strip_line_suffix(r)), canon_scope, "MODIFIED") == CLASS_FORBIDDEN]
    if contradictory:
        raise HandoffBuildError("INPUT_EVIDENCE_REFS_FORBIDDEN",
                                {"task_id": str(task_id), "refs": contradictory})

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
    return _codec.render_document("L5DGVA_MODEL_HANDOFF_V1", _FIELD_ORDER, values, _LIST_FIELDS)


class HandoffParseError(ValueError):
    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def from_markdown(text: str) -> ModelHandoffV1:
    """Real, strict parser -- the exact inverse of `to_markdown()`. Every
    required field must be present; a missing one is a real
    `HandoffParseError`, never a silently-defaulted value."""
    try:
        sections, escaped = _codec.split_sections(text, _FIELD_ORDER, "L5DGVA_MODEL_HANDOFF_V1")
        missing = [f for f in _FIELD_ORDER if f not in sections]
        if missing:
            raise HandoffParseError("MISSING_REQUIRED_FIELDS", {"missing": missing})
        values = {
            f: (_codec.parse_list(sections[f], escaped) if f in _LIST_FIELDS
                else _codec.parse_scalar(sections[f], escaped))
            for f in _FIELD_ORDER
        }
    except _codec.MdKvError as exc:
        raise HandoffParseError("NOT_A_HANDOFF_DOCUMENT" if exc.reason == "NOT_THIS_DOCUMENT" else exc.reason, exc.detail) from exc

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
    scope_match = _re.fullmatch(r"task_id=(.*); require_new_file=(True|False)", scope_raw)
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
    bad = unsafe_declarations(scope, values["INPUT_EVIDENCE_REFS"] or ())
    if bad:
        raise HandoffParseError("UNSAFE_PATH_DECLARATION", {"declarations": bad})

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
