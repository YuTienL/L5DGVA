# M1 — Knowledge Brain Preservation Inventory

Per instruction #10. Real, fresh re-verification (file presence, line counts,
dedicated test-file presence, real CLI-wiring grep) — not a re-assertion of
this session's own pre-compaction summary, though the summary's module list
turned out accurate. **M1 does not redesign or fully operationalize this
system; full integration is M8.** Classification vocabulary per instruction:
`IMPLEMENTED` / `WIRED` / `TRIGGERED` / `CONSUMED` / `OBSERVED` / `TESTED`.

## Module inventory (all 17 confirmed present in this canonical repo, cloned unmodified from v50 HEAD)

| Module | Lines | Dedicated test file | CLASSIFICATION |
|---|---|---|---|
| `memory.py` | 1184 | none found by this naming convention | IMPLEMENTED |
| `memory_router.py` | 1197 | none found by this naming convention | IMPLEMENTED |
| `memory_vault.py` | 1812 | `test_memory_vault.py` | IMPLEMENTED, TESTED |
| `memory_doctor.py` | 338 | `test_memory_doctor.py` | IMPLEMENTED, **WIRED** (`dv-harness memory doctor`, confirmed `cli.py:1978`/`6090`; also delegated-into by the new `dv-harness doctor` in M1), TESTED |
| `memory_cli.py` | 105 | none found by this naming convention | IMPLEMENTED, WIRED (backs the `memory` subcommand family, `cli.py:1902`) |
| `memory_dedup.py` | 242 | `test_memory_dedup.py` | IMPLEMENTED, TESTED |
| `memory_security.py` | 305 | `test_memory_security.py` | IMPLEMENTED, **CONSUMED** (real caller: `memory_vault.py`'s `redact_note_content()` call before every write — confirmed in the M1 security-preservation comparison), TESTED |
| `memory_lineage.py` | 818 | `test_memory_lineage.py` | IMPLEMENTED, TESTED |
| `memory_artifact_policy.py` | 216 | none found by this naming convention | IMPLEMENTED |
| `memory_quality_policy.py` | 546 | `test_memory_quality_policy.py` | IMPLEMENTED, TESTED |
| `memory_buffer_arch_extraction.py` | 552 | `test_memory_buffer_arch_extraction.py` | IMPLEMENTED, TESTED |
| `knowledge_center.py` | 584 | `test_knowledge_center.py` | IMPLEMENTED, **WIRED** (`KnowledgeCenterClient` imported/used at multiple real `cli.py` call sites: `4769`, `5514`, `5516`, plus its own `knowledge-center status` subcommand at `778`), TESTED |
| `knowledge_conflict_resolver.py` | 418 | `test_knowledge_conflict_resolver.py` | IMPLEMENTED, TESTED |
| `design_knowledge_correlation.py` | 593 | `test_design_knowledge_correlation.py` | IMPLEMENTED, TESTED |
| `design_knowledge_output_package.py` | 812 | `test_design_knowledge_output_package.py` | IMPLEMENTED, TESTED |
| `dut_knowledge_graph.py` | 735 | `test_dut_knowledge_graph.py` | IMPLEMENTED, TESTED |
| `verification_knowledge_graph.py` | 608 | `test_verification_knowledge_graph.py` | IMPLEMENTED, TESTED |

13 of 17 have a dedicated test file by this exact naming convention; the
remaining 4 (`memory.py`, `memory_router.py`, `memory_cli.py`,
`memory_artifact_policy.py`) may still be exercised indirectly through other
test files (e.g. `test_memory_tier_completion.py`,
`test_memory_write_guard_and_job_evidence.py` both reference `vchost`/`vchop`
and memory-tier logic per the earlier grep in this same session) — not
independently re-confirmed here, disclosed as an open item rather than
assumed covered.

## Five-tier Memory + KnowledgeService

- **Tier 1 Working / Tier 2 Job / Tier 3 Project / Tier 4 Engineering /
  Tier 5 Organizational**: `memory_router.route_memory()` /
  `promote_to_organizational()` implement the tier model and its admission
  gates (per this project's own `CLAUDE.md` "Engineering Memory Policy"
  section, itself sourced from `memory_router.py`'s real code) — IMPLEMENTED,
  not independently re-derived from scratch in this inventory pass (per the
  "do not recompute already-established evidence" rule); CLAUDE.md's own
  citations of `engineering_admission_gate()` / `organizational_admission_gate()`
  were spot-checked present via the earlier `grep`, not re-read function-by-function here.
- **KnowledgeService**: no module literally named `knowledge_service.py`
  exists in this v50-derived checkout — the closest real equivalent is
  `knowledge_center.py` (a client to an external Knowledge Center server, a
  different concept — cross-team knowledge sharing, not the in-process
  5-tier memory service). Honest finding: **no unified `KnowledgeService`
  facade module exists yet** in this baseline; the 5-tier memory system is
  accessed via `memory_router.py`/`memory.py` directly.

## Obsidian integration

- **Obsidian adapter**: `memory_vault.py`'s `ObsidianAdapter` class —
  IMPLEMENTED, TESTED (`test_memory_vault.py`).
- **Obsidian CLI mechanism**: `memory_vault.detect_obsidian_cli()` — real,
  confirmed working end-to-end via `dv-harness doctor`'s
  `OBSIDIAN_CLI_STATUS` field (returned `AVAILABLE` on this machine during
  M1's own doctor runs) — IMPLEMENTED, WIRED, OBSERVED (a live, real
  detection result was actually produced on this machine, not merely coded).
- **Vault configuration**: `memory_vault.resolve_vault_path()` — confirmed
  location-independent (reads `.dv-harness/config.json`'s `memory.vault_path`,
  honest empty fallback, no hardcoded default) — IMPLEMENTED, WIRED, OBSERVED
  (via `dv-harness doctor`'s `OBSIDIAN_VAULT_CONFIGURATION` field).

## Knowledge ingest / retrieval / promotion / provenance / cross-session recall / pending-offline

Per instruction's own explicit caveat ("a successful Obsidian search alone
does NOT qualify the subsystem as operational" — real operational proof
requires persist→retrieve→applicability-check→agent-consumes→
affects-real-decision→evidence-recorded): **none of these six end-to-end
behaviors were exercised in M1** — M1 performed no real debugging/engineering
session that would produce a genuine ingest→retrieve→consume→decision chain.
Honest classification for all six: **IMPLEMENTED only** (the code paths exist
and were already unit-tested in their own dedicated test files listed above),
**not TRIGGERED, not CONSUMED, not OBSERVED** as a real end-to-end chain
during M1. This is the expected, correct M1 boundary — full operational
integration proof is explicitly M8's job, not M1's.

## Summary

```
KNOWLEDGE_BRAIN_PRESERVED = YES (all 17 modules present, unmodified, cloned
                                  from v50 HEAD; 13/17 independently tested
                                  by dedicated test file)
KC_ENGINE_PRESERVED = YES (knowledge_center.py present, WIRED, TESTED --
                            though "KC Engine" here means the external
                            Knowledge Center client, not a unified
                            KnowledgeService facade, which does not exist
                            in this baseline -- disclosed above)
M1_M5_MEMORY_PRESERVED = YES (memory_router.py/memory.py present, tier
                               model documented in this project's own
                               CLAUDE.md, not independently re-derived here)
OBSIDIAN_CAPABILITY_PRESERVED = YES (adapter + CLI detection + vault-path
                                      resolution all present, WIRED, and
                                      OBSERVED live via dv-harness doctor)
OBSIDIAN_CLI_ADAPTER = IMPLEMENTED, WIRED, OBSERVED
OBSIDIAN_VAULT_PATH_HARDCODED = NO (resolve_vault_path() confirmed
                                     config-driven with an honest empty
                                     fallback, no hardcoded path)
OBSIDIAN_OPTIONAL_DEGRADED_MODE = YES (dv_doctor.py's OBSIDIAN_CLI_STATUS
                                        reports KNOWLEDGE_BACKEND_DEGRADED,
                                        never a hard failure, when the CLI
                                        is unavailable)
KNOWLEDGE_PENDING_QUEUE = IMPLEMENTED only (not exercised in M1)
KNOWLEDGE_RETRIEVE = IMPLEMENTED only (not exercised in M1)
KNOWLEDGE_PROMOTION = IMPLEMENTED only (not exercised in M1)
KNOWLEDGE_PROVENANCE = IMPLEMENTED only (not exercised in M1)
CROSS_SESSION_RECALL = IMPLEMENTED only (not exercised in M1)
AGENT_KNOWLEDGE_CONSUMPTION = IMPLEMENTED only (not exercised in M1)
```

Full operational integration (real persist→retrieve→applicability-check→
agent-consumes→affects-real-decision→evidence-recorded proof) remains **M8**,
not attempted here.
