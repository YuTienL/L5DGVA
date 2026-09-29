# M14 — Benchmark Fairness Policy

Status: `DEFINED`, roadmap-only. No benchmark task has been run under
this policy. This document is the policy itself, not an execution
record.

## 1. Equivalence requirements

Both benchmark arms (`A = Junior DV + Native Claude CLI`,
`B = Junior DV + L5DGVA`) must receive **equivalent**:

| Dimension | Equivalence requirement |
|---|---|
| DUT | Same RTL, same revision/SHA |
| Spec | Same specification documents, same revision |
| Requirements | Same requirement set (vPlan or equivalent), same revision |
| Starting project state | Same starting repository/environment state — for the `EXISTING_VERIFICATION_ENVIRONMENT_MAINTENANCE` level, the same pre-change qualified environment |
| EDA environment | Same simulator/tool versions, same license pool, same host class |
| VIP availability | Same VIP package/version available to both arms |
| Compute resources | Same CPU/memory/license budget, same job-queue priority |
| Time window | Same wall-clock time budget (or explicitly unbounded for both) |
| Task definition | Same task description, same acceptance criteria, given to both a Junior DV in the same role |

**Any unavoidable difference between the two arms must be recorded
explicitly** in the benchmark run's own evidence, never silently
absorbed into a result. A benchmark run that cannot establish one of
the rows above as equivalent is not a valid comparison and must be
disclosed as such, not reported as a clean result.

## 2. What is and is not a fair asymmetry

**Never restrict Arm A artificially.** Native Claude CLI in Arm A must
be used exactly as a Junior DV would use it in real practice — full
tool access, full context window, no deliberately crippled prompt or
withheld capability designed to make Arm A look worse.

**Never give Arm B hidden source information Arm A lacks**, with one
explicit, bounded exception: capability or knowledge that is
**legitimately part of the L5DGVA product being evaluated** — its
generators, its governance rules, its memory/knowledge system, its
methodology skills, its telemetry. That is not an unfair advantage; it
is the very thing M14 exists to measure the value of. The line: if a
capability is something a Junior DV using Arm A *could* also have
access to (public documentation, the DUT's own spec, standard EDA
tooling), it must be equally available to Arm A. If a capability only
exists because it was purpose-built as part of the L5DGVA product
(e.g. its memory-backed institutional knowledge, its automated
generators, its governance gates), it stays exclusive to Arm B — that
asymmetry is the product being tested, not a fairness violation.

## 3. Quality-parity requirement (`BENCHMARK_QUALITY_PARITY_GATE`)

M14 must never declare Arm B a "win" on productivity metrics
(Section 3 of `M14_METRIC_DEFINITIONS.md`) alone. A valid M14 result
requires productivity metrics to be reported **together with** the
verification-quality family (functional/code/requirement coverage, bug
detection, escaped holes, traceability completeness, reproducibility,
signoff evidence completeness) and, for maintenance tasks, the
maintenance-specific family (user customization preservation,
re-signoff time). A result where Arm B is faster but has materially
worse verification-quality metrics than Arm A is **not** a successful
L5DGVA result under this policy — it must be reported as a genuine
trade-off, not a win.

This gate is registered as its own capability
(`CAP-M14-005` `BENCHMARK_QUALITY_PARITY_GATE`, status `DEFINED`) so a
future M14 benchmark-runner implementation has a named, checkable
requirement to satisfy rather than a policy paragraph a report author
could forget to apply.

## 4. Junior DV role definition (for both arms)

Both arms are staffed by a DV engineer at the same junior experience
level — defined for benchmark purposes as: DV fundamentals known,
UVM/protocol-specific and this-project's-own-methodology expertise not
yet developed. This document does not define a numeric years-of-
experience threshold (that would be a target number, prohibited by
Section 9 Claim Governance in the parent requirements document) —
determining the exact staffing/screening criteria for a real Junior DV
participant is deferred to the M14 execution wave itself.
