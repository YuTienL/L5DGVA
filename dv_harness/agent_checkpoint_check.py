"""dv_harness/agent_checkpoint_check.py -- verification checker for
CORE/agent-checkpoint-discipline/SKILL.md's required resume-state artifact
convention.

Gap #4 closure (2026-09-03): the IP_UVM_DV_Gen build agent investigating the
TCA NC->USB hang became permanently unresumable mid-investigation (a real
"No transcript found for agent ID" failure on SendMessage) after hours of
accumulated context. It happened to recover well because its own
documentation habits (usb31_dev_uvm's CLAUDE.md trap catalogue + docs/
dut-request.md) were already thorough -- but that was a side effect of
general good practice, not a checked, required convention. This module is
the checkable half of making it required: given a build-tree path, it
answers "does a resume-state artifact matching the defined schema exist,
and does it look current" without any human having to read the tree by eye.

**Scope boundary vs. dv_harness/session_snapshot.py (read and confirmed
before writing this module, per the workflow's own instruction).**
session_snapshot.py covers the ENGINE's own CURRENT-RUN layer -- state.json,
blackboard/, plans/, react/, agents/, lsf/, all rooted at `.dv-harness/`
within a DVHarness project, saved at the engine's own run_stage()/loop()
stage transitions. It never reaches into a separately-dispatched, long-
running Agent-tool subagent's own accumulated context inside an arbitrary
build tree (e.g. a build agent working inside D:/DV/Task/USB/usb31_dev_uvm,
which has no `.dv-harness/` of its own and is not a DVHarness project at
all) -- that gap is what this module and the skill it backs close. The two
mechanisms are complementary, not overlapping: session_snapshot.py resumes
THIS harness's own engine loop; this module verifies that a DISPATCHED
BUILD/INVESTIGATION AGENT left behind a resume-state artifact a fresh agent
(or human) could re-brief itself from, inside whatever tree that agent was
actually working in.

Typed result, no bare bool/None: CheckpointCheckResult carries `.ok`,
`.reason`, `.detail` -- the same short SCREAMING_SNAKE_CASE `reason` code
plus a concrete `detail` dict convention already used throughout
dv_harness/uvm_generator/*.py (see address_map_verifier.py's
AddressMapVerificationError for the sibling pattern this follows), even
though this checker never raises -- a checker that can fail in more than
one interesting way should let a caller branch on WHY, not just on ok/not
ok.

Recognizes both real layouts CORE/agent-checkpoint-discipline/SKILL.md
documents:

  DUAL-FILE  -- the real worked example this whole convention is reverse-
               distilled from: a `CLAUDE.md` at the build-tree root (the
               durable, append-only evidence/citation log -- usb31_dev_uvm's
               "trap catalogue") plus an open-items file under a `docs/`
               directory named like `dut-request.md` (the mutable,
               status-tracked next-step/pending-decision list).
  SINGLE-FILE -- `RESUME.md` or `STATUS.md` at the build-tree root or under
               a `docs/` directory, carrying all five schema sections in one
               file -- for a build tree that has not already organically
               grown the dual-file convention.

Schema (five required sections; see the skill for the full rationale and
the annotated real-example mapping):
  1. current hypothesis / status
  2. evidence gathered so far, with file:line citations
  3. next planned step
  4. decisions pending user/coordinator confirmation
  5. files touched this session

Section detection is by keyword/pattern, not by requiring a literal
markdown header spelled exactly like the schema name -- the real worked
example satisfies every section using its own organic vocabulary ("Owner:",
"To close:", "grep -rn \"DV_UVM HOOK\"", trap-catalogue citations), and a
checker that only recognized the canonical single-file template's own
header text would falsely report the real example as non-compliant.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Layout recognition
# ---------------------------------------------------------------------------

SINGLE_FILE_NAMES = ("RESUME.md", "STATUS.md")
SINGLE_FILE_DIRS = (".", "docs", "uvm/docs")

DUAL_FILE_ROOT_NAME = "CLAUDE.md"
DUAL_FILE_OPEN_ITEMS_DIRS = ("docs", "uvm/docs", ".")
# Matches dut-request.md (the real name), plus generic equivalents a project
# might use instead (open-items.md, RESUME.md/STATUS.md living in a docs/
# dir rather than at the root -- still a valid open-items half of the dual
# layout even if it reuses a single-file-style name).
OPEN_ITEMS_NAME_RE = re.compile(
    r"^(dut[-_]?request|open[-_]?items?|resume|status)\.md$", re.IGNORECASE
)

# Directories that are legitimately read-only/vendor source in this
# harness's own established convention (IP_UVM_DV_Gen.md Step 2: "Enforce
# read-only mechanically with deny rules on DUT/** and VIP/**") and so are
# excluded from the "what else changed recently in this tree" staleness
# scan -- an agent's own session work never lands there, so their mtimes
# (old, from vendor delivery) are not useful staleness evidence, and a
# multi-gigabyte vendor RTL/VIP tree is exactly what would make a naive
# full-tree stat walk slow for no benefit.
STALENESS_SCAN_EXCLUDE_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", "DUT", "VIP", ".dv-harness",
})

# Heuristic file:line citation pattern -- matches both "file.ext:123" and
# "file.ext, 123" (the two forms actually used across usb31_dev_uvm's
# CLAUDE.md/dut-request.md, e.g. "MODEL_ALL.v:1756" and
# "svt_usb_protocol_block.svp, 7016").
CITATION_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,5}[:,]\s*\d+")
MIN_CITATIONS_FOR_EVIDENCE_SECTION = 3

# Keyword/pattern detectors for the five schema sections. Deliberately
# pattern-based rather than literal-header-based -- see module docstring.
SECTION_PATTERNS: Dict[str, re.Pattern] = {
    "current_hypothesis_status": re.compile(
        r"(current\s+hypothesis|current\s+status|\bhypothesis\b|"
        r"\bstatus\b|\bOPEN\b|\bCLOSED\b|\bRESOLVED\b|blocking-)",
        re.IGNORECASE,
    ),
    "next_planned_step": re.compile(
        r"(next\s+(planned\s+)?step|to\s+close\s*:|next\s+action|"
        r"remaining\s+work|\bplan\b\s*:|\btodo\b)",
        re.IGNORECASE,
    ),
    "decisions_pending_confirmation": re.compile(
        r"(pending\s+(user|coordinator)?\s*confirmation|"
        r"decisions?\s+pending|owner\s*:|awaiting\s+(confirmation|decision)|"
        r"ask\s+the\s+user|needs?\s+(a\s+)?(human|user)\s+decision|"
        r"open\s+item)",
        re.IGNORECASE,
    ),
    "files_touched_this_session": re.compile(
        r"(files?\s+touched|modified\s+files?|edited\s+files?|"
        r"changes?\s+to\s+the\s+delivered\s+files?|grep\s+-rn|"
        r"hook\b[^.]{0,40}(applied|edit|land))",
        re.IGNORECASE,
    ),
}
# "evidence_gathered_with_citations" is checked separately via CITATION_RE
# density rather than a keyword, since the schema's own requirement is the
# citations themselves, not a section title naming them.
ALL_SECTION_KEYS = tuple(SECTION_PATTERNS.keys()) + ("evidence_gathered_with_citations",)

DEFAULT_STALE_THRESHOLD_SECONDS = 6 * 3600  # "many hours" per the real incident


@dataclass
class CheckpointCheckResult:
    ok: bool
    reason: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "detail": self.detail}


def _find_single_file_artifact(build_tree: Path) -> Optional[List[Path]]:
    for d in SINGLE_FILE_DIRS:
        for name in SINGLE_FILE_NAMES:
            candidate = (build_tree / d / name) if d != "." else (build_tree / name)
            if candidate.is_file():
                return [candidate]
    return None


def _find_dual_file_artifact(build_tree: Path) -> Optional[List[Path]]:
    claude_md = build_tree / DUAL_FILE_ROOT_NAME
    if not claude_md.is_file():
        return None
    for d in DUAL_FILE_OPEN_ITEMS_DIRS:
        base = build_tree if d == "." else (build_tree / d)
        if not base.is_dir():
            continue
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_file() and OPEN_ITEMS_NAME_RE.match(entry.name):
                return [claude_md, entry]
    return None


def locate_resume_state_artifact(build_tree: Path):
    """Returns (layout, [Path, ...]) or (None, []) if nothing recognized."""
    single = _find_single_file_artifact(build_tree)
    if single is not None:
        return "single", single
    dual = _find_dual_file_artifact(build_tree)
    if dual is not None:
        return "dual", dual
    return None, []


def _read_text(path: Path) -> str:
    # Project markdown/notes files are not guaranteed UTF-8 (a recurring,
    # already-documented trap in this exact agent's own Step 3 standing
    # rules) -- fall back to a permissive decode rather than raising.
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def check_schema_sections(texts: List[str]) -> Dict[str, Any]:
    combined = "\n".join(texts)
    missing: List[str] = []
    citation_hits = len(CITATION_RE.findall(combined))
    if citation_hits < MIN_CITATIONS_FOR_EVIDENCE_SECTION:
        missing.append("evidence_gathered_with_citations")
    for key, pattern in SECTION_PATTERNS.items():
        if not pattern.search(combined):
            missing.append(key)
    return {
        "missing_sections": missing,
        "citation_count": citation_hits,
        "checked_sections": list(ALL_SECTION_KEYS),
    }


def _max_mtime(paths: List[Path]) -> float:
    return max(p.stat().st_mtime for p in paths)


def scan_max_other_mtime(build_tree: Path, exclude_paths: List[Path]) -> Optional[float]:
    """Walks build_tree (excluding STALENESS_SCAN_EXCLUDE_DIRS and the
    artifact's own files) and returns the newest mtime found, or None if
    the tree contains no other files."""
    exclude_resolved = {p.resolve() for p in exclude_paths}
    newest: Optional[float] = None
    for root, dirs, files in os.walk(build_tree):
        dirs[:] = [d for d in dirs if d not in STALENESS_SCAN_EXCLUDE_DIRS]
        for fname in files:
            fpath = Path(root) / fname
            try:
                resolved = fpath.resolve()
            except OSError:
                continue
            if resolved in exclude_resolved:
                continue
            try:
                mtime = fpath.stat().st_mtime
            except OSError:
                continue
            if newest is None or mtime > newest:
                newest = mtime
    return newest


def check_resume_state_artifact(
    build_tree_path: str,
    stale_threshold_seconds: int = DEFAULT_STALE_THRESHOLD_SECONDS,
    _now: Optional[float] = None,
) -> CheckpointCheckResult:
    """Given a build-tree path, checks whether a resume-state artifact
    matching CORE/agent-checkpoint-discipline/SKILL.md's schema exists and
    looks current. Never raises for an ordinary "not found"/"stale" outcome
    -- those are reported via `.ok is False` + `.reason`; only a genuinely
    unexpected OS error propagates."""
    build_tree = Path(build_tree_path)
    if not build_tree.is_dir():
        return CheckpointCheckResult(
            ok=False, reason="BUILD_TREE_NOT_FOUND",
            detail={"build_tree_path": build_tree_path},
        )

    layout, artifact_paths = locate_resume_state_artifact(build_tree)
    if layout is None:
        return CheckpointCheckResult(
            ok=False, reason="NO_RESUME_ARTIFACT_FOUND",
            detail={
                "build_tree_path": str(build_tree),
                "checked_single_file_locations": [
                    str((build_tree / d / n) if d != "." else (build_tree / n))
                    for d in SINGLE_FILE_DIRS for n in SINGLE_FILE_NAMES
                ],
                "checked_dual_file_root": str(build_tree / DUAL_FILE_ROOT_NAME),
            },
        )

    texts = [_read_text(p) for p in artifact_paths]
    schema_result = check_schema_sections(texts)
    artifact_mtime = _max_mtime(artifact_paths)
    other_mtime = scan_max_other_mtime(build_tree, exclude_paths=artifact_paths)

    now = _now if _now is not None else time.time()
    staleness_gap = None
    stale = False
    if other_mtime is not None:
        staleness_gap = other_mtime - artifact_mtime
        stale = staleness_gap > stale_threshold_seconds

    detail = {
        "build_tree_path": str(build_tree),
        "layout": layout,
        "artifact_paths": [str(p) for p in artifact_paths],
        "missing_sections": schema_result["missing_sections"],
        "citation_count": schema_result["citation_count"],
        "artifact_mtime": artifact_mtime,
        "newest_other_file_mtime": other_mtime,
        "staleness_gap_seconds": staleness_gap,
        "stale_threshold_seconds": stale_threshold_seconds,
        "checked_at": now,
    }

    if schema_result["missing_sections"]:
        return CheckpointCheckResult(
            ok=False, reason="RESUME_ARTIFACT_INCOMPLETE", detail=detail,
        )
    if stale:
        return CheckpointCheckResult(
            ok=False, reason="RESUME_ARTIFACT_STALE", detail=detail,
        )
    return CheckpointCheckResult(ok=True, reason="RESUME_ARTIFACT_CURRENT", detail=detail)


def _main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=(
            "Check a build/investigation tree for a resume-state artifact "
            "matching CORE/agent-checkpoint-discipline/SKILL.md's schema."
        )
    )
    parser.add_argument("build_tree", help="Path to the build tree to check")
    parser.add_argument(
        "--stale-threshold-hours", type=float, default=DEFAULT_STALE_THRESHOLD_SECONDS / 3600,
        help="Hours of gap (artifact mtime vs. newest other file in tree) before flagging stale",
    )
    args = parser.parse_args(argv)

    result = check_resume_state_artifact(
        args.build_tree,
        stale_threshold_seconds=int(args.stale_threshold_hours * 3600),
    )
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0 if result.ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_main())
