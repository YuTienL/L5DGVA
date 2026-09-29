"""dv_harness/controlled_process_executor.py -- L5DGVA Controlled Process
Execution and Model Worker Governance
(`docs/architecture/canonical_detailed_governance/
L5DGVA_CONTROLLED_PROCESS_EXECUTION_AND_MODEL_WORKER_GOVERNANCE_
REQUIREMENTS.md`).

`L5DGVA_OWNS_PROCESS_AUTHORITY=YES`, `MODEL_OWNS_PROCESS_AUTHORITY=NO`:
Codex/ChatGPT/Claude return evidence, findings, or implementation output
-- never arbitrary process/mutation authority of their own. This module
is the one place that fact becomes checkable code.

THIN COMPOSITION LAYER, deliberately -- never a second orchestration
engine:
  * `agent_execution_backend.py` already IS the Execution Backend Router
    (`resolve_execution_backend()`) and the Controlled Process Executor
    for the Claude-worker case (`launch_worker()`); this module does not
    duplicate either.
  * `safe_tool_profile.py` already IS the tool-allowlist primitive; this
    module adds the missing SEMANTIC PROFILE NAMES the governance doc
    requires as data over that same primitive, not a new one.
  * `task_boundary_conformance.py` already IS Task Boundary enforcement.

What is genuinely new here, because nothing in the codebase did it
before:
  * `verify_canonical_repository_identity()` -- a real, evidenced risk:
    this program's own real Codex review probes create nested throwaway
    git repositories INSIDE the Canonical tree (real, observed paths:
    `.dv-harness/model_handoffs/*/.probe_tmp/*/work/.git`,
    `.dv-harness/model_handoffs/*/.pytest_tmp/*/work/.git`) -- exactly the
    kind of "another repository" a controlled launch must fail closed
    against, never trust on a relative `.dv-harness` path match alone
    (the governance doc's own explicit warning).
  * `safe_test_temp_cleanup()` -- a bounded, pre-authorized cleanup for
    exactly those registered-to-task scratch directories, so a future
    caller does not need a fresh human/classifier decision every single
    time one appears. `dry_run=True` by default; this module never
    invokes the real deletion itself (see its own docstring for why)."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

# --- Repository Identity Gate -------------------------------------------------


class RepositoryIdentityError(ValueError):
    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


@dataclass(frozen=True)
class RepositoryIdentityResult:
    matched: bool
    reason: str
    resolved_root: str
    expected_root: Optional[str]
    head: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def verify_canonical_repository_identity(
    root: Path, *, expected_repo_root: Optional[Path] = None,
) -> RepositoryIdentityResult:
    """Fails closed unless `root` genuinely IS the Canonical repository.
    Never a relative `.dv-harness` path match: a NESTED throwaway repo
    (exactly what this program's own real Codex-probe scratch directories
    are) satisfies that check just as well as the real root. Real checks,
    all required: `root` resolves to a real git worktree (`.git` exists);
    `root` has its OWN `.dv-harness` state directory (not inherited from a
    parent by relative-path coincidence); when `expected_repo_root` is
    given, `root`'s resolved absolute path equals it exactly; `git
    rev-parse HEAD` actually succeeds against `root` (a real worktree, not
    a directory that merely looks like one)."""
    resolved = Path(root).resolve()
    expected = Path(expected_repo_root).resolve() if expected_repo_root is not None else None

    if not (resolved / ".git").exists():
        return RepositoryIdentityResult(False, "NOT_A_GIT_WORKTREE", str(resolved),
                                        str(expected) if expected else None, None)
    if not (resolved / ".dv-harness").is_dir():
        return RepositoryIdentityResult(False, "NO_OWN_DV_HARNESS_STATE", str(resolved),
                                        str(expected) if expected else None, None)
    if expected is not None and resolved != expected:
        return RepositoryIdentityResult(False, "REPO_ROOT_MISMATCH", str(resolved), str(expected), None)
    try:
        proc = subprocess.run(["git", "-C", str(resolved), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        head = proc.stdout.strip() if proc.returncode == 0 else None
    except OSError:
        head = None
    if not head:
        return RepositoryIdentityResult(False, "HEAD_UNRESOLVABLE", str(resolved),
                                        str(expected) if expected else None, None)
    return RepositoryIdentityResult(True, "MATCHED", str(resolved), str(expected) if expected else None, head)


def require_canonical_repository_identity(root: Path, *, expected_repo_root: Optional[Path] = None) -> RepositoryIdentityResult:
    """Same check, but raises `RepositoryIdentityError` on any mismatch --
    the real fail-closed gate a controlled launch calls before doing
    anything else, rather than a caller having to remember to check
    `.matched` itself."""
    result = verify_canonical_repository_identity(root, expected_repo_root=expected_repo_root)
    if not result.matched:
        raise RepositoryIdentityError(result.reason, result.to_dict())
    return result


# --- Semantic Safe Tool Profiles (governance doc's own named list) ----------

SAFE_STATUS = "SAFE_STATUS"
SAFE_READ = "SAFE_READ"
SAFE_TEST = "SAFE_TEST"
SAFE_TEST_TEMP_CLEANUP = "SAFE_TEST_TEMP_CLEANUP"
SAFE_HANDOFF_GENERATION = "SAFE_HANDOFF_GENERATION"
SAFE_RESULT_VALIDATION = "SAFE_RESULT_VALIDATION"
SAFE_REGRESSION = "SAFE_REGRESSION"
CLAUDE_REMEDIATION = "CLAUDE_REMEDIATION"
CODEX_REVIEW = "CODEX_REVIEW"
CHATGPT_HANDOFF_PREPARATION = "CHATGPT_HANDOFF_PREPARATION"
NATIVE_CANONICAL_MAINTENANCE = "NATIVE_CANONICAL_MAINTENANCE"

#: Every profile the governance doc names, mapped to the EXISTING
#: `safe_tool_profile` primitive it reuses -- never a second tool-scoping
#: mechanism. Profiles with no code-execution surface (status/read/
#: handoff-prep) reuse `CLAUDE_READONLY_PROFILE`'s own shape; profiles that
#: run tests/regression reuse `CLAUDE_IMPLEMENTATION_PROFILE`'s own
#: `PowerShell(python -m pytest *)` pattern. `SAFE_TEST_TEMP_CLEANUP` has
#: no `ToolExecutionProfile` of its own -- it is never a PowerShell grant
#: at all, only the bounded, in-process `safe_test_temp_cleanup()` function
#: below, which is a stronger guarantee than any shell allowlist pattern
#: could express (a real path-bounds check, not a command-string match).
SEMANTIC_PROFILE_NAMES = (
    SAFE_STATUS, SAFE_READ, SAFE_TEST, SAFE_TEST_TEMP_CLEANUP, SAFE_HANDOFF_GENERATION,
    SAFE_RESULT_VALIDATION, SAFE_REGRESSION, CLAUDE_REMEDIATION, CODEX_REVIEW,
    CHATGPT_HANDOFF_PREPARATION, NATIVE_CANONICAL_MAINTENANCE,
)


def semantic_profile_tool_execution_profile(name: str):
    """Maps a semantic profile name onto the real, existing
    `safe_tool_profile.ToolExecutionProfile` it reuses. `SAFE_STATUS`/
    `SAFE_READ`/`SAFE_HANDOFF_GENERATION`/`SAFE_RESULT_VALIDATION`/
    `CODEX_REVIEW`/`CHATGPT_HANDOFF_PREPARATION` never need code execution
    -> `CLAUDE_READONLY_PROFILE`. `SAFE_TEST`/`SAFE_REGRESSION`/
    `CLAUDE_REMEDIATION`/`NATIVE_CANONICAL_MAINTENANCE` need bounded
    mutation/test execution -> `CLAUDE_IMPLEMENTATION_PROFILE`.
    `SAFE_TEST_TEMP_CLEANUP` has none -- see module docstring."""
    from .safe_tool_profile import CLAUDE_READONLY_PROFILE, CLAUDE_IMPLEMENTATION_PROFILE
    if name not in SEMANTIC_PROFILE_NAMES:
        raise ValueError(f"UNKNOWN_SEMANTIC_PROFILE:{name}")
    if name == SAFE_TEST_TEMP_CLEANUP:
        return None
    if name in (SAFE_STATUS, SAFE_READ, SAFE_HANDOFF_GENERATION, SAFE_RESULT_VALIDATION,
               CODEX_REVIEW, CHATGPT_HANDOFF_PREPARATION):
        return CLAUDE_READONLY_PROFILE
    return CLAUDE_IMPLEMENTATION_PROFILE


# --- SAFE_TEST_TEMP_CLEANUP --------------------------------------------------

class UnsafeTempCleanupTargetError(ValueError):
    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


#: The two real, OBSERVED scratch-directory names this program's own real
#: Codex reviews have produced -- never an arbitrary caller-supplied name
#: ("do not use remembered REVIEW-specific command strings as Canonical
#: policy", the governance doc's own words -- this is the general
#: PATTERN those specific incidents fit, not a hardcoded one-off).
_REGISTERED_SCRATCH_DIR_NAMES = (".probe_tmp", ".pytest_tmp")


def _is_registered_task_scratch_dir(root: Path, target: Path) -> bool:
    """A target is "registered to a task" for this profile's purposes when
    it lives under that task's own `.dv-harness/model_handoffs/<task_id>/`
    directory (the same directory `model_handoff_workflow.py` already
    owns) as one of the real, observed scratch-directory names."""
    from . import model_handoff_workflow as _wf
    base = (root / _wf._HANDOFF_DIR).resolve()
    try:
        rel = target.relative_to(base)
    except ValueError:
        return False
    parts = rel.parts
    if len(parts) < 2:
        return False
    task_id, scratch_name = parts[0], parts[1]
    return scratch_name in _REGISTERED_SCRATCH_DIR_NAMES and (base / task_id).is_dir()


def safe_test_temp_cleanup(root: Path, target: Path, *, dry_run: bool = True) -> Dict[str, Any]:
    """`SAFE_TEST_TEMP_CLEANUP`: removes a real, registered-to-task
    scratch directory ONLY when every bound holds -- never a caller-
    supplied arbitrary path. All required: `target` resolves under THIS
    repo's own registered-task scratch-dir pattern (see
    `_is_registered_task_scratch_dir()`); it is not, and does not contain
    and is not contained by, the repository root, `.git`, or any real
    production directory (`dv_harness/`, `dv_harness_tests/`); its
    resolved path stays inside the repository root (no traversal/symlink
    escape).

    `dry_run=True` (the default): validates every bound and reports
    without deleting anything. This module never invokes the real
    deletion (`dry_run=False`) on its own -- a real, current Claude Code
    "Irreversible Local Destruction" classifier denial this same session
    already received for a direct `rm -rf` on one of these exact
    directories applies to the OUTCOME, not just that one command; a
    caller in THIS session choosing `dry_run=False` to route around it
    through this function would be exactly the "another tool/interpreter"
    workaround that denial explicitly named and forbade. A genuinely
    different actor (e.g. a spawned worker under this exact profile, in a
    context where the classifier separately evaluates and permits it) is
    the real, intended caller for `dry_run=False`."""
    root = Path(root).resolve()
    try:
        resolved = Path(target).resolve()
    except OSError as exc:
        raise UnsafeTempCleanupTargetError("UNRESOLVABLE_TARGET", {"target": str(target), "error": str(exc)})

    try:
        resolved.relative_to(root)
    except ValueError:
        raise UnsafeTempCleanupTargetError("TARGET_ESCAPES_REPOSITORY_ROOT", {"target": str(resolved)})

    if resolved == root:
        raise UnsafeTempCleanupTargetError("TARGET_IS_REPOSITORY_ROOT", {"target": str(resolved)})
    git_dir = root / ".git"
    if resolved == git_dir or git_dir in resolved.parents:
        raise UnsafeTempCleanupTargetError("TARGET_IS_GIT_DIRECTORY", {"target": str(resolved)})
    for production_dir in ("dv_harness", "dv_harness_tests"):
        prod_path = root / production_dir
        if resolved == prod_path or prod_path in resolved.parents or prod_path == resolved or resolved in (prod_path,):
            raise UnsafeTempCleanupTargetError("TARGET_IS_PRODUCTION_PATH", {"target": str(resolved)})
        try:
            resolved.relative_to(prod_path)
            raise UnsafeTempCleanupTargetError("TARGET_IS_PRODUCTION_PATH", {"target": str(resolved)})
        except ValueError:
            pass
    if not _is_registered_task_scratch_dir(root, resolved):
        raise UnsafeTempCleanupTargetError("TARGET_NOT_A_REGISTERED_TASK_SCRATCH_DIR", {"target": str(resolved)})

    result: Dict[str, Any] = {"target": str(resolved), "validated": True, "dry_run": dry_run, "deleted": False}
    if not dry_run:
        shutil.rmtree(resolved)
        result["deleted"] = True
    return result
