# M4 — Closing the M3→M4 Deferred Capability

Per M3's own record (`M3_CAPABILITY_MIGRATION_RECORDS.md`), exactly one
capability was explicitly `DEFERRED_TO_M4`:

```
CAPABILITY_ID (pending): l5dgva_requirement_dependency_closure.py
SOURCE: Parent, dv_harness/l5dgva_requirement_dependency_closure.py
SOURCE_PATH DEPENDENCY: dv_harness.l5dgva_contract_registry (build_master_registry)
REASON M3 COULD NOT SAFELY MIGRATE: ModuleNotFoundError -- l5dgva_contract_registry.py
  not present in canonical.
```

## Investigation performed

Copied `l5dgva_contract_registry.py` into canonical to test the dependency
directly (not left as an assumption). Result: **8 of its own real tests
fail**, not with an import error, but with:

```
ValueError: L5DGVA contract chain did not verify as a byte-exact prefix
series; refusing to treat any single file as the union.
```

Root cause, fully traced: `l5dgva_contract_registry.discover_contract_files()`
recursively scans a real directory, `DEFAULT_L5DGVA_DIR = ROOT / "L5DGVA"`,
for the ~20+ dated `.md` files that make up the "L5DGVA governing-contract"
document corpus (V1 through V23, referenced throughout this session's own
project memory as "the L5DGVA audit program", ~1150 requirement items).
**This directory does not exist in canonical at all** — it is Parent-only,
untracked-vs-tracked status not yet determined, and represents a
*much larger* content-migration question (a ~20-document, multi-version
governing-contract corpus) than a schema/contract dependency gap M4 is
scoped to resolve.

- SCHEMA_DEPENDENCIES: none (pure filesystem + regex/AST parsing of `.md` text)
- CONTRACT_DEPENDENCIES: none beyond the document corpus itself
- REGISTRY_DEPENDENCIES: none
- EVENT_DEPENDENCIES: none
- BLACKBOARD_DEPENDENCIES: none
- CONFIG_DEPENDENCIES: `DEFAULT_L5DGVA_DIR` constant (repository-relative,
  location-independent in principle — the gap is content presence, not
  path design)
- TEST_DEPENDENCIES: `dv_harness_tests/test_l5dgva_contract_registry.py`
  (ported, 8/16 tests fail for the reason above)
- CANONICAL_TARGET: not assigned — see disposition below

## Disposition

**Not resolved by M4. Reassigned, not silently re-deferred to the same
wave.** This is not a schema/contract foundation gap M4 can close by
writing a contract — it is a genuinely new finding: whether/how to migrate
an entire ~20-document governing-contract corpus is an architectural
decision bigger than M4's scope (dependency/schema/contract closure), and
arguably bigger than M5's scope too (N-way *code* semantic merge). Recorded
here as an **open scope question for explicit future decision**, not
assigned a wave number, rather than forcing it into M5 by default.

`l5dgva_requirement_dependency_closure.py` itself remains **not migrated**
(its own 2 tests that exercise the real registry integration cannot pass
without the corpus decision above; its other tests, which don't touch the
registry, were not partially imported per this session's own standing
policy of not landing a file with known-red tests).

```
M3_DEFERRED_TO_M4_RESOLVED = 0
M3_DEFERRED_REDEFERRED = 1 (reassigned to an unscheduled, explicitly-flagged
                             future decision, not silently left as "M4" or
                             defaulted to "M5")
```

## Separately, a genuinely resolved M3-adjacent gap (not the formal M3→M4 item, but the same investigation surfaced it)

M3's Cohort 1 also removed `ipxact_register_import.py` (b7a, DUT-04) after
discovering a `RegisterFieldIR.__init__()` API gap (`enum_values` keyword
missing from canonical's `register_excel_extract.py`), deferring it to M5.
**This M4 wave resolved that gap for real** — see `M4_SCHEMA_CLOSURE.md` —
and `ipxact_register_import.py` is now migrated, tests 54/54 passing. This
was not itself the formal M3→M4 deferred item (M3 assigned it to M5, not
M4), but M4's own schema-closure work happened to unblock it, and leaving
it un-migrated now that it demonstrably works would be a real,
avoidable capability loss.
