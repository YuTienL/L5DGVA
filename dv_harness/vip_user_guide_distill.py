"""dv_harness/vip_user_guide_distill.py -- the OFFLINE VIP-user-guide
distiller behind env.manifest.json's `vip_config.user_guide_refs` sub-layer.

THE GAP THIS CLOSES (2026-09-04). The env.manifest.json spec's VIP layer
asks for the VIP user guide to be "distilled OFFLINE into a reference file,
never loaded into runtime context". A 2026-09-04 re-audit found no module
implementing it: `doc_extraction.py` is an identity/provenance index and
record-normalizer that contains no PDF text extraction at all (still true
after its 2026-09-04 ResearchEvidenceCard extension, which is likewise
identity-only), and `vip_distill.py` -- despite the name --
normalizes sim.log/job-record/fsdbreport RUNTIME evidence and never opens a
document. `.work/pdftxt/*.txt` are real PDF-derived text files, but they are
protocol SPEC documents and nothing wired them anywhere. So the whole bullet
was BLOCKED, not merely stubbed.

WHY THIS IS A SEPARATE MODULE AND A SEPARATE CLI COMMAND, not a step inside
`env-manifest generate`. "Offline" is the entire point of the requirement,
and it is enforced structurally rather than by intention: this module is the
only thing that ever opens the source document, it runs as its own
`dv-harness vip-user-guide distill` invocation, and `env_manifest.py` reads
only the small `.reference.json` record it leaves behind. A generation run
therefore cannot pull a user guide's text into context even by accident,
because the code path that could do so is not on it.

WHAT LANDS WHERE, and why the manifest gets the least of it. Three artifacts
are produced per document:

  <stem>.fulltext.txt   the complete extracted plain text. This is the
                        TARGETED-READ target, never a context load. It
                        exists so that "what does section 4.3 actually say"
                        has a real answer that does not require re-opening a
                        binary PDF.
  <stem>.reference.md   the bounded NAVIGATION AID: document metadata plus a
                        section index (heading -> page -> character offset
                        into the fulltext). This is the tier-3
                        load-on-demand artifact.
  <stem>.reference.json the machine-readable record `env_manifest.py`
                        consumes.

`env.manifest.json` itself records only the POINTERS from that record --
paths, sha256s, byte sizes, page count, section COUNT, and which extractor
produced them. Not the section headings, and emphatically not any document
prose. That is deliberate and load-bearing: CLAUDE.md's Context Budget makes
`.dv-harness/env.manifest.json` a TIER-2 ALWAYS-RESIDENT artifact, so any
text inlined into it is text pushed into every session's context window in
perpetuity -- which is precisely the outcome "never loaded into runtime
context" forbids. `env_manifest.assert_no_user_guide_body_in_manifest()`
turns that from a convention into a checkable property.

WHY A MECHANICAL SECTION INDEX AND NOT A PROSE SUMMARY. This module has no
LLM and does not pretend to. It detects numbered headings ("4.3.1 Link
Training") by pattern, which is a real, verifiable, reproducible property of
the document's own text -- not an interpretation of it. That is the same
discipline `vip_symbol_index.py` already established for VIP source in this
repo: the artifact answers "what exists, and where", and "what does it say"
is then ONE targeted read of a cited offset. A generated prose summary would
be this module inventing content, which the Evidence Truth Rule forbids and
which nothing downstream could verify.

EXTRACTOR HONESTY. A `.pdf` source requires `pypdf`; when it is not
installed this raises `UserGuideDistillError` rather than silently producing
an empty or partial reference. A `.txt` source (e.g. an already-extracted
`.work/pdftxt/*.txt`) is read directly and records `method="pre_extracted_
text"`, so a reader can always tell a real PDF extraction apart from a text
file someone handed us. Page numbers exist only for the PDF path and are
honestly `null` for the text path -- never a fabricated page count.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "1.0"

#: Suffixes this module can genuinely extract text from. Deliberately much
#: narrower than doc_extraction.SUPPORTED -- listing a format this module
#: cannot actually read would be a capability claim it cannot honour.
SUPPORTED_SUFFIXES = (".pdf", ".txt", ".md")

#: Numbered-heading detector, e.g. "4", "4.3", "4.3.1" followed by a title.
#: Anchored and length-bounded so a body sentence beginning with a figure
#: reference ("3.2 shows the ...") does not masquerade as a heading: a real
#: heading line is short and does not end in sentence punctuation.
_HEADING_RE = re.compile(r"^\s{0,8}(?P<number>\d+(?:\.\d+){0,4})\.?\s+(?P<title>\S.{0,110})$")

#: Longest heading text retained. A "heading" longer than this is a wrapped
#: body paragraph that happened to start with a number, not a section title.
_MAX_HEADING_CHARS = 120


class UserGuideDistillError(RuntimeError):
    """Distillation could not be performed against a real source document --
    an unsupported suffix, a missing file, or a missing real extractor
    dependency. Raised rather than returning a partial/empty reference,
    because a reference record that silently describes zero sections is
    indistinguishable from a real document that genuinely has none."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_pdf_pages(path: Path) -> tuple:
    """Returns `(pages, pypdf_version)` where `pages` is one plain-text
    string per PDF page in page order, extracted by the REAL pypdf library.
    Raises UserGuideDistillError when pypdf is not installed -- never a
    silent empty extraction."""
    try:
        import pypdf
    except ImportError as exc:
        raise UserGuideDistillError(
            f"cannot extract {path}: the 'pypdf' package is not installed. Install it, or pre-extract "
            "the PDF to a .txt and distil that instead (the reference record will honestly record "
            "method='pre_extracted_text' and page=null)."
        ) from exc
    reader = pypdf.PdfReader(str(path))
    return [(page.extract_text() or "") for page in reader.pages], getattr(pypdf, "__version__", None)


def _find_sections(full_text: str, page_starts: Optional[list]) -> list:
    """Scan `full_text` for numbered headings and return
    [{"heading", "number", "page", "char_offset"}, ...] in document order.

    `page_starts` is the character offset at which each page begins (PDF
    path only); when it is None every section reports page=null rather than
    a page number this module did not actually observe."""
    sections = []
    offset = 0
    for line in full_text.splitlines(keepends=True):
        stripped = line.strip()
        m = _HEADING_RE.match(stripped)
        if m and len(stripped) <= _MAX_HEADING_CHARS and not stripped.endswith((".", ",", ";", ":")):
            page = None
            if page_starts:
                # Number of page starts at or before this offset == 1-based page.
                page = sum(1 for s in page_starts if s <= offset) or None
            sections.append({
                "heading": stripped,
                "number": m.group("number"),
                "page": page,
                "char_offset": offset,
            })
        offset += len(line)
    return sections


def _render_reference_markdown(record: dict, sections: list) -> str:
    src = record["source_document"]
    lines = [
        f"# {record['title']} -- distilled reference index",
        "",
        "Mechanically generated by `dv_harness/vip_user_guide_distill.py`. This file is a NAVIGATION",
        "index, not a summary: every line below is a heading that literally appears in the source",
        "document. Nothing here is an interpretation of what the document says. To read a section,",
        "do ONE targeted read of the full-text extract at the cited character offset.",
        "",
        f"- Document kind: `{record['doc_kind']}`",
        f"- Source document: `{src['path']}`",
        f"- Source sha256: `{src['sha256']}`",
        f"- Source bytes: {src['bytes']}",
        f"- Page count: {src['page_count'] if src['page_count'] is not None else 'null (text source -- no pages)'}",
        f"- Extractor: `{record['extraction']['tool']}` "
        f"{record['extraction']['tool_version'] or '(version unreported)'} "
        f"(method `{record['extraction']['method']}`)",
        f"- Full-text extract: `{record['full_text_extract']['path']}`",
        f"- Sections detected: {len(sections)}",
        "",
        "## Section index",
        "",
    ]
    if not sections:
        lines.append("_No numbered headings were detected in this document._ That is a real observation "
                     "about the source, not an extraction failure -- read the full-text extract directly.")
    else:
        lines.append("| Section | Page | Char offset |")
        lines.append("|---|---|---|")
        for s in sections:
            page = s["page"] if s["page"] is not None else ""
            lines.append(f"| {s['heading']} | {page} | {s['char_offset']} |")
    lines.append("")
    return "\n".join(lines)


def distill_user_guide(source_path, out_dir, *, title: Optional[str] = None,
                       doc_kind: str = "vip_user_guide") -> dict:
    """Distil ONE real user-guide document into the three artifacts described
    in this module's docstring, and return the `.reference.json` record.

    `doc_kind` names what the document actually is (`vip_user_guide`,
    `protocol_spec`, `programming_guide`, ...) so a later reader is never
    left guessing which of a project's documents a reference points at."""
    source = Path(source_path)
    if not source.is_file():
        raise UserGuideDistillError(f"source document does not exist: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UserGuideDistillError(
            f"{source}: unsupported suffix {suffix!r}; this module genuinely extracts only "
            f"{', '.join(SUPPORTED_SUFFIXES)}"
        )

    page_starts = None
    page_count = None
    if suffix == ".pdf":
        pages, tool_version = _extract_pdf_pages(source)
        page_starts = []
        chunks = []
        cursor = 0
        for page_text in pages:
            page_starts.append(cursor)
            chunk = page_text if page_text.endswith("\n") else page_text + "\n"
            chunks.append(chunk)
            cursor += len(chunk)
        full_text = "".join(chunks)
        page_count = len(pages)
        extraction = {"tool": "pypdf", "tool_version": tool_version, "method": "pdf_text_extraction"}
    else:
        full_text = source.read_text(encoding="utf-8", errors="replace")
        extraction = {"tool": "builtin", "tool_version": None, "method": "pre_extracted_text"}

    sections = _find_sections(full_text, page_starts)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    fulltext_path = out / f"{stem}.fulltext.txt"
    reference_md_path = out / f"{stem}.reference.md"
    reference_json_path = out / f"{stem}.reference.json"

    fulltext_path.write_text(full_text, encoding="utf-8")

    record = {
        "schema_version": SCHEMA_VERSION,
        "doc_kind": doc_kind,
        "title": title or stem,
        "source_document": {
            "path": str(source),
            "sha256": _sha256_file(source),
            "bytes": source.stat().st_size,
            "page_count": page_count,
        },
        "full_text_extract": {
            "path": str(fulltext_path),
            "sha256": _sha256_text(full_text),
            "bytes": len(full_text.encode("utf-8")),
        },
        "extraction": extraction,
        "section_count": len(sections),
    }

    reference_md = _render_reference_markdown(record, sections)
    reference_md_path.write_text(reference_md, encoding="utf-8")
    record["distilled_reference"] = {
        "path": str(reference_md_path),
        "sha256": _sha256_text(reference_md),
        "bytes": len(reference_md.encode("utf-8")),
    }

    reference_json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def load_reference_record(path) -> dict:
    """Load a `.reference.json` produced by distill_user_guide(). Raises
    UserGuideDistillError on a record that is not one, so `env-manifest
    generate` cannot be pointed at an arbitrary JSON file and quietly record
    it as a distilled user-guide reference."""
    p = Path(path)
    try:
        record = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UserGuideDistillError(f"{p}: not a readable JSON reference record: {exc}") from exc
    if not isinstance(record, dict):
        raise UserGuideDistillError(f"{p}: reference record must be a JSON object, got {type(record).__name__}")
    for required in ("schema_version", "doc_kind", "title", "source_document",
                     "distilled_reference", "full_text_extract", "extraction", "section_count"):
        if required not in record:
            raise UserGuideDistillError(
                f"{p}: not a vip_user_guide_distill reference record -- missing {required!r}. "
                "Produce it with `dv-harness vip-user-guide distill`."
            )
    return record
