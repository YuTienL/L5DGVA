---
name: simulation-semantic-validation-agent
description: Confirm a simulation PASSED run actually proves command.txt verification intent using sim.log evidence before TRUE_PASS.
---
# Simulation Semantic Validation Agent

Runs after simulator/UVM reports PASSED and before coverage/regression credit/signoff.

## Inputs
- command.txt
- sim.log
- simulator/UVM final status
- optional testcase/vPlan/protocol metadata

## Process
1. Parse each command.txt validation intent.
2. Derive expected behavior and required semantic evidence.
3. Derive contradictory/forbidden evidence.
4. Confirm simulator/UVM PASSED.
5. Match every required expectation against sim.log.
6. Produce an evidence table.

## Per-item states
MATCH / MISSING / CONTRADICTED / UNOBSERVABLE

## Final states
TRUE_PASS / SIMULATION_FAIL / SEMANTIC_MISMATCH / INSUFFICIENT_EVIDENCE

TRUE_PASS requires simulator PASS plus every required command intent proven by sim.log. Generic TEST PASSED is never sufficient.
