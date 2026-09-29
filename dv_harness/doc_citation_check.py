"""Verify that every `<file>.py:<line>` citation in a Markdown doc still points
at the symbol the surrounding prose names.

docs/MEMORY_ARCHITECTURE.md opens with the claim "file:line references are
given so any claim here can be checked against the source directly". That
claim decays silently: the prose stays correct while the numbers rot with the
next edit to the cited module. Every one of the memory docs' line citations had
drifted by 2026-09-04 (route_and_store 59 -> 91, promote_to_organizational
260 -> 445, route_memory 386 -> 571, ...), which is the failure this module
turns into a test failure.

The check is deliberately symbol-anchored rather than text-anchored: the
prose around a citation names a real symbol (`route_and_store`,
`CornerCaseLibrary.add()`, `MEMORY_LEVELS`), that symbol is located in the
cited source file, and the citation is correct only if the symbol's real
definition line falls inside the cited line or line range. That also makes a
failure mechanically fixable -- the report carries the line the citation
should have said.

    python -m dv_harness.doc_citation_check docs/MEMORY_ARCHITECTURE.md
    python -m dv_harness.doc_citation_check --memory-docs

Exits 1 on drift, 2 on an unverifiable citation (one whose surrounding prose
names no symbol that exists in the cited file, so nothing can be checked).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

# The 5 docs Phase 24 requires. Kept here so the checker and its test agree.
MEMORY_DOCS = (
    "docs/MEMORY_ARCHITECTURE.md",
    "docs/OBSIDIAN_INTEGRATION.md",
    "docs/MEMORY_AGENT.md",
    "docs/MEMORY_SCHEMA.md",
    "docs/MEMORY_OPERATIONS.md",
)

# A citation is a backtick span holding nothing but a .py path and a line or
# line range: `memory.py:91`, `dv_harness/memory.py:10`, `memory.py:783-789`.
CITATION_RE = re.compile(r"`([A-Za-z0-9_./\\-]+\.py):(\d+)(?:-(\d+))?`")

# Where a bare (non-path-qualified) `foo.py` citation is looked up, in order.
SOURCE_SEARCH_DIRS = ("dv_harness", ".", "tools")

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

OK = "OK"
DRIFT = "DRIFT"
UNVERIFIABLE = "UNVERIFIABLE"
MISSING_SOURCE = "MISSING_SOURCE"
OUT_OF_RANGE = "OUT_OF_RANGE"

# How many doc lines either side of a citation are read for symbol names. A
# citation's own sentence often wraps, and the naming symbol is regularly a
# section heading a line or two above it.
CONTEXT_WINDOW = 3


@dataclass
class Citation:
    doc: str
    doc_line: int
    source_ref: str
    start: int
    end: int
    context: str = ""


@dataclass
class CitationResult:
    citation: Citation
    verdict: str
    matched_symbols: List[str] = field(default_factory=list)
    expected_lines: List[int] = field(default_factory=list)
    detail: str = ""

    def render(self) -> str:
        cited = (f"{self.citation.start}-{self.citation.end}"
                 if self.citation.end != self.citation.start else str(self.citation.start))
        head = (f"{self.verdict:<14} {self.citation.doc}:{self.citation.doc_line}"
                f"  cites {self.citation.source_ref}:{cited}")
        if self.verdict == DRIFT:
            symbols = ", ".join(self.matched_symbols)
            lines = ", ".join(str(n) for n in self.expected_lines)
            return f"{head}\n{'':<14} {symbols} is really at line {lines}"
        if self.detail:
            return f"{head}\n{'':<14} {self.detail}"
        return head


def iter_prose_lines(text: str):
    """Yield (1-based lineno, line) for every line outside a fenced code block.

    Citations inside a ``` block are illustrative snippets, not claims about
    the source tree, and are not checked.
    """
    in_fence = False
    for i, line in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield i, line


def parse_citations(doc_text: str, doc_name: str) -> List[Citation]:
    lines = doc_text.splitlines()
    found: List[Citation] = []
    for lineno, line in iter_prose_lines(doc_text):
        for m in CITATION_RE.finditer(line):
            start = int(m.group(2))
            end = int(m.group(3)) if m.group(3) else start
            lo = max(0, lineno - 1 - CONTEXT_WINDOW)
            hi = min(len(lines), lineno + CONTEXT_WINDOW)
            found.append(Citation(doc=doc_name, doc_line=lineno, source_ref=m.group(1),
                                  start=start, end=end, context="\n".join(lines[lo:hi])))
    return found


def collect_definitions(py_text: str) -> Dict[str, List[int]]:
    """Map every citable symbol in a Python source to the line(s) defining it.

    Methods are registered under their qualified `Class.method` name only. A
    bare `add` would otherwise match four different classes in memory.py and
    wave through a citation pointing at any of them.
    """
    defs: Dict[str, List[int]] = {}
    bare_def_counts: Dict[str, int] = {}
    pending: List[tuple] = []
    current_class: Optional[str] = None
    class_indent = 0

    for lineno, raw in enumerate(py_text.splitlines(), start=1):
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(stripped)

        m = re.match(r"class\s+([A-Za-z_][A-Za-z0-9_]*)", stripped)
        if m:
            defs.setdefault(m.group(1), []).append(lineno)
            current_class, class_indent = m.group(1), indent
            continue

        if current_class is not None and indent <= class_indent:
            current_class = None

        m = re.match(r"(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)", stripped)
        if m:
            name = m.group(1)
            if current_class and indent > class_indent:
                defs.setdefault(f"{current_class}.{name}", []).append(lineno)
            bare_def_counts[name] = bare_def_counts.get(name, 0) + 1
            pending.append((name, lineno))
            continue

        if indent == 0:
            m = re.match(r"([A-Z_][A-Z0-9_]*)\s*(?::[^=]+)?=", stripped)
            if m:
                defs.setdefault(m.group(1), []).append(lineno)

    for name, lineno in pending:
        if bare_def_counts.get(name) == 1:
            defs.setdefault(name, []).append(lineno)

    return defs


def context_symbols(context: str) -> Set[str]:
    """Every identifier-shaped token near a citation, plus the tail segments of
    each dotted chain, so `dv_harness.memory_router.route_memory` also offers
    `memory_router.route_memory` and `route_memory`.
    """
    tokens: Set[str] = set()
    for raw in _IDENTIFIER_RE.findall(context):
        parts = raw.split(".")
        for i in range(len(parts)):
            tokens.add(".".join(parts[i:]))
    return tokens


def _matched_definitions(defs: Dict[str, List[int]], tokens: Set[str]) -> Dict[str, List[int]]:
    """Definitions the citation's prose actually names.

    A qualified `Class.method` also matches prose that mentions the class and
    the method separately -- a section heading "## MemoryStore record" above a
    sentence about `add()` names the symbol just as clearly as writing
    `MemoryStore.add()` inline does.
    """
    matched: Dict[str, List[int]] = {}
    for name, lines in defs.items():
        if name in tokens:
            matched[name] = lines
            continue
        if "." in name:
            cls, _, method = name.rpartition(".")
            if cls in tokens and method in tokens:
                matched[name] = lines
    return matched


def resolve_source(repo_root: Path, source_ref: str) -> Optional[Path]:
    ref = source_ref.replace("\\", "/")
    if "/" in ref:
        candidate = repo_root / ref
        return candidate if candidate.is_file() else None
    for d in SOURCE_SEARCH_DIRS:
        candidate = repo_root / d / ref
        if candidate.is_file():
            return candidate
    return None


def check_citation(repo_root: Path, citation: Citation) -> CitationResult:
    source = resolve_source(repo_root, citation.source_ref)
    if source is None:
        return CitationResult(citation, MISSING_SOURCE,
                              detail=f"no such file under {'/, '.join(SOURCE_SEARCH_DIRS)}/")

    py_text = source.read_text(encoding="utf-8")
    total_lines = len(py_text.splitlines())
    if citation.start < 1 or citation.end > total_lines or citation.end < citation.start:
        return CitationResult(citation, OUT_OF_RANGE,
                              detail=f"{source.name} has {total_lines} lines")

    matched = _matched_definitions(collect_definitions(py_text),
                                   context_symbols(citation.context))
    if not matched:
        return CitationResult(citation, UNVERIFIABLE,
                              detail="surrounding prose names no symbol defined in "
                                     f"{source.name}; cite one so this stays checkable")

    for name, lines in matched.items():
        if any(citation.start <= n <= citation.end for n in lines):
            return CitationResult(citation, OK, matched_symbols=[name])

    return CitationResult(citation,
                          DRIFT,
                          matched_symbols=sorted(matched),
                          expected_lines=sorted({n for lines in matched.values() for n in lines}))


def check_doc(repo_root: Path, doc_path: Path) -> List[CitationResult]:
    text = doc_path.read_text(encoding="utf-8")
    try:
        name = doc_path.relative_to(repo_root).as_posix()
    except ValueError:
        name = doc_path.name
    return [check_citation(repo_root, c) for c in parse_citations(text, name)]


def check_docs(repo_root: Path, doc_paths: Sequence[Path]) -> List[CitationResult]:
    results: List[CitationResult] = []
    for p in doc_paths:
        results.extend(check_doc(repo_root, p))
    return results


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    repo_root = Path(__file__).resolve().parents[1]

    if "--memory-docs" in argv or not argv:
        argv = [a for a in argv if a != "--memory-docs"]
        argv.extend(MEMORY_DOCS)

    docs = [Path(a) if Path(a).is_absolute() else repo_root / a for a in argv]
    missing = [d for d in docs if not d.is_file()]
    if missing:
        for d in missing:
            print(f"{MISSING_SOURCE:<14} {d}: no such doc")
        return 2

    results = check_docs(repo_root, docs)
    for r in results:
        if r.verdict != OK:
            print(r.render())

    drift = sum(1 for r in results if r.verdict in (DRIFT, MISSING_SOURCE, OUT_OF_RANGE))
    unverifiable = sum(1 for r in results if r.verdict == UNVERIFIABLE)
    print(f"{len(results)} citation(s) checked across {len(docs)} doc(s): "
          f"{len(results) - drift - unverifiable} OK, {drift} drifted, "
          f"{unverifiable} unverifiable")
    if drift:
        return 1
    if unverifiable:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
