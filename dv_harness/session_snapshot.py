from __future__ import annotations
import json, os, re, shutil, subprocess, time
from pathlib import Path
from typing import Any, Dict, List, Optional

# A "session" snapshot covers the CURRENT-RUN layer only -- state/control/
# blackboard/plans/react/agents/telemetry/config/project_meta/events -- and
# deliberately NEVER the durable knowledge layer (memory/, i.e. the 5-level
# Memory Hierarchy + Corner-Case Library) or static policy config (graph/,
# workflow/, governance/, inference/, qualification/). This mirrors the
# project's own Blackboard-vs-Memory distinction (CLAUDE.md: "Blackboard
# stores current verification truth" / "Verification Memory stores
# historical verified engineering knowledge") -- restoring an OLD session
# must never regress knowledge accumulated since it was saved, and must
# never touch static config files that define how the harness behaves.
SESSION_FILES = ["state.json", "control.json", "project_meta.json", "config.json", "events.jsonl"]
SESSION_DIRS = ["blackboard", "plans", "react", "agents", "telemetry", "lsf"]

# events.jsonl is saved into every snapshot (useful to see "what had
# happened by save time"), but deliberately excluded from what restore_session
# copies BACK -- an append-only audit log should never be destructively
# rewound; restore_session appends a SESSION_RESTORED marker to the live,
# continuous events.jsonl instead (see cli.py/dashboard.py callers).
RESTORE_FILES = [f for f in SESSION_FILES if f != "events.jsonl"]

SESSIONS_SUBDIR = "sessions"


def _default_user() -> str:
    # Same fallback chain as control_plane.py's _default_user() / this
    # feature's knowledge_center.py sibling -- kept as a separate private
    # copy rather than a cross-module import so this module stays a plain,
    # dependency-light snapshot utility.
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def _current_git_sha(root: Path) -> Optional[str]:
    # Same subprocess pattern as dv_harness/engine.py's DVHarness._git_sha()
    # (not imported, to keep this module a plain, dependency-light snapshot
    # utility) -- reused here so restore_session() can cross-check CLAUDE.md's
    # "Same regression batch must use the same source/build/config identity"
    # rule against a REAL current SHA, not just replay the saved state blindly.
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(root), text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _slug(name: str) -> str:
    name = (name or "").strip()
    out = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return out or time.strftime("%Y%m%d-%H%M%S")


def _sessions_root(project_root: Path) -> Path:
    d = Path(project_root) / ".dv-harness" / SESSIONS_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_json(p: Path, default=None):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_session(project_root: Path, name: Optional[str] = None, note: str = "") -> Dict[str, Any]:
    """Copy the current run-state layer under `.dv-harness/sessions/<name>/`.
    Raises FileExistsError if `name` already exists (an explicit --name
    is a request for a stable, reusable label, not something a second save
    should silently clobber -- pick a new name, or restore/inspect the old
    one first)."""
    root = Path(project_root)
    name = _slug(name) if name else time.strftime("%Y%m%d-%H%M%S")
    dest = _sessions_root(root) / name
    if dest.exists():
        raise FileExistsError(f"session '{name}' already exists -- choose a different name")
    dvh = root / ".dv-harness"
    dest.mkdir(parents=True)

    copied_files, copied_dirs, missing = [], [], []
    for fn in SESSION_FILES:
        src = dvh / fn
        if src.exists():
            shutil.copy2(src, dest / fn)
            copied_files.append(fn)
        else:
            missing.append(fn)
    for dn in SESSION_DIRS:
        src = dvh / dn
        if src.exists() and src.is_dir():
            shutil.copytree(src, dest / dn)
            copied_dirs.append(dn)

    state = _read_json(dest / "state.json", {}) or {}
    manifest = {
        "name": name,
        "note": note,
        "saved_at": time.time(),
        "saved_by": _default_user(),
        "current_stage": state.get("current_stage"),
        "active_stages": state.get("active_stages", []),
        "overall_status": state.get("overall_status"),
        "git_sha": state.get("git_sha"),
        "server_sha": state.get("server_sha"),
        "files": copied_files,
        "dirs": copied_dirs,
        "missing": missing,
    }
    (dest / "session_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def list_sessions(project_root: Path) -> List[Dict[str, Any]]:
    root = _sessions_root(Path(project_root))
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        mf = _read_json(d / "session_manifest.json")
        if mf:
            out.append(mf)
    out.sort(key=lambda m: m.get("saved_at") or 0, reverse=True)
    return out


class SourceIdentityMismatchError(RuntimeError):
    """Raised by restore_session() when require_sha_match=True and the
    real, current git SHA differs from the SHA recorded in the snapshot
    being restored -- CLAUDE.md's "Same regression batch must use the same
    source/build/config identity" rule, enforced at restore time instead of
    only documented as a policy."""
    def __init__(self, saved_sha, current_sha):
        super().__init__(
            f"session was saved at git_sha={saved_sha!r} but the current working "
            f"tree is at git_sha={current_sha!r} -- restoring this session's state "
            f"now would silently pair old run-state with different source; pass "
            f"require_sha_match=False to override if this is genuinely intended."
        )
        self.saved_sha = saved_sha
        self.current_sha = current_sha


def restore_session(project_root: Path, name: str, backup_current: bool = True,
                     require_sha_match: bool = False) -> Dict[str, Any]:
    """Copy a saved snapshot back over the live `.dv-harness/` run-state
    layer. Unless `backup_current=False`, the state being overwritten is
    itself saved first (as `_pre_restore_<epoch>`) so a restore is never a
    one-way, unrecoverable action -- the immediately-previous state is
    always one more `restore_session` call away.

    `require_sha_match` defaults False for backward compatibility (existing
    callers keep working unchanged); the return dict's `sha_match` field is
    always populated honestly regardless, so a caller/dashboard can surface
    the real comparison even when not enforcing it. `sha_match` is None
    (not True/False) when either side's SHA is unknown (not a git repo, or
    the snapshot predates this field) -- an unknown comparison is never
    reported as a false match."""
    root = Path(project_root)
    src = _sessions_root(root) / _slug(name)
    manifest_path = src / "session_manifest.json"
    if not src.is_dir() or not manifest_path.exists():
        raise FileNotFoundError(f"no saved session named '{name}'")
    manifest = _read_json(manifest_path, {})

    saved_sha = manifest.get("git_sha")
    current_sha = _current_git_sha(root)
    sha_match = (saved_sha == current_sha) if (saved_sha and current_sha) else None
    if require_sha_match and sha_match is False:
        raise SourceIdentityMismatchError(saved_sha, current_sha)

    backup_name = None
    if backup_current:
        backup = save_session(root, name=f"_pre_restore_{int(time.time())}",
                               note=f"auto-backup before restoring '{name}'")
        backup_name = backup["name"]

    dvh = root / ".dv-harness"
    dvh.mkdir(parents=True, exist_ok=True)
    for fn in manifest.get("files", []):
        if fn not in RESTORE_FILES:
            continue
        s = src / fn
        if s.exists():
            shutil.copy2(s, dvh / fn)
    for dn in manifest.get("dirs", []):
        s = src / dn
        d = dvh / dn
        if not s.exists():
            continue
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(s, d)

    return {"restored": name, "auto_backup": backup_name, "manifest": manifest,
            "saved_sha": saved_sha, "current_sha": current_sha, "sha_match": sha_match}


def delete_session(project_root: Path, name: str) -> bool:
    src = _sessions_root(Path(project_root)) / _slug(name)
    if not src.is_dir():
        return False
    shutil.rmtree(src)
    return True
