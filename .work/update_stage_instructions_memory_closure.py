"""Updates MEM-34FD025AD6 (STAGE_INSTRUCTIONS/STAGE_GATES completeness gap,
persisted 2026-09-01) to record that its named durable fix -- the permanent
regression test dv_harness_tests/test_stage_instructions_gate_completeness.py
-- was actually committed and synced today (it had been written but left
uncommitted/orphaned since 2026-09-01, discovered via `git status` during
unrelated cleanup and committed on its own, per the Methodology Consolidation
Rule: a validated fix isn't "done" until it's a permanent, git-tracked asset).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dv_harness.memory_router import route_and_store
from dv_harness.memory import MemoryStore

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")

MEMORY_ID = "MEM-34FD025AD6"


def main() -> int:
    store = MemoryStore(ROOT)
    record = store.get(MEMORY_ID)
    if record is None:
        print(f"ERROR: {MEMORY_ID} not found locally")
        return 1

    record["verification"]["regression"] = (
        record["verification"]["regression"]
        + " -- CLOSED 2026-09-02: the test file existed on disk but was never "
        "git-committed (an orphaned artifact from the 2026-09-01 session), "
        "discovered via `git status` during unrelated .work/ cleanup. Committed "
        "on its own (55d44d6, 'test: add permanent stage-gate/instructions "
        "completeness check') and synced to /home/svcacct/AI/Agent; runs 2/2 "
        "passed both locally and on the remote deployment."
    )
    record["note"] = (
        record["note"]
        + " SECOND LESSON (2026-09-02 closure): a permanent regression test "
        "being written and passing locally is not the same as it being "
        "consolidated -- this test sat uncommitted for a full day, meaning "
        "any fresh session or the remote deployment had zero protection "
        "from this bug class recurring, silently contradicting the memory "
        "record's own claim that the test was 'the actual durable fix'. "
        "After completing any implementation work, verify the artifacts "
        "the work's own memory record depends on are actually committed and "
        "synced -- `git status` for orphaned untracked files is a cheap, "
        "concrete check worth running before considering consolidation done."
    )
    record["confirmation_count"] = record.get("confirmation_count", 0) + 1

    # route_and_store's ENGINEERING_MEMORY path calls MemoryStore(root).add(),
    # which overwrites the existing record in place (same memory_id) --
    # no separate store.add() call needed here.
    push = route_and_store(ROOT, record)
    print(f"result -> {push}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
