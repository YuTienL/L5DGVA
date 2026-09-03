---
name: memory-consolidation
description: 只有 CLOSED/VERIFIED + single PASS + regression PASS/NOT_REQUIRED + re-audit CLEAN 才 promotion。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# memory-consolidation
只有 CLOSED/VERIFIED + single PASS + regression PASS/NOT_REQUIRED + re-audit CLEAN 才 promotion。

核心原則：Memory is prior knowledge, not current evidence.

## Mechanics (2026-09-03, real wiring)

**Purpose**: the qualitative hard precondition for anything crossing INTO
Engineering Memory (`MemoryConsolidator.from_closed_finding()`) or from
Engineering to Organizational (`memory_router.promote_to_organizational()`
-- re-checked there, not merely assumed from tier membership, per that
function's own docstring).

**Inputs**: a closed finding + its verification evidence, in ONE of two real
shapes this codebase's write paths actually produce -- there is no third
canonical shape, and `memory_router._verification_is_gate_validated()`
recognizes exactly these two, nothing invented:
- **finding_consolidation_shape** (`MemoryConsolidator.from_closed_finding()`):
  `verification = {"single_sim": "PASS", "regression": "PASS"|"NOT_REQUIRED",
  "reaudit": "CLEAN"}`.
- **re_audit_gate_shape** (`engine.py`'s `_promote_verified_fix_knowledge()`,
  gated beforehand by `fix_effectiveness_gate`/`fix_regression_non_regression_gate`):
  `verification = {"targeted_reproducer_passed": true,
  "broader_regression_passed": true, "new_failures_introduced": false,
  "target_pre_fix_result": "FAIL", "target_post_fix_result": "PASS",
  "replay_equivalent": true}`.

**Outputs**: `(gate_ok: bool, gate_shape: str)` from
`_verification_is_gate_validated(mem)` -- `gate_shape` is
`"finding_consolidation_shape"` / `"re_audit_gate_shape"` /
`"NEITHER_KNOWN_VERIFICATION_SHAPE_SATISFIED"`.

**Preconditions**: the finding must be CLOSED/VERIFIED before this check is
even attempted -- an open or disputed finding never reaches this gate.

**Execution Steps**:
1. Build `verification` in one of the two shapes above, from REAL
   evidence -- never hand-assemble the dict to satisfy the shape without
   the underlying PASS/CLEAN actually having happened.
2. `MemoryConsolidator(store).from_closed_finding(finding, verification)`
   for the initial Engineering Memory write, OR let
   `promote_to_organizational()` re-check an existing record's
   `verification` field for the Engineering->Organizational boundary.
3. On `NEITHER_KNOWN_VERIFICATION_SHAPE_SATISFIED`, do not invent a third
   shape or partially satisfy one -- gather the missing PASS/CLEAN evidence
   first.

**Fallback**: none -- this is a hard precondition, not a soft preference.
A record that cannot satisfy either shape does not consolidate.

**Evidence Requirements**: single-sim PASS + regression PASS/NOT_REQUIRED +
re-audit CLEAN (or the re_audit_gate_shape's stricter pre/post-fix
equivalent), all from actual gate-verified runs, not self-reported.

**Failure Conditions**: mixing fields from both shapes (e.g. `single_sim`
plus `replay_equivalent`) satisfies neither -- `_verification_is_gate_validated()`
checks each shape's full field set independently, with no partial-credit
combination.

**Example** (finding_consolidation_shape):
```python
from dv_harness.memory import MemoryStore, MemoryConsolidator
MemoryConsolidator(MemoryStore(root)).from_closed_finding(finding, {
    "single_sim": "PASS", "regression": "NOT_REQUIRED", "reaudit": "CLEAN",
})
```
