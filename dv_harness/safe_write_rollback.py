r"""dv_harness/safe_write_rollback.py -- Safe Write / Rollback Contract
(ULTIMATE_PRODUCTION_COMPLETE.md section 154).

REUSE CHECK FIRST, per this item's own instruction. A repo-wide grep for
`rollback` before writing a line of code found three real, but narrower,
precedents, none of which cover a generalized "any write the harness makes"
contract:

  1. `capability_evolution.shadow_rollback_manifest()` -- derives an undo set
     for one shadow-experiment run FROM the experiment's own surviving
     untouched baseline-arm workspace. It is real and it is the direct model
     for this module (same `restore_content`/`delete` vocabulary, same
     "producing the manifest is the mechanism, applying stays a separate,
     attributed act" split), but it only works because a controlled
     experiment happens to leave a whole second copy of the tree lying
     around. A generated file or a config-file edit made in the ordinary
     course of harness work has no such baseline arm to diff against -- this
     module has to capture the pre-write state ITSELF, at write time, or
     there is nothing to roll back to.
  2. `schema_config_governance.classify_change_full()` reports schema
     "rollback" AVAILABLE/NOT_AVAILABLE by checking whether the OLD blob is
     retrievable from git history (`schema_compat.read_blob_at_rev()`). Real,
     but read-only, git-only, and schema-file-only -- it never captures a
     pre-write snapshot itself and has no apply path at all (git history is
     not always present -- a freshly generated file that was never
     committed has no blob to recover, which is exactly the case this
     module has to cover).
  3. `tools/verification_flow/promotion_rollback_gate.py` /
     `rollback_consistency_gate.py` check a *promotion-state* rollback flag
     for self-consistency (`rollback_applied` vs. `promotion_state`). They
     never touch a filesystem path at all -- a different axis (governance
     STATE rollback, not file-CONTENT rollback).

None of the three lets a caller say "I am about to write this exact file (or
this set of files, as one config change); capture what was there before, do
the write, and hand me back a checkable, attributable record I can later use
to prove it is safe to undo, or actually undo it." That is the genuine gap
this module closes, and it is additive to all three -- nothing above is
reimplemented, and `capability_evolution.py`'s two-arm shadow machinery is
untouched.

WHAT THIS IS. `safe_write()` is a drop-in replacement for "open a path and
write bytes to it" for any real production write this harness performs (a
generated UVM file, a rendered report, a config edit) -- it snapshots the
pre-write state (existed + a real backup copy of the original bytes, or
"did not exist" if there was none) BEFORE writing, then performs the write
atomically (`storage._atomic_replace()`, the same primitive
`waiver_store.py`/`golden_scenario.py`/`safety_sandbox.py` already share --
no second atomic-write helper), then persists an attributed manifest record
under `.dv-harness/safe_write/`. `plan_rollback()` is the READ-ONLY, checkable
half: given a `write_id`, is a safe undo actually possible right now, or has
something changed since (the live file drifted, the backup was tampered
with, the manifest itself was edited) that makes a blind restore unsafe.
`apply_rollback()` is the one function that mutates the target path again --
it refuses (raises) unless `plan_rollback()` itself reports AVAILABLE, so the
same check that lets a human decide also gates the code path that acts.

EVIDENCE TRUTH RULE. There is no "assume it is safe" branch anywhere in
`plan_rollback()`. Every non-AVAILABLE outcome names exactly what evidence is
missing or wrong (`NOT_FOUND`, `MANIFEST_TAMPERED`, `BACKUP_CORRUPTED`,
`DRIFT_DETECTED`, `ALREADY_ROLLED_BACK`) rather than defaulting to "probably
fine". `apply_rollback()` / `apply_rollback_batch()` re-derive that status at
call time from real digests re-read off disk -- never from a cached field --
so a manifest cannot be forged into looking rollback-safe by editing it.

WORST-WINS COMPOSITE GATE. A "config change" is usually more than one file.
`safe_write_batch()` groups N `safe_write()` calls under one `batch_id`.
`plan_rollback_batch()` folds all N per-file plans to the single WORST status
found (severity order below), and adds one batch-only status,
`PARTIALLY_ROLLED_BACK`, for the case a per-file view cannot see: some files
in the batch already restored, others not -- a real inconsistency, not an
average of two fine outcomes. `apply_rollback_batch()` refuses the WHOLE
batch unless the plan is cleanly AVAILABLE for every file in it -- there is
no partial-apply path, so a three-file config edit reverts atomically or not
at all, never leaving two files reverted and one not.

NEVER A GOLDEN-REFERENCE MINE. This module reads and writes only what THIS
harness itself produced (its own prior write's backup and manifest); it has
no code path that reads from `USB_UVM_Handoff`, `uvm_syoscb-1.0.2.4`, or
`ATB`, and could not "mine" protocol-behavior content even by accident --
the only content it ever moves is bytes this harness itself wrote a moment
earlier.

DISCLOSED RESIDUAL, matching this project's own "Deliberately bounded"
convention. (1) No CLI verb is wired into `cli.py`, and no gate call site
exists in `gates.py` -- both files are large and under concurrent edit
pressure from many items in this batch, so this module ships its own
`python -m dv_harness.safe_write_rollback` front door instead, exactly the
choice `safety_sandbox.py` and `schema_config_governance.py` already made.
(2) `apply_rollback()` restores file CONTENT only; it does not restore file
mode/permission bits or restore a symlink-vs-regular-file distinction --
POSIX metadata beyond bytes-on-disk is out of scope for this pass. (3) There
is no automatic trigger anywhere in the engine that calls `safe_write()`
instead of a plain `open(...).write()` -- REACHED, not WIRED, like several
recent modules in this codebase; wiring every existing write call site
through this contract is a separate, larger effort this pass does not
attempt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .storage import _atomic_replace

# --- status vocabulary, deliberately not models.Status -----------------------
STATUS_AVAILABLE = "AVAILABLE"
STATUS_ALREADY_ROLLED_BACK = "ALREADY_ROLLED_BACK"
STATUS_DRIFT_DETECTED = "DRIFT_DETECTED"
STATUS_BACKUP_CORRUPTED = "BACKUP_CORRUPTED"
STATUS_MANIFEST_TAMPERED = "MANIFEST_TAMPERED"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_PARTIALLY_ROLLED_BACK = "PARTIALLY_ROLLED_BACK"  # batch-only rollup value

# Most severe first -- plan_rollback_batch() folds a batch to the WORST entry
# found here, never an average. "Can't even tell" (NOT_FOUND / tampered
# metadata) outranks "evidence says it's actively unsafe" (corrupted backup /
# live drift), which outranks "batch is in an inconsistent half-done state"
# (PARTIALLY_ROLLED_BACK), which outranks "already fully done"
# (ALREADY_ROLLED_BACK), which outranks the only clean state, AVAILABLE.
_SEVERITY_ORDER = (
    STATUS_NOT_FOUND,
    STATUS_MANIFEST_TAMPERED,
    STATUS_BACKUP_CORRUPTED,
    STATUS_DRIFT_DETECTED,
    STATUS_PARTIALLY_ROLLED_BACK,
    STATUS_ALREADY_ROLLED_BACK,
    STATUS_AVAILABLE,
)


def _severity_rank(status: str) -> int:
    try:
        return _SEVERITY_ORDER.index(status)
    except ValueError:
        return -1  # an unrecognized status is treated as worse than everything real


def _assert_vocabulary_disjoint_from_models_status() -> None:
    """Run once at import, the same self-check `safety_sandbox.py` runs: this
    module's status vocabulary must share no token with
    `dv_harness.models.Status`, so a rollback-plan status can never be
    mistaken for a stage-gate verdict."""
    from .models import Status

    verdict_tokens = {m.value for m in Status}
    ours = {
        STATUS_AVAILABLE, STATUS_ALREADY_ROLLED_BACK, STATUS_DRIFT_DETECTED,
        STATUS_BACKUP_CORRUPTED, STATUS_MANIFEST_TAMPERED, STATUS_NOT_FOUND,
        STATUS_PARTIALLY_ROLLED_BACK,
    }
    collision = ours & verdict_tokens
    if collision:
        raise AssertionError(
            f"safe_write_rollback status vocabulary collides with models.Status: {collision}"
        )


_assert_vocabulary_disjoint_from_models_status()


class SafeWriteError(ValueError):
    """A malformed safe_write()/batch call -- a caller-usage defect, distinct
    from a real rollback-plan finding."""


class RollbackRefusedError(PermissionError):
    """apply_rollback()/apply_rollback_batch() refuse to mutate a path unless
    the corresponding plan is cleanly AVAILABLE. Raised (never silently
    no-op'd) so a caller that forgets to check the plan first still cannot
    apply an unsafe rollback."""

    def __init__(self, write_id: str, plan: Dict[str, Any]):
        self.write_id = write_id
        self.plan = plan
        super().__init__(
            f"REFUSED: rollback for write_id={write_id!r} is not AVAILABLE "
            f"(status={plan.get('status')}). {plan.get('detail', '')}"
        )


# --- path / digest helpers ----------------------------------------------------


def _within(child: Path, parent: Path) -> bool:
    """Re-derives the same resolve-and-check discipline `safety_sandbox.py`
    and `capability_evolution.py` each already established for their own,
    different, destinations -- deliberately not imported from either (both
    name it as a private, module-local helper), so this module's containment
    of the LIVE project tree stays independent of either module's internal
    layout."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _coerce_bytes(content: Union[bytes, str]) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    raise SafeWriteError(f"safe_write() content must be bytes or str, got {type(content)!r}")


def _resolve_target(root: Path, rel_path: str) -> Path:
    rel = str(rel_path)
    if not rel or os.path.isabs(rel) or rel in (".", ".."):
        raise SafeWriteError(f"invalid path {rel_path!r}: must be a real project-relative path")
    target = (root / rel).resolve()
    if not _within(target, root):
        raise SafeWriteError(
            f"REFUSED: path {rel_path!r} resolves outside project root {root} "
            f"(target={target})"
        )
    return target


def _write_json_atomic(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        _atomic_replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _new_id(prefix: str, *salt: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    h = hashlib.sha256(("|".join(salt) + "|" + stamp).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{stamp}-{h}"


# --- on-disk layout -----------------------------------------------------------


def _sw_root(root) -> Path:
    return Path(root) / ".dv-harness" / "safe_write"


def _manifest_path(root, write_id: str) -> Path:
    if not write_id or "/" in write_id or "\\" in write_id or write_id in (".", ".."):
        raise SafeWriteError(f"invalid write_id {write_id!r}: must be a bare filename component")
    return _sw_root(root) / "manifests" / f"{write_id}.json"


def _backup_path(root, write_id: str) -> Path:
    return _sw_root(root) / "backups" / f"{write_id}.orig"


def _batch_path(root, batch_id: str) -> Path:
    if not batch_id or "/" in batch_id or "\\" in batch_id or batch_id in (".", ".."):
        raise SafeWriteError(f"invalid batch_id {batch_id!r}: must be a bare filename component")
    return _sw_root(root) / "batches" / f"{batch_id}.json"


# --- manifest tamper-evidence --------------------------------------------------

_PINNED_FIELDS = ("write_id", "path", "pre_existed", "pre_digest", "post_digest")


def _manifest_digest(record: Dict[str, Any]) -> str:
    payload = json.dumps({k: record.get(k) for k in _PINNED_FIELDS},
                          sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# --- safe_write() --------------------------------------------------------------


def safe_write(root, rel_path: str, content: Union[bytes, str], *, actor: str, reason: str,
               write_id: Optional[str] = None, batch_id: Optional[str] = None) -> Dict[str, Any]:
    """Perform ONE tracked write and return its manifest record.

    Snapshots pre-write state first (a real backup copy of the prior bytes if
    the path existed, `pre_existed=False` and no backup if it did not), THEN
    performs the write atomically, THEN persists the manifest. If the target
    already exists and a caller-supplied `write_id` collides with an existing
    manifest, this refuses rather than silently overwriting someone else's
    rollback record.
    """
    if not actor or not str(actor).strip():
        raise SafeWriteError("safe_write() requires a real actor identity")
    if not reason or not str(reason).strip():
        raise SafeWriteError("safe_write() requires a real, non-empty reason")

    root = Path(root).resolve()
    target = _resolve_target(root, rel_path)
    data = _coerce_bytes(content)

    wid = write_id or _new_id("SW", str(rel_path), actor)
    manifest_path = _manifest_path(root, wid)
    if manifest_path.exists():
        raise SafeWriteError(f"write_id {wid!r} already has a manifest on disk -- use a new id")

    pre_existed = target.is_file()
    pre_digest = None
    pre_backup_path = None
    if pre_existed:
        original = target.read_bytes()
        pre_digest = _digest_bytes(original)
        backup = _backup_path(root, wid)
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(original)
        pre_backup_path = str(backup.relative_to(root)).replace(os.sep, "/")

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=target.stem + ".", suffix=target.suffix or ".tmp",
                               dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        _atomic_replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass

    record: Dict[str, Any] = {
        "write_id": wid,
        "batch_id": batch_id,
        "path": str(target.relative_to(root)).replace(os.sep, "/"),
        "actor": str(actor),
        "reason": str(reason),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pre_existed": pre_existed,
        "pre_digest": pre_digest,
        "pre_backup_path": pre_backup_path,
        "post_digest": _digest_bytes(data),
        "post_size": len(data),
        "rollback_applied": False,
        "rollback_at": None,
        "rollback_actor": None,
        "rollback_reason": None,
    }
    record["manifest_digest"] = _manifest_digest(record)
    _write_json_atomic(manifest_path, record)
    return record


def read_manifest(root, write_id: str) -> Optional[Dict[str, Any]]:
    root = Path(root).resolve()
    return _read_json(_manifest_path(root, write_id))


def list_writes(root) -> List[str]:
    d = _sw_root(root) / "manifests"
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


# --- plan_rollback() (read-only) ----------------------------------------------


def plan_rollback(root, write_id: str) -> Dict[str, Any]:
    """READ-ONLY. Reports whether `write_id`'s write can be safely undone
    RIGHT NOW. Never mutates the target path, the backup, or the manifest.
    """
    root = Path(root).resolve()
    record = read_manifest(root, write_id)
    if record is None:
        return {"write_id": write_id, "status": STATUS_NOT_FOUND,
                "detail": "no manifest on disk for this write_id"}

    if _manifest_digest(record) != record.get("manifest_digest"):
        return {"write_id": write_id, "status": STATUS_MANIFEST_TAMPERED,
                "detail": "manifest's pinned fields no longer match its own stored digest"}

    if record.get("rollback_applied"):
        return {"write_id": write_id, "status": STATUS_ALREADY_ROLLED_BACK,
                "detail": f"already rolled back at {record.get('rollback_at')}",
                "path": record["path"]}

    target = Path(root) / record["path"]
    live_digest = _digest_bytes(target.read_bytes()) if target.is_file() else None
    if live_digest != record.get("post_digest"):
        return {"write_id": write_id, "status": STATUS_DRIFT_DETECTED,
                "detail": ("live file no longer matches what safe_write() produced -- "
                           "something else changed it since; refusing a blind restore"),
                "path": record["path"], "expected_digest": record.get("post_digest"),
                "live_digest": live_digest}

    if record.get("pre_existed"):
        backup = Path(root) / record["pre_backup_path"]
        if not backup.is_file():
            return {"write_id": write_id, "status": STATUS_BACKUP_CORRUPTED,
                     "detail": "backup file is missing", "path": record["path"]}
        backup_digest = _digest_bytes(backup.read_bytes())
        if backup_digest != record.get("pre_digest"):
            return {"write_id": write_id, "status": STATUS_BACKUP_CORRUPTED,
                     "detail": "backup content no longer matches its own recorded digest",
                     "path": record["path"]}
        action = "restore_content"
    else:
        action = "delete"

    return {"write_id": write_id, "status": STATUS_AVAILABLE, "action": action,
            "path": record["path"], "detail": "safe to roll back"}


def apply_rollback(root, write_id: str, *, actor: str, reason: str) -> Dict[str, Any]:
    """Undo ONE write. Refuses (raises `RollbackRefusedError`) unless
    `plan_rollback()` itself reports AVAILABLE, re-derived from disk at call
    time -- never from a cached field."""
    if not actor or not str(actor).strip():
        raise SafeWriteError("apply_rollback() requires a real actor identity")
    if not reason or not str(reason).strip():
        raise SafeWriteError("apply_rollback() requires a real, non-empty reason")

    root = Path(root).resolve()
    plan = plan_rollback(root, write_id)
    if plan["status"] != STATUS_AVAILABLE:
        raise RollbackRefusedError(write_id, plan)

    record = read_manifest(root, write_id)  # re-read; plan_rollback proved it is trustworthy
    target = Path(root) / record["path"]

    if record.get("pre_existed"):
        backup = Path(root) / record["pre_backup_path"]
        original = backup.read_bytes()
        fd, tmp = tempfile.mkstemp(prefix=target.stem + ".", suffix=target.suffix or ".tmp",
                                   dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(original)
            _atomic_replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        restored_digest = _digest_bytes(target.read_bytes())
        if restored_digest != record.get("pre_digest"):
            raise AssertionError(
                f"apply_rollback(): restored content for {write_id!r} does not match "
                "its own recorded pre_digest -- refusing to mark it rolled back"
            )
    else:
        if target.is_file():
            target.unlink()

    record["rollback_applied"] = True
    record["rollback_at"] = datetime.now(timezone.utc).isoformat()
    record["rollback_actor"] = str(actor)
    record["rollback_reason"] = str(reason)
    _write_json_atomic(_manifest_path(root, write_id), record)
    return record


# --- batch (multi-file "config change") ---------------------------------------


def safe_write_batch(root, files: Dict[str, Union[bytes, str]], *, actor: str, reason: str,
                      batch_id: Optional[str] = None) -> Dict[str, Any]:
    """Track a multi-file config change as ONE contract. Every path is
    validated (containment + non-collision) BEFORE any file in the batch is
    written, so an invalid path anywhere in the batch aborts the whole batch
    with nothing written -- never a half-applied config change."""
    if not files:
        raise SafeWriteError("safe_write_batch() requires at least one file")
    root = Path(root).resolve()
    bid = batch_id or _new_id("SWB", actor, ",".join(sorted(files)))
    batch_path = _batch_path(root, bid)
    if batch_path.exists():
        raise SafeWriteError(f"batch_id {bid!r} already has a batch record on disk")

    # Validate every path up front; write nothing until all are known-good.
    resolved = {rel: _resolve_target(root, rel) for rel in files}

    write_ids: List[str] = []
    for rel, target in resolved.items():
        record = safe_write(root, rel, files[rel], actor=actor, reason=reason,
                             write_id=_new_id("SW", bid, rel), batch_id=bid)
        write_ids.append(record["write_id"])

    batch_record = {
        "batch_id": bid, "actor": str(actor), "reason": str(reason),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "write_ids": write_ids, "rollback_applied": False,
    }
    _write_json_atomic(batch_path, batch_record)
    return batch_record


def read_batch(root, batch_id: str) -> Optional[Dict[str, Any]]:
    root = Path(root).resolve()
    return _read_json(_batch_path(root, batch_id))


def list_batches(root) -> List[str]:
    d = _sw_root(root) / "batches"
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def plan_rollback_batch(root, batch_id: str) -> Dict[str, Any]:
    """Worst-wins over every write in the batch, plus the one status only a
    batch-wide view can see: some entries already rolled back and others
    not (`PARTIALLY_ROLLED_BACK`)."""
    root = Path(root).resolve()
    batch = read_batch(root, batch_id)
    if batch is None:
        return {"batch_id": batch_id, "status": STATUS_NOT_FOUND,
                "detail": "no batch record on disk for this batch_id", "entries": []}

    entries = [plan_rollback(root, wid) for wid in batch["write_ids"]]
    statuses = {e["status"] for e in entries}

    if statuses == {STATUS_ALREADY_ROLLED_BACK}:
        overall = STATUS_ALREADY_ROLLED_BACK
    elif STATUS_ALREADY_ROLLED_BACK in statuses and statuses - {STATUS_ALREADY_ROLLED_BACK} <= {STATUS_AVAILABLE}:
        overall = STATUS_PARTIALLY_ROLLED_BACK
    else:
        # _SEVERITY_ORDER is most-severe-first, so the WORST status is the
        # one with the SMALLEST rank -- min(), never max().
        overall = min(statuses, key=_severity_rank)

    return {"batch_id": batch_id, "status": overall, "entries": entries}


def apply_rollback_batch(root, batch_id: str, *, actor: str, reason: str) -> Dict[str, Any]:
    """Refuses (raises) unless every entry's plan is cleanly AVAILABLE --
    there is no partial-apply path. Applies all entries, or none."""
    if not actor or not str(actor).strip():
        raise SafeWriteError("apply_rollback_batch() requires a real actor identity")
    if not reason or not str(reason).strip():
        raise SafeWriteError("apply_rollback_batch() requires a real, non-empty reason")

    root = Path(root).resolve()
    plan = plan_rollback_batch(root, batch_id)
    if plan["status"] != STATUS_AVAILABLE:
        raise RollbackRefusedError(batch_id, plan)

    batch = read_batch(root, batch_id)
    applied = [apply_rollback(root, wid, actor=actor, reason=reason)
               for wid in batch["write_ids"]]

    batch["rollback_applied"] = True
    batch["rollback_at"] = datetime.now(timezone.utc).isoformat()
    batch["rollback_actor"] = str(actor)
    batch["rollback_reason"] = str(reason)
    _write_json_atomic(_batch_path(root, batch_id), batch)
    return {"batch_id": batch_id, "rollback_applied": True, "entries": applied}


# --- CLI / ad hoc front door ---------------------------------------------------


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dv_harness.safe_write_rollback")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_write = sub.add_parser("write")
    p_write.add_argument("--path", required=True, help="project-relative destination path")
    p_write.add_argument("--content-file", required=True, help="local file whose bytes to write")
    p_write.add_argument("--actor", required=True)
    p_write.add_argument("--reason", required=True)
    p_write.add_argument("--write-id", default=None)

    p_plan = sub.add_parser("plan")
    p_plan.add_argument("--write-id", required=True)

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--write-id", required=True)
    p_apply.add_argument("--actor", required=True)
    p_apply.add_argument("--reason", required=True)

    p_bplan = sub.add_parser("batch-plan")
    p_bplan.add_argument("--batch-id", required=True)

    p_bapply = sub.add_parser("batch-apply")
    p_bapply.add_argument("--batch-id", required=True)
    p_bapply.add_argument("--actor", required=True)
    p_bapply.add_argument("--reason", required=True)

    sub.add_parser("list")
    sub.add_parser("list-batches")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.verb == "write":
        try:
            content = Path(args.content_file).read_bytes()
            record = safe_write(root, args.path, content, actor=args.actor, reason=args.reason,
                                 write_id=args.write_id)
        except SafeWriteError as e:
            print(f"REFUSED: {e}")
            return 2
        print(json.dumps(record, indent=2))
        return 0

    if args.verb == "plan":
        plan = plan_rollback(root, args.write_id)
        print(json.dumps(plan, indent=2))
        return 0 if plan["status"] == STATUS_AVAILABLE else 1

    if args.verb == "apply":
        try:
            record = apply_rollback(root, args.write_id, actor=args.actor, reason=args.reason)
        except (SafeWriteError, RollbackRefusedError) as e:
            print(f"REFUSED: {e}")
            return 2
        print(json.dumps(record, indent=2))
        return 0

    if args.verb == "batch-plan":
        plan = plan_rollback_batch(root, args.batch_id)
        print(json.dumps(plan, indent=2))
        return 0 if plan["status"] == STATUS_AVAILABLE else 1

    if args.verb == "batch-apply":
        try:
            result = apply_rollback_batch(root, args.batch_id, actor=args.actor, reason=args.reason)
        except (SafeWriteError, RollbackRefusedError) as e:
            print(f"REFUSED: {e}")
            return 2
        print(json.dumps(result, indent=2))
        return 0

    if args.verb == "list":
        ids = list_writes(root)
        print(json.dumps(ids, indent=2))
        return 0 if ids else 2

    if args.verb == "list-batches":
        ids = list_batches(root)
        print(json.dumps(ids, indent=2))
        return 0 if ids else 2

    parser.error(f"unknown verb {args.verb!r}")
    return 2


def main() -> None:
    sys.exit(execute_verb())


if __name__ == "__main__":
    main()
