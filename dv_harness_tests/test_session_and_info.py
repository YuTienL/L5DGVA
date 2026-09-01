"""Tests for three related features built on the same session's work:
- dv_harness/session_snapshot.py + CLI save-session/restore-session +
  dashboard /api/session/{save,restore,list}
- tools/knowledge_center/broker.py's activity log (cmd_db_info) +
  dv_harness/knowledge_center.py's db_info() client method + CLI
  `knowledge db-info` + dashboard /api/knowledge/db-info
- dv_harness/user_info.py (per-deployment access rollup from events.jsonl's
  CLI_ACCESS/GUI_ACCESS events) + CLI user-info + dashboard /api/user-info
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

from dv_harness.session_snapshot import (
    save_session, restore_session, list_sessions, delete_session, RESTORE_FILES,
    SourceIdentityMismatchError, _current_git_sha,
    SESSION_EXTRA_DIRS, SESSION_ARTIFACT_REFERENCE_DIRS,
)
from dv_harness.storage import StateStore
from dv_harness.user_info import summarize_user_access, ACCESS_EVENT_TYPES
from dv_harness.knowledge_center import RESULT_MARKER

ROOT = Path(__file__).resolve().parents[1]
BROKER = ROOT / "tools" / "knowledge_center" / "broker.py"


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _run_cli(root: Path, *args):
    # encoding="utf-8" explicit (not just text=True): cli.py reconfigures
    # its OWN stdout to UTF-8, but subprocess.run's reader threads decode
    # with the OS's default codepage unless told otherwise -- on a
    # non-English Windows codepage this raises UnicodeDecodeError on any
    # non-ASCII byte (same fix already applied to an existing CLI test in
    # test_engine_gates_and_routing.py).
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(root), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
    )
    return r


# --- session_snapshot.py -------------------------------------------------------

def test_save_and_restore_session_round_trip():
    tmp = _tmp()
    try:
        r = _run_cli(tmp, "set-stage", "DISCOVERY")
        assert r.returncode == 0, r.stderr
        manifest = save_session(tmp, name="checkpoint1", note="before risky change")
        assert manifest["current_stage"] == "DISCOVERY"
        assert "state.json" in manifest["files"]
        assert "events.jsonl" in manifest["files"]  # copied for reference

        r = _run_cli(tmp, "set-stage", "BUILD")
        assert r.returncode == 0, r.stderr

        result = restore_session(tmp, "checkpoint1")
        assert result["restored"] == "checkpoint1"
        assert result["auto_backup"]  # a pre-restore backup was made

        state = json.loads((tmp / ".dv-harness" / "state.json").read_text(encoding="utf-8"))
        assert state["current_stage"] == "DISCOVERY"

        # The auto-backup itself is a real, restorable session.
        names = {s["name"] for s in list_sessions(tmp)}
        assert "checkpoint1" in names
        assert result["auto_backup"] in names
    finally:
        shutil.rmtree(tmp)


def _git(root, *args):
    subprocess.run(["git", *args], cwd=str(root), check=True,
                    capture_output=True, text=True,
                    env={**__import__("os").environ,
                         "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _rmtree_git_safe(path):
    # git on Windows marks packed objects read-only; shutil.rmtree's default
    # error handler doesn't clear that bit before retrying, so a real git
    # repo's temp dir needs an error handler that chmods-then-retries.
    #
    # REAL COMPAT BUG (found deploying to the real remote server, Python
    # 3.7): this used to pass `onexc=` (the non-deprecated hook, but only
    # added in Python 3.12) -- crashed with TypeError on the real 3.7
    # interpreter. `onerror` (the older callback signature,
    # `onerror(function, path, exc_info)` taking a 3-tuple rather than
    # onexc's bare exception instance) is supported on every Python 3.x
    # version from 3.3 through at least 3.14 -- deprecated as of 3.12 but
    # not removed, so it's the one signature that actually works across
    # this project's real version range (3.7 through this dev machine's
    # 3.14), at the cost of one deprecation warning on the newest
    # interpreters.
    import os as _os, stat as _stat

    def _onerror(func, p, exc_info):
        _os.chmod(p, _stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=_onerror)


def _seed_git_sha(root: Path) -> str:
    # "set-stage" alone doesn't populate git_sha (only a real run_stage()
    # engine call does, via DVHarness._git_sha()) -- write it directly via
    # StateStore so this test can exercise restore_session()'s own
    # sha-comparison logic without needing a full engine run.
    store = StateStore(root)
    st = store.load()
    st.git_sha = _current_git_sha(root)
    store.save(st)
    return st.git_sha


def test_restore_session_reports_sha_match_when_source_unchanged():
    # BUG FIX (2026-08-29, poster-compliance-audit #4 "Session Save/Restore
    # 可重現性"): restore_session() must honestly report whether the CURRENT
    # git SHA still matches what was recorded at save time, per CLAUDE.md's
    # "same source/build/config identity" rule.
    tmp = _tmp()
    try:
        _git(tmp, "init", "-q")
        (tmp / "f.txt").write_text("x", encoding="utf-8")
        _git(tmp, "add", "f.txt")
        _git(tmp, "commit", "-q", "-m", "init")

        r = _run_cli(tmp, "set-stage", "DISCOVERY")
        assert r.returncode == 0, r.stderr
        _seed_git_sha(tmp)
        save_session(tmp, name="c1")

        result = restore_session(tmp, "c1")
        assert result["sha_match"] is True
        assert result["saved_sha"] == result["current_sha"]
    finally:
        _rmtree_git_safe(tmp)


def test_restore_session_detects_sha_mismatch_and_can_enforce_it():
    tmp = _tmp()
    try:
        _git(tmp, "init", "-q")
        (tmp / "f.txt").write_text("x", encoding="utf-8")
        _git(tmp, "add", "f.txt")
        _git(tmp, "commit", "-q", "-m", "init")

        r = _run_cli(tmp, "set-stage", "DISCOVERY")
        assert r.returncode == 0, r.stderr
        _seed_git_sha(tmp)
        save_session(tmp, name="c1")

        # advance the real source past the saved snapshot
        (tmp / "f.txt").write_text("y", encoding="utf-8")
        _git(tmp, "add", "f.txt")
        _git(tmp, "commit", "-q", "-m", "second")

        # default (require_sha_match=False): restores anyway, but honestly
        # reports the mismatch rather than silently claiming a match.
        result = restore_session(tmp, "c1")
        assert result["sha_match"] is False
        assert result["saved_sha"] != result["current_sha"]

        # enforced: must refuse rather than silently proceed.
        try:
            restore_session(tmp, "c1", require_sha_match=True)
            assert False, "expected SourceIdentityMismatchError"
        except SourceIdentityMismatchError as e:
            assert e.saved_sha != e.current_sha
    finally:
        _rmtree_git_safe(tmp)


def test_restore_session_sha_match_is_none_when_not_a_git_repo():
    # An unknown comparison (no real git repo here) must never be reported
    # as a false positive match.
    tmp = _tmp()
    try:
        r = _run_cli(tmp, "set-stage", "DISCOVERY")
        assert r.returncode == 0, r.stderr
        save_session(tmp, name="c1")
        result = restore_session(tmp, "c1")
        assert result["sha_match"] is None
    finally:
        shutil.rmtree(tmp)


def test_save_session_duplicate_name_refused():
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        save_session(tmp, name="dup")
        try:
            save_session(tmp, name="dup")
            assert False, "duplicate name must be refused"
        except FileExistsError:
            pass
    finally:
        shutil.rmtree(tmp)


def test_restore_nonexistent_session_raises():
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        try:
            restore_session(tmp, "does-not-exist")
            assert False
        except FileNotFoundError:
            pass
    finally:
        shutil.rmtree(tmp)


def test_restore_never_rewinds_events_jsonl():
    # events.jsonl is saved INTO every snapshot for reference, but excluded
    # from RESTORE_FILES -- an append-only audit log must never be
    # destructively rewritten by a restore.
    assert "events.jsonl" not in RESTORE_FILES
    tmp = _tmp()
    try:
        _run_cli(tmp, "set-stage", "DISCOVERY")
        save_session(tmp, name="c1")
        before = (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8")
        _run_cli(tmp, "set-stage", "BUILD")  # adds more events
        restore_session(tmp, "c1")
        after = (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8")
        assert after.startswith(before)  # nothing removed, only appended since
        assert len(after) > len(before)
    finally:
        shutil.rmtree(tmp)


def test_save_session_excludes_memory_and_static_config():
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        (tmp / ".dv-harness" / "memory" / "engineering").mkdir(parents=True, exist_ok=True)
        (tmp / ".dv-harness" / "memory" / "engineering" / "MEM-1.json").write_text("{}", encoding="utf-8")
        (tmp / ".dv-harness" / "graph").mkdir(parents=True, exist_ok=True)
        (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text("{}", encoding="utf-8")

        manifest = save_session(tmp, name="c1")
        snap_dir = tmp / ".dv-harness" / "sessions" / "c1"
        assert not (snap_dir / "memory").exists()
        assert not (snap_dir / "graph").exists()
        assert "memory" not in manifest["dirs"]
        assert "graph" not in manifest["dirs"]
    finally:
        shutil.rmtree(tmp)


# --- session_snapshot.py: SESSION_EXTRA_DIRS / SESSION_ARTIFACT_REFERENCE_DIRS
# (session-snapshot-extension, 2026-09-01) --------------------------------

def test_save_and_restore_session_round_trips_command_catalog_extra_dir():
    assert SESSION_EXTRA_DIRS == ["generated/06_tests/command_catalog"]
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        catalog = tmp / "generated" / "06_tests" / "command_catalog"
        catalog.mkdir(parents=True)
        (catalog / "usb2_hs_basic.command.txt").write_text("RUN usb2_hs_basic\n", encoding="utf-8")

        manifest = save_session(tmp, name="c1")
        assert manifest["extra_dirs"] == ["generated/06_tests/command_catalog"]
        snap_file = (tmp / ".dv-harness" / "sessions" / "c1" / "extra"
                     / "generated" / "06_tests" / "command_catalog" / "usb2_hs_basic.command.txt")
        assert snap_file.read_text(encoding="utf-8") == "RUN usb2_hs_basic\n"

        # Mutate the live copy, then restore -- the snapshot's content comes back.
        (catalog / "usb2_hs_basic.command.txt").write_text("RUN something_else\n", encoding="utf-8")
        restore_session(tmp, "c1")
        assert (catalog / "usb2_hs_basic.command.txt").read_text(encoding="utf-8") == "RUN usb2_hs_basic\n"
    finally:
        shutil.rmtree(tmp)


def test_save_session_excludes_project_input_command_raw():
    # RULING 1 (session_snapshot.py): project_input/08_command is durable
    # project SOURCE material, not current-run state -- deliberately never
    # copied, unlike generated/06_tests/command_catalog above.
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        raw_dir = tmp / "project_input" / "08_command" / "raw"
        raw_dir.mkdir(parents=True)
        (raw_dir / "command.txt").write_text("RUN foo\n", encoding="utf-8")

        manifest = save_session(tmp, name="c1")
        assert "project_input/08_command" not in manifest["extra_dirs"]
        assert not (tmp / ".dv-harness" / "sessions" / "c1" / "extra" / "project_input").exists()
    finally:
        shutil.rmtree(tmp)


def test_save_session_missing_extra_dir_is_silently_skipped():
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        manifest = save_session(tmp, name="c1")
        assert manifest["extra_dirs"] == []
        assert manifest["artifact_references"] == {}
    finally:
        shutil.rmtree(tmp)


def test_save_session_records_fsdb_and_coverage_as_hash_references_not_copies():
    assert SESSION_ARTIFACT_REFERENCE_DIRS == {
        "fsdb": "generated/10_runtime/waveform",
        "coverage": "generated/11_coverage",
    }
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        wave_dir = tmp / "generated" / "10_runtime" / "waveform"
        wave_dir.mkdir(parents=True)
        fsdb_bytes = b"FAKE-FSDB-BINARY-CONTENT-0123456789"
        (wave_dir / "run1.fsdb").write_bytes(fsdb_bytes)

        cov_dir = tmp / "generated" / "11_coverage"
        cov_dir.mkdir(parents=True)
        cov_bytes = b"FAKE-UCDB-COVERAGE-CONTENT-abcdef"
        (cov_dir / "merged.ucdb").write_bytes(cov_bytes)

        manifest = save_session(tmp, name="c1")
        refs = manifest["artifact_references"]

        import hashlib
        fsdb_ref = refs["fsdb"][0]
        assert fsdb_ref["path"] == "generated/10_runtime/waveform/run1.fsdb"
        assert fsdb_ref["size"] == len(fsdb_bytes)
        assert fsdb_ref["sha256"] == hashlib.sha256(fsdb_bytes).hexdigest()

        cov_ref = refs["coverage"][0]
        assert cov_ref["path"] == "generated/11_coverage/merged.ucdb"
        assert cov_ref["sha256"] == hashlib.sha256(cov_bytes).hexdigest()

        # REFERENCE only -- the binary content itself is never duplicated
        # into the snapshot directory.
        snap_dir = tmp / ".dv-harness" / "sessions" / "c1"
        assert not (snap_dir / "extra" / "generated" / "10_runtime").exists()
        assert not (snap_dir / "extra" / "generated" / "11_coverage").exists()
        assert not any(snap_dir.rglob("*.fsdb"))
        assert not any(snap_dir.rglob("*.ucdb"))
    finally:
        shutil.rmtree(tmp)


def test_artifact_reference_skips_hash_for_oversized_file():
    from dv_harness import session_snapshot as _snap
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        cov_dir = tmp / "generated" / "11_coverage"
        cov_dir.mkdir(parents=True)
        big = b"x" * 4096
        (cov_dir / "huge.ucdb").write_bytes(big)

        with patch.object(_snap, "ARTIFACT_REFERENCE_HASH_SIZE_LIMIT_BYTES", 1024):
            manifest = save_session(tmp, name="c1")

        ref = manifest["artifact_references"]["coverage"][0]
        assert ref["size"] == 4096
        assert ref["sha256"] is None
        assert "hash_skipped_reason" in ref
    finally:
        shutil.rmtree(tmp)


def test_restore_session_never_touches_artifact_reference_directories():
    # There is nothing to restore for a reference-only entry -- restoring an
    # older session must not delete/replace whatever FSDB/coverage the LIVE
    # tree currently has under generated/10_runtime/waveform or
    # generated/11_coverage.
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        wave_dir = tmp / "generated" / "10_runtime" / "waveform"
        wave_dir.mkdir(parents=True)
        (wave_dir / "old.fsdb").write_bytes(b"old-run-bytes")
        save_session(tmp, name="c1")

        (wave_dir / "old.fsdb").unlink()
        (wave_dir / "new.fsdb").write_bytes(b"new-run-bytes")

        restore_session(tmp, "c1")
        assert not (wave_dir / "old.fsdb").exists()
        assert (wave_dir / "new.fsdb").exists()
    finally:
        shutil.rmtree(tmp)


def test_delete_session():
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        save_session(tmp, name="c1")
        assert delete_session(tmp, "c1") is True
        assert delete_session(tmp, "c1") is False
        assert list_sessions(tmp) == []
    finally:
        shutil.rmtree(tmp)


# --- CLI save-session / restore-session -----------------------------------

def test_cli_save_and_restore_session():
    tmp = _tmp()
    try:
        r = _run_cli(tmp, "set-stage", "VPLAN")
        assert r.returncode == 0, r.stderr
        r = _run_cli(tmp, "save-session", "--name", "cli1", "--note", "n1")
        assert r.returncode == 0, r.stderr
        manifest = json.loads(r.stdout)
        assert manifest["name"] == "cli1"

        r = _run_cli(tmp, "restore-session", "--list")
        assert r.returncode == 0, r.stderr
        listed = json.loads(r.stdout)
        assert any(s["name"] == "cli1" for s in listed)

        r = _run_cli(tmp, "set-stage", "IMPLEMENT")
        assert r.returncode == 0

        r = _run_cli(tmp, "restore-session", "cli1")
        assert r.returncode == 0, r.stderr
        result = json.loads(r.stdout)
        assert result["restored"] == "cli1"

        r = _run_cli(tmp, "status")
        assert json.loads(r.stdout)["current_stage"] == "VPLAN"

        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()]
        kinds = [e.get("event") for e in events]
        assert "SESSION_SAVED" in kinds
        assert "SESSION_RESTORED" in kinds
    finally:
        shutil.rmtree(tmp)


def test_cli_restore_session_not_found_reports_clean_error():
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        r = _run_cli(tmp, "restore-session", "nope")
        assert r.returncode == 1
        assert json.loads(r.stdout)["error"] == "NOT_FOUND"
    finally:
        shutil.rmtree(tmp)


# --- CLI_ACCESS / user-info --------------------------------------------------

def test_cli_invocations_are_logged_and_user_info_reports_them():
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        _run_cli(tmp, "explain")
        _run_cli(tmp, "status")

        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()]
        access = [e for e in events if e.get("event") == "CLI_ACCESS"]
        assert len(access) == 3
        assert {e["cmd"] for e in access} == {"status", "explain"}
        assert all(e.get("user") for e in access)

        info = summarize_user_access(tmp)
        assert len(info["users"]) == 1
        u = info["users"][0]
        assert u["total_events"] == 3
        assert u["session_count"] == 1  # all within SESSION_GAP_SECONDS of each other
    finally:
        shutil.rmtree(tmp)


def test_cli_user_info_subcommand():
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        r = _run_cli(tmp, "user-info")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert len(data["users"]) == 1
        assert data["users"][0]["total_events"] >= 1
    finally:
        shutil.rmtree(tmp)


def test_user_info_infers_separate_sessions_across_a_gap():
    tmp = _tmp()
    try:
        _run_cli(tmp, "status")
        # Backdate the just-logged CLI_ACCESS event so the next one looks
        # like a new session (gap > SESSION_GAP_SECONDS), without sleeping
        # in the test.
        events_file = tmp / ".dv-harness" / "events.jsonl"
        events = [json.loads(l) for l in events_file.read_text(encoding="utf-8").strip().splitlines()]
        from dv_harness.control_plane import now as cp_now
        import datetime
        old_ts = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(hours=2)).isoformat()
        for e in events:
            if e.get("event") == "CLI_ACCESS":
                e["ts"] = old_ts
        events_file.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

        _run_cli(tmp, "status")  # a fresh, "now" CLI_ACCESS event

        info = summarize_user_access(tmp)
        u = info["users"][0]
        assert u["session_count"] == 2
    finally:
        shutil.rmtree(tmp)


def test_summarize_user_access_empty_project_returns_no_users():
    tmp = _tmp()
    try:
        (tmp / ".dv-harness").mkdir(parents=True, exist_ok=True)
        info = summarize_user_access(tmp)
        assert info == {"users": [], "recent_access": []}
    finally:
        shutil.rmtree(tmp)


# --- tools/knowledge_center/broker.py: cmd_db_info --------------------------

def _run_broker(verb, root, payload):
    fd = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fd)
    fd.close()
    try:
        proc = subprocess.run(
            [sys.executable, str(BROKER), verb, "--root", str(root), "--payload-file", fd.name],
            capture_output=True, text=True, timeout=30,
        )
    finally:
        Path(fd.name).unlink(missing_ok=True)
    line = next((l for l in proc.stdout.splitlines() if l.startswith(RESULT_MARKER)), None)
    assert line is not None, f"broker.py printed no result marker: {proc.stdout!r} {proc.stderr!r}"
    return json.loads(line[len(RESULT_MARKER):]), proc.returncode


def test_broker_db_info_tracks_created_retracted_confirmed():
    tmp = _tmp()
    try:
        root = tmp / "kc"
        _run_broker("init", root, {})
        added, _ = _run_broker("add", root, {
            "category": "usb", "protocol": "usb",
            "record": {"kind": "debug_lesson", "title": "t1"},
            "provenance": {"origin_user": "alice", "origin_host": "pc1"},
        })
        mid = added["memory_id"]

        info, rc = _run_broker("db_info", root, {})
        assert rc == 0
        assert info["count"] == 1
        assert info["by_action"] == {"CREATED": 1}
        assert info["activity"][0]["memory_id"] == mid
        assert info["activity"][0]["origin_user"] == "alice"
        assert info["activity"][0]["summary"] == "t1"

        _run_broker("confirm", root, {"record_id": mid, "category": "usb", "protocol": "usb",
                                        "provenance": {"origin_user": "bob"}})
        _run_broker("deprecate", root, {"record_id": mid, "category": "usb", "protocol": "usb",
                                          "reason": "wrong", "provenance": {"origin_user": "carol"}})

        info, rc = _run_broker("db_info", root, {})
        assert info["count"] == 3
        assert info["by_action"] == {"CREATED": 1, "CONFIRMED": 1, "RETRACTED": 1}
        # newest first
        assert info["activity"][0]["action"] == "RETRACTED"
        assert info["activity"][0]["origin_user"] == "carol"

        filtered, _ = _run_broker("db_info", root, {"action": "CONFIRMED"})
        assert filtered["count"] == 1
        assert filtered["activity"][0]["origin_user"] == "bob"
    finally:
        shutil.rmtree(tmp)


def test_broker_db_info_empty_db_reports_zero_not_error():
    tmp = _tmp()
    try:
        root = tmp / "kc"
        _run_broker("init", root, {})
        info, rc = _run_broker("db_info", root, {})
        assert rc == 0
        assert info == {"count": 0, "by_action": {}, "activity": [], "ok": True}
    finally:
        shutil.rmtree(tmp)


# --- dv_harness/knowledge_center.py client: db_info() ------------------------
#
# REAL BUG FIX (2026-09-01, dv_harness/knowledge_center.py's _invoke()
# rewrite, commit 7ae3a28): this test used to mock subprocess.run() against
# the old hop_script-direct-invocation transport, which _invoke() no longer
# uses at all (that transport read VCPW from its own process env -- a real
# credential-exposure risk, replaced with the credential-free persistent
# relay). Rewritten to exercise the new transport against a real local fake
# relay server, mirroring dv_harness_tests/test_knowledge_center.py's own
# _FakeRelayServer pattern (kept private to that file; duplicated minimally
# here rather than cross-importing test internals between files).

def test_client_db_info_parses_result(tmp_path, monkeypatch):
    import json as _json
    import socket as _socket
    import threading as _threading

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    remote_dir = str(ROOT / "tools" / "remote")
    if remote_dir not in sys.path:
        sys.path.insert(0, remote_dir)
    from remote_relay import info_path

    server_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(2)
    port = server_sock.getsockname()[1]
    responses = [
        {"ok": True, "exit_code": 0, "stdout": "", "error": ""},  # put
        {"ok": True, "exit_code": 0,
         "stdout": f'{RESULT_MARKER}{{"count": 2, "by_action": {{"CREATED": 2}}, "activity": []}}\n',
         "error": ""},  # run
    ]

    def _serve():
        for resp in responses:
            conn, _ = server_sock.accept()
            buf = b""
            while b"\n" not in buf:
                buf += conn.recv(65536)
            conn.sendall((_json.dumps(resp) + "\n").encode("utf-8"))
            conn.close()

    t = _threading.Thread(target=_serve)
    t.start()
    try:
        p = info_path("vchost-b", "host-c")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps({"host": "127.0.0.1", "port": port, "token": "tok",
                                   "pid": 1, "started": "2026-09-01T00:00:00"}), encoding="utf-8")

        cfg = {"knowledge_center": {"enabled": True, "remote_root": "/srv/kc",
                                     "vchost": "vchost-b", "vchop": "host-c"}}
        from dv_harness.knowledge_center import KnowledgeCenterClient
        client = KnowledgeCenterClient(cfg)
        result = client.db_info(limit=10)
    finally:
        t.join(timeout=5)
        server_sock.close()

    assert result["ok"] is True
    assert result["count"] == 2


# --- dashboard endpoints ------------------------------------------------------

import socket
import threading
import urllib.error
import urllib.request


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _mk_dashboard_project(port: int) -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness").mkdir(parents=True, exist_ok=True)
    cfg = {"dashboard": {"host": "127.0.0.1", "port": port},
           "policy": {"require_stage_gate_evidence": False, "max_stage_retries": 0}}
    (tmp / ".dv-harness" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return tmp


def _start_dashboard(tmp: Path) -> threading.Thread:
    from dv_harness import dashboard
    t = threading.Thread(target=dashboard.serve, args=(tmp,), daemon=True)
    t.start()
    return t


def _wait_ready(base: str, timeout: float = 10) -> None:
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            _get(base, "/api/state")
            return
        except Exception as e:
            last_exc = e
            time.sleep(0.05)
    raise AssertionError(f"dashboard at {base} never became ready: {last_exc}")


def _get(base: str, path: str):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def _post(base: str, path: str, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + path, data=data,
                                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def test_dashboard_session_save_list_restore():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/session/save", {"name": "gui1", "note": "n"})
        assert status == 200, data
        assert data["name"] == "gui1"

        status, data = _get(base, "/api/session/list")
        assert status == 200
        assert any(s["name"] == "gui1" for s in data["sessions"])

        status, data = _post(base, "/api/session/restore", {"name": "gui1"})
        assert status == 200, data
        assert data["restored"] == "gui1"

        status, data = _post(base, "/api/session/restore", {"name": "does-not-exist"})
        assert status == 404
        assert data["error"] == "NOT_FOUND"
    finally:
        shutil.rmtree(tmp)


def test_dashboard_session_save_duplicate_name_conflict():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _post(base, "/api/session/save", {"name": "dup"})
        status, data = _post(base, "/api/session/save", {"name": "dup"})
        assert status == 409
    finally:
        shutil.rmtree(tmp)


def test_dashboard_root_page_load_logs_gui_access_and_user_info_reports_it():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            assert resp.status == 200

        status, data = _get(base, "/api/user-info")
        assert status == 200
        assert len(data["users"]) == 1
        assert data["users"][0]["total_events"] >= 1
        events = [json.loads(l) for l in
                  (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()]
        assert any(e.get("event") == "GUI_ACCESS" for e in events)
    finally:
        shutil.rmtree(tmp)


def test_dashboard_knowledge_db_info_not_configured():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        status, data = _get(base, "/api/knowledge/db-info")
        assert status == 409
        assert data["error"] == "NOT_CONFIGURED"
    finally:
        shutil.rmtree(tmp)
