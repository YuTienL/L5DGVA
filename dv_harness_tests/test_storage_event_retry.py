"""StateStore.event() retry-on-transient-PermissionError (2026-09-07).

Real defect found while adding RCA_JOIN's own genuine cross-branch
contradiction detection (fanout_contradiction_detection): a real concurrent
RCA_G1 fan-out run, driven through engine._advance_with_fanout()'s own real
ThreadPoolExecutor, raised `PermissionError: ... events.jsonl` from
StateStore.event()'s plain append-mode open() -- state.json (StateStore.save,
via storage._atomic_replace()) and every Blackboard topic (blackboard.py's
write()) already retry this exact transient Windows failure; event() was the
one remaining plain, unretried write in the same real multi-threaded path.
This file proves the fix additively: normal behavior is unchanged, a
transient failure is retried and succeeds, and a persistent failure still
raises after the retry budget -- the identical contract _atomic_replace()
already gives its own callers.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from dv_harness.storage import StateStore


def _tmp_root() -> Path:
    return Path(tempfile.mkdtemp())


def test_event_appends_one_real_json_line_unchanged():
    root = _tmp_root()
    store = StateStore(root)
    store.event({"ts": "t1", "event": "A"})
    store.event({"ts": "t2", "event": "B"})
    lines = store.events_file.read_text(encoding="utf-8").splitlines()
    assert [json.loads(l) for l in lines] == [
        {"ts": "t1", "event": "A"}, {"ts": "t2", "event": "B"}]


def test_event_retries_a_transient_permission_error_and_still_writes_the_line(monkeypatch):
    root = _tmp_root()
    store = StateStore(root)
    real_open = Path.open
    calls = {"n": 0}

    def flaky_open(self, *a, **kw):
        if self == store.events_file and calls["n"] < 2:
            calls["n"] += 1
            raise PermissionError(13, "simulated transient lock")
        return real_open(self, *a, **kw)

    monkeypatch.setattr(Path, "open", flaky_open)
    monkeypatch.setattr(time, "sleep", lambda _s: None)  # keep the test fast
    store.event({"ts": "t1", "event": "REAL_ISSUE"})
    assert calls["n"] == 2, "must genuinely have retried, not skipped the failure"
    lines = store.events_file.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"ts": "t1", "event": "REAL_ISSUE"}


def test_event_still_raises_after_a_persistent_permission_error(monkeypatch):
    """A real, non-transient lock (not a race) must still raise -- the same
    honest failure mode _atomic_replace() keeps for state.json, never a
    silently-dropped event."""
    root = _tmp_root()
    store = StateStore(root)

    def always_fails(self, *a, **kw):
        raise PermissionError(13, "persistently locked")

    monkeypatch.setattr(Path, "open", always_fails)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        store.event({"ts": "t1", "event": "X"})


def test_concurrent_event_writes_from_real_threads_never_lose_or_corrupt_a_line():
    """The real shape of the bug: several threads (mirroring
    engine._advance_with_fanout()'s real ThreadPoolExecutor branches) each
    call event() concurrently against the SAME StateStore. Every one of
    their lines must land intact -- proven by an independent recount, never
    trusting this module's own bookkeeping."""
    import threading
    root = _tmp_root()
    store = StateStore(root)
    n_threads, n_each = 8, 15
    errors = []

    def worker(idx):
        try:
            for j in range(n_each):
                store.event({"ts": f"{idx}-{j}", "event": "BRANCH_EVENT", "thread": idx})
        except Exception as e:  # pragma: no cover - failure path asserted below
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], errors
    lines = store.events_file.read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(l) for l in lines]  # raises if any line is torn/corrupt
    assert len(parsed) == n_threads * n_each
    seen = {(p["thread"], p["ts"]) for p in parsed}
    assert len(seen) == n_threads * n_each, "no line may be lost or duplicated"
