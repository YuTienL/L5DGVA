# -*- coding: utf-8 -*-
"""Server-side broker for the DV Agent Harness L5 shared knowledge center.

Deploy ONE copy of this file to a fixed path on the Linux DV server (e.g.
`--put broker.py <remote_root>/broker.py` via remote_hop.py, once). Every
user's local `dv_harness.knowledge_center.KnowledgeCenterClient` invokes it
over a short-lived telnet+ssh call (never a mounted network filesystem) with
one JSON payload file and reads exactly one result line back.

WHY a server-side broker instead of a shared mounted directory: an audit of
this project's own storage code (dv_harness/memory.py, blackboard.py) found
ZERO file-locking anywhere, and every index file is read-modify-write
(read the whole index, mutate one row, overwrite the whole file) -- safe for
one process, a silent lost-update race for two. Doing that read-modify-write
on a Windows-vs-Linux NFS mount from multiple independent machines would
inherit that race with no reliable cross-client lock semantics to fix it
with. Routing every write through ONE broker process on the Linux side lets
this file use real `fcntl.flock()` on a local POSIX filesystem, which IS
reliable, and serializes all writes to the same shard through one lock file.

Directory layout under --root (created by `init`, one-time):
  <root>/
    manifest.json                        taxonomy + schema version
    registry/<category>/<protocol>/index.json   sharded index (small -> low lock contention)
    records/<category>/<protocol>/<id>.json     one file per knowledge record
    locks/<category>__<protocol>.lock           one flock file per shard

Record status lifecycle (mirrors dv_harness/memory.py's MemoryGC/
CornerCaseLibrary methods so a shared record and a purely local one use the
same vocabulary): ACTIVE -> NEEDS_REVALIDATION -> ACTIVE (via `confirm`), or
ACTIVE -> SUPERSEDED / RETRACTED (via `deprecate`, permanent). Only ACTIVE
records are returned by `search`.

Usage (always one verb + one JSON payload file):
  python3 broker.py init     --root <root>
  python3 broker.py ping     --root <root>
  python3 broker.py add      --root <root> --payload-file <p>
  python3 broker.py search   --root <root> --payload-file <p>
  python3 broker.py deprecate --root <root> --payload-file <p>
  python3 broker.py confirm  --root <root> --payload-file <p>

Every invocation prints exactly ONE line starting with "DVHKC_RESULT:"
followed by a JSON object, as its LAST stdout line -- this is the only
contract the client (dv_harness/knowledge_center.py) relies on; anything
else printed before it is ignored (so this script's own errors/tracebacks
elsewhere on stdout/stderr don't break parsing, they just make that run
report ok:false with no result line).
"""
import argparse, json, os, sys, tempfile, time, uuid

try:
    import fcntl
    _HAVE_FCNTL = True
except ImportError:  # Windows -- this script is meant to run on the Linux
    _HAVE_FCNTL = False  # server, but stay importable for local dev/tests.

RESULT_MARKER = "DVHKC_RESULT:"
SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_DAYS = 180
ACTIVE_STATUSES = {"ACTIVE"}
TERMINAL_STATUSES = {"SUPERSEDED", "RETRACTED"}


def _slug(s: str) -> str:
    s = (s or "_general").strip().lower()
    out = "".join(c if c.isalnum() or c in "-_" else "_" for c in s)
    return out or "_general"


class _ShardLock:
    """A real advisory lock, held for the shortest possible critical
    section (read-index, mutate, write-index). Local-filesystem-only by
    design (see module docstring) -- never used across a network mount."""

    def __init__(self, root: str, category: str, protocol: str):
        lock_dir = os.path.join(root, "locks")
        os.makedirs(lock_dir, exist_ok=True)
        self.path = os.path.join(lock_dir, f"{_slug(category)}__{_slug(protocol)}.lock")
        self._fh = None

    def __enter__(self):
        self._fh = open(self.path, "a+")
        if _HAVE_FCNTL:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        if _HAVE_FCNTL and self._fh:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        if self._fh:
            self._fh.close()
        return False


def _atomic_write_json(path: str, obj) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp.", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _read_json(path: str, default):
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _index_path(root: str, category: str, protocol: str) -> str:
    return os.path.join(root, "registry", _slug(category), _slug(protocol), "index.json")


def _record_path(root: str, category: str, protocol: str, record_id: str) -> str:
    return os.path.join(root, "records", _slug(category), _slug(protocol), f"{record_id}.json")


def _manifest_path(root: str) -> str:
    return os.path.join(root, "manifest.json")


def _activity_path(root: str) -> str:
    return os.path.join(root, "activity.jsonl")


def _log_activity(root: str, action: str, record_id: str, category: str, protocol: str,
                   provenance: dict, summary: str = "", extra: dict = None) -> None:
    """Append one line to the DB-wide activity log (who added/updated/
    retracted/confirmed what, when) -- distinct from each record's own
    per-record `history` list, which only that ONE record's document
    carries. This is the source `db_info` reads to answer "what has
    happened across the whole shared knowledge center", the equivalent of
    the local harness's events.jsonl but for the shared store. Uses its own
    lock file (not a per-category/protocol shard lock) since this is a
    single global append target regardless of which shard the record
    belongs to."""
    entry = {
        "ts": time.time(), "action": action, "memory_id": record_id,
        "category": category, "protocol": protocol,
        "origin_user": (provenance or {}).get("origin_user"),
        "origin_host": (provenance or {}).get("origin_host"),
        "summary": summary,
    }
    if extra:
        entry.update(extra)
    lock_dir = os.path.join(root, "locks")
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, "_activity.lock")
    fh = open(lock_path, "a+")
    try:
        if _HAVE_FCNTL:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        with open(_activity_path(root), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    finally:
        if _HAVE_FCNTL:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def cmd_init(root: str, payload: dict) -> dict:
    os.makedirs(root, exist_ok=True)
    for sub in ("registry", "records", "locks"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    manifest_path = _manifest_path(root)
    manifest = _read_json(manifest_path, None)
    if manifest is None:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": time.time(),
            "categories": payload.get("categories") or [
                "usb", "pcie", "amba4", "ethernet", "mipi_csi2", "mipi_dsi",
                "can_fd", "emmc", "sd_sdio", "_general",
            ],
        }
        _atomic_write_json(manifest_path, manifest)
    return {"root": root, "manifest": manifest, "created": True}


def cmd_ping(root: str, payload: dict) -> dict:
    manifest = _read_json(_manifest_path(root), None)
    return {"root": root, "initialized": manifest is not None, "manifest": manifest,
            "server_time": time.time()}


def cmd_add(root: str, payload: dict) -> dict:
    category = payload.get("category") or "_general"
    protocol = payload.get("protocol") or "_general"
    record = dict(payload.get("record") or {})
    provenance = dict(payload.get("provenance") or {})
    max_age_days = payload.get("max_age_days", DEFAULT_MAX_AGE_DAYS)

    record_id = record.get("memory_id") or record.get("ccl_id") or f"KC-{uuid.uuid4().hex[:12].upper()}"
    record["memory_id"] = record_id
    record.setdefault("status", "ACTIVE")
    record.setdefault("confirmation_count", 0)
    record.setdefault("last_confirmed_at", None)
    # The server stamps its own clock for written_at/revalidate_by -- a
    # client's local clock is not trusted as the authoritative timestamp for
    # data multiple OTHER users' harnesses will read staleness decisions
    # from.
    now = time.time()
    record["written_at"] = now
    if max_age_days:
        record["revalidate_by"] = now + float(max_age_days) * 86400.0
    else:
        record["revalidate_by"] = None
    provenance.setdefault("server_received_at", now)
    record["provenance"] = provenance
    record["category"] = category
    record["protocol"] = protocol

    with _ShardLock(root, category, protocol):
        rec_path = _record_path(root, category, protocol, record_id)
        _atomic_write_json(rec_path, record)
        idx_path = _index_path(root, category, protocol)
        rows = [r for r in _read_json(idx_path, []) if r.get("memory_id") != record_id]
        rows.append({
            "memory_id": record_id, "category": category, "protocol": protocol,
            "kind": record.get("kind"), "title": record.get("title") or record.get("description", ""),
            "status": record.get("status"), "written_at": now,
            "revalidate_by": record.get("revalidate_by"),
            "origin_user": provenance.get("origin_user"),
            "origin_project": provenance.get("origin_project"),
        })
        _atomic_write_json(idx_path, rows)

    _log_activity(root, "CREATED", record_id, category, protocol, provenance,
                  summary=record.get("title") or record.get("description", ""))
    return {"memory_id": record_id, "category": category, "protocol": protocol, "written_at": now}


def _iter_shards(root: str, category: str, protocol: str):
    reg_root = os.path.join(root, "registry")
    if not os.path.isdir(reg_root):
        return
    cats = [category] if category else os.listdir(reg_root)
    for cat in cats:
        cat_dir = os.path.join(reg_root, _slug(cat))
        if not os.path.isdir(cat_dir):
            continue
        protos = [protocol] if protocol else os.listdir(cat_dir)
        for proto in protos:
            idx = os.path.join(cat_dir, _slug(proto), "index.json")
            if os.path.isfile(idx):
                yield _slug(cat), _slug(proto), idx


def cmd_search(root: str, payload: dict) -> dict:
    category = payload.get("category") or ""
    protocol = payload.get("protocol") or ""
    text = str(payload.get("text") or "").lower()
    limit = int(payload.get("limit") or 8)
    now = time.time()
    hits = []
    for cat, proto, idx_path in _iter_shards(root, category, protocol):
        for row in _read_json(idx_path, []):
            if row.get("status") not in ACTIVE_STATUSES:
                continue
            revalidate_by = row.get("revalidate_by")
            if revalidate_by is not None and now > float(revalidate_by):
                continue  # aged out -- needs revalidation, not returned as reusable
            if text and text not in json.dumps(row, ensure_ascii=False).lower():
                continue
            hits.append(row)
    hits.sort(key=lambda r: r.get("written_at") or 0, reverse=True)
    hits = hits[:limit]
    records = []
    for row in hits:
        rec = _read_json(_record_path(root, row["category"], row["protocol"], row["memory_id"]), None)
        if rec:
            records.append(rec)
    return {"count": len(records), "records": records}


def _load_mutate_save(root: str, category: str, protocol: str, record_id: str, mutate):
    with _ShardLock(root, category, protocol):
        rec_path = _record_path(root, category, protocol, record_id)
        rec = _read_json(rec_path, None)
        if rec is None:
            return None
        mutate(rec)
        _atomic_write_json(rec_path, rec)
        idx_path = _index_path(root, category, protocol)
        rows = _read_json(idx_path, [])
        for row in rows:
            if row.get("memory_id") == record_id:
                row["status"] = rec.get("status")
                row["revalidate_by"] = rec.get("revalidate_by")
        _atomic_write_json(idx_path, rows)
        return rec


def cmd_deprecate(root: str, payload: dict) -> dict:
    category = payload.get("category") or "_general"
    protocol = payload.get("protocol") or "_general"
    record_id = payload["record_id"]
    reason = payload.get("reason", "")
    evidence = payload.get("evidence") or {}
    provenance = payload.get("provenance") or {}

    def mutate(rec):
        rec["status"] = "RETRACTED"
        rec["retraction_reason"] = reason
        rec["retraction_evidence"] = evidence
        rec.setdefault("history", []).append({
            "action": "RETRACTED", "reason": reason, "by": provenance,
            "at": time.time(),
        })

    rec = _load_mutate_save(root, category, protocol, record_id, mutate)
    if rec is None:
        return {"ok": False, "error": "NOT_FOUND"}
    _log_activity(root, "RETRACTED", record_id, category, protocol, provenance, summary=reason)
    return {"memory_id": record_id, "status": rec["status"]}


def cmd_confirm(root: str, payload: dict) -> dict:
    category = payload.get("category") or "_general"
    protocol = payload.get("protocol") or "_general"
    record_id = payload["record_id"]
    evidence = payload.get("evidence") or {}
    provenance = payload.get("provenance") or {}
    max_age_days = payload.get("max_age_days", DEFAULT_MAX_AGE_DAYS)

    def mutate(rec):
        rec["confirmation_count"] = int(rec.get("confirmation_count", 0)) + 1
        now = time.time()
        rec["last_confirmed_at"] = now
        rec["last_confirmation_evidence"] = evidence
        if max_age_days:
            rec["revalidate_by"] = now + float(max_age_days) * 86400.0
        if rec.get("status") == "NEEDS_REVALIDATION":
            rec["status"] = "ACTIVE"
        rec.setdefault("history", []).append({
            "action": "CONFIRMED", "by": provenance, "at": now,
        })

    rec = _load_mutate_save(root, category, protocol, record_id, mutate)
    if rec is None:
        return {"ok": False, "error": "NOT_FOUND"}
    _log_activity(root, "CONFIRMED", record_id, category, protocol, provenance)
    return {"memory_id": record_id, "status": rec["status"],
             "confirmation_count": rec["confirmation_count"]}


def cmd_db_info(root: str, payload: dict) -> dict:
    """Answers "who added/updated/deleted what, when, and a short
    description" across the WHOLE shared knowledge center -- the DB-wide
    activity log, distinct from a single record's own `history` list.
    Reads activity.jsonl (append-only, written by cmd_add/cmd_deprecate/
    cmd_confirm), newest first, optionally filtered by category/protocol/
    action, capped at `limit` (default 100)."""
    category = payload.get("category") or ""
    protocol = payload.get("protocol") or ""
    action = payload.get("action") or ""
    limit = int(payload.get("limit") or 100)
    path = _activity_path(root)
    entries = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if category:
        entries = [e for e in entries if e.get("category") == category]
    if protocol:
        entries = [e for e in entries if e.get("protocol") == protocol]
    if action:
        entries = [e for e in entries if e.get("action") == action]
    entries.sort(key=lambda e: e.get("ts") or 0, reverse=True)
    entries = entries[:limit]
    by_action = {}
    for e in entries:
        by_action[e.get("action", "?")] = by_action.get(e.get("action", "?"), 0) + 1
    return {"count": len(entries), "by_action": by_action, "activity": entries}


VERBS = {
    "init": cmd_init, "ping": cmd_ping, "add": cmd_add, "search": cmd_search,
    "deprecate": cmd_deprecate, "confirm": cmd_confirm, "db_info": cmd_db_info,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("verb", choices=sorted(VERBS.keys()))
    ap.add_argument("--root", required=True)
    ap.add_argument("--payload-file", default=None)
    args = ap.parse_args()

    payload = {}
    if args.payload_file:
        with open(args.payload_file, "r", encoding="utf-8") as f:
            payload = json.load(f)

    try:
        result = VERBS[args.verb](args.root, payload)
        result.setdefault("ok", True)
    except Exception as exc:  # noqa: BLE001 - must always emit a result line
        result = {"ok": False, "error": type(exc).__name__, "detail": str(exc)}

    print(RESULT_MARKER + json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
