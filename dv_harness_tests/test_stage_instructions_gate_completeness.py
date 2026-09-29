"""Permanent, automated consistency check distilled from a real class of bug
found and fixed twice during live `dv-harness run-stage` runs this session
(commits cc5d396 for INTAKE, 358565c for DISCOVERY): a stage can be
registered in dv_harness/gates.py's STAGE_GATES with N required gate
scripts, while dv_harness/prompts.py's STAGE_INSTRUCTIONS for that same
stage never mentions some subset of those gate ids at all -- meaning no
agent, no matter how good its actual analysis is, can ever know it needs to
supply that gate's evidence block. Both real occurrences were confirmed
live: the agent produced genuinely thorough, evidence-grounded work and
still failed GATE_FAIL/MISSING_EVIDENCE identically across multiple retries,
because the missing gate name was never surfaced to it anywhere in its
prompt.

This is a STRUCTURAL/DOCUMENTATION completeness check, not a functional
one -- it only proves the gate's `gate_id` string literally appears
somewhere in that stage's instruction text (the same weak-but-necessary
check the real live failures demonstrated is sufficient to unblock an
agent: once told the gate exists, a competent agent supplies a real,
correct evidence block on the very next attempt, confirmed twice).

A full completeness audit run against the real STAGE_GATES/STAGE_INSTRUCTIONS
state on 2026-09-01 found 20 of 35 gated stages had at least one such gap
(100+ individual gate omissions total) -- far beyond the 2 this session's
real execution happened to hit. This test's job is to make sure that
number only ever goes to zero and stays there, instead of being
rediscovered one expensive real run at a time.
"""
from __future__ import annotations

from dv_harness.gates import STAGE_GATES
from dv_harness.models import Stage
from dv_harness.prompts import STAGE_INSTRUCTIONS


def _missing_gate_mentions() -> dict[str, list[str]]:
    gaps: dict[str, list[str]] = {}
    for stage in Stage:
        gate_tuples = STAGE_GATES.get(stage.value, [])
        if not gate_tuples:
            continue
        instr = STAGE_INSTRUCTIONS.get(stage.value, "")
        missing = [entry[0] for entry in gate_tuples if entry[0] not in instr]
        if missing:
            gaps[stage.value] = missing
    return gaps


def test_every_stage_gates_entry_is_mentioned_in_its_stage_instructions():
    gaps = _missing_gate_mentions()
    if gaps:
        detail = "\n".join(f"  {stage}: missing {ids}" for stage, ids in sorted(gaps.items()))
        raise AssertionError(
            "The following stages have STAGE_GATES-registered gates that "
            "STAGE_INSTRUCTIONS never mentions by name, so an agent has no "
            "way to know it must supply that gate's evidence block "
            "(confirmed live twice to cause identical GATE_FAIL/"
            "MISSING_EVIDENCE across multiple retries even with otherwise "
            "thorough, correct work):\n" + detail
        )


def test_every_gate_id_in_stage_gates_is_a_real_nonempty_string():
    # Cheap sanity guard for the completeness check itself: if a gate_id
    # were ever empty/malformed, the "in instr" substring check above could
    # trivially "pass" without meaning anything.
    for stage_value, gate_tuples in STAGE_GATES.items():
        for entry in gate_tuples:
            gate_id = entry[0]
            assert isinstance(gate_id, str) and gate_id.strip(), (
                f"malformed gate_id in STAGE_GATES[{stage_value!r}]: {entry!r}"
            )
