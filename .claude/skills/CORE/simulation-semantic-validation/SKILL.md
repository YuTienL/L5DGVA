---
name: simulation-semantic-validation
description: Parse command.txt verification intent and prove each required behavior from sim.log after simulator PASSED.
---
# Simulation Semantic Validation

Flow: command.txt -> intent extraction -> simulator PASS -> sim.log semantic match -> TRUE_PASS.

Rules:
- Generic PASSED/end-of-sim does not satisfy feature-level intent.
- Required evidence must be present.
- Contradictory evidence blocks TRUE_PASS.
- Unobservable required behavior returns INSUFFICIENT_EVIDENCE.
- Only TRUE_PASS gets regression/signoff credit.
