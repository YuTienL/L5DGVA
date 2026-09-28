"""dv_harness/result_ingestion.py -- Automatic External Result Ingestion
(`docs/architecture/canonical_detailed_governance/
L5DGVA_AUTOMATIC_EXTERNAL_RESULT_INGESTION_REQUIREMENTS.md`): the human
transports an artifact across the boundary; L5DGVA detects its return,
imports, validates, consumes/rejects, resumes and resolves the next action.

`HUMAN_MANUAL_IMPORT_REQUIRED=NO` -- but this module is deliberately NOT a
second ingestion engine. It owns only what the manual path never had:
which files to watch (registered expected results ONLY), whether a file is
finished being written, content identity (SHA-256), duplicate/quarantine
suppression, and resuming after the import. EVERY import -- automatic or
manual -- goes through `model_handoff_workflow.import_result()`, the single
Canonical parser/validator/consumer/registry/replay authority
(`AUTO_IMPORT_PATH == CANONICAL_IMPORT_PATH`; the manual
`python -m dv_harness.model_handoff_workflow import` verb now calls
`ingest_result_file()` too, so they share identity and quarantine state).

Correctness never depends on the watcher process being alive: the watcher
is a loop over `poll_once()`, and every step's state is persisted, so
`startup_scan()` (or a fresh watcher) resumes exactly where any earlier
process stopped. Detection never implies trust: a detected file is only
ever passed to the Canonical validator; returned content is never executed
and an external result is never rewritten.

Persistence (all beside the task's own state.json, additive):
  expected_result.json   the registration
  ingestion_state.json   per-SHA identity / import / quarantine records
  ingestion_events.jsonl append-only audit trace
  <model_handoffs>/result_watcher.json   watcher heartbeat
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from . import execution_contract as _ec
from . import model_handoff_workflow as _wf

# --- vocabulary ---------------------------------------------------------------

EVENTS = (
    "EXPECTED_RESULT_REGISTERED", "WATCH_STARTED", "RESULT_DETECTED", "RESULT_STABILITY_CONFIRMED",
    "RESULT_HASHED", "DUPLICATE_SUPPRESSED", "AUTO_IMPORT_STARTED", "RESULT_ACCEPTED", "RESULT_REJECTED",
    "RESULT_QUARANTINED", "RESULT_CONSUMED", "AUTO_RESUME_STARTED", "NEXT_ACTION_RESOLVED",
    # operational events beyond the required list
    "WATCH_TRANSIENT_ERROR", "AUTO_IMPORT_FAILED_TRANSIENT", "RESULT_UNSAFE_PATH", "REPLAY_SCHEDULED",
    "RESULT_CHANGED_AFTER_CONSUMPTION", "RESULT_CHANGED_DURING_IMPORT", "INGESTION_TERMINATED",
)

#: Workflow states in which an expected result may still (re)arrive: waiting
#: for transport, an import that was interrupted part-way, or a rejected
#: result whose changed content / scheduled replay may still be imported.
PENDING_WORKFLOW_STATES = (
    _wf.STATE_WAITING_FOR_HUMAN_TRANSPORT, _wf.STATE_RESULT_RETURNED, _wf.STATE_RESULT_VALIDATING,
    _wf.STATE_RESULT_ACCEPTED, _wf.STATE_RESULT_REJECTED,
)

H_IMPORT_STARTED = "IMPORT_STARTED"
H_CONSUMED = "CONSUMED"
H_QUARANTINED = "QUARANTINED"

RETRY_ON_CHANGE = "ON_CHANGED_HASH_OR_SCHEDULED_REPLAY_OR_AUTHORIZED_RECOVERY"
RETRY_REPLAY_SCHEDULED = "REPLAY_SCHEDULED"

_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class IngestionError(ValueError):
    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


@dataclass(frozen=True)
class IngestionPolicy:
    """Configurable, evidence-based policy (override with
    `.dv-harness/result_ingestion_policy.json`).

    Stability is primarily EVIDENCE: identical (size, mtime_ns, SHA-256)
    across `min_observations` observations spanning at least `quiet_seconds`,
    on a fully readable non-empty file. `quiet_seconds` only bounds how long
    a writer may pause between flushes; 2.0 s is a conservative starting
    point for local copy/editor/atomic-rename flushes, not a tuned constant.
    A mid-write import is also self-correcting by design (the partial
    content is rejected, its hash quarantined, and the completed file has a
    new hash that is retried automatically)."""
    quiet_seconds: float = 2.0
    min_observations: int = 2
    poll_interval_seconds: float = 5.0
    heartbeat_grace_factor: float = 3.0
    max_import_attempts: int = 5
    lock_stale_seconds: float = 120.0
    idle_exit_seconds: float = 600.0


def load_policy(root: Path) -> IngestionPolicy:
    p = Path(root) / ".dv-harness" / "result_ingestion_policy.json"
    if not p.is_file():
        return IngestionPolicy()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return IngestionPolicy()
    fields = IngestionPolicy.__dataclass_fields__
    return IngestionPolicy(**{k: type(getattr(IngestionPolicy(), k))(v) for k, v in raw.items() if k in fields})


# --- small persistence helpers ----------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_dir(root: Path, task_id: str) -> Path:
    if not _SAFE_TASK_ID.match(task_id or "") or ".." in task_id:
        raise IngestionError("UNSAFE_TASK_ID", {"task_id": task_id})
    return _wf._task_dir(Path(root), task_id)


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _expected_path(root: Path, task_id: str) -> Path:
    return _task_dir(root, task_id) / "RESULT_V1.md"


def _emit(root: Path, task_id: str, event: str, **details: Any) -> None:
    assert event in EVENTS, event
    path = _task_dir(root, task_id) / "ingestion_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": _now_iso(), "event": event, "task_id": task_id, **details}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")


def read_events(root: Path, task_id: str) -> List[Dict[str, Any]]:
    path = _task_dir(root, task_id) / "ingestion_events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _state_file(root: Path, task_id: str) -> Path:
    return _task_dir(root, task_id) / "ingestion_state.json"


def _load_ing(root: Path, task_id: str) -> Dict[str, Any]:
    st = _read_json(_state_file(root, task_id)) or {}
    st.setdefault("task_id", task_id)
    st.setdefault("results", {})
    st.setdefault("observation", None)
    st.setdefault("last_detected_result_sha256", None)
    st.setdefault("import_attempts", {})
    st.setdefault("suppression_logged", [])
    st.setdefault("auto_import_status", "IDLE")
    st.setdefault("auto_resume_status", "NOT_STARTED")
    return st


def _save_ing(root: Path, task_id: str, st: Dict[str, Any]) -> None:
    _atomic_write_json(_state_file(root, task_id), st)


@contextmanager
def _task_lock(root: Path, task_id: str, policy: IngestionPolicy) -> Iterator[bool]:
    """Single-writer per task across a watcher and any other poller / manual
    front door (the workflow's own O_EXCL lock primitive; a separate lock
    file from the import lock so poll -> import never self-blocks)."""
    lock = _task_dir(root, task_id) / "ingestion.lock"
    token = _wf._acquire_lock(lock, policy.lock_stale_seconds)
    try:
        yield token is not None
    finally:
        if token is not None:
            _wf._release_lock(lock, token)


# --- expected result registration --------------------------------------------

#: The complete registration schema `register_expected_result()` itself
#: writes. Used by `_valid_registration()` (REVIEW-005 R005-3) to require
#: every field present, never merely "some JSON object decoded".
_REGISTRATION_SCHEMA_FIELDS = (
    "TASK_ID", "TARGET_MODEL", "HANDOFF_FILE", "EXPECTED_RESULT_FILE",
    "EXPECTED_RESULT_CONTRACT", "EXPECTED_PRODUCER", "EXPECTED_TASK_TYPE",
    "CURRENT_HEAD", "WAIT_STATE", "CREATED_AT",
)


#: Real, known workflow-state vocabulary (never a hardcoded string copy --
#: sourced from `model_handoff_workflow`'s own `STATE_*` constants) used by
#: `_valid_registration()`'s WAIT_STATE domain check.
_KNOWN_WORKFLOW_STATES = (
    _wf.STATE_HANDOFF_READY, _wf.STATE_WAITING_FOR_HUMAN_TRANSPORT, _wf.STATE_RESULT_RETURNED,
    _wf.STATE_RESULT_VALIDATING, _wf.STATE_RESULT_ACCEPTED, _wf.STATE_RESULT_REJECTED,
    _wf.STATE_RESULT_CONSUMED,
)


def _valid_registration(reg: Any, root: Path, task_id: str) -> bool:
    """REVIEW-005 R005-3 / REVIEW-006 R006-3 fix: a successfully-decoded
    JSON object at `expected_result.json` is never, on its own, a genuine
    registration. REVIEW-005's own fix required the complete schema and
    correlated only `TASK_ID`/`EXPECTED_RESULT_FILE` -- Codex's real
    REVIEW-006 probe then tampered `TARGET_MODEL`, `EXPECTED_PRODUCER`,
    `EXPECTED_TASK_TYPE` and `CURRENT_HEAD` while keeping every key present
    and those two fields correct, and the REVIEW-005 version wrongly
    accepted it. This version correlates every field that has a real,
    independently-derivable ground truth against the task's own current,
    persisted handoff -- `TARGET_MODEL`/`EXPECTED_PRODUCER`/
    `EXPECTED_TASK_TYPE`/`HANDOFF_FILE`/`EXPECTED_RESULT_CONTRACT`/
    `CURRENT_HEAD` must equal exactly what `register_expected_result()`
    itself would derive right now.

    `WAIT_STATE` and `CREATED_AT` are DELIBERATELY NOT compared for exact
    equality against live state (disclosed, not silently narrower):
    `WAIT_STATE` legitimately reflects the workflow's state AT
    REGISTRATION TIME, which by design differs from the CURRENT state by
    the time this function runs during real ingestion (registration
    happens at `WAITING_FOR_HUMAN_TRANSPORT`; this check runs once a
    result has already arrived) -- comparing it to `current_state()` would
    reject every real, legitimate registration. It is instead validated as
    a real, known workflow-state value (a domain check). `CREATED_AT` has
    no independent ground truth to recompute at all; it is validated as a
    non-empty string only. Both are real, if narrower, checks -- never
    silently skipped."""
    if not isinstance(reg, dict):
        return False
    if any(k not in reg for k in _REGISTRATION_SCHEMA_FIELDS):
        return False
    if reg.get("TASK_ID") != task_id:
        return False
    handoff = _wf._load_handoff(root, task_id)
    if handoff is None:
        return False
    try:
        expected_rel = _expected_path(root, task_id).relative_to(root).as_posix()
        handoff_rel = (_task_dir(root, task_id) / "HANDOFF_V1.md").relative_to(root).as_posix()
    except ValueError:
        return False
    if reg.get("EXPECTED_RESULT_FILE") != expected_rel:
        return False
    if reg.get("TARGET_MODEL") != handoff.target_model:
        return False
    if reg.get("EXPECTED_PRODUCER") != handoff.target_model:
        return False
    if reg.get("EXPECTED_TASK_TYPE") != handoff.task_type:
        return False
    if reg.get("HANDOFF_FILE") != handoff_rel:
        return False
    if reg.get("EXPECTED_RESULT_CONTRACT") != handoff.expected_output_schema:
        return False
    if reg.get("CURRENT_HEAD") != handoff.current_head:
        return False
    if reg.get("WAIT_STATE") not in _KNOWN_WORKFLOW_STATES:
        return False
    return isinstance(reg.get("CREATED_AT"), str) and bool(reg.get("CREATED_AT"))


def register_expected_result(root: Path, task_id: str) -> Dict[str, Any]:
    """Persist the expected-result registration for a task that reached
    HUMAN_TRANSPORT_REQUIRED. Idempotent. Only a registered path is ever
    watched. A second pending task claiming the same expected path is a
    real conflict, never silently shared.

    A malformed, empty, or mismatched EXISTING record at this task's
    registration path (REVIEW-005 R005-3) is never trusted/returned as-is
    -- it is treated exactly like "no registration yet" and replaced with a
    fresh, genuine one derived from the task's own real handoff."""
    root = Path(root)
    handoff = _wf._load_handoff(root, task_id)
    if handoff is None:
        raise IngestionError("NO_HANDOFF_TO_REGISTER", {"task_id": task_id})
    expected = _expected_path(root, task_id)
    rel = expected.relative_to(root).as_posix()
    for other in _registered_task_ids(root):
        if other != task_id and (_read_json(_task_dir(root, other) / "expected_result.json") or {}).get(
                "EXPECTED_RESULT_FILE") == rel and (_wf.current_state(root, other) in PENDING_WORKFLOW_STATES):
            raise IngestionError("EXPECTED_RESULT_FILE_CONFLICT", {"task_id": task_id, "other": other})
    existing = _read_json(_task_dir(root, task_id) / "expected_result.json")
    if existing is not None and _valid_registration(existing, root, task_id):
        return existing
    reg = {
        "TASK_ID": task_id,
        "TARGET_MODEL": handoff.target_model,
        "HANDOFF_FILE": (_task_dir(root, task_id) / "HANDOFF_V1.md").relative_to(root).as_posix(),
        "EXPECTED_RESULT_FILE": rel,
        "EXPECTED_RESULT_CONTRACT": handoff.expected_output_schema,
        "EXPECTED_PRODUCER": handoff.target_model,
        "EXPECTED_TASK_TYPE": handoff.task_type,
        "CURRENT_HEAD": handoff.current_head,
        "WAIT_STATE": _wf.current_state(root, task_id),
        "CREATED_AT": _now_iso(),
    }
    _atomic_write_json(_task_dir(root, task_id) / "expected_result.json", reg)
    _emit(root, task_id, "EXPECTED_RESULT_REGISTERED", expected_result_file=rel)
    return reg


def _registered_task_ids(root: Path) -> List[str]:
    base = Path(root) / _wf._HANDOFF_DIR
    if not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir() if d.is_dir() and (d / "expected_result.json").is_file())


def list_pending(root: Path) -> List[str]:
    """Registered tasks whose result may still arrive. Never a directory
    scan for Markdown: only `expected_result.json` registrations count."""
    return [t for t in _registered_task_ids(root) if _wf.current_state(root, t) in PENDING_WORKFLOW_STATES]


def _register_unregistered_waiting_tasks(root: Path) -> List[str]:
    """Startup/resume: a persisted WAITING_FOR_HUMAN_TRANSPORT task with no
    registration (e.g. exported before this capability existed) is
    registered from its own persisted handoff -- wait states drive it."""
    base = Path(root) / _wf._HANDOFF_DIR
    added: List[str] = []
    if not base.is_dir():
        return added
    for d in sorted(base.iterdir()):
        if d.is_dir() and not (d / "expected_result.json").is_file() and _SAFE_TASK_ID.match(d.name) \
                and _wf.current_state(root, d.name) == _wf.STATE_WAITING_FOR_HUMAN_TRANSPORT:
            try:
                register_expected_result(root, d.name)
                added.append(d.name)
            except (IngestionError, _wf.HandoffParseError, OSError):
                continue
    return added


# --- the shared ingestion path ------------------------------------------------

@dataclass
class IngestionResult:
    task_id: str
    action: str  # IMPORTED | DUPLICATE_SUPPRESSED | QUARANTINE_SUPPRESSED | LATE_CHANGE_QUARANTINED | TRANSIENT_ERROR | TERMINATED
    sha256: Optional[str] = None
    outcome: Optional[_wf.ImportOutcome] = None
    detail: str = ""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _own_attempt_id(task_id: str, sha: str) -> str:
    return f"{task_id}:{sha[:12]}:{uuid.uuid4().hex[:8]}"


def _log_suppression_once(root: Path, task_id: str, st: Dict[str, Any], sha: str, reason: str) -> None:
    key = f"{sha}:{reason}"
    if key not in st["suppression_logged"]:
        st["suppression_logged"].append(key)
        _emit(root, task_id, "DUPLICATE_SUPPRESSED", result_sha256=sha, reason=reason)


def ingest_result_file(root: Path, task_id: str, path: Path, *, trigger: str = "AUTO",
                       authorized_replay: bool = False, allow_unregistered_path: bool = False,
                       policy: Optional[IngestionPolicy] = None, _locked: bool = False) -> IngestionResult:
    """The ONE ingestion entry point for automatic and manual imports.
    Identity, duplicate suppression and quarantine wrap the Canonical
    `import_result()`; nothing here parses, validates or consumes.

    `trigger="MANUAL"` (or `authorized_replay=True`) is authorized recovery:
    it may re-import a quarantined hash. An already-CONSUMED hash is always
    suppressed -- consumption is at-most-once per (task, sha256).

    `allow_unregistered_path` (REVIEW-004 R004-1, default False): by
    default `path` MUST resolve to the task's own real, registered
    `_expected_path()` (a genuine `expected_result.json` must exist, and
    `path` must actually name it) -- a caller-supplied path is untrusted
    input, never accepted merely because it names the right `task_id`. A
    caller that genuinely needs to ingest from elsewhere (e.g. a documented
    disaster-recovery procedure) must pass this explicitly True -- a real,
    separate, auditable override, never the default."""
    root = Path(root)
    policy = policy or load_policy(root)
    if _locked:  # the watcher already holds the task's ingestion lock
        return _ingest_locked(root, task_id, Path(path), trigger, authorized_replay, policy, allow_unregistered_path)
    with _task_lock(root, task_id, policy) as got:  # manual front door / direct callers: same single writer
        if not got:
            return IngestionResult(task_id, "LOCKED", detail="INGESTION_IN_PROGRESS")
        return _ingest_locked(root, task_id, Path(path), trigger, authorized_replay, policy, allow_unregistered_path)


def _sealed_manifest_path(path: Path) -> Path:
    """Sidecar path for an OPTIONAL sealed-manifest completion signal
    (REVIEW-005 R005-2's own recommended fix: "an explicit sealed/manifest
    marker binding size and SHA-256"). A producer that writes this file
    ATOMICALLY, LAST -- only after its real result content is completely
    and finally written -- gives ingestion a positive completion proof that
    replaces quiet-interval INFERENCE with quiet-interval-free VERIFICATION,
    closing the slow-writer race Codex's own probe demonstrated for any
    producer that adopts it. Optional and fully backward compatible: a
    producer that never writes this sidecar gets the pre-existing
    quiet-interval behavior, unchanged (still narrower than required, as
    disclosed and regression-tested)."""
    return path.with_name(path.name + ".manifest.json")


def _read_sealed_manifest(path: Path) -> Optional[Dict[str, Any]]:
    manifest = _read_json(_sealed_manifest_path(path))
    if not isinstance(manifest, dict):
        return None
    if not isinstance(manifest.get("sha256"), str) or not isinstance(manifest.get("size"), int):
        return None
    return manifest


def _sealed_manifest_confirms_completion(path: Path) -> Optional[bytes]:
    """Returns the manifest-VERIFIED bytes on success, `None` otherwise --
    never a bare Boolean (REVIEW-006 R006-2 fix). The prior Boolean-only
    contract let `_ingest_locked()` independently re-read `path` afterward
    for the real import: a real, reproduced race let an external writer
    replace the file's content AFTER this check returned True but BEFORE
    that later read, so the bytes actually consumed were never the ones the
    manifest verified. The caller MUST import exactly the bytes returned
    here, never re-read the path."""
    manifest = _read_sealed_manifest(path)
    if manifest is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) == manifest["size"] and _sha256_bytes(data) == manifest["sha256"]:
        return data
    return None


def _synchronous_stability_check(path: Path, policy: IngestionPolicy) -> Optional[bytes]:
    """A real, bounded, synchronous two-snapshot stability check for a
    caller-supplied path that did NOT come through the watcher's own
    multi-observation `_observe()` pre-check (REVIEW-004 R004-1) -- used
    only for non-`AUTO` (manual/recovery) ingestion. The `AUTO` watcher path
    is already stability-verified by `poll_once()`/`_observe()` before this
    function is ever reached, so re-checking there would only double real
    latency for no safety benefit.

    Returns the STABLE bytes (the second, confirming read) on success,
    `None` on failure -- never a bare Boolean (REVIEW-006 R006-2 fix, same
    class of defect as the sealed-manifest check above): the caller must
    import exactly these bytes, never re-read the path afterward, or a
    writer that changes the file between this check and a later
    independent read can swap in content that was never actually
    confirmed stable."""
    try:
        s1 = path.stat()
        b1 = path.read_bytes()
    except OSError:
        return None
    if policy.quiet_seconds > 0:
        time.sleep(policy.quiet_seconds)
    try:
        s2 = path.stat()
        b2 = path.read_bytes()
    except OSError:
        return None
    if (s1.st_size, s1.st_mtime_ns, b1) != (s2.st_size, s2.st_mtime_ns, b2):
        return None
    return b2


def _ingest_locked(root: Path, task_id: str, path: Path, trigger: str, authorized_replay: bool,
                   policy: IngestionPolicy, allow_unregistered_path: bool = False) -> IngestionResult:
    path = Path(path)
    # REVIEW-006 R006-2 fix: `verified_bytes`, when the gate below already
    # confirmed a specific buffer stable/manifest-matched, is what gets
    # imported -- never a fresh, independent re-read of `path` (that
    # re-read is exactly what let a writer swap in un-verified content
    # between the check and the import in the pre-fix code).
    verified_bytes: Optional[bytes] = None
    if not allow_unregistered_path:
        reason, verified_bytes = _unsafe_manual_path_reason(root, task_id, path, trigger, policy)
        if reason is not None:
            _emit(root, task_id, "RESULT_UNSAFE_PATH", path=str(path), reason=reason)
            return IngestionResult(task_id, "UNREGISTERED_PATH_REFUSED", detail=reason)
    st = _load_ing(root, task_id)
    if verified_bytes is not None:
        data = verified_bytes
    else:
        try:
            data = path.read_bytes()
        except OSError as exc:
            _emit(root, task_id, "WATCH_TRANSIENT_ERROR", error=type(exc).__name__, path=str(path))
            return IngestionResult(task_id, "TRANSIENT_ERROR", detail=type(exc).__name__)
    sha = _sha256_bytes(data)
    st["last_detected_result_sha256"] = sha
    _emit(root, task_id, "RESULT_HASHED", result_sha256=sha, trigger=trigger, result_path=str(path))
    entry = st["results"].get(sha)
    wf_state = _wf.current_state(root, task_id)

    # --- duplicate / quarantine suppression --------------------------------
    if entry and entry["import_state"] == H_CONSUMED:
        _log_suppression_once(root, task_id, st, sha, "SAME_HASH_ALREADY_CONSUMED")
        _save_ing(root, task_id, st)
        return IngestionResult(task_id, "DUPLICATE_SUPPRESSED", sha)
    if wf_state == _wf.STATE_RESULT_CONSUMED:
        consumed = [s for s, e in st["results"].items() if e["import_state"] == H_CONSUMED]
        if not consumed:  # consumed through a path that predates ingestion records: reconcile
            # REVIEW-004 R004-4: never label the CURRENTLY SUPPLIED bytes as
            # CONSUMED on faith -- compare against the real, already-persisted
            # consumed digest (workflow state, else the registry row) when
            # one is available. A caller with no persisted digest to compare
            # against (pre-digest-era state) is reconciled as before, honestly
            # disclosed as such.
            real_digest = _real_consumed_digest(root, task_id)
            if real_digest is not None and real_digest != sha:
                st["results"][sha] = {"import_state": H_QUARANTINED, "result_path": str(path),
                                      "rejection_reason": "RECONCILIATION_DIGEST_MISMATCH",
                                      "retry_eligibility": RETRY_ON_CHANGE, "quarantined_at": _now_iso()}
                _emit(root, task_id, "RESULT_CHANGED_AFTER_CONSUMPTION", result_sha256=sha,
                      real_consumed_digest=real_digest)
                _emit(root, task_id, "RESULT_QUARANTINED", result_sha256=sha, reason="RECONCILIATION_DIGEST_MISMATCH")
                _save_ing(root, task_id, st)
                return IngestionResult(task_id, "LATE_CHANGE_QUARANTINED", sha)
            st["results"][sha] = {"import_state": H_CONSUMED, "result_path": str(path), "imported_at": None,
                                  "consumed_at": None,
                                  "note": ("RECONCILED_FROM_WORKFLOW_STATE" if real_digest is None
                                          else "RECONCILED_DIGEST_VERIFIED")}
            _log_suppression_once(root, task_id, st, sha, "TASK_ALREADY_CONSUMED_RECONCILED")
            _save_ing(root, task_id, st)
            return IngestionResult(task_id, "DUPLICATE_SUPPRESSED", sha, detail="RECONCILED")
        st["results"][sha] = {"import_state": H_QUARANTINED, "result_path": str(path),
                              "rejection_reason": "RESULT_CHANGED_AFTER_CONSUMPTION",
                              "retry_eligibility": RETRY_ON_CHANGE, "quarantined_at": _now_iso()}
        _emit(root, task_id, "RESULT_CHANGED_AFTER_CONSUMPTION", result_sha256=sha)
        _emit(root, task_id, "RESULT_QUARANTINED", result_sha256=sha, reason="RESULT_CHANGED_AFTER_CONSUMPTION")
        _save_ing(root, task_id, st)
        return IngestionResult(task_id, "LATE_CHANGE_QUARANTINED", sha)
    if entry and entry["import_state"] == H_QUARANTINED:
        replay = entry.get("retry_eligibility") == RETRY_REPLAY_SCHEDULED
        if not (replay or authorized_replay or trigger == "MANUAL"):
            _log_suppression_once(root, task_id, st, sha, "QUARANTINED_HASH_NOT_RETRIED")
            st["auto_import_status"] = "QUARANTINED"
            _save_ing(root, task_id, st)
            return IngestionResult(task_id, "QUARANTINE_SUPPRESSED", sha)

    # --- bounded automatic attempts (interrupted / failing imports) ----------
    attempts = st["import_attempts"].get(sha, 0)
    if trigger == "AUTO" and attempts >= policy.max_import_attempts:
        _emit(root, task_id, "INGESTION_TERMINATED", result_sha256=sha, attempts=attempts)
        st["auto_import_status"] = "TERMINATED"
        _save_ing(root, task_id, st)
        _ec.persist_stop(root, task_id, _ec.can_i_stop(_ec.WorkflowSignals(
            termination_policy_triggered=True,
            stop_evidence=f"automatic import of sha256 {sha[:12]} failed {attempts} times (max {policy.max_import_attempts}); never treated as PASS",
            next_required_action="diagnose the import failure; then schedule_replay() or authorized recovery",
            resume_action="SCHEDULE_REPLAY")))
        return IngestionResult(task_id, "TERMINATED", sha)
    st["import_attempts"][sha] = attempts + 1
    attempt_id = _own_attempt_id(task_id, sha)
    st["results"][sha] = {"import_state": H_IMPORT_STARTED, "result_path": str(path), "import_attempt_id": attempt_id,
                          "imported_at": _now_iso(), "consumed_at": None}
    st["auto_import_status"] = "IMPORTING"
    _save_ing(root, task_id, st)
    _emit(root, task_id, "AUTO_IMPORT_STARTED", result_sha256=sha, import_attempt_id=attempt_id, trigger=trigger)

    # --- the Canonical import path (unchanged manual authority) --------------
    # REVIEW-006 R006-2 fix: pass the ALREADY-VERIFIED buffer (`data`, which
    # is `verified_bytes` when one exists) through so import_result() never
    # performs its own independent re-read of `path` -- closing the gap
    # between this gate's own check and the Canonical parser's read.
    try:
        outcome = _wf.import_result(root, task_id, path, pre_read_bytes=verified_bytes)
    except OSError as exc:  # registry / state write failure etc.: transient, retried, bounded above
        _emit(root, task_id, "AUTO_IMPORT_FAILED_TRANSIENT", result_sha256=sha, error=type(exc).__name__)
        return IngestionResult(task_id, "TRANSIENT_ERROR", sha, detail=type(exc).__name__)

    st = _load_ing(root, task_id)
    imported_sha = outcome.result_sha256 or sha
    if imported_sha != sha:  # the file changed between our hash and the canonical read
        _emit(root, task_id, "RESULT_CHANGED_DURING_IMPORT", detected_sha256=sha, imported_sha256=imported_sha)
        st["results"][imported_sha] = st["results"].pop(sha)
        sha = imported_sha
    entry = st["results"][sha]
    if outcome.consumed:
        entry.update(import_state=H_CONSUMED, consumed_at=_now_iso(), question_id=outcome.question_id)
        st["auto_import_status"] = "DONE"
        _emit(root, task_id, "RESULT_ACCEPTED", result_sha256=sha)
        _emit(root, task_id, "RESULT_CONSUMED", result_sha256=sha, question_id=outcome.question_id)
    else:
        findings = list(outcome.validation.findings) if outcome.validation is not None else []
        entry.update(import_state=H_QUARANTINED, rejection_reason=outcome.parse_error or ",".join(findings) or "REJECTED",
                     validation_findings=findings, retry_eligibility=RETRY_ON_CHANGE, quarantined_at=_now_iso())
        st["auto_import_status"] = "QUARANTINED"
        _emit(root, task_id, "RESULT_REJECTED", result_sha256=sha, reason=entry["rejection_reason"], findings=findings)
        _emit(root, task_id, "RESULT_QUARANTINED", result_sha256=sha, retry_eligibility=RETRY_ON_CHANGE)
    _save_ing(root, task_id, st)
    resume_after_import(root, task_id)
    return IngestionResult(task_id, "IMPORTED", sha, outcome=outcome)


def schedule_replay(root: Path, task_id: str, result_sha256: str, reason: str) -> None:
    """Explicit, audited authorization to re-import a quarantined hash once
    -- e.g. after Canonical remediation fixed the validator that rejected it.
    The external result file itself is never touched."""
    st = _load_ing(root, task_id)
    entry = st["results"].get(result_sha256)
    if not entry or entry["import_state"] != H_QUARANTINED:
        raise IngestionError("NOT_QUARANTINED", {"task_id": task_id, "sha256": result_sha256})
    entry["retry_eligibility"] = RETRY_REPLAY_SCHEDULED
    entry["replay_reason"] = reason
    st["import_attempts"][result_sha256] = 0
    _save_ing(root, task_id, st)
    _emit(root, task_id, "REPLAY_SCHEDULED", result_sha256=result_sha256, reason=reason)


def resume_after_import(root: Path, task_id: str) -> Dict[str, Any]:
    """AUTO_RESUME: the Canonical import already persisted NEXT_ACTION;
    this records the resume, resolves it, and replaces the stale
    WAITING_FOR_HUMAN_TRANSPORT stop with the real current decision."""
    root = Path(root)
    st = _load_ing(root, task_id)
    _emit(root, task_id, "AUTO_RESUME_STARTED")
    rec = _ec.read_next_action(root, task_id) or {}
    _emit(root, task_id, "NEXT_ACTION_RESOLVED", next_action=rec.get("next_action"),
          auto_actionable=rec.get("auto_actionable"), stop_reason=rec.get("stop_reason"))
    signals = _ec.WorkflowSignals(
        human_authority_required=(rec.get("stop_reason") == "HUMAN_AUTHORITY_REQUIRED"),
        human_transport_required=(rec.get("stop_reason") == "HUMAN_TRANSPORT_REQUIRED"),
        auto_actionable_pending=bool(rec.get("auto_actionable")),
        next_required_action=str(rec.get("next_action") or ""),
        resume_action="AUTO_RESUME",
        stop_evidence=f"external result ingested automatically; next action {rec.get('next_action')}")
    decision = _ec.can_i_stop(signals)
    _ec.persist_stop(root, task_id, decision)
    st["auto_resume_status"] = "DONE"
    _save_ing(root, task_id, st)
    return decision.to_dict()


def _real_consumed_digest(root: Path, task_id: str) -> Optional[str]:
    """The real, already-persisted consumed content digest for `task_id`,
    if one exists (REVIEW-004 R004-4) -- `model_handoff_workflow`'s own
    state first (`result_sha256`/`accepted_result_sha256`), else the
    registry row's `result_sha256` column. `None` when no real digest was
    ever recorded (pre-digest-era state), never a fabricated placeholder."""
    state = _wf._load_state(root, task_id) or {}
    digest = state.get("result_sha256") or state.get("accepted_result_sha256")
    if digest:
        return digest
    row = _wf._registry_row(root, task_id) or {}
    return row.get("result_sha256") or None


def _unsafe_manual_path_reason(root: Path, task_id: str, path: Path, trigger: str,
                               policy: IngestionPolicy) -> Tuple[Optional[str], Optional[bytes]]:
    """The real registration/identity/safety gate `_ingest_locked()` applies
    to a caller-supplied path by default (REVIEW-004 R004-1). Returns
    `(reason, verified_bytes)`: `reason` is a real refusal string when the
    path is untrusted, `None` when it is safe to ingest. Mirrors
    `_observe()`'s own symlink/non-file/resolved-parent/non-empty checks and
    additionally requires the path to actually BE the task's registered
    expected path -- naming the right `task_id` is never sufficient on its
    own.

    `verified_bytes` (REVIEW-006 R006-2 fix) is the EXACT byte buffer a
    non-`AUTO` manifest/stability check already confirmed -- the caller
    MUST import this buffer verbatim, never re-read `path` afterward (the
    prior Boolean-only contract let a writer replace the file between this
    check and the caller's own later independent read, so content the
    check never actually verified could still be imported). `None` for any
    rejection, and for the `AUTO` trigger (whose own stability evidence
    lives in `_observe()`/`poll_once()`, a separate, unaffected mechanism)."""
    reg = _read_json(_task_dir(root, task_id) / "expected_result.json")
    if reg is None:
        return "NO_REGISTRATION", None
    if not _valid_registration(reg, root, task_id):
        return "MALFORMED_REGISTRATION", None
    expected = _expected_path(root, task_id)
    try:
        if path.resolve() != expected.resolve():
            return "PATH_NOT_REGISTERED_EXPECTED_PATH", None
    except OSError:
        return "PATH_NOT_REGISTERED_EXPECTED_PATH", None
    if path.is_symlink() or not path.is_file():
        return "UNSAFE_FILE", None
    try:
        if path.resolve().parent != _task_dir(root, task_id).resolve():
            return "UNSAFE_FILE", None
        if path.stat().st_size == 0:
            return "EMPTY_FILE", None
    except OSError:
        return "UNSAFE_FILE", None
    if trigger == "AUTO":
        return None, None
    verified = _sealed_manifest_confirms_completion(path)
    if verified is None:
        verified = _synchronous_stability_check(path, policy)
    if verified is None:
        return "NOT_STABLE", None
    return None, verified


# --- arrival detection + stability ---------------------------------------------

def _observe(root: Path, task_id: str, path: Path, policy: IngestionPolicy, now: float) -> str:
    """Returns one of: ABSENT, UNSAFE, TRANSIENT, OBSERVING, STABLE. Persists
    stability evidence so it survives a watcher restart."""
    st = _load_ing(root, task_id)
    if not path.exists() and not path.is_symlink():
        if st["observation"]:
            st["observation"] = None
            _save_ing(root, task_id, st)
        return "ABSENT"
    if path.is_symlink() or not path.is_file() or path.resolve().parent != _task_dir(root, task_id).resolve():
        _emit(root, task_id, "RESULT_UNSAFE_PATH", path=str(path))
        return "UNSAFE"
    try:
        stat = path.stat()
        data = path.read_bytes()
    except OSError as exc:  # locked / vanished mid-check
        _emit(root, task_id, "WATCH_TRANSIENT_ERROR", error=type(exc).__name__)
        return "TRANSIENT"
    if not data:
        return "OBSERVING"
    snap = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": _sha256_bytes(data)}
    obs = st["observation"]
    if not obs or {k: obs.get(k) for k in snap} != snap:
        first = obs is None or obs.get("sha256") != snap["sha256"]
        st["observation"] = {**snap, "first_seen_at": now, "observations": 1}
        st["last_detected_result_sha256"] = snap["sha256"]
        st["auto_import_status"] = "OBSERVING"
        _save_ing(root, task_id, st)
        _emit(root, task_id, "RESULT_DETECTED", result_sha256=snap["sha256"], size=snap["size"], first_detection=first)
        return "OBSERVING"
    obs["observations"] += 1
    stable = obs["observations"] >= policy.min_observations and (now - obs["first_seen_at"]) >= policy.quiet_seconds
    _save_ing(root, task_id, st)
    if stable and not obs.get("stability_logged"):
        obs["stability_logged"] = True
        _save_ing(root, task_id, st)
        _emit(root, task_id, "RESULT_STABILITY_CONFIRMED", result_sha256=snap["sha256"],
              observations=obs["observations"], quiet_seconds=policy.quiet_seconds)
    return "STABLE" if stable else "OBSERVING"


def poll_once(root: Path, *, policy: Optional[IngestionPolicy] = None,
              now: Optional[float] = None) -> List[Dict[str, Any]]:
    """One non-blocking pass over registered pending expected results.
    `now` is injectable so stability is testable without sleeping."""
    root = Path(root)
    policy = policy or load_policy(root)
    now = time.time() if now is None else now
    _register_unregistered_waiting_tasks(root)
    report: List[Dict[str, Any]] = []
    for task_id in list_pending(root):
        with _task_lock(root, task_id, policy) as got:
            if not got:
                report.append({"task_id": task_id, "status": "LOCKED"})
                continue
            path = _expected_path(root, task_id)
            status = _observe(root, task_id, path, policy, now)
            row = {"task_id": task_id, "status": status}
            if status == "STABLE":
                res = ingest_result_file(root, task_id, path, trigger="AUTO", policy=policy, _locked=True)
                row.update(action=res.action, sha256=res.sha256,
                           state=res.outcome.state if res.outcome else _wf.current_state(root, task_id))
            report.append(row)
    return report


def startup_scan(root: Path, *, policy: Optional[IngestionPolicy] = None, timeout_seconds: float = 60.0,
                 sleep: Callable[[float], None] = time.sleep) -> List[Dict[str, Any]]:
    """STARTUP/RESUME: load persisted wait states, find expected results
    already present, and run stability/identity/duplicate checks and the
    canonical import until nothing is left mid-observation (or timeout)."""
    policy = policy or load_policy(root)
    deadline = time.time() + timeout_seconds
    last: List[Dict[str, Any]] = []
    while True:
        last = poll_once(root, policy=policy)
        if not any(r["status"] in ("OBSERVING", "TRANSIENT", "LOCKED") for r in last) or time.time() >= deadline:
            return last
        sleep(max(policy.quiet_seconds / max(policy.min_observations, 1), 0.05))


# --- watcher process -----------------------------------------------------------

def _watcher_file(root: Path) -> Path:
    return Path(root) / _wf._HANDOFF_DIR / "result_watcher.json"


def _stop_flag(root: Path) -> Path:
    return Path(root) / _wf._HANDOFF_DIR / "result_watcher.stop"


def watcher_status(root: Path, policy: Optional[IngestionPolicy] = None, now: Optional[float] = None) -> str:
    policy = policy or load_policy(root)
    rec = _read_json(_watcher_file(root))
    if not rec:
        return "RECOVERABLE"
    age = (time.time() if now is None else now) - float(rec.get("last_heartbeat_epoch", 0))
    if rec.get("status") == "STOPPED":
        return "STOPPED"
    return "ACTIVE" if age <= policy.poll_interval_seconds * policy.heartbeat_grace_factor else "RECOVERABLE"


def watch(root: Path, *, policy: Optional[IngestionPolicy] = None, max_iterations: Optional[int] = None,
          sleep: Callable[[float], None] = time.sleep) -> int:
    """The watcher loop: heartbeat + startup scan first, then poll. Exits on
    the stop flag, after `max_iterations`, or when nothing has been pending
    for `idle_exit_seconds` (a later export/startup re-ensures it)."""
    root = Path(root)
    policy = policy or load_policy(root)
    try:
        _stop_flag(root).unlink()
    except OSError:
        pass
    started = time.time()
    idle_since = None
    for t in list_pending(root):
        _emit(root, t, "WATCH_STARTED", pid=os.getpid())
    i = 0
    while max_iterations is None or i < max_iterations:
        i += 1
        _atomic_write_json(_watcher_file(root), {
            "pid": os.getpid(), "started_at_epoch": started, "last_heartbeat_epoch": time.time(),
            "poll_interval_seconds": policy.poll_interval_seconds, "iterations": i, "status": "ACTIVE"})
        if _stop_flag(root).exists():
            break
        try:
            poll_once(root, policy=policy)
        except Exception as exc:  # the loop must survive anything a single poll hits
            print(f"[result_watcher] poll error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        if list_pending(root):
            idle_since = None
        else:
            idle_since = idle_since or time.time()
            if time.time() - idle_since >= policy.idle_exit_seconds:
                break
        sleep(policy.poll_interval_seconds)
    _atomic_write_json(_watcher_file(root), {
        "pid": os.getpid(), "started_at_epoch": started, "last_heartbeat_epoch": time.time(),
        "poll_interval_seconds": policy.poll_interval_seconds, "iterations": i, "status": "STOPPED"})
    return 0


def ensure_watcher(root: Path, *, policy: Optional[IngestionPolicy] = None, wait_seconds: float = 10.0) -> str:
    """Start the detached watcher if its heartbeat is not fresh. Honors
    `L5DGVA_RESULT_WATCHER=off` (used by the test-suite so tests never leave
    background processes). Returns ACTIVE / RECOVERABLE."""
    root = Path(root)
    policy = policy or load_policy(root)
    if os.environ.get("L5DGVA_RESULT_WATCHER", "").lower() == "off":
        return "RECOVERABLE"
    if watcher_status(root, policy) == "ACTIVE":
        return "ACTIVE"
    log = open(Path(root) / _wf._HANDOFF_DIR / "result_watcher.log", "a", encoding="utf-8")
    kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "dv_harness.result_ingestion", "watch", "--root", str(root)],
                     cwd=str(root), stdin=subprocess.DEVNULL, stdout=log, stderr=log, **kwargs)
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if watcher_status(root, policy) == "ACTIVE":
            return "ACTIVE"
        time.sleep(0.25)
    return "RECOVERABLE"


def stop_watcher(root: Path) -> None:
    """Cooperative stop (flag file); never kills a process."""
    _stop_flag(root).parent.mkdir(parents=True, exist_ok=True)
    _stop_flag(root).write_text("stop", encoding="utf-8")


# --- observability / reports -----------------------------------------------------

def status_report(root: Path) -> Dict[str, Any]:
    """Never exposes 'waiting for user to import'."""
    root = Path(root)
    policy = load_policy(root)
    tasks: Dict[str, Any] = {}
    for t in _registered_task_ids(root):
        st = _load_ing(root, t)
        reg = _read_json(_task_dir(root, t) / "expected_result.json") or {}
        na = _ec.read_next_action(root, t) or {}
        stop = _ec.read_persisted_stop(root, t) or {}
        quarantined = [s[:12] for s, e in st["results"].items() if e["import_state"] == H_QUARANTINED]
        tasks[t] = {
            "WORKFLOW_STATE": _wf.current_state(root, t),
            "EXPECTED_RESULT_FILE": reg.get("EXPECTED_RESULT_FILE"),
            "LAST_DETECTED_RESULT_SHA256": st["last_detected_result_sha256"],
            "AUTO_IMPORT_STATUS": st["auto_import_status"],
            "QUARANTINE_STATUS": "QUARANTINED:" + ",".join(quarantined) if quarantined else "NONE",
            "AUTO_RESUME_STATUS": st["auto_resume_status"],
            "NEXT_ACTION": na.get("next_action"),
            "HUMAN_ACTION_REQUIRED": stop.get("HUMAN_ACTION_REQUIRED", "NO"),
        }
    return {
        "RESULT_WATCHER_STATUS": watcher_status(root, policy),
        "PENDING_EXTERNAL_RESULTS": list_pending(root),
        "TASKS": tasks,
    }


def transport_stop_report(root: Path, task_id: str) -> Dict[str, str]:
    """The Human Transport stop as required by the Automatic External
    Result Ingestion contract. The human only transports the artifact --
    no import command is part of the report."""
    root = Path(root)
    reg = register_expected_result(root, task_id)
    return _ec.human_transport_report(
        task_id, reg["TARGET_MODEL"], reg["HANDOFF_FILE"], reg["EXPECTED_RESULT_FILE"],
        result_watcher="ACTIVE_OR_RECOVERABLE")


# --- CLI (debug / recovery front door; the normal flow needs none of these) -------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="result_ingestion")
    sub = ap.add_subparsers(dest="verb", required=True)
    for name in ("register", "scan", "poll", "watch", "status", "ensure-watcher", "stop-watcher", "replay"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".")
        if name in ("register", "replay"):
            p.add_argument("--task-id", required=True)
        if name == "replay":
            p.add_argument("--sha256", required=True)
            p.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.verb == "register":
        print(json.dumps(register_expected_result(root, a.task_id), indent=2))
    elif a.verb == "scan":
        print(json.dumps(startup_scan(root), indent=2))
    elif a.verb == "poll":
        print(json.dumps(poll_once(root), indent=2))
    elif a.verb == "watch":
        return watch(root)
    elif a.verb == "status":
        print(json.dumps(status_report(root), indent=2))
    elif a.verb == "ensure-watcher":
        print(ensure_watcher(root))
    elif a.verb == "stop-watcher":
        stop_watcher(root)
    elif a.verb == "replay":
        schedule_replay(root, a.task_id, a.sha256, a.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
