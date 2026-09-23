# M5 Pool Closure — Batch 2 — Dependency Graph

START_HEAD = `0a00679fc2af90a1cf35d4dd61c907fc4ac63708`

Resolved from Batch 1's own committed `M5_POOL_CLOSURE_DEPENDENCY_GRAPH.md`
(not from memory), then independently re-verified against real Parent source
during this batch's own investigation. Two independent dependency chains,
not one flat list of four modules — Batch 1's graph named this correctly.

## Chain A — shared by CAP-POOL-001 and CAP-POOL-011

```
eight_engine_runtime_proof_matrix.py (ABSENT from canonical at batch start)
  <- engine_maturity_state.py          [CAP-POOL-001]
  <- eight_engine_telemetry_rollup.py  [CAP-POOL-011]
```

`eight_engine_runtime_proof_matrix.py` itself depends only on `loop_telemetry.py`
(PRESENT in canonical, unchanged). Migrated **WITH ADAPTATION**: Parent's
`five_level_memory_engine` `EngineRule` names 8 `EngineSignal`s; canonical's
independently-evolved `engine.py` was grepped directly and genuinely emits
only 5 of those 8 memory-promotion event names
(`ARCHITECTURE_DISCOVERY_PROMOTED`/`VERIFICATION_ARCHITECTURE_TOPOLOGY_PROMOTED`/
`DE_BASELINE_REPRODUCTION_PROMOTED` have zero producers — confirmed via grep,
zero matches for all three). The `signals` tuple was reduced to the 5 real,
confirmed names; every other `EngineRule`'s `evidence_refs` line number was
re-derived against canonical's own `engine.py` (re-grepped for this
migration), never Parent's own line numbers.

`engine_maturity_state.py` and `eight_engine_telemetry_rollup.py` both
hardcode zero event names of their own — they read only
`EngineProofRow`/`ENGINE_RULES` fields already computed by the (now adapted)
proof-matrix module — so the adaptation propagated automatically with no
separate edit in either target module.

## Chain B — shared by CAP-POOL-003 and CAP-POOL-004

```
l5dgva_gap_queue.py (ABSENT at batch start, self-contained: stdlib only)
  <- l5dgva_workitem_projection.py (ABSENT at batch start)
       <- l5dgva_directive_registry.py (ABSENT at batch start)
            <- l5dgva_directive_blackboard_work_queue.py  [CAP-POOL-003]
                 (also depends directly on blackboard.py, PRESENT in canonical,
                  independently verified write()/read() shape-compatible)
  <- l5dgva_kc_extraction.py  [CAP-POOL-004]
       (also depends directly on protocol_capability.py — see disclosure below)
```

All three chain-B dependency modules ported **verbatim** (byte-for-byte
unchanged logic/text) — none of the three hardcodes an `engine.py` event name
or any other canonical-specific fact that could have diverged.

## Disclosed new dependency (found during this batch's own sweep, not in Batch 1's graph)

Batch 1's dependency graph named `l5dgva_gap_queue.py` as CAP-POOL-004's only
dependency. This batch's own investigation found a second, real dependency:
`l5dgva_kc_extraction.py`'s `_protocol_registry_tokens()` imports
`protocol_capability.PROTOCOL_CAPABILITIES`. Independently verified before
migration: canonical's `ProtocolCapability` carries `protocol: str` and
`aliases: Tuple[str, ...] = ()` (`dv_harness/protocol_capability.py:146,151`)
— the exact shape the module already assumes. `protocol_capability.py` itself
required no migration (already present, unchanged, in canonical). Disclosed
here as new evidence this batch's own sweep produced, not silently absorbed
as if Batch 1 had already known it.

## Classification (per this batch's own instruction vocabulary)

| Module | Classification |
|---|---|
| `l5dgva_gap_queue.py` | `READY` (self-contained, no dependency) |
| `l5dgva_workitem_projection.py` | `READY` once `l5dgva_gap_queue.py` migrated |
| `l5dgva_directive_registry.py` | `READY` once `l5dgva_workitem_projection.py` migrated |
| `eight_engine_runtime_proof_matrix.py` | `READY` (`loop_telemetry.py` already `CANONICAL_ALREADY_SUPERSET`-equivalent, i.e. present+compatible) |
| `engine_maturity_state.py` [CAP-POOL-001] | `READY` once chain A migrated |
| `eight_engine_telemetry_rollup.py` [CAP-POOL-011] | `READY` once chain A migrated |
| `l5dgva_directive_blackboard_work_queue.py` [CAP-POOL-003] | `READY` once chain B migrated (`blackboard.py` already `CANONICAL_ALREADY_SUPERSET`-equivalent) |
| `l5dgva_kc_extraction.py` [CAP-POOL-004] | `READY` once `l5dgva_gap_queue.py` migrated (`protocol_capability.py` already `CANONICAL_ALREADY_SUPERSET`-equivalent) |

`UNKNOWN_DEPENDENCIES = 0` — every dependency of every one of the 8 modules
in this batch's scope was independently confirmed present/compatible or
migrated in this batch; no module was migrated against an assumed-but-
unverified dependency.

## Actual migration order (dependency-ordered commits, canonical/m4-dependency-closure)

1. `a55735a` — chain B: `l5dgva_gap_queue.py` + `l5dgva_workitem_projection.py` + `l5dgva_directive_registry.py`
2. `f4f165a` — chain A: `eight_engine_runtime_proof_matrix.py` (MIGRATE_WITH_ADAPTATION)
3. `ec27675` — CAP-POOL-001 (`engine_maturity_state.py`) + CAP-POOL-011 (`eight_engine_telemetry_rollup.py`)
4. `303a58d` — CAP-POOL-003 (`l5dgva_directive_blackboard_work_queue.py`)
5. `dd6b90d` — CAP-POOL-004 (`l5dgva_kc_extraction.py`)
