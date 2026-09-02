"""Persists the 2026-09-02 graph-parallel-dispatch flaky-test root-cause fix
into Engineering Memory, via memory_router.route_and_store() (auto-loads
cfg, pushes to the shared Knowledge Center automatically).

Second instance of the same real-time-margin-under-load bug class fixed
this session (see MEM-F869C96ECB for the first, the dashboard loop() test)
-- linked as related.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dv_harness.memory_router import route_and_store

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")

RECORD = {
    "kind": "verified_fix",
    "verified": True,
    "title": "test_engine_dispatches_all_three_branches_concurrently_and_joins: real-time span assertion failed under -n8 due to OS thread-scheduling jitter, not a dispatch bug -- fixed by diluting the fixed jitter via a longer SLEEP",
    "scope": "engine",
    "symptoms": [
        "dv_harness_tests/test_graph_parallel_dispatch.py::test_engine_dispatches_all_three_branches_concurrently_and_joins failed under a full-suite `pytest -n8` run: AssertionError on `span < SLEEP * 1.8` (SLEEP=0.25, threshold=0.45s), with span=0.7508s -- close to the 3xSLEEP=0.75s a truly-serial (buggy) dispatch would produce, making it look like a real fan-out regression at first glance",
    ],
    "root_cause": (
        "Captured failure data (state['windows']) showed COMMAND_PATTERN's window (enter/exit ~0.25s apart) entirely "
        "disjoint from DISCOVERY/INTAKE's window (which started ~0.24s after COMMAND_PATTERN's own window had "
        "already closed) -- COMMAND_PATTERN ran essentially alone, then DISCOVERY+INTAKE ran together afterward. "
        "This is NOT a dispatch-logic bug: engine.py's fan-out (dv_harness/engine.py, the advance()/ "
        "_advance_with_fanout() path) correctly uses `ThreadPoolExecutor(max_workers=len(targets))`, submitting all "
        "branches in one tight Python-level loop with no artificial staggering. The root cause is real OS-level "
        "thread-scheduling latency: under heavy multi-process CPU contention (pytest -n8's 8 competing worker "
        "processes, several of which spawn their own gate-script subprocesses concurrently, e.g. the dashboard "
        "loop() test fixed the same session -- see MEM-F869C96ECB), the OS can delay actually scheduling 2 of 3 "
        "freshly-created worker threads onto a physical core for a real, noticeable duration, even though Python's "
        "ThreadPoolExecutor.submit() calls happened essentially simultaneously from the test's own perspective. "
        "That absolute OS-jitter magnitude (observed ~0.24s here) does not shrink just because SLEEP is longer -- "
        "it is a roughly fixed environmental cost, independent of the fake adapter's own sleep duration."
    ),
    "fix": (
        "Increased SLEEP from 0.25s to 1.0s (kept the same 1.8x margin, so the threshold becomes 1.8s), diluting the "
        "same fixed ~0.24s absolute OS-jitter down to a much smaller fraction of the total window -- the identical "
        "calibration principle used for the dashboard loop()-test fix (MEM-F869C96ECB) in the same session: widen "
        "the real 'unit of work' relative to a fixed environmental overhead source, rather than arbitrarily loosening "
        "the pass/fail ratio itself (which would blur the line between 'OS jitter' and 'genuinely serial execution', "
        "since both symptoms land in the same rough neighborhood of 3xSLEEP when SLEEP is small)."
    ),
    "verification": {
        "single_sim": "N/A (test-infrastructure fix, not a simulation fix)",
        "regression": (
            "Isolated file run: 6/6 PASS. Full-suite -n8 stress run (the exact condition that reproduced the "
            "original failure): 1865/1865 PASS, zero failures -- both this test and the previously-fixed dashboard "
            "test (MEM-F869C96ECB) held up cleanly together under the same contention that broke each of them "
            "individually earlier the same session."
        ),
        "reaudit": "CONFIRMED: synced to and passed on the real /home/svcacct/AI/Agent deployment (2.18s there for the whole file, uncontended remote environment)",
    },
    "confidence": "CONFIRMED",
    "note": (
        "GENERALIZABLE LESSON, extending MEM-F869C96ECB's finding to a SECOND independent test in the same session: "
        "hard real-time assertions in tests that spawn real OS threads/subprocesses (ThreadPoolExecutor workers, "
        "gate-script subprocesses, HTTP polling threads) are systematically fragile under `pytest -n8` because "
        "MULTIPLE unrelated worker processes compete for the same physical cores simultaneously -- this is not a "
        "single one-off flaky test, it is a class of risk anywhere this test suite spawns real concurrency and "
        "measures wall-clock time against a tight margin. The fix pattern that generalizes: identify the FIXED "
        "environmental overhead (OS thread-scheduling jitter, subprocess-spawn latency) via a captured failure's "
        "actual timing data, then widen the test's own 'unit of work' (a longer SLEEP, more stages, whatever the "
        "test's real workload is) so that fixed overhead becomes a smaller fraction of the total measured window -- "
        "rather than loosening the pass/fail ratio itself, which doesn't distinguish environmental noise from a "
        "genuine regression the assertion exists to catch. Any FUTURE flaky-test report involving real threads/"
        "subprocesses under -n8 should be suspected of this same root cause first, and the SAME two-part diagnostic "
        "(measure the real baseline; check whether the failure's own captured timing data shows a plausible-OS-"
        "jitter shape vs. a plausible-genuine-regression shape) should be applied before touching any number."
    ),
    "provenance": (
        "dv-agent-harness-l5 session, 2026-09-02, systematic-debugging investigation of a second known flaky test "
        "surfaced by the same -n8 stress run used to verify the dashboard test fix (d289589). Commit 436db96."
    ),
    "related_memory": "MEM-F869C96ECB",
}


def main() -> int:
    result = route_and_store(ROOT, RECORD)
    print(f"[{RECORD['title'][:60]}...] -> {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
