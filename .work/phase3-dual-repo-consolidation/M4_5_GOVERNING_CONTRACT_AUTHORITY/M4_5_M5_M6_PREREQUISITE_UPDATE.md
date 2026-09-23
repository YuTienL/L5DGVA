# M4.5 — M5/M6 Prerequisite Recompute (post-contract-reconciliation)

Per instruction Section 12: recompute after contract reconciliation,
without executing anything.

```
M5_UNRESOLVED_FOUNDATION_PREREQUISITES = 8  (UNCHANGED)
M6_UNRESOLVED_FOUNDATION_PREREQUISITES = 2  (UNCHANGED)
```

## Why unchanged

This closure promoted **0** corpus clauses to Canonical contract status
(`M4_5_CANONICAL_CONTRACT_CANDIDATES.md`) and modified **0** production
files. Neither `M4_M5_PREREQUISITE_MATRIX.csv` nor
`M4_M6_CORE_PREREQUISITE_MATRIX.csv`'s own per-target contract questions
(`env_manifest.py`'s 44-fan-in merge, `vip_capability_extraction.py`'s
signature-break risk, the `cli.py`/`dashboard.py` dispatch decision, the
`ClarificationService` build, etc.) depend on anything this corpus
analysis touched — they are pre-existing, independently-scoped
engineering/decision items, re-confirmed present and unresolved by
direct recount against the live CSVs this wave (re-verified: M5 row-sum
= 8; M6 row-sum = 3 raw, reconciles to 2 after the documented
`cli.py`/`dashboard.py` shared-decision dedup, exactly matching
`M4_FINAL_REPORT.md`'s own stated total).

## Ownership breakdown (instruction's own explicit ask)

```
M5-owned (8): env_manifest.py N-way merge (1), vip_capability_extraction.py
  N-way merge (1), create_environment.py ARCH-01 (1),
  soc_environment_composer.py ARCH-03 (1), amba_fabric_generator.py
  ARCH-04/12 (1), functional_coverage_signoff.py judgment call (1),
  design_source_inventory.py contract question (1),
  l5dgva_contract_registry.py adaptation (1 -- NEW this wave, see
  M4_5_CONTRACT_REGISTRY_DISPOSITION.md; this is an ADDITIONAL real M5
  item this closure surfaced, not yet in the prior 8-item count --
  see note below)

M6-owned (2): cli.py/dashboard.py dispatch-mechanism decision (1,
  counted once), lifecycle.py integration wiring-point identification (1)

Other-wave-owned: none newly surfaced by this closure
```

## Disclosed addition, not silently folded in

The `l5dgva_contract_registry.py` adaptation work
(`M4_5_CONTRACT_REGISTRY_DISPOSITION.md`: `MIGRATE_WITH_ADAPTATION`) is
a **real, new M5-scoped item** this closure identified — parameterizing
`DEFAULT_L5DGVA_DIR` and the cache path to point at an external,
evidence-on-demand corpus location rather than assuming a local
`L5DGVA/` directory. It is listed here for transparency but **not added
to the `8` total above**, since `M4_M5_PREREQUISITE_MATRIX.csv` itself
was not edited this wave (per instruction: analysis/disposition only,
no execution) — the matrix update belongs to whichever wave next edits
that CSV for real, with this document as its evidence trail. Reporting
`M5_UNRESOLVED_FOUNDATION_PREREQUISITES = 8` above is therefore the
**unchanged, currently-recorded** figure, not a claim that exactly 8
M5-scoped items exist in total once this new one is folded in.
