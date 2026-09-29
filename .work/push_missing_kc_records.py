"""One-off script fixing a real bug just found: route_and_store()'s shared
push to the Knowledge Center only fires when the caller passes `cfg`
explicitly -- persist_relay_msys_kc_memory.py and
persist_debug_workflow_gap_closure_memory.py both called
route_and_store(ROOT, record) without cfg, so their 4 records wrote
locally but were never pushed to /home/svcacct/AI/DB. This pushes those
existing local records directly via maybe_push_to_shared(), without
re-adding them locally (route_and_store() would mint new memory_ids).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dv_harness.config import load_config
from dv_harness.knowledge_center import maybe_push_to_shared

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")

MISSING_IDS = ["MEM-04B0C14D91", "MEM-36006EC300", "MEM-57B0E47E41", "MEM-EA3FCC5DA5"]


def main() -> int:
    cfg = load_config(ROOT)
    for mem_id in MISSING_IDS:
        path = ROOT / ".dv-harness" / "memory" / "engineering" / f"{mem_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        result = maybe_push_to_shared(cfg, ROOT, "ENGINEERING_MEMORY", "_general", "_general", record)
        print(f"[{mem_id}] -> {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
