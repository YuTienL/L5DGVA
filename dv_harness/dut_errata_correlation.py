"""dv_harness/dut_errata_correlation.py -- discovers/parses a DUT
errata/known-issues document (a real, mechanically-detected structural
index of erratum entries, never a document-body dump) and correlates each
named erratum's own cited affected block/register/signal/module against
this project's real RTL/register-map/clock-reset/address-map evidence
(env.manifest.json's `dut_facts`), reporting NOT_AVAILABLE honestly when no
errata document is supplied.

THE GAP THIS CLOSES. No module anywhere in this repo discovered or parsed
an errata/known-issues document, let alone correlated a named erratum to
the specific RTL region/register it affects. A repo-wide grep for
`errata`/`known_issue`/`ERR-` before this module found nothing executable.
An agent asking "does erratum ERR-042 in the vendor's silicon errata sheet
still apply to the register block this environment binds against" had no
bounded artifact to answer from and no honest way to get one short of
opening the whole errata document and re-deriving the RTL correspondence by
hand every time.

REUSE, TWICE OVER -- this module invents no new extraction or correlation
mechanism of its own; it composes two that already exist.

  1. STRUCTURAL EXTRACTION reuses `spec_doc_map.py`'s own PATTERN, not its
     code (spec_doc_map.py itself is not imported here, for the identical
     independent-testability reasoning that module's own docstring gives
     for not importing `vip_user_guide_distill.py`): the same real
     `pypdf.PdfReader(...).pages[i].extract_text()` call, the same
     "raise rather than silently produce an empty/partial artifact"
     discipline (`ErrataDocumentError`, mirroring `SpecDocMapError`), the
     same mechanically-detected line-pattern regex idea, and the same
     two-artifact-pair convention (`<stem>.errata_index.json` /
     `<stem>.errata_index.md`, structure-only -- see "WHAT LANDS WHERE"
     below). What is detected is different because the document family is
     different: instead of numbered chapter headings and Table captions,
     this module detects ERRATUM headers ("Erratum 12: <title>",
     "Errata ID: ERR-042 - <title>", a bare "ERR042: <title>") and, within
     each erratum's own bounded text block, LABELED EVIDENCE FIELDS
     ("Affected Register: CTRL0", "Silicon Revision: A0, A1",
     "Workaround: ..."). A labeled field is detected by its LABEL, never by
     what its value happens to say -- the same "a real, verifiable,
     reproducible property of the document's OWN text" discipline
     spec_doc_map.py's own docstring states for its heading/caption regexes.

  2. CORRELATION reuses `dut_evidence_correlation.py` directly (a real
     import, not a re-derivation -- that module is a stable, already-shipped
     part of this repo, not a concurrently-edited file this task must avoid
     coupling to). Every affected-component name an erratum cites is turned
     into exactly the declared-fact item shape that module's own
     `correlate_item()` already accepts (`fact_type="feature"`, which
     searches every dut_facts layer -- rtl, registers, clock_reset,
     address_map -- since an erratum's affected component could legitimately
     be any of them) and handed to it unmodified. This module adds nothing
     to that module's own five-status per-citation verdict
     (RTL_CONFIRMED / RTL_CONTRADICTS_SPEC / RTL_PARTIAL / RTL_NOT_FOUND /
     NOT_AVAILABLE); it only rolls several citations' worth of that verdict
     up into ONE per-erratum correlation status (see below), because one
     erratum can legitimately cite more than one affected component.

WHAT LANDS WHERE, and why prose lands nowhere, mirroring spec_doc_map.py's
own discipline: `<stem>.errata_index.json` / `<stem>.errata_index.md` carry
each erratum's ID, title, page/line-anchored location, its cited affected
components (name + which label cited it), its cited silicon-revision
values, a boolean "does this erratum name a workaround section at all" fact
plus that section's own real Status-labeled value if one exists, and a
short (<=300 char) EXCERPT of the first few non-labeled lines of the
erratum's own block -- never the full erratum description/workaround
prose. An excerpt this short is the same kind of short, real, bounded
document text spec_doc_map.py's own headings and table captions already
are (<=150/130 chars respectively); it is not a document-body dump.

THE PER-ERRATUM CORRELATION STATUS, and what earns each one. A single
erratum can cite zero, one, or several affected-component names; this
module's own job is to roll `dut_evidence_correlation`'s per-citation
verdicts up into one honest per-erratum answer, never picking one citation
arbitrarily and discarding the rest:
  RTL_LOCATED                 at least one cited affected component has a
                               real EXACT match in this project's own
                               dut_facts (RTL_CONFIRMED or
                               RTL_CONTRADICTS_SPEC on the underlying
                               citation) -- we now know concretely which
                               RTL/register evidence this erratum affects.
  RTL_PARTIALLY_LOCATED       no exact match on any citation, but at least
                               one has an unproven substring match
                               (RTL_PARTIAL) -- a plausible but unconfirmed
                               correspondence, never silently upgraded.
  RTL_NOT_LOCATED             every cited affected component was actually
                               searched against available dut_facts
                               evidence and none was found -- a real
                               negative (the erratum's naming may have
                               drifted from the RTL's actual naming, or the
                               cited block genuinely does not exist in this
                               project's RTL), not an absence of evidence.
  NO_AFFECTED_COMPONENT_CITED the erratum's own text named no affected
                               block/register/signal/module at all -- a
                               real structural fact about the DOCUMENT
                               (this extraction found nothing to correlate
                               against), never conflated with a real RTL
                               search finding nothing.
  NOT_AVAILABLE                the erratum cited at least one affected
                               component, but no env.manifest.json was
                               available to correlate any of them against --
                               per the Evidence Truth Rule this is never
                               collapsed into RTL_NOT_LOCATED: "we looked
                               and it is not there" and "we could not look"
                               are different claims.

THE ONE-SHOT FRONT DOOR, `analyze_errata()`, is what turns "no errata
document supplied" into the honest top-level NOT_AVAILABLE this task's own
contract requires -- a `source_path` of `None` (or one that genuinely does
not exist, or a document `extract_errata_document()` itself cannot open --
missing pypdf, an unsupported suffix) reports `status: "NOT_AVAILABLE"`
with the real reason, and correlates nothing, rather than silently
reporting a clean pass over zero errata.

DELIBERATELY BOUNDED, and stated rather than implied closed.
(1) Erratum-header detection is a line-pattern scan bounded to three real,
    conventional shapes ("Erratum <id>: <title>", "Errata ID: <id> -
    <title>", a bare "ERR<digits>: <title>"); a document whose erratum
    entries are numbered/tabled in some other convention this scan does not
    recognise contributes zero detected errata, and that is reported as a
    real, honest zero -- never guessed at from body prose.
(2) Labeled-field detection is likewise bounded to a small, explicit label
    vocabulary (affected block/register/signal/module/component, silicon
    revision, workaround/fix/resolution, status); a field expressed under a
    differently-worded label is not detected. Only the first
    `MAX_BLOCK_LINES` lines following a detected erratum header are
    scanned for labeled fields -- a deliberate bound, the same "cap the
    read, do not let one document's shape dictate an unbounded scan"
    discipline this project applies elsewhere.
(3) Affected-component NAME matching against RTL/registers is entirely
    `dut_evidence_correlation.py`'s own job -- this module performs zero
    matching logic of its own, so its own name-based / no-fuzzy-synonym /
    no-semantic-matching limits apply here identically.
(4) This module decides nothing beyond reporting: no build, job, approval,
    or stage gate is touched, and there is no stage-gate entry for it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import dut_evidence_correlation as dec
from . import env_manifest

SCHEMA_VERSION = "1.0"

#: Suffixes this module can genuinely extract structure from -- identical
#: reasoning to spec_doc_map.py's own SUPPORTED_SUFFIXES: claiming a format
#: this module cannot actually read would be a capability claim it cannot
#: honour.
SUPPORTED_SUFFIXES = (".pdf", ".txt", ".md")

#: A deliberate bound on how far past a detected erratum header this module
#: will scan for labeled evidence fields -- see "DELIBERATELY BOUNDED" (2).
MAX_BLOCK_LINES = 250

_MAX_TITLE_CHARS = 160
_MAX_COMPONENT_NAME_CHARS = 64
_MAX_EXCERPT_CHARS = 300
_MAX_EXCERPT_LINES = 4

# ---------------------------------------------------------------------------
# Correlation-status vocabulary (per erratum, rolled up from
# dut_evidence_correlation's own per-citation verdicts).
# ---------------------------------------------------------------------------
STATUS_RTL_LOCATED = "RTL_LOCATED"
STATUS_RTL_PARTIALLY_LOCATED = "RTL_PARTIALLY_LOCATED"
STATUS_RTL_NOT_LOCATED = "RTL_NOT_LOCATED"
STATUS_NO_AFFECTED_COMPONENT_CITED = "NO_AFFECTED_COMPONENT_CITED"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
ERRATUM_CORRELATION_STATUSES: Tuple[str, ...] = (
    STATUS_RTL_LOCATED, STATUS_RTL_PARTIALLY_LOCATED, STATUS_RTL_NOT_LOCATED,
    STATUS_NO_AFFECTED_COMPONENT_CITED, STATUS_NOT_AVAILABLE,
)

#: Fields a real errata_index.json record must carry -- checked by
#: load_errata_document() so a caller cannot be pointed at an arbitrary
#: JSON file and have it quietly accepted as a real errata-index record.
_REQUIRED_RECORD_FIELDS = (
    "schema_version", "doc_kind", "title", "source_document", "extraction",
    "errata", "erratum_count", "structure_map",
)


class ErrataDocumentError(RuntimeError):
    """Structural extraction could not be performed against a real source
    document -- an unsupported suffix, a missing file, or a missing real
    extractor dependency. Raised rather than returning a partial/empty
    errata index, because a record that silently describes zero errata is
    indistinguishable from a real document that genuinely has none.
    `analyze_errata()` is what turns this into this task's required honest
    `NOT_AVAILABLE` status carrying this exception's own real reason text --
    the raise/report split is deliberate, mirroring spec_doc_map.py's own
    `SpecDocMapError` / `execute_verb()` contract."""


# ---------------------------------------------------------------------------
# Small helpers re-derived locally (not imported from spec_doc_map.py) --
# see this module's own docstring for why: independent testability, and
# spec_doc_map.py is this repo's own precedent for exactly this choice.
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_pdf_pages(path: Path) -> Tuple[List[str], Optional[str]]:
    """Returns `(pages, pypdf_version)`, one plain-text string per PDF page,
    via the real pypdf library. Raises ErrataDocumentError when pypdf is not
    installed -- never a silent empty extraction."""
    try:
        import pypdf
    except ImportError as exc:
        raise ErrataDocumentError(
            f"cannot extract {path}: the 'pypdf' package is not installed. Install it, or "
            "pre-extract the document to a .txt and analyze that instead (the errata index will "
            "honestly record method='pre_extracted_text_errata_scan' and page=null)."
        ) from exc
    reader = pypdf.PdfReader(str(path))
    return [(page.extract_text() or "") for page in reader.pages], getattr(pypdf, "__version__", None)


# ---------------------------------------------------------------------------
# Erratum-header detection.
# ---------------------------------------------------------------------------

#: "Erratum 12: Title" / "Errata ID: ERR-042 - Title" / "Erratum: ERR-1 - Title".
#: Requires the literal "Errata"/"Erratum" keyword, an id token, and a
#: separator into a bounded title -- the real, conventional shape used by
#: most vendor silicon errata sheets and datasheet "Known Issues" chapters.
_ERRATUM_KEYWORD_HEADER_RE = re.compile(
    r"^\s{0,8}Errat(?:a|um)\b\s*[:#]?\s*(?:ID\s*[:#]?\s*)?"
    r"(?P<id>[A-Za-z0-9][\w./-]{0,39})\s*[:\-–]\s*(?P<title>\S.{0,150})$",
    re.IGNORECASE,
)

#: A bare "ERR042: Title" / "ERR-042 - Title" -- the other real, conventional
#: shape (no "Erratum"/"Errata" keyword, just a vendor-style id prefix).
_ERRATUM_BARE_ID_HEADER_RE = re.compile(
    r"^\s{0,8}(?P<id>ERR[-_]?\d{1,6})\s*[:\-–]\s*(?P<title>\S.{0,150})$",
    re.IGNORECASE,
)

#: A labeled evidence field: "Affected Register: CTRL0", "Status: Open".
_LABELED_FIELD_RE = re.compile(
    r"^\s{0,8}(?P<label>[A-Za-z][A-Za-z0-9 /_-]{1,40}?)\s*:\s*(?P<value>\S.{0,200})$"
)

#: Recognised labels, normalized (lowercased, whitespace-collapsed), mapped
#: to the fixed field categories this module extracts. A label outside this
#: set contributes nothing -- see "DELIBERATELY BOUNDED" (2).
_AFFECTED_COMPONENT_LABELS = {
    "affected block", "affected blocks", "affected register", "affected registers",
    "affected signal", "affected signals", "affected module", "affected modules",
    "affected component", "affected components", "block", "blocks", "register", "registers",
    "module", "modules", "component", "components", "signal", "signals",
}
_REVISION_LABELS = {
    "silicon revision", "silicon revisions", "revision", "revisions",
    "affected revision", "affected revisions",
    "affected silicon revision", "affected silicon revisions",
}
_WORKAROUND_PRESENCE_LABELS = {"workaround", "workarounds", "fix", "resolution"}
_STATUS_LABELS = {"status"}


def _normalize_label(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip().lower())


def _find_erratum_headers(lines: Sequence[Tuple[Optional[int], str]]) -> List[Dict[str, Any]]:
    headers: List[Dict[str, Any]] = []
    for idx, (page, raw) in enumerate(lines):
        stripped = raw.strip()
        if not stripped or len(stripped) > _MAX_TITLE_CHARS or stripped.endswith((".", ",", ";")):
            continue
        m = _ERRATUM_KEYWORD_HEADER_RE.match(stripped)
        if not m:
            m = _ERRATUM_BARE_ID_HEADER_RE.match(stripped)
        if m:
            headers.append({
                "index": idx, "page": page,
                "id": m.group("id"), "title": m.group("title").strip(),
            })
    return headers


def _split_component_names(value: str) -> List[str]:
    parts = re.split(r",|;| and ", value, flags=re.IGNORECASE)
    names: List[str] = []
    for p in parts:
        p = p.strip().strip(".")
        if not p or len(p) > _MAX_COMPONENT_NAME_CHARS:
            continue
        names.append(p)
    return names


def _extract_erratum_block(lines: Sequence[Tuple[Optional[int], str]], start_idx: int, end_idx: int,
                            header_id: str, header_title: str, header_page: Optional[int]) -> Dict[str, Any]:
    """Scans lines[start_idx:end_idx], bounded to MAX_BLOCK_LINES, for
    labeled evidence fields. Every affected-component citation carries the
    real label that named it and the real page it was found on (which may
    legitimately differ from the erratum header's own page, when an
    erratum's block spans a page boundary)."""
    affected_components: List[Dict[str, Any]] = []
    revisions_affected: List[str] = []
    has_workaround = False
    status_value: Optional[str] = None
    excerpt_lines: List[str] = []

    scan_end = min(end_idx, start_idx + MAX_BLOCK_LINES)
    for idx in range(start_idx, scan_end):
        page, raw = lines[idx]
        stripped = raw.strip()
        if not stripped:
            continue
        m = _LABELED_FIELD_RE.match(stripped)
        if m:
            label = _normalize_label(m.group("label"))
            value = m.group("value").strip()
            if label in _AFFECTED_COMPONENT_LABELS:
                for name in _split_component_names(value):
                    affected_components.append({"raw_label": label, "name": name, "page": page})
            elif label in _REVISION_LABELS:
                revisions_affected.append(value)
            elif label in _WORKAROUND_PRESENCE_LABELS:
                has_workaround = True
            elif label in _STATUS_LABELS:
                status_value = value
            continue
        if len(excerpt_lines) < _MAX_EXCERPT_LINES:
            excerpt_lines.append(stripped)

    excerpt = " ".join(excerpt_lines)
    if len(excerpt) > _MAX_EXCERPT_CHARS:
        excerpt = excerpt[:_MAX_EXCERPT_CHARS].rstrip() + "..."

    return {
        "erratum_id": header_id,
        "title": header_title,
        "page": header_page,
        "affected_components": affected_components,
        "revisions_affected": revisions_affected,
        "has_workaround": has_workaround,
        "status": status_value,
        "excerpt": excerpt,
    }


def _find_errata(pages: Sequence[str], has_real_pages: bool) -> List[Dict[str, Any]]:
    """Flattens `pages` into one document-order line stream (page-tagged),
    finds every erratum header, and extracts each one's own bounded block --
    a block may legitimately span a page boundary, which is why detection
    runs over the flattened stream rather than per-page."""
    lines: List[Tuple[Optional[int], str]] = []
    for page_idx, page_text in enumerate(pages):
        page_no = (page_idx + 1) if has_real_pages else None
        for raw in page_text.splitlines():
            lines.append((page_no, raw))

    headers = _find_erratum_headers(lines)
    errata: List[Dict[str, Any]] = []
    for i, h in enumerate(headers):
        start = h["index"] + 1
        end = headers[i + 1]["index"] if i + 1 < len(headers) else len(lines)
        errata.append(_extract_erratum_block(lines, start, end, h["id"], h["title"], h["page"]))
    return errata


def _render_errata_markdown(record: Dict[str, Any]) -> str:
    src = record["source_document"]
    ext = record["extraction"]
    lines = [
        f"# {record['title']} -- errata/known-issues structural index",
        "",
        "Mechanically generated by `dv_harness/dut_errata_correlation.py`. This file records "
        "STRUCTURE ONLY -- erratum id/title/location, cited affected components, cited silicon "
        "revisions, and whether a workaround section exists. It contains no full erratum "
        "description/workaround prose beyond a short (<=300 char) excerpt per erratum.",
        "",
        f"- Doc kind: `{record['doc_kind']}`",
        f"- Source document: `{src['path']}`",
        f"- Source sha256: `{src['sha256']}`",
        f"- Source bytes: {src['bytes']}",
        f"- Page count: {src['page_count'] if src['page_count'] is not None else 'null (text source -- no pages)'}",
        f"- Extractor: `{ext['tool']}` {ext['tool_version'] or '(version unreported)'} "
        f"(method `{ext['method']}`)",
        f"- Errata detected: {record['erratum_count']}",
        "",
        "## Errata index",
        "",
    ]
    if not record["errata"]:
        lines.append("_No erratum entries matching this module's recognised header shapes were detected "
                      "in this document._ That is a real observation about the source, not an "
                      "extraction failure.")
    else:
        lines.append("| Erratum ID | Title | Page | Affected components | Revisions | Workaround? |")
        lines.append("|---|---|---|---|---|---|")
        for e in record["errata"]:
            comps = ", ".join(c["name"] for c in e["affected_components"]) or "-"
            revs = ", ".join(e["revisions_affected"]) or "-"
            page = e["page"] if e["page"] is not None else ""
            lines.append(f"| {e['erratum_id']} | {e['title']} | {page} | {comps} | {revs} | "
                          f"{'yes' if e['has_workaround'] else 'no'} |")
    lines.append("")
    return "\n".join(lines)


def extract_errata_document(source_path, out_dir, *, title: Optional[str] = None,
                             doc_kind: str = "errata_sheet") -> Dict[str, Any]:
    """Distil ONE real DUT errata/known-issues document into the two
    structure-only artifacts described in this module's docstring, and
    return the `.errata_index.json` record. Mirrors
    spec_doc_map.extract_spec_doc_map()'s own contract precisely (see this
    module's docstring)."""
    source = Path(source_path)
    if not source.is_file():
        raise ErrataDocumentError(f"errata document does not exist: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ErrataDocumentError(
            f"{source}: unsupported suffix {suffix!r}; this module genuinely extracts only "
            f"{', '.join(SUPPORTED_SUFFIXES)}"
        )

    page_count: Optional[int] = None
    has_real_pages = False
    if suffix == ".pdf":
        pages, tool_version = _extract_pdf_pages(source)
        page_count = len(pages)
        has_real_pages = True
        extraction = {"tool": "pypdf", "tool_version": tool_version, "method": "pdf_errata_scan"}
    else:
        pages = [source.read_text(encoding="utf-8", errors="replace")]
        extraction = {"tool": "builtin", "tool_version": None, "method": "pre_extracted_text_errata_scan"}

    errata = _find_errata(pages, has_real_pages)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    json_path = out / f"{stem}.errata_index.json"
    md_path = out / f"{stem}.errata_index.md"

    record: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "doc_kind": doc_kind,
        "title": title or stem,
        "source_document": {
            "path": str(source),
            "sha256": _sha256_file(source),
            "bytes": source.stat().st_size,
            "page_count": page_count,
        },
        "extraction": extraction,
        "errata": errata,
        "erratum_count": len(errata),
    }

    md_text = _render_errata_markdown(record)
    md_path.write_text(md_text, encoding="utf-8")
    record["structure_map"] = {
        "path": str(md_path),
        "sha256": _sha256_text(md_text),
        "bytes": len(md_text.encode("utf-8")),
    }

    json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def load_errata_document(path) -> Dict[str, Any]:
    """Load a `.errata_index.json` produced by extract_errata_document().
    Raises ErrataDocumentError on a record that is not one."""
    p = Path(path)
    try:
        record = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErrataDocumentError(f"{p}: not a readable JSON errata-index record: {exc}") from exc
    if not isinstance(record, dict):
        raise ErrataDocumentError(f"{p}: errata-index record must be a JSON object, got {type(record).__name__}")
    for required in _REQUIRED_RECORD_FIELDS:
        if required not in record:
            raise ErrataDocumentError(
                f"{p}: not a dut_errata_correlation errata-index record -- missing {required!r}. "
                "Produce it with `python -m dv_harness.dut_errata_correlation extract`."
            )
    return record


# ---------------------------------------------------------------------------
# Correlation -- reuses dut_evidence_correlation.py's own per-citation
# verdict, rolled up per erratum.
# ---------------------------------------------------------------------------

def _correlate_citation(name: str, dut_facts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if dut_facts is None:
        return {
            "item_id": name, "fact_type": "feature", "name": name,
            "status": dec.STATUS_NOT_AVAILABLE,
            "reason": "no env.manifest.json is available for this project -- dut_facts unknown, never guessed",
            "layers_searched": [], "layer_status": {}, "exact_matches": [], "fuzzy_matches": [],
            "contradictions": [], "warnings": [],
        }
    item = {"item_id": name, "fact_type": "feature", "name": name}
    return dec.correlate_item(item, dut_facts)


def correlate_erratum_to_rtl(erratum: Dict[str, Any], manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Correlates ONE errata_index.json erratum entry's own cited
    affected-component names against `manifest`'s dut_facts (or reports the
    honest NOT_AVAILABLE/NO_AFFECTED_COMPONENT_CITED cases -- see this
    module's docstring for exactly what earns each of the five statuses)."""
    dut_facts = (manifest or {}).get("dut_facts") if manifest is not None else None
    components = erratum.get("affected_components") or []
    citations = [_correlate_citation(c["name"], dut_facts) for c in components]
    statuses = {c["status"] for c in citations}

    if not components:
        correlation_status = STATUS_NO_AFFECTED_COMPONENT_CITED
        reason = ("this erratum's own text cited no affected block/register/signal/module -- "
                  "nothing to correlate against RTL")
    elif statuses <= {dec.STATUS_NOT_AVAILABLE}:
        correlation_status = STATUS_NOT_AVAILABLE
        reason = ("no env.manifest.json was available to correlate this erratum's affected-component "
                  "citation(s) against -- never collapsed into RTL_NOT_LOCATED")
    elif dec.STATUS_RTL_CONFIRMED in statuses or dec.STATUS_RTL_CONTRADICTS_SPEC in statuses:
        located = [c for c in citations
                   if c["status"] in (dec.STATUS_RTL_CONFIRMED, dec.STATUS_RTL_CONTRADICTS_SPEC)]
        correlation_status = STATUS_RTL_LOCATED
        reason = f"{len(located)} affected-component citation(s) matched real RTL/register evidence exactly"
    elif dec.STATUS_RTL_PARTIAL in statuses:
        correlation_status = STATUS_RTL_PARTIALLY_LOCATED
        reason = ("no exact match; at least one affected-component citation has an unproven substring "
                  "match in RTL/register evidence")
    else:
        correlation_status = STATUS_RTL_NOT_LOCATED
        reason = ("every affected-component citation was searched against available dut_facts evidence "
                  "and none was found -- a real negative")

    return {
        "erratum_id": erratum.get("erratum_id"),
        "title": erratum.get("title"),
        "page": erratum.get("page"),
        "correlation_status": correlation_status,
        "reason": reason,
        "citations": citations,
        "revisions_affected": erratum.get("revisions_affected", []),
        "has_workaround": erratum.get("has_workaround"),
        "status": erratum.get("status"),
        "excerpt": erratum.get("excerpt"),
    }


def correlate_errata(errata: Sequence[Dict[str, Any]], manifest_path) -> Dict[str, Any]:
    """Correlates a list of already-extracted errata entries (e.g. from a
    real `.errata_index.json`'s `errata` list) against `manifest_path`.
    Mirrors dut_evidence_correlation.correlate()'s own disk-loading
    contract: a missing manifest path reports NOT_AVAILABLE for every
    erratum with a cited component, never a guess; a manifest that exists
    but fails schema validation propagates env_manifest.EnvManifestValidationError."""
    manifest: Optional[Dict[str, Any]]
    if manifest_path is None or not Path(manifest_path).is_file():
        manifest = None
    else:
        manifest = env_manifest.load_env_manifest(manifest_path)

    results = [correlate_erratum_to_rtl(e, manifest) for e in errata]
    summary = {s: 0 for s in ERRATUM_CORRELATION_STATUSES}
    for r in results:
        summary[r["correlation_status"]] += 1

    report: Dict[str, Any] = {
        "manifest_path": str(manifest_path) if manifest_path is not None else None,
        "manifest_status": "LOADED" if manifest is not None else "NOT_AVAILABLE",
        "errata": results,
        "erratum_count": len(results),
        "summary": summary,
    }
    if manifest is None and manifest_path is not None:
        report["manifest_reason"] = f"env.manifest.json does not exist at {manifest_path}"
    return report


def analyze_errata(source_path: Optional[str], manifest_path, out_dir=None, *,
                    title: Optional[str] = None) -> Dict[str, Any]:
    """The one-shot front door: extract structural errata facts from
    `source_path` (or honestly report `NOT_AVAILABLE` when none is supplied
    or the extraction itself genuinely fails) and correlate every extracted
    erratum's affected-component citations against `manifest_path`'s
    dut_facts. This is the function this task's own "reporting NOT_AVAILABLE
    honestly when no errata document is supplied" requirement is enforced
    by: a `source_path` of `None`/empty produces the honest top-level
    NOT_AVAILABLE without ever attempting to open anything."""
    empty_summary = {s: 0 for s in ERRATUM_CORRELATION_STATUSES}
    if not source_path:
        return {
            "status": STATUS_NOT_AVAILABLE,
            "reason": "no errata/known-issues document was supplied",
            "source_document": None,
            "manifest_path": str(manifest_path) if manifest_path else None,
            "manifest_status": None,
            "errata": [],
            "erratum_count": 0,
            "summary": empty_summary,
            "structure_map": None,
        }
    try:
        doc_record = extract_errata_document(source_path, out_dir, title=title)
    except ErrataDocumentError as exc:
        return {
            "status": STATUS_NOT_AVAILABLE,
            "reason": str(exc),
            "source_document": str(source_path),
            "manifest_path": str(manifest_path) if manifest_path else None,
            "manifest_status": None,
            "errata": [],
            "erratum_count": 0,
            "summary": empty_summary,
            "structure_map": None,
        }

    correlation = correlate_errata(doc_record["errata"], manifest_path)
    return {
        "status": "ANALYZED",
        "reason": None,
        "source_document": doc_record["source_document"],
        "manifest_path": correlation["manifest_path"],
        "manifest_status": correlation["manifest_status"],
        "manifest_reason": correlation.get("manifest_reason"),
        "errata": correlation["errata"],
        "erratum_count": correlation["erratum_count"],
        "summary": correlation["summary"],
        "structure_map": doc_record.get("structure_map"),
    }


# ---------------------------------------------------------------------------
# CLI front door -- python -m dv_harness.dut_errata_correlation
# (no dv-harness verb: cli.py/gates.py are out of scope for this batch --
# several very recent same-day modules in this repo make the identical
# disclosed choice; the standalone python -m front door is the sanctioned
# fallback.)
# ---------------------------------------------------------------------------

def _format_extract_report(record: Dict[str, Any]) -> str:
    ext = record["extraction"]
    lines = [
        f"doc_kind             : {record['doc_kind']}",
        f"title                : {record['title']}",
        f"source               : {record['source_document']['path']}",
        f"page_count           : {record['source_document']['page_count']}",
        f"extractor            : {ext['tool']} {ext['tool_version'] or ''} (method {ext['method']})",
        f"errata detected      : {record['erratum_count']}",
        f"structure_map        : {record['structure_map']['path']}",
    ]
    for e in record["errata"]:
        comps = ", ".join(c["name"] for c in e["affected_components"]) or "(none cited)"
        lines.append(f"  [{e['erratum_id']}] {e['title']} -- affects: {comps}")
    return "\n".join(lines)


def _format_correlate_report(report: Dict[str, Any]) -> str:
    lines = [f"manifest_status : {report['manifest_status']}"]
    for r in report["errata"]:
        lines.append(f"  [{r['erratum_id']}] {r['title']!r:40s} {r['correlation_status']:26s} {r['reason']}")
    lines.append(f"\nsummary: {report['summary']}")
    return "\n".join(lines)


def _format_analyze_report(report: Dict[str, Any]) -> str:
    if report["status"] == STATUS_NOT_AVAILABLE:
        return f"NOT_AVAILABLE: {report['reason']}"
    lines = [f"manifest_status : {report['manifest_status']}",
             f"erratum_count   : {report['erratum_count']}"]
    for r in report["errata"]:
        lines.append(f"  [{r['erratum_id']}] {r['title']!r:40s} {r['correlation_status']:26s} {r['reason']}")
    lines.append(f"\nsummary: {report['summary']}")
    return "\n".join(lines)


def execute_verb(verb: str, *, source_path: Optional[str] = None, out_dir: Optional[str] = None,
                  errata_index_path: Optional[str] = None, manifest_path: Optional[str] = None,
                  record_path: Optional[str] = None, title: Optional[str] = None,
                  doc_kind: str = "errata_sheet", as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.dut_errata_correlation`.
    Returns `(text, exit_code)`. Exit codes are deliberately per-verb honest
    signals, never a single collapsed pass/fail:
      extract   : 0 EXTRACTED, 2 NOT_AVAILABLE (unreadable/missing source)
      correlate : 0 clean, 1 a real RTL_NOT_LOCATED finding exists,
                  2 nothing could be correlated at all (NOT_AVAILABLE for
                  every erratum with a citation, or zero errata)
      analyze   : 0 clean, 1 a real RTL_NOT_LOCATED finding exists,
                  2 NOT_AVAILABLE (no source supplied, or extraction failed,
                  or nothing could be correlated)
      show      : 0 always (a display-only verb)
    """
    if verb == "extract":
        if not source_path or not out_dir:
            return "extract requires --source and --out-dir", 2
        try:
            record = extract_errata_document(source_path, out_dir, title=title, doc_kind=doc_kind)
        except ErrataDocumentError as exc:
            report = {"status": STATUS_NOT_AVAILABLE, "reason": str(exc), "source_document": str(source_path)}
            text = json.dumps(report, indent=2, ensure_ascii=False) if as_json else f"NOT_AVAILABLE: {exc}"
            return text, 2
        report = dict(record)
        report["status"] = "EXTRACTED"
        text = json.dumps(report, indent=2, ensure_ascii=False) if as_json else _format_extract_report(record)
        return text, 0

    if verb == "correlate":
        if not errata_index_path:
            return "correlate requires --errata-index", 2
        try:
            doc_record = load_errata_document(errata_index_path)
        except ErrataDocumentError as exc:
            return f"NOT_AVAILABLE: {exc}", 2
        try:
            report = correlate_errata(doc_record["errata"], manifest_path)
        except env_manifest.EnvManifestValidationError as exc:
            return f"env.manifest.json failed validation: {exc}", 2
        text = json.dumps(report, indent=2, ensure_ascii=False) if as_json else _format_correlate_report(report)
        if report["manifest_status"] == "NOT_AVAILABLE" or report["erratum_count"] == 0:
            return text, 2
        if report["summary"][STATUS_RTL_NOT_LOCATED]:
            return text, 1
        return text, 0

    if verb == "analyze":
        try:
            report = analyze_errata(source_path, manifest_path, out_dir, title=title)
        except env_manifest.EnvManifestValidationError as exc:
            return f"env.manifest.json failed validation: {exc}", 2
        text = json.dumps(report, indent=2, ensure_ascii=False) if as_json else _format_analyze_report(report)
        if report["status"] == STATUS_NOT_AVAILABLE:
            return text, 2
        if report["summary"][STATUS_RTL_NOT_LOCATED]:
            return text, 1
        if report.get("manifest_status") == "NOT_AVAILABLE" or report["erratum_count"] == 0:
            return text, 2
        return text, 0

    if verb == "show":
        if not record_path:
            return "show requires --record", 2
        try:
            record = load_errata_document(record_path)
        except ErrataDocumentError as exc:
            return f"NOT_AVAILABLE: {exc}", 2
        text = json.dumps(record, indent=2, ensure_ascii=False) if as_json else _format_extract_report(record)
        return text, 0

    return f"unknown verb {verb!r}; expected 'extract', 'correlate', 'analyze' or 'show'", 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.dut_errata_correlation",
        description="Discovers/parses a DUT errata/known-issues document into a structure-only "
                    "index and correlates each erratum's cited affected block/register/signal/module "
                    "against real RTL/register-map evidence. Reports NOT_AVAILABLE honestly when no "
                    "errata document is supplied.")
    sub = ap.add_subparsers(dest="verb", required=True)

    ex = sub.add_parser("extract", help="Extract a structural errata index from one source document.")
    ex.add_argument("--source", required=True, dest="source_path")
    ex.add_argument("--out-dir", required=True, dest="out_dir")
    ex.add_argument("--title")
    ex.add_argument("--doc-kind", default="errata_sheet")
    ex.add_argument("--json", action="store_true")

    co = sub.add_parser("correlate", help="Correlate an already-extracted errata index against a manifest.")
    co.add_argument("--errata-index", required=True, dest="errata_index_path")
    co.add_argument("--manifest", dest="manifest_path")
    co.add_argument("--json", action="store_true")

    an = sub.add_parser("analyze", help="One-shot: extract + correlate. --source may be omitted.")
    an.add_argument("--source", dest="source_path")
    an.add_argument("--out-dir", dest="out_dir")
    an.add_argument("--manifest", dest="manifest_path")
    an.add_argument("--title")
    an.add_argument("--json", action="store_true")

    sh = sub.add_parser("show", help="Print an already-extracted errata_index.json record.")
    sh.add_argument("--record", required=True, dest="record_path")
    sh.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)
    text, code = execute_verb(
        a.verb,
        source_path=getattr(a, "source_path", None), out_dir=getattr(a, "out_dir", None),
        errata_index_path=getattr(a, "errata_index_path", None),
        manifest_path=getattr(a, "manifest_path", None),
        record_path=getattr(a, "record_path", None),
        title=getattr(a, "title", None), doc_kind=getattr(a, "doc_kind", "errata_sheet"),
        as_json=a.json,
    )
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
