# L5DGVA Canonical Final Definition of Done

Recorded verbatim as delivered by the project owner, during M1 execution
(2026-09-22). This is a standing, long-term governing target for the
canonical `L5_DGVA` repository as a whole -- it does **not** change M1's
own approved, bounded scope (canonical repository bootstrap + v50
baseline qualification only). M1's final report still reports
`PARENT_CAPABILITY_MIGRATION_STARTED = NO`,
`WORKTREE_CAPABILITY_MIGRATION_STARTED = NO`, etc., unchanged by this
statement. Later waves (M3+) are the ones this Definition of Done governs
directly.

> Canonical L5DGVA SHALL be a strict operational capability superset of
> the maximum verified capability union of Parent DV Agent Harness L5,
> v50, and all approved worktree/working-tree migration inputs, while
> resolving source defects and semantic conflicts and adding the
> canonical platform capabilities required to automatically generate,
> execute, close coverage, trace, and sign off VIP-based verification
> environments at IP, Subsystem, and System-Level.

## Correction (same session, immediately following): milestone-scoped strength

The project owner corrected an oversimplified reading of the above ("functionality
at least equal to v50") that is valid **only** as the M1 bootstrap checkpoint gate,
not as the final product criterion:

- **M1 gate**: `Capability(Canonical_M1) >= Capability(V50_REQUIRED_BASELINE)`
- **Final gate**: `Capability(Canonical_Final) > MaximumVerifiedCapabilityUnion(Parent, v50, approved Parent working-tree inputs, approved v50 working-tree inputs, b7a, b7b, b8, approved untracked migration inputs)` -- a **strict** superset, never merely equal, and never measured by file/module/method/line/test count -- only by capability-level evidence (`IMPLEMENTED`/`WIRED`/`TRIGGERED`/`CONSUMED`/`OBSERVED`/`TESTED`).

Final strict-superset gate (future waves, not M1):
```
SOURCE_CAPABILITY_LOSS = 0
SOURCE_VERIFIED_CAPABILITIES_PRESERVED = 100%
CANONICAL_NEW_OPERATIONAL_CAPABILITIES > 0
CANONICAL_ENHANCED_CAPABILITIES > 0
CANONICAL_CAPABILITY_STRICT_SUPERSET = PASS
```
tracked via a `CANONICAL_CAPABILITY_SUPERSET_MATRIX` (per Capability ID:
`PARENT_STATUS`/`V50_STATUS`/`WORKTREE_STATUS`/`CANONICAL_STATUS`/`PRESERVED`/
`SUPERSEDED`/`ENHANCED`/`NEW`/`EVIDENCE`/`TEST`/`FINAL_VERDICT`) -- not yet
created; a future-wave artifact, not an M1 deliverable.

A source implementation may be replaced by a stronger canonical one without
surviving as a duplicate file, provided its verified behavior is not lost.

Milestone semantics:
```
M1:  Canonical >= v50 baseline
M8:  Canonical >= verified union of all migration sources
M13: Canonical > verified union of all migration sources
```

The final product must additionally prove (future waves): automatic IP/
Subsystem/System-Level VIP-based generation, OpenSpec/Intake, vPlan
generation, UVM TB generation, sequence/scenario generation,
scoreboard/checker/assertion generation, regression, failure triage/RCA,
functional coverage collection + hole closure, requirements/evidence
traceability, waiver handling, functional-coverage signoff/SIGNOFF_READY,
Knowledge Brain full operational integration, the ExecutionService
architecture, location independence + developer/deployment-copy modes,
USB Golden Qualification, and PCIe Zero-Core-Change genericity
qualification.

**Explicit, binding for this M1 report**: `M1_IS_FINAL_PRODUCT = NO`,
`M1_CAPABILITY_GATE = V50_BASELINE_PRESERVATION`,
`FINAL_CAPABILITY_GATE = STRICT_SUPERSET_OF_ALL_APPROVED_SOURCES`. No
final migration/product completion may be claimed before
`CANONICAL_CAPABILITY_STRICT_SUPERSET = PASS`. This correction does not
expand M1's own implementation scope -- M1 continues exactly as already
planned (bootstrap + v50 baseline qualification only).

## How this relates to already-established governance

- Consistent with, and a sharper restatement of, the existing
  `NEW_CANONICAL_L5_DGVA = MAXIMUM VERIFIED CAPABILITY UNION (PARENT, V50)`
  principle from the dual-repo consolidation pivot -- adds the explicit
  "strict operational capability **superset**" framing (never merely
  equal to the union; genuinely new canonical-platform capability is also
  required) and names the concrete end-to-end verification capability
  the platform must ultimately deliver (generate -> execute -> close
  coverage -> trace -> sign off, at IP/Subsystem/System-Level).
- "Resolving source defects and semantic conflicts" is exactly what the
  already-approved `M5_N_WAY_CAPABILITY_SEMANTIC_MERGE` policy
  (`M0_6_N_WAY_MERGE_POLICY.md`) and the per-input dispositions in
  `M0_5_MIGRATION_INPUT_REGISTRY.csv` exist to do -- this statement does
  not introduce a new mechanism, it names the standard those mechanisms
  are held to.
- Governs completion criteria for M3 (Parent capability migration), M4/M5
  (worktree capability migration + N-way semantic merge), and the later
  Platform Upgrade / C6 waves -- none of which are in scope for M1.
