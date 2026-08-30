from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List, Optional


class ParallelFrontierStore:
    """Tracks in-flight graph fan-out branches for a join_group.

    This is the ONLY new persistent state the graph-level parallel
    fan-out/join feature introduces -- HarnessState.current_stage stays a
    scalar string exactly as before; a concurrently-dispatched branch set
    (e.g. PROTOCOL_CAPABILITY's ANALYSIS_G1 fan-out) is tracked here instead,
    separately from .dv-harness/state.json.
    """

    def __init__(self, root):
        self.path = Path(root) / ".dv-harness" / "graph" / "parallel_frontier.json"

    def _load(self) -> Dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: Dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def start(self, join_group: str, source_node: str, branches: List[str]) -> None:
        data = self._load()
        data[join_group] = {
            "join_group": join_group,
            "source_node": source_node,
            "branches": {b: "PENDING" for b in branches},
        }
        self._save(data)

    def set_branch_status(self, join_group: str, branch: str, status: str) -> None:
        data = self._load()
        entry = data.setdefault(
            join_group, {"join_group": join_group, "source_node": None, "branches": {}}
        )
        entry["branches"][branch] = status
        self._save(data)

    def get(self, join_group: str) -> Optional[dict]:
        return self._load().get(join_group)

    def clear(self, join_group: str) -> None:
        data = self._load()
        data.pop(join_group, None)
        self._save(data)
