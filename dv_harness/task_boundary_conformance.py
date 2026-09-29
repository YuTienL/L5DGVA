"""dv_harness/task_boundary_conformance.py -- structural, evidence-grounded
check that a real git change set stayed within a DECLARED task boundary.

THE GAP THIS CLOSES (originally built for this project's domain-C audit,
cluster C15 "Claude CLI Behavioral Containment"). A qualified reference
requirement in that family reads, in substance: an AI executor is not
authorized to substitute its own convenient implementation for a qualified
reference/DE/KC/OpenSpec method, and before any material write must state
current graph/state/phase, the applicable MUST rules, the qualified
reference method, existing task/environment reuse, required engine
invocations and prohibited actions, plus a fixed reference-before-invention
search order.

WHAT IS AND IS NOT BUILDABLE FROM REAL EVIDENCE. Most of that requirement
is a SEMANTIC judgment -- "did the agent actually consult the qualified
reference method / KC / project skill registry before writing" cannot be
read off any artifact this repo produces; there is no log of an agent's own
reasoning process to grep. Building a check that claims to answer that would
be exactly the kind of fabricated evidence the Evidence Truth Rule forbids.

One narrow slice of "unauthorized behavioral deviation" IS mechanically
provable from a real artifact: whether the FILES a change actually touched
stayed inside a task's DECLARED boundary (an explicit allow-list of path
prefixes the task was scoped to, plus an explicit forbidden-path list the
task was told never to touch -- exactly the shape of instruction this
repo's own multi-agent dispatch prompts already issue, e.g. "NEVER edit
dv_harness/engine.py, dv_harness/cli.py, or CLAUDE.md yourself ... build a
NEW standalone file only"). That is what this module checks, from a real
`git status`/`git diff`, never from an agent's self-report of what it
touched.

WHAT THIS DOES NOT DO (stated rather than implied closed):
 1. It does NOT judge file CONTENT. A change that stays entirely inside its
    declared allowed paths but does something out-of-scope INSIDE those
    files (e.g. quietly widening a function's contract) is invisible to
    this check -- that remains a semantic judgment, and this module makes
    no claim over it.
 2. It does NOT decide whether a boundary declaration itself was the RIGHT
    boundary for the task -- `TaskBoundary` is a plain, caller-declared
    input (typically transcribed from the dispatch prompt that scoped the
    task), not derived. A caller who declares an over-broad boundary gets a
    weaker check; this module does not second-guess that declaration.
 3. **Wired into `engine.py`'s `start_lifecycle()` since CAP-ATL-004
    (item 6/8), and into `cli.py`'s `start --task-boundary-*` flags /
    `dashboard.py`'s POST `/api/start` `task_boundary` JSON field since
    `M6-TASK-BOUNDARY-PRODUCTION-001` (2026-09-24).** Not wired into any
    stage GATE (this remains a pre-dispatch check inside `start_lifecycle()`
    itself, never a `STAGE_GATES` entry) or into a standalone
    `task-boundary-conformance` CLI verb the way Parent's own source
    (`D:\\DV\\Task\\DV_Agent_Harness_L5`) has one -- canonical exposes the
    SAME real contract (`TaskBoundary.from_dict()`, reused verbatim) through
    `start`'s own flags/JSON field instead, converging on the ONE
    lifecycle-first entry point `CAP-M6-DISPATCH-001` already established,
    rather than adding a second, parallel CLI verb.

REUSE, NOT DUPLICATION. `change_impact._git()` is imported directly (the
exact same degrade-never-raise git subprocess wrapper `change_impact.py` and
`change_blast_radius.py` already share in this canonical repo too) rather
than re-implemented a third time, per the Methodology Consolidation Rule.
This module adds only what neither of those already has: (a) an
UNCOMMITTED working-tree view (`git status --porcelain`, so a new file an
agent wrote but never `git add`ed is still real evidence) and (b)
ADDED-vs-MODIFIED status per file, needed to check an "add a NEW file only"
boundary, which `change_impact.changed_files()` does not carry (`--name-only`,
not `--name-status`).

KNOWN LIMITATION: `git status --porcelain=v1`'s plain (unquoted) text output
does not correctly split a path containing a literal space -- the same
simplification `change_impact.changed_files()` already makes over
`git diff --name-only` (neither module parses `-z`/NUL-delimited output).
A spaced path is misclassified, not silently dropped: it still appears in
`entries`/`findings`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .change_impact import _git  # reuse the exact degrade-never-raise git wrapper; no second copy

# --- per-file change status, from a real `git status --porcelain` code ----

STATUS_ADDED = "ADDED"
STATUS_MODIFIED = "MODIFIED"
STATUS_DELETED = "DELETED"
STATUS_RENAMED = "RENAMED"
STATUS_UNKNOWN = "UNKNOWN"

# --- per-file boundary classification --------------------------------------

CLASS_WITHIN_BOUNDARY = "WITHIN_DECLARED_BOUNDARY"
CLASS_FORBIDDEN = "FORBIDDEN_PATH_TOUCHED"
CLASS_OUTSIDE = "OUTSIDE_DECLARED_BOUNDARY"
CLASS_ADD_ONLY_VIOLATION = "DECLARED_ADD_ONLY_VIOLATION"

# --- aggregate verdict ------------------------------------------------------

VERDICT_HELD = "BOUNDARY_HELD"
VERDICT_VIOLATION = "BOUNDARY_VIOLATION"
VERDICT_NO_GIT = "NO_GIT_EVIDENCE"
VERDICT_NO_CHANGES = "NO_CHANGES_TO_CHECK"

#: Rendered alongside every result, so a consumer cannot mistake a real,
#: narrow, path-only check for the full semantic behavioral-containment
#: requirement it is derived from. See the module docstring, point 1.
SCOPE_CAVEAT = (
    "STRUCTURAL PATH CHECK ONLY: this verdict is derived from real git "
    "evidence about WHICH FILES were touched. It does not and cannot judge "
    "whether the CONTENT of an in-boundary file silently exceeded the "
    "task's intended scope -- that remains a human/reviewer judgment."
)


@dataclass(frozen=True)
class TaskBoundary:
    """A caller-declared scope contract for one task, transcribed from
    whatever authorized the task (a dispatch prompt, a work-item record) --
    never inferred. `allowed_path_prefixes` and `forbidden_paths` are
    repo-relative path prefixes ("/" separators); a path matches a prefix
    when it equals it or starts with it followed by "/"."""

    task_id: str
    allowed_path_prefixes: Tuple[str, ...] = ()
    forbidden_paths: Tuple[str, ...] = ()
    #: True for an "add a NEW file only" boundary: every in-boundary path
    #: must be STATUS_ADDED, never a modification of a pre-existing tracked
    #: file.
    require_new_file: bool = False

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TaskBoundary":
        return TaskBoundary(
            task_id=str(d.get("task_id", "")),
            allowed_path_prefixes=tuple(
                _norm(p) for p in (d.get("allowed_path_prefixes") or [])
            ),
            forbidden_paths=tuple(
                _norm(p) for p in (d.get("forbidden_paths") or [])
            ),
            require_new_file=bool(d.get("require_new_file", False)),
        )


def _norm(path: str) -> str:
    return str(path).strip().replace("\\", "/").rstrip("/")


def _matches_prefix(path: str, prefixes: Sequence[str]) -> bool:
    for raw in prefixes:
        p = _norm(raw)
        if not p:
            continue
        if path == p or path.startswith(p + "/"):
            return True
    return False


def classify_path(path: str, boundary: TaskBoundary, change_status: str) -> str:
    """One file's classification against one declared boundary. Forbidden
    always wins over allowed (a forbidden path nested under an allowed
    prefix is still forbidden) -- the same "never the reverse" direction
    `change_blast_radius.py` uses for its own escalation rule."""
    path = _norm(path)
    if _matches_prefix(path, boundary.forbidden_paths):
        return CLASS_FORBIDDEN
    if not _matches_prefix(path, boundary.allowed_path_prefixes):
        return CLASS_OUTSIDE
    if boundary.require_new_file and change_status != STATUS_ADDED:
        return CLASS_ADD_ONLY_VIOLATION
    return CLASS_WITHIN_BOUNDARY


def _status_from_code(xy: str) -> str:
    xy = xy or ""
    if xy.strip() == "??":
        return STATUS_ADDED
    if "R" in xy:
        return STATUS_RENAMED
    if "A" in xy:
        return STATUS_ADDED
    if "D" in xy:
        return STATUS_DELETED
    if "M" in xy:
        return STATUS_MODIFIED
    return STATUS_UNKNOWN


def _parse_porcelain_line(line: str) -> Optional[Dict[str, Optional[str]]]:
    if len(line) < 4:
        return None
    xy = line[:2]
    rest = line[3:]
    if "R" in xy and " -> " in rest:
        old_path, new_path = rest.split(" -> ", 1)
        return {"status_code": xy, "path": _norm(new_path), "old_path": _norm(old_path)}
    return {"status_code": xy, "path": _norm(rest), "old_path": None}


def working_tree_changes(root: Path) -> Dict[str, Any]:
    """Real `git status --porcelain=v1 --untracked-files=all` over the
    CURRENT WORKING TREE (staged + unstaged + untracked) -- the evidence
    shape a mid-task/pre-commit boundary check needs, distinct from
    `change_impact.changed_files()`'s committed base..head diff.

    Returns {"status", "entries", "detail"}; status is GIT_STATUS_OK /
    NO_GIT / STATUS_FAILED, the same degrade-never-raise vocabulary
    discipline as `change_impact.changed_files()`. Each entry:
    {"path", "old_path", "status_code", "change_status"}.
    """
    root = Path(root)
    rc, _, err = _git(root, ["rev-parse", "--git-dir"])
    if rc == 127 or rc != 0:
        return {"status": "NO_GIT", "entries": [],
                "detail": err or "not a git repository"}
    rc, out, err = _git(root, ["status", "--porcelain=v1", "--untracked-files=all"])
    if rc != 0:
        return {"status": "STATUS_FAILED", "entries": [], "detail": err}
    entries: List[Dict[str, Any]] = []
    for line in out.splitlines():
        if not line.strip("\n"):
            continue
        parsed = _parse_porcelain_line(line)
        if parsed is None:
            continue
        parsed["change_status"] = _status_from_code(parsed["status_code"])
        entries.append(parsed)
    return {"status": "GIT_STATUS_OK", "entries": entries, "detail": None}


def committed_range_changes(root: Path, base_sha: str, head_sha: str = "HEAD") -> Dict[str, Any]:
    """Real `git diff --name-status <base>..<head>` -- the committed-range
    counterpart of `working_tree_changes()`, for checking a boundary against
    a finished, committed change set rather than an in-progress one.

    Returns the same {"status", "entries", "detail"} shape; status is
    REAL_DIFF / NO_GIT / UNKNOWN_BASE / UNKNOWN_HEAD / DIFF_FAILED, matching
    `change_impact.changed_files()`'s own vocabulary (a different producer of
    the same fact family should read the same way to a caller)."""
    from .change_impact import resolve_sha  # local import: avoid a cycle at module load

    root = Path(root)
    rc, _, err = _git(root, ["rev-parse", "--git-dir"])
    if rc == 127 or rc != 0:
        return {"status": "NO_GIT", "entries": [],
                "detail": err or "not a git repository"}
    base = resolve_sha(root, base_sha)
    if base is None:
        return {"status": "UNKNOWN_BASE", "entries": [],
                "detail": f"base revision {base_sha!r} does not resolve to a commit"}
    head = resolve_sha(root, head_sha)
    if head is None:
        return {"status": "UNKNOWN_HEAD", "entries": [],
                "detail": f"head revision {head_sha!r} does not resolve to a commit"}
    rc, out, err = _git(root, ["diff", "--name-status", f"{base}..{head}"])
    if rc != 0:
        return {"status": "DIFF_FAILED", "entries": [], "detail": err}
    entries: List[Dict[str, Any]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0].strip()
        if code.startswith("R") and len(parts) >= 3:
            entries.append({"status_code": code, "path": _norm(parts[2]),
                             "old_path": _norm(parts[1]), "change_status": STATUS_RENAMED})
        elif len(parts) >= 2:
            status_map = {"A": STATUS_ADDED, "M": STATUS_MODIFIED, "D": STATUS_DELETED}
            entries.append({"status_code": code, "path": _norm(parts[1]), "old_path": None,
                             "change_status": status_map.get(code[:1], STATUS_UNKNOWN)})
    return {"status": "REAL_DIFF", "entries": entries, "detail": None}


def _filter_exempt(evidence: Dict[str, Any], exempt_path_prefixes: Sequence[str]) -> Dict[str, Any]:
    """Drops entries matching `exempt_path_prefixes` from the evidence
    BEFORE classification -- an exempt path is invisible to the boundary
    check entirely, not merely "allowed" (so it is never subject to a
    declared `forbidden_paths` or `require_new_file=True` either). Additive,
    `()` (the default everywhere) is a true no-op, byte-identical to before
    this parameter existed."""
    if not exempt_path_prefixes or not evidence.get("entries"):
        return evidence
    kept = [e for e in evidence["entries"] if not _matches_prefix(e["path"], exempt_path_prefixes)]
    if len(kept) == len(evidence["entries"]):
        return evidence
    return {**evidence, "entries": kept}


def _conform(boundary: TaskBoundary, evidence: Dict[str, Any]) -> Dict[str, Any]:
    ok_statuses = {"GIT_STATUS_OK", "REAL_DIFF"}
    if evidence["status"] not in ok_statuses:
        return {
            "task_id": boundary.task_id, "verdict": VERDICT_NO_GIT,
            "git_status": evidence["status"], "detail": evidence["detail"],
            "findings": [], "scope_caveat": SCOPE_CAVEAT,
        }
    if not evidence["entries"]:
        return {
            "task_id": boundary.task_id, "verdict": VERDICT_NO_CHANGES,
            "git_status": evidence["status"], "detail": None,
            "findings": [], "scope_caveat": SCOPE_CAVEAT,
        }
    findings = []
    for e in evidence["entries"]:
        cls = classify_path(e["path"], boundary, e["change_status"])
        findings.append({
            "path": e["path"], "old_path": e.get("old_path"),
            "change_status": e["change_status"], "classification": cls,
        })
    violated = any(f["classification"] != CLASS_WITHIN_BOUNDARY for f in findings)
    return {
        "task_id": boundary.task_id,
        "verdict": VERDICT_VIOLATION if violated else VERDICT_HELD,
        "git_status": evidence["status"], "detail": None,
        "findings": findings, "scope_caveat": SCOPE_CAVEAT,
    }


def check_working_tree_conformance(
    root: Path, boundary: TaskBoundary, exempt_path_prefixes: Sequence[str] = (),
) -> Dict[str, Any]:
    """The check a mid-task/pre-commit reviewer runs: did the CURRENT
    working tree stay inside `boundary`? See `working_tree_changes()` for
    the real evidence source.

    `exempt_path_prefixes` (additive, default `()`): repo-relative path
    prefixes to drop from the evidence BEFORE classification -- for a
    caller-owned control-plane directory that is not part of the task's own
    work (e.g. engine.py's `start_lifecycle()` exempts `.dv-harness`, its
    own bookkeeping directory, which it writes to on every call regardless
    of task content) and must not be forced into every declared
    `TaskBoundary.allowed_path_prefixes` by every real caller. An exempt
    path is invisible to the check entirely, distinct from `allowed_
    path_prefixes` (still subject to `forbidden_paths`/`require_new_file`)."""
    return _conform(boundary, _filter_exempt(working_tree_changes(root), exempt_path_prefixes))


def check_committed_range_conformance(
    root: Path, boundary: TaskBoundary, base_sha: str, head_sha: str = "HEAD",
    exempt_path_prefixes: Sequence[str] = (),
) -> Dict[str, Any]:
    """The check a post-commit/PR reviewer runs: did `base_sha..head_sha`
    stay inside `boundary`? See `committed_range_changes()` for the real
    evidence source. `exempt_path_prefixes`: see `check_working_tree_
    conformance()` above."""
    return _conform(boundary, _filter_exempt(
        committed_range_changes(root, base_sha, head_sha), exempt_path_prefixes))
