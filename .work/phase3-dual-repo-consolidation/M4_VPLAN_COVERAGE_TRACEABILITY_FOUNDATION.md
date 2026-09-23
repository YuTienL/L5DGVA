# M4 — vPlan / Coverage / Traceability Foundation

Per instruction #14. Real, on-disk presence check in canonical for the
Requirement <-> vPlan Feature <-> Test/Scenario <-> Checker/Scoreboard/
Assertion <-> Coverage <-> Regression Result <-> Evidence <-> Waiver <->
Signoff chain.

| Link | Real module present | Status |
|---|---|---|
| Requirement | `requirement_contract.py` | PRESENT |
| vPlan Feature | `vplan_artifact.py` | PRESENT (a confirmed `SEMANTIC_CONFLICT` file per `10_SHARED_FILE_SEMANTIC_DIFF.md`'s original 24-candidate pass, later reclassified as a false positive -- a strict superset relationship, not a real conflict) |
| Test / Scenario | `golden_scenario.py` (identical Parent/v50) | PRESENT |
| Checker / Scoreboard / Assertion | `verification_knowledge_graph.py` (TEST/REQUIREMENT/COVERAGE/ROOT_CAUSE linking, per CLAUDE.md's own Module Index) | PRESENT |
| Coverage | `coverage_analysis.py`, `coverage_closure_action_utility.py` | PRESENT |
| Regression Result | `regression_reporter.py`, `regression_tiers.py` (regression_reporter.py confirmed `identical`; regression_tiers.py `diverged`, not investigated this wave) | PRESENT |
| Evidence | `evidence_db.py`, `evidence_provenance.py` (evidence_db.py `identical`; evidence_provenance.py `diverged`) | PRESENT |
| Waiver | `waiver_store.py` (`identical`) | PRESENT |
| Signoff | `signoff_export.py` (`diverged`, not investigated this wave) | PRESENT |

## Missing foundational contracts

None found this wave — every named link in the chain has a real, present
canonical module. The `diverged` files noted above (`vplan_artifact.py`,
`regression_tiers.py`, `evidence_provenance.py`, `signoff_export.py`)
represent real M5-territory reconciliation work (Parent vs. v50 symbol-level
differences), not a MISSING foundation — the contract/schema exists on both
sides, they merely need N-way reconciliation, which is explicitly out of
M4's scope (M4 establishes what M5 must implement; it does not perform the
implementation itself).

```
VPLAN_COVERAGE_TRACEABILITY_FOUNDATION = READY
  (every link in the chain has a present canonical module; several are
   `diverged` and await their own M5 symbol-level reconciliation, which
   is a real, disclosed follow-on, not a missing-foundation gap)
```

No M10 signoff flow implemented or implied by this check, per instruction.
