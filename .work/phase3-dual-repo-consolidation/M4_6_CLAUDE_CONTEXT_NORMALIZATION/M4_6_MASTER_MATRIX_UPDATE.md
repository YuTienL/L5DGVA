# M4.6 — Master Capability/Ownership Matrix Update

Applied directly to the existing authoritative matrices (no competing
matrix created, per the standing "extend, never duplicate" rule):
`.work/phase3-dual-repo-consolidation/M4_5_MASTER_RECONCILIATION/MASTER_CAPABILITY_STATUS_MATRIX.csv`
(48 rows, was 47) and `MASTER_WAVE_OWNERSHIP_MATRIX.csv` (47 rows, was
46). Both re-validated: 0 malformed rows, 0 duplicate
`CAPABILITY_ID`s.

## Changes made (S21)

| Capability | Field | Before | After | Justification |
|---|---|---|---|---|
| `CAP-M4.5-001` `TASK_SCOPED_GOVERNANCE_RETRIEVAL` | `CANONICAL_STATE`/`CONSUMED` | PARTIAL / not a live routing consumer | **OPERATIONAL** / YES | M4.6 made CLAUDE.md's own routing table the real, live consumer of the registry — 301 sections are now genuinely reached only through it. Not a rubber stamp: `test_claude_reference_graph.py` (10/10) is the evidence. |
| `CAP-M4.5-001` | `PRIORITY` | P1 | P2 | The live-routing gap this row tracked is closed; residual work (a non-CLAUDE.md-mediated automated call site) is lower priority. |
| `CAP-M4.5-005` `CHATGPT_PLANNING_OFFLOAD` | `PRIMARY_OWNER_WAVE` | M8 | **M7** | Explicit M4.6 S21 instruction. `CANONICAL_STATE` left unchanged (`NOT_PRESENT`) — **not marked operational**. |
| `CAP-M4.5-006` `CODEX_REVIEW_OFFLOAD` | `PRIMARY_OWNER_WAVE` | M8 | **M7** | Same. `CANONICAL_STATE` unchanged (`NOT_PRESENT`). |
| `CAP-M4.5-007` `STRUCTURED_AGENT_HANDOFF` | `PRIMARY_OWNER_WAVE` | M8 | **M7** | Same. `CANONICAL_STATE` unchanged (`PARTIAL`, review schema only). |
| `CAP-M4.5-010` `TOKEN_USAGE_OBSERVABILITY` | `PRIMARY_OWNER_WAVE` | M8 | **M7** | Same. `CANONICAL_STATE` unchanged (`PARTIAL`, Claude-only telemetry). |
| *(new)* `CAP-M4.6-001` `CLAUDE_ALWAYS_ON_CONTEXT_NORMALIZATION` | new row | — | `OPERATIONAL`, owner `M4.6`, `P1 (closed)` | This wave's own deliverable, recorded with real evidence refs. |

`MINIMUM_SUFFICIENT_CONTEXT` (`CAP-M4.5-002`): left `PARTIAL`, **not**
upgraded to `ENFORCED` — real improvement happened (301 sections no
longer load unconditionally), but no per-domain further-distillation
exists yet (`SUMMARY_PATH == FULL_SPEC_PATH` for all 6 new entries, see
`M4_6_TASK_SCOPED_ROUTING.md`), so the honest label stays `PARTIAL`.

## What was deliberately NOT changed

- No M7 capability's `CANONICAL_STATE` was touched — only
  `PRIMARY_OWNER_WAVE`, per the explicit "Do not mark M7 capabilities
  operational" instruction.
- `CHATGPT_INTEGRATION`/`CODEX_INTEGRATION`/`TOKEN_REDUCTION_MEASURED`
  truth values from M4.5 are unchanged (`HUMAN_MEDIATED_CHATGPT_HANDOFF`
  / `HUMAN_MEDIATED_CODEX_REVIEW` / `NO`) — restated as still current in
  `M4_6_FINAL_REPORT.md`, not re-audited from scratch this wave.
- No M5/M6/M7 work was started; this update only reassigns an owner
  label and adds one new, already-closed capability row.
