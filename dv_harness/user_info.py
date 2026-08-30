from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# Answers "who has used THIS project-root deployment of the harness, and
# when" -- distinct from control_plane.py's approvals/cosigns (which only
# capture human-control-plane actions) and from the shared knowledge
# center's own activity.jsonl (dv_harness/knowledge_center.py + tools/
# knowledge_center/broker.py, which tracks record-level add/retract/confirm
# across the SHARED store, not per-deployment CLI/GUI access). This module
# reads the SAME events.jsonl every other audit view already reads
# (dashboard.py's _audit_trail, `dv-harness audit`) -- no new storage
# format, just a by-user rollup of the "user"/"host" fields CLI_ACCESS/
# GUI_ACCESS events (logged in cli.py/dashboard.py) and the pre-existing
# control-plane events already carry.

ACCESS_EVENT_TYPES = {"CLI_ACCESS", "GUI_ACCESS"}

# Neither the CLI (one short-lived process per invocation) nor the GUI
# (stateless HTTP polling) has a real "logout" signal to log -- there is no
# hook that fires when a user closes their terminal or browser tab. Rather
# than fabricate a fake logout event, sessions are inferred: a gap of more
# than SESSION_GAP_SECONDS between two of the same user's access events
# starts a new session; a session's `login_at` is its first event, and
# `logout_at` is its LAST event timestamp -- an honest "last seen before
# this session went quiet", not a guaranteed real logout instant.
SESSION_GAP_SECONDS = 1800.0


def _read_events(root: Path) -> List[Dict[str, Any]]:
    p = Path(root) / ".dv-harness" / "events.jsonl"
    if not p.exists():
        return []
    out = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _to_epoch(ts) -> Optional[float]:
    """events.jsonl timestamps are ISO-8601 strings (control_plane.now())
    for control-plane events but epoch floats for CLI_ACCESS/GUI_ACCESS
    (this module logs those with time.time(), matching session_snapshot.py/
    knowledge_center.py's convention) -- normalize both to epoch floats so
    session-gap arithmetic works regardless of which kind of event it is."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def summarize_user_access(root: Path, limit: int = 200) -> Dict[str, Any]:
    """Every event that carries a `user` field (CLI_ACCESS/GUI_ACCESS,
    plus the pre-existing control-plane events -- PAUSE/TAKEOVER/APPROVE/
    CORRECT/etc already stamp `taken_by`/`corrected_by`/`reviewer_id` via
    control_plane.py's _default_user()) counts as one access record.
    Rolled up per user into inferred login/logout sessions (see
    SESSION_GAP_SECONDS) plus a flat recent-access feed."""
    events = _read_events(root)
    per_user_events: Dict[str, List[Dict[str, Any]]] = {}
    recent: List[Dict[str, Any]] = []

    for e in events:
        kind = e.get("event", "")
        user = e.get("user") or e.get("taken_by") or e.get("corrected_by") or e.get("reviewer_id")
        if not user:
            continue
        epoch = _to_epoch(e.get("ts"))
        per_user_events.setdefault(user, []).append({
            "ts": e.get("ts"), "epoch": epoch, "event": kind, "host": e.get("host"),
        })
        if kind in ACCESS_EVENT_TYPES:
            recent.append(e)

    recent.sort(key=lambda e: str(e.get("ts") or ""), reverse=True)
    recent = recent[:limit]

    users = []
    for user, evs in per_user_events.items():
        evs = [e for e in evs if e["epoch"] is not None] or evs
        evs.sort(key=lambda e: e["epoch"] if e["epoch"] is not None else 0)
        sessions = []
        for e in evs:
            if sessions and e["epoch"] is not None and sessions[-1]["_last_epoch"] is not None \
                    and e["epoch"] - sessions[-1]["_last_epoch"] <= SESSION_GAP_SECONDS:
                sessions[-1]["logout_at"] = e["ts"]
                sessions[-1]["_last_epoch"] = e["epoch"]
                sessions[-1]["event_count"] += 1
                if e["host"]:
                    sessions[-1]["hosts"].add(e["host"])
            else:
                sessions.append({
                    "login_at": e["ts"], "logout_at": e["ts"], "_last_epoch": e["epoch"],
                    "event_count": 1, "hosts": {e["host"]} if e["host"] else set(),
                })
        for s in sessions:
            s.pop("_last_epoch", None)
            s["hosts"] = sorted(s["hosts"])
        users.append({
            "user": user,
            "session_count": len(sessions),
            "total_events": len(evs),
            "first_seen": sessions[0]["login_at"] if sessions else None,
            "last_seen": sessions[-1]["logout_at"] if sessions else None,
            "sessions": sessions,
        })

    users.sort(key=lambda r: str(r["last_seen"] or ""), reverse=True)
    return {"users": users, "recent_access": recent}
