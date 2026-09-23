# M4.5 — `l5dgva_contract_registry.py` Disposition

```
DISPOSITION = MIGRATE_WITH_ADAPTATION (adaptation work deferred to M5)
```

## Re-evaluated against the now-frozen authority model

Directly re-read `D:\DV\Task\DV_Agent_Harness_L5\dv_harness\l5dgva_contract_registry.py`
(Parent, read-only) in full and **ran its real, unmodified functions**
against the live corpus this wave (`build_master_registry()`,
`verify_chain()`, `detect_master_registry_value_conflicts()`) —
evidence, not a re-assertion of the earlier M4 finding.

## Correction of an earlier finding

M4's own finding (`M4_M3_DEFERRED_CLOSURE.md`) reported: *"real finding:
`l5dgva_contract_registry.py` depends on a real `L5DGVA/` directory...
absent from canonical entirely"* and (per the session's own prior
summary) that migrating it raised `ValueError: L5DGVA contract chain
did not verify as a byte-exact prefix series`.

**Re-running the module's own `verify_chain()` against the real Parent
corpus this wave produces a clean result**: `22/22` links verified,
chain head = `L5_DGVA_v23_...md`, **zero** value conflicts. The module's
chain-verification logic is not broken — the earlier `ValueError` almost
certainly fired because canonical has **no `L5DGVA/` directory at all**
(`discover_contract_files()` would find zero files, so
`verify_chain()` trivially has no chain to verify, and
`build_master_registry()` raises exactly the quoted `ValueError` on an
empty governing-file list) — not because the real 25-document corpus
itself is internally inconsistent. This is disclosed as a correction to
the earlier characterization, not a silent overwrite of it.

## Why not `MIGRATE_AS_IS`

The module hardcodes `DEFAULT_L5DGVA_DIR = ROOT / "L5DGVA"` — it assumes
the corpus is a local directory under the repo root. Migrating it
byte-for-byte to canonical would either (a) do nothing useful (no such
directory will ever exist in canonical, per the frozen decision that the
corpus stays `SOURCE_EVIDENCE_ONLY`/`EVIDENCE_ON_DEMAND`, never
committed), or (b) tempt a future caller to actually create an
`L5DGVA/` directory in canonical just to make the module work — directly
violating "Do not append the corpus to CLAUDE.md" / the broader
"never committed" intent.

## Why not `SUPERSEDED` or `DEFER_TO_M5` outright

The module's core techniques are real, valuable, and exactly what this
M4.5 closure just reused successfully: byte-exact chain verification,
confidence-tiered requirement extraction (`exact` vs `heuristic`),
stable requirement IDs, and version-block provenance. Nothing else in
this program does this. Discarding it (`SUPERSEDED`) would be a real
capability loss with no replacement; deferring it wholesale
(`DEFER_TO_M5`) would understate that its core logic was **already
proven correct against the real corpus this session**, not merely
theorized.

## The real adaptation needed (M5-scoped, not done here)

1. `l5dgva_dir` (and `cache_path`) must become caller-supplied
   parameters with no canonical-repo-relative default — the corpus
   lives only at its external, evidence-on-demand location
   (`dv_harness/governance_registry.json`'s `L5DGVA_GOVERNING_CONTRACT_CORPUS`
   entry's `external_source_path`).
2. The module must be invoked strictly as an on-demand evidence-analysis
   tool (e.g. a future `dv-harness governing-contract analyze --source
   <path>` verb), never assuming local presence — consistent with
   `TOKEN_CLASS: SOURCE_EVIDENCE_ONLY` and "never loaded wholesale even
   once migrated."
3. `build_master_registry_cached()`'s cache-write path
   (`.dv-harness/l5dgva_contract_registry_cache.json`) needs the same
   external-path treatment — it must not assume a local `L5DGVA/` tree
   to fingerprint.
4. The persisted `.dv-harness/l5dgva_contract_registry_cache.json` this
   module would otherwise write is itself derived evidence (a cache of
   corpus analysis, not the corpus), so it can safely live in canonical
   once (1)-(3) are done.

## Not executed this wave

Per instruction Section 12 ("Do not execute [prerequisites]") and the
overall M4.5 closure scope (analysis/disposition only): this adaptation
is real, scoped, disclosed work for **M5**, not performed here. No
production code was modified as part of reaching this disposition.
