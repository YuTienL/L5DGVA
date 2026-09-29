# M4 — Schema Closure

## CAP-M4-001: `RegisterFieldIR.enum_values` schema field (register_excel_extract.py)

Real, executed schema closure — not just documented, actually landed with tests.

- **Gap**: b7a's `ipxact_register_import.py` (DUT-04) constructs
  `RegisterFieldIR(..., enum_values=[...])`; canonical's `RegisterFieldIR`
  dataclass had no such field (`TypeError: unexpected keyword argument`).
- **Canonical authority decision**: `PARENT_SUPERSET`-shaped —
  neither Parent's nor v50's own `RegisterFieldIR` had this field at the
  time of the M0/M0.5 audit; it originates from worktree `b7a`'s DUT-10
  capability (a different, larger capability than DUT-04, per
  `17_CANONICAL_MIGRATION_WAVES.md`'s M5 section: `register_excel_extract.py`
  + DUT-10 from `b7a`). Per instruction #6, chosen from **verified behavior
  and contracts**, not timestamp/size/preference: the field shape
  (`Optional[List[Dict[str, Any]]] = None`) was taken byte-identical from
  b7a's own dataclass definition, since that is the one real, evidenced
  shape any future consumer (DUT-04 today, DUT-10 in M5) actually
  constructs.
- **Schema change**: added `enum_values: Optional[List[Dict[str, Any]]] = None`
  to `RegisterFieldIR` (pure additive, default `None`, zero effect on any
  existing caller — proven, not assumed, by 2 new tests plus the full
  pre-existing 42-test suite passing unchanged).
- **`to_dict()`**: extended to include `enum_values` (needed by
  `ipxact_register_import.py`'s own CLI JSON output).
- **`register_map.schema.json`**: extended the `field` definition with an
  optional `enum_values` array property (`{value: "0x.." string, name}`,
  matching the document's own existing hex-string convention for
  `reset_value` — corrected once, from an initial integer-typed draft,
  after the real test showed the document format is a hex string, not
  a raw int). Optional property; a document that omits it remains valid.
- **`to_register_map_document()` bridge**: extended with a purely mechanical
  pass-through (`enum_values` copied into the field dict, hex-formatted,
  only when present) — no new judgment/decision logic, consistent with
  "M4 establishes the contract/schema M5 must implement" rather than
  performing the M5 behavior merge. What is explicitly NOT done: any of
  DUT-10's own Excel-driven enum-value *parsing* logic (that remains a
  real M5 N-way merge item for `register_excel_extract.py` + DUT-10).

```
CAPABILITY_ID = CAP-M4-001
CAPABILITY_DOMAIN = SCHEMA / DATA_MODEL
CANONICAL_TARGET_PATH = dv_harness/register_excel_extract.py, dv_harness/schemas/register_map.schema.json
CONSUMER = dv_harness/ipxact_register_import.py (real, migrated this same wave -- see below)
TESTS = dv_harness_tests/test_register_excel_extract.py (44/44, incl. 2 new),
        dv_harness_tests/test_ipxact_register_import.py (10/10)
DOWNSTREAM REGRESSION CHECK = test_env_manifest.py, test_register_rtl_trace.py,
        test_artifact_relationship_discovery.py, test_stage_progress_display.py
        (121/121, all consumers of the same schema file, unaffected)
```

## Consequence: `ipxact_register_import.py` (DUT-04, b7a) migrated for real

With the schema closed, `ipxact_register_import.py`'s own tests (previously
4/10 failing in M3) now pass 54/54 combined with `register_excel_extract.py`'s
suite. Migrated as:

```
CAPABILITY_ID = CAP-M4-002
CAPABILITY_NAME = IP-XACT register-map importer (DUT-04)
SOURCE_REPO = b7a worktree
SOURCE_HEAD = 7b2a65a4dc2d40d493451b409669c90ed0b3d9a5
SOURCE_PATH = dv_harness/ipxact_register_import.py
DEPENDENCIES = .register_excel_extract (RegisterFieldIR incl. enum_values,
  ExtractionResult, RegisterIR -- all now present/compatible)
CANONICAL_TARGET_PATH = dv_harness/ipxact_register_import.py
MIGRATION_ACTION = straight copy (the file itself needed zero adaptation --
  only its dependency's schema needed extending)
TESTS = dv_harness_tests/test_ipxact_register_import.py, 10/10 real pass
CANONICAL_OPERATIONALIZATION_AFTER_M4 = IMPLEMENTED, TESTED, not wired
  (no engine.py/cli.py consumer -- that remains a later wave)
```

## Foundation taxonomy classification (per instruction #5)

`RegisterFieldIR.enum_values` → **SCHEMA** + **DATA_MODEL** (a dataclass
field + its JSON Schema mirror). Real consumer confirmed:
`ipxact_register_import.py` (already migrated, not speculative). Not dead
infrastructure.
