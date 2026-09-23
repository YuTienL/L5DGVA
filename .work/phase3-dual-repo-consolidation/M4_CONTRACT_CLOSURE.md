# M4 — Contract Closure

Per instruction #18's Contract-First Rule: for every M5/M6 target where
possible, establish WHAT behavior must be preserved, WHAT data enters/exits,
WHAT state is mutated, WHAT evidence is produced, WHAT downstream consumer
exists, WHAT error states exist, WHAT compatibility behavior is required —
without performing the implementation merge itself.

## CAP-M4-001's real contract (the one fully closed this wave)

```
WHAT_ENTERS: RegisterFieldIR(name, bit_offset, bit_width, access_type,
             access_in_current_schema, reset_value, notes=None,
             enum_values=None)
WHAT_EXITS: RegisterFieldIR.to_dict() -- now includes "enum_values" key
            (raw int-keyed list, unchanged shape from the dataclass field)
WHAT_STATE_IS_MUTATED: none (RegisterFieldIR is a plain, immutable-by-
            convention dataclass; no persisted state)
WHAT_EVIDENCE_IS_PRODUCED: to_register_map_document()'s output document
            now carries enum_values (hex-string-formatted) on any field
            that has them, validated against the extended
            register_map.schema.json
WHAT_DOWNSTREAM_CONSUMER_EXISTS: dv_harness/ipxact_register_import.py
            (real, migrated this wave, CAP-M4-002)
WHAT_ERROR_STATES_EXIST: none new -- a field with no enumeratedValues
            container in its source XML gets enum_values=None, identical
            to today's behavior for every other optional field
WHAT_COMPATIBILITY_BEHAVIOR_IS_REQUIRED: every existing caller that never
            passes/reads enum_values is provably unaffected (44/44 +
            121/121 downstream-consumer tests unchanged)
```

## The 10 M5 targets and 7 M6 targets

Full per-target contract status (RESOLVED/PARTIAL/UNRESOLVED, with the
specific WHAT-question each status answers or leaves open) is recorded in
`M4_M5_PREREQUISITE_MATRIX.csv` and `M4_M6_CORE_PREREQUISITE_MATRIX.csv` —
not duplicated here to avoid two documents drifting out of sync. Headline:

- **Fully RESOLVED this wave or re-confirmed from prior waves**:
  `register_excel_extract.py` (schema), `memory_vault.py` (security
  contract, from M1), `create_environment.py` (defect contract, from M1),
  `loop_telemetry.py` (factual-claim re-verification, new this wave),
  `engine.py` (full 247-method contract, pre-existing from the Canonical
  Migration Audit, re-confirmed this wave against live canonical code),
  multi-agent orchestration interfaces (protected-input status,
  `M4_PROTECTED_INPUT_STATUS.md`).
- **PARTIAL** (the contract QUESTION is known and documented; the actual
  domain-judgment ANSWER is real M5/M6 behavior work, correctly not
  attempted here): `functional_coverage_signoff.py`,
  `design_source_inventory.py`, `cli.py`/`dashboard.py` (dispatch-mechanism
  decision), `lifecycle integration surfaces`.
- **UNRESOLVED this wave, disclosed, not investigated**: `env_manifest.py`,
  `vip_capability_extraction.py` (including its known breaking
  signature-change risk), `soc_environment_composer.py`,
  `amba_fabric_generator.py`.

## Why not all 10+7 were closed this wave

A real symbol-level `ast`-based diff (the technique `11_CORE_FILE_SYMBOL_MATRIX.csv`
already established and `M0_6_N_WAY_MERGE_POLICY.md` mandates for every M5
target) was performed for exactly one file this wave
(`register_excel_extract.py`, driven by a real, concrete, test-verified
blocker) rather than all ten pre-emptively, per the instruction's own
"M4 does NOT attempt to maximize migrated file count" framing and the time
budget available. This is a disclosed scope boundary, not a silent gap —
every UNRESOLVED row names exactly what investigation remains.
