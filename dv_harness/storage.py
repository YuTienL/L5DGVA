from __future__ import annotations
import json, os, tempfile, time
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
        with self.events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
