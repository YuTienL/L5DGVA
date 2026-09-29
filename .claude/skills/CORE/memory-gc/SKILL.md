---
name: memory-gc
description: 對過時、錯誤、API 失效或反覆 bad reuse 的 memory 做 DEPRECATED/QUARANTINED，保留 audit history。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# memory-gc
對過時、錯誤、API 失效或反覆 bad reuse 的 memory 做 DEPRECATED/QUARANTINED，保留 audit history。

核心原則：Memory is prior knowledge, not current evidence.

## Mechanics (2026-09-03, real wiring)

**Purpose**: lifecycle management for a memory record that is stale,
wrong, or superseded -- WITHOUT deleting the audit history (retraction and
deprecation are both status changes on the same record, not file removal).
This is also the real "repeated confirmation" mechanism `engineering-memory`
and `organizational-memory` depend on -- `confirm()` lives here.

**Inputs**: a `memory_id` (or `ccl_id` for Corner Case Library entries) and
an action: `deprecate` / `supersede` / `retract` / `flag_stale` / `confirm`.

**Outputs** (`dv_harness.memory.MemoryGC`, mirrored by
`CornerCaseLibrary`'s own methods for CCL entries):
- `deprecate(memory_id, reason)` -> `status: "DEPRECATED"`, reason recorded.
- `supersede(memory_id, superseded_by, reason)` -> `status: "SUPERSEDED"`,
  links forward to the replacement record.
- `retract(memory_id, reason, evidence=None)` -> `status: "RETRACTED"` --
  for a record that turned out to be actively wrong (not merely stale).
- `flag_stale(memory_id, reason="")` -> `status: "STALE"` -- e.g. an API or
  RTL that the record's fix depended on has since changed.
- `confirm(memory_id, evidence=None)` -> increments `confirmation_count`,
  sets `last_confirmed_at` -- the ONLY code path that increments these
  fields. Both Engineering-tier write paths fire it on a re-derivation,
  through the shared `memory.find_confirming_engineering_match()` dedup:
  `memory_router._add_or_confirm_engineering()` (route_and_store's path) and
  `MemoryConsolidator.from_closed_finding()` (memory-consolidation's).

**Preconditions**: the `memory_id` must already exist
(`MemoryStore.get(memory_id)` returns non-None).

**Execution Steps**:
1. Via CLI: `python -m dv_harness.memory_cli deprecate <memory_id> --reason "<why>"`
   (also `corner-case-deprecate <ccl_id> --reason "<why>"`).
2. Via Python: `MemoryGC(MemoryStore(root)).<action>(memory_id, ...)`.
3. `confirm()` is invoked automatically by `route_and_store()` when a NEW
   record's `protocol`+`root_cause` exact-match an existing ACTIVE
   engineering record -- do not call it manually to simulate reconfirmation
   without a genuine independent re-derivation.

**Fallback**: none -- a status change always applies directly; there is no
soft/tentative GC action.

**Evidence Requirements**: `retract`/`flag_stale` should carry the evidence
that made the record stale/wrong (a changed RTL sha, a superseding fix) in
their `evidence`/`reason` argument, for audit trail completeness.

**Failure Conditions**: a record left `ACTIVE` after evidence shows it is
wrong/stale is a policy violation of "current evidence wins" -- do not
leave a known-bad record silently reusable by future retrieval.

**Example**:
```python
from dv_harness.memory import MemoryStore, MemoryGC
MemoryGC(MemoryStore(root)).flag_stale("MEM-ABCDEF0123",
    reason="VIP upgraded to v2.3, sequence API this fix depended on changed")
```
