"""Tests for the shared, cross-user knowledge center feature:
- dv_harness/config.py's `knowledge_center` config block
- dv_harness/memory.py's staleness/correction lifecycle (supersede/retract/
  flag_stale/confirm) on MemoryGC and CornerCaseLibrary
- dv_harness/gates.py's `_ccl_reuse_verified` revalidate_by expiry check
- dv_harness/memory_router.py's opt-in best-effort push to the shared store
- dv_harness/knowledge_center.py's KnowledgeCenterClient transport parsing
- tools/knowledge_center/broker.py, the server-side script, run for real as
  a subprocess against a local temp directory (mirrors how gate scripts are
  already tested elsewhere in this suite -- they're stdlib-only, argparse/
  json/pathlib CLI programs, exercised via subprocess, not imported).
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

from dv_harness.config import load_config, DEFAULT_CONFIG
from dv_harness.memory import MemoryStore, MemoryGC, CornerCaseLibrary, CornerCaseLibraryConsolidator
from dv_harness.memory_router import route_and_store
from dv_harness.gates import _ccl_reuse_verified
from dv_harness.knowledge_center import KnowledgeCenterClient, RESULT_MARKER, maybe_push_to_shared

ROOT = Path(__file__).resolve().parents[1]
BROKER = ROOT / "tools" / "knowledge_center" / "broker.py"


def _tmp():
    return Path(tempfile.mkdtemp())


# --- config ------------------------------------------------------------------

def test_default_config_has_knowledge_center_block_disabled_and_empty():
    kc = DEFAULT_CONFIG["knowledge_center"]
    assert kc["enabled"] is False
    assert kc["remote_root"] == ""
    assert "usb" in kc["categories"] and "_general" in kc["categories"]


def test_load_config_merges_knowledge_center_defaults_for_fresh_project():
    tmp = _tmp()
    try:
        cfg = load_config(tmp)
        assert cfg["knowledge_center"]["enabled"] is False
        assert cfg["knowledge_center"]["remote_root"] == ""
    finally:
        shutil.rmtree(tmp)


# --- memory.py lifecycle -------------------------------------------------------

def test_memory_gc_supersede_retract_flag_stale_confirm():
    tmp = _tmp()
    try:
        store = MemoryStore(tmp)
        mem = store.add("engineering", {"title": "root cause X", "kind": "root_cause"})
        gc = MemoryGC(store)

        assert gc.flag_stale(mem["memory_id"], "aged past policy window") is True
        assert store.get(mem["memory_id"])["status"] == "NEEDS_REVALIDATION"

        assert gc.confirm(mem["memory_id"], evidence={"resim": "pass"}) is True
        refreshed = store.get(mem["memory_id"])
        assert refreshed["status"] == "ACTIVE"
        assert refreshed["confirmation_count"] == 1
        assert refreshed["last_confirmed_at"] is not None

        assert gc.retract(mem["memory_id"], "wrong root cause", {"counter_evidence": "..."}) is True
        assert store.get(mem["memory_id"])["status"] == "RETRACTED"

        mem2 = store.add("engineering", {"title": "root cause Y"})
        assert gc.supersede(mem2["memory_id"], mem["memory_id"], "better fix found") is True
        rec2 = store.get(mem2["memory_id"])
        assert rec2["status"] == "SUPERSEDED"
        assert rec2["superseded_by"] == mem["memory_id"]

        assert gc.retract("MEM-DOES-NOT-EXIST", "x") is False
    finally:
        shutil.rmtree(tmp)


def test_corner_case_library_supersede_retract_flag_stale_confirm():
    tmp = _tmp()
    try:
        lib = CornerCaseLibrary(tmp)
        rec = lib.add({"corner_id": "cc1", "protocol": "USB", "category": "reset_power", "risk_tier": "P1"})
        ccl_id = rec["ccl_id"]
        assert rec["provenance"] is None  # local-only record, no shared-center provenance
        assert rec["revalidate_by"] is None  # no expiry unless the caller set one

        assert lib.flag_stale(ccl_id, "policy window elapsed") is True
        assert lib.get(ccl_id)["status"] == "NEEDS_REVALIDATION"

        assert lib.confirm(ccl_id, evidence={"resim": "pass"}) is True
        refreshed = lib.get(ccl_id)
        assert refreshed["status"] == "ACTIVE"
        assert refreshed["confirmation_count"] == 1

        assert lib.retract(ccl_id, "false positive", {"note": "misclassified"}) is True
        assert lib.get(ccl_id)["status"] == "RETRACTED"
        assert not any(h["corner_case"]["ccl_id"] == ccl_id for h in lib.search({"protocol": "USB"}))

        rec2 = lib.add({"corner_id": "cc2", "protocol": "USB", "category": "reset_power", "risk_tier": "P1"})
        assert lib.supersede(rec2["ccl_id"], ccl_id, "merged into older entry") is True
        assert lib.get(rec2["ccl_id"])["status"] == "SUPERSEDED"

        assert lib.retract("CCL-NOPE", "x") is False
    finally:
        shutil.rmtree(tmp)


# --- gates.py staleness-aware reuse check --------------------------------------

def test_ccl_reuse_verified_rejects_expired_revalidate_by():
    lib = CornerCaseLibrary(ROOT)
    consolidator = CornerCaseLibraryConsolidator(lib)
    rec = consolidator.from_resolved_corner_case(
        {"corner_id": "kc-stale-1", "protocol": "USB", "category": "reset_power", "risk_tier": "P1"},
        {"test_mapping": "usb_x", "semantic_verdict": "TRUE_PASS", "runtime_evidence_hash": "abc"},
    )
    ccl_id = rec["ccl_id"]
    try:
        # Fresh record, no expiry set -> still trusted (backward compatible).
        assert _ccl_reuse_verified(ROOT, ccl_id) is True

        # Manually age it out, as the broker's `confirm`/`add` would via
        # revalidate_by, without going through the shared transport.
        stale = lib.get(ccl_id)
        stale["revalidate_by"] = time.time() - 3600
        lib.add(stale)
        assert _ccl_reuse_verified(ROOT, ccl_id) is False

        # Confirming it (fresh evidence) must restore reuse-eligibility.
        lib.confirm(ccl_id)
        fresh = lib.get(ccl_id)
        fresh["revalidate_by"] = time.time() + 3600
        lib.add(fresh)
        assert _ccl_reuse_verified(ROOT, ccl_id) is True
    finally:
        (lib.dir / f"{ccl_id}.json").unlink(missing_ok=True)
        rows = [r for r in lib._index() if r.get("ccl_id") != ccl_id]
        lib._save_index(rows)


def test_ccl_reuse_verified_rejects_retracted_status():
    lib = CornerCaseLibrary(ROOT)
    consolidator = CornerCaseLibraryConsolidator(lib)
    rec = consolidator.from_resolved_corner_case(
        {"corner_id": "kc-retract-1", "protocol": "USB", "category": "reset_power", "risk_tier": "P1"},
        {"test_mapping": "usb_y", "semantic_verdict": "TRUE_PASS", "runtime_evidence_hash": "def"},
    )
    ccl_id = rec["ccl_id"]
    try:
        assert _ccl_reuse_verified(ROOT, ccl_id) is True
        lib.retract(ccl_id, "found wrong")
        assert _ccl_reuse_verified(ROOT, ccl_id) is False
    finally:
        (lib.dir / f"{ccl_id}.json").unlink(missing_ok=True)
        rows = [r for r in lib._index() if r.get("ccl_id") != ccl_id]
        lib._save_index(rows)


# --- memory_router.py opt-in shared push ---------------------------------------

def test_route_and_store_without_cfg_never_touches_knowledge_center():
    tmp = _tmp()
    try:
        result = route_and_store(tmp, {
            "kind": "root_cause", "verified": True, "title": "t",
        })
        assert "shared_push" not in result
    finally:
        shutil.rmtree(tmp)


def test_route_and_store_with_knowledge_center_disabled_is_a_noop():
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False}}
        result = route_and_store(tmp, {"kind": "root_cause", "verified": True, "title": "t"}, cfg=cfg)
        assert "shared_push" not in result
    finally:
        shutil.rmtree(tmp)


def test_route_and_store_with_knowledge_center_enabled_attempts_shared_push():
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": True, "sync_on_promote": True,
                                     "remote_root": "/srv/kc", "hop_script": "/nonexistent/remote_hop.py"}}
        result = route_and_store(tmp, {"kind": "root_cause", "verified": True, "title": "t",
                                        "protocol": "usb", "root_cause": "ep0 fifo underrun",
                                        "confidence": "HIGH",
                                        "evidence": ["sim.log:8821 UVM_ERROR"]}, cfg=cfg)
        # No real server reachable in this test -- must degrade gracefully,
        # never raise, and never lose the LOCAL write (memory_id present).
        assert "memory_id" in result
        assert "shared_push" in result
        assert result["shared_push"]["ok"] is False
    finally:
        shutil.rmtree(tmp)


def test_blackboard_destination_is_never_shareable():
    from dv_harness.memory_router import _SHAREABLE_DESTINATIONS
    assert "BLACKBOARD" not in _SHAREABLE_DESTINATIONS
    assert "JOB_MEMORY" not in _SHAREABLE_DESTINATIONS
    assert "ENGINEERING_MEMORY" in _SHAREABLE_DESTINATIONS
    assert "CORNER_CASE_LIBRARY" in _SHAREABLE_DESTINATIONS
    # ORGANIZATIONAL_MEMORY (2026-08-29, memory-tier-completion wiring) is
    # deliberately NOT in this set anymore -- it no longer has a separate
    # local write to additionally share on top of. route_and_store() now
    # routes it straight to OrganizationalMemoryStore/KnowledgeCenterClient
    # instead of the local-write-then-maybe-share pattern the other
    # shareable destinations use; see test_route_and_store_routes_
    # organizational_memory_through_knowledge_center_client_only below.
    assert "ORGANIZATIONAL_MEMORY" not in _SHAREABLE_DESTINATIONS


def test_route_and_store_routes_organizational_memory_through_knowledge_center_client_only():
    # Regression test for the memory-tier-completion wiring: previously
    # route_and_store() wrote a LOCAL .dv-harness/memory/organizational/*.json
    # file for every ORGANIZATIONAL_MEMORY record (via the generic
    # MemoryStore(root).add(level, record) dispatch used for every other
    # level) and ADDITIONALLY best-effort-pushed it to the shared knowledge
    # center -- directly contradicting memory.py's own OrganizationalMemoryStore
    # design comment, which says organizational memory's only real backing
    # store is the shared Knowledge Center and a local file copy would be "a
    # second, disconnected copy". Now it must route straight to
    # OrganizationalMemoryStore (no local file), with knowledge_center
    # disabled degrading gracefully to {"ok": False, "error": "NOT_CONFIGURED"}
    # exactly like calling OrganizationalMemoryStore directly would.
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False, "remote_root": ""}}
        result = route_and_store(tmp, {
            "kind": "cross_project_lesson", "verified": True,
            "title": "shared lesson", "protocol": "usb",
        }, cfg=cfg)
        assert result["destination"] == "ORGANIZATIONAL_MEMORY"
        assert result["ok"] is False
        assert result["error"] == "NOT_CONFIGURED"
        org_dir = tmp / ".dv-harness" / "memory" / "organizational"
        assert not org_dir.exists() or not any(org_dir.glob("*.json"))
    finally:
        shutil.rmtree(tmp)


# --- knowledge_center.py client (persistent-relay transport) ---------------
#
# REAL INCIDENT FIX (2026-09-01): KnowledgeCenterClient._invoke() used to
# spawn its own tools/remote/remote_hop.py subprocess directly, which reads
# VCPW from ITS OWN process environment -- the exact credential-exposure
# pattern CLAUDE.md's "Remote Linux Execution" section already forbids for
# remote_relay.py. All tests below were rewritten to exercise the new,
# credential-free persistent-relay transport (tools/remote/remote_exec.py's
# read_relay_info()/send_request()) instead of mocking subprocess.run() /
# a hop_script path. The two tests for the now-deleted _resolve_hop_script()
# method (test_resolve_hop_script_falls_back_to_tools_remote_when_explicit_
# path_is_stale, test_resolve_hop_script_resolves_configured_repo_relative_
# path) were removed along with the method itself -- that code path no
# longer exists to test.

import socket as _socket
import threading as _threading


def _fake_relay_info(tmp_path, vchost="vchost-b", vchop="host-c", port=0, token="tok"):
    """Writes a real relay-info JSON file (same shape/location
    tools/remote/remote_relay.py's info_path() writes for a real running
    relay) so read_relay_info() finds it, without a monkeypatch of the
    resolver itself."""
    import os as _os
    remote_dir = str(ROOT / "tools" / "remote")
    if remote_dir not in sys.path:
        sys.path.insert(0, remote_dir)
    from remote_relay import info_path
    p = info_path(vchost, vchop)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"host": "127.0.0.1", "port": port, "token": token,
                              "pid": 1, "started": "2026-09-01T00:00:00"}),
                 encoding="utf-8")
    return p


class _FakeRelayServer:
    """A real local TCP server standing in for remote_relay.py's own
    request loop, handling exactly the request sequence
    KnowledgeCenterClient._invoke() issues (one 'put', then one 'run') and
    returning caller-supplied canned responses for each -- a true
    socket round-trip against real send_request(), not a mocked transport."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.received = []
        self.sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(len(responses))
        self.port = self.sock.getsockname()[1]
        self.thread = _threading.Thread(target=self._serve)

    def _serve(self):
        for resp in self.responses:
            conn, _ = self.sock.accept()
            buf = b""
            while b"\n" not in buf:
                buf += conn.recv(65536)
            req = json.loads(buf.decode("utf-8"))
            # Read the 'local' file's real content NOW, synchronously, while
            # the client's send_request() call is still blocked waiting for
            # our response -- _invoke()'s own finally-block deletes that temp
            # file the moment send_request() returns, so reading it back
            # from the test AFTER the roundtrip completes is a real race
            # (confirmed live: FileNotFoundError).
            if req.get("op") == "put":
                try:
                    req["_local_content"] = Path(req["local"]).read_text(encoding="utf-8")
                except OSError:
                    req["_local_content"] = None
            self.received.append(req)
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            conn.close()

    def start(self):
        self.thread.start()
        return self

    def join(self):
        self.thread.join(timeout=5)
        self.sock.close()


def test_client_not_configured_returns_ok_false_without_relay_call():
    client = KnowledgeCenterClient({"knowledge_center": {"enabled": False, "remote_root": ""}})
    result = client.search()
    assert result == {"ok": False, "error": "NOT_CONFIGURED"}


def test_client_missing_vc_host_hop_reports_clear_error(monkeypatch):
    monkeypatch.delenv("VCHOST", raising=False)
    monkeypatch.delenv("VCHOP", raising=False)
    cfg = {"knowledge_center": {"enabled": True, "remote_root": "/srv/kc"}}
    client = KnowledgeCenterClient(cfg)
    result = client.test_connection()
    assert result["ok"] is False
    assert result["error"] == "VC_HOST_HOP_NOT_CONFIGURED"


def test_client_relay_not_ready_reports_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # empty -- no relay info file exists here
    cfg = {"knowledge_center": {"enabled": True, "remote_root": "/srv/kc",
                                 "vchost": "vchost-b", "vchop": "host-c"}}
    client = KnowledgeCenterClient(cfg)
    result = client.test_connection()
    assert result["ok"] is False
    assert result["error"] == "RELAY_NOT_READY"


def test_client_full_invoke_roundtrip_against_fake_relay_server(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    server = _FakeRelayServer([
        {"ok": True, "exit_code": 0, "stdout": "", "error": ""},  # put
        {"ok": True, "exit_code": 0,
         "stdout": f'{RESULT_MARKER}{{"count": 1, "records": [{{"memory_id": "KC-1"}}]}}\n',
         "error": ""},  # run
    ]).start()
    try:
        _fake_relay_info(tmp_path, port=server.port)
        cfg = {"knowledge_center": {"enabled": True, "remote_root": "/srv/kc",
                                     "vchost": "vchost-b", "vchop": "host-c"}}
        client = KnowledgeCenterClient(cfg)
        result = client.search(category="usb")
    finally:
        server.join()

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["records"][0]["memory_id"] == "KC-1"
    assert server.received[0]["op"] == "put"
    assert server.received[1]["op"] == "run"
    assert "broker.py search --root /srv/kc" in server.received[1]["cmd"]


def test_client_no_result_marker_reports_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    server = _FakeRelayServer([
        {"ok": True, "exit_code": 0, "stdout": "", "error": ""},
        {"ok": True, "exit_code": 1, "stdout": "some unrelated failure text\n", "error": ""},
    ]).start()
    try:
        _fake_relay_info(tmp_path, port=server.port)
        cfg = {"knowledge_center": {"enabled": True, "remote_root": "/srv/kc",
                                     "vchost": "vchost-b", "vchop": "host-c"}}
        client = KnowledgeCenterClient(cfg)
        result = client.search()
    finally:
        server.join()

    assert result["ok"] is False
    assert result["error"] == "NO_RESULT_MARKER"


def test_client_transport_put_failure_reports_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    server = _FakeRelayServer([
        {"ok": False, "exit_code": 1, "stdout": "", "error": "MD5_MISMATCH"},
    ]).start()
    try:
        _fake_relay_info(tmp_path, port=server.port)
        cfg = {"knowledge_center": {"enabled": True, "remote_root": "/srv/kc",
                                     "vchost": "vchost-b", "vchop": "host-c"}}
        client = KnowledgeCenterClient(cfg)
        result = client.search()
    finally:
        server.join()

    assert result["ok"] is False
    assert result["error"] == "TRANSPORT_PUT_FAILED"
    assert result["detail"] == "MD5_MISMATCH"


def test_client_confirm_sends_configured_max_age_days(tmp_path, monkeypatch):
    # BUG FIX (2026-08-28, audit-knowledge-center-reality): confirm() used to
    # omit max_age_days entirely, so broker.py's cmd_confirm silently fell
    # back to its own hardcoded 180-day default every time, regardless of
    # what the project actually configured. add() already sent this
    # correctly; confirm() must send the exact same value. Still real and
    # still worth guarding after the 2026-09-01 transport rewrite.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    server = _FakeRelayServer([
        {"ok": True, "exit_code": 0, "stdout": "", "error": ""},  # put
        {"ok": True, "exit_code": 0, "stdout": f'{RESULT_MARKER}{{"ok": true}}\n', "error": ""},  # run
    ]).start()
    try:
        _fake_relay_info(tmp_path, port=server.port)
        cfg = {"knowledge_center": {"enabled": True, "remote_root": "/srv/kc",
                                     "vchost": "vchost-b", "vchop": "host-c", "max_age_days": 30}}
        client = KnowledgeCenterClient(cfg)
        result = client.confirm("KC-1", "engineering", "usb", evidence={"resim": "pass"})
    finally:
        server.join()

    assert result["ok"] is True
    put_req = server.received[0]
    payload = json.loads(put_req["_local_content"])
    assert payload["max_age_days"] == 30


def test_knowledge_center_source_never_reads_vcpw_env_var():
    # Mirrors tools/remote/test_remote_exec.py's own
    # test_remote_exec_source_never_reads_vcpw_env_var -- the real safety
    # property the 2026-09-01 transport rewrite exists to guarantee.
    source = (ROOT / "dv_harness" / "knowledge_center.py").read_text(encoding="utf-8")
    assert "environ.get('VCPW'" not in source
    assert 'environ.get("VCPW"' not in source
    assert "environ['VCPW']" not in source
    assert 'environ["VCPW"]' not in source
    # The real safety property is "never imports the subprocess module"
    # (that's what would let this file spawn remote_hop.py directly again,
    # the credential-exposure risk) -- prose/comments mentioning
    # "subprocess"/"remote_hop.py" by name while explaining what changed and
    # why are expected and fine, so this checks the actual import statement,
    # not any bare substring.
    assert "import subprocess" not in source and "subprocess," not in source, (
        "knowledge_center.py must never import the subprocess module again "
        "(that's what let it invoke remote_hop.py directly) -- route "
        "through tools/remote/remote_exec.py's relay client only"
    )


def test_maybe_push_to_shared_returns_none_when_disabled():
    tmp = _tmp()
    try:
        assert maybe_push_to_shared({"knowledge_center": {"enabled": False}}, tmp,
                                     "ENGINEERING_MEMORY", "usb", "usb", {}) is None
        assert maybe_push_to_shared({"knowledge_center": {"enabled": True, "sync_on_promote": True}}, tmp,
                                     "BLACKBOARD", "usb", "usb", {}) is None
    finally:
        shutil.rmtree(tmp)


# --- tools/knowledge_center/broker.py, run for real as a subprocess -----------

def _run_broker(verb, root, payload):
    fd_payload = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fd_payload)
    fd_payload.close()
    try:
        proc = subprocess.run(
            [sys.executable, str(BROKER), verb, "--root", str(root), "--payload-file", fd_payload.name],
            capture_output=True, text=True, timeout=30,
        )
    finally:
        Path(fd_payload.name).unlink(missing_ok=True)
    line = next((l for l in proc.stdout.splitlines() if l.startswith(RESULT_MARKER)), None)
    assert line is not None, f"broker.py printed no result marker: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    return json.loads(line[len(RESULT_MARKER):]), proc.returncode


def test_broker_init_creates_manifest_and_directories():
    tmp = _tmp()
    try:
        result, rc = _run_broker("init", tmp / "kc", {})
        assert rc == 0
        assert result["created"] is True
        assert (tmp / "kc" / "manifest.json").is_file()
        assert "usb" in result["manifest"]["categories"]
    finally:
        shutil.rmtree(tmp)


def test_broker_add_search_deprecate_lifecycle():
    tmp = _tmp()
    try:
        root = tmp / "kc"
        _run_broker("init", root, {})
        added, rc = _run_broker("add", root, {
            "category": "usb", "protocol": "usb",
            "record": {"kind": "debug_lesson", "title": "attach debounce mismatch"},
            "provenance": {"origin_user": "alice", "origin_host": "pc-alice"},
            "max_age_days": 180,
        })
        assert rc == 0
        mid = added["memory_id"]

        searched, rc = _run_broker("search", root, {"category": "usb", "protocol": "usb"})
        assert rc == 0
        assert searched["count"] == 1
        assert searched["records"][0]["memory_id"] == mid
        assert searched["records"][0]["provenance"]["origin_user"] == "alice"

        deprecated, rc = _run_broker("deprecate", root, {
            "record_id": mid, "category": "usb", "protocol": "usb",
            "reason": "was actually a testbench bug", "provenance": {"origin_user": "bob"},
        })
        assert rc == 0
        assert deprecated["status"] == "RETRACTED"

        searched2, _ = _run_broker("search", root, {"category": "usb", "protocol": "usb"})
        assert searched2["count"] == 0
    finally:
        shutil.rmtree(tmp)


def test_broker_add_with_negative_max_age_is_immediately_stale():
    tmp = _tmp()
    try:
        root = tmp / "kc"
        _run_broker("init", root, {})
        added, _ = _run_broker("add", root, {
            "category": "pcie", "protocol": "pcie",
            "record": {"kind": "root_cause", "title": "LTSSM timeout"},
            "provenance": {"origin_user": "carol"}, "max_age_days": -1,
        })
        mid = added["memory_id"]
        searched, _ = _run_broker("search", root, {"category": "pcie", "protocol": "pcie"})
        assert searched["count"] == 0  # aged out even though status is still ACTIVE

        confirmed, rc = _run_broker("confirm", root, {
            "record_id": mid, "category": "pcie", "protocol": "pcie",
            "evidence": {"resim": "pass"}, "provenance": {"origin_user": "dave"},
            "max_age_days": 90,
        })
        assert rc == 0
        assert confirmed["confirmation_count"] == 1

        searched2, _ = _run_broker("search", root, {"category": "pcie", "protocol": "pcie"})
        assert searched2["count"] == 1
    finally:
        shutil.rmtree(tmp)


def test_broker_deprecate_not_found_reports_clean_error():
    tmp = _tmp()
    try:
        root = tmp / "kc"
        _run_broker("init", root, {})
        result, rc = _run_broker("deprecate", root, {
            "record_id": "KC-NOPE", "category": "usb", "protocol": "usb", "reason": "x",
        })
        assert rc == 1
        assert result["ok"] is False
        assert result["error"] == "NOT_FOUND"
    finally:
        shutil.rmtree(tmp)


# --- tools/verification_flow/knowledge_center_registry_consistency_gate.py --

def _run_gate_script(payload):
    script = ROOT / "tools" / "verification_flow" / "knowledge_center_registry_consistency_gate.py"
    fd = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fd)
    fd.close()
    try:
        proc = subprocess.run([sys.executable, str(script), "--catalog", fd.name],
                               capture_output=True, text=True, timeout=15)
    finally:
        Path(fd.name).unlink(missing_ok=True)
    return json.loads(proc.stdout), proc.returncode


def test_knowledge_center_registry_gate_passes_on_well_formed_catalog():
    result, rc = _run_gate_script({
        "manifest": {"schema_version": 1, "categories": ["usb", "_general"]},
        "records": [
            {"memory_id": "KC-1", "category": "usb", "protocol": "usb", "status": "ACTIVE",
             "written_at": 1.0, "revalidate_by": None,
             "provenance": {"origin_user": "alice", "origin_host": "pc1"}},
        ],
        "now": 100.0,
    })
    assert rc == 0
    assert result["status"] == "PASS"
    assert result["records_checked"] == 1


def test_knowledge_center_registry_gate_fails_on_missing_provenance():
    result, rc = _run_gate_script({
        "manifest": {"schema_version": 1, "categories": ["usb"]},
        "records": [
            {"memory_id": "KC-2", "category": "usb", "protocol": "usb", "status": "ACTIVE",
             "written_at": 1.0, "revalidate_by": None, "provenance": None},
        ],
        "now": 100.0,
    })
    assert rc == 2
    assert result["status"] == "FAIL"
    assert any("provenance.origin_user" in p for p in result["problems"])


def test_knowledge_center_registry_gate_fails_on_unrecognized_category():
    result, rc = _run_gate_script({
        "manifest": {"schema_version": 1, "categories": ["usb"]},
        "records": [
            {"memory_id": "KC-3", "category": "not_a_taxonomy_category", "protocol": "usb",
             "status": "ACTIVE", "written_at": 1.0, "revalidate_by": None,
             "provenance": {"origin_user": "alice"}},
        ],
        "now": 100.0,
    })
    assert rc == 2
    assert any("not in manifest.categories" in p for p in result["problems"])


def test_knowledge_center_registry_gate_fails_on_silently_stale_active_record():
    result, rc = _run_gate_script({
        "manifest": {"schema_version": 1, "categories": ["usb"]},
        "records": [
            {"memory_id": "KC-4", "category": "usb", "protocol": "usb", "status": "ACTIVE",
             "written_at": 1.0, "revalidate_by": 50.0,
             "provenance": {"origin_user": "alice"}},
        ],
        "now": 100.0,  # now > revalidate_by, but status was never flipped off ACTIVE
    })
    assert rc == 2
    assert any("revalidate_by" in p and "stale record not being filtered" in p
               for p in result["problems"])


def test_knowledge_center_registry_gate_fails_on_unknown_status():
    result, rc = _run_gate_script({
        "manifest": {"schema_version": 1, "categories": ["usb"]},
        "records": [
            {"memory_id": "KC-5", "category": "usb", "protocol": "usb", "status": "MADE_UP_STATUS",
             "written_at": 1.0, "revalidate_by": None, "provenance": {"origin_user": "alice"}},
        ],
        "now": 100.0,
    })
    assert rc == 2
    assert any("MADE_UP_STATUS" in p for p in result["problems"])


def test_broker_ping_reports_uninitialized_root_honestly():
    tmp = _tmp()
    try:
        result, rc = _run_broker("ping", tmp / "never_init", {})
        assert rc == 0
        assert result["initialized"] is False
    finally:
        shutil.rmtree(tmp)
