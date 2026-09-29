"""One shared builder for a record that really clears
`memory_router.organizational_admission_gate()` (2026-09-04, gap-close-
obsidian-memory phase 13+14).

The ORGANIZATIONAL_MEMORY write boundary is now gated: a record reaches the
shared, cross-user Knowledge Center (and mints a real vault git commit
labelled "Organizational Memory approval") only when it carries the promotion
provenance `promote_to_organizational()` stamps, AND that provenance resolves
to a real ACTIVE engineering-tier record whose on-disk `confirmation_count`
was earned through MemoryGC.confirm().

Several test modules exercise what happens AFTER that gate -- tier routing
(test_memory_tier_completion), the Knowledge-Center-only backing store
(test_knowledge_center), the vault note + commit (test_memory_vault), the
write-time secret/artifact guard (test_memory_write_guard_and_job_evidence).
Each of them needs an admitted record, and hand-writing the provenance in
four places would duplicate the gate's contract four times and let the copies
drift. This builds it once, from the real stores and the real scorer -- never
a hand-typed confidence dict and never a forged count.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from dv_harness.inference import score_confidence
from dv_harness.memory import MemoryGC, MemoryStore
from dv_harness.memory_router import ORGANIZATIONAL_MIN_CONFIRMATIONS

# The gate-validated verification shape MemoryConsolidator.from_closed_finding()
# produces (memory_router._verification_is_gate_validated's
# "finding_consolidation_shape").
SOURCE_ENGINEERING_RECORD = {
    "kind": "root_cause", "verified": True, "protocol": "USB3", "scope": "subsystem",
    "title": "LSF job reconciled before batch clean", "root_cause": "sim.log epilogue not parsed",
    "fix": "reconcile on terminal transition", "confidence": "HIGH",
    "evidence": ["sim.log:2201 UVM_ERROR"],
    "verification": {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"},
}

HIGH_CONFIDENCE_INPUTS = dict(independent_sources_count=3, evidence_refs_verified=True,
                              counter_evidence_count=0, multi_agent_consensus_count=2)


def seed_promotable_engineering_record(root: Path) -> str:
    """A real ACTIVE engineering-tier record with ORGANIZATIONAL_MIN_CONFIRMATIONS
    genuinely earned through the one authorized writer (MemoryGC.confirm()),
    since MemoryStore discards a confirmation_count supplied in a record body.
    Returns its memory_id."""
    store = MemoryStore(root)
    memory_id = store.add("engineering", dict(SOURCE_ENGINEERING_RECORD))["memory_id"]
    for run in range(ORGANIZATIONAL_MIN_CONFIRMATIONS):
        MemoryGC(store).confirm(memory_id, evidence={"independent_run": run + 1})
    assert store.get(memory_id)["confirmation_count"] == ORGANIZATIONAL_MIN_CONFIRMATIONS
    return memory_id


def admitted_organizational_record(root: Path, **overrides: Any) -> Dict[str, Any]:
    """The same record shape `promote_to_organizational()` hands to
    `route_and_store()`, backed by a freshly seeded source record in `root`.
    `overrides` are applied last, so a caller can change kind/title/protocol
    or inject the payload its own assertion needs."""
    memory_id = seed_promotable_engineering_record(root)
    record = {
        "kind": "methodology", "verified": True,
        "title": SOURCE_ENGINEERING_RECORD["title"],
        "protocol": SOURCE_ENGINEERING_RECORD["protocol"],
        "root_cause": SOURCE_ENGINEERING_RECORD["root_cause"],
        "verification": dict(SOURCE_ENGINEERING_RECORD["verification"]),
        "confidence_result": score_confidence(**HIGH_CONFIDENCE_INPUTS),
        "source_confirmation_count": ORGANIZATIONAL_MIN_CONFIRMATIONS,
        "source_engineering_memory_id": memory_id,
    }
    record.update(overrides)
    return record
