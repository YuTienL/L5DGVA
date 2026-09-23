# M14 — Metric Definitions (registration only, no target numbers)

Per instruction: "Do not invent target performance numbers at this
stage." Every metric below has a name, a definition, a unit, and the
telemetry source it would eventually read from — never a numeric
target, threshold, or expected improvement percentage. Any such number
appearing in a future document before M14 produces real results would
violate Section 9 Claim Governance (`M14_PRODUCTIVITY_AND_EXPERTISE_
AMPLIFICATION_REQUIREMENTS.md`).

## Time-to-milestone family

| Metric | Definition | Unit | Future telemetry source |
|---|---|---|---|
| `TIME_TO_FIRST_RUN` | Wall-clock from task start to the first simulation/build attempt reaching a completed (pass or fail) result | minutes | build/sim timestamp events |
| `TIME_TO_FIRST_PASS` | Wall-clock from task start to the first fully passing test/regression run | minutes | regression evidence timestamps |
| `TIME_TO_COVERAGE_TARGET` | Wall-clock from task start to the task's own stated coverage goal being met | minutes | coverage progression events |
| `TIME_TO_SIGNOFF` | Wall-clock from task start to a real signoff artifact being produced | minutes | signoff/evidence events |

## Human/AI interaction family

| Metric | Definition | Unit | Future telemetry source |
|---|---|---|---|
| `DV_HUMAN_HOURS` | Total human (Junior DV) time actively spent on the task | hours | human-interaction timestamps |
| `AI_INTERACTION_TIME` | Total wall-clock time the AI system (Native Claude CLI or L5DGVA) spent actively working | minutes | AI interaction timestamps |
| `NUMBER_OF_AI_INTERACTIONS` | Count of distinct human-initiated turns/prompts to the AI system | count | AI interaction counts |
| `CONTEXT_REEXPLANATION_COUNT` | Count of times the human had to re-explain context the AI system had already been given (a session/context loss) | count | AI interaction counts + session-boundary events |
| `HUMAN_CLARIFICATION_COUNT` | Count of times the AI system asked the human a clarifying question | count | AI interaction counts (L5DGVA arm: `question_queue.py` records) |
| `MANUAL_CODE_FIX_COUNT` | Count of times the human manually edited AI-produced code/config rather than re-prompting the AI | count | human-interaction counts |

## Iteration-count family

| Metric | Definition | Unit | Future telemetry source |
|---|---|---|---|
| `BUILD_ITERATIONS` | Count of distinct build/elaboration attempts | count | build/simulation iteration events |
| `SIMULATION_ITERATIONS` | Count of distinct simulation run attempts | count | build/simulation iteration events |
| `RCA_ITERATIONS` | Count of distinct root-cause-analysis passes over a single failure before resolution | count | RCA iteration events |

## Verification-quality family

| Metric | Definition | Unit | Future telemetry source |
|---|---|---|---|
| `FUNCTIONAL_COVERAGE` | Functional coverage percentage reached at task completion | percent | coverage progression events |
| `CODE_COVERAGE` | Code (line/toggle/branch/condition) coverage percentage reached at task completion | percent | coverage progression events |
| `REQUIREMENT_COVERAGE` | Fraction of the task's own requirement set (vPlan items) with a passing traced test | percent | test/regression selection + traceability records |
| `BUG_DETECTION` | Count of real DUT/environment defects found during the task | count | evidence/signoff events |
| `ESCAPED_VERIFICATION_HOLES` | Count of real gaps found by an independent post-task review that the task itself missed | count | post-task review, not live telemetry |
| `TRACEABILITY_COMPLETENESS` | Fraction of produced artifacts with a complete requirement-to-test-to-evidence chain | percent | traceability records |
| `REPRODUCIBILITY` | Whether re-running the task's own regression from its recorded seed/config reproduces the same verdict | boolean/percent | regression selection + evidence events |
| `SIGNOFF_EVIDENCE_COMPLETENESS` | Fraction of the task's required signoff evidence fields actually populated (never fabricated) | percent | evidence/signoff events |

## Maintenance-specific family (used only by `EXISTING_VERIFICATION_ENVIRONMENT_MAINTENANCE`)

| Metric | Definition | Unit | Future telemetry source |
|---|---|---|---|
| `MAINTENANCE_CHANGE_TIME` | Wall-clock from a maintenance task's trigger (RTL/spec change, defect report) to a re-qualified environment | minutes | maintenance-change events (M10.5) |
| `REGRESSION_SELECTION_EFFICIENCY` | Ratio of tests actually re-run to the full regression set, for a change whose real impact was later confirmed fully covered by the selected subset | ratio | test/regression selection events |
| `USER_CUSTOMIZATION_PRESERVATION` | Whether a user's own prior manual customization survived the maintenance change unmodified (or was correctly, visibly merged) | boolean | maintenance-change events + `ARTIFACT_OWNERSHIP_REQUIREMENTS.md`'s ownership classes |
| `RE_SIGNOFF_TIME` | Wall-clock from a maintenance change landing to a new, valid signoff artifact | minutes | evidence/signoff events |

## Explicitly out of scope for this reconciliation

No metric above has a target value, pass/fail threshold, or expected
improvement percentage attached. No metric above has a producer module
implemented by this task. Wiring any of these into real telemetry is
M7–M13 work (see `M14_PRE_M13_TELEMETRY_REQUIREMENTS.md`), and even
then only as a non-invasive foundation — collection itself remains
inert (no arm comparison, no report) until M14 actually starts, which
happens only after M13 completes.
