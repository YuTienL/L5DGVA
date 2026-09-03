---
name: organizational-memory
description: 保存跨 project 可重用 VIP integration、debug methodology、tool usage、signoff lesson；不得保存 credential。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# organizational-memory
保存跨 project 可重用 VIP integration、debug methodology、tool usage、signoff lesson；不得保存 credential。

核心原則：Memory is prior knowledge, not current evidence.

## Mechanics (2026-09-03, real wiring)

**Purpose**: the highest, cross-project reuse tier -- methodology/best
practice/cross-project lesson knowledge, gated hardest because it is trusted
across every project, not just the one that produced it.

**Inputs**: never write `ORGANIZATIONAL_MEMORY` directly. Call
`dv_harness.memory_router.promote_to_organizational(root, memory_id,
confidence_inputs, cfg, kind="methodology"|"best_practice"|"cross_project_lesson")`
against an EXISTING, ACTIVE Engineering Memory `memory_id`.
`confidence_inputs` = `{independent_sources_count, evidence_refs_verified,
counter_evidence_count, multi_agent_consensus_count}` for
`inference.score_confidence()`.

**Outputs**: on success, the same shape as a direct `route_and_store()`
ORGANIZATIONAL_MEMORY call (`OrganizationalMemoryStore.add()` push result +
`vault_write`), PLUS a `promotion_gate` block showing
`qualitative_shape`/`confidence_result`/`confirmation_count` -- the actual
evidence the promotion decision was based on. On a gate miss, returns
`{"promoted": False, "reason": "QUALITATIVE_GATE_FAILED" |
"CONFIDENCE_NOT_HIGH" | "INSUFFICIENT_CONFIRMATION" | "NOT_ENGINEERING_TIER"
| "NOT_ACTIVE", ...}` -- never raises for an ordinary gate miss (only for an
unknown `memory_id`).

**Preconditions** (ALL required, cheapest-first):
1. `mem["level"] == "engineering"` and `mem["status"] == "ACTIVE"`.
2. Qualitative gate: one of the two real verification shapes (see
   `memory-consolidation`) present on the record.
3. `score_confidence(**confidence_inputs)["level"] == "HIGH"`.
4. `mem["confirmation_count"] >= ORGANIZATIONAL_MIN_CONFIRMATIONS` (2).

**Execution Steps**:
1. Ensure the source Engineering Memory record has already been
   re-confirmed at least once (`engineering-memory` skill's dedup/confirm
   path) -- one creation event is not revalidation (CLAUDE.md: "any current
   root cause must be revalidated with current evidence").
2. Gather the 4 `confidence_inputs` honestly from THIS promotion decision's
   own evidence gathering (independent sources actually consulted,
   evidence refs actually verified, counter-evidence actually found,
   multi-agent consensus actually reached) -- never hardcode inputs to force
   a HIGH result.
3. Call `promote_to_organizational()`. Inspect `reason` on any
   `promoted: False` result before retrying -- do not loosen the gate
   inputs to force a pass.

**Fallback**: no fallback promotion path exists by design -- a record that
cannot clear all three gates stays at Engineering tier until it can.

**Evidence Requirements**: real, current evidence for every
`confidence_inputs` field -- this is the one place in the memory system
where a caller (today: a human or the future Memory Agent) supplies
evidence-gathering results the code cannot derive on its own.

**Failure Conditions**: promoting on a single PASS, an unconfirmed record,
or fabricated `confidence_inputs` all violate the Engineering Memory
Policy's "Never promote unverified hypotheses" rule even though the code
gate would catch fabricated-but-consistent inputs only probabilistically,
not deterministically -- this remains a human/agent integrity requirement,
not solely a code guarantee.

**Example**:
```python
from dv_harness.memory_router import promote_to_organizational
promote_to_organizational(root, "MEM-ABCDEF0123",
    confidence_inputs={"independent_sources_count": 3, "evidence_refs_verified": True,
                        "counter_evidence_count": 0, "multi_agent_consensus_count": 2},
    cfg=cfg, kind="methodology")
```
