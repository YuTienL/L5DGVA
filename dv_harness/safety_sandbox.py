"""dv_harness/safety_sandbox.py -- Safety Sandbox / Change Containment (2026-09-06).

GAP THIS CLOSES. `change_blast_radius.py` measures a change's reach AFTER a real
git diff already exists -- it is a push/merge gate, and its own docstring says so
plainly: it scores `git diff --name-only`, it runs at pre-push/pre-merge-commit
time, and it can only ever turn an already-allowed push into a block. Nothing in
this repo bounds a change BEFORE it is made: an agent about to start a task has
no mechanism that lets it (or a human reviewing its plan) DECLARE, up front,
which files/paths it intends to touch, and then have every subsequent proposed
write checked against that declaration before the write happens. A repo-wide
grep for `SandboxDeclaration`/`declared sandbox`/`change containment` before
this module returned nothing executable.

`capability_evolution.py`'s controlled-experiment machinery
(`_prepare_shadow_run()`/`_execute_shadow_run()`/`_apply_mutation()`) is the
closest real precedent, and its containment PATTERN -- resolve every path,
check it is `_within()` a fixed root, raise a dedicated PermissionError
subclass naming exactly what escaped, before any write happens -- is the
pattern this module reuses. It is deliberately not imported: that module's
containment is hardcoded to ONE destination (a freshly-copied experiment
workspace under `.dv-harness/experiments/`), so nothing in it can express "an
arbitrary, human/agent-declared allowlist of paths inside the LIVE project
tree", which is what a pre-change sandbox has to be. This module re-derives
the same resolve-and-check discipline for that different, wider shape.

WHAT A SANDBOX IS. A `SandboxDeclaration` is a named, attributed, persisted
record: which path patterns (exact paths, directory prefixes, or glob
patterns) an agent-proposed change may touch, who declared it and why, made
BEFORE any write. `declare_sandbox()` persists one to
`.dv-harness/sandbox/declarations/<sandbox_id>.json`
(`storage._atomic_replace()`, the same atomic-write convention
`waiver_store.py`/`golden_scenario.py` already use -- no second JSON-write
helper). `assess_proposed_change()` / `assert_change_within_sandbox()` are the
enforcement half: given a list of paths a change is ABOUT to write, every path
is classified against the declaration before anything is written. There is no
code path anywhere in this module that performs a write to the paths being
checked -- checking a sandbox is never itself a mutating act on the target
paths.

EVIDENCE TRUTH RULE, applied to "no sandbox was ever declared". A path
checked against a `sandbox_id` this project has no declaration file for is
NEVER silently read as ALLOWED -- that would be exactly the fabricated-permit
failure this module exists to prevent. It is reported `NOT_DECLARED`, and
`assert_change_within_sandbox()` refuses (raises) on it precisely as it does
on a real violation. The only way to get an ALLOWED verdict is a real,
on-disk declaration whose patterns really match every proposed path.

WORST-WINS COMPOSITE GATE. `assess_proposed_change()` checks every proposed
path independently and folds the whole batch to the worst single outcome
found -- one path outside the declared sandbox blocks the WHOLE change,
regardless of how many other paths in the same batch are cleanly inside it.
Severity order, most severe first: `INVALID_PATH` (an active escape attempt --
`..` traversal, an absolute path outside the project root, or a path that
resolves outside the root through a symlink) > `VIOLATION` (a real path,
inside the root, that the declared sandbox simply does not cover) >
`NOT_DECLARED` (no sandbox declaration exists for this id at all) >
`ALLOWED`. Nothing here averages, scores, or partially-credits a batch of
paths; the overall verdict is always exactly the worst individual path
result.

STRICTLY ADDITIVE, NEVER A SUBSTITUTE FOR change_blast_radius.py. This module
answers a different question than that one, and answering it does not relax
that one: change_blast_radius.py still runs at push/merge time over the real
diff and still scores REACH/SIZE/GOVERNANCE-file-touch against measured
thresholds. A change that stayed entirely inside its declared sandbox can
still be `TIER_WIDE` or `TIER_GOVERNANCE` under that gate and still require a
pinned human confirmation there -- this module never overrides, weakens, or
substitutes for that decision. `verify_diff_against_sandbox()` (below) is an
OPTIONAL, secondary, post-hoc check reusing `change_impact.changed_files()` --
the same real git-diff reader `change_blast_radius.py` itself reuses -- to
confirm a change that already landed stayed inside what was declared for it;
it answers "did the real diff match the pre-declared sandbox", never "is this
diff too big/too governance-sensitive", which stays change_blast_radius.py's
job alone.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .storage import _atomic_replace

# --- status vocabulary, deliberately not models.Status -----------------------
STATUS_ALLOWED = "ALLOWED"
STATUS_VIOLATION = "VIOLATION"
STATUS_INVALID_PATH = "INVALID_PATH"
STATUS_NOT_DECLARED = "NOT_DECLARED"

# Most severe first. INVALID_PATH (an active escape attempt) outranks a plain
# VIOLATION (a real, in-root path simply not covered); NOT_DECLARED (no
# evidence at all) is the fail-closed floor a check without a real declaration
# always lands on, deliberately worse than "ALLOWED" and deliberately never
# silently promoted to it.
_SEVERITY_ORDER = (STATUS_INVALID_PATH, STATUS_VIOLATION, STATUS_NOT_DECLARED, STATUS_ALLOWED)


def _severity_rank(status: str) -> int:
    try:
        return _SEVERITY_ORDER.index(status)
    except ValueError:
        return -1  # an unrecognized status is treated as more severe than everything


def _assert_vocabulary_disjoint_from_models_status() -> None:
    """Run once at import: this module's four-value status vocabulary must
    share no token with `dv_harness.models.Status` -- the same guard several
    sibling modules already run against their own domain vocabularies, so a
    sandbox check result can never be mistaken for a stage-gate verdict."""
    from .models import Status

    verdict_tokens = {m.value for m in Status}
    ours = {STATUS_ALLOWED, STATUS_VIOLATION, STATUS_INVALID_PATH, STATUS_NOT_DECLARED}
    collision = ours & verdict_tokens
    if collision:
        raise AssertionError(
            f"safety_sandbox status vocabulary collides with models.Status: {collision}"
        )


_assert_vocabulary_disjoint_from_models_status()


class SandboxError(ValueError):
    """A malformed sandbox declaration or a malformed check request -- a
    caller-usage defect, distinct from a real containment finding."""


class SandboxViolationError(PermissionError):
    """A proposed change is not entirely within its declared sandbox. Raised
    (never silently reported as allowed) by `assert_change_within_sandbox()`
    so a caller that forgets to check the return value still cannot proceed
    past an unbounded write."""

    def __init__(self, assessment: "SandboxAssessment"):
        self.assessment = assessment
        worst = assessment.status
        offending = [p.path for p in assessment.checked_paths if p.status != STATUS_ALLOWED]
        super().__init__(
            f"BLOCKED: proposed change is not within its declared sandbox "
            f"(sandbox_id={assessment.sandbox_id!r}, overall={worst}). "
            f"Offending path(s): {offending}. "
            f"{assessment.reasons[0] if assessment.reasons else ''}"
        )


# --- declaration --------------------------------------------------------------


@dataclass
class SandboxDeclaration:
    sandbox_id: str
    allowed_paths: List[str]
    declared_by: str
    reason: str
    created_at: str
    digest: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(payload: dict) -> "SandboxDeclaration":
        required = ("sandbox_id", "allowed_paths", "declared_by", "reason", "created_at")
        missing = [k for k in required if k not in payload]
        if missing:
            raise SandboxError(f"sandbox declaration missing required field(s): {missing}")
        return SandboxDeclaration(
            sandbox_id=str(payload["sandbox_id"]),
            allowed_paths=[str(p) for p in payload["allowed_paths"]],
            declared_by=str(payload["declared_by"]),
            reason=str(payload["reason"]),
            created_at=str(payload["created_at"]),
            digest=str(payload.get("digest") or ""),
        )


def _digest(sandbox_id: str, allowed_paths: Sequence[str]) -> str:
    payload = json.dumps(
        {"sandbox_id": sandbox_id, "allowed_paths": sorted(str(p) for p in allowed_paths)},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _sandbox_dir(root) -> Path:
    return Path(root) / ".dv-harness" / "sandbox" / "declarations"


def _sandbox_path(root, sandbox_id: str) -> Path:
    # sandbox_id is used as a bare filename component; refuse anything that
    # could escape the declarations directory rather than sanitize it, since
    # a silently-sanitized id could collide two distinct sandboxes together.
    if not sandbox_id or "/" in sandbox_id or "\\" in sandbox_id or sandbox_id in (".", ".."):
        raise SandboxError(f"invalid sandbox_id {sandbox_id!r}: must be a bare filename component")
    return _sandbox_dir(root) / f"{sandbox_id}.json"


def declare_sandbox(root, allowed_paths: Sequence[str], *, declared_by: str, reason: str,
                     sandbox_id: Optional[str] = None) -> SandboxDeclaration:
    """Persist a new sandbox declaration BEFORE any change is made under it.

    `allowed_paths` may be empty -- a legitimate "this agent may write
    nothing" declaration -- but every non-empty entry must be a real,
    non-blank string; `declared_by` and `reason` are mandatory (an
    unattributed sandbox is not a real declaration, the same discipline
    `waiver_store.record_waiver()`/`golden_scenario.record_golden_scenario()`
    already apply to their own attributed records). Re-declaring the same
    `sandbox_id` OVERWRITES it -- a sandbox is meant to be declared once, at
    the start of a task, not silently amended mid-task; a caller that wants a
    wider sandbox mid-task should declare a NEW id so the narrower one it
    started under stays on disk as a real historical fact.
    """
    if not declared_by or not str(declared_by).strip():
        raise SandboxError("declare_sandbox() requires a real declared_by identity")
    if not reason or not str(reason).strip():
        raise SandboxError("declare_sandbox() requires a real, non-empty reason")
    patterns = [str(p) for p in (allowed_paths or [])]
    for p in patterns:
        if not p.strip():
            raise SandboxError("declare_sandbox() refuses a blank allowed_paths entry")

    root = Path(root).resolve()
    sid = sandbox_id or "SBX-{}-{}".format(
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
        hashlib.sha256(
            f"{declared_by}|{reason}|{patterns}|{datetime.now(timezone.utc).isoformat()}"
            .encode("utf-8")
        ).hexdigest()[:8],
    )
    decl = SandboxDeclaration(
        sandbox_id=sid, allowed_paths=patterns, declared_by=str(declared_by),
        reason=str(reason), created_at=datetime.now(timezone.utc).isoformat(),
        digest=_digest(sid, patterns),
    )
    path = _sandbox_path(root, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, dir=str(path.parent), encoding="utf-8")
    try:
        json.dump(decl.to_dict(), tmp, indent=2)
        tmp.close()
        _atomic_replace(tmp.name, path)
    except Exception:
        tmp.close()
        try:
            Path(tmp.name).unlink()
        except FileNotFoundError:
            pass
        raise
    return decl


def load_sandbox(root, sandbox_id: str) -> Optional[SandboxDeclaration]:
    """A real, on-disk declaration, or None -- never a fabricated default.
    None is the honest "no evidence of a sandbox" answer that
    `assess_proposed_change()` turns into NOT_DECLARED for every path."""
    try:
        path = _sandbox_path(root, sandbox_id)
    except SandboxError:
        return None
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SandboxDeclaration.from_dict(payload)


def list_sandboxes(root) -> List[SandboxDeclaration]:
    directory = _sandbox_dir(root)
    if not directory.is_dir():
        return []
    out: List[SandboxDeclaration] = []
    for p in sorted(directory.glob("*.json")):
        try:
            out.append(SandboxDeclaration.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return out


# --- path classification -------------------------------------------------


def normalize_relpath(root, path) -> Optional[str]:
    """POSIX-style path relative to `root`, or None when it cannot be
    expressed as one (an absolute path elsewhere, or a `..`-laden path that
    resolves outside root). Never raises -- callers decide what an
    unresolvable path means for their own status."""
    root = Path(root).resolve()
    candidate = Path(path)
    try:
        resolved = (root / candidate).resolve() if not candidate.is_absolute() \
            else candidate.resolve()
    except OSError:
        return None
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return None
    return rel.as_posix()


def _match_segments(path_segs: Sequence[str], pat_segs: Sequence[str]) -> bool:
    """Recursive per-segment glob match. A `*`/`?`/`[...]` in one pattern
    segment (via `fnmatch.fnmatchcase`) matches only WITHIN that one path
    segment -- it never crosses a `/`, unlike plain `fnmatch` on a whole
    string, where `*` matches everything including path separators. A bare
    `**` segment matches zero or more whole path segments, so it is the one
    wildcard that DOES cross directory boundaries."""
    if not pat_segs:
        return not path_segs
    head = pat_segs[0]
    if head == "**":
        if _match_segments(path_segs, pat_segs[1:]):
            return True
        if path_segs and _match_segments(path_segs[1:], pat_segs):
            return True
        return False
    if not path_segs:
        return False
    if not fnmatch.fnmatchcase(path_segs[0], head):
        return False
    return _match_segments(path_segs[1:], pat_segs[1:])


def path_matches_pattern(relpath: str, pattern: str) -> bool:
    """Three pattern shapes, all resolved through one segment-boundary-aware
    matcher (`_match_segments()`): an exact relative-path match; a
    directory-prefix match (a pattern ending in `/` covers every path under
    it, including the bare directory itself); and a per-segment glob match,
    where `*`/`?`/`[...]` inside one path segment behave like an ordinary
    shell glob (never crossing a `/`) and a literal `**` segment matches zero
    or more whole path segments."""
    pattern = pattern.replace("\\", "/").strip()
    if not pattern:
        return False
    if pattern == relpath:
        return True
    if pattern.endswith("/"):
        pattern = (pattern[:-1] + "/**") if pattern != "/" else "**"
    return _match_segments(relpath.split("/"), pattern.split("/"))


@dataclass
class PathCheckResult:
    path: str
    relpath: Optional[str]
    status: str
    matched_pattern: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def classify_path(root, declaration: Optional[SandboxDeclaration], path) -> PathCheckResult:
    """One path's classification against one (possibly absent) declaration.

    Order matters: containment is checked FIRST, independent of whether a
    declaration exists at all -- an escape attempt is INVALID_PATH whether or
    not a sandbox was ever declared for the change carrying it, because it is
    a defect in the path itself, not a question the sandbox could answer
    either way."""
    relpath = normalize_relpath(root, path)
    if relpath is None:
        return PathCheckResult(
            path=str(path), relpath=None, status=STATUS_INVALID_PATH,
            reason=f"{path!r} does not resolve to a path inside {Path(root).resolve()}",
        )
    if declaration is None:
        return PathCheckResult(
            path=str(path), relpath=relpath, status=STATUS_NOT_DECLARED,
            reason="no sandbox declaration exists for this sandbox_id -- an undeclared "
                   "change is never treated as allowed",
        )
    for pattern in declaration.allowed_paths:
        if path_matches_pattern(relpath, pattern):
            return PathCheckResult(
                path=str(path), relpath=relpath, status=STATUS_ALLOWED, matched_pattern=pattern,
            )
    return PathCheckResult(
        path=str(path), relpath=relpath, status=STATUS_VIOLATION,
        reason=f"{relpath!r} matches none of the declared sandbox's "
               f"{len(declaration.allowed_paths)} allowed path pattern(s)",
    )


# --- the pre-flight assessment --------------------------------------------


@dataclass
class SandboxAssessment:
    sandbox_id: str
    status: str
    checked_paths: List[PathCheckResult] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        out = asdict(self)
        return out


def assess_proposed_change(root, sandbox_id: str, proposed_paths: Sequence[str]) -> SandboxAssessment:
    """The pre-flight check: every path a change is ABOUT to write, checked
    against the declared sandbox BEFORE any write happens. Worst-wins over
    the whole batch -- see the module docstring's severity order."""
    if not proposed_paths:
        raise SandboxError("assess_proposed_change() needs at least one proposed path to check")
    declaration = load_sandbox(root, sandbox_id)
    checked = [classify_path(root, declaration, p) for p in proposed_paths]
    worst = min(checked, key=lambda r: _severity_rank(r.status))
    overall = worst.status
    reasons: List[str] = []
    if overall == STATUS_ALLOWED:
        reasons.append(
            f"all {len(checked)} proposed path(s) are within the sandbox declared under "
            f"{sandbox_id!r}"
        )
    else:
        offenders = [r for r in checked if r.status == overall]
        reasons.append(
            f"{len(offenders)} of {len(checked)} proposed path(s) are {overall}: "
            + "; ".join(f"{r.path} ({r.reason})" for r in offenders)
        )
    return SandboxAssessment(sandbox_id=sandbox_id, status=overall, checked_paths=checked,
                              reasons=reasons)


def assert_change_within_sandbox(root, sandbox_id: str, proposed_paths: Sequence[str]) -> SandboxAssessment:
    """Raising variant of `assess_proposed_change()` -- the real pre-flight
    gate an agent's own write step should call before touching disk. Returns
    the assessment on success so a caller can still inspect it; raises
    `SandboxViolationError` (never a silent pass) the moment the overall
    status is anything but ALLOWED."""
    assessment = assess_proposed_change(root, sandbox_id, proposed_paths)
    if assessment.status != STATUS_ALLOWED:
        raise SandboxViolationError(assessment)
    return assessment


# --- optional post-hoc verification against a real diff --------------------


def verify_diff_against_sandbox(root, sandbox_id: str, base_rev: Optional[str] = None,
                                 head_rev: str = "HEAD") -> SandboxAssessment:
    """Confirm a change that has ALREADY landed stayed inside what was
    declared for it, by checking the REAL git diff against the declaration.

    This is a secondary, optional convenience -- the primary mechanism this
    module provides is the pre-flight check above, run BEFORE a write. This
    function reuses `change_impact.changed_files()` (the same real
    `git diff --name-only` reader `change_blast_radius.py` itself reuses,
    never a second diff implementation) purely to source the real file list;
    it answers a different question than change_blast_radius.py's own gate
    (did the diff match what was pre-declared, never how big or
    governance-sensitive the diff is) and never substitutes for it.

    No real diff (no git, unresolvable base/head) reports the same
    NOT_DECLARED-shaped honesty change_impact.py itself already uses for its
    own diff_status, folded here into a single explanatory path-result rather
    than silently treating "no diff" as "nothing to check"."""
    from .change_impact import changed_files, resolve_sha

    base = base_rev
    if base is None:
        raise SandboxError("verify_diff_against_sandbox() requires a base_rev to diff against")
    diff = changed_files(Path(root), base, head_rev)
    if diff["status"] != "REAL_DIFF":
        placeholder = PathCheckResult(
            path="<no real diff>", relpath=None, status=STATUS_INVALID_PATH,
            reason=f"no real diff to verify (status={diff['status']}); a sandbox cannot be "
                   "verified against a change nobody could measure",
        )
        return SandboxAssessment(sandbox_id=sandbox_id, status=STATUS_INVALID_PATH,
                                  checked_paths=[placeholder],
                                  reasons=[placeholder.reason])
    files = diff.get("files") or []
    if not files:
        return SandboxAssessment(sandbox_id=sandbox_id, status=STATUS_ALLOWED, checked_paths=[],
                                  reasons=["real diff contains zero changed files"])
    return assess_proposed_change(root, sandbox_id, files)


# --- CLI / ad hoc front door -----------------------------------------------


def render_assessment(assessment: SandboxAssessment) -> str:
    lines = [f"sandbox_id: {assessment.sandbox_id}", f"status: {assessment.status}"]
    for r in assessment.checked_paths:
        lines.append(f"  [{r.status}] {r.path}" + (f" -> {r.matched_pattern}" if r.matched_pattern else ""))
    for reason in assessment.reasons:
        lines.append(f"reason: {reason}")
    return "\n".join(lines)


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.safety_sandbox")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_declare = sub.add_parser("declare")
    p_declare.add_argument("--paths", nargs="*", default=[])
    p_declare.add_argument("--declared-by", required=True)
    p_declare.add_argument("--reason", required=True)
    p_declare.add_argument("--sandbox-id", default=None)

    p_check = sub.add_parser("check")
    p_check.add_argument("--sandbox-id", required=True)
    p_check.add_argument("--paths", nargs="+", required=True)

    p_verify = sub.add_parser("verify-diff")
    p_verify.add_argument("--sandbox-id", required=True)
    p_verify.add_argument("--base", required=True)
    p_verify.add_argument("--head", default="HEAD")

    p_status = sub.add_parser("status")
    p_status.add_argument("--sandbox-id", required=True)

    p_list = sub.add_parser("list")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.verb == "declare":
        try:
            decl = declare_sandbox(root, args.paths, declared_by=args.declared_by,
                                    reason=args.reason, sandbox_id=args.sandbox_id)
        except SandboxError as e:
            print(f"REFUSED: {e}")
            return 2
        print(json.dumps(decl.to_dict(), indent=2))
        return 0

    if args.verb == "check":
        try:
            assessment = assess_proposed_change(root, args.sandbox_id, args.paths)
        except SandboxError as e:
            print(f"REFUSED: {e}")
            return 2
        print(render_assessment(assessment))
        if assessment.status == STATUS_ALLOWED:
            return 0
        if assessment.status == STATUS_NOT_DECLARED:
            return 2
        return 1

    if args.verb == "verify-diff":
        try:
            assessment = verify_diff_against_sandbox(root, args.sandbox_id, args.base, args.head)
        except SandboxError as e:
            print(f"REFUSED: {e}")
            return 2
        print(render_assessment(assessment))
        if assessment.status == STATUS_ALLOWED:
            return 0
        if assessment.status == STATUS_NOT_DECLARED:
            return 2
        return 1

    if args.verb == "status":
        decl = load_sandbox(root, args.sandbox_id)
        if decl is None:
            print(f"NOT_DECLARED: no sandbox {args.sandbox_id!r} on disk under {root}")
            return 2
        print(json.dumps(decl.to_dict(), indent=2))
        return 0

    if args.verb == "list":
        decls = list_sandboxes(root)
        print(json.dumps([d.to_dict() for d in decls], indent=2))
        return 0 if decls else 2

    parser.error(f"unknown verb {args.verb!r}")
    return 2


def main() -> None:
    sys.exit(execute_verb())


if __name__ == "__main__":
    main()
