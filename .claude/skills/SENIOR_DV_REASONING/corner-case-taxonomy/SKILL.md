---
name: corner-case-taxonomy
description: Canonical facet-to-generator map for protocol corner case intelligence -- what each risk facet is, which SENIOR_DV_REASONING skill generates it, and how selected corners get ranked P0-P3 and linked to vPlan.
allowed-tools: Read Grep Glob Skill
---
# corner-case-taxonomy

Router/index for protocol-corner-case-intelligence-agent. Consult this table instead of enumerating generators inline in the agent file.

## Facets -> Generators

Reset -> reset-interruption-generator (assertion/deassertion during active/idle/error/recovery)
Power -> power-transition-generator (power-state transition x traffic/config)
Concurrency -> concurrency-corner-generator (multi-master/multi-channel/cross-feature, from actual DUT topology)
Ordering -> ordering-corner-generator (ordering/reordering/outstanding transactions)
Backpressure -> backpressure-corner-generator (sustained/intermittent flow-control pressure)
Resource Limit -> resource-exhaustion-generator (queue/FIFO/credit/tag/buffer saturation and recovery)
Boundary/Numeric Value -> boundary-value-generator (sizes/addresses/credits/counters/alignment min-max legal boundaries)
Timing -> timing-corner-generator (legal min/max windows, timeout boundaries, sequencing transitions -- CDC-specific evidence is NOT covered here; treat CDC as an open gap, do not assume covered)
Error/Fault -> error-injection-generator (legal/illegal/recoverable error injection with expected checking)
Recovery -> recovery-corner-generator (error/link/state recovery, retry, re-entry)
State Transition -> protocol-state-space-analyzer (high-risk reachable state transitions/interactions, generative, no brute force -- NOT fsm-transition-analyzer, which validates observed transitions against design/spec and belongs to the debug/RCA skill set)
Cross Feature -> cross-feature-interaction-generator (interactions among individually-legal features)
Cross Protocol -> cross-protocol-interaction-generator (System-Level mode only, across selected subsystem protocols)
Traffic Pattern -> none currently (GAP: no dedicated generator skill as of this audit; nearest partial coverage is concurrency-corner-generator's multi-master/channel shape -- do not claim this facet is covered until a dedicated skill exists or the gap is explicitly waived)

## Prerequisite (not a ranked facet)

protocol-feature-decomposer decomposes a protocol feature into states/transactions/config/timing/error/recovery dimensions BEFORE the generators above run. It is input preparation, not a corner-case source itself.

## Ranking (Iron Rule 149 / 230)

corner-case-risk-ranker is canonical for ranking generated corner cases into P0-P3 (see its SKILL.md for the exact rule). verification-risk-analyzer is a separate general-purpose P0-P3 ranker used elsewhere in the harness (e.g. debug/review flows) -- do not conflate the two; for corner-case selection, corner-case-risk-ranker is the entry point.

## Linking

corner-case-vplan-linker ties ranked/selected corners to vPlan requirements, tests, checkers/assertions/scoreboards and coverage. Iron Rule 230: required corner cases need an evidence-backed matrix, not just a list -- unlinked corners cannot signoff.
