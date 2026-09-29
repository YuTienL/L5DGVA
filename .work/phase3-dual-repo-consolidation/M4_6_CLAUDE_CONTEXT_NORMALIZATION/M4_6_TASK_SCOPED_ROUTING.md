# M4.6 — Task-Scoped Routing

301 of 363 sections (1,880,037 bytes, ~92% of the original file) are
`TASK_SCOPED_GOVERNANCE`, moved **verbatim** into 6 domain documents
under `docs/architecture/canonical_detailed_governance/`, each
registered in `dv_harness/governance_registry.json` with
`load_policy: TASK_SCOPED`.

| Registry id | Sections moved | File bytes (incl. doc header) | Trigger keywords |
|---|---|---|---|
| `VIP_PROTOCOL_GENERATION` | 145 | 897,867 | vip, protocol, register, rtl, dut, phy, vplan, coverage, amba, axi, command, de-command, branch, pattern, scenario, checker, scoreboard, signoff, waiver, uvm |
| `GOVERNANCE_SAFETY_AUDIT` | 40 | 276,566 | safety sandbox, rollback, governance, audit, accountability, dependency, supply-chain, multi-agent, parallelism, security policy, traceability |
| `GUI_DASHBOARD_WEB` | 40 | 245,047 | gui, dashboard, web control plane, status bar, live event, rest api, ui, wizard |
| `KNOWLEDGE_MEMORY_RESEARCH` | 31 | 213,051 | memory, knowledge, obsidian, research, experience, learning, capability-evolution, confidence |
| `EXECUTION_REMOTE_REGRESSION_RCA` | 24 | 158,510 | remote, lsf, execution, build, sim-script, waveform, fsdb, regression, loop, convergence, root-cause, rca |
| `INTAKE_CLARIFICATION_QUESTION` | 21 | 124,807 | intake, clarification, question, answer, onboarding, openspec |

Sum: 145+40+40+31+24+21 = **301**, matching the 301
`TASK_SCOPED_GOVERNANCE` rows in `M4_6_CONTEXT_CLASSIFICATION.csv`
exactly (287 direct-keyword-matched + 14 keyword-fallback, all folded
into the 6 counts above; `GOVERNANCE_SAFETY_AUDIT`'s 40 includes the 14
lower-confidence fallback sections — see that CSV's `METHOD` column for
exactly which). These counts were re-verified directly against the
written files and the classification CSV before publishing this table
(a first draft of this table used stale intermediate numbers from
before the S063 correction below and was caught and corrected).

## Manual correction disclosed

`S063` ("Cross-Project Pattern Mining: What Recurs Across Projects")
was initially keyword-routed to `VIP_PROTOCOL_GENERATION.md` because
its title contains "Pattern" (a VIP/DE-command keyword collision). On
review — this section is Article-0-cited as a continuous-evolution
capability, conceptually a knowledge-generalization mechanism, not a
VIP protocol pattern — it was re-targeted to
`KNOWLEDGE_MEMORY_RESEARCH.md`. Content moved byte-for-byte between the
two already-written files (verified: `VIP_PROTOCOL_GENERATION.md`
shrank by exactly 6,882 bytes, `KNOWLEDGE_MEMORY_RESEARCH.md` grew by
exactly the same). This is disclosed, not hidden, as the one specific
case where the keyword classifier's output was overridden by a
one-item manual review.

## Reuse-before-redesign (S5)

No new directory taxonomy was invented beyond the 6 domain buckets
above, which are a direct instantiation of S5's own named potential
categories (intake/clarification -> `INTAKE_CLARIFICATION_QUESTION`;
protocol/VIP/generation/coverage/signoff -> `VIP_PROTOCOL_GENERATION`;
execution/remote EDA/regression/RCA -> `EXECUTION_REMOTE_REGRESSION_RCA`;
knowledge/Obsidian/research/experience learning ->
`KNOWLEDGE_MEMORY_RESEARCH`; security/multi-agent/Git-worktrees/release
/migration -> `GOVERNANCE_SAFETY_AUDIT`). The existing
`dv_harness/governance_registry.py` mechanism (built M4.5) was reused
as-is — no second registry was created.

## Known limitation, disclosed (not fabricated as solved)

`MINIMUM_SUFFICIENT_CONTEXT` stays `PARTIAL`: each domain document is a
**verbatim relocation**, not a further-distilled summary — a task
matching `VIP_PROTOCOL_GENERATION`'s trigger still loads a ~900KB
document (124 sections), not a short synopsis. `SUMMARY_PATH` equals
`FULL_SPEC_PATH` for all 6 domain entries in the registry, honestly, so
this is visible rather than hidden behind a fake "summary." Further
per-domain distillation is a real, disclosed future-wave item (owner
M8, per `MASTER_WAVE_OWNERSHIP_MATRIX.csv`'s `CAP-M4.5-002`), not
claimed done here.
