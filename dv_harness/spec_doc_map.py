"""dv_harness/spec_doc_map.py -- offline STRUCTURAL distiller for non-VIP DUT
documents: specifications, datasheets, and programming guides.

THE GAP THIS CLOSES. `vip_user_guide_distill.py` already turns a VIP user
guide PDF into a bounded, offline reference artifact -- a real `pypdf`
extraction, a mechanically-detected numbered-heading section index, and the
discipline of never inlining prose into a Tier-2 always-resident manifest.
Nothing in this repo did the analogous thing for the OTHER document family a
verification environment is built from: the DUT's own spec/datasheet/
programming-guide PDFs. `env_manifest.py`'s Tier-1 policy already denies raw
PDF originals into runtime context and names `vip_user_guide_distill.py` as
the route forward for a VIP user guide -- but a DUT spec PDF has no route at
all, and an agent asking "what page is the register map chapter on" or "where
is Table 4-3" had no bounded artifact to answer from and no honest way to get
one short of opening the whole PDF.

WHY THIS IS A SEPARATE MODULE, and deliberately does not import from or edit
`vip_user_guide_distill.py`. Two real reasons, not one:
  1. Scope. This task's contract narrows the extraction to structure ONLY --
     chapter/section titles, table locations, register-chapter page ranges --
     and never a full-text extract, even as a targeted-read byproduct.
     `vip_user_guide_distill.py`'s own contract is wider by design: it ALWAYS
     also writes a `.fulltext.txt` (its own "TARGETED-READ target, never a
     context load"). Calling into that module's public
     `distill_user_guide()` to get this module's section index would also
     always produce a full-text prose file this module's own contract forbids
     ever writing, and there is no narrower public entry point in that module
     to call instead -- its per-page extraction and heading scan are private.
  2. Independent testability (batch file-safety rule). This module is one of
     several independently-developed additions landing in the same session;
     importing another module's PRIVATE helpers to avoid re-deriving ~15 lines
     of straightforward `pypdf` usage would be a fragile coupling for no real
     reuse benefit, whereas the two modules' PUBLIC surfaces genuinely do not
     overlap (this module never touches `.reference.json`/`.reference.md`/
     `.fulltext.txt`, and produces its own `.structure_map.json`/
     `.structure_map.md` pair instead).
  So: this module EXTENDS THE PATTERN (the same real `pypdf.PdfReader(...).
  pages[i].extract_text()` call, the same "raise rather than silently produce
  an empty/partial artifact" discipline, the same mechanically-detected
  numbered-heading regex idea) rather than the module. `vip_user_guide_distill.
  py` itself is untouched -- not one line.

WHAT LANDS WHERE, and why prose lands nowhere. Two artifacts per document,
both structure-only:

  <stem>.structure_map.json   the machine-readable record: section index
                              (heading/number/level/page), table-caption
                              index (number/caption/page), and
                              register-chapter page ranges. No document body
                              text appears in this file, ever -- unlike
                              `vip_user_guide_distill.py`'s record, which
                              POINTS AT a full-text extract this module
                              deliberately never produces.
  <stem>.structure_map.md     the same content rendered as a human-readable
                              navigation table -- still zero body prose.

Neither artifact is a context load by construction: there is no full-text
byproduct at all for a generation-time read to accidentally pull in, and the
two structure artifacts together are still small (headings and captions are
each capped at ~120 characters), so even loading the whole `.json` record
stays far short of a document dump. This is the same Tier-1/Tier-2
context-budget discipline `vip_user_guide_distill.py` and `context_budget.py`
already establish, applied to a narrower artifact contract.

WHY A MECHANICAL SCAN AND NOT A PROSE SUMMARY. Exactly `vip_user_guide_distill.
py`'s own reasoning, restated for this document family rather than
re-invented: a numbered heading ("4.3.1 Link Training"), a chapter heading
("Chapter 4: Register Map"), and a table caption ("Table 4-1: Register
Summary") are each a real, verifiable, reproducible property of the
document's OWN text, detected by pattern -- never an interpretation of it.
Register-CHAPTER page ranges are likewise mechanical: a chapter whose own
title contains a register/CSR keyword, bounded by that chapter's own
detected start page and the next detected chapter's start page. Nothing here
guesses which registers exist or what a table contains -- only where the
chapter/table IS.

EXTRACTOR HONESTY, and the module's one hard stop condition. A `.pdf` source
requires `pypdf`; when it is not installed, `extract_spec_doc_map()` raises
`SpecDocMapError` naming the real missing dependency rather than silently
producing an empty or partial structure map (the same discipline
`vip_user_guide_distill.py`'s own `UserGuideDistillError` enforces). A missing
source file and an unsupported suffix raise the same way. `execute_verb()` --
the CLI/reporting layer -- is what turns that raise into the honest
`status: "NOT_AVAILABLE"` this task's contract requires: "Absent/unreadable
PDF reports NOT_AVAILABLE with the real reason," carrying the exact exception
text rather than a generic failure. A `.txt`/`.md` source (an
already-extracted plain-text document) is read directly and records
`method="pre_extracted_text_structure_scan"`; page numbers are honestly
`null` on that path, since no real page boundary exists to report -- never a
fabricated page count.

DELIBERATELY BOUNDED, and stated rather than implied closed. (1) Heading and
table-caption detection is a line-pattern scan, not a layout/typography
analysis: a document whose headings are set in body-sized text with no
numbering this scan can detect (a bare "Overview" with no leading number, no
"Chapter" keyword) contributes nothing to the section index, and that is
reported as a real zero rather than guessed at. (2) Register-chapter ranges
are computed only over CHAPTER-level headings (a heading whose detected
number has no dot, e.g. "4" or "Chapter 4" -- never "4.3.1"); a
register-titled SUBSECTION still appears in the section index but is not
itself given its own page range, because a subsection's true end is another
subsection's start, which this module does not attempt to disambiguate from
a subsection that merely continues the same chapter. (3) Table CONTENT (rows,
columns, field names) is never read -- only the caption line and its page.
(4) This module decides nothing beyond reporting: no build, job, approval, or
stage gate is touched, and there is no stage-gate entry for it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"

#: Suffixes this module can genuinely extract structure from. Narrower than
#: doc_extraction.SUPPORTED for the identical reason vip_user_guide_distill.py
#: states for its own SUPPORTED_SUFFIXES -- claiming a format this module
#: cannot actually read would be a capability claim it cannot honour.
SUPPORTED_SUFFIXES = (".pdf", ".txt", ".md")

#: Numbered heading, e.g. "4", "4.3", "4.3.1" followed by a title. Anchored
#: and length-bounded so a body sentence beginning with a figure/table
#: reference ("4.3 shows the register layout") does not masquerade as a
#: heading -- a real heading line is short and does not end in sentence
#: punctuation. Mirrors vip_user_guide_distill.py's own heading regex.
_NUMBERED_HEADING_RE = re.compile(r"^\s{0,8}(?P<number>\d+(?:\.\d+){0,4})\.?\s+(?P<title>\S.{0,110})$")

#: "Chapter N: Title" / "Chapter N - Title" heading, the other real
#: chapter-numbering convention DUT spec/programming-guide documents use.
_CHAPTER_HEADING_RE = re.compile(
    r"^\s{0,8}Chapter\s+(?P<number>\d+)\s*[:.\-]?\s+(?P<title>\S.{0,110})$", re.IGNORECASE)

#: "Table 4-1: Caption" / "Table 4.1 Caption" -- the real, conventional table
#: caption shape in this document family. Anchored the same way as the
#: heading regexes, for the same reason.
_TABLE_CAPTION_RE = re.compile(
    r"^\s{0,8}Table\s+(?P<number>[0-9]+(?:[.\-][0-9]+)*)\s*[:.\-]?\s+(?P<caption>\S.{0,110})$", re.IGNORECASE)

#: Longest heading/caption text retained. A "heading" longer than this is a
#: wrapped body paragraph that happened to start with a number, not a title.
_MAX_HEADING_CHARS = 120
_MAX_CAPTION_CHARS = 130

#: A chapter TITLE containing one of these (word-boundary, case-insensitive)
#: is a register chapter. Deliberately narrow and word-bounded so "Chapter 9
#: Registration Procedures" (an unrelated administrative chapter some
#: programming guides carry) is not mistaken for a register-map chapter.
_REGISTER_CHAPTER_RE = re.compile(r"\b(registers?|register\s+map|csr)\b", re.IGNORECASE)

#: Fields a real structure_map.json record must carry -- checked by
#: load_spec_doc_map() so a caller cannot be pointed at an arbitrary JSON file
#: and have it quietly accepted as a real structure-map record.
_REQUIRED_RECORD_FIELDS = (
    "schema_version", "doc_kind", "title", "source_document", "extraction",
    "sections", "tables", "register_chapters", "section_count", "table_count",
    "register_chapter_count", "structure_map",
)


class SpecDocMapError(RuntimeError):
    """Structural extraction could not be performed against a real source
    document -- an unsupported suffix, a missing file, or a missing real
    extractor dependency. Raised rather than returning a partial/empty
    structure map, because a record that silently describes zero sections is
    indistinguishable from a real document that genuinely has none.

    `execute_verb()` (the CLI/reporting layer) is what turns this into this
    task's required honest `NOT_AVAILABLE` status carrying this exception's
    own real reason text -- the raise/report split is deliberate, mirroring
    vip_user_guide_distill.UserGuideDistillError's own contract."""


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
    """Returns `(pages, pypdf_version)`, one plain-text string per PDF page in
    page order, extracted by the REAL pypdf library -- the same call
    (`pypdf.PdfReader(str(path))`, `page.extract_text()`) vip_user_guide_
    distill.py's own private `_extract_pdf_pages()` makes, re-derived here
    rather than imported per this module's own docstring (scope +
    independent-testability). Raises SpecDocMapError when pypdf is not
    installed -- never a silent empty extraction."""
    try:
        import pypdf
    except ImportError as exc:
        raise SpecDocMapError(
            f"cannot extract {path}: the 'pypdf' package is not installed. Install it, or "
            "pre-extract the document to a .txt and map that instead (the structure map will "
            "honestly record method='pre_extracted_text_structure_scan' and page=null)."
        ) from exc
    reader = pypdf.PdfReader(str(path))
    return [(page.extract_text() or "") for page in reader.pages], getattr(pypdf, "__version__", None)


def _find_structure(pages: Sequence[str], has_real_pages: bool) -> Tuple[List[dict], List[dict]]:
    """Scan `pages` (one string per real PDF page, or a single string holding
    the whole pre-extracted text) for numbered/Chapter headings and Table
    captions. Returns `(sections, tables)` in document order. `page` is the
    real 1-based page number when `has_real_pages`, else honestly `None` --
    never a fabricated page count for a text source with no real pages."""
    sections: List[dict] = []
    tables: List[dict] = []
    for page_idx, page_text in enumerate(pages):
        page_no = (page_idx + 1) if has_real_pages else None
        for raw_line in page_text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            m = _NUMBERED_HEADING_RE.match(stripped)
            if m and len(stripped) <= _MAX_HEADING_CHARS and not stripped.endswith((".", ",", ";", ":")):
                number = m.group("number")
                sections.append({
                    "heading": stripped,
                    "title": m.group("title"),
                    "number": number,
                    "level": number.count(".") + 1,
                    "page": page_no,
                })
                continue
            m2 = _CHAPTER_HEADING_RE.match(stripped)
            if m2 and len(stripped) <= _MAX_HEADING_CHARS:
                sections.append({
                    "heading": stripped,
                    "title": m2.group("title"),
                    "number": m2.group("number"),
                    "level": 1,
                    "page": page_no,
                })
                continue
            m3 = _TABLE_CAPTION_RE.match(stripped)
            if m3 and len(stripped) <= _MAX_CAPTION_CHARS:
                tables.append({
                    "number": m3.group("number"),
                    "caption": stripped,
                    "page": page_no,
                })
    return sections, tables


def _compute_register_chapter_ranges(sections: Sequence[dict], page_count: Optional[int],
                                      has_real_pages: bool) -> List[dict]:
    """Chapter-level (`level == 1`) headings only -- see this module's
    docstring for why a register SUBSECTION is not itself given a range. A
    chapter's page range runs from its own detected start page to the page
    before the NEXT chapter's start page, or to the document's last page for
    the final chapter. Honestly `None` on a source with no real pages."""
    chapters = [s for s in sections if s["level"] == 1]
    ranges: List[dict] = []
    for i, ch in enumerate(chapters):
        if not _REGISTER_CHAPTER_RE.search(ch["title"]):
            continue
        start_page = ch["page"]
        end_page = None
        if has_real_pages and start_page is not None:
            if i + 1 < len(chapters) and chapters[i + 1]["page"] is not None:
                end_page = max(start_page, chapters[i + 1]["page"] - 1)
            else:
                end_page = page_count
        ranges.append({
            "heading": ch["heading"],
            "number": ch["number"],
            "start_page": start_page,
            "end_page": end_page,
        })
    return ranges


def _render_structure_markdown(record: dict) -> str:
    src = record["source_document"]
    ext = record["extraction"]
    lines = [
        f"# {record['title']} -- structural document map",
        "",
        "Mechanically generated by `dv_harness/spec_doc_map.py`. This file records STRUCTURE ONLY --",
        "chapter/section titles, table locations, and register-chapter page ranges. It contains no",
        "body prose from the source document; nothing here is an interpretation of what the document",
        "says.",
        "",
        f"- Document kind: `{record['doc_kind']}`",
        f"- Source document: `{src['path']}`",
        f"- Source sha256: `{src['sha256']}`",
        f"- Source bytes: {src['bytes']}",
        f"- Page count: {src['page_count'] if src['page_count'] is not None else 'null (text source -- no pages)'}",
        f"- Extractor: `{ext['tool']}` {ext['tool_version'] or '(version unreported)'} "
        f"(method `{ext['method']}`)",
        f"- Sections detected: {len(record['sections'])}",
        f"- Tables detected: {len(record['tables'])}",
        f"- Register chapters detected: {len(record['register_chapters'])}",
        "",
        "## Section index",
        "",
    ]
    if not record["sections"]:
        lines.append("_No numbered chapter/section headings were detected in this document._ That is a "
                     "real observation about the source, not an extraction failure.")
    else:
        lines.append("| Section | Page |")
        lines.append("|---|---|")
        for s in record["sections"]:
            lines.append(f"| {s['heading']} | {s['page'] if s['page'] is not None else ''} |")
    lines.append("")
    lines.append("## Table locations")
    lines.append("")
    if not record["tables"]:
        lines.append("_No table captions were detected in this document._")
    else:
        lines.append("| Table | Page |")
        lines.append("|---|---|")
        for t in record["tables"]:
            lines.append(f"| {t['caption']} | {t['page'] if t['page'] is not None else ''} |")
    lines.append("")
    lines.append("## Register-chapter page ranges")
    lines.append("")
    if not record["register_chapters"]:
        lines.append("_No chapter heading matched a register/CSR keyword._ That is a real observation "
                     "about the source, not an extraction failure.")
    else:
        lines.append("| Chapter | Start page | End page |")
        lines.append("|---|---|---|")
        for r in record["register_chapters"]:
            sp = r["start_page"] if r["start_page"] is not None else ""
            ep = r["end_page"] if r["end_page"] is not None else ""
            lines.append(f"| {r['heading']} | {sp} | {ep} |")
    lines.append("")
    return "\n".join(lines)


def extract_spec_doc_map(source_path, out_dir, *, title: Optional[str] = None,
                          doc_kind: str = "dut_spec") -> dict:
    """Distil ONE real DUT spec/datasheet/programming-guide document into the
    two structure-only artifacts described in this module's docstring, and
    return the `.structure_map.json` record.

    `doc_kind` names what the document actually is (`dut_spec`, `datasheet`,
    `programming_guide`, `register_reference`, ...) -- free text, like
    vip_user_guide_distill.py's own `doc_kind`, so a later reader is never
    left guessing which of a project's documents a record points at."""
    source = Path(source_path)
    if not source.is_file():
        raise SpecDocMapError(f"source document does not exist: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise SpecDocMapError(
            f"{source}: unsupported suffix {suffix!r}; this module genuinely extracts only "
            f"{', '.join(SUPPORTED_SUFFIXES)}"
        )

    page_count: Optional[int] = None
    has_real_pages = False
    if suffix == ".pdf":
        pages, tool_version = _extract_pdf_pages(source)
        page_count = len(pages)
        has_real_pages = True
        extraction = {"tool": "pypdf", "tool_version": tool_version, "method": "pdf_structure_scan"}
    else:
        pages = [source.read_text(encoding="utf-8", errors="replace")]
        extraction = {"tool": "builtin", "tool_version": None, "method": "pre_extracted_text_structure_scan"}

    sections, tables = _find_structure(pages, has_real_pages)
    register_chapters = _compute_register_chapter_ranges(sections, page_count, has_real_pages)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    json_path = out / f"{stem}.structure_map.json"
    md_path = out / f"{stem}.structure_map.md"

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
        "sections": sections,
        "tables": tables,
        "register_chapters": register_chapters,
        "section_count": len(sections),
        "table_count": len(tables),
        "register_chapter_count": len(register_chapters),
    }

    md_text = _render_structure_markdown(record)
    md_path.write_text(md_text, encoding="utf-8")
    record["structure_map"] = {
        "path": str(md_path),
        "sha256": _sha256_text(md_text),
        "bytes": len(md_text.encode("utf-8")),
    }

    json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def load_spec_doc_map(path) -> dict:
    """Load a `.structure_map.json` produced by extract_spec_doc_map(). Raises
    SpecDocMapError on a record that is not one, so a caller cannot be
    pointed at an arbitrary JSON file and have it quietly accepted as a real
    structure-map record."""
    p = Path(path)
    try:
        record = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecDocMapError(f"{p}: not a readable JSON structure-map record: {exc}") from exc
    if not isinstance(record, dict):
        raise SpecDocMapError(f"{p}: structure-map record must be a JSON object, got {type(record).__name__}")
    for required in _REQUIRED_RECORD_FIELDS:
        if required not in record:
            raise SpecDocMapError(
                f"{p}: not a spec_doc_map structure-map record -- missing {required!r}. Produce it "
                "with `python -m dv_harness.spec_doc_map extract`."
            )
    return record


def _format_report(record: dict) -> str:
    ext = record["extraction"]
    lines = [
        f"doc_kind             : {record['doc_kind']}",
        f"title                : {record['title']}",
        f"source               : {record['source_document']['path']}",
        f"page_count           : {record['source_document']['page_count']}",
        f"extractor            : {ext['tool']} {ext['tool_version'] or ''} (method {ext['method']})",
        f"sections             : {record['section_count']}",
        f"tables               : {record['table_count']}",
        f"register_chapters    : {record['register_chapter_count']}",
        f"structure_map        : {record['structure_map']['path']}",
    ]
    if record.get("register_chapters"):
        lines.append("")
        lines.append("register-chapter page ranges:")
        for r in record["register_chapters"]:
            lines.append(f"  [{r['start_page']}-{r['end_page']}] {r['heading']}")
    return "\n".join(lines)


def execute_verb(verb: str, *, source_path: Optional[str] = None, out_dir: Optional[str] = None,
                  record_path: Optional[str] = None, title: Optional[str] = None,
                  doc_kind: str = "dut_spec", as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.spec_doc_map` (no
    `dv-harness` CLI verb was wired -- see this module's disclosed residual;
    the ad hoc front door is the sanctioned fallback the house style already
    uses for several recent modules). Returns `(text, exit_code)`:
    0 EXTRACTED/shown, 2 NOT_AVAILABLE or a usage error -- 2 is deliberately
    the ONLY non-zero exit code here: an absent/unreadable document is an
    honest, expected outcome (this task's own required contract), not a
    distinct failure class needing its own code."""
    if verb == "extract":
        if not source_path or not out_dir:
            return "extract requires --source and --out-dir", 2
        try:
            record = extract_spec_doc_map(source_path, out_dir, title=title, doc_kind=doc_kind)
        except SpecDocMapError as exc:
            report = {"status": "NOT_AVAILABLE", "reason": str(exc), "source_document": str(source_path)}
            text = json.dumps(report, indent=2, ensure_ascii=False) if as_json else f"NOT_AVAILABLE: {exc}"
            return text, 2
        report = dict(record)
        report["status"] = "EXTRACTED"
        text = json.dumps(report, indent=2, ensure_ascii=False) if as_json else _format_report(record)
        return text, 0
    if verb == "show":
        if not record_path:
            return "show requires --record", 2
        try:
            record = load_spec_doc_map(record_path)
        except SpecDocMapError as exc:
            return f"NOT_AVAILABLE: {exc}", 2
        text = json.dumps(record, indent=2, ensure_ascii=False) if as_json else _format_report(record)
        return text, 0
    return f"unknown verb {verb!r}; expected 'extract' or 'show'", 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.spec_doc_map",
        description="Offline STRUCTURAL distiller for non-VIP DUT spec/datasheet/programming-guide "
                    "documents: chapter/section titles, table locations, register-chapter page ranges. "
                    "Never extracts or persists full body prose.")
    sub = ap.add_subparsers(dest="verb", required=True)

    ex = sub.add_parser("extract", help="Extract a structure map from one source document.")
    ex.add_argument("--source", required=True, dest="source_path")
    ex.add_argument("--out-dir", required=True, dest="out_dir")
    ex.add_argument("--title")
    ex.add_argument("--doc-kind", default="dut_spec")
    ex.add_argument("--json", action="store_true")

    sh = sub.add_parser("show", help="Print an already-extracted structure_map.json record.")
    sh.add_argument("--record", required=True, dest="record_path")
    sh.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)
    text, code = execute_verb(
        a.verb, source_path=getattr(a, "source_path", None), out_dir=getattr(a, "out_dir", None),
        record_path=getattr(a, "record_path", None), title=getattr(a, "title", None),
        doc_kind=getattr(a, "doc_kind", "dut_spec"), as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
