"""dv_harness/file_candidate_ranker.py -- general-purpose ranking of an
AMBIGUOUS CHOICE among similarly-named files (the recurring real-world shape:
`usb_reg.xlsx` vs `usb_reg_v2.xlsx` vs `usb_reg_final.xlsx`, or three copies of
a Makefile nobody remembers which one the build actually uses) using ONLY
real, independently-checkable evidence.

WHAT THIS MODULE IS, AND WHAT IT IS NOT. This is deliberately GENERIC: it
ranks ANY set of candidate file paths a caller hands it, for ANY reason a
caller has for being unsure which one is canonical. It is NOT scoped to DE
command.txt files, VIP scenarios, or any other domain-specific artifact type
-- there is a separate, already-claimed module in this batch for that
narrower DE-command question, and this module must never be confused with it
or grown to duplicate it. Three real, independently-obtained signals are
gathered per candidate:

  1. GIT LOG REFERENCE COUNT / RECENCY -- a real `git log --oneline --
     <path>` subprocess invocation against a caller-supplied repository root,
     giving the number of commits that touched the path and the most recent
     commit's date/sha/subject.
  2. BUILD-SCRIPT / MAKEFILE REFERENCE COUNT -- a real text scan of every
     Makefile/shell/csh/tcl/perl/CMake/filelist file found under a
     caller-supplied project root, counting literal occurrences of the
     candidate's own basename.
  3. REAL FILE MTIME -- a real `os.stat()` call against the candidate path on
     disk (mtime, and size as a secondary fact).

Per the Evidence Truth Rule, every signal that could not be genuinely
determined reports NOT_AVAILABLE with the specific real reason (git binary
missing, path not inside any git repository, this repository's own commit
log genuinely contains ZERO commits touching this specific path -- see the
"NOT_AVAILABLE vs. a real zero" note below --, no build scripts found under
the given project root, file absent from disk) -- this module never defaults
a signal it could not check to a guessed value, and it never claims a
directory it was not asked to scan.

**THIS MODULE NEVER PICKS A WINNER.** `rank_file_candidates()` always returns
EVERY candidate it was given, each carrying its own full, independently-cited
evidence. The one thing it additionally computes -- `display_rank` and the
`display_order_reason` that explains it -- is a purely INFORMATIONAL sort
order over the SAME evidence a human reading the report can already see and
override in one glance; it is explicitly documented and asserted (see the
test suite) never to be read as, or presented as, a decision, a
recommendation, or a verdict. There is no "winner" field, no "delete the
others" action, and no vocabulary token shared with `models.Status` (asserted
at import time) -- this module is a fact-gatherer, and the choice of which
file is canonical remains a human's.

NOT_AVAILABLE VS. A REAL ZERO -- a deliberate distinction, not an oversight.
For the BUILD-SCRIPT signal and the git RECENCY signal, a real, checked zero
(a project really does have build scripts and none of them mention this
file; a file really was found and stat'd and just has an old mtime) is
reported as AVAILABLE with that zero/old value -- collapsing "we checked and
the answer is zero" into NOT_AVAILABLE would be exactly the "never conflate
absence with zero" failure the Evidence Truth Rule forbids. The one place
this module deliberately reports NOT_AVAILABLE for a real, successful,
zero-result `git log` call is the specific case the task names outright: a
repository that is reachable and has commits, but whose history contains
ZERO commits touching this particular path ("no history" for this path).
That case is reported NOT_AVAILABLE, with the real commit_count=0 carried on
the record anyway (never hidden) -- because for THIS module's purpose (rank
candidates by evidence of use), "this file has never once appeared in this
repository's history" carries no COMPARATIVE information the other two
signals do not already surface more concretely (a file with no git history
at all is exactly as informative as a file whose git history the module
could not read, for the purpose this signal exists to serve), and the task's
own instruction names this exact case for NOT_AVAILABLE treatment.

REUSE NOTE: `change_impact.py` already has a private, degrade-never-raise git
subprocess wrapper (`_git()`, module-private, underscore-prefixed and not
exported for reuse). This module's own `_run_git()` below follows the
IDENTICAL contract (missing binary -> rc 127, timeout -> rc 124, never
raises) rather than importing a private symbol from another module, or
inventing a differently-behaved one -- see that function's own docstring.
Nothing in `change_impact.py`, `env_manifest.py`, or any other existing
module is otherwise imported here: this task's own scope is a brand-new,
self-contained file, and the three signals it gathers (git log, a build-file
text grep, a raw filesystem stat) are all directly implementable from the
standard library with no existing higher-level primitive to reuse.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Vocabulary. Deliberately disjoint from `models.Status` -- this module makes
# no verification-verdict claim of any kind, only reports whether a signal
# was determinable.
# ---------------------------------------------------------------------------

AVAILABLE = "AVAILABLE"
NOT_AVAILABLE = "NOT_AVAILABLE"

_SIGNAL_STATUSES = frozenset({AVAILABLE, NOT_AVAILABLE})


def assert_no_verification_verdict_vocabulary() -> None:
    """Fails loudly (at import, via a test) if this module's own status
    vocabulary ever grows a token shared with `dv_harness.models.Status` --
    the same collision guard `capability_evolution.py` /
    `benchmark_dataset.py` / `subsystem_maturity_gate.py` already apply to
    their own domain vocabularies. Imported lazily inside the function so a
    caller who has no interest in `models` never pays for importing it."""
    from . import models

    verdict_tokens = {member.value for member in models.Status}
    overlap = _SIGNAL_STATUSES & verdict_tokens
    if overlap:
        raise AssertionError(
            f"file_candidate_ranker status vocabulary collides with "
            f"models.Status: {sorted(overlap)}"
        )


# ---------------------------------------------------------------------------
# Default build-script/Makefile file patterns this module scans for. Data,
# not a hardcoded single name -- a caller with a differently-shaped build
# tree may pass its own `build_script_globs` to `gather_build_script_evidence`
# / `rank_file_candidates` instead of editing this module.
# ---------------------------------------------------------------------------

DEFAULT_BUILD_SCRIPT_GLOBS: Tuple[str, ...] = (
    "Makefile",
    "makefile",
    "GNUmakefile",
    "*.mk",
    "*.sh",
    "*.csh",
    "*.tcl",
    "*.pl",
    "CMakeLists.txt",
    "*.cmake",
    "*.f",
    "*.list",
)

#: A pathological project root (a whole checked-out monorepo, say) must not
#: make a ranking call scan an unbounded number of files. Exceeding this cap
#: is DISCLOSED on the evidence record (`scan_truncated: true`) rather than
#: silently producing an undercount that looks complete.
MAX_BUILD_SCRIPT_FILES = 4000


# ---------------------------------------------------------------------------
# git subprocess helper.
# ---------------------------------------------------------------------------


def _run_git(repo_root: Path, args: Sequence[str], timeout: int = 30) -> Tuple[int, str, str]:
    """Read-only git invocation. Mirrors `change_impact.py`'s own private
    `_git()` degrade-never-raise contract (missing binary -> rc 127, timeout
    -> rc 124, never raises) -- see this module's own header for why that
    function is not imported directly (it is module-private there)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return 127, "", f"git not found on PATH: {exc}"
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"git timed out: {exc}"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


# ---------------------------------------------------------------------------
# Signal 1: git log reference count / recency.
# ---------------------------------------------------------------------------


@dataclass
class GitLogEvidence:
    status: str  # AVAILABLE / NOT_AVAILABLE
    commit_count: Optional[int] = None
    last_commit_sha: Optional[str] = None
    last_commit_subject: Optional[str] = None
    last_commit_date: Optional[str] = None  # ISO 8601, committer date
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "commit_count": self.commit_count,
            "last_commit_sha": self.last_commit_sha,
            "last_commit_subject": self.last_commit_subject,
            "last_commit_date": self.last_commit_date,
            "reason": self.reason,
        }


def gather_git_log_evidence(repo_root: Optional[Path], candidate_path: Path) -> GitLogEvidence:
    """Real `git log --oneline -- <path>` (commit count, most recent
    sha/subject) plus a real `git log -1 --format=%cI -- <path>` (the same
    most-recent commit's committer date) against `repo_root`.

    NOT_AVAILABLE, each with the real reason: no `repo_root` supplied; git
    binary missing; `repo_root` is not inside a git repository; the
    candidate path is not inside `repo_root`'s own working tree; or the path
    genuinely has zero commits touching it (this repository's history has
    "no history" for this specific path -- see the module header's
    NOT_AVAILABLE-vs-a-real-zero note for why this one real-zero case is
    reported NOT_AVAILABLE rather than AVAILABLE with commit_count=0)."""
    if repo_root is None:
        return GitLogEvidence(status=NOT_AVAILABLE, reason="no repository root supplied")

    repo_root = Path(repo_root)
    if not repo_root.exists():
        return GitLogEvidence(
            status=NOT_AVAILABLE,
            reason=f"repository root does not exist on disk: {repo_root}",
        )

    rc, _out, err = _run_git(repo_root, ["rev-parse", "--git-dir"])
    if rc == 127:
        return GitLogEvidence(status=NOT_AVAILABLE, reason=f"git not found on PATH: {err.strip()}")
    if rc != 0:
        return GitLogEvidence(
            status=NOT_AVAILABLE,
            reason=f"not a git repository at {repo_root}: {err.strip()}",
        )

    try:
        candidate_abs = candidate_path.resolve()
        repo_abs = repo_root.resolve()
        candidate_abs.relative_to(repo_abs)
    except ValueError:
        return GitLogEvidence(
            status=NOT_AVAILABLE,
            reason=(
                f"candidate path {candidate_path} is not inside the given "
                f"repository root {repo_root}"
            ),
        )

    rc, out, err = _run_git(repo_root, ["log", "--oneline", "--", str(candidate_abs)])
    if rc != 0:
        return GitLogEvidence(status=NOT_AVAILABLE, reason=f"git log failed: {err.strip()}")

    lines = [line for line in out.splitlines() if line.strip()]
    commit_count = len(lines)
    if commit_count == 0:
        return GitLogEvidence(
            status=NOT_AVAILABLE,
            commit_count=0,
            reason="no commits touch this path in this repository's history",
        )

    first_line = lines[0]
    sha, _, subject = first_line.partition(" ")

    rc2, out2, _err2 = _run_git(
        repo_root, ["log", "-1", "--format=%cI", "--", str(candidate_abs)]
    )
    last_commit_date = out2.strip() if rc2 == 0 and out2.strip() else None

    return GitLogEvidence(
        status=AVAILABLE,
        commit_count=commit_count,
        last_commit_sha=sha.strip() or None,
        last_commit_subject=subject.strip() or None,
        last_commit_date=last_commit_date,
    )


# ---------------------------------------------------------------------------
# Signal 2: build-script / Makefile reference count.
# ---------------------------------------------------------------------------


@dataclass
class BuildScriptReferenceEvidence:
    status: str  # AVAILABLE / NOT_AVAILABLE
    reference_count: Optional[int] = None
    referencing_files: List[Dict[str, Any]] = field(default_factory=list)
    build_scripts_scanned: Optional[int] = None
    scan_truncated: bool = False
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reference_count": self.reference_count,
            "referencing_files": self.referencing_files,
            "build_scripts_scanned": self.build_scripts_scanned,
            "scan_truncated": self.scan_truncated,
            "reason": self.reason,
        }


def _discover_build_scripts(
    project_root: Path, build_script_globs: Sequence[str]
) -> Tuple[List[Path], bool]:
    found: Dict[Path, None] = {}
    truncated = False
    for pattern in build_script_globs:
        for match in project_root.rglob(pattern):
            if not match.is_file():
                continue
            found.setdefault(match.resolve(), None)
            if len(found) >= MAX_BUILD_SCRIPT_FILES:
                truncated = True
                return list(found.keys()), truncated
    return list(found.keys()), truncated


def gather_build_script_evidence(
    project_root: Optional[Path],
    candidate_path: Path,
    build_script_globs: Sequence[str] = DEFAULT_BUILD_SCRIPT_GLOBS,
) -> BuildScriptReferenceEvidence:
    """Real text scan of every build script/Makefile found under
    `project_root` (per `build_script_globs`), counting literal occurrences
    of `candidate_path`'s own basename.

    NOT_AVAILABLE, with the real reason: no `project_root` supplied;
    `project_root` does not exist; or the scan found ZERO build scripts
    under it at all (there was nothing to check the candidate against, a
    different fact from "we checked N scripts and none mention it", which is
    a real AVAILABLE reference_count=0)."""
    if project_root is None:
        return BuildScriptReferenceEvidence(
            status=NOT_AVAILABLE, reason="no project root supplied"
        )

    project_root = Path(project_root)
    if not project_root.exists():
        return BuildScriptReferenceEvidence(
            status=NOT_AVAILABLE,
            reason=f"project root does not exist on disk: {project_root}",
        )

    scripts, truncated = _discover_build_scripts(project_root, build_script_globs)
    if not scripts:
        return BuildScriptReferenceEvidence(
            status=NOT_AVAILABLE,
            build_scripts_scanned=0,
            reason=(
                f"no build scripts/Makefiles found under project root "
                f"{project_root} (patterns tried: {list(build_script_globs)})"
            ),
        )

    basename = candidate_path.name
    total = 0
    referencing: List[Dict[str, Any]] = []
    for script_path in sorted(scripts):
        try:
            text = script_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        count = text.count(basename)
        if count > 0:
            total += count
            try:
                rel = str(script_path.relative_to(project_root.resolve()))
            except ValueError:
                rel = str(script_path)
            referencing.append({"file": rel, "occurrences": count})

    return BuildScriptReferenceEvidence(
        status=AVAILABLE,
        reference_count=total,
        referencing_files=referencing,
        build_scripts_scanned=len(scripts),
        scan_truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Signal 3: real file mtime.
# ---------------------------------------------------------------------------


@dataclass
class FileMtimeEvidence:
    status: str  # AVAILABLE / NOT_AVAILABLE
    mtime_epoch: Optional[float] = None
    mtime_iso: Optional[str] = None
    size_bytes: Optional[int] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "mtime_epoch": self.mtime_epoch,
            "mtime_iso": self.mtime_iso,
            "size_bytes": self.size_bytes,
            "reason": self.reason,
        }


def gather_mtime_evidence(candidate_path: Path) -> FileMtimeEvidence:
    """Real `os.stat()` of `candidate_path`. NOT_AVAILABLE, naming the real
    path, when the file is not present on disk (or is not a regular file --
    a directory sharing a candidate's name is not this signal's business)."""
    candidate_path = Path(candidate_path)
    if not candidate_path.exists() or not candidate_path.is_file():
        return FileMtimeEvidence(
            status=NOT_AVAILABLE,
            reason=f"file not found on disk: {candidate_path}",
        )
    st = candidate_path.stat()
    mtime_iso = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
    return FileMtimeEvidence(
        status=AVAILABLE,
        mtime_epoch=st.st_mtime,
        mtime_iso=mtime_iso,
        size_bytes=st.st_size,
    )


# ---------------------------------------------------------------------------
# Per-candidate assembly + ranking. Never picks a winner -- see module header.
# ---------------------------------------------------------------------------


@dataclass
class FileCandidateEvidence:
    path: str
    exists_on_disk: bool
    git_log: GitLogEvidence
    build_script_references: BuildScriptReferenceEvidence
    mtime: FileMtimeEvidence

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "exists_on_disk": self.exists_on_disk,
            "git_log": self.git_log.to_dict(),
            "build_script_references": self.build_script_references.to_dict(),
            "mtime": self.mtime.to_dict(),
        }

    def available_signal_count(self) -> int:
        return sum(
            1
            for sig in (self.git_log, self.build_script_references, self.mtime)
            if sig.status == AVAILABLE
        )


def analyze_candidate(
    candidate_path,
    *,
    repo_root: Optional[Path] = None,
    project_root: Optional[Path] = None,
    build_script_globs: Sequence[str] = DEFAULT_BUILD_SCRIPT_GLOBS,
) -> FileCandidateEvidence:
    """Gather all three real signals for ONE candidate path. Does not rank,
    does not compare against other candidates -- that is `rank_file_
    candidates()`'s job, over a list of these."""
    path = Path(candidate_path)
    return FileCandidateEvidence(
        path=str(candidate_path),
        exists_on_disk=path.exists() and path.is_file(),
        git_log=gather_git_log_evidence(repo_root, path),
        build_script_references=gather_build_script_evidence(
            project_root, path, build_script_globs
        ),
        mtime=gather_mtime_evidence(path),
    )


@dataclass
class RankedCandidate:
    path: str
    evidence: FileCandidateEvidence
    available_signal_count: int
    display_rank: int
    display_order_reason: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "evidence": self.evidence.to_dict(),
            "available_signal_count": self.available_signal_count,
            "display_rank": self.display_rank,
            "display_order_reason": self.display_order_reason,
        }


@dataclass
class FileCandidateRankingReport:
    candidates: List[RankedCandidate]
    caller_must_decide: bool = True
    disclosure: str = (
        "display_rank is an informational sort order over the evidence "
        "attached to each candidate. It is NOT a recommendation, a verdict, "
        "or a decision -- this module never picks a winner. The caller (a "
        "human) decides which candidate is canonical after reading the "
        "cited evidence for every candidate below."
    )

    def to_dict(self) -> dict:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "caller_must_decide": self.caller_must_decide,
            "disclosure": self.disclosure,
        }


def _sort_weight(evidence: FileCandidateEvidence) -> Tuple[float, float, float]:
    """Purely a DISPLAY-ORDER heuristic, documented and tested as such: more
    commits, a more recent commit, and more build-script references sort
    earlier. A NOT_AVAILABLE signal contributes zero weight -- it is never
    treated as evidence of LESS activity than a real, checked zero would be,
    it simply contributes nothing to the sort, exactly as it contributes
    nothing to any claim this module makes."""
    commit_weight = 0.0
    recency_weight = 0.0
    if evidence.git_log.status == AVAILABLE:
        commit_weight = float(evidence.git_log.commit_count or 0)
        if evidence.git_log.last_commit_date:
            try:
                dt = datetime.fromisoformat(evidence.git_log.last_commit_date)
                recency_weight = dt.timestamp()
            except ValueError:
                recency_weight = 0.0

    build_weight = 0.0
    if evidence.build_script_references.status == AVAILABLE:
        build_weight = float(evidence.build_script_references.reference_count or 0)

    return (commit_weight, recency_weight, build_weight)


def _order_reason(evidence: FileCandidateEvidence) -> str:
    parts = []
    if evidence.git_log.status == AVAILABLE:
        parts.append(
            f"{evidence.git_log.commit_count} git commit(s), most recent "
            f"{evidence.git_log.last_commit_date or 'unknown date'}"
        )
    else:
        parts.append(f"git log NOT_AVAILABLE ({evidence.git_log.reason})")

    if evidence.build_script_references.status == AVAILABLE:
        parts.append(
            f"{evidence.build_script_references.reference_count} build-script "
            "reference(s)"
        )
    else:
        parts.append(
            "build-script references NOT_AVAILABLE "
            f"({evidence.build_script_references.reason})"
        )

    if evidence.mtime.status == AVAILABLE:
        parts.append(f"mtime {evidence.mtime.mtime_iso}")
    else:
        parts.append(f"mtime NOT_AVAILABLE ({evidence.mtime.reason})")

    return "; ".join(parts)


def rank_file_candidates(
    candidate_paths: Sequence[Any],
    *,
    repo_root: Optional[Any] = None,
    project_root: Optional[Any] = None,
    build_script_globs: Sequence[str] = DEFAULT_BUILD_SCRIPT_GLOBS,
) -> FileCandidateRankingReport:
    """Gather real evidence for every path in `candidate_paths` and return a
    `FileCandidateRankingReport` -- every candidate, every signal, cited.
    `display_rank` is an informational sort convenience only; see
    `FileCandidateRankingReport.disclosure`. Ties (identical sort weight,
    including the common all-NOT_AVAILABLE case) keep the caller's own input
    order via Python's stable sort -- never an arbitrary re-ordering."""
    repo_root_path = Path(repo_root) if repo_root is not None else None
    project_root_path = Path(project_root) if project_root is not None else None

    evidences = [
        analyze_candidate(
            p,
            repo_root=repo_root_path,
            project_root=project_root_path,
            build_script_globs=build_script_globs,
        )
        for p in candidate_paths
    ]

    indexed = list(enumerate(evidences))
    indexed.sort(key=lambda pair: _sort_weight(pair[1]), reverse=True)

    ranked: List[RankedCandidate] = []
    for display_rank, (_orig_index, evidence) in enumerate(indexed, start=1):
        ranked.append(
            RankedCandidate(
                path=evidence.path,
                evidence=evidence,
                available_signal_count=evidence.available_signal_count(),
                display_rank=display_rank,
                display_order_reason=_order_reason(evidence),
            )
        )

    return FileCandidateRankingReport(candidates=ranked)


# ---------------------------------------------------------------------------
# Shared execute_verb()/main() convention (power-intent, golden-scenario,
# waiver-store, ...). No `dv-harness` CLI verb is registered here -- per this
# task's own file-safety scope, `cli.py` must never be edited by this task;
# the front door is `python -m dv_harness.file_candidate_ranker`.
# ---------------------------------------------------------------------------


def execute_verb(
    verb: str,
    *,
    candidates: Optional[Sequence[str]] = None,
    repo_root: Optional[str] = None,
    project_root: Optional[str] = None,
) -> Tuple[int, dict]:
    """`verb` is "rank". Returns (exit_code, result_dict): 0 = ranking
    produced, every candidate has at least one AVAILABLE signal; 1 = ranking
    produced but at least one candidate has NO available signal at all (a
    real, disclosed finding: this module could gather no evidence
    whatsoever about that path); 2 = usage error (no candidates supplied)."""
    if verb != "rank":
        return 2, {"status": NOT_AVAILABLE, "reason": f"unrecognized verb '{verb}'"}
    if not candidates:
        return 2, {"status": NOT_AVAILABLE, "reason": "no candidate paths supplied"}

    report = rank_file_candidates(
        candidates, repo_root=repo_root, project_root=project_root
    )
    result = report.to_dict()
    any_fully_unevidenced = any(
        c.available_signal_count == 0 for c in report.candidates
    )
    return (1 if any_fully_unevidenced else 0), result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rank ambiguous file candidates by real git-log/build-script/"
            "mtime evidence. Never picks a winner -- the caller decides."
        )
    )
    parser.add_argument("verb", choices=("rank",))
    parser.add_argument("candidates", nargs="+", help="candidate file paths")
    parser.add_argument("--repo-root", default=None, help="git repository root")
    parser.add_argument(
        "--project-root",
        default=None,
        help="project root to scan for build scripts/Makefiles",
    )
    args = parser.parse_args(argv)

    exit_code, result = execute_verb(
        args.verb,
        candidates=args.candidates,
        repo_root=args.repo_root,
        project_root=args.project_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
