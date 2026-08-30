import json
import shutil
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


def test_organizational_memory_store_add_and_search_round_trip_through_real_kc_transport():
    # Exercises the real KnowledgeCenterClient transport/result-marker parsing
    # plumbing end-to-end (same fake-hop-script mocking convention as
    # dv_harness_tests/test_knowledge_center.py's
    # test_client_parses_result_marker_out_of_noisy_stdout), proving
    # OrganizationalMemoryStore.add()/search() correctly delegate to it and
    # forward the record's protocol.
    tmp = Path(tempfile.mkdtemp())
    try:
        cfg = {"knowledge_center": {"enabled": True, "remote_root": "/srv/kc", "hop_script": __file__}}
        store = OrganizationalMemoryStore(tmp, cfg=cfg)
        assert store.configured() is True

        captured = {}

        def fake_run(cmd, **kwargs):
            local_tmp = cmd[3]  # [sys.executable, hop, "--put", local_tmp, remote_tmp, remote_cmd]
            captured["payload"] = json.loads(Path(local_tmp).read_text(encoding="utf-8"))
            return MagicMock(returncode=0, stdout=f'{RESULT_MARKER}{{"memory_id": "KC-1"}}\n', stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            add_result = store.add({
                "title": "One submitted LSF job = one isolated Job Agent context",
                "protocol": "USB2", "scope": "organizational",
            })
        assert add_result["ok"] is True
        assert add_result["memory_id"] == "KC-1"
        assert captured["payload"]["category"] == "_general"
        assert captured["payload"]["protocol"] == "USB2"
        assert captured["payload"]["record"]["title"] == "One submitted LSF job = one isolated Job Agent context"

        noisy_stdout = f'{RESULT_MARKER}{{"count": 1, "records": [{{"memory_id": "KC-1"}}]}}\n'
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=noisy_stdout, stderr="")):
            search_result = store.search({"text": "job agent"})
        assert search_result["ok"] is True
        assert search_result["records"][0]["memory_id"] == "KC-1"
    finally:
        shutil.rmtree(tmp)


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
