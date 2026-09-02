"""Persists the 2026-09-02 lsf-watch-start operational gap into Engineering
Memory, via memory_router.route_and_store() (auto-loads cfg, pushes to the
shared Knowledge Center automatically).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dv_harness.memory_router import route_and_store

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")

RECORD = {
    "kind": "debug_lesson",
    "verified": True,
    "title": "REMOTE_EXECUTION was declared and remote work dispatched to a specialized subagent without first running dv-harness lsf-watch-start -- the CLAUDE.md rule exists but is not self-enforcing when a subagent owns the remote work",
    "scope": "engine",
    "symptoms": [
        "Declared REMOTE_EXECUTION and dispatched a full USB VIP UVM environment build to the IP_UVM_DV_Gen specialized agent (SSH relay already confirmed READY), without first running `dv-harness lsf-watch-start --vcuser <account>` as CLAUDE.md's own 'Background Job/Log Monitor Auto-Start' section requires before submitting or expecting visibility into any LSF job that session",
        "User caught it directly: \"為何沒有上 LSF\" (why hasn't the LSF watcher been started)",
    ],
    "root_cause": (
        "CLAUDE.md documents the lsf-watch-start requirement, but it is agent-supplied protocol discipline, not an "
        "engine-enforced gate (no code path fires it automatically the moment REMOTE_EXECUTION_REQUIRED is declared "
        "-- this is explicitly called out in CLAUDE.md's own text). When the controlling session dispatches remote "
        "work to a SPECIALIZED SUBAGENT (here, IP_UVM_DV_Gen) rather than running remote_exec.py commands directly "
        "itself, the natural place this rule gets applied -- right before issuing the first remote command -- gets "
        "skipped, because the controller's own next action is 'dispatch an agent', not 'issue a remote command', "
        "and the dispatched subagent's own prompt did not explicitly carry the lsf-watch-start requirement forward. "
        "The rule was followed correctly in every PRIOR remote_exec.py-direct interaction this session (verifying "
        "the DUT path, checking relay status) -- the gap was specific to the moment the controller handed off "
        "remote responsibility to a subagent without re-stating this specific protocol obligation in the handoff."
    ),
    "fix": (
        "Started the watcher retroactively (`dv-harness lsf-watch-start --vcuser devuser`) once caught, and "
        "cross-checked `bjobs -a` on the remote host first to confirm no USB-build-related LSF job had already run "
        "unmonitored during the gap window (only 2 pre-existing, unrelated jobs were running -- calibre and apr -- "
        "confirming the dispatched agent had not yet reached an actual `bsub` submission, it was still in compile/"
        "static-check territory, so no real job visibility was actually lost this time)."
    ),
    "verification": {
        "single_sim": "N/A (process/protocol gap, not a simulation defect)",
        "regression": "N/A",
        "reaudit": "Watcher confirmed started (pid 35656) via `dv-harness lsf-watch-start --vcuser devuser`; `bjobs -a` cross-checked to confirm no unmonitored job had already run",
    },
    "confidence": "CONFIRMED",
    "note": (
        "GENERALIZABLE PROCESS LESSON: whenever REMOTE_EXECUTION is declared AND the actual remote work is handed "
        "off to a dispatched agent (not run directly by the controlling session via remote_exec.py), the controller "
        "must run `dv-harness lsf-watch-start --vcuser <account>` itself BEFORE dispatching -- do not rely on the "
        "dispatched agent's own prompt to carry this forward implicitly, and do not treat 'I already checked the "
        "relay is READY' as equivalent to 'the LSF watcher is running'; they are two separate, both-required setup "
        "steps under CLAUDE.md's Execution Mode Gate + Background Job/Log Monitor Auto-Start sections. A useful "
        "self-check before any REMOTE_EXECUTION dispatch: relay READY? watcher started? -- both, not just the "
        "first. If a dispatch already happened without it (as here), cross-check `bjobs -a` on the remote host "
        "immediately upon noticing the gap to determine whether any job actually ran unmonitored, rather than "
        "assuming either 'nothing happened yet' or 'something was definitely missed'."
    ),
    "provenance": (
        "dv-agent-harness-l5 session, 2026-09-02, USB VIP-based UVM subsystem environment build (IP_UVM_DV_Gen "
        "dispatch). Caught by direct user query, not self-detected."
    ),
}


def main() -> int:
    result = route_and_store(ROOT, RECORD)
    print(f"[{RECORD['title'][:60]}...] -> {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
