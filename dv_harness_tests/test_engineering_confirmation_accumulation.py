"""The Engineering -> Organizational confirmation path, proven reachable from
the REAL production writers (2026-09-04, gap-close-obsidian-memory Phase 4+5).

`memory_router.promote_to_organizational()`'s third gate is
`confirmation_count >= ORGANIZATIONAL_MIN_CONFIRMATIONS` -- CLAUDE.md's "a
second independent run re-deriving the same root_cause/protocol". The only
authorized writer of that field is `MemoryGC.confirm()`, which
`_add_or_confirm_engineering()` fires when a later record matches an ACTIVE
engineering record on (protocol, root_cause).

That mechanism was real, correct and tested -- but only ever exercised by
tests calling `MemoryGC.confirm()` DIRECTLY (see
`organizational_promotion_fixture.seed_promotable_engineering_record`). Both
real production writers read `protocol` off a gate evidence block, and
neither `experience_knowledge_gate`'s nor `root_cause_evidence_gate`'s
`JUDGMENT_FIELDS` list includes `protocol`, so no gate required or judged it:
in the real on-disk store it was None on 30 of 31 engineering records, every
match returned None, and each re-derivation minted a fresh record. The
organizational tier was unreachable by its own intended organic route.

These tests exercise the real path end-to-end -- a real `DVHarness.run_stage`,
all 11 real `STAGE_GATES["RE_AUDIT"]` gate scripts run as real subprocesses,
a real un-mocked `route_and_store()` writing to a real `MemoryStore` -- and
assert the accumulation really happens and really clears the real
promotion gate. Nothing here calls `MemoryGC.confirm()` itself; that is the
entire point.

The RE_AUDIT PASS fixture is imported from test_inference_engine_wiring rather
than copied, so both modules stay bound to one definition of a real PASS.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.adapters.base import AgentResult
from dv_harness.engine import DVHarness
from dv_harness.memory import MemoryConsolidator, MemoryStore
from dv_harness.memory_router import (
    ORGANIZATIONAL_MIN_CONFIRMATIONS,
    promote_to_organizational,
)
from dv_harness.models import Status
from dv_harness.protocol_router import resolve_protocol
from dv_harness_tests.test_inference_engine_wiring import (
    _install_re_audit_gates,
    _re_audit_pass_text,
)

ROOT = Path(__file__).resolve().parents[1]

# A user goal protocol_router.resolve_protocol() really resolves, so the
# harness supplies a canonical protocol key of its own rather than the
# unjudged one the evidence block never carries. Asserted below rather than
# assumed, so a routing-alias change cannot quietly turn these tests into
# vacuous no-ops.
_USB_GOAL = "debug USB2 ep0 GET_DESCRIPTOR timeout"

# The root_cause the shared RE_AUDIT fixture's root_cause_evidence_gate block
# selects -- the other half of the (protocol, root_cause) dedup key.
_FIXTURE_ROOT_CAUSE = "ep0 FIFO underrun due to missing prefetch on GET_DESCRIPTOR"

_HIGH_CONFIDENCE_INPUTS = dict(independent_sources_count=3, evidence_refs_verified=True,
                               counter_evidence_count=0, multi_agent_consensus_count=2)


class _PassAdapter:
    def __init__(self, text: str):
        self._text = text

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        return AgentResult(ok=True, text=self._text, raw={}, session_id=None)


def _fresh_harness_with_graph():
    """A DVHarness rooted at a fresh temp dir with the REAL shipped graph and
    the real RE_AUDIT gate scripts in place -- same idiom as
    test_system_level_soc_composition_wiring._fresh_project().

    The graph is not optional here, unlike in the sibling tests that call
    _promote_verified_fix_knowledge() directly: `protocol_decision` is only
    computed for a real graph NODE (engine.py's _gather_stage_context), so a
    graph-less harness would supply protocol=None and these tests would pass
    for the wrong reason. It is also the real production shape -- the shipped
    graph is what run_stage() resolves against on a real project. Caller must
    shutil.rmtree(tmp)."""
    tmp = Path(tempfile.mkdtemp())
    graph_dir = tmp / ".dv-harness" / "graph"
    graph_dir.mkdir(parents=True)
    (graph_dir / "main_graph.json").write_text(
        (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    _install_re_audit_gates(tmp)
    return tmp, DVHarness(tmp)


def _run_re_audit_pass(h: DVHarness, goal: str) -> None:
    """One real, independently gate-verified RE_AUDIT PASS."""
    h.set_stage("RE_AUDIT")
    h.adapter = _PassAdapter(_re_audit_pass_text(target_testcase_id="t1"))
    h.run_stage(goal)
    assert h.state.stages["RE_AUDIT"]["status"] == Status.PASS.value


def _engineering_records(root: Path):
    store = MemoryStore(root)
    return [store.get(r["memory_id"]) for r in store._index()
            if r.get("level") == "engineering"]


def test_the_fixture_goal_really_resolves_to_a_canonical_protocol():
    # Guards every test below: if resolve_protocol() stopped recognizing this
    # goal, the harness would supply protocol=None and the accumulation tests
    # would pass for the wrong reason (nothing to key on == nothing to
    # confirm), so pin the real resolved value.
    decision = resolve_protocol({"protocol_hint": _USB_GOAL})
    assert decision["resolved"] is True
    assert decision["protocol"] == "usb"


def test_repeated_re_audit_passes_confirm_one_engineering_record_instead_of_minting_many():
    # THE gap this closes. Three real RE_AUDIT PASSes over the same finding
    # used to leave three separate engineering records each with
    # confirmation_count 0; they must now leave ONE record whose
    # confirmation_count was earned by the second and third runs.
    tmp, h = _fresh_harness_with_graph()
    try:
        for _ in range(1 + ORGANIZATIONAL_MIN_CONFIRMATIONS):
            _run_re_audit_pass(h, _USB_GOAL)

        records = _engineering_records(tmp)
        verified_fixes = [r for r in records if r.get("kind") == "verified_fix"]
        assert len(verified_fixes) == 1, (
            "each independent re-derivation minted its own record instead of "
            f"confirming the first: {[r['memory_id'] for r in verified_fixes]}"
        )
        record = verified_fixes[0]
        assert record["protocol"] == "usb"
        assert record["root_cause"] == _FIXTURE_ROOT_CAUSE
        assert record["confirmation_count"] == ORGANIZATIONAL_MIN_CONFIRMATIONS
        assert record["last_confirmed_at"] is not None
        assert record["status"] == "ACTIVE"
    finally:
        shutil.rmtree(tmp)


def test_repeated_re_audit_passes_make_promote_to_organizational_actually_succeed():
    # The payoff: the Organizational tier is reachable through its own
    # intended organic route -- real gate-verified runs only, never a direct
    # MemoryGC.confirm() call and never a hand-written confirmation_count.
    tmp, h = _fresh_harness_with_graph()
    try:

        _run_re_audit_pass(h, _USB_GOAL)
        record = [r for r in _engineering_records(tmp) if r.get("kind") == "verified_fix"][0]
        memory_id = record["memory_id"]

        # After ONE run the confirmation gate must still refuse -- a single
        # PASS is exactly what must not promote.
        first = promote_to_organizational(tmp, memory_id, _HIGH_CONFIDENCE_INPUTS, cfg={})
        assert first["promoted"] is False
        assert first["reason"] == "INSUFFICIENT_CONFIRMATION"

        for _ in range(ORGANIZATIONAL_MIN_CONFIRMATIONS):
            _run_re_audit_pass(h, _USB_GOAL)

        # A cleared promotion returns route_and_store()'s own result (there is
        # no "promoted" key on the success path), so assert the record really
        # landed in the Organizational tier rather than being demoted to
        # Working with an organizational_admission_rejected reason.
        result = promote_to_organizational(tmp, memory_id, _HIGH_CONFIDENCE_INPUTS, cfg={})
        assert result["destination"] == "ORGANIZATIONAL_MEMORY", result
        assert result["promotion_gate"]["confirmation_count"] == ORGANIZATIONAL_MIN_CONFIRMATIONS
        assert result["promotion_gate"]["qualitative_shape"] == "re_audit_gate_shape"
        assert result["promotion_gate"]["confidence_result"]["level"] == "HIGH"
    finally:
        shutil.rmtree(tmp)


def test_a_different_protocols_identical_root_cause_is_not_falsely_confirmed():
    # The dedup key is (protocol, root_cause), so the same root_cause text
    # re-derived under a DIFFERENT protocol is a different finding and must
    # mint its own record -- otherwise "confirmation" would just mean
    # "someone wrote similar words again".
    tmp, h = _fresh_harness_with_graph()
    try:
        _run_re_audit_pass(h, _USB_GOAL)
        _run_re_audit_pass(h, "debug PCIe LTSSM recovery timeout")

        verified_fixes = [r for r in _engineering_records(tmp) if r.get("kind") == "verified_fix"]
        assert sorted(r["protocol"] for r in verified_fixes) == ["pcie", "usb"]
        assert all(r["confirmation_count"] == 0 for r in verified_fixes)
    finally:
        shutil.rmtree(tmp)


def test_an_unresolved_protocol_still_writes_a_record_and_never_fabricates_a_key():
    # Backward compatibility, and the honest half of the fix: a goal naming no
    # recognized protocol must still promote its record (nothing regressed),
    # carry protocol None (never a fabricated placeholder), and therefore not
    # participate in dedup at all.
    tmp, h = _fresh_harness_with_graph()
    try:
        _run_re_audit_pass(h, "goal")
        _run_re_audit_pass(h, "goal")

        verified_fixes = [r for r in _engineering_records(tmp) if r.get("kind") == "verified_fix"]
        assert len(verified_fixes) == 2
        assert all(r["protocol"] is None for r in verified_fixes)
        assert all(r["confirmation_count"] == 0 for r in verified_fixes)
    finally:
        shutil.rmtree(tmp)


@pytest.mark.parametrize("resolved,block,expected", [
    ("usb", "USB 2.0 Device", "usb"),          # canonical value wins over free text
    (None, "USB 2.0 Device", "USB 2.0 Device"),  # block value is the fallback, not dead
    ("  usb  ", None, "usb"),                    # whitespace never becomes part of the key
    (None, "   ", None),                         # blank is absence, never a key
    (None, None, None),                          # both absent stays absent, never invented
])
def test_engineering_record_protocol_precedence(resolved, block, expected):
    assert DVHarness._engineering_record_protocol(resolved, block) == expected


def test_memory_consolidator_confirms_a_re_derived_closed_finding_instead_of_duplicating_it():
    # The memory-consolidation skill's own write path (the sanctioned "initial
    # Engineering Memory write") had the same duplication problem: it calls
    # MemoryStore.add() directly, so calling it twice for one finding minted
    # two records and zero confirmations. A second closed finding cleared the
    # same single_sim + regression + reaudit bar on its own evidence, so it
    # confirms rather than competes.
    tmp = Path(tempfile.mkdtemp())
    try:
        store = MemoryStore(tmp)
        finding = {
            "title": "USB2 EP0 underrun", "status": "CLOSED", "protocol": "USB2",
            "scope": "subsystem", "root_cause": "missing prefetch on GET_DESCRIPTOR",
            "fix": "rev2", "finding_id": "F-1",
        }
        verification = {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"}

        first = MemoryConsolidator(store).from_closed_finding(finding, verification)
        assert first["confirmation_count"] == 0

        second = MemoryConsolidator(store).from_closed_finding(
            dict(finding, finding_id="F-2", evidence=["sim.log:9001 FIFO_EMPTY"]),
            verification,
        )
        assert second["memory_id"] == first["memory_id"]
        assert second["confirmation_count"] == 1
        assert second["last_confirmation_evidence"] == ["sim.log:9001 FIFO_EMPTY"]
        assert len([r for r in store._index() if r.get("level") == "engineering"]) == 1
    finally:
        shutil.rmtree(tmp)


def test_memory_consolidator_without_a_protocol_still_adds_a_separate_record():
    # A finding carrying no protocol has no dedup key, so it must behave
    # exactly as it did before this change -- a fresh record every time,
    # never collapsed onto an unrelated record by root_cause text alone.
    tmp = Path(tempfile.mkdtemp())
    try:
        store = MemoryStore(tmp)
        finding = {"status": "CLOSED", "title": "t", "finding_id": "F1",
                   "root_cause": "shared root cause text"}
        verification = {"single_sim": "PASS", "regression": "NOT_REQUIRED", "reaudit": "CLEAN"}

        first = MemoryConsolidator(store).from_closed_finding(finding, verification)
        second = MemoryConsolidator(store).from_closed_finding(finding, verification)

        assert first["memory_id"] != second["memory_id"]
        assert len([r for r in store._index() if r.get("level") == "engineering"]) == 2
    finally:
        shutil.rmtree(tmp)
