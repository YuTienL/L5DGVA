import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

from remote_relay import (
    DEFAULT_LISTEN_BACKLOG,
    RelayServer,
    bind_loopback,
    should_idle_exit,
    running_inside_ai_agent,
    is_credential_inspection_command,
    is_msys_mangled_path,
)


class FakeSession:
    """Stands in for remote_hop.Session -- records calls, returns canned
    results, so RelayServer.handle_request can be tested without a real
    telnet/ssh connection."""

    def __init__(self):
        self.run_calls = []
        self.put_calls = []
        self.get_calls = []
        self.sent = []
        self.run_result = ("some output", 0)
        self.put_result = True
        self.get_result = True

    def run(self, cmd, timeout):
        self.run_calls.append((cmd, timeout))
        return self.run_result

    def put(self, local, remote):
        self.put_calls.append((local, remote))
        return self.put_result

    def get(self, remote, local):
        self.get_calls.append((remote, local))
        return self.get_result

    def send(self, line):
        self.sent.append(line)

    def read_until(self, pattern, timeout, label):
        return "host-bok$"


TOKEN = "abc123"


def make_server():
    return RelayServer(FakeSession(), TOKEN, "ssh -o BatchMode=yes host-b")


def test_wrong_token_is_rejected():
    server = make_server()
    resp = server.handle_request({"token": "wrong", "op": "status"})
    assert resp["ok"] is False
    assert resp["error"] == "BAD_TOKEN"
    assert server.session.run_calls == []


def test_missing_token_is_rejected():
    server = make_server()
    resp = server.handle_request({"op": "status"})
    assert resp["ok"] is False
    assert resp["error"] == "BAD_TOKEN"


def test_status_op_calls_echo_alive():
    server = make_server()
    server.session.run_result = ("alive", 0)
    resp = server.handle_request({"token": TOKEN, "op": "status"})
    assert resp["ok"] is True
    assert resp["exit_code"] == 0
    assert resp["stdout"] == "alive"
    assert server.session.run_calls == [("echo alive", 30)]


def test_run_op_passes_cmd_and_timeout():
    server = make_server()
    server.session.run_result = ("hello\n", 0)
    resp = server.handle_request({"token": TOKEN, "op": "run", "cmd": "echo hello", "timeout": 60})
    assert resp["ok"] is True
    assert resp["stdout"] == "hello\n"
    assert server.session.run_calls == [("echo hello", 60)]


def test_run_op_defaults_timeout_to_1800():
    server = make_server()
    server.handle_request({"token": TOKEN, "op": "run", "cmd": "pwd"})
    assert server.session.run_calls == [("pwd", 1800)]


def test_put_op_success():
    server = make_server()
    resp = server.handle_request({"token": TOKEN, "op": "put", "local": "a.txt", "remote": "/tmp/a.txt"})
    assert resp["ok"] is True
    assert resp["exit_code"] == 0
    assert server.session.put_calls == [("a.txt", "/tmp/a.txt")]


def test_put_op_failure_reports_md5_mismatch():
    server = make_server()
    server.session.put_result = False
    resp = server.handle_request({"token": TOKEN, "op": "put", "local": "a.txt", "remote": "/tmp/a.txt"})
    assert resp["ok"] is False
    assert resp["error"] == "MD5_MISMATCH"


def test_get_op_success():
    server = make_server()
    resp = server.handle_request({"token": TOKEN, "op": "get", "remote": "/tmp/a.txt", "local": "a.txt"})
    assert resp["ok"] is True
    assert server.session.get_calls == [("/tmp/a.txt", "a.txt")]


def test_reconnect_hop_op_resends_hop_command():
    server = make_server()
    resp = server.handle_request({"token": TOKEN, "op": "reconnect_hop"})
    assert resp["ok"] is True
    assert server.session.sent == ["ssh -o BatchMode=yes host-b"]


def test_unknown_op_returns_error():
    server = make_server()
    resp = server.handle_request({"token": TOKEN, "op": "frobnicate"})
    assert resp["ok"] is False
    assert resp["error"] == "UNKNOWN_OP"


def test_handle_request_updates_last_activity_only_on_valid_token():
    server = make_server()
    before = server.last_activity
    time.sleep(0.01)
    server.handle_request({"token": "wrong", "op": "status"})
    assert server.last_activity == before
    server.handle_request({"token": TOKEN, "op": "status"})
    assert server.last_activity > before


def test_bind_loopback_always_uses_127_0_0_1():
    sock = bind_loopback(0)
    try:
        assert sock.getsockname()[0] == "127.0.0.1"
    finally:
        sock.close()


def test_should_idle_exit_true_after_timeout():
    server = make_server()
    server.last_activity = time.time() - 100
    assert should_idle_exit(server, idle_timeout=10) is True


def test_should_idle_exit_false_within_timeout():
    server = make_server()
    server.last_activity = time.time()
    assert should_idle_exit(server, idle_timeout=7200) is False


# --- Layer 2: AI-agent-environment guard --------------------------------

def test_running_inside_ai_agent_detects_claudecode_marker(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert running_inside_ai_agent() is True


def test_running_inside_ai_agent_detects_anthropic_api_key(monkeypatch):
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    assert running_inside_ai_agent() is True


def test_running_inside_ai_agent_false_in_a_clean_environment(monkeypatch):
    for marker in ("CLAUDECODE", "CLAUDE_CODE", "CLAUDE_CODE_ENTRYPOINT",
                   "CLAUDE_CODE_SESSION_ID", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(marker, raising=False)
    assert running_inside_ai_agent() is False


# --- Layer 4: credential-inspection command DENY list -------------------

def test_bare_env_is_denied():
    assert is_credential_inspection_command("env") is True


def test_bare_printenv_is_denied():
    assert is_credential_inspection_command("printenv") is True


def test_printenv_vcpw_is_denied():
    assert is_credential_inspection_command("printenv VCPW") is True


def test_echo_dollar_vcpw_is_denied():
    assert is_credential_inspection_command("echo $VCPW") is True


def test_bare_set_is_denied():
    assert is_credential_inspection_command("set") is True


def test_bare_export_is_denied():
    assert is_credential_inspection_command("export") is True


def test_python_os_environ_is_denied():
    assert is_credential_inspection_command("python3 -c \"import os; print(os.environ)\"") is True


def test_normal_export_with_assignment_is_allowed():
    assert is_credential_inspection_command("export FOO=bar") is False


def test_ordinary_commands_are_allowed():
    for cmd in ("hostname", "pwd", "ls -la", "git status", "make WAVE=1", "bsub < run.csh", "bjobs 12345"):
        assert is_credential_inspection_command(cmd) is False


def test_run_op_denies_credential_inspection_before_touching_session():
    server = make_server()
    resp = server.handle_request({"token": TOKEN, "op": "run", "cmd": "printenv VCPW"})
    assert resp["ok"] is False
    assert resp["error"] == "CREDENTIAL_INSPECTION_DENIED"
    assert server.session.run_calls == []


# --- Multi-user concurrency safety (2026-09-02) --------------------------
# Real concern raised live: "一組 relay = 一個真實的 telnet+ssh session,
# 多人共用同一組帳號/主機會讓指令互相插隊" (one relay is one real shell;
# multiple people sharing it could make commands cut in line / interleave).

def test_default_listen_backlog_queues_rather_than_refuses_concurrent_users():
    # A relay meant to be shared needs more than the original backlog=1 --
    # that queued only one pending connection beyond the one being served
    # and refused the rest outright when several callers connected at once.
    assert DEFAULT_LISTEN_BACKLOG >= 16


def test_bind_loopback_accepts_explicit_backlog_override():
    sock = bind_loopback(0, backlog=4)
    try:
        assert sock.getsockname()[0] == "127.0.0.1"
    finally:
        sock.close()


def test_run_op_with_cwd_composes_a_non_leaking_subshell_cd():
    server = make_server()
    server.handle_request({
        "token": TOKEN, "op": "run", "cmd": "pwd", "cwd": "/home/svcacct/AI/Agent",
    })
    assert server.session.run_calls == [("(cd '/home/svcacct/AI/Agent' && pwd)", 1800)]


def test_run_op_cwd_quoting_escapes_embedded_single_quotes():
    server = make_server()
    server.handle_request({
        "token": TOKEN, "op": "run", "cmd": "pwd", "cwd": "/tmp/o'brien",
    })
    cmd, _timeout = server.session.run_calls[0]
    assert cmd == "(cd '/tmp/o'\\''brien' && pwd)"


def test_run_op_cwd_equal_to_relays_own_startup_workdir_is_a_safe_noop():
    # VCWORKDIR (the relay's own cd-at-startup target) and DVWORKDIR (a
    # caller's per-request --cwd default) are independent env vars with no
    # cross-check between them -- a user pointing both at the same real
    # deployment path (the common case for a relay dedicated to one
    # environment) must not trigger any special-cased rejection or
    # behavior change. `cd` into the directory you are already in is a
    # normal no-op in both bash and tcsh.
    server = make_server()
    same_path = "/home/svcacct/AI/Agent"  # stands in for VCWORKDIR's value
    server.handle_request({
        "token": TOKEN, "op": "run", "cmd": "pwd", "cwd": same_path,
    })
    assert server.session.run_calls == [("(cd '/home/svcacct/AI/Agent' && pwd)", 1800)]


def test_run_op_without_cwd_key_is_unchanged_from_before():
    server = make_server()
    server.handle_request({"token": TOKEN, "op": "run", "cmd": "pwd"})
    assert server.session.run_calls == [("pwd", 1800)]


def test_run_op_denies_credential_inspection_hidden_in_cwd():
    server = make_server()
    resp = server.handle_request({
        "token": TOKEN, "op": "run", "cmd": "pwd", "cwd": "$VCPW",
    })
    assert resp["ok"] is False
    assert resp["error"] == "CREDENTIAL_INSPECTION_DENIED"
    assert server.session.run_calls == []


# --- MSYS path-mangling detection (2026-09-02) ---------------------------

def test_is_msys_mangled_path_detects_windows_drive_paths():
    assert is_msys_mangled_path("D:/Program Files/Git/home/x/y.txt") is True
    assert is_msys_mangled_path(r"C:\Users\x\home\y") is True


def test_is_msys_mangled_path_accepts_ordinary_unix_paths():
    assert is_msys_mangled_path("/home/svcacct/AI/Agent") is False
    assert is_msys_mangled_path("/tmp/x") is False


def test_is_msys_mangled_path_false_for_empty_or_none():
    assert is_msys_mangled_path("") is False
    assert is_msys_mangled_path(None) is False


def test_handle_request_serializes_concurrent_callers_no_interleaving():
    server = make_server()
    events = []
    events_lock = threading.Lock()

    class SlowSession(FakeSession):
        def run(self, cmd, timeout):
            with events_lock:
                events.append(("start", cmd))
            time.sleep(0.03)
            with events_lock:
                events.append(("end", cmd))
            return ("out", 0)

    server.session = SlowSession()

    def worker(n):
        server.handle_request({"token": TOKEN, "op": "run", "cmd": "cmd-%d" % n})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(events) == 12
    # Every "start" must be immediately followed by that same command's
    # "end" before any other command's "start" appears -- i.e. no two run()
    # calls ever overlap in time, regardless of how many threads call
    # handle_request() at once.
    for i in range(0, 12, 2):
        assert events[i][0] == "start"
        assert events[i + 1] == ("end", events[i][1])
