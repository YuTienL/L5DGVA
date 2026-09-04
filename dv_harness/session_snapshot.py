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
# Phase 14 addendum (2026-09-03, obsidian-memory-debugflow task): SESSION_
# FILES/SESSION_DIRS above already cover the raw files a resume needs
# (state.json for current_stage/project, react/ for the latest hypothesis/
# evidence/confidence/next_action, lsf/ for job state) -- what was missing
# was a lightweight, save-time SUMMARY of them in session_manifest.json
# itself, so a restored session can answer "where we stopped / what was
# proven / what remains unknown / what action should execute next" by
# reading the manifest, without first having to know react.py's/
# lsf_client.py's own private directory layouts. See
# _read_latest_react_iteration()/_collect_current_job_reference()/
# _collect_related_memory_references()/describe_resume_point() below --
# every one of these READS already-real files/records, none is a new write
# path, and `related_memory` is deliberately REFERENCES ONLY (memory_id/
# level/title), consistent with this module's own "never the durable
# knowledge layer" design above -- it points at Memory, it does not copy it.
SESSION_FILES = ["state.json", "control.json", "project_meta.json", "config.json", "events.jsonl"]
SESSION_DIRS = ["blackboard", "plans", "react", "agents", "telemetry", "lsf", "evidence"]

# RULING 3 ("evidence", added 2026-09-04 by a re-audit of this mechanism
# against the user's own required-field list): `.dv-harness/evidence/` holds
# `evidence.duckdb` (`evidence_db.DB_PATH_PARTS`), whose `normalized_evidence`
# table is keyed by the `evidence_id` the user's list names explicitly. It was
# absent from all four capture lists above -- by omission, exactly like the
# 2026-09-01 command.txt/FSDB/coverage gap -- so every save silently dropped
# it. The round-trip proof: delete `.dv-harness/evidence/`, restore, and the
# directory used to stay gone because the snapshot never held it.
# react/'s own per-attempt `evidence` blocks are NOT a substitute: those are
# adapter-attempt gate reasons, a different and narrower corpus than the
# queryable evidence_id records the reconciliation cycle writes
# (`regression_reporter.py`) and MCP reads (`mcp/regression_queries.py`).
#
# It is a plain SESSION_DIRS entry -- same CURRENT-RUN tier as lsf/react, so
# the generic copytree/rmtree+copytree loops below handle it with no special
# case -- but it is the ONE entry that is not plain JSON, so it carries two
# protections the others do not need (SESSION_BEST_EFFORT_DIRS below):
#   - A live DuckDB file is held open by real production callers
#     (`regression_reporter.py`'s `with EvidenceStore(db_path) as store:`,
#     `mcp/runtime.py`). A copy can therefore fail for a reason no JSON dir
#     can -- an exclusive file lock, or a snapshot landing mid-transaction.
#     Losing the WHOLE save_session() to that would take every other
#     captured field down with it, so this entry's copy/restore is
#     best-effort and the manifest records WHY it was skipped, rather than
#     dropping the field a second, quieter way.
#   - Size. Every other SESSION_DIRS entry is small JSON; an evidence store
#     for a large regression is not, and save_auto_checkpoint() fires on
#     every stage transition with DEFAULT_AUTO_CHECKPOINT_KEEP retained.
#     Past EVIDENCE_DIR_COPY_SIZE_LIMIT_BYTES the directory is recorded as a
#     REFERENCE (path+size+sha256, via the same _hash_file() Ruling 2 uses)
#     instead of copied -- the same "a lightweight checkpoint never turns
#     into a disk-doubling one" doctrine, applied to the one control-plane
#     directory that can grow like an artifact.
#
# Restore rewinds this directory wholesale, like blackboard/plans/react/lsf
# and unlike events.jsonl. That does destructively rewind the deliberately
# append-only `regression_verdict_history` table (see evidence_db.py) back to
# save time -- accepted, because restore_session()'s own `_pre_restore_`
# auto-backup captures the newer store first, so the discarded history is
# always one restore away, which is exactly the safety net every other
# destructive directory restore here already relies on.
SESSION_BEST_EFFORT_DIRS = {"evidence"}

# 64 MB: at DEFAULT_AUTO_CHECKPOINT_KEEP=10 retained auto-checkpoints this
# bounds the evidence store's worst-case contribution to ~640 MB. It is a
# ceiling for a pathological store, not a routine path -- this repo's own
# real `.dv-harness/evidence/evidence.duckdb` is ~2 MB, the same order as the
# JSON directories beside it.
EVIDENCE_DIR_COPY_SIZE_LIMIT_BYTES = 64 * 1024 * 1024

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

# --- Auto-checkpoint naming + bounded retention (2026-09-03, harness-
# reliability task: "checkpoint 與回滾：每個階段留可回復點, agent 走偏時不必
# 從頭") -----------------------------------------------------------------
#
# save_session()/restore_session() above already do all the real work,
# including the source-identity (git SHA) mismatch protection a rollback
# needs. What was missing was that NOTHING called save_session()
# automatically -- it fired only on an explicit `dv-harness save-session`,
# so an agent that went off the rails mid-run had a recovery point only if a
# human had happened to make one. engine.DVHarness.run_stage() now calls
# save_auto_checkpoint() at every real stage transition (see its own
# best-effort call site there).
#
# Two prefixes, deliberately distinct, because retention MUST be able to tell
# these three kinds of snapshot apart:
#   - AUTO_CHECKPOINT_PREFIX ("auto_"): machine-generated, one per stage
#     transition, cheap and numerous -- the ONLY kind prune_auto_checkpoints()
#     is ever allowed to delete.
#   - PRE_RESTORE_PREFIX ("_pre_restore_"): restore_session()'s own
#     auto-backup of the state it is about to overwrite. Never pruned here:
#     it is the undo of a destructive action, and deleting it would remove
#     the very safety net that makes a restore reversible.
#   - anything else: a human's deliberately-named `save-session --name foo`.
#     Never pruned here -- an explicit name is a request for a stable,
#     reusable label (see save_session()'s own FileExistsError docstring).
AUTO_CHECKPOINT_PREFIX = "auto_"
PRE_RESTORE_PREFIX = "_pre_restore_"

# Keep the last N auto-checkpoints. A stage transition snapshot is small
# (control-plane JSON + per-run dirs; FSDB/coverage are references, never
# copied -- see Ruling 2 above), but "small" times "every transition of every
# retry of every stage, forever" is still unbounded growth on a long project.
DEFAULT_AUTO_CHECKPOINT_KEEP = 10


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


def _dir_size_bytes(d: Path) -> int:
    """Total bytes of every regular file under `d`. Unreadable entries are
    skipped rather than raising -- this only feeds the
    EVIDENCE_DIR_COPY_SIZE_LIMIT_BYTES decision, and a directory we cannot
    fully stat is one the copy attempt below will report on honestly anyway."""
    total = 0
    for p in d.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def _dir_file_references(d: Path, root: Path) -> List[Dict[str, Any]]:
    """path+size(+sha256) for every file under `d`, the same reference shape
    _collect_artifact_references() produces for FSDB/coverage -- reused here
    for an evidence store too large to copy (Ruling 3), so an over-limit
    snapshot still records exactly which bytes existed at save time instead
    of recording nothing."""
    entries = []
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        info = _hash_file(p, ARTIFACT_REFERENCE_HASH_SIZE_LIMIT_BYTES)
        info["path"] = str(p.relative_to(root)).replace(os.sep, "/")
        entries.append(info)
    return entries


def _copy_session_dir(src: Path, dest: Path, name: str) -> Optional[str]:
    """Copy one SESSION_DIRS entry. Returns None when it was copied, or a
    plain-language reason string when it was deliberately skipped.

    Only a name in SESSION_BEST_EFFORT_DIRS can be skipped: for every other
    entry a copy failure propagates, because a snapshot silently missing
    blackboard/plans/react/lsf would be worse than no snapshot at all. See
    Ruling 3 above for why the evidence store is the one exception."""
    if name in SESSION_BEST_EFFORT_DIRS:
        size = _dir_size_bytes(src)
        if size > EVIDENCE_DIR_COPY_SIZE_LIMIT_BYTES:
            return (f"directory is {size} bytes, over the "
                    f"{EVIDENCE_DIR_COPY_SIZE_LIMIT_BYTES}-byte copy limit -- "
                    f"recorded as an artifact reference instead")
    try:
        shutil.copytree(src, dest)
    except Exception as e:
        if name not in SESSION_BEST_EFFORT_DIRS:
            raise
        # Never leave a half-copied directory behind claiming to be a snapshot.
        shutil.rmtree(dest, ignore_errors=True)
        return f"copy failed: {type(e).__name__}: {e}"
    return None


def _read_latest_react_iteration(dvh: Path, stage: Optional[str]) -> Optional[Dict[str, Any]]:
    """Session-snapshot extension (Phase 14, 2026-09-03, obsidian-memory-
    debugflow task): the real hypothesis/evidence/confidence/next_action
    snapshot for the CURRENT stage, read from the highest-numbered
    `iteration_NNN.json` under `.dv-harness/react/<stage>/` -- the exact
    same file `react.ReactRecorder.record()` already writes once per stage
    attempt (`reason_summary`/`evidence`/`confidence`/`next_action` fields,
    see react.py). This is a READ of an already-real file, not a new write
    path: `react` is already one of SESSION_DIRS above, so the file this
    reads is already copied into every snapshot regardless of this
    function existing -- this only extracts a lightweight, save-time
    summary of it into `session_manifest.json` so a restored session can
    see "what was proven / what remains unknown / what action should
    execute next" without having to know react.py's own directory layout
    or open the raw per-iteration files itself."""
    if not stage:
        return None
    d = dvh / "react" / stage
    if not d.is_dir():
        return None
    files = sorted(d.glob("iteration_*.json"), key=lambda p: p.name)
    if not files:
        return None
    return _read_json(files[-1])


def _collect_current_job_reference(dvh: Path) -> Optional[Dict[str, Any]]:
    """Session-snapshot extension (Phase 14): a lightweight REFERENCE
    (job_id/pattern/lsf_status/sim_status/uvm_error_count/uvm_fatal_count),
    never the full JobState content, for the single job most likely to be
    "the current one" -- the most recently changed record under
    `.dv-harness/lsf/jobs/*.json` (real files, already copied wholesale as
    part of SESSION_DIRS' "lsf" entry above; this only extracts a quick-
    glance index entry for the manifest, the same "reference, not full
    content" discipline Ruling 2 above already applies to FSDB/coverage).
    Returns None when no job has ever been recorded for this project --
    an honest absence, not a fabricated placeholder job."""
    d = dvh / "lsf" / "jobs"
    if not d.is_dir():
        return None
    best = None
    best_ts = ""
    for p in sorted(d.glob("*.json")):
        data = _read_json(p, {}) or {}
        ts = str(data.get("last_change_time") or "")
        if best is None or ts > best_ts:
            best = data
            best_ts = ts
    if best is None:
        return None
    return {
        "job_id": best.get("job_id"), "pattern": best.get("pattern"),
        "lsf_status": best.get("lsf_status"), "sim_status": best.get("sim_status"),
        "uvm_error_count": best.get("uvm_error_count"), "uvm_fatal_count": best.get("uvm_fatal_count"),
    }


def _collect_related_memory_references(root: Path, stage: Optional[str], project: Optional[str],
                                        note: str = "") -> List[Dict[str, Any]]:
    """Session-snapshot extension (Phase 14): REFERENCES ONLY (memory_id/
    level/title/root_cause/confidence), never full record content -- the
    durable Memory tier (`.dv-harness/memory/`) is deliberately excluded
    from every session snapshot (see this module's own top-of-file design
    comment: it is durable knowledge, not current-run state). This is a
    lightweight index of which prior records were relevant AT SAVE TIME, so
    a restored session knows WHICH memory to re-fetch (via
    `dv_harness.memory.MemoryStore.get(memory_id)` / `memory_cli`) on
    demand, rather than a duplicate copy of the records themselves. Reuses
    the exact same MemoryRetriever.search() engine.py's own run_stage()
    already calls for its `relevant_memory` prompt context (step 1b) --
    not a second, differently-scored search."""
    try:
        from .memory import MemoryStore, MemoryRetriever
        query_text = " ".join(str(v) for v in (stage, project, note) if v).strip()
        hits = MemoryRetriever(MemoryStore(root)).search({"text": query_text}, limit=5)
        return [
            {"memory_id": h["memory"].get("memory_id"), "level": h["memory"].get("level"),
             "title": h["memory"].get("title"), "root_cause": h["memory"].get("root_cause"),
             "confidence": h["memory"].get("confidence")}
            for h in hits
        ]
    except Exception:
        return []


def describe_resume_point(manifest: Dict[str, Any]) -> str:
    """Session-snapshot extension (Phase 14): a short, plain-language answer
    to "where we stopped / what was proven / what remains unknown / what
    action should execute next", built ONLY from fields this same manifest
    already carries (current_stage/current_job/current_hypothesis/
    current_evidence/current_confidence/pending_action/related_memory) --
    never a re-analysis, never new evidence gathering. Intended so an agent
    (or a human) reading `restore_session()`'s return value does not have to
    manually cross-reference every manifest field itself; this is purely a
    formatting convenience over already-real data."""
    lines = [f"Stopped at stage: {manifest.get('current_stage') or 'unknown'} "
             f"(overall_status={manifest.get('overall_status') or 'unknown'})."]
    if manifest.get("current_project"):
        lines.append(f"Project: {manifest['current_project']}.")
    job = manifest.get("current_job")
    if job:
        lines.append(f"Current job: {job.get('job_id')} (pattern={job.get('pattern')}, "
                      f"lsf_status={job.get('lsf_status')}, sim_status={job.get('sim_status')}).")
    if manifest.get("current_hypothesis"):
        lines.append(f"What was proven / last hypothesis: {manifest['current_hypothesis']}")
    if manifest.get("current_evidence"):
        lines.append(f"Evidence gathered: {manifest['current_evidence']}")
    if manifest.get("current_confidence"):
        lines.append(f"Confidence: {manifest['current_confidence']}.")
    related = manifest.get("related_memory") or []
    if related:
        lines.append("Related prior memory (references, re-fetch by memory_id before trusting): "
                      + ", ".join(str(r.get("memory_id")) for r in related if r.get("memory_id")))
    if manifest.get("pending_action"):
        lines.append(f"What remains unknown / next action to execute: {manifest['pending_action']}")
    else:
        lines.append("No pending_action was recorded for this stage at save time -- "
                      "re-evaluate the current stage's own gate evidence before proceeding.")
    return "\n".join(lines)


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
    dirs_copy_skipped: Dict[str, str] = {}
    for dn in SESSION_DIRS:
        src = dvh / dn
        if not (src.exists() and src.is_dir()):
            continue
        reason = _copy_session_dir(src, dest / dn, dn)
        if reason:
            dirs_copy_skipped[dn] = reason
        else:
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
    # Ruling 3: a SESSION_BEST_EFFORT_DIRS entry that was skipped still gets
    # its bytes RECORDED (path+size+sha256), so an over-limit or locked
    # evidence store is a known, identified absence in the manifest rather
    # than an unexplained one.
    for dn in dirs_copy_skipped:
        entries = _dir_file_references(dvh / dn, root)
        if entries:
            artifact_references[dn] = entries

    state = _read_json(dest / "state.json", {}) or {}
    current_stage = state.get("current_stage")
    # Phase 14 (2026-09-03, obsidian-memory-debugflow task -- Session Save/
    # Restore): "where we stopped" alone (current_stage/overall_status,
    # already captured above since 2026-09-01) is not enough to resume
    # without re-analyzing from zero. These four reads are ALL real,
    # already-persisted CURRENT-RUN facts (never re-derived/guessed at save
    # time): the current stage's own latest react iteration record supplies
    # hypothesis/evidence/confidence/next_action; the LSF jobs dir and the
    # Memory tier supply lightweight references. See each helper's own
    # docstring above for why every one of these is a REFERENCE/READ, never
    # a new write path or a duplicate copy of durable knowledge.
    react_snapshot = _read_latest_react_iteration(dvh, current_stage) or {}
    manifest = {
        "name": name,
        "note": note,
        "saved_at": time.time(),
        "saved_by": _default_user(),
        "current_stage": current_stage,
        "active_stages": state.get("active_stages", []),
        "overall_status": state.get("overall_status"),
        "git_sha": state.get("git_sha"),
        "server_sha": state.get("server_sha"),
        # dut_version/tb_version (session-snapshot-extension, 2026-09-01):
        # see models.py's HarnessState.dut_version docstring -- real,
        # gate-validated VERIFY-stage identity when known, None otherwise.
        "dut_version": state.get("dut_version"),
        "tb_version": state.get("tb_version"),
        # current_project/current_job/current_hypothesis/current_evidence/
        # current_confidence/pending_action/related_memory (Phase 14,
        # 2026-09-03): see the module-level docstring additions above for
        # what each is sourced from and why.
        "current_project": state.get("project"),
        "current_job": _collect_current_job_reference(dvh),
        "current_hypothesis": react_snapshot.get("reason_summary"),
        "current_evidence": react_snapshot.get("evidence"),
        "current_confidence": react_snapshot.get("confidence"),
        "pending_action": react_snapshot.get("next_action"),
        "related_memory": _collect_related_memory_references(root, current_stage, state.get("project"), note),
        "files": copied_files,
        "dirs": copied_dirs,
        "missing": missing,
        # dirs_copy_skipped (Ruling 3, 2026-09-04): {dir_name: why}, only ever
        # populated for a SESSION_BEST_EFFORT_DIRS entry. Empty dict is the
        # normal case; a non-empty one is the honest record of a captured
        # field that this particular save could not take, never a silent drop.
        "dirs_copy_skipped": dirs_copy_skipped,
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


def is_auto_checkpoint(name: str) -> bool:
    """True only for a machine-generated auto-checkpoint. Deliberately does
    NOT match PRE_RESTORE_PREFIX or a human's own --name, so retention can
    never reach either -- see AUTO_CHECKPOINT_PREFIX's comment above."""
    return bool(name) and name.startswith(AUTO_CHECKPOINT_PREFIX)


def list_auto_checkpoints(project_root: Path) -> List[Dict[str, Any]]:
    """The auto-checkpoint subset of list_sessions(), newest first. Reuses
    list_sessions() rather than re-walking the sessions directory, so both
    always agree on what exists and on the sort order."""
    return [m for m in list_sessions(project_root) if is_auto_checkpoint(str(m.get("name") or ""))]


def prune_auto_checkpoints(project_root: Path,
                            keep: int = DEFAULT_AUTO_CHECKPOINT_KEEP) -> List[str]:
    """Deletes the oldest auto-checkpoints beyond the newest `keep`, and
    returns the names actually removed (empty list when nothing needed
    pruning). Only ever touches names is_auto_checkpoint() accepts.

    `keep <= 0` is treated as "retention disabled" and deletes NOTHING --
    the safe reading of a misconfigured value, since the alternative
    (deleting every checkpoint) would destroy exactly the recovery points
    this feature exists to create."""
    if keep is None or int(keep) <= 0:
        return []
    checkpoints = list_auto_checkpoints(project_root)  # newest first
    removed: List[str] = []
    for manifest in checkpoints[int(keep):]:
        name = str(manifest.get("name") or "")
        if not is_auto_checkpoint(name):
            continue
        if delete_session(project_root, name):
            removed.append(name)
    return removed


def save_auto_checkpoint(project_root: Path, stage: Optional[str] = None,
                          attempt: Optional[int] = None, note: str = "",
                          keep: int = DEFAULT_AUTO_CHECKPOINT_KEEP) -> Dict[str, Any]:
    """One automatic stage-transition recovery point: a real save_session()
    (identical content and identical manifest to a hand-made one -- this adds
    no second snapshot format) under an `auto_`-prefixed name, immediately
    followed by bounded-retention pruning.

    The name embeds the real stage and attempt number so `dv-harness
    list-sessions` reads as a legible history ("auto_VERIFY_2_20260903-..."),
    and so two transitions within the same wall-clock second (a fast retry)
    do not collide. A collision is still possible in principle -- save_session()
    raises FileExistsError by design rather than clobbering -- so a bounded
    numeric suffix is tried before giving up, instead of letting a name clash
    silently cost a recovery point.

    Returns the manifest, with `pruned` added: the names retention removed on
    this call."""
    base = f"{AUTO_CHECKPOINT_PREFIX}{_slug(stage or 'stage')}"
    if attempt is not None:
        base += f"_{int(attempt)}"
    base += f"_{time.strftime('%Y%m%d-%H%M%S')}"
    manifest = None
    for suffix in ("", "-2", "-3", "-4", "-5"):
        try:
            manifest = save_session(project_root, name=base + suffix, note=note)
            break
        except FileExistsError:
            continue
    if manifest is None:
        raise FileExistsError(
            f"could not allocate an auto-checkpoint name from base '{base}' "
            f"(5 suffixes already taken)")
    manifest["pruned"] = prune_auto_checkpoints(project_root, keep=keep)
    return manifest


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
    # A SESSION_BEST_EFFORT_DIRS entry can fail to be rewound for the same
    # reason it can fail to be copied (a live DuckDB file held open by a
    # production caller -- Ruling 3). Aborting here would leave a PARTIAL
    # restore: state.json/blackboard already overwritten, the rest not. So
    # that one entry's failure is reported in the return value instead, and
    # every other directory still raises.
    dirs_restore_skipped: Dict[str, str] = {}
    for dn in manifest.get("dirs", []):
        s = src / dn
        d = dvh / dn
        if not s.exists():
            continue
        try:
            if d.exists():
                shutil.rmtree(d)
            shutil.copytree(s, d)
        except Exception as e:
            if dn not in SESSION_BEST_EFFORT_DIRS:
                raise
            dirs_restore_skipped[dn] = f"restore failed: {type(e).__name__}: {e}"

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
            "saved_sha": saved_sha, "current_sha": current_sha, "sha_match": sha_match,
            # dirs_restore_skipped (Ruling 3, 2026-09-04): {dir_name: why} for
            # any best-effort directory this restore could not rewind. Empty
            # dict is the normal case; a caller/dashboard that reports
            # "restored" without checking it is reporting an incomplete
            # restore as a complete one.
            "dirs_restore_skipped": dirs_restore_skipped,
            # resume_summary (Phase 14, 2026-09-03): a ready-to-read plain-
            # language answer to "where we stopped / what was proven / what
            # remains unknown / what action should execute next" -- see
            # describe_resume_point()'s own docstring. `.get(..., {})` so
            # restoring a snapshot saved BEFORE this feature (no
            # current_hypothesis/pending_action/etc. keys in its manifest)
            # degrades to the honest "no pending_action was recorded"
            # fallback line rather than raising on a missing key.
            "resume_summary": describe_resume_point(manifest)}


def delete_session(project_root: Path, name: str) -> bool:
    src = _sessions_root(Path(project_root)) / _slug(name)
    if not src.is_dir():
        return False
    shutil.rmtree(src)
    return True
