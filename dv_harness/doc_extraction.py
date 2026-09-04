# NOTICE (added during industrial-grade audit, 2026-08-28; scope narrowed
# 2026-09-04): the pipeline half of this module is still orphaned -- no stage in
# dv_harness/engine.py and no .claude/agents/*.md profile invokes DocumentIndex,
# needs_extract(), register() or normalize_register_record(), so any
# WORKFLOW_MANIFEST.json capability flag referencing document extraction remains
# aspirational rather than a statement that this code runs in the graph. See
# CHANGELOG_v0_to_v50.md and the industrial-grade-deep-audit findings.
#
# What changed on 2026-09-04: build_research_evidence_card_skeleton() below gave
# sha256_file()/DocumentIndex/evidence_ref() their first real caller -- the
# `research-ingestion` skill (.claude/skills/research-ingestion/SKILL.md), the
# Stage-1 half of the Research-Capability Evolution master prompt. That caller is
# an agent following a skill, not an engine stage, and it is honest to say so:
# this module is now REACHED, not yet WIRED.
#
# This module does NOT extract text from any document. It never has: SUPPORTED is
# a suffix allowlist, not a parser inventory (CLAUDE.md's Context Budget section
# corrected a policy route that had assumed otherwise). Reading a document's
# CONTENT is done by the agent for research cards, and by
# dv_harness/vip_user_guide_distill.py (real pypdf) for VIP guides. Everything
# here is identity and provenance only.
from __future__ import annotations
from pathlib import Path
import hashlib, json, time, re
from datetime import datetime, timezone
from typing import Dict, Any, List

from .inference import CONFIDENCE_LEVELS, identify_gap

SUPPORTED = {".pdf",".docx",".txt",".md",".html",".htm",".csv",".xlsx",".xls",".sv",".v",".vh",".svh"}

# External technical literature only -- deliberately narrower than SUPPORTED.
# The RTL suffixes there (.sv/.v/.vh/.svh) and the spreadsheet/CSV ones are
# project design/data inputs; an .sv file arriving at research ingestion means
# the caller reached for the wrong path, which is worth an error rather than a
# ResearchEvidenceCard about a Verilog file.
RESEARCH_DOCUMENT_SUFFIXES = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}

_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
RESEARCH_EVIDENCE_CARD_SCHEMA_PATH = _SCHEMA_DIR / "research_evidence_card.schema.json"

RESEARCH_CARD_SCHEMA_VERSION = "1.0"
RESEARCH_CARD_INGESTION_VERSION = "1.0"

# The kind DocumentIndex rows carry for a document ingested as research
# literature, so a research document is distinguishable from a register/PHY
# document in the same index.
RESEARCH_DOCUMENT_INDEX_KIND = "research_document"

# The split that makes a half-filled card impossible to mistake for a finished
# one. MECHANICAL is everything build_research_evidence_card_skeleton() can
# derive from the file itself; LLM_AUTHORED is everything that requires actually
# reading the document. Together they must be exactly the schema's `required`
# list -- held to that by dv_harness_tests/test_research_evidence_card.py rather
# than by anyone remembering to update both.
RESEARCH_CARD_MECHANICAL_FIELDS = (
    "schema_version", "document_id", "title", "source", "document_type",
    "document_sha256", "document_path", "document_bytes", "document_suffix",
    "source_provenance", "ingestion_timestamp", "ingestion_version",
    "analysis_version",
)
RESEARCH_CARD_LLM_AUTHORED_FIELDS = (
    "authors", "date", "verification_domain", "problem_statement",
    "core_method", "architecture_pattern", "key_mechanisms", "inputs",
    "outputs", "ai_role", "deterministic_tool_role", "eda_tools",
    "feedback_loop", "quantitative_results", "limitations", "assumptions",
    "maturity", "production_relevance", "evidence_strength", "confidence",
    "claim_set", "candidate_l5_mapping", "related_prior_research",
    "contradictions",
)


class ResearchIngestionError(ValueError):
    """The supplied path cannot be ingested as external technical literature
    (missing, not a file, or not one of RESEARCH_DOCUMENT_SUFFIXES). Raised
    rather than returned so a skeleton is never built over a file the caller
    did not mean to hand in."""


class ResearchEvidenceCardValidationError(ValueError):
    """A ResearchEvidenceCard fails research_evidence_card.schema.json.
    Raised, not returned, matching every other schema-backed artifact in this
    package: a card that did not validate must never be filed under
    research/evidence_cards/ where a later synthesis pass would read it as
    settled evidence."""

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

class DocumentIndex:
    def __init__(self, project_root: Path):
        self.root=project_root.resolve()
        self.dir=self.root/".dv-harness"/"documents"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_file=self.dir/"document_index.json"
        if not self.index_file.exists():
            self.index_file.write_text("[]", encoding="utf-8")

    def load(self):
        return json.loads(self.index_file.read_text(encoding="utf-8"))

    def save(self, rows):
        self.index_file.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")

    def needs_extract(self, path: Path) -> bool:
        digest=sha256_file(path)
        for row in self.load():
            if row.get("path")==str(path.resolve()) and row.get("sha256")==digest:
                return False
        return True

    def register(self, path: Path, kind: str="generic", metadata: Dict[str,Any]|None=None):
        digest=sha256_file(path)
        rows=[r for r in self.load() if r.get("path")!=str(path.resolve())]
        rows.append({
            "path":str(path.resolve()),
            "name":path.name,
            "suffix":path.suffix.lower(),
            "sha256":digest,
            "kind":kind,
            "mtime":path.stat().st_mtime,
            "indexed_at":time.time(),
            "metadata":metadata or {}
        })
        self.save(rows)
        return rows[-1]

def normalize_register_record(record: Dict[str,Any]) -> Dict[str,Any]:
    keys=["document","version","page","section","register_name","address","bit_range",
          "field_name","access","reset_value","description","source_location"]
    return {k:record.get(k) for k in keys}

def evidence_ref(document: str, version: str, page: str, section: str, location: str=""):
    return {
        "document":document,
        "version":version,
        "page":page,
        "section":section,
        "source_location":location
    }


# --- ResearchEvidenceCard: mechanical identity/provenance half ---------------
#
# Master prompt sections 6-9. The division of labour here is the whole point:
# this code owns ONLY what a file hash and a filesystem stat can establish, and
# the `research-ingestion` skill owns everything that requires reading the
# document. Nothing below opens a document's content.


def _load_research_card_schema() -> Dict[str, Any]:
    return json.loads(RESEARCH_EVIDENCE_CARD_SCHEMA_PATH.read_text(encoding="utf-8"))


def assert_confidence_vocabulary_reused() -> None:
    """The card schema's confidence enum must be inference.CONFIDENCE_LEVELS
    plus UNKNOWN -- nothing more.

    The master prompt (section 10) forbids a Research Inference Engine, and this
    repo already carries a real 3-vs-4-level confidence ambiguity between
    inference.py ("HIGH"/"MEDIUM"/"LOW") and memory_router.py's
    ENGINEERING_ADMISSION_CONFIDENCE_LEVELS (which also accepts "CONFIRMED").
    Adding a third vocabulary here would make that worse, so the schema borrows
    the existing one and this function makes the borrow checkable instead of a
    claim in a description. UNKNOWN is admitted as "not yet assessed" -- it never
    orders against the other three -- and is not counted as a level.
    """
    schema = _load_research_card_schema()
    enum = list(schema["$defs"]["confidence_level"]["enum"])
    scored = [v for v in enum if v != "UNKNOWN"]
    if scored != list(CONFIDENCE_LEVELS) or "UNKNOWN" not in enum:
        raise ResearchEvidenceCardValidationError(
            "research_evidence_card.schema.json's confidence_level enum "
            f"{enum} is not inference.CONFIDENCE_LEVELS {list(CONFIDENCE_LEVELS)} "
            "plus UNKNOWN -- a fourth confidence vocabulary was introduced."
        )


def research_card_required_fields() -> List[str]:
    """The schema's own `required` list, read from the schema file rather than
    duplicated here -- so this module cannot drift from the contract it claims
    to build against."""
    return list(_load_research_card_schema()["required"])


def prior_research_relations() -> List[str]:
    """The card schema's own `prior_research_link.relation` enum, in schema
    order -- master prompt section 28's relation labels.

    Read from the schema for the same reason research_card_required_fields()
    is: a cross-card comparator (capability_evolution.compare_evidence_cards())
    must speak THIS vocabulary and not a second one of its own. Section 28
    names these seven once; giving a second module its own tuple of them is how
    two vocabularies that agree today stop agreeing later.
    """
    schema = _load_research_card_schema()
    return list(schema["$defs"]["prior_research_link"]["properties"]["relation"]["enum"])


def validate_research_evidence_card(card: Dict[str, Any]) -> None:
    """Validate `card` against research_evidence_card.schema.json.

    Raises ResearchEvidenceCardValidationError listing every violation with its
    JSON path. A freshly built skeleton is EXPECTED to fail this -- see
    research_card_missing_fields() for the field-level view a reader works from.
    """
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise ResearchEvidenceCardValidationError(
            "jsonschema package is not installed; cannot validate against "
            f"{RESEARCH_EVIDENCE_CARD_SCHEMA_PATH.name}. Install it rather than "
            "skipping validation."
        ) from exc
    schema = _load_research_card_schema()
    # FormatChecker is attached for the same reason design_intent.py and
    # exemptions.py attach it: `format: date-time` on ingestion_timestamp is
    # inert without it, so an impossible timestamp would validate here and only
    # fail later at parse time.
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(card), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise ResearchEvidenceCardValidationError(
            f"{RESEARCH_EVIDENCE_CARD_SCHEMA_PATH.name} validation failed:\n" + "\n".join(lines))


def research_card_missing_fields(card: Dict[str, Any]) -> List[str]:
    """Which required card fields are still unfilled, in schema order.

    Reuses dv_harness.inference.identify_gap() -- the harness's existing
    Gap step -- instead of a private set-difference, per the master prompt's
    section 10 instruction to route research reasoning through the existing
    Autonomous Inference Engine rather than a parallel one. On a skeleton this
    returns exactly RESEARCH_CARD_LLM_AUTHORED_FIELDS: the reader's actual
    worklist for this document.
    """
    return identify_gap(research_card_required_fields(), sorted(card.keys()))


def build_research_evidence_card_skeleton(
    path,
    project_root,
    *,
    title: str | None = None,
    source: str | None = None,
    document_type: str = "UNCLASSIFIED",
    version: str | None = None,
    analysis_version: str = "1.0",
    register: bool = True,
    now: str | None = None,
) -> Dict[str, Any]:
    """Build the MECHANICAL half of a ResearchEvidenceCard for one document.

    Populates only what the file itself establishes -- content identity
    (sha256 -> document_id), path/size/suffix, and source_provenance in
    evidence_ref()'s existing 5-key shape. Every analytical field
    (problem_statement, core_method, claim_set, candidate_l5_mapping, ...) is
    deliberately ABSENT, because this function does not read the document; the
    `research-ingestion` skill fills those from an actual reading. The returned
    dict therefore does not yet validate, and that is the contract: an unfilled
    card fails loudly instead of looking finished.

    `title` defaults to the file stem, which is all a hash can honestly know --
    the reader replaces it with the document's real title. `document_type`
    defaults to UNCLASSIFIED for the same reason. `version` defaults to
    "sha256:<digest>" so evidence_ref's version slot is never blank and never a
    guess; pass the document's own revision string when it has one.

    With `register` (default), the document is recorded in the same
    DocumentIndex this module already maintains, keyed by path+sha256, so
    re-ingesting an unchanged document is detectable via needs_extract() rather
    than re-read from scratch.
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise ResearchIngestionError(f"not an existing file: {p}")
    suffix = p.suffix.lower()
    if suffix not in RESEARCH_DOCUMENT_SUFFIXES:
        raise ResearchIngestionError(
            f"{p.name}: suffix {suffix!r} is not external technical literature. "
            f"Supported: {sorted(RESEARCH_DOCUMENT_SUFFIXES)}. "
            "Design/RTL/spreadsheet inputs go through the project's own document "
            "path, not research ingestion."
        )
    resolved = p.resolve()
    digest = sha256_file(resolved)
    document_id = f"DOC-{digest[:12]}"
    doc_version = version or f"sha256:{digest}"

    if register:
        DocumentIndex(Path(project_root)).register(
            resolved,
            kind=RESEARCH_DOCUMENT_INDEX_KIND,
            metadata={"document_id": document_id, "document_type": document_type},
        )

    return {
        "schema_version": RESEARCH_CARD_SCHEMA_VERSION,
        "document_id": document_id,
        "title": title or resolved.stem,
        "source": source or str(resolved),
        "document_type": document_type,
        "document_sha256": digest,
        "document_path": str(resolved),
        "document_bytes": resolved.stat().st_size,
        "document_suffix": suffix,
        "source_provenance": evidence_ref(
            document=resolved.name,
            version=doc_version,
            # The whole document is the referent at card level; per-claim page
            # and section belong on each claim_set entry's own source_location.
            page="",
            section="",
            location=str(resolved),
        ),
        "ingestion_timestamp": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ingestion_version": RESEARCH_CARD_INGESTION_VERSION,
        "analysis_version": analysis_version,
    }
