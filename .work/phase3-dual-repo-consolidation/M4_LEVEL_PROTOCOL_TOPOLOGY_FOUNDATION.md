# M4 — Level / Protocol / Topology Foundation

Per instruction #13. Real, on-disk presence check in canonical (not
assumed) for the models the final IP/SUBSYSTEM/SYSTEM_LEVEL product needs.

| Foundation concept | Real module | Status |
|---|---|---|
| verification level (IP/SUBSYSTEM/SYSTEM_LEVEL) | `verification_level.py` | **ABSENT from canonical** -- Parent-only, already investigated in M3 Cohort 1 and deferred: depends on `.question_queue` (`HUMAN_DECISION_SOURCE`, `QuestionQueueStore`, `make_question_id`), a diverged/M3-excluded module. Real evidence, not assumed. |
| protocol | `protocol_router.py`, `protocol_capability.py` | PRESENT in canonical |
| VIP provider/type | `vip_capability_extraction.py` (M5 target, not yet merged), `vip_distill.py` | PRESENT (vip_distill.py); vip_capability_extraction.py's N-way merge still pending (see M4_M5_PREREQUISITE_MATRIX.csv) |
| DUT ports/interfaces | `dut_evidence_correlation.py`, `interrupt_dma_clock_reset_extraction.py` | PRESENT |
| master/slave, host/device roles | `arbitration_policy_ir.py`, `shared_bus_resource_registry.py` (both confirmed `identical` Parent/v50 per `09_TRANSITIVE_DEPENDENCY_CLOSURE.md`) | PRESENT |
| topology | `subsystem_architecture_analysis.py`, `subsystem_discovery.py` | PRESENT |
| multiple instances, cross-subsystem connectivity | `connectivity.py`, `connectivity_check.py` (both `identical` Parent/v50) | PRESENT |
| binding path | `phy_boundary.py` (diverged -- not investigated this wave) | PRESENT, divergence unresolved |
| source-of-interface discovery | `subsystem_discovery.py` | PRESENT |
| scenario ownership | `de_command_style_learning.py` (diverged, not investigated), `branch_ownership_resolver` (per CLAUDE.md's own Module Index citation) | PRESENT |
| coverage ownership | `coverage_analysis.py` (diverged -- symbol-level check already performed this wave for the specific symbols CAP-M4-002 needed; a full diff not performed) | PRESENT |
| scoreboard/checker ownership | referenced in CLAUDE.md's CSR Checker Placement Rule section (governance-level, not re-verified as code this wave) | PRESENT (governance level) |

## GENERICITY_FOUNDATION_GAP

```
GENERICITY_FOUNDATION_GAPS = 1
  1. verification_level.py absent from canonical -- the ONE foundational
     model that names IP_MODE/SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE explicitly
     is currently missing. This is a REAL gap, not a hard-coded
     single-level assumption forcing a later rewrite -- canonical's own
     environment_mode_router.py (confirmed earlier this session, during
     the KNOWN_SOURCE_B_DEFECT investigation) already resolves
     SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE without IP_MODE support at all, an
     independently-confirmed, narrower version of the same gap.
     Migrating verification_level.py itself requires resolving its
     question_queue.py dependency first (an M5/M6 architecture decision,
     not a foundation item M4 can close alone).
```

No M9 generation work performed or implied by this check, per instruction.
