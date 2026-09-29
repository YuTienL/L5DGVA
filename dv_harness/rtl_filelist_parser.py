"""dv_harness/rtl_filelist_parser.py -- expand a real VCS-style RTL compile
filelist (`.f`) into the ordered file list / include-directory list / macro
define table a real `vcs`/`verible-verilog-syntax` invocation would actually
see, so a caller (`design_architecture_ir.parse_rtl_file()`,
`verible_parser.parse_file()`) can be handed a concrete file list instead of
needing one already hand-expanded by a human.

MIGRATED (M5 Capability Pool Closure, CAP-POOL-012). PROVENANCE DISCLOSED:
this module has no committed source anywhere in Parent, v50, B7B, or B8 --
it exists only as an UNTRACKED file in B7A's own worktree (`D:/wt/b7a`,
`dv_harness/rtl_filelist_parser.py`), discovered incidentally during this
project's Cohort 4 source-integrity re-checks, not as a registered
migration input. Migrated here verbatim (self-contained, stdlib-only, no
external dependency of any kind) because its two real canonical consumers
already exist and both currently require manual pre-expansion:
`design_architecture_ir.py` and `verible_parser.py`. No test file was
found anywhere for this module (in B7A or elsewhere) -- the test suite
ported alongside this module (`dv_harness_tests/test_rtl_filelist_
parser.py`) is NEW, derived from this module's own documented behavior
(the "REAL-WORLD `.f` SYNTAX SUPPORTED" and "BOUNDED, HONESTLY" sections
below), not copied from any pre-existing source.

THE GAP THIS CLOSES (DUT-03, B7A's own gap numbering). Before this
module, a repo-wide grep for `filelist` in canonical `dv_harness/*.py`
matched only Makefile TEMPLATE text (compile filelists this harness's own
generated environments write FOR a real `vcs` invocation to consume) --
nothing anywhere READ a `.f` file and expanded `-f`/`+incdir+`/
`` `define `` into a concrete file list (confirmed by this migration's own
re-check, not merely trusted from the source's own claim). `env_manifest.
build_dut_facts_rtl()`'s `rtl_files` parameter, and `design_architecture_ir.
build_architecture_ir()`'s `rtl_files` parameter, both require the caller to
have already done that expansion by hand. A real DUT delivery package
practically always ships a filelist rather than a bare list of file names;
this module is the missing front door that makes that a live input rather
than a manual pre-step.

REAL-WORLD `.f` SYNTAX SUPPORTED, one real per-line token grammar (the same
one `vcs -f`/most Verilog toolchains accept):
  `-f <path>` / `-F <path>`      include another filelist. `-f` and `-F`
                                  differ, in a real tool, only in whether a
                                  RELATIVE path INSIDE the nested file
                                  resolves against the nested file's own
                                  directory (`-F`) or the original
                                  invocation's directory (`-f`); this module
                                  deliberately does not implement that
                                  distinction (see BOUNDED below) and
                                  resolves both the same way.
  `+incdir+<dir>[+<dir>...]`      one or more include directories.
  `` `define NAME[=VALUE] ``     a Verilog macro define (backtick literal,
                                  the real preprocessor-directive syntax --
                                  NOT a Python f-string).
  `-v <file>`                     a Verilog LIBRARY file (searched for
                                  referenced-but-undeclared modules, not an
                                  always-compiled source) -- kept separate
                                  from `files`.
  `-y <dir>`                      a Verilog library DIRECTORY (same
                                  distinction).
  `// ...` / `# ...`             a line, or the tail of a line, comment.
  any other bare token            a source file path.
  any other `-flag` token         an unrecognized tool flag (e.g.
                                  `-sverilog`, `-full64`) -- recorded, never
                                  silently dropped and never mistaken for a
                                  file path.

REUSE OVER REINVENT: this module produces a plain, ordered `files` list --
the exact shape `design_architecture_ir.build_architecture_ir(rtl_files=...)`
and `verible_parser.parse_file()` already accept -- rather than inventing a
project-specific compile-command wrapper; a caller does
`build_architecture_ir(parse_filelist(path).files)` and nothing else changes
downstream. Neither consumer is wired to call this module automatically by
this migration -- that wiring is left open, same disclosed-not-implied-
closed posture this project uses throughout.

BOUNDED, HONESTLY.
- `-f` vs `-F` relative-path-base distinction is NOT implemented (both
  resolve a nested file's own relative paths against ITS OWN directory,
  which is real `-F` semantics) -- a filelist relying on real `-f`'s
  different base could see a path resolve differently than a real `vcs`
  invocation would. Stated here rather than silently assumed correct.
  `nested_filelist_directive` on each expansion records which directive was
  actually written, so a caller auditing a mismatch can see it.
  Wildcards/globs in a file-path token are NOT expanded (no `*.v`) -- the
  token is kept literal and reported as a file that will not exist on disk,
  the same honest non-guess this module's siblings apply elsewhere.
- A cyclic `-f` chain (filelist A includes B includes A) is detected and
  reported as a warning; the cycle edge is not re-expanded (infinite
  recursion is a real, not merely defensive, risk here).
- A referenced nested filelist or source file that does not exist on disk
  is recorded in `missing_paths`, never silently dropped from awareness and
  never fabricated as present.
- No macro EXPANSION/substitution is performed (a `` `define WIDTH 32 ``
  followed by a source file using `` `WIDTH `` is not resolved here) --
  this module only collects the macro table; a real preprocessor/verible
  run is what actually expands it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"

_DEFINE_RE = re.compile(r"^`define\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\s+(?P<value>\S.*))?$")


@dataclass
class FilelistResult:
    status: str
    reason: Optional[str]
    source_path: str
    files: List[str] = field(default_factory=list)
    incdirs: List[str] = field(default_factory=list)
    defines: Dict[str, Optional[str]] = field(default_factory=dict)
    library_dirs: List[str] = field(default_factory=list)
    library_files: List[str] = field(default_factory=list)
    nested_filelists: List[Dict[str, Any]] = field(default_factory=list)
    ignored_flags: List[Dict[str, Any]] = field(default_factory=list)
    missing_paths: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "source_path": self.source_path,
            "files": self.files,
            "incdirs": self.incdirs,
            "defines": self.defines,
            "library_dirs": self.library_dirs,
            "library_files": self.library_files,
            "nested_filelists": self.nested_filelists,
            "ignored_flags": self.ignored_flags,
            "missing_paths": self.missing_paths,
            "warnings": self.warnings,
        }


def _strip_comment(line: str) -> str:
    for marker in ("//", "#"):
        idx = line.find(marker)
        if idx != -1:
            line = line[:idx]
    return line.strip()


def _tokenize(line: str) -> List[str]:
    """A filelist line is whitespace-separated; a `` `define `` line is kept
    as a single re-joined logical unit by the caller (its value may itself
    contain spaces), everything else splits on whitespace."""
    return line.split()


class _Accumulator:
    def __init__(self, root: str):
        self.root = root
        self.files: List[str] = []
        self._files_seen: Set[str] = set()
        self.incdirs: List[str] = []
        self._incdirs_seen: Set[str] = set()
        self.defines: Dict[str, Optional[str]] = {}
        self.library_dirs: List[str] = []
        self._library_dirs_seen: Set[str] = set()
        self.library_files: List[str] = []
        self._library_files_seen: Set[str] = set()
        self.nested_filelists: List[Dict[str, Any]] = []
        self.ignored_flags: List[Dict[str, Any]] = []
        self.missing_paths: List[Dict[str, Any]] = []
        self.warnings: List[str] = []

    def add_file(self, resolved: str, exists: bool, origin: str) -> None:
        if not exists:
            self.missing_paths.append({"path": resolved, "kind": "file", "referenced_from": origin})
        if resolved not in self._files_seen:
            self._files_seen.add(resolved)
            self.files.append(resolved)

    def add_incdir(self, resolved: str, exists: bool, origin: str) -> None:
        if not exists:
            self.missing_paths.append({"path": resolved, "kind": "incdir", "referenced_from": origin})
        if resolved not in self._incdirs_seen:
            self._incdirs_seen.add(resolved)
            self.incdirs.append(resolved)

    def add_library_dir(self, resolved: str, exists: bool, origin: str) -> None:
        if not exists:
            self.missing_paths.append({"path": resolved, "kind": "library_dir", "referenced_from": origin})
        if resolved not in self._library_dirs_seen:
            self._library_dirs_seen.add(resolved)
            self.library_dirs.append(resolved)

    def add_library_file(self, resolved: str, exists: bool, origin: str) -> None:
        if not exists:
            self.missing_paths.append({"path": resolved, "kind": "library_file", "referenced_from": origin})
        if resolved not in self._library_files_seen:
            self._library_files_seen.add(resolved)
            self.library_files.append(resolved)


def _resolve(token: str, base_dir: Path) -> str:
    p = Path(token)
    if not p.is_absolute():
        p = base_dir / p
    return str(p)


def _expand(path: Path, acc: _Accumulator, *, ancestors: Tuple[str, ...],
            directive: str = "root") -> None:
    real_path = str(path.resolve()) if path.exists() else str(path)
    if real_path in ancestors:
        acc.warnings.append(
            f"cyclic filelist include detected and skipped: {path} is already an ancestor of this "
            f"include chain ({' -> '.join(ancestors)})"
        )
        return
    if not path.is_file():
        acc.missing_paths.append({"path": str(path), "kind": "filelist", "referenced_from": directive})
        acc.warnings.append(f"referenced filelist does not exist, skipped: {path}")
        return

    base_dir = path.resolve().parent
    text = path.read_text(encoding="utf-8", errors="replace")
    next_ancestors = ancestors + (real_path,)

    for raw_line in text.splitlines():
        stripped = _strip_comment(raw_line)
        if not stripped:
            continue

        define_match = _DEFINE_RE.match(stripped)
        if define_match:
            acc.defines[define_match.group("name")] = define_match.group("value")
            continue

        tokens = _tokenize(stripped)
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in ("-f", "-F"):
                i += 1
                if i >= len(tokens):
                    acc.warnings.append(f"{path}: {tok} with no path argument, ignored")
                    break
                nested = _resolve(tokens[i], base_dir)
                acc.nested_filelists.append({
                    "path": nested, "directive": tok, "included_from": str(path),
                })
                _expand(Path(nested), acc, ancestors=next_ancestors, directive=f"{tok} in {path}")
            elif tok.startswith("+incdir+"):
                for d in tok[len("+incdir+"):].split("+"):
                    if d:
                        resolved = _resolve(d, base_dir)
                        acc.add_incdir(resolved, Path(resolved).is_dir(), str(path))
            elif tok == "-v":
                i += 1
                if i >= len(tokens):
                    acc.warnings.append(f"{path}: -v with no file argument, ignored")
                    break
                resolved = _resolve(tokens[i], base_dir)
                acc.add_library_file(resolved, Path(resolved).is_file(), str(path))
            elif tok == "-y":
                i += 1
                if i >= len(tokens):
                    acc.warnings.append(f"{path}: -y with no dir argument, ignored")
                    break
                resolved = _resolve(tokens[i], base_dir)
                acc.add_library_dir(resolved, Path(resolved).is_dir(), str(path))
            elif tok.startswith("-"):
                acc.ignored_flags.append({"flag": tok, "filelist": str(path)})
            else:
                resolved = _resolve(tok, base_dir)
                acc.add_file(resolved, Path(resolved).is_file(), str(path))
            i += 1


def parse_filelist(path: Any) -> FilelistResult:
    """Expand one real `.f` filelist (recursively, through any `-f`/`-F`
    nested filelists it references) into a `FilelistResult`. Never raises on
    a real, mundane defect (a missing nested filelist, an unrecognized
    flag, a referenced file that does not exist) -- those are reported in
    the result's own fields; only the ROOT path itself missing/unreadable
    is reported as `NOT_AVAILABLE`."""
    source_path = str(path)
    p = Path(path)
    if not p.exists():
        return FilelistResult(status=STATUS_NOT_AVAILABLE, reason=f"file not found: {source_path}",
                               source_path=source_path)
    if not p.is_file():
        return FilelistResult(status=STATUS_NOT_AVAILABLE, reason=f"not a regular file: {source_path}",
                               source_path=source_path)
    try:
        text_check = p.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        pass  # re-read tolerantly inside _expand(); a non-UTF-8 filelist is unusual but not fatal

    acc = _Accumulator(root=source_path)
    _expand(p, acc, ancestors=())

    if not acc.files:
        return FilelistResult(
            status=STATUS_PARTIAL if (acc.missing_paths or acc.warnings) else STATUS_OK,
            reason="filelist expanded with zero source files" if not (acc.missing_paths or acc.warnings) else
                   f"filelist expanded with zero source files; {len(acc.missing_paths)} missing path(s), "
                   f"{len(acc.warnings)} warning(s)",
            source_path=source_path, incdirs=acc.incdirs, defines=acc.defines,
            library_dirs=acc.library_dirs, library_files=acc.library_files,
            nested_filelists=acc.nested_filelists, ignored_flags=acc.ignored_flags,
            missing_paths=acc.missing_paths, warnings=acc.warnings,
        )

    status = STATUS_OK if not (acc.missing_paths or acc.warnings) else STATUS_PARTIAL
    reason = None if status == STATUS_OK else (
        f"{len(acc.missing_paths)} missing path(s), {len(acc.warnings)} warning(s) -- see those fields"
    )
    return FilelistResult(
        status=status, reason=reason, source_path=source_path, files=acc.files, incdirs=acc.incdirs,
        defines=acc.defines, library_dirs=acc.library_dirs, library_files=acc.library_files,
        nested_filelists=acc.nested_filelists, ignored_flags=acc.ignored_flags,
        missing_paths=acc.missing_paths, warnings=acc.warnings,
    )


# ---------------------------------------------------------------------------
# Ad hoc entry point, mirroring this project's other standalone modules'
# bare `python -m` front door (cli.py wiring left to a future task).
# ---------------------------------------------------------------------------

def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m dv_harness.rtl_filelist_parser")
    parser.add_argument("path", help="RTL compile filelist (.f)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = parse_filelist(args.path)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"status: {result.status}")
        if result.reason:
            print(f"reason: {result.reason}")
        print(f"files: {len(result.files)}")
        for f in result.files:
            print(f"  {f}")
        if result.incdirs:
            print(f"incdirs: {result.incdirs}")
        if result.defines:
            print(f"defines: {result.defines}")
        for m in result.missing_paths:
            print(f"  missing: {m}")

    return 2 if result.status == STATUS_NOT_AVAILABLE else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return execute_verb(argv)


if __name__ == "__main__":
    raise SystemExit(main())
