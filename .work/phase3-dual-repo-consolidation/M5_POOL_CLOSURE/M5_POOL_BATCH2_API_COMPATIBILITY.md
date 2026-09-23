# M5 Pool Closure — Batch 2 — API Compatibility

Per-public-symbol `PUBLIC_SIGNATURE_BREAK`/`RETURN_SCHEMA_BREAK`/
`CONFIG_SCHEMA_BREAK`/`PERSISTED_DATA_BREAK` check. All 8 modules were
`ABSENT` from canonical before this batch — there is no PRE-EXISTING
canonical public API for any of them to break. The compatibility question
this batch actually carries is therefore one-directional: does each new
module's real dependency on already-present canonical infrastructure
(`loop_telemetry.py`, `blackboard.py`, `protocol_capability.py`,
`engine.py`'s own event-emission set) hold, not whether this batch broke an
existing canonical consumer.

## New-module public API (no pre-existing canonical consumer to break)

| Module | PUBLIC_SIGNATURE_BREAK | RETURN_SCHEMA_BREAK | CONFIG_SCHEMA_BREAK | PERSISTED_DATA_BREAK |
|---|---|---|---|---|
| `l5dgva_gap_queue.py` | N/A (new) | N/A (new) | N/A (new) | N/A (new) |
| `l5dgva_workitem_projection.py` | N/A (new) | N/A (new) | N/A (new) | N/A (new) |
| `l5dgva_directive_registry.py` | N/A (new) | N/A (new) | N/A (new) | N/A (new) |
| `eight_engine_runtime_proof_matrix.py` | N/A (new) | N/A (new) | N/A (new) | N/A (new) |
| `engine_maturity_state.py` | N/A (new) | N/A (new) | N/A (new) | N/A (new) |
| `eight_engine_telemetry_rollup.py` | N/A (new) | N/A (new) | N/A (new) | N/A (new) |
| `l5dgva_directive_blackboard_work_queue.py` | N/A (new) | N/A (new) | N/A (new) | N/A (new) |
| `l5dgva_kc_extraction.py` | N/A (new) | N/A (new) | N/A (new) | N/A (new) |

`UNKNOWN_RUNTIME_CALLERS = 0` — every one of these 8 modules' canonical
callers was enumerated by grep before this batch's own commits (see
`M5_POOL_BATCH2_CALLER_SWEEP.csv`); each has either an internal caller
migrated in this same batch, or 0 canonical callers (disclosed, matching
the same 0/low-caller state each module already has in Parent).

## The one real compatibility QUESTION this batch answered: does canonical's existing infrastructure honor each new module's assumptions

| Existing canonical component | New module that depends on it | Compatibility finding |
|---|---|---|
| `loop_telemetry.read_events()` / `DEFAULT_EVENT_SCAN_LINES` | `eight_engine_runtime_proof_matrix.py`, `eight_engine_telemetry_rollup.py` | Compatible — reused unchanged, same reader `dashboard._tail_events()`/`platform_health.py` already share |
| `engine.py`'s own literal event-name emission set | `eight_engine_runtime_proof_matrix.py`'s `ENGINE_RULES` | **PARTIALLY compatible** — 7 of 8 `EngineRule`s' cited events confirmed present at re-grepped canonical line numbers; the 8th (`five_level_memory_engine`) required `MIGRATE_WITH_ADAPTATION` (5 of Parent's 8 signals real in canonical, 3 have zero producers) — see `M5_POOL_BATCH2_SOURCE_BEHAVIOR_MATRIX.csv` |
| `blackboard.Blackboard.write()`/`.read()` | `l5dgva_directive_blackboard_work_queue.py` | Compatible — `Blackboard.__init__` writes to `<root>/.dv-harness/blackboard` (`dv_harness/blackboard.py:12`), `write(t, value, source='', confidence='HIGH')`/`read(t, default=None)` shape confirmed identical to Parent's, independently re-verified by direct source read before migration, not assumed |
| `protocol_capability.PROTOCOL_CAPABILITIES` | `l5dgva_kc_extraction.py` | Compatible — `ProtocolCapability.protocol: str` / `.aliases: Tuple[str, ...] = ()` confirmed present at `dv_harness/protocol_capability.py:146,151`, exact shape the module's `_protocol_registry_tokens()` already assumes |
| `memory_router.route_and_store(root, record, cfg=None)` | `l5dgva_kc_extraction.py` (test-only, via the real end-to-end round trip test) | Compatible — signature confirmed at `dv_harness/memory_router.py:140`, real call in `test_record_is_genuinely_consumable_by_route_and_store` returns `destination="WORKING_MEMORY"` as expected |

`PUBLIC_SIGNATURE_BREAKS_UNRESOLVED = 0`.
`SOURCE_CAPABILITY_LOSS = 0` — every real Parent capability this batch
targeted (CAP-POOL-001/003/004/011) is now present in canonical with
byte-for-byte-preserved logic (chain-B modules, `engine_maturity_state.py`,
`eight_engine_telemetry_rollup.py`, `l5dgva_directive_blackboard_work_queue.py`,
`l5dgva_kc_extraction.py`) or a disclosed, evidence-grounded adaptation
(`eight_engine_runtime_proof_matrix.py`'s 5-signal `five_level_memory_engine`
rule, which changes zero observable behavior since the 3 dropped signals
could never have matched any real canonical event anyway).
