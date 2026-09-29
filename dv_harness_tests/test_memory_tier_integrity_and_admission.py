"""Phase 4+5 gap closure (2026-09-03, gap-close-obsidian-memory-phase-4-5):
the three PARTIAL sub-findings of the 5-Level Memory tiers / Promotion Engine
audit, each proven closed against real files and real routing -- never a
parse/import smoke test.

  1. Job-tier field completeness -- the spec's own named Job Memory fields
     (start/end time, command, timeout, fix attempt, result) really reach the
     persisted Job Memory record, from real JobState/bjobs sources.
  2. JSON MemoryStore index integrity -- record files with no index.json row
     were invisible to MemoryRetriever.search(); index_integrity() detects
     that state and reindex() repairs it, and concurrent writers no longer
     create it.
  3. (Working/Project) -> Engineering admission gate -- the tier boundary one
     level below promote_to_organizational()'s, previously enforced only by a
     caller-supplied `verified` boolean.
  4. (2026-09-04 re-audit) confirmation_count integrity -- the organizational
     gate's third input was itself caller-supplied, so one creation event
     could self-declare the repeated confirmation the gate exists to require.
  5. (2026-09-04 phase 13+14) Engineering -> Organizational admission at the
     WRITE boundary -- promote_to_organizational()'s three gates were enforced
     only by its own callers, so a direct route_and_store() reached the
     shared, cross-user Knowledge Center without clearing any of them.
"""

from __future__ import annotations

import json
import multiprocessing
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dv_harness import lsf_client, memory_doctor
from dv_harness.memory import MemoryGC, MemoryRetriever, MemoryStore
from dv_harness.memory_router import (
    ORGANIZATIONAL_MIN_CONFIRMATIONS, engineering_admission_gate,
    organizational_admission_gate, promote_to_organizational, route_and_store,
)


@pytest.fixture()
def tmp_root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _job_memory_record(root: Path, job_id: int):
    store = MemoryStore(root)
    return store.get(f"JOB-{job_id}-TERMINAL-RECONCILE")


# ===========================================================================
# 1. Job-tier field completeness
# ===========================================================================

def test_job_memory_record_carries_command_timeout_times_fix_attempt_and_result(tmp_root):
    """The audit's finding: `bjobs -json` was queried with submit_time/run_time
    and reconcile_job() discarded both; the bsub command string was never on
    JobState at all; and root_cause_status/fix_proposal_status existed but
    were never copied into the persisted record. All five spec-named fields
    must now be real, sourced values on the Job Memory record."""
    lsf_client.save_job_state(tmp_root, lsf_client.JobState(
        job_id=901, lsf_status="RUN", sim_status="UNKNOWN", pattern="usb2_hs_basic",
        command="make -C /proj/usb2 run PAT=usb2_hs_basic", runlimit_minutes=120,
        run_dir="/proj/usb2/run", sim_log="/proj/usb2/run/901/sim.log",
        root_cause_status="IN_PROGRESS", fix_proposal_status="NOT_STARTED",
    ))
    payload = json.dumps({"RECORDS": [{"JOBID": "901", "STAT": "DONE",
                                        "SUBMIT_TIME": "Sep  3 09:12", "RUN_TIME": "418 second(s)"}]})
    with patch("dv_harness.lsf_client.subprocess.run",
               return_value=MagicMock(stdout=payload, stderr="", returncode=0)):
        lsf_client.reconcile_batch(tmp_root, [901])

    rec = _job_memory_record(tmp_root, 901)
    assert rec is not None and rec["level"] == "job"
    # start time + elapsed runtime: LSF's OWN reported strings, verbatim
    assert rec["submit_time"] == "Sep  3 09:12"
    assert rec["run_time"] == "418 second(s)"
    # end time: this harness's real first-observation timestamp, honestly named
    assert rec["observed_terminal_at"].endswith("+00:00")
    # command + timeout budget
    assert rec["command"] == "make -C /proj/usb2 run PAT=usb2_hs_basic"
    assert rec["runlimit_minutes"] == 120
    # fix attempt + result
    assert rec["root_cause_status"] == "IN_PROGRESS"
    assert rec["fix_proposal_status"] == "NOT_STARTED"
    assert rec["dv_result"] == "UNKNOWN"          # DV verdict, distinct from lsf_status
    assert rec["lsf_status"] == "DONE"            # CLAUDE.md: LSF DONE != DV PASS
    assert rec["run_dir"] == "/proj/usb2/run"

    # The same values are durable on the JobState file too, not only in memory.
    state = lsf_client.load_job_state(tmp_root, 901)
    assert state.submit_time == "Sep  3 09:12"
    assert state.run_time == "418 second(s)"
    assert state.command == "make -C /proj/usb2 run PAT=usb2_hs_basic"
    assert state.runlimit_minutes == 120


def test_job_memory_record_omits_optional_fields_the_caller_never_supplied(tmp_root):
    """Honest-absence convention (the same one seed/fsdb_path established):
    a field nothing supplied is OMITTED, never written as a null placeholder
    that would look like the schema captured it."""
    lsf_client.save_job_state(tmp_root, lsf_client.JobState(
        job_id=902, lsf_status="RUN", sim_status="UNKNOWN", pattern="usb2_hs_basic"))
    payload = json.dumps({"RECORDS": [{"JOBID": "902", "STAT": "DONE"}]})
    with patch("dv_harness.lsf_client.subprocess.run",
               return_value=MagicMock(stdout=payload, stderr="", returncode=0)):
        lsf_client.reconcile_batch(tmp_root, [902])

    rec = _job_memory_record(tmp_root, 902)
    for absent in ("command", "runlimit_minutes", "submit_time", "run_time", "run_dir"):
        assert absent not in rec, f"{absent} must be omitted, not written as null"
    # but the always-real ones are still there
    assert rec["root_cause_status"] == "NOT_STARTED"
    assert rec["dv_result"] == "UNKNOWN"
    assert rec["observed_terminal_at"]


def test_observed_terminal_at_is_set_once_not_refreshed_by_later_polls(tmp_root):
    lsf_client.save_job_state(tmp_root, lsf_client.JobState(
        job_id=903, lsf_status="RUN", sim_status="UNKNOWN"))
    payload = json.dumps({"RECORDS": [{"JOBID": "903", "STAT": "DONE"}]})
    with patch("dv_harness.lsf_client.subprocess.run",
               return_value=MagicMock(stdout=payload, stderr="", returncode=0)):
        lsf_client.reconcile_batch(tmp_root, [903])
        first = lsf_client.load_job_state(tmp_root, 903).observed_terminal_at
        lsf_client.reconcile_batch(tmp_root, [903])
        lsf_client.reconcile_batch(tmp_root, [903])
    assert first is not None
    assert lsf_client.load_job_state(tmp_root, 903).observed_terminal_at == first


def test_bsub_submit_emits_a_real_run_limit_only_when_one_was_requested():
    with patch("dv_harness.lsf_client.subprocess.run",
               return_value=MagicMock(stdout="Job <7001> is submitted", stderr="", returncode=0)) as m:
        lsf_client.bsub_submit("simv +test", queue="normal", runlimit_minutes=90)
    argv = m.call_args.args[0]
    assert "-W" in argv and argv[argv.index("-W") + 1] == "90"

    with patch("dv_harness.lsf_client.subprocess.run",
               return_value=MagicMock(stdout="Job <7002> is submitted", stderr="", returncode=0)) as m:
        lsf_client.bsub_submit("simv +test", queue="normal")
    assert "-W" not in m.call_args.args[0]


def test_lsf_status_literal_only_declares_values_the_stat_map_can_actually_produce():
    """The audit's finding: TIMEOUT/MEMLIMIT/LICENSE_WAIT were declared but
    unreachable -- _BJOBS_STAT_MAP yields none of them, and it is the only
    writer of JobState.lsf_status. Every declared value must be producible."""
    producible = set(lsf_client._BJOBS_STAT_MAP.values()) | {"KILLED"}
    declared = set(getattr(lsf_client.LsfStatus, "__args__", ()))
    if not declared:  # pragma: no cover - Python < 3.8 fallback aliases LsfStatus to str
        pytest.skip("typing.Literal unavailable; LsfStatus degrades to plain str")
    assert declared == producible, f"unreachable declared statuses: {sorted(declared - producible)}"


# ===========================================================================
# 2. JSON MemoryStore index integrity
# ===========================================================================

def _write_out_of_band_record(root: Path, level: str, memory_id: str, **fields):
    """Write a real, well-formed record FILE with no index.json row -- exactly
    the live state this project's own store was found in (18/31 engineering
    and 13/14 working files had no row)."""
    p = root / ".dv-harness" / "memory" / level / f"{memory_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"memory_id": memory_id, "level": level, "status": "ACTIVE",
                              "confidence": "HIGH", **fields}, ensure_ascii=False), encoding="utf-8")
    return p


def test_record_file_without_an_index_row_is_invisible_to_search_then_reindex_restores_it(tmp_root):
    store = MemoryStore(tmp_root)
    _write_out_of_band_record(tmp_root, "engineering", "MEM-ORPHAN01",
                              title="USB2 LFPS polling timeout", protocol="USB2",
                              root_cause="missing sync flop on lfps_detect")

    # Reachable by exact id (get() reads the file) but NOT by search()
    # (search() iterates index.json) -- the precise asymmetry the audit found.
    assert store.get("MEM-ORPHAN01") is not None
    query = {"protocol": "USB2", "text": "lfps polling timeout"}
    assert MemoryRetriever(store).search(query) == []

    report = store.index_integrity()
    assert report["ok"] is False
    assert [r["memory_id"] for r in report["files_missing_from_index"]] == ["MEM-ORPHAN01"]

    result = store.reindex()
    assert result["added"] == ["MEM-ORPHAN01"]
    assert store.index_integrity()["ok"] is True

    hits = MemoryRetriever(store).search(query)
    assert [h["memory"]["memory_id"] for h in hits] == ["MEM-ORPHAN01"]


def test_reindex_reports_but_never_drops_rows_whose_file_is_gone_unless_asked(tmp_root):
    store = MemoryStore(tmp_root)
    mem = store.add("project", {"title": "topology", "protocol": "USB2"})
    (tmp_root / ".dv-harness" / "memory" / "project" / f"{mem['memory_id']}.json").unlink()

    assert store.index_integrity()["index_rows_without_file"][0]["memory_id"] == mem["memory_id"]

    kept = store.reindex()
    assert kept["rows_without_file"] == [mem["memory_id"]] and kept["pruned"] is False
    assert any(r["memory_id"] == mem["memory_id"] for r in store._index())

    pruned = store.reindex(prune_missing=True)
    assert pruned["pruned"] is True
    assert not any(r["memory_id"] == mem["memory_id"] for r in store._index())


def test_reindex_refreshes_a_row_that_drifted_from_its_own_record_file(tmp_root):
    store = MemoryStore(tmp_root)
    mem = store.add("engineering", {"title": "old title", "protocol": "USB2",
                                     "root_cause": "rc", "confidence": "HIGH"})
    path = tmp_root / ".dv-harness" / "memory" / "engineering" / f"{mem['memory_id']}.json"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    on_disk["status"] = "DEPRECATED"
    path.write_text(json.dumps(on_disk), encoding="utf-8")

    assert [r for r in store._index() if r["memory_id"] == mem["memory_id"]][0]["status"] == "ACTIVE"
    assert store.reindex()["refreshed"] == [mem["memory_id"]]
    assert [r for r in store._index() if r["memory_id"] == mem["memory_id"]][0]["status"] == "DEPRECATED"


def _concurrent_writer(args):
    root, tag, count = args
    store = MemoryStore(Path(root))
    for i in range(count):
        store.add("working", {"title": f"{tag}-{i}", "protocol": "USB2"})
    return tag


def test_concurrent_processes_writing_memory_never_lose_each_others_index_rows(tmp_root):
    """The real root cause of the live drift: index.json's read-append-write
    was unlocked, so two concurrent harness processes (this project runs
    several agents at once, each calling route_and_store()) each read the same
    index and the second write dropped the first's row. Every record file
    survived -- only the index rows were lost, which is exactly the signature
    that was found on disk. Four real processes, 15 writes each."""
    MemoryStore(tmp_root)  # create the store before forking writers
    writers = 4
    per_writer = 15
    with multiprocessing.Pool(writers) as pool:
        pool.map(_concurrent_writer, [(str(tmp_root), f"w{n}", per_writer) for n in range(writers)])

    store = MemoryStore(tmp_root)
    files = list((tmp_root / ".dv-harness" / "memory" / "working").glob("*.json"))
    assert len(files) == writers * per_writer
    report = store.index_integrity()
    assert report["ok"] is True, report["files_missing_from_index"]
    assert report["index_row_count"] == writers * per_writer


def test_memory_doctor_reports_index_drift_and_goes_ready_after_reindex(tmp_root):
    cfg = {"knowledge_center": {"enabled": False},
           "memory": {"vault_path": "", "git_enabled": False}}
    _write_out_of_band_record(tmp_root, "engineering", "MEM-ORPHAN02", title="t", protocol="USB2")

    before = memory_doctor.run_doctor(tmp_root, cfg=cfg)
    assert before["checks"]["memory_store_index"]["status"] == "PARTIAL"
    assert "memory_store_index" in before["partial_reasons"]
    assert "reindex" in before["checks"]["memory_store_index"]["reason"]

    MemoryStore(tmp_root).reindex()
    after = memory_doctor.run_doctor(tmp_root, cfg=cfg)
    assert after["checks"]["memory_store_index"]["status"] == "READY"


def test_memory_cli_reindex_and_index_check_run_end_to_end(tmp_root, capsys, monkeypatch):
    import sys
    from dv_harness import memory_cli
    _write_out_of_band_record(tmp_root, "engineering", "MEM-ORPHAN03", title="t", protocol="USB2")

    monkeypatch.setattr(sys, "argv", ["memory_cli", "--project-root", str(tmp_root), "index-check"])
    memory_cli.main()
    assert json.loads(capsys.readouterr().out)["ok"] is False

    monkeypatch.setattr(sys, "argv", ["memory_cli", "--project-root", str(tmp_root), "reindex"])
    memory_cli.main()
    assert json.loads(capsys.readouterr().out)["added"] == ["MEM-ORPHAN03"]

    monkeypatch.setattr(sys, "argv", ["memory_cli", "--project-root", str(tmp_root), "index-check"])
    memory_cli.main()
    assert json.loads(capsys.readouterr().out)["ok"] is True


# ===========================================================================
# 3. (Working/Project) -> Engineering admission gate
# ===========================================================================

_ADMISSIBLE = {
    "kind": "root_cause", "verified": True, "protocol": "USB2", "scope": "LFPS",
    "title": "USB2 LFPS polling timeout", "root_cause": "missing sync flop on lfps_detect",
    "fix": "add 2-flop synchronizer", "confidence": "HIGH",
    "evidence": ["waveform: lfps_detect glitches across clock domains"],
}


def test_engineering_admission_gate_admits_a_fully_evidenced_record():
    admitted, reasons = engineering_admission_gate(_ADMISSIBLE)
    assert admitted is True and reasons == []


@pytest.mark.parametrize("mutation,expected_reason", [
    ({"evidence": [], "verification": {}}, "NO_EVIDENCE"),
    ({"evidence": "   ", "verification": {}}, "NO_EVIDENCE"),
    ({"confidence": "LOW"}, "CONFIDENCE_BELOW_HIGH"),
    ({"confidence": None}, "CONFIDENCE_BELOW_HIGH"),
    ({"reusable": False}, "EXPLICITLY_NOT_REUSABLE"),
    ({"root_cause": "", "fix": "", "lesson": ""}, "NO_REUSABLE_CLAIM"),
])
def test_engineering_admission_gate_names_the_specific_missing_requirement(mutation, expected_reason):
    admitted, reasons = engineering_admission_gate({**_ADMISSIBLE, **mutation})
    assert admitted is False
    assert expected_reason in reasons


def test_a_gate_validated_verification_block_satisfies_evidence_and_confidence_on_its_own():
    """Both real engineering-tier write paths in this codebase carry one of
    the two verification shapes _verification_is_gate_validated() recognizes
    -- independently gate-script-verified evidence, which is strictly stronger
    than a self-declared `confidence` label. Neither shape should need a
    separate `evidence` list or `confidence` string to clear this gate."""
    for verification in (
        {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"},
        {"targeted_reproducer_passed": True, "broader_regression_passed": True,
         "new_failures_introduced": False, "target_pre_fix_result": "FAIL",
         "target_post_fix_result": "PASS", "replay_equivalent": True},
    ):
        admitted, reasons = engineering_admission_gate({
            "kind": "verified_fix", "verified": True, "protocol": "USB2",
            "root_cause": "rc", "verification": verification,
        })
        assert admitted is True, reasons


def test_route_and_store_demotes_an_unevidenced_verified_record_to_working_memory(tmp_root):
    """The audit's live-confirmed hole: this exact record used to land in
    ENGINEERING_MEMORY on the strength of a caller-supplied `verified: True`
    alone, and was only rejected one tier later at the organizational gate."""
    result = route_and_store(tmp_root, {
        "kind": "root_cause", "verified": True, "protocol": "PCIe", "scope": "x",
        "root_cause": "unverified guess", "verification": {},
    }, cfg={})

    assert result["destination"] == "WORKING_MEMORY"
    assert result["level"] == "working"
    assert result["requested_destination"] == "ENGINEERING_MEMORY"
    assert result["engineering_admission"]["admitted"] is False
    assert set(result["engineering_admission"]["reasons"]) == {"NO_EVIDENCE", "CONFIDENCE_BELOW_HIGH"}

    # Nothing reached the engineering tier on disk, and the demoted record
    # keeps the rejection reasons so a reader can see what it still needs.
    assert not list((tmp_root / ".dv-harness" / "memory" / "engineering").glob("*.json"))
    demoted = MemoryStore(tmp_root).get(result["memory_id"])
    assert demoted["level"] == "working"
    assert demoted["engineering_admission_rejected"] == result["engineering_admission"]["reasons"]
    assert demoted["root_cause"] == "unverified guess"   # content preserved, not dropped


def test_route_and_store_still_admits_a_real_engineering_record(tmp_root):
    result = route_and_store(tmp_root, dict(_ADMISSIBLE), cfg={})
    assert result["destination"] == "ENGINEERING_MEMORY"
    assert result["level"] == "engineering"
    assert "engineering_admission" not in result
    assert MemoryStore(tmp_root).get(result["memory_id"])["level"] == "engineering"


def test_a_demoted_record_never_becomes_a_confirmation_of_an_existing_engineering_record(tmp_root):
    """confirmation_count is the organizational gate's third input. An
    unevidenced re-assertion of an existing engineering claim must not be able
    to bump it -- otherwise the admission gate could be walked around by
    re-stating a claim twice with no evidence."""
    first = route_and_store(tmp_root, dict(_ADMISSIBLE), cfg={})
    assert first["destination"] == "ENGINEERING_MEMORY"

    weak = route_and_store(tmp_root, {
        "kind": "root_cause", "verified": True, "protocol": "USB2",
        "root_cause": "missing sync flop on lfps_detect", "verification": {},
    }, cfg={})
    assert weak["destination"] == "WORKING_MEMORY"
    assert MemoryStore(tmp_root).get(first["memory_id"])["confirmation_count"] == 0


def test_engine_verified_fix_promotion_record_shape_still_clears_the_gate():
    """engine.py's _promote_verified_fix_knowledge() builds its record from
    two independently-PASSed RE_AUDIT gate scripts and sets confidence HIGH --
    the real production call site must not be blocked by this new gate."""
    admitted, reasons = engineering_admission_gate({
        "kind": "verified_fix", "verified": True, "protocol": "USB2",
        "title": "Verified fix: ep0 underrun", "root_cause": "missing prefetch guard",
        "fix": "rev 4c1f2a", "confidence": "HIGH",
        "verification": {"targeted_reproducer_passed": True, "broader_regression_passed": True,
                          "new_failures_introduced": False, "target_pre_fix_result": "FAIL",
                          "target_post_fix_result": "PASS", "replay_equivalent": True},
    })
    assert admitted is True, reasons


# ---------------------------------------------------------------------------
# 4. confirmation_count is not forgeable by the record body (2026-09-04)
#
# Re-audit of the Phase 4+5 READY verdict found the organizational gate's
# third input was self-declarable: MemoryStore.add() used
# `setdefault("confirmation_count", 0)`, so a value supplied in the record
# body passed straight through to disk, and promote_to_organizational() read
# it back as if it had been earned. A SINGLE creation event carrying
# confirmation_count=2 therefore promoted straight to ORGANIZATIONAL_MEMORY,
# defeating the one gate whose entire purpose is to require a SECOND,
# independently-derived run (CLAUDE.md: "not the same run reported twice").
# The other two gates were never forgeable this way, which is why only this
# one needed closing.
# ---------------------------------------------------------------------------

_PROMOTABLE = {
    "kind": "root_cause", "verified": True, "protocol": "USB2", "scope": "LFPS",
    "title": "USB2 LFPS polling timeout", "root_cause": "missing sync flop on lfps_detect",
    "fix": "add 2-flop synchronizer", "confidence": "HIGH",
    "evidence": ["waveform: lfps_detect glitches across clock domains"],
    "verification": {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"},
}
_HIGH_CONF = dict(independent_sources_count=3, evidence_refs_verified=True,
                  counter_evidence_count=0, multi_agent_consensus_count=2)


def test_confirmation_count_supplied_in_the_record_body_is_discarded_on_creation(tmp_root):
    result = route_and_store(tmp_root, dict(_PROMOTABLE, confirmation_count=7), cfg={})
    assert result["destination"] == "ENGINEERING_MEMORY"
    stored = MemoryStore(tmp_root).get(result["memory_id"])
    assert stored["confirmation_count"] == 0
    # last_confirmed_at is what proves it was never really confirmed: the one
    # authorized writer always sets the two together.
    assert stored["last_confirmed_at"] is None


def test_a_single_creation_event_cannot_self_declare_its_way_to_organizational(tmp_root):
    """The regression this whole section exists for: before the fix this
    promoted, on one creation event, with zero independent re-derivation."""
    result = route_and_store(
        tmp_root, dict(_PROMOTABLE, confirmation_count=ORGANIZATIONAL_MIN_CONFIRMATIONS), cfg={})
    promoted = promote_to_organizational(tmp_root, result["memory_id"], _HIGH_CONF, cfg={})
    assert promoted["promoted"] is False
    assert promoted["reason"] == "INSUFFICIENT_CONFIRMATION"
    assert promoted["confirmation_count"] == 0
    assert promoted["required"] == ORGANIZATIONAL_MIN_CONFIRMATIONS


def test_direct_memorystore_add_cannot_forge_the_counter_either(tmp_root):
    """route_and_store() is not the only door -- the guard lives in
    MemoryStore.add() itself, so seeding the store directly is also covered."""
    seeded = MemoryStore(tmp_root).add("engineering", dict(_PROMOTABLE, confirmation_count=5))
    assert seeded["confirmation_count"] == 0
    assert MemoryStore(tmp_root).get(seeded["memory_id"])["confirmation_count"] == 0


def test_only_genuine_repeated_confirmation_opens_the_organizational_gate(tmp_root):
    """The positive half: two real MemoryGC.confirm() calls -- the authorized
    writer -- still reach ORGANIZATIONAL_MEMORY. The fix must close the forged
    path without breaking the earned one."""
    store = MemoryStore(tmp_root)
    mid = route_and_store(tmp_root, dict(_PROMOTABLE), cfg={})["memory_id"]

    MemoryGC(store).confirm(mid, evidence={"independent_run": 1})
    assert store.get(mid)["confirmation_count"] == 1
    assert store.get(mid)["last_confirmed_at"] is not None
    assert promote_to_organizational(tmp_root, mid, _HIGH_CONF, cfg={})["reason"] == \
        "INSUFFICIENT_CONFIRMATION"

    MemoryGC(store).confirm(mid, evidence={"independent_run": 2})
    assert store.get(mid)["confirmation_count"] == ORGANIZATIONAL_MIN_CONFIRMATIONS
    result = promote_to_organizational(tmp_root, mid, _HIGH_CONF,
                                        cfg={"knowledge_center": {"enabled": False}})
    assert result["destination"] == "ORGANIZATIONAL_MEMORY"
    assert result["promotion_gate"]["confirmation_count"] == ORGANIZATIONAL_MIN_CONFIRMATIONS


def test_an_ordinary_re_add_neither_invents_nor_drops_confirmations(tmp_root):
    """Every non-confirm writer round-trips a record through add()
    (mark_used(), the knowledge_commit_sha write-back, MemoryGC's
    revalidation paths). Those must preserve the earned count exactly --
    zeroing them would silently un-confirm a record."""
    store = MemoryStore(tmp_root)
    mid = route_and_store(tmp_root, dict(_PROMOTABLE), cfg={})["memory_id"]
    MemoryGC(store).confirm(mid)
    MemoryGC(store).confirm(mid)

    store.mark_used(mid)
    assert store.get(mid)["confirmation_count"] == 2

    # A re-add that tries to lower the count is refused the same way one that
    # tries to raise it is: on-disk truth wins in both directions.
    store.add("engineering", dict(store.get(mid), confirmation_count=0))
    assert store.get(mid)["confirmation_count"] == 2


def test_promoted_organizational_record_carries_source_count_not_its_own(tmp_root):
    """A freshly-promoted organizational record has zero confirmations OF ITS
    OWN; the source engineering record's count is provenance and is named as
    such, so the promoted record can never look pre-confirmed.

    The organizational tier has no local file store by design -- its backing
    IS the shared Knowledge Center (memory.py's OrganizationalMemoryStore) --
    so the record is captured at that real push boundary rather than read
    back off disk."""
    store = MemoryStore(tmp_root)
    mid = route_and_store(tmp_root, dict(_PROMOTABLE), cfg={})["memory_id"]
    MemoryGC(store).confirm(mid)
    MemoryGC(store).confirm(mid)

    pushed = []
    with patch("dv_harness.memory_router.OrganizationalMemoryStore") as org_store:
        org_store.return_value.add.side_effect = lambda rec: pushed.append(rec) or {"ok": True}
        promote_to_organizational(tmp_root, mid, _HIGH_CONF, cfg={})

    assert len(pushed) == 1
    assert pushed[0]["source_confirmation_count"] == ORGANIZATIONAL_MIN_CONFIRMATIONS
    assert pushed[0]["source_engineering_memory_id"] == mid
    # The promoted record must not carry a `confirmation_count` of its own at
    # all -- the field name that the gate reads back.
    assert "confirmation_count" not in pushed[0]


# ===========================================================================
# 5. Engineering -> Organizational admission gate at the WRITE boundary
#    (2026-09-04, gap-close-obsidian-memory phase 13+14)
#
# The Phase 13 audit's disclosed residual: unlike ENGINEERING_MEMORY, whose
# route_and_store() branch is hard-gated by engineering_admission_gate(), the
# ORGANIZATIONAL_MEMORY branch had none. route_memory() sent any
# methodology/best_practice/cross_project_lesson record with verified=True
# straight to OrganizationalMemoryStore.add() -- i.e. to the shared,
# cross-user Knowledge Center -- and on a successful push minted a real vault
# git commit labelled "Organizational Memory approval", without the record
# ever clearing promote_to_organizational()'s three gates. Those gates were
# enforced only by the fact that today's two real callers happen to use it.
# ===========================================================================

_UNEARNED_ORGANIZATIONAL = {
    "kind": "methodology", "verified": True, "protocol": "USB3",
    "title": "always reconcile the sim.log epilogue before a batch clean",
}


def test_a_direct_route_and_store_can_no_longer_reach_the_shared_organizational_tier(tmp_root):
    """The regression this section exists for: the shared broker must never
    be contacted at all for a record that never cleared a gate."""
    with patch("dv_harness.memory_router.OrganizationalMemoryStore") as org_store:
        result = route_and_store(tmp_root, dict(_UNEARNED_ORGANIZATIONAL), cfg={})
    org_store.assert_not_called()

    assert result["destination"] == "WORKING_MEMORY"
    assert result["requested_destination"] == "ORGANIZATIONAL_MEMORY"
    assert result["organizational_admission"]["admitted"] is False
    assert "NO_ACTIVE_ENGINEERING_SOURCE_RECORD" in result["organizational_admission"]["reasons"]
    assert "CONFIDENCE_NOT_HIGH" in result["organizational_admission"]["reasons"]


def test_a_rejected_organizational_record_is_kept_in_working_memory_with_its_reasons(tmp_root):
    """Demotion, not a raise and not a drop -- the same contract the
    engineering gate already uses. The content is real; it just has not
    earned the shared tier, and the record itself says why."""
    result = route_and_store(tmp_root, dict(_UNEARNED_ORGANIZATIONAL), cfg={})
    stored = MemoryStore(tmp_root).get(result["memory_id"])
    assert stored["level"] == "working"
    assert stored["requested_destination"] == "ORGANIZATIONAL_MEMORY"
    assert "NO_ACTIVE_ENGINEERING_SOURCE_RECORD" in stored["organizational_admission_rejected"]


def test_no_vault_note_or_commit_is_minted_for_a_record_that_never_cleared_the_gate(tmp_root):
    """Phase 13's commit policy names "Organizational Memory approval" as a
    real commit trigger. A rejected record must therefore produce no vault
    note at all -- WORKING_MEMORY is excluded from
    _VAULT_WRITE_THROUGH_DESTINATIONS by construction, so the demotion is
    what makes that true."""
    cfg = {"knowledge_center": {"enabled": False},
           "memory": {"vault_path": "", "git_enabled": False}}
    result = route_and_store(tmp_root, dict(_UNEARNED_ORGANIZATIONAL), cfg=cfg)
    assert "vault_write" not in result
    vault = tmp_root / ".dv-harness" / "vault"
    assert not vault.exists() or not list(vault.rglob("*.md"))


def test_the_gate_reads_confirmation_count_off_the_store_never_off_the_payload(tmp_root):
    """The one gate input a payload could otherwise self-declare. The source
    record here is real, ACTIVE, engineering-tier and gate-validated -- only
    the repeated confirmation is missing, and the record claims to have it."""
    source_id = route_and_store(tmp_root, dict(_PROMOTABLE), cfg={})["memory_id"]
    assert MemoryStore(tmp_root).get(source_id)["confirmation_count"] == 0

    forged = dict(_UNEARNED_ORGANIZATIONAL,
                  confidence_result={"level": "HIGH", "score": 10},
                  source_confirmation_count=ORGANIZATIONAL_MIN_CONFIRMATIONS + 5,
                  source_engineering_memory_id=source_id)
    result = route_and_store(tmp_root, forged, cfg={})
    assert result["destination"] == "WORKING_MEMORY"
    assert result["organizational_admission"]["reasons"] == ["INSUFFICIENT_CONFIRMATION"]


def test_the_gate_rejects_provenance_pointing_at_a_record_that_never_passed_its_own_gates(tmp_root):
    """A source record with two REAL confirmations but no gate-validated
    verification block is still not promotable -- the qualitative gate is
    re-read from that record, not trusted from the promoted payload."""
    store = MemoryStore(tmp_root)
    unvalidated = store.add("engineering", {
        "title": "no verification block", "protocol": "USB3", "root_cause": "guess",
    })["memory_id"]
    MemoryGC(store).confirm(unvalidated)
    MemoryGC(store).confirm(unvalidated)

    result = route_and_store(tmp_root, dict(
        _UNEARNED_ORGANIZATIONAL,
        confidence_result={"level": "HIGH"},
        # A gate-validated block on the PROMOTED record does not help: the
        # gate reads the source record's own.
        verification={"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"},
        source_engineering_memory_id=unvalidated), cfg={})
    assert result["destination"] == "WORKING_MEMORY"
    assert result["organizational_admission"]["reasons"] == ["QUALITATIVE_GATE_FAILED"]


def test_a_retracted_source_record_can_no_longer_carry_a_promotion(tmp_root):
    """Provenance is only as good as the record it points at: retracting the
    source (MemoryGC's real lifecycle) must close the gate again, not leave
    an already-minted stamp valid forever."""
    store = MemoryStore(tmp_root)
    source_id = route_and_store(tmp_root, dict(_PROMOTABLE), cfg={})["memory_id"]
    MemoryGC(store).confirm(source_id)
    MemoryGC(store).confirm(source_id)
    record = dict(_UNEARNED_ORGANIZATIONAL, confidence_result={"level": "HIGH"},
                  source_engineering_memory_id=source_id)

    admitted, reasons = organizational_admission_gate(tmp_root, record)
    assert (admitted, reasons) == (True, [])

    MemoryGC(store).retract(source_id, reason="superseded by a later RTL revision")
    admitted, reasons = organizational_admission_gate(tmp_root, record)
    assert admitted is False
    assert reasons == ["NO_ACTIVE_ENGINEERING_SOURCE_RECORD"]


def test_the_earned_promotion_path_still_clears_the_write_boundary_gate(tmp_root):
    """The positive half: promote_to_organizational() stamps exactly the
    provenance this gate re-reads, so closing the bypass must not close the
    one sanctioned door. Asserted at the real push boundary."""
    store = MemoryStore(tmp_root)
    source_id = route_and_store(tmp_root, dict(_PROMOTABLE), cfg={})["memory_id"]
    MemoryGC(store).confirm(source_id, evidence={"independent_run": 1})
    MemoryGC(store).confirm(source_id, evidence={"independent_run": 2})

    pushed = []
    with patch("dv_harness.memory_router.OrganizationalMemoryStore") as org_store:
        org_store.return_value.add.side_effect = lambda rec: pushed.append(rec) or {"ok": True}
        result = promote_to_organizational(tmp_root, source_id, _HIGH_CONF, cfg={})

    assert result["destination"] == "ORGANIZATIONAL_MEMORY"
    assert len(pushed) == 1
    assert pushed[0]["source_engineering_memory_id"] == source_id
