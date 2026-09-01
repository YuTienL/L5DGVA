import json
import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import remote_exec
from remote_exec import format_result, read_relay_info, send_request


def test_format_result_pass():
    resp = {"ok": True, "exit_code": 0, "stdout": "hello\n"}
    out = format_result("host-b", resp)
    assert "REMOTE_HOST=host-b" in out
    assert "EXIT_CODE=0" in out
    assert "STATUS=PASS" in out
    assert "hello" in out


def test_format_result_fail_on_nonzero_exit():
    resp = {"ok": True, "exit_code": 2, "stdout": "boom"}
    out = format_result("host-b", resp)
    assert "STATUS=FAIL" in out


def test_format_result_fail_when_not_ok():
    resp = {"ok": False, "exit_code": None, "stdout": ""}
    out = format_result("host-b", resp)
    assert "STATUS=FAIL" in out


def test_format_result_omits_body_when_empty():
    resp = {"ok": True, "exit_code": 0, "stdout": ""}
    out = format_result("host-b", resp)
    lines = out.splitlines()
    assert len(lines) == 3


def test_format_result_surfaces_error_field_on_put_get_failure():
    # Real bug found live 2026-09-01: remote_relay.py's handle_request()
    # returns a real 'error' string (e.g. 'MD5_MISMATCH', 'BAD_TOKEN') on
    # put/get/status failures, but format_result() silently dropped it --
    # a failed --put/--get printed only STATUS=FAIL with no reason.
    resp = {"ok": False, "exit_code": 1, "stdout": "", "error": "MD5_MISMATCH"}
    out = format_result("host-b", resp)
    assert "STATUS=FAIL" in out
    assert "ERROR=MD5_MISMATCH" in out


def test_format_result_omits_error_line_when_error_is_empty():
    resp = {"ok": True, "exit_code": 0, "stdout": "hello", "error": ""}
    out = format_result("host-b", resp)
    assert "ERROR=" not in out


def test_read_relay_info_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert read_relay_info("vchost-b", "host-b") is None


def test_read_relay_info_reads_real_json(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    relay_dir = tmp_path / "dv_agent_harness" / "relay"
    relay_dir.mkdir(parents=True)
    payload = {"host": "127.0.0.1", "port": 54321, "token": "tok", "pid": 1, "started": "now"}
    (relay_dir / "vchost-b-host-b.json").write_text(json.dumps(payload), encoding="utf-8")
    info = read_relay_info("vchost-b", "host-b")
    assert info == payload


def test_send_request_roundtrip_against_fake_server():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    def fake_server():
        conn, _ = server_sock.accept()
        buf = b""
        while b"\n" not in buf:
            buf += conn.recv(65536)
        req = json.loads(buf.decode("utf-8"))
        assert req["op"] == "run"
        assert req["cmd"] == "pwd"
        conn.sendall((json.dumps({"ok": True, "exit_code": 0, "stdout": "/home/x\n"}) + "\n").encode("utf-8"))
        conn.close()

    t = threading.Thread(target=fake_server)
    t.start()
    try:
        resp = send_request("127.0.0.1", port, {"token": "tok", "op": "run", "cmd": "pwd"}, timeout=5)
    finally:
        t.join(timeout=5)
        server_sock.close()

    assert resp == {"ok": True, "exit_code": 0, "stdout": "/home/x\n"}


def test_remote_exec_source_never_reads_vcpw_env_var():
    # The file may (and does) mention "VCPW" in prose/instructions -- the
    # real safety property is that it never reads the secret's value.
    source = (ROOT / "tools" / "remote" / "remote_exec.py").read_text(encoding="utf-8")
    assert "environ.get('VCPW'" not in source
    assert 'environ.get("VCPW"' not in source
    assert "environ['VCPW']" not in source
    assert 'environ["VCPW"]' not in source


def test_main_prints_down_block_when_no_relay_info(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("VCHOST", "vchost-b")
    monkeypatch.setenv("VCHOP", "host-b")
    monkeypatch.setattr(sys, "argv", ["remote_exec.py", "pwd"])
    rc = remote_exec.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "STATUS=DOWN" in out
    assert "VCPW=..." in out  # instruction text, not a real value
