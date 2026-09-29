"""Shared, real promotion-evidence check for the PROMOTION_READINESS
stage's two sibling gates: tools/verification_flow/promotion_chain_
audit_gate.py (EXPERIENCE_READY, M8 Cohort 1 / GAP-M8-001) and tools/
verification_flow/closed_loop_promotion_gate.py (experience_capture_
status, M8 Cohort H / GAP-M8-010).

CONNECT BEFORE EXPAND (M8 Cohort H): GAP-M8-001's own fix was originally
built directly inside promotion_chain_audit_gate.py. GAP-M8-010 found the
identical self-attestation loophole on its sibling gate -- rather than
copy-pasting the same ~40 lines into a second script (two independently-
maintained copies of the same trust check, exactly the "second trust
framework" this program's own governance forbids), this module is the
ONE real, shared implementation both gate scripts import, the same
established `DV_HARNESS_PACKAGE_ROOT` pattern several other tools/
verification_flow/*.py scripts already use (e.g. qualification_matrix_
consistency_gate.py) to reach the real dv_harness package from their own
standalone-script context.

Deliberately narrow: this module answers exactly one question --
"does this project's own real, durable events.jsonl contain a real,
non-failed promotion event" -- and nothing else. It does not decide which
agent-facing field (EXPERIENCE_READY, experience_capture_status, or any
future sibling) that answer corroborates; each gate script's own main()
keeps that decision, matching its own real self-attested-field name and
semantics."""
from __future__ import annotations

import json
import os
from pathlib import Path

# The real, already-wired promotion events dv_harness/engine.py's own
# route_and_store() call sites emit via StateStore.event() into this
# project's .dv-harness/events.jsonl (see engine.py lines ~1944/3189/
# 3258/3434/3656). A real, non-failed write under one of these names is
# what corroborates a self-attested experience-capture claim. Extend this
# set (never let it silently drift) if a 6th real promotion call site is
# added.
REAL_PROMOTION_EVENTS = {
    "EXPERIENCE_KNOWLEDGE_PROMOTED",
    "PROJECT_TOPOLOGY_PROMOTED",
    "VPLAN_SUMMARY_PROMOTED",
    "VERIFIED_FIX_PROMOTED",
    "DEBUG_ATTEMPT_JOB_MEMORY_RECORDED",
}


def project_root_from_env() -> Path:
    """Same DV_HARNESS_PROJECT_ROOT convention as the waiver_*_gate.py
    scripts (dv_harness/gates.py's _gate_env(): a harness-supplied fact,
    never sourced from agent-authored evidence text, so a caller can't be
    pointed at a fabricated tree). cwd fallback matches run_gate()'s own
    cwd=<project root> subprocess convention."""
    return Path(os.environ.get("DV_HARNESS_PROJECT_ROOT") or os.getcwd())


def real_promotion_event_exists(root: Path) -> bool:
    """True iff this project's own real, durable events.jsonl (dv_harness/
    storage.py's StateStore.event(), the same mechanism every engine.py
    route_and_store() call site already writes through) contains at least
    one real promotion event whose own `promotion` result reports a real,
    non-failed destination."""
    events_file = Path(root) / ".dv-harness" / "events.jsonl"
    if not events_file.exists():
        return False
    try:
        lines = events_file.read_text(encoding="utf-8").splitlines()
    except Exception:
        return False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("event") not in REAL_PROMOTION_EVENTS:
            continue
        promotion = rec.get("promotion")
        if not isinstance(promotion, dict):
            continue
        destination = promotion.get("destination")
        if not destination or destination == "PROMOTION_FAILED":
            continue
        return True
    return False
