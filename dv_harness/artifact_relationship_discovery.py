"""dv_harness/artifact_relationship_discovery.py -- discover REAL relationships
between intake artifacts (a register-map file references a block also
described in a spec doc; two RTL files share an instantiated module; a spec
doc names a register a register-map file also declares), using
`dv_harness/design_source_inventory.py`'s real registry rows as input.

CLAUDE_L5_INTAKE_MASTER.md section 6 ("Artifact Relationship Discovery") asks
for exactly this. REUSE OVER REINVENT was checked first, per this project's
own house rule -- a repo-wide grep for `artifact_relationship`/
`relationship_discovery`/`ArtifactRelationship`/`discover_relationships`
found nothing executable. Two similarly-shaped mechanisms exist and are
deliberately NOT reused wholesale, because they answer different questions:

  * `design_knowledge_correlation.py` correlates FACTS a caller has already
    reduced to `{fact_key, value}` pairs and JOINS on the caller's own
    `fact_key` -- it never discovers that two pieces of ARTIFACT CONTENT
    share an identifier in the first place. This module is the layer BELOW
    that one: it is where a `fact_key` match would come from if a caller
    wanted to feed one artifact's extracted identifiers into that engine.
  * `doc_citation_check.py` checks that a Markdown doc's own
    `file.py:line` CITATIONS still point at the symbol they claim to --
    a citation-DRIFT checker over prose that already names a specific
    file:line, not a discovery mechanism that finds new relationships an
    intake session never explicitly cited.

Neither is imported here (and neither would have been the right reuse target
even if it existed): this module is genuinely new territory, a step BEFORE
either -- it opens real artifact content, extracts real citable identifiers,
and reports a relationship ONLY when a real identifier is shared, never from
a filename, a project-declared `type` string, or a coincidence-shaped guess.

EVIDENCE TRUTH RULE, applied to a domain built entirely from real project
identifiers.  A "relationship" is never inferred from two artifacts merely
sitting in the same `DISCOVERY_ORDER` kind, from their file names looking
similar, or from an agent's own belief that "this register map is probably
what that spec chapter documents".  It is reported only when a NAMED,
CITABLE identifier -- an RTL module/parameter/port name (via the real
`verible_parser.py`, imported and called, never a second SystemVerilog
parser), a register-map block/register/field name (via the real
`env_manifest.load_register_map()`, the documented input contract that
module already validates against `register_map.schema.json`), or a
plausible-identifier-shaped TOKEN scanned out of a plain-text/Markdown
document with a real `line:<n>` citation -- appears, exactly (case-
normalized, never fuzzy), in TWO artifacts' own extracted identifier sets.

ANTI-FALSE-POSITIVE RULE.  A shared TOKEN (the weakest evidence class -- a
line-scanned candidate out of prose, not a real parsed declaration) between
two artifacts that BOTH only ever contributed tokens is never reported: two
spec documents sharing an ordinary word is not evidence of a real
relationship. A relationship is reported only when at least one side of the
match is a NAMED ENTITY a real extractor actually declared (an RTL module/
parameter/port, or a register-map block/register/field) -- so "a register-
map file references a block also described in a spec doc" (this section's
own worked example) is exactly reportable: the block NAME is a named entity
on the register-map side, matched against a real cited token occurrence on
the spec-doc side.

WHAT COUNTS AS "EVIDENCE" FOR A PDF.  Per this project's own Context Budget
Tier-1 policy ("NEVER-*" raw-PDF-original rule), this module never opens a
raw `.pdf` itself to scan its text -- that route is `vip_user_guide_distill.
py`'s (`dv-harness vip-user-guide distill`), which already produces a real,
bounded `<stem>.fulltext.txt` sibling artifact from a real `pypdf` extraction.
A `.pdf` registry row is resolved by looking for that already-produced
sibling file; absent it, the row is honestly `NOT_AVAILABLE` naming the real
distill command to run, never a raw PDF scan of its own and never a silently
empty relationship contribution presented as "nothing to relate".

WHAT THIS MODULE DOES NOT DO.  It discovers no artifact of its own -- the
registry rows it reads come entirely from `design_source_inventory.
build_source_registry()` (or an equivalent caller-supplied row list in that
same shape); it decides, approves and arbitrates nothing (no build, no job,
no approval, and there is deliberately no stage gate -- a discovered
relationship is an input to a human/agent's intake review, never a
verification verdict); and it never mines a golden-reference environment for
protocol-BEHAVIOR content -- every identifier this module reports comes from
the CURRENT project's own artifacts, never from a reference environment read
for any purpose other than structural conformance elsewhere in this repo.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Union

from . import env_manifest
from . import verible_parser

__all__ = [
    "ArtifactRelationshipDiscoveryError",
    "STATUS_EXTRACTED", "STATUS_PARTIAL", "STATUS_NOT_AVAILABLE",
    "KIND_MODULE", "KIND_PARAMETER", "KIND_PORT",
    "KIND_BLOCK", "KIND_REGISTER", "KIND_FIELD", "KIND_TOKEN",
    "NAMED_ENTITY_KINDS",
    "Identifier", "IdentifierExtractionResult", "ArtifactRelationship",
    "RelationshipDiscoveryReport",
    "extract_identifiers_from_entry", "discover_relationships",
    "discover_relationships_from_registry", "render_relationships_markdown",
]


class ArtifactRelationshipDiscoveryError(ValueError):
    """Typed error, same convention as the rest of this package: a short
    SCREAMING_SNAKE_CASE `reason` plus a concrete `detail` dict."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

STATUS_EXTRACTED = "EXTRACTED"          # real identifiers found (possibly zero)
STATUS_PARTIAL = "PARTIAL"              # extraction machinery ran but degraded
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"  # could not even attempt extraction

KIND_MODULE = "module"
KIND_PARAMETER = "parameter"
KIND_PORT = "port"
KIND_BLOCK = "block"
KIND_REGISTER = "register"
KIND_FIELD = "field"
KIND_TOKEN = "token"

#: Identifier kinds a real, structured extractor DECLARED (RTL parse, a
#: schema-validated register map) -- as opposed to KIND_TOKEN, a line-scanned
#: CANDIDATE out of prose. The anti-false-positive rule below requires at
#: least one side of a match to be one of these.
NAMED_ENTITY_KINDS = frozenset({
    KIND_MODULE, KIND_PARAMETER, KIND_PORT, KIND_BLOCK, KIND_REGISTER, KIND_FIELD,
})

#: A small, disclosed stoplist of generic technical-writing words that would
#: otherwise pass the plain-text token shape filter (see `_looks_like_token`)
#: purely because they are frequently written in caps/with an underscore in
#: prose, without naming any real project entity.
DEFAULT_TEXT_STOPWORDS = frozenset({
    "TODO", "FIXME", "NOTE", "NOTES", "SECTION", "SECTIONS", "FIGURE",
    "FIGURES", "TABLE", "TABLES", "CHAPTER", "CHAPTERS", "APPENDIX",
    "REFERENCE", "REFERENCES", "OVERVIEW", "SUMMARY", "INTRODUCTION",
    "DESCRIPTION", "EXAMPLE", "EXAMPLES", "WARNING", "CAUTION", "IMPORTANT",
})

#: Minimum "core" length (underscores stripped) for a plain-text token
#: candidate to be considered -- named entities from a real extractor are
#: never subject to this floor, since they are already real declared names.
DEFAULT_MIN_TOKEN_LENGTH = 4

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,63}")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class Identifier:
    """One real, citable name extracted from one artifact.

    `locator` is a structural or line-based citation, never invented: for
    RTL/register-map facts (neither of which carries a source line anywhere
    upstream -- the same disclosed limitation `dut_evidence_correlation.py`
    already states for these same two producers) it is a structural path
    like `module:usb3_link_ctrl` or `block:USB3_LINK/register:CTRL0`; for a
    plain-text/Markdown scan it is a real `line:<n>`.
    """
    name: str
    kind: str
    locator: str

    @property
    def normalized(self) -> str:
        return self.name.strip().lower()


@dataclass
class IdentifierExtractionResult:
    source_id: str
    path: Optional[str]
    status: str
    reason: Optional[str] = None
    identifiers: List[Identifier] = field(default_factory=list)


@dataclass
class ArtifactRelationship:
    """One real, evidenced relationship between two artifacts, proven by a
    shared identifier -- never by name/type/discovery-kind coincidence."""
    artifact_a: str
    artifact_b: str
    identifier: str          # normalized (case-folded) shared name
    name_a: str               # as it appeared in artifact A
    name_b: str                # as it appeared in artifact B
    kind_a: str
    kind_b: str
    locator_a: str
    locator_b: str
    path_a: Optional[str]
    path_b: Optional[str]

    def to_row(self) -> dict:
        return {
            "artifact_a": self.artifact_a, "artifact_b": self.artifact_b,
            "identifier": self.identifier,
            "citation_a": f"{self.name_a} ({self.kind_a}) @ {self.locator_a}",
            "citation_b": f"{self.name_b} ({self.kind_b}) @ {self.locator_b}",
        }


@dataclass
class RelationshipDiscoveryReport:
    artifact_count: int
    extraction_results: Dict[str, IdentifierExtractionResult]
    relationships: List[ArtifactRelationship]
    unresolved_artifacts: List[dict]

    def to_dict(self) -> dict:
        return {
            "artifact_count": self.artifact_count,
            "extraction_results": {
                sid: {
                    "source_id": r.source_id, "path": r.path, "status": r.status,
                    "reason": r.reason,
                    "identifiers": [
                        {"name": i.name, "kind": i.kind, "locator": i.locator}
                        for i in r.identifiers
                    ],
                }
                for sid, r in self.extraction_results.items()
            },
            "relationships": [
                {
                    "artifact_a": rel.artifact_a, "artifact_b": rel.artifact_b,
                    "identifier": rel.identifier,
                    "name_a": rel.name_a, "kind_a": rel.kind_a, "locator_a": rel.locator_a,
                    "path_a": rel.path_a,
                    "name_b": rel.name_b, "kind_b": rel.kind_b, "locator_b": rel.locator_b,
                    "path_b": rel.path_b,
                }
                for rel in self.relationships
            ],
            "unresolved_artifacts": list(self.unresolved_artifacts),
        }


# ---------------------------------------------------------------------------
# Per-kind extraction
# ---------------------------------------------------------------------------

def _looks_like_token(tok: str, min_core_length: int, stopwords) -> bool:
    """A plain-text scan candidate must look DESIGNED -- an underscore-joined
    or ALL_CAPS or mixedCase/CamelCase token -- never an ordinary lowercase
    English word, which the shape check below excludes by construction."""
    core = tok.replace("_", "")
    if len(core) < min_core_length:
        return False
    if tok.upper() in stopwords:
        return False
    has_underscore = "_" in tok
    is_all_caps = tok.isupper() and len(tok) >= 3
    mixed_case = any(c.isupper() for c in tok[1:]) and not tok.isupper()
    return has_underscore or is_all_caps or mixed_case


def _extract_from_text(path: Path, source_id: str, *, min_token_length: int,
                        stopwords) -> IdentifierExtractionResult:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return IdentifierExtractionResult(
            source_id, str(path), STATUS_NOT_AVAILABLE,
            reason=f"UNREADABLE_TEXT_FILE: {path} ({exc})")
    identifiers: List[Identifier] = []
    seen = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in _TOKEN_RE.finditer(line):
            tok = m.group(0)
            if not _looks_like_token(tok, min_token_length, stopwords):
                continue
            key = (tok.lower(), lineno)
            if key in seen:
                continue
            seen.add(key)
            identifiers.append(Identifier(tok, KIND_TOKEN, f"line:{lineno}"))
    return IdentifierExtractionResult(source_id, str(path), STATUS_EXTRACTED,
                                       identifiers=identifiers)


def _extract_from_rtl(path: Path, source_id: str) -> IdentifierExtractionResult:
    try:
        result = verible_parser.parse_file(path)
    except verible_parser.VeribleUnavailableError as exc:
        return IdentifierExtractionResult(
            source_id, str(path), STATUS_NOT_AVAILABLE,
            reason=f"VERIBLE_UNAVAILABLE: {exc}")
    except verible_parser.VeribleParseError as exc:
        return IdentifierExtractionResult(
            source_id, str(path), STATUS_NOT_AVAILABLE,
            reason=f"VERIBLE_PARSE_ERROR: {exc}")
    identifiers: List[Identifier] = []
    for mod in result.modules:
        if mod.name:
            identifiers.append(Identifier(mod.name, KIND_MODULE, f"module:{mod.name}"))
        for p in mod.parameters:
            if p.name:
                identifiers.append(Identifier(
                    p.name, KIND_PARAMETER, f"module:{mod.name}/parameter:{p.name}"))
        for p in mod.ports:
            if p.name:
                identifiers.append(Identifier(
                    p.name, KIND_PORT, f"module:{mod.name}/port:{p.name}"))
    return IdentifierExtractionResult(source_id, str(path), STATUS_EXTRACTED,
                                       identifiers=identifiers)


def _extract_from_register_map(path: Path, source_id: str) -> IdentifierExtractionResult:
    try:
        doc = env_manifest.load_register_map(path)
    except env_manifest.RegisterMapValidationError as exc:
        return IdentifierExtractionResult(
            source_id, str(path), STATUS_NOT_AVAILABLE,
            reason=f"NOT_A_REGISTER_MAP_DOCUMENT: {exc}")
    except (OSError, json.JSONDecodeError) as exc:
        return IdentifierExtractionResult(
            source_id, str(path), STATUS_NOT_AVAILABLE,
            reason=f"UNREADABLE_JSON: {path} ({exc})")
    identifiers: List[Identifier] = []
    for block in doc.get("blocks", []) or []:
        bname = block.get("name")
        if bname:
            identifiers.append(Identifier(bname, KIND_BLOCK, f"block:{bname}"))
        for reg in block.get("registers", []) or []:
            rname = reg.get("name")
            if rname:
                identifiers.append(Identifier(
                    rname, KIND_REGISTER, f"block:{bname}/register:{rname}"))
            for fld in reg.get("fields", []) or []:
                fname = fld.get("name")
                if fname:
                    identifiers.append(Identifier(
                        fname, KIND_FIELD,
                        f"block:{bname}/register:{rname}/field:{fname}"))
    return IdentifierExtractionResult(source_id, str(path), STATUS_EXTRACTED,
                                       identifiers=identifiers)


def _extract_from_pdf(path: Path, source_id: str, *, min_token_length: int,
                       stopwords, fulltext_override: Optional[Union[str, Path]] = None
                       ) -> IdentifierExtractionResult:
    """Never opens the raw PDF itself (Context Budget Tier-1 policy). Reads
    only the real `<stem>.fulltext.txt` sibling `vip_user_guide_distill.
    distill_user_guide()` already produces -- or a caller-supplied override
    of that same real artifact."""
    sibling = Path(fulltext_override) if fulltext_override else (
        path.parent / f"{path.stem}.fulltext.txt")
    if not sibling.is_file():
        return IdentifierExtractionResult(
            source_id, str(path), STATUS_NOT_AVAILABLE,
            reason=(f"NO_DISTILLED_FULLTEXT: this module never opens a raw .pdf "
                     f"itself (Context Budget Tier-1 policy) -- run "
                     f"`dv-harness vip-user-guide distill --source {path}` "
                     f"(vip_user_guide_distill.distill_user_guide()) first; "
                     f"expected {sibling}"))
    inner = _extract_from_text(sibling, source_id, min_token_length=min_token_length,
                                stopwords=stopwords)
    inner.path = str(path)
    if inner.reason:
        inner.reason = f"(via distilled fulltext {sibling}) {inner.reason}"
    return inner


_TEXT_SUFFIXES = frozenset({".txt", ".md", ".markdown"})
_RTL_SUFFIXES = frozenset({".v", ".sv", ".svh"})
_JSON_SUFFIXES = frozenset({".json"})
_PDF_SUFFIXES = frozenset({".pdf"})


def extract_identifiers_from_entry(entry: dict, *,
                                    min_token_length: int = DEFAULT_MIN_TOKEN_LENGTH,
                                    stopwords=DEFAULT_TEXT_STOPWORDS,
                                    fulltext_override: Optional[Union[str, Path]] = None
                                    ) -> IdentifierExtractionResult:
    """Extract real, citable identifiers from ONE design_source_inventory
    registry row (a `build_source_registry()`/`evaluate_source()` row, or
    any dict carrying at least `source_id` and `path`).

    Dispatch is by real file SUFFIX, never by the row's own free-text `type`
    field (that field is caller-declared and unvalidated -- see
    `design_source_inventory.SourceEntry`'s own docstring) -- so this
    function never trusts a label over the artifact's real, on-disk shape.
    """
    source_id = str(entry.get("source_id") or entry.get("id") or "").strip()
    if not source_id:
        raise ArtifactRelationshipDiscoveryError("SOURCE_ID_MUST_BE_STATED", {"entry": entry})
    raw_path = entry.get("path")
    if not raw_path:
        return IdentifierExtractionResult(
            source_id, None, STATUS_NOT_AVAILABLE,
            reason="NO_PATH_SUPPLIED: this registry row has no `path` to read")
    path = Path(raw_path)
    if not path.exists():
        return IdentifierExtractionResult(
            source_id, str(path), STATUS_NOT_AVAILABLE,
            reason=f"PATH_DOES_NOT_EXIST: {path}")
    if path.is_dir():
        return IdentifierExtractionResult(
            source_id, str(path), STATUS_NOT_AVAILABLE,
            reason=f"IS_A_DIRECTORY: identifier extraction is per-file only: {path}")

    suffix = path.suffix.lower()
    if suffix in _RTL_SUFFIXES:
        return _extract_from_rtl(path, source_id)
    if suffix in _JSON_SUFFIXES:
        return _extract_from_register_map(path, source_id)
    if suffix in _TEXT_SUFFIXES:
        return _extract_from_text(path, source_id, min_token_length=min_token_length,
                                   stopwords=stopwords)
    if suffix in _PDF_SUFFIXES:
        return _extract_from_pdf(path, source_id, min_token_length=min_token_length,
                                  stopwords=stopwords, fulltext_override=fulltext_override)
    return IdentifierExtractionResult(
        source_id, str(path), STATUS_NOT_AVAILABLE,
        reason=f"UNSUPPORTED_ARTIFACT_KIND: no identifier extractor for suffix {suffix!r}")


# ---------------------------------------------------------------------------
# Relationship discovery
# ---------------------------------------------------------------------------

def _index_by_normalized_name(result: IdentifierExtractionResult) -> Dict[str, List[Identifier]]:
    index: Dict[str, List[Identifier]] = {}
    for ident in result.identifiers:
        index.setdefault(ident.normalized, []).append(ident)
    return index


def discover_relationships(entries: Iterable[dict], *,
                            min_token_length: int = DEFAULT_MIN_TOKEN_LENGTH,
                            stopwords=DEFAULT_TEXT_STOPWORDS,
                            extraction_results: Optional[Dict[str, IdentifierExtractionResult]] = None
                            ) -> RelationshipDiscoveryReport:
    """Discover real, shared-identifier relationships across a batch of
    design_source_inventory registry rows.

    `entries` is duck-typed (each a dict carrying at least `source_id` and
    `path`) exactly like `design_source_inventory.build_source_registry()`'s
    own `sources` list, so a caller can pass that list directly.
    `extraction_results`, when supplied, is consulted before re-extracting a
    given `source_id` -- useful when a caller already ran extraction (e.g.
    once per project run) and wants to reuse it across several discovery
    calls without re-parsing every artifact.
    """
    entries = list(entries)
    results: Dict[str, IdentifierExtractionResult] = dict(extraction_results or {})
    order: List[str] = []
    for entry in entries:
        sid = str(entry.get("source_id") or entry.get("id") or "")
        if sid not in results:
            results[sid] = extract_identifiers_from_entry(
                entry, min_token_length=min_token_length, stopwords=stopwords)
        order.append(sid)

    indices: Dict[str, Dict[str, List[Identifier]]] = {
        sid: _index_by_normalized_name(results[sid]) for sid in order
    }

    unresolved: List[dict] = []
    for sid in order:
        r = results[sid]
        if r.status == STATUS_NOT_AVAILABLE:
            unresolved.append({"source_id": sid, "path": r.path, "reason": r.reason})

    relationships: List[ArtifactRelationship] = []
    for i in range(len(order)):
        for j in range(i + 1, len(order)):
            sid_a, sid_b = order[i], order[j]
            idx_a, idx_b = indices[sid_a], indices[sid_b]
            shared = sorted(set(idx_a) & set(idx_b))
            for key in shared:
                idents_a = idx_a[key]
                idents_b = idx_b[key]
                if (all(x.kind == KIND_TOKEN for x in idents_a)
                        and all(x.kind == KIND_TOKEN for x in idents_b)):
                    # Two artifacts sharing only a scanned prose token, on
                    # BOTH sides, is not real evidence of a relationship --
                    # see this module's own "ANTI-FALSE-POSITIVE RULE".
                    continue
                rep_a, rep_b = idents_a[0], idents_b[0]
                relationships.append(ArtifactRelationship(
                    artifact_a=sid_a, artifact_b=sid_b, identifier=key,
                    name_a=rep_a.name, kind_a=rep_a.kind, locator_a=rep_a.locator,
                    path_a=results[sid_a].path,
                    name_b=rep_b.name, kind_b=rep_b.kind, locator_b=rep_b.locator,
                    path_b=results[sid_b].path,
                ))

    return RelationshipDiscoveryReport(
        artifact_count=len(order), extraction_results=results,
        relationships=relationships, unresolved_artifacts=unresolved,
    )


def discover_relationships_from_registry(registry: dict, **kwargs) -> RelationshipDiscoveryReport:
    """Convenience wrapper taking the FULL
    `design_source_inventory.build_source_registry()` result dict directly
    (its own `{"sources": [...], ...}` shape) rather than a bare row list."""
    sources = registry.get("sources") if isinstance(registry, dict) else None
    if sources is None:
        raise ArtifactRelationshipDiscoveryError(
            "REGISTRY_HAS_NO_SOURCES_LIST",
            {"hint": "expected the dict build_source_registry() returns, "
                      "carrying a 'sources' list"})
    return discover_relationships(sources, **kwargs)


def render_relationships_markdown(report: RelationshipDiscoveryReport) -> str:
    from .connectivity import render_markdown_table
    columns = [
        ("artifact_a", "Artifact A"), ("artifact_b", "Artifact B"),
        ("identifier", "Shared Identifier"),
        ("citation_a", "Citation A"), ("citation_b", "Citation B"),
    ]
    rows = [rel.to_row() for rel in report.relationships]
    lines = [
        f"Artifacts examined: {report.artifact_count}",
        f"Relationships discovered: {len(report.relationships)}",
        f"Unresolved artifacts: {len(report.unresolved_artifacts)}",
        "",
        render_markdown_table(columns, rows, empty_note="(no relationships discovered)"),
    ]
    if report.unresolved_artifacts:
        lines.append("")
        lines.append("Unresolved (could not extract identifiers):")
        for u in report.unresolved_artifacts:
            lines.append(f"  - {u['source_id']} ({u.get('path')}): {u['reason']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI front door (no `dv-harness` verb -- see house-style item 8: `cli.py`
# is a large file under heavy edit pressure from many concurrent items in
# this same batch, so this stays a standalone `python -m` entry point).
# ---------------------------------------------------------------------------

def _load_entries(path: Path) -> List[dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, dict) and "sources" in doc:
        return doc["sources"]
    if isinstance(doc, list):
        return doc
    raise ArtifactRelationshipDiscoveryError(
        "UNRECOGNIZED_INPUT_SHAPE",
        {"hint": "expected a JSON list of registry rows, or a "
                  "build_source_registry()-shaped {'sources': [...]} document"})


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m dv_harness.artifact_relationship_discovery")
    parser.add_argument("--sources", required=True,
                         help="path to a JSON file: a design_source_inventory "
                              "build_source_registry() result, or a bare list "
                              "of registry rows")
    parser.add_argument("--json", action="store_true", help="print JSON instead of markdown")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    try:
        entries = _load_entries(Path(args.sources))
        report = discover_relationships(entries)
    except ArtifactRelationshipDiscoveryError as exc:
        print(f"{exc.reason}: {exc.detail}", file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        print(f"CANNOT_READ_SOURCES_FILE: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=False))
    else:
        print(render_relationships_markdown(report))
    return 0 if report.relationships else 1


if __name__ == "__main__":
    raise SystemExit(main())
