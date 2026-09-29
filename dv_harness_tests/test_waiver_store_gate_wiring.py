"""Proves the waiver ledger (dv_harness/waiver_store.py) is the SOURCE OF
TRUTH the three real waiver gate scripts read from -- spec section 237
(WAIVER EXPIRATION / REVALIDATION).

The gap this closes: before 2026-09-06 the store had no consumer at all (its
own docstring said so), and every waiver gate judged records the agent typed
into its own ```dv-harness-evidence``` block -- the same agent wrote both the
waiver and the evidence that the waiver was still valid, so an expired waiver
stopped being mentioned rather than being re-flagged.

Nothing here is mocked: every assertion drives the REAL
gates.evaluate_stage_evidence() over the REAL shipped STAGE_GATES entries for
REQUIREMENTS_TRACEABILITY, running the REAL gate scripts as subprocesses
against a REAL ledger on disk. Nothing runs a build, a regression or an LSF
submission, and no approval gate is touched.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import waiver_store
from dv_harness.gates import STAGE_GATES, evaluate_stage_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]

GOOD_REQUIREMENTS = {"requirements": [{
    "req_id": "REQ-USB-014", "spec_ref": "USB3.1 spec 7.2.4", "feature": "LPM L1 substates",
    "expected_behavior": "device enters L1 within 10us of LGO_U1",
    "verification_method": "directed test", "coverage_goal": "cg_lpm_l1",
}]}

CURRENT = {"spec_revision": "SPEC-1.2", "rtl_hash": "rtl-aaa111", "revision": "REV5"}


# --- fixtures -------------------------------------------------------------

def _make_project(tmp_path: Path) -> Path:
    """A real project root carrying real copies of exactly the gate scripts
    STAGE_GATES["REQUIREMENTS_TRACEABILITY"] names -- the same layout a
    deployed project has (its own copy of tools/verification_flow/, the real
    dv_harness package supplied by run_gate() through the env)."""
    root = tmp_path / "proj"
    dest = root / "tools" / "verification_flow"
    dest.mkdir(parents=True)
    for _gate_id, script_name, _flag in STAGE_GATES["REQUIREMENTS_TRACEABILITY"]:
        src = REPO_ROOT / "tools" / "verification_flow" / script_name
        assert src.is_file(), src
        shutil.copy2(src, dest / Path(script_name).name)
    return root


def _canonical_waiver(waiver_id="W-USB-001", **overrides):
    record = {
        "waiver_id": waiver_id,
        "item": "REQ-USB-014",
        "reason": "DUT does not implement LPM L1 substates in this silicon revision",
        "evidence": "usb31_dev/rtl/usb_lpm.v has no L1 FSM; design review 2026-08-30",
        "scope": {
            "requirement_ids": ["REQ-USB-014"],
            "subsystem": "usb31_dev",
            "spec_revision": "SPEC-1.2",
            "design_evidence_hash": "sha256:deadbeef",
            "approval_id": "APPR-77",
            "scope_hash": "sha256:cafe1234",
            "applied_requirement_ids": ["REQ-USB-014"],
        },
        "approver": "dv-lead-alice",
        "affected_version": {"spec_revision": "SPEC-1.2", "rtl_hash": "rtl-aaa111",
                             "revision": "REV5"},
        "risk": "LOW",
        "created_at": "2026-08-30T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "revalidation_trigger": {"spec_revision": "SPEC-1.2", "rtl_hash": "rtl-aaa111"},
    }
    record.update(overrides)
    return record


def _agent_text(declared_waivers=None, current=None):
    """The agent's own stage response. `declared_waivers` is what the AGENT
    claims -- deliberately independent of the ledger, so a test can prove the
    verdict came from the ledger and not from this text."""
    declared = declared_waivers if declared_waivers is not None else []
    current = current if current is not None else CURRENT
    scope = {"waivers": declared}
    freshness = {"current": {"spec_revision": current["spec_revision"],
                             "rtl_hash": current["rtl_hash"]},
                 "waivers": declared}
    revalidation = {"waivers": {"waivers": declared},
                    "current_revision": current["revision"]}
    return (
        f"```dv-harness-evidence:spec_to_vplan_requirement_quality_gate\n{json.dumps(GOOD_REQUIREMENTS)}\n```\n"
        f"```dv-harness-evidence:waiver_scope_consistency_gate\n{json.dumps(scope)}\n```\n"
        f"```dv-harness-evidence:waiver_revision_freshness_gate\n{json.dumps(freshness)}\n```\n"
        f"```dv-harness-evidence:waiver_revalidation_gate\n{json.dumps(revalidation)}\n```\n"
    )


def _evaluate(root, declared=None, current=None):
    return evaluate_stage_evidence(root, "REQUIREMENTS_TRACEABILITY",
                                   _agent_text(declared, current))


# --- the headline: a ledger waiver is really read and really enforced -----

def test_expired_ledger_waiver_reflags_the_item_the_agent_never_mentioned(tmp_path):
    """The central proof. A waiver recorded in the ledger EXPIRES; the agent's
    own evidence block declares NO waivers at all (exactly what a self-attested
    flow produces once a waiver becomes inconvenient); the REAL gate re-flags
    it anyway, naming the waiver and the requirement it was waiving."""
    root = _make_project(tmp_path)
    waiver_store.record_waiver(root, _canonical_waiver(
        expires_at="2026-01-01T00:00:00+00:00"))

    verdict, reasons = _evaluate(root, declared=[])
    joined = " ".join(reasons)
    assert verdict == "GATE_FAIL", reasons
    assert "WAIVER_EXPIRED" in joined, reasons
    assert "W-USB-001" in joined, reasons
    assert "waiver_store" in joined, reasons  # the verdict names its source

    # ... and the ledger itself names the requirement that is no longer waived,
    # which is the thing a human has to act on.
    report = waiver_store.status_report(root)
    row = next(r for r in report["waivers"] if r["waiver_id"] == "W-USB-001")
    assert row["status"] == "EXPIRED"
    assert row["item"] == "REQ-USB-014"
    assert report["status"] == "WAIVERS_NOT_VALID"


def test_positive_control_same_waiver_unexpired_passes_the_same_stage(tmp_path):
    """The negative control that gives the test above its detection power:
    the identical ledger, identical agent text, identical gates -- only the
    expiry moved -- reaches a real PASS."""
    root = _make_project(tmp_path)
    waiver_store.record_waiver(root, _canonical_waiver())
    verdict, reasons = _evaluate(root, declared=[])
    assert verdict == "PASS", reasons


def test_agent_cannot_pass_by_declaring_a_waiver_the_ledger_never_recorded(tmp_path):
    root = _make_project(tmp_path)
    waiver_store.record_waiver(root, _canonical_waiver())
    fabricated = [{"waiver_id": "W-FABRICATED", "approved": True, "evidence": "trust me",
                   "requirement_ids": ["REQ-X"], "subsystem": "s", "spec_revision": "SPEC-1.2",
                   "design_evidence_hash": "h", "approval_id": "a", "scope_hash": "sh",
                   "revision": "REV5", "rtl_hash": "rtl-aaa111"}]
    verdict, reasons = _evaluate(root, declared=fabricated)
    assert verdict == "GATE_FAIL", reasons
    assert "WAIVER_NOT_IN_STORE" in " ".join(reasons), reasons
    assert "W-FABRICATED" in " ".join(reasons), reasons


def test_agent_declaring_a_ledger_waiver_is_accepted(tmp_path):
    """Citing a waiver that IS recorded is legitimate and must not be
    penalised -- the refusal above is about fabrication, not about citing."""
    root = _make_project(tmp_path)
    waiver_store.record_waiver(root, _canonical_waiver())
    verdict, reasons = _evaluate(root, declared=[{"waiver_id": "W-USB-001"}])
    assert verdict == "PASS", reasons


def test_revoked_ledger_waiver_is_refused(tmp_path):
    root = _make_project(tmp_path)
    waiver_store.record_waiver(root, _canonical_waiver())
    waiver_store.revoke_waiver(root, "W-USB-001", revoked_by="dv-lead-alice",
                               reason="RTL now implements L1; waiver no longer applies")
    verdict, reasons = _evaluate(root, declared=[])
    assert verdict == "GATE_FAIL", reasons
    assert "WAIVER_REVOKED" in " ".join(reasons), reasons


def test_moved_rtl_hash_requires_revalidation_and_revalidating_clears_it(tmp_path):
    root = _make_project(tmp_path)
    waiver_store.record_waiver(root, _canonical_waiver())
    moved = dict(CURRENT, rtl_hash="rtl-bbb222")

    verdict, reasons = _evaluate(root, current=moved)
    assert verdict == "GATE_FAIL", reasons
    joined = " ".join(reasons)
    assert "WAIVER_REVALIDATION_REQUIRED" in joined or "STALE_WAIVER_AFTER_REVISION_CHANGE" in joined, reasons

    # Revalidating against the new RTL, with real revalidation evidence, clears it.
    records = waiver_store.read_waivers(root)
    records[0]["revalidated_for"] = {"rtl_hash": "rtl-bbb222"}
    records[0]["revalidation_evidence_hash"] = "sha256:revalidated-2026-09-06"
    waiver_store._write_waivers(root, records)
    verdict2, reasons2 = _evaluate(root, current=moved)
    assert verdict2 == "PASS", reasons2


def test_legacy_four_field_record_is_unknown_not_silently_valid(tmp_path):
    """A record the dashboard's original 4-field form wrote carries no expiry
    and no revalidation trigger. It is real human intent and is never dropped,
    but it cannot be shown to still be valid -- UNKNOWN, with the missing
    section 237 fields named."""
    root = _make_project(tmp_path)
    waiver_store.append_waiver(root, {"gate_id": "waiver_revalidation_gate",
                                      "item_id": "REQ-USB-014", "approved": True,
                                      "evidence": "reviewed against spec 7.2.4"})
    verdict, reasons = _evaluate(root, declared=[])
    assert verdict == "GATE_FAIL", reasons
    joined = " ".join(reasons)
    assert "WAIVER_STATUS_UNKNOWN" in joined, reasons
    assert "MISSING_SECTION_237_FIELDS" in joined, reasons


def test_scope_incompleteness_still_fails_on_a_ledger_record(tmp_path):
    """The gates' own pre-existing checks still run over ledger records --
    the store supplies the records, it does not replace the checks."""
    root = _make_project(tmp_path)
    record = _canonical_waiver()
    waiver_store.record_waiver(root, record)
    stored = waiver_store.read_waivers(root)
    stored[0]["scope"]["approval_id"] = ""        # nobody approved it after all
    waiver_store._write_waivers(root, stored)
    verdict, reasons = _evaluate(root, declared=[])
    assert verdict == "GATE_FAIL", reasons
    assert "INCOMPLETE_WAIVER_SCOPE" in " ".join(reasons), reasons


def test_waiver_hiding_an_active_failure_still_fails_on_a_ledger_record(tmp_path):
    root = _make_project(tmp_path)
    waiver_store.record_waiver(root, _canonical_waiver(
        active_failure_ids=["FAIL-usb-lpm-timeout-3"]))
    verdict, reasons = _evaluate(root, declared=[])
    assert verdict == "GATE_FAIL", reasons
    assert "WAIVER_ATTEMPTS_TO_HIDE_ACTIVE_FAILURE" in " ".join(reasons), reasons


# --- un-migrated projects are never retroactively failed -----------------

def test_project_with_no_ledger_keeps_the_original_agent_attested_behaviour(tmp_path):
    root = _make_project(tmp_path)
    assert not waiver_store.store_exists(root)
    declared = [{"waiver_id": "W-AGENT", "approved": True, "evidence": "e",
                 "requirement_ids": ["REQ-USB-014"], "subsystem": "usb31_dev",
                 "spec_revision": "SPEC-1.2", "design_evidence_hash": "h",
                 "approval_id": "a", "scope_hash": "sh",
                 "revision": "REV5", "rtl_hash": "rtl-aaa111"}]
    verdict, reasons = _evaluate(root, declared=declared)
    assert verdict == "PASS", reasons

    # ... and its original failure paths are unchanged too.
    stale = [dict(declared[0], revision="REV3")]
    verdict2, reasons2 = _evaluate(root, declared=stale)
    assert verdict2 == "GATE_FAIL", reasons2
    assert "WAIVER_REVISION_STALE" in " ".join(reasons2), reasons2
    assert "agent_evidence_block" in " ".join(reasons2), reasons2


def test_real_repo_root_has_no_ledger_so_shipped_gate_behaviour_is_unchanged():
    """This repository itself has never recorded a waiver, which is why the
    pre-existing test_engine_gates_and_routing waiver test still describes the
    agent-attested path. Asserted rather than assumed, so adopting a ledger
    here can never silently change that test's meaning."""
    assert not waiver_store.store_exists(REPO_ROOT)


# --- derived status: every section 237 value, from real content ----------

def test_status_vocabulary_is_section_237s():
    assert waiver_store.WAIVER_STATUSES == (
        "VALID", "REVALIDATION_REQUIRED", "EXPIRED", "REVOKED", "UNKNOWN")


def test_derive_status_valid():
    status, reason = waiver_store.derive_status(
        _canonical_waiver(), now="2026-09-06T00:00:00+00:00", current=CURRENT)
    assert status == "VALID", reason


def test_derive_status_expired():
    status, reason = waiver_store.derive_status(
        _canonical_waiver(expires_at="2026-01-01T00:00:00+00:00"),
        now="2026-09-06T00:00:00+00:00", current=CURRENT)
    assert status == "EXPIRED"
    assert "2026-01-01" in reason


def test_derive_status_revalidation_required_on_moved_rtl():
    status, reason = waiver_store.derive_status(
        _canonical_waiver(), now="2026-09-06T00:00:00+00:00",
        current=dict(CURRENT, rtl_hash="rtl-bbb222"))
    assert status == "REVALIDATION_REQUIRED"
    assert "RTL_HASH_CHANGED" in reason


def test_derive_status_revoked_outranks_expiry():
    """A human's revocation is the last word: an also-expired record still
    reads REVOKED, so the reason a human sees is the decision, not the clock."""
    status, _ = waiver_store.derive_status(
        _canonical_waiver(expires_at="2020-01-01T00:00:00+00:00",
                          revoked=True, revoked_by="alice"),
        now="2026-09-06T00:00:00+00:00", current=CURRENT)
    assert status == "REVOKED"


def test_derive_status_unknown_when_nothing_can_go_stale():
    record = _canonical_waiver()
    record.pop("expires_at")
    record.pop("revalidation_trigger")
    status, reason = waiver_store.derive_status(record, now="2026-09-06T00:00:00+00:00")
    assert status == "UNKNOWN"
    assert reason == "NO_EXPIRATION_AND_NO_REVALIDATION_TRIGGER_DECLARED"


def test_derive_status_unknown_on_unparseable_expiry():
    status, reason = waiver_store.derive_status(
        _canonical_waiver(expires_at="whenever"), now="2026-09-06T00:00:00+00:00")
    assert status == "UNKNOWN"
    assert "UNPARSEABLE_EXPIRES_AT" in reason


def test_expiry_is_not_decided_without_a_real_clock():
    """`now=None` means nobody measured the time -- the expiry check is
    skipped rather than guessed. The gate that owns the harness clock
    (waiver_revalidation_gate, the only --now ContextFlag) decides it."""
    status, _ = waiver_store.derive_status(
        _canonical_waiver(expires_at="2020-01-01T00:00:00+00:00"), now=None,
        current=CURRENT)
    assert status == "VALID"


def test_unmeasured_trigger_key_is_not_reported_as_changed():
    status, _ = waiver_store.derive_status(
        _canonical_waiver(), now="2026-09-06T00:00:00+00:00", current={})
    assert status == "VALID"


def test_every_supported_trigger_key_is_really_measured_by_some_gate():
    waiver_store.assert_trigger_coverage()
    measured = set()
    for spec in waiver_store.GATE_STATUS_CONTEXT.values():
        measured.update(spec["current_keys"])
    assert set(waiver_store.SUPPORTED_TRIGGER_KEYS) <= measured
    assert set(waiver_store.GATE_STATUS_CONTEXT) == set(waiver_store.WAIVER_GATE_FAMILY)


def test_gate_status_context_matches_the_shipped_stage_gate_entries():
    """Every gate this module claims to serve really is a shipped
    REQUIREMENTS_TRACEABILITY gate -- so the split of who measures what cannot
    outlive the gates it describes."""
    shipped = {gate_id for gate_id, _s, _f in STAGE_GATES["REQUIREMENTS_TRACEABILITY"]}
    assert set(waiver_store.WAIVER_GATE_FAMILY) <= shipped


# --- record_waiver refusals ----------------------------------------------

def test_record_waiver_refuses_a_stored_status(tmp_path):
    with pytest.raises(waiver_store.WaiverStoreError) as e:
        waiver_store.record_waiver(tmp_path, _canonical_waiver(status="VALID"))
    assert "derived" in str(e.value)


def test_record_waiver_refuses_a_trigger_no_gate_measures(tmp_path):
    with pytest.raises(waiver_store.WaiverStoreError) as e:
        waiver_store.record_waiver(tmp_path, _canonical_waiver(
            revalidation_trigger={"tool_version": "vcs-2024.09"}))
    assert "tool_version" in str(e.value)


def test_record_waiver_refuses_neither_expiry_nor_trigger(tmp_path):
    record = _canonical_waiver()
    record.pop("expires_at")
    record.pop("revalidation_trigger")
    with pytest.raises(waiver_store.WaiverStoreError):
        waiver_store.record_waiver(tmp_path, record)


def test_record_waiver_refuses_a_duplicate_id(tmp_path):
    waiver_store.record_waiver(tmp_path, _canonical_waiver())
    with pytest.raises(waiver_store.WaiverStoreError):
        waiver_store.record_waiver(tmp_path, _canonical_waiver())


def test_record_waiver_refuses_incomplete_scope(tmp_path):
    record = _canonical_waiver()
    record["scope"].pop("scope_hash")
    with pytest.raises(waiver_store.WaiverStoreError) as e:
        waiver_store.record_waiver(tmp_path, record)
    assert "scope_hash" in str(e.value)


@pytest.mark.parametrize("field", waiver_store.CANONICAL_REQUIRED_FIELDS)
def test_record_waiver_refuses_each_missing_section_237_field(tmp_path, field):
    record = _canonical_waiver()
    record.pop(field)
    if field == "waiver_id":
        # append_waiver()'s legacy dispatch keys on waiver_id; call the
        # canonical writer directly so the refusal under test is the one meant.
        with pytest.raises(waiver_store.WaiverStoreError):
            waiver_store.record_waiver(tmp_path, record)
        return
    with pytest.raises(waiver_store.WaiverStoreError) as e:
        waiver_store.record_waiver(tmp_path, record)
    assert field in str(e.value)


def test_revoke_requires_a_named_human_and_a_reason(tmp_path):
    waiver_store.record_waiver(tmp_path, _canonical_waiver())
    with pytest.raises(waiver_store.WaiverStoreError):
        waiver_store.revoke_waiver(tmp_path, "W-USB-001", revoked_by="", reason="x")
    with pytest.raises(waiver_store.WaiverStoreError):
        waiver_store.revoke_waiver(tmp_path, "W-USB-001", revoked_by="alice", reason="")
    with pytest.raises(waiver_store.WaiverStoreError):
        waiver_store.revoke_waiver(tmp_path, "NO-SUCH", revoked_by="alice", reason="r")


def test_append_waiver_dispatches_a_canonical_record_to_the_real_validator(tmp_path):
    waiver_store.append_waiver(tmp_path, _canonical_waiver())
    stored = waiver_store.read_waivers(tmp_path)
    assert stored[0]["schema_version"] == waiver_store.SCHEMA_VERSION
    with pytest.raises(waiver_store.WaiverStoreError):
        waiver_store.append_waiver(tmp_path, _canonical_waiver(status="VALID"))


# --- reading is not a mutating act ---------------------------------------

def test_reading_never_writes(tmp_path):
    root = _make_project(tmp_path)
    waiver_store.record_waiver(root, _canonical_waiver())
    path = waiver_store._store_path(root)
    before = path.read_bytes()
    waiver_store.gate_records(root, "waiver_revalidation_gate",
                              now=dt.datetime.now(dt.timezone.utc).isoformat(),
                              current=CURRENT)
    waiver_store.status_report(root)
    _evaluate(root, declared=[])
    assert path.read_bytes() == before


def test_status_report_on_a_project_with_no_ledger_creates_nothing(tmp_path):
    report = waiver_store.status_report(tmp_path)
    assert report["status"] == "NOT_AVAILABLE"
    assert report["reason"] == "NO_WAIVER_STORE"
    assert not (tmp_path / ".dv-harness").exists()


# --- front door -----------------------------------------------------------

def _run_module(root, *args):
    return subprocess.run([sys.executable, "-m", "dv_harness.waiver_store", *args],
                          cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)


def test_module_front_door_exit_codes(tmp_path):
    root = _make_project(tmp_path)
    r = _run_module(root, "status", "--root", str(root))
    assert r.returncode == 2, r.stdout + r.stderr
    assert json.loads(r.stdout)["reason"] == "NO_WAIVER_STORE"

    waiver_store.record_waiver(root, _canonical_waiver())
    r2 = _run_module(root, "status", "--root", str(root))
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert json.loads(r2.stdout)["status"] == "CLEAR"

    waiver_store.revoke_waiver(root, "W-USB-001", revoked_by="alice", reason="fixed in RTL")
    r3 = _run_module(root, "status", "--root", str(root))
    assert r3.returncode == 1, r3.stdout + r3.stderr
    assert json.loads(r3.stdout)["not_valid"] == 1

    r4 = _run_module(root, "statuses")
    assert r4.returncode == 0
    assert json.loads(r4.stdout)["statuses"] == list(waiver_store.WAIVER_STATUSES)
