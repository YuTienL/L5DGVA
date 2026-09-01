from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess, time
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
# (SESSION_EXTRA_DIRS/SESSION_ARTIFACT_REFERENCE_DIRS below extend this
# CURRENT-RUN layer with two more real per-run artifact kinds -- command.txt/
# scenario content and FSDB/coverage -- while respecting this same
# CURRENT-RUN-only intent; see their own comments for the two rulings.)
SESSION_FILES = ["state.json", "control.json", "project_meta.json", "config.json", "events.jsonl"]
SESSION_DIRS = ["blackboard", "plans", "react", "agents", "telemetry", "lsf"]

# SESSION_EXTRA_DIRS / SESSION_ARTIFACT_REFERENCE_DIRS (session-snapshot-
# extension, 2026-09-01): a 2026-09-01 AI-mechanism architecture audit found
# command.txt/scenario content, FSDB waveform references and coverage data
# entirely absent from every snapshot -- by omission, not by a considered
# design choice, since SESSION_FILES/SESSION_DIRS above never named them.
# Both new lists are kept SEPARATE from SESSION_DIRS on purpose: every
# SESSION_DIRS entry is resolved relative to `.dv-harness/` (see
# save_session()'s `dvh / dn` below), while these two are project-scaffold
# directories that live directly under project_root -- generated/... and
# project_input/... in this repo's own scaffolding layout -- a structurally
# different root, so silently overloading SESSION_DIRS's existing meaning
# would be the wrong fix even though the CLI surface (save-session/
# restore-session) stays the same.
#
# RULING 1 (command.txt/scenario content -- copied wholesale, like any
# SESSION_DIRS entry): the audit named two candidate locations,
# generated/06_tests and project_input/08_command. Only
# generated/06_tests/command_catalog qualifies as CURRENT-RUN state per this
# module's own top-of-file design comment -- it is the harness's own
# per-run-generated scenario/command catalog, the same tier as plans/react/
# agents above. project_input/08_command is deliberately EXCLUDED: it is
# durable project SOURCE material (the raw command.txt handed over once at
# project onboarding, analogous to project_input/02_dut RTL, which this
# module has likewise never copied since it is source-tree content, not
# run state) -- copying it on every save-session would not track "what
# changed this run" the way state.json/blackboard/plans genuinely do, and
# would make every snapshot larger for no run-state benefit. It is small
# text either way, so wholesale copy (not a reference) is the right choice
# for the one directory that IS in scope.
SESSION_EXTRA_DIRS = ["generated/06_tests/command_catalog"]

# RULING 2 (FSDB waveform / coverage -- REFERENCE only, never copied): these
# are exactly the large, often multi-GB binary artifact this module's own
# top-of-file comment implies a lightweight CURRENT-RUN snapshot was never
# meant to carry -- copying them wholesale would turn a cheap, frequent
# checkpoint action into a slow, disk-doubling one, unlike every other
# SESSION_DIRS/SESSION_EXTRA_DIRS entry (all small JSON/text control-plane
# or scenario-catalog content). Instead, save_session() records a
# REFERENCE for each directory that exists under project_root: relative
# path + size (+ sha256, streamed rather than loaded whole) for every file
# found under it, into session_manifest.json's new "artifact_references"
# field -- enough to say "the FSDB/coverage this run produced was exactly
# these bytes at this path" without ever duplicating the binary content.
# restore_session() deliberately never touches these directories either --
# there is nothing here to restore, only a record of what existed at save
# time.
SESSION_ARTIFACT_REFERENCE_DIRS = {
    "fsdb": "generated/10_runtime/waveform",
    "coverage": "generated/11_coverage",
}
# A file larger than this is listed by path+size only (sha256 omitted,
# honestly, via "hash_skipped_reason" -- never a fabricated digest).
# Hashing a many-GB waveform dump on every save-session would defeat the
# "lightweight snapshot" goal Ruling 2 above exists to preserve.
ARTIFACT_REFERENCE_HASH_SIZE_LIMIT_BYTES = 200 * 1024 * 1024  # 200 MB

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


def _hash_file(path: Path, limit_bytes: int) -> Dict[str, Any]:
    """One artifact_references entry for `path`: always {size}, plus a real
    streamed sha256 UNLESS the file exceeds `limit_bytes` or cannot be read
    -- see ARTIFACT_REFERENCE_HASH_SIZE_LIMIT_BYTES's own comment for why a
    large file is skipped rather than hashed. Never fabricates a digest for
    the skipped/unreadable case; "hash_skipped_reason" says why instead."""
    try:
        size = path.stat().st_size
    except OSError as e:
        return {"size": None, "sha256": None, "hash_skipped_reason": f"stat failed: {e}"}
    entry: Dict[str, Any] = {"size": size}
    if size > limit_bytes:
        entry["sha256"] = None
        entry["hash_skipped_reason"] = f"file exceeds {limit_bytes}-byte hashing limit"
        return entry
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        entry["sha256"] = h.hexdigest()
    except OSError as e:
        entry["sha256"] = None
        entry["hash_skipped_reason"] = f"read failed: {e}"
    return entry


def _collect_artifact_references(root: Path) -> Dict[str, List[Dict[str, Any]]]:
    """See SESSION_ARTIFACT_REFERENCE_DIRS's own Ruling 2 comment: a
    REFERENCE (relative path + size/+hash) for every file under each
    configured directory that exists, never the binary content itself. A
    key with no existing directory (or an existing-but-empty one) is simply
    omitted from the result, not written as an empty list -- consistent
    with how `missing`/`dirs` below already only record what is real."""
    refs: Dict[str, List[Dict[str, Any]]] = {}
    for key, rel in SESSION_ARTIFACT_REFERENCE_DIRS.items():
        d = root / rel
        if not d.is_dir():
            continue
        entries = []
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            info = _hash_file(p, ARTIFACT_REFERENCE_HASH_SIZE_LIMIT_BYTES)
            info["path"] = str(p.relative_to(root)).replace(os.sep, "/")
            entries.append(info)
        if entries:
            refs[key] = entries
    return refs


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

    # SESSION_EXTRA_DIRS: project_root-relative (NOT .dv-harness-relative,
    # unlike SESSION_DIRS above) -- see this module's Ruling 1 comment.
    # Copied under dest/"extra"/<same relative path> so this never collides
    # with anything copied from .dv-harness/ above. A missing directory is
    # silently skipped, exactly like a missing SESSION_DIRS entry above
    # (neither is added to `missing`, which is reserved for SESSION_FILES).
    copied_extra_dirs: List[str] = []
    for rel in SESSION_EXTRA_DIRS:
        src = root / rel
        if src.exists() and src.is_dir():
            extra_dest = dest / "extra" / rel
            extra_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, extra_dest)
            copied_extra_dirs.append(rel)

    artifact_references = _collect_artifact_references(root)

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
        # dut_version/tb_version (session-snapshot-extension, 2026-09-01):
        # see models.py's HarnessState.dut_version docstring -- real,
        # gate-validated VERIFY-stage identity when known, None otherwise.
        "dut_version": state.get("dut_version"),
        "tb_version": state.get("tb_version"),
        "files": copied_files,
        "dirs": copied_dirs,
        "missing": missing,
        # extra_dirs/artifact_references (session-snapshot-extension,
        # 2026-09-01): see SESSION_EXTRA_DIRS/SESSION_ARTIFACT_REFERENCE_DIRS
        # comments above for the two rulings these implement.
        "extra_dirs": copied_extra_dirs,
        "artifact_references": artifact_references,
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

    # SESSION_EXTRA_DIRS restore (session-snapshot-extension, 2026-09-01):
    # symmetric with the SESSION_DIRS loop above, but rooted at project_root
    # (not .dv-harness/) and reading back from dest/"extra"/<rel>, matching
    # exactly where save_session() put it -- see SESSION_EXTRA_DIRS's own
    # Ruling 1 comment. A manifest predating this feature simply has no
    # "extra_dirs" key, so this is a no-op for an old snapshot (get([])).
    for rel in manifest.get("extra_dirs", []):
        s = src / "extra" / rel
        d = root / rel
        if not s.exists():
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
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
