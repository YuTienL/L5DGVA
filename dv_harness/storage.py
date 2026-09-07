from __future__ import annotations
import json, os, tempfile, threading, time
from pathlib import Path
from typing import Any, Dict
from .models import HarnessState


def _atomic_replace(tmp: str, dest: Path) -> None:
    """os.replace() wrapped with a short retry-on-PermissionError.

    dashboard.py's interactive GET /api/state now polls state.json from an
    HTTP handler thread WHILE a background POST /api/start run is actively
    writing it (dv_harness.dashboard's own thread, same process) -- a
    concurrent-access pattern this file never had to survive when the
    dashboard was read-only and every write came from a separate one-shot
    CLI process. On Windows, os.replace()'s underlying MoveFileEx can throw
    PermissionError (WinError 5) if a reader happens to have the destination
    file open (even just for a read_text() that completes almost
    immediately) at the exact instant of the rename -- POSIX os.replace has
    no such window, so this retry is a no-op there (PermissionError from a
    genuinely-locked file, e.g. a stale antivirus scan, would still
    eventually raise after the last attempt)."""
    last_exc: Exception | None = None
    for attempt in range(10):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError as e:
            last_exc = e
            time.sleep(0.02 * (attempt + 1))
    raise last_exc


class StateStore:
    def __init__(self, project_root: Path):
        self.root = project_root
        self.dir = project_root / ".dv-harness"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.dir / "state.json"
        self.events_file = self.dir / "events.jsonl"
        # Real, not hypothetical: engine._advance_with_fanout() runs every
        # parallel_group branch (RCA_G1, ANALYSIS_G1) via ex.submit(self.
        # _run_branch_to_terminal, ...) on the SAME DVHarness instance, so
        # every branch thread shares this ONE StateStore object -- an
        # in-process threading.Lock fully serializes event() below for the
        # real concurrency shape this bug was found under (see event()'s
        # own docstring). It does not, and is not meant to, guard against a
        # SEPARATE process (e.g. dashboard.py) appending concurrently --
        # that already-different, cross-process case is unchanged.
        self._event_lock = threading.Lock()

    def load(self) -> HarnessState:
        if not self.state_file.exists():
            st = HarnessState(project=self.root.name)
            st.ensure_stages()
            self.save(st)
            return st
        raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        st = HarnessState(**raw)
        st.ensure_stages()
        return st

    def save(self, state: HarnessState) -> None:
        data = state.__dict__.copy()
        fd, tmp = tempfile.mkstemp(prefix="state.", suffix=".json", dir=str(self.dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _atomic_replace(tmp, self.state_file)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def event(self, event: Dict[str, Any]) -> None:
        """Append one line to events.jsonl -- serialized by a real
        threading.Lock, with a short retry-on-transient-PermissionError
        exactly like _atomic_replace() above as a second, independent
        safety net (2026-09-07, real defect found while adding RCA_JOIN's
        own genuine cross-branch contradiction detection).

        engine._advance_with_fanout() runs parallel_group branches -- RCA_G1
        and ANALYSIS_G1 both -- through a real ThreadPoolExecutor inside one
        process, and every branch's run_stage() calls this method from its
        own thread, all sharing this one StateStore instance (see __init__'s
        own comment). Two threads opening the SAME file in append mode at
        nearly the same instant reproduced two real, independent failures
        on Windows: a PermissionError (WinError 5) from the open() call
        itself, AND -- confirmed separately under real concurrent-thread
        stress -- a genuinely LOST line with no exception raised at all
        (Windows' CRT-level append is a seek-to-end-then-write, not POSIX
        O_APPEND's atomic single write, so two interleaved writers can each
        seek to the same offset and one overwrite the other). Retrying the
        open() alone only fixes the first failure; the lock is what actually
        closes the second, real data-loss one, for the real in-process
        concurrency shape this bug was found under. It does not, and is not
        meant to, guard against a SEPARATE process (e.g. dashboard.py)
        appending concurrently -- that already-different, cross-process case
        is unchanged, and the retry-on-PermissionError loop is kept as a
        defensive second layer for exactly that external case (a reader
        transiently holding the file open across a process boundary)."""
        last_exc: Exception | None = None
        with self._event_lock:
            for attempt in range(10):
                try:
                    with self.events_file.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(event, ensure_ascii=False) + "\n")
                    return
                except PermissionError as e:
                    last_exc = e
                    time.sleep(0.02 * (attempt + 1))
        raise last_exc
