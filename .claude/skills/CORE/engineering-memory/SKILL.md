---
name: engineering-memory
description: 保存 CLOSED/VERIFIED bug -> root cause -> fix -> evidence -> regression -> re-audit reusable knowledge。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# engineering-memory
保存 CLOSED/VERIFIED bug -> root cause -> fix -> evidence -> regression -> re-audit reusable knowledge。

核心原則：Memory is prior knowledge, not current evidence.

## Mechanics (2026-09-03, real wiring)

**Purpose**: reusable, single-finding engineering knowledge (root
cause/fix/evidence for one CLOSED/VERIFIED bug) -- the tier
`memory-consolidation`'s qualitative gate protects, and the source tier
`memory_router.promote_to_organizational()` promotes FROM.

**Inputs**: a record with `kind` in `root_cause` / `verified_fix` /
`debug_lesson` AND `verified: true`, ideally carrying `protocol` and
`root_cause` (both required for the dedup/reconfirm path below).

**Outputs**: `route_and_store()` returns
`{"destination": "ENGINEERING_MEMORY", "level": "engineering",
"memory_id": ..., "confirmed_existing": <bool, if a match was reconfirmed>,
"shared_push": <if cfg enables the shared Knowledge Center>,
"vault_write": <the DV-Knowledge Vault note write result>}`.

**Preconditions**: `verified: true`, and ideally the qualitative
verification shape `memory-consolidation` requires (see that skill) already
present on the record before it is written here.

**Execution Steps**:
1. `dv_harness.memory_router._add_or_confirm_engineering()` (called
   automatically by `route_and_store()`) checks for an ACTIVE engineering
   record with the SAME `protocol` + `root_cause` (case-insensitive,
   exact-string match, no fuzzy matching -- a real limitation, not silently
   glossed over).
2. If found: `MemoryGC.confirm(match_id)` increments `confirmation_count`
   and sets `last_confirmed_at` -- this IS the "repeated confirmation"
   mechanism `promote_to_organizational()` later checks. This is what a
   SECOND independent run re-deriving the same root cause looks like in
   practice; it is not achieved by writing the same record twice in one run.
3. If not found: a fresh `MemoryStore.add("engineering", record)`.
4. On success, this ALSO (a) best-effort pushes to the shared cross-user
   Knowledge Center when `cfg.knowledge_center` is enabled (never blocks the
   local write on failure), and (b) mirrors the record into the DV-Knowledge
   Vault as a Markdown+YAML note (`memory_vault.py`,
   `build_frontmatter_from_memory_record()` / `build_sections_from_memory_record()`)
   -- also best-effort, never blocking the local write.

**Fallback**: a vault-write or shared-push failure is reported inline
(`vault_write`/`shared_push` keys showing `"ok": false`) but never raises --
the local JSON write is the one thing that must always succeed.

**Evidence Requirements**: one of the two real verification shapes
`memory_router._verification_is_gate_validated()` recognizes (see
`memory-consolidation` skill) -- both are checked, not assumed, at the
`promote_to_organizational()` boundary, not silently trusted from tier
membership alone.

**Failure Conditions**: `route_memory()` does NOT accept `verified=False`
records with these kinds -- they fall through to WORKING_MEMORY. A caller
that populates `protocol`/`root_cause` inconsistently across independent
runs (e.g. paraphrasing the same root cause differently each time) breaks
the confirmation-dedup match and each run silently creates a new record
instead of confirming the existing one -- keep `root_cause` wording stable
for the same underlying defect.

**Example**:
```python
route_and_store(root, {
    "kind": "verified_fix", "verified": True, "protocol": "USB",
    "scope": "branch_b0", "root_cause": "scoreboard off-by-one on split transactions",
    "fix": "scoreboard.sv:142 -- compare against post-split expected length",
    "verification": {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"},
}, cfg=cfg)
```
