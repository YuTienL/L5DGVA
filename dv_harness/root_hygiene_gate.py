"""M1D canonical root-layout gate.

Real, decreed by M1D — Canonical Root Normalization (see
.work/phase3-dual-repo-consolidation/M1D_CANONICAL_ROOT_NORMALIZATION.md):
a new, unlisted root-level MD/PS1/CMD/JSON/TCL/SH file (or a `.gitignore`
rule quietly absorbing one) is a real architecture violation, never a
tooling detail to route around silently.

``PRODUCT_ROOT_ALLOWLIST`` is the strict allowlist -- every entry earned
its place with a real, evidenced, proven necessity (documented in the M1D
report), never "something references it" alone (the Phase-2 "has a
consumer => keep in root" rule this gate explicitly supersedes). Adding a
new root-level file to the real repository means either it belongs on
this list with a recorded reason, or it belongs in ``docs/<domain>/`` /
``scripts/powershell/`` / ``config/`` / ``generated/`` / ``examples/``
like everything this gate governs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

# Every one of these earned its place via a real M1D finding -- see
# M1D_CANONICAL_ROOT_NORMALIZATION.md for the evidence behind each:
#   - root-authority config/build/entry-point files (never moved)
#   - WORKFLOW_MANIFEST.json: a real gate script
#     (tools/verification_flow/gate_manifest_registry_consistency_gate.py)
#     hardcodes `root / "WORKFLOW_MANIFEST.json"` -- proven root-anchored.
#   - replay.ps1 + the 11 other *.ps1: each already a thin (2-30 line)
#     shim over canonical dv_harness/*.py logic, with a real, live,
#     multi-surface consumer expectation (START_HERE.md,
#     docs/remote/REMOTE_CONTROL_MODE.md, docs/MEMORY_OPERATIONS.md, and
#     a live .claude/skills/CORE/memory-retrieval/SKILL.md) that a
#     root-relative invocation. Moving any of these would only add
#     indirection, not reduce root file count.
PRODUCT_ROOT_ALLOWLIST = frozenset({
    # Root-authority config
    ".gitignore",
    ".claudeignore",
    # Root-authority governance/entry-point docs
    "README.md",
    "START_HERE.md",
    "CLAUDE.md",
    # Root-authority build/package config
    "pyproject.toml",
    "justfile",
    "requirements-harness.txt",
    # Proven-necessity manifest (real root-anchored gate consumer)
    "WORKFLOW_MANIFEST.json",
    # Proven-necessity thin launcher shims (real, live, multi-surface consumers)
    "replay.ps1",
    "DV_HARNESS_STATUS.ps1",
    "DV_MEMORY_GET.ps1",
    "DV_MEMORY_SEARCH.ps1",
    "DV_STAGE_PROFILE.ps1",
    "INSTALL.ps1",
    "REMOTE_CONTROL_READINESS.ps1",
    "REMOTE_CONTROL_START.ps1",
    "REMOTE_CONTROL_STATUS.ps1",
    "REMOTE_CONTROL_STOP.ps1",
    "START_DV_HARNESS.ps1",
    "START_DV_HARNESS_DASHBOARD.ps1",
})

# The extensions this gate actually governs. A root-level file with any
# other extension (a stray .txt, a lockfile, etc.) is out of this gate's
# scope -- root hygiene for those is a separate, not-yet-built concern,
# never silently claimed as covered by this one.
GOVERNED_EXTENSIONS = frozenset({".md", ".ps1", ".cmd", ".json", ".tcl", ".sh"})

_SUGGESTION_BY_EXTENSION = {
    ".md": "move it under docs/<domain>/ (architecture, workflow, verification, "
           "protocol, remote, knowledge, release, legacy, user-guide -- pick by "
           "the file's real semantic purpose, not its filename)",
    ".ps1": "move it under scripts/powershell/ (or scripts/powershell/legacy/ if superseded)",
    ".cmd": "move it under scripts/powershell/ (or scripts/powershell/legacy/ if superseded)",
    ".json": "move it under config/, generated/, or examples/ depending on its "
             "semantics (execution profile, regression/validation config, "
             "manifest, fixture, release snapshot, runtime state, or generated output)",
    ".tcl": "move it under scripts/tcl/",
    ".sh": "move it under scripts/shell/",
}


@dataclass(frozen=True)
class RootLayoutViolation:
    path: str
    suggestion: str


def check_root_layout(root: Union[str, Path]) -> List[RootLayoutViolation]:
    """Real, on-disk check: any file directly under ``root`` (not a
    subdirectory) whose extension this gate governs and whose bare name
    is not in ``PRODUCT_ROOT_ALLOWLIST`` is a violation.

    Never inspects subdirectories -- this gate is about the root level
    only, exactly like the M1D instruction scoped it.
    """
    root = Path(root)
    violations: List[RootLayoutViolation] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in GOVERNED_EXTENSIONS:
            continue
        if entry.name in PRODUCT_ROOT_ALLOWLIST:
            continue
        suggestion = _SUGGESTION_BY_EXTENSION[entry.suffix.lower()]
        violations.append(RootLayoutViolation(path=entry.name, suggestion=suggestion))
    return violations


def render_report(violations: List[RootLayoutViolation]) -> str:
    if not violations:
        return "ROOT_LAYOUT_GATE: PASS (0 violations)"
    lines = ["ROOT_LAYOUT_GATE: FAIL (%d violation(s))" % len(violations)]
    for v in violations:
        lines.append("  %s -- %s" % (v.path, v.suggestion))
    return "\n".join(lines)
