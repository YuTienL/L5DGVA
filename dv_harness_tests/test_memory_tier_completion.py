import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from dv_harness.memory import (
    MemoryStore, MemoryRetriever, MemoryConsolidator, MemoryGC, CornerCaseLibrary,
    JobMemoryStore, ProjectMemoryStore, WorkingMemoryStore, OrganizationalMemoryStore,
)
from dv_harness.memory_router import route_and_store
from dv_harness.knowledge_center import RESULT_MARKER


def test_job_memory_store_round_trips_through_real_filesystem():
    tmp = Path(tempfile.mkdtemp())
    try:
        rec = JobMemoryStore(tmp).add({
            "title": "LSF rerun blocked by build/config identity drift",
            "protocol": "USB2", "scope": "regression", "job_id": "J-TEST-1",
            "root_cause": "rerun batch mixed two different build IDs across seeds",
        })
        mid = rec["memory_id"]
        assert (tmp / ".dv-harness" / "memory" / "job" / f"{mid}.json").exists()

        fetched = JobMemoryStore(tmp).get(mid)
        assert fetched is not None
        assert fetched["level"] == "job"
        assert fetched["title"] == "LSF rerun blocked by build/config identity drift"

        # not visible under a different tier's accessor
        assert ProjectMemoryStore(tmp).get(mid) is None
    finally:
        shutil.rmtree(tmp)


def test_project_memory_store_round_trips_through_real_filesystem():
    tmp = Path(tempfile.mkdtemp())
    try:
        rec = ProjectMemoryStore(tmp).add({
            "title": "USB subsystem VIP/DUT topology",
            "protocol": "USB2", "scope": "subsystem",
            "topology": "Host/device dual-role VIP wraps DUT PHY via UTMI+ interface",
        })
        mid = rec["memory_id"]
        p = tmp / ".dv-harness" / "memory" / "project" / f"{mid}.json"
        assert p.exists()

        fetched = ProjectMemoryStore(tmp).get(mid)
        assert fetched["level"] == "project"
        assert fetched["topology"].startswith("Host/device")

        ProjectMemoryStore(tmp).mark_used(mid)
        assert ProjectMemoryStore(tmp).get(mid)["reuse_count"] == 1
    finally:
        shutil.rmtree(tmp)


def test_working_memory_store_round_trips_through_real_filesystem():
    tmp = Path(tempfile.mkdtemp())
    try:
        rec = WorkingMemoryStore(tmp).add({
            "title": "Working-memory tier backing-store completeness seed",
            "scope": "subsystem",
        })
        mid = rec["memory_id"]
        assert (tmp / ".dv-harness" / "memory" / "working" / f"{mid}.json").exists()
        assert WorkingMemoryStore(tmp).get(mid)["level"] == "working"
    finally:
        shutil.rmtree(tmp)


def test_organizational_memory_store_degrades_gracefully_when_kc_not_configured():
    # organizational_memory is backed by the shared KnowledgeCenterClient, not
    # a local file store -- with knowledge_center disabled (this project's
    # real default), add()/search() must return an honest {"ok": False, ...}
    # instead of raising or silently no-opping.
    tmp = Path(tempfile.mkdtemp())
    try:
        cfg = {"knowledge_center": {"enabled": False, "remote_root": ""}}
        store = OrganizationalMemoryStore(tmp, cfg=cfg)
        assert store.configured() is False
        with patch("subprocess.run") as mock_run:
            add_result = store.add({"title": "cross-project lesson", "scope": "organizational"})
            search_result = store.search({"text": "lesson"})
        assert add_result == {"ok": False, "error": "NOT_CONFIGURED"}
        assert search_result == {"ok": False, "error": "NOT_CONFIGURED"}
        mock_run.assert_not_called()
        # no local .dv-harness/memory/organizational file store is created
        org_dir = tmp / ".dv-harness" / "memory" / "organizational"
        assert not org_dir.exists() or not any(org_dir.glob("*.json"))
    finally:
        shutil.rmtree(tmp)


def test_organizational_memory_store_add_and_search_round_trip_through_real_kc_transport(monkeypatch):
    # Exercises the real KnowledgeCenterClient transport/result-marker
    # parsing plumbing end-to-end, proving OrganizationalMemoryStore.add()/
    # search() correctly delegate to it and forward the record's protocol.
    #
    # REAL BUG FIX (2026-09-01, dv_harness/knowledge_center.py's _invoke()
    # rewrite, commit 7ae3a28): rewritten to exercise the new
    # credential-free persistent-relay transport against a real local fake
    # relay server (mirroring dv_harness_tests/test_knowledge_center.py's
    # own _FakeRelayServer pattern) instead of mocking subprocess.run()
    # against the old hop_script-direct-invocation transport (which read
    # VCPW from its own process env -- the real risk this rewrite closed).
    import socket as _socket
    import threading as _threading

    tmp = Path(tempfile.mkdtemp())
    localappdata_tmp = Path(tempfile.mkdtemp())
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata_tmp))
    remote_dir = str(Path(__file__).resolve().parents[1] / "tools" / "remote")
    if remote_dir not in sys.path:
        sys.path.insert(0, remote_dir)
    from remote_relay import info_path

    def _run_against_fake_relay(responses):
        server_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(len(responses))
        port = server_sock.getsockname()[1]
        received = []

        def _serve():
            for resp in responses:
                conn, _ = server_sock.accept()
                buf = b""
                while b"\n" not in buf:
                    buf += conn.recv(65536)
                req = json.loads(buf.decode("utf-8"))
                if req.get("op") == "put":
                    try:
                        req["_local_content"] = Path(req["local"]).read_text(encoding="utf-8")
                    except OSError:
                        req["_local_content"] = None
                received.append(req)
                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
                conn.close()

        t = _threading.Thread(target=_serve)
        t.start()

        p = info_path("vchost-b", "host-c")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"host": "127.0.0.1", "port": port, "token": "tok",
                                  "pid": 1, "started": "2026-09-01T00:00:00"}), encoding="utf-8")
        return t, server_sock, received

    try:
        cfg = {"knowledge_center": {"enabled": True, "remote_root": "/srv/kc",
                                     "vchost": "vchost-b", "vchop": "host-c"}}
        store = OrganizationalMemoryStore(tmp, cfg=cfg)
        assert store.configured() is True

        t, server_sock, received = _run_against_fake_relay([
            {"ok": True, "exit_code": 0, "stdout": "", "error": ""},  # put
            {"ok": True, "exit_code": 0, "stdout": f'{RESULT_MARKER}{{"memory_id": "KC-1"}}\n', "error": ""},  # run
        ])
        try:
            add_result = store.add({
                "title": "One submitted LSF job = one isolated Job Agent context",
                "protocol": "USB2", "scope": "organizational",
            })
        finally:
            t.join(timeout=5)
            server_sock.close()

        assert add_result["ok"] is True
        assert add_result["memory_id"] == "KC-1"
        payload = json.loads(received[0]["_local_content"])
        assert payload["category"] == "_general"
        assert payload["protocol"] == "USB2"
        assert payload["record"]["title"] == "One submitted LSF job = one isolated Job Agent context"

        t2, server_sock2, _received2 = _run_against_fake_relay([
            {"ok": True, "exit_code": 0, "stdout": "", "error": ""},  # put
            {"ok": True, "exit_code": 0,
             "stdout": f'{RESULT_MARKER}{{"count": 1, "records": [{{"memory_id": "KC-1"}}]}}\n',
             "error": ""},  # run
        ])
        try:
            search_result = store.search({"text": "job agent"})
        finally:
            t2.join(timeout=5)
            server_sock2.close()

        assert search_result["ok"] is True
        assert search_result["records"][0]["memory_id"] == "KC-1"
    finally:
        shutil.rmtree(tmp)
        shutil.rmtree(localappdata_tmp)


def test_all_five_memory_levels_get_a_real_directory_on_first_use():
    tmp = Path(tempfile.mkdtemp())
    try:
        MemoryStore(tmp)
        base = tmp / ".dv-harness" / "memory"
        for level in ("working", "job", "project", "engineering", "organizational"):
            assert (base / level).is_dir()
    finally:
        shutil.rmtree(tmp)


def test_route_and_store_actually_uses_the_named_tier_classes_not_just_the_base_store():
    # Regression test (2026-08-29, memory-tier-completion wiring): before this
    # fix, WorkingMemoryStore/JobMemoryStore/ProjectMemoryStore/
    # OrganizationalMemoryStore were only ever constructed by THIS test file --
    # the real engine flow (engine.py -> memory_router.route_and_store) wrote
    # every level through the bare MemoryStore(root).add(level, record) call,
    # bypassing all four named classes entirely. Prove the real routing entry
    # point now dispatches through the tier classes: patch each class's add()
    # and confirm route_and_store() for the matching kind calls it exactly
    # once, with the raw record (not a level string).
    tmp = Path(tempfile.mkdtemp())
    try:
        with patch.object(JobMemoryStore, "add", autospec=True) as job_add:
            job_add.return_value = {"memory_id": "MEM-JOB", "level": "job"}
            result = route_and_store(tmp, {"kind": "job_result", "job_id": "J-1"})
            assert result == {"destination": "JOB_MEMORY", "level": "job", "memory_id": "MEM-JOB"}
            job_add.assert_called_once()
            assert job_add.call_args[0][1] == {"kind": "job_result", "job_id": "J-1"}

        with patch.object(ProjectMemoryStore, "add", autospec=True) as project_add:
            project_add.return_value = {"memory_id": "MEM-PROJ", "level": "project"}
            result = route_and_store(tmp, {"kind": "project_fact", "verified": True, "title": "t"})
            assert result["destination"] == "PROJECT_MEMORY"
            project_add.assert_called_once()

        with patch.object(WorkingMemoryStore, "add", autospec=True) as working_add:
            working_add.return_value = {"memory_id": "MEM-WORK", "level": "working"}
            result = route_and_store(tmp, {"kind": "unclassified_note"})
            assert result["destination"] == "WORKING_MEMORY"
            working_add.assert_called_once()

        with patch.object(OrganizationalMemoryStore, "add", autospec=True) as org_add:
            org_add.return_value = {"ok": True, "memory_id": "KC-1"}
            result = route_and_store(tmp, {"kind": "methodology", "verified": True, "title": "t"})
            assert result == {"destination": "ORGANIZATIONAL_MEMORY", "ok": True, "memory_id": "KC-1"}
            org_add.assert_called_once()
    finally:
        shutil.rmtree(tmp)


def test_lsf_reconcile_writes_a_job_tier_memory_record():
    # Task 9 (poster-gap-closing round 2): the real lsf-reconcile path
    # (dv_harness.lsf_client.reconcile_batch, the same function cli.py's
    # `lsf-reconcile` subcommand calls) previously only ever persisted the
    # per-job JobState JSON file -- nothing wrote to the Job memory tier, so
    # a submitted LSF job's outcome was never captured as reusable memory.
    # reconcile_job's own CRITICAL "sim_status"->"ANALYSIS_OWED" discrepancy
    # (fired the moment a job's live LSF status reaches DONE/EXIT while
    # sim_status is still UNKNOWN/RUNNING) is the real, structurally-
    # guaranteed signal used here -- not a fabricated trigger.
    from dv_harness import lsf_client
    tmp = Path(tempfile.mkdtemp())
    try:
        lsf_client.save_job_state(
            tmp, lsf_client.JobState(job_id=501, lsf_status="RUN", sim_status="UNKNOWN",
                                      pattern="usb2_hs_basic"))
        payload = json.dumps({"RECORDS": [{"JOBID": "501", "STAT": "DONE"}]})
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=MagicMock(stdout=payload, stderr="", returncode=0)):
            lsf_client.reconcile_batch(tmp, [501])

        job_store = JobMemoryStore(tmp)
        rows = [r for r in job_store.store._index() if r.get("level") == "job"]
        assert rows, f"no Job Memory record written by lsf-reconcile: {job_store.store._index()}"
        rec = job_store.get(rows[0]["memory_id"])
        assert rec is not None
        assert rec["job_id"] == 501
        assert rec["lsf_status"] == "DONE"
        assert rec["pattern"] == "usb2_hs_basic"
        assert rec["kind"] == "job_result"  # no failure signal in this fixture (no uvm_fatal/EXIT)
    finally:
        shutil.rmtree(tmp)


def test_lsf_reconcile_writes_a_job_failure_tier_memory_record_on_real_failure_signal():
    # Same trigger, but a genuine failure signal already present in the
    # JobState (uvm_fatal_count>0) must route as job_failure, not job_result
    # -- classification is derived from real evidence already on the state,
    # never guessed.
    from dv_harness import lsf_client
    tmp = Path(tempfile.mkdtemp())
    try:
        lsf_client.save_job_state(
            tmp, lsf_client.JobState(job_id=502, lsf_status="RUN", sim_status="UNKNOWN",
                                      uvm_fatal_count=1))
        payload = json.dumps({"RECORDS": [{"JOBID": "502", "STAT": "DONE"}]})
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=MagicMock(stdout=payload, stderr="", returncode=0)):
            lsf_client.reconcile_batch(tmp, [502])

        job_store = JobMemoryStore(tmp)
        rows = [r for r in job_store.store._index() if r.get("level") == "job"]
        assert rows
        rec = job_store.get(rows[0]["memory_id"])
        assert rec["kind"] == "job_failure"
        assert rec["job_id"] == 502
    finally:
        shutil.rmtree(tmp)


def test_lsf_reconcile_is_idempotent_across_repeated_polls_of_the_same_stuck_job():
    # Finding I3 (2026-08-31 fix wave): lsf-reconcile is DESIGNED to be
    # polled repeatedly (unlike _promote_experience_knowledge, which fires
    # once per stage PASS) -- reconcile_job's CRITICAL sim_status->
    # ANALYSIS_OWED discrepancy keeps firing on EVERY reconcile_batch() call
    # while a job stays stuck at sim_status UNKNOWN with a terminal live LSF
    # status. Before the fix, each poll minted a fresh memory_id, so 3
    # reconciles of the same stuck job produced 3 duplicate Job-tier
    # records. Reconcile the SAME stuck job 3 times and assert exactly ONE
    # Job-tier record exists afterward, not three.
    from dv_harness import lsf_client
    tmp = Path(tempfile.mkdtemp())
    try:
        lsf_client.save_job_state(
            tmp, lsf_client.JobState(job_id=504, lsf_status="RUN", sim_status="UNKNOWN",
                                      pattern="usb2_hs_basic"))
        payload = json.dumps({"RECORDS": [{"JOBID": "504", "STAT": "DONE"}]})
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=MagicMock(stdout=payload, stderr="", returncode=0)):
            lsf_client.reconcile_batch(tmp, [504])
            lsf_client.reconcile_batch(tmp, [504])
            lsf_client.reconcile_batch(tmp, [504])

        job_store = JobMemoryStore(tmp)
        rows = [r for r in job_store.store._index() if r.get("level") == "job" and r.get("path")]
        job_504_rows = [r for r in rows
                        if (job_store.get(r["memory_id"]) or {}).get("job_id") == 504]
        assert len(job_504_rows) == 1, (
            f"expected exactly one Job-tier record after 3 reconciles of the "
            f"same stuck job, found {len(job_504_rows)}: {job_504_rows}")

        # The single record itself must be present and correct, not merely
        # "count == 1 by accident" -- it must be the real record content.
        rec = job_store.get(job_504_rows[0]["memory_id"])
        assert rec["job_id"] == 504
        assert rec["lsf_status"] == "DONE"
        assert rec["kind"] == "job_result"

        # Same guarantee at the on-disk file level: exactly one file under
        # the job/ tier directory for this job, not three separate files.
        job_dir = tmp / ".dv-harness" / "memory" / "job"
        job_files = [
            p for p in job_dir.glob("*.json")
            if json.loads(p.read_text(encoding="utf-8")).get("job_id") == 504
        ]
        assert len(job_files) == 1, f"expected 1 file on disk, found {len(job_files)}: {job_files}"
    finally:
        shutil.rmtree(tmp)


def test_lsf_reconcile_does_not_write_job_tier_memory_when_no_terminal_signal():
    # A live RUN status (not DONE/EXIT) never fires reconcile_job's CRITICAL
    # ANALYSIS_OWED discrepancy -- no job outcome exists yet, so no Job
    # Memory record should be written.
    from dv_harness import lsf_client
    tmp = Path(tempfile.mkdtemp())
    try:
        lsf_client.save_job_state(tmp, lsf_client.JobState(job_id=503, lsf_status="PEND"))
        payload = json.dumps({"RECORDS": [{"JOBID": "503", "STAT": "RUN"}]})
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=MagicMock(stdout=payload, stderr="", returncode=0)):
            lsf_client.reconcile_batch(tmp, [503])

        job_store = JobMemoryStore(tmp)
        rows = [r for r in job_store.store._index() if r.get("level") == "job"]
        assert rows == []
    finally:
        shutil.rmtree(tmp)


def test_lsf_reconcile_extracts_seed_and_fsdb_path_from_options_when_present():
    # memory-engine-schema-completion audit (2026-09-01): "seed"/"fsdb_path"
    # are extracted from JobState.options -- the one real field that can
    # carry them -- only when the caller's own options text genuinely
    # contains one of the documented markers (never guessed).
    from dv_harness import lsf_client
    tmp = Path(tempfile.mkdtemp())
    try:
        lsf_client.save_job_state(
            tmp, lsf_client.JobState(
                job_id=505, lsf_status="RUN", sim_status="UNKNOWN", pattern="usb2_hs_basic",
                options="+ntb_random_seed=778812 +fsdb_file=/proj/run/fsdb/505.fsdb"))
        payload = json.dumps({"RECORDS": [{"JOBID": "505", "STAT": "DONE"}]})
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=MagicMock(stdout=payload, stderr="", returncode=0)):
            lsf_client.reconcile_batch(tmp, [505])

        job_store = JobMemoryStore(tmp)
        rows = [r for r in job_store.store._index() if r.get("level") == "job"]
        assert rows
        rec = job_store.get(rows[0]["memory_id"])
        assert rec["seed"] == "778812"
        assert rec["fsdb_path"] == "/proj/run/fsdb/505.fsdb"
    finally:
        shutil.rmtree(tmp)


def test_lsf_reconcile_extracts_seed_only_with_bare_seed_marker():
    from dv_harness import lsf_client
    tmp = Path(tempfile.mkdtemp())
    try:
        lsf_client.save_job_state(
            tmp, lsf_client.JobState(
                job_id=507, lsf_status="RUN", sim_status="UNKNOWN", options="seed=42 +UVM_VERBOSITY=UVM_LOW"))
        payload = json.dumps({"RECORDS": [{"JOBID": "507", "STAT": "DONE"}]})
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=MagicMock(stdout=payload, stderr="", returncode=0)):
            lsf_client.reconcile_batch(tmp, [507])

        job_store = JobMemoryStore(tmp)
        rows = [r for r in job_store.store._index() if r.get("level") == "job"]
        rec = job_store.get(rows[0]["memory_id"])
        assert rec["seed"] == "42"
        assert "fsdb_path" not in rec
    finally:
        shutil.rmtree(tmp)


def test_lsf_reconcile_omits_seed_and_fsdb_path_when_not_available_at_call_site():
    # Honest residual-gap behavior: when options carries neither marker (the
    # common case -- e.g. register_external_job()-style registration, or a
    # plain --options string with no seed/fsdb markers), the keys must be
    # OMITTED entirely, never written as a None placeholder that would look
    # like the schema captured this data when it did not.
    from dv_harness import lsf_client
    tmp = Path(tempfile.mkdtemp())
    try:
        lsf_client.save_job_state(
            tmp, lsf_client.JobState(job_id=506, lsf_status="RUN", sim_status="UNKNOWN",
                                      pattern="usb2_hs_basic"))
        payload = json.dumps({"RECORDS": [{"JOBID": "506", "STAT": "DONE"}]})
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=MagicMock(stdout=payload, stderr="", returncode=0)):
            lsf_client.reconcile_batch(tmp, [506])

        job_store = JobMemoryStore(tmp)
        rows = [r for r in job_store.store._index() if r.get("level") == "job"]
        rec = job_store.get(rows[0]["memory_id"])
        assert "seed" not in rec
        assert "fsdb_path" not in rec
    finally:
        shutil.rmtree(tmp)


def test_extract_seed_and_fsdb_helpers_directly():
    from dv_harness.lsf_client import extract_seed_from_options, extract_fsdb_path_from_options
    assert extract_seed_from_options(None) is None
    assert extract_seed_from_options("+UVM_TESTNAME=foo") is None
    assert extract_seed_from_options("+ntb_random_seed=123") == "123"
    assert extract_seed_from_options("SEED: 999") == "999"
    assert extract_fsdb_path_from_options(None) is None
    assert extract_fsdb_path_from_options("+ntb_random_seed=1") is None
    assert extract_fsdb_path_from_options("+fsdb_file=/a/b/c.fsdb") == "/a/b/c.fsdb"


def test_preexisting_engineering_memory_and_corner_case_behavior_is_unchanged():
    # Exercises the same pre-existing MemoryStore/MemoryConsolidator/MemoryGC/
    # CornerCaseLibrary paths as dv_harness_tests/test_engine_gates_and_routing.py
    # to confirm the new tier accessors did not alter existing behavior.
    tmp = Path(tempfile.mkdtemp())
    try:
        finding = {
            "title": "USB2 HS scoreboard port ownership", "status": "CLOSED",
            "protocol": "USB2", "scope": "subsystem", "root_cause": "global expected queue",
            "fix": "per-port expected queue", "finding_id": "F-1",
        }
        verification = {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"}
        store = MemoryStore(tmp)
        mem = MemoryConsolidator(store).from_closed_finding(finding, verification)
        assert mem["level"] == "engineering"
        assert mem["confidence"] == "CONFIRMED"

        hits = MemoryRetriever(store).search({"protocol": "USB2", "text": "scoreboard"})
        assert any(h["memory"]["memory_id"] == mem["memory_id"] for h in hits)

        assert MemoryGC(store).deprecate(mem["memory_id"], "superseded") is True
        assert store.get(mem["memory_id"])["status"] == "DEPRECATED"

        lib = CornerCaseLibrary(tmp)
        cc = lib.add({"corner_id": "cc-x", "protocol": "USB2", "category": "reset_power", "risk_tier": "P1"})
        assert lib.get(cc["ccl_id"])["protocol"] == "USB2"
    finally:
        shutil.rmtree(tmp)
