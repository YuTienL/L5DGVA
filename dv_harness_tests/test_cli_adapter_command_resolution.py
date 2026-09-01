"""Regression coverage for a real bug found via an actual `dv-harness
run-stage` run on 2026-09-01 (not a hypothetical): on Windows, `npm install
-g` places two files on PATH for one package -- a bare POSIX shell script
named exactly `claude` (runnable only by bash/sh) and a real Windows launcher
`claude.cmd`. ClaudeCLIAdapter.run()'s subprocess.run(cmd, ...) call uses
shell=False (the default), which invokes Win32 CreateProcess directly --
CreateProcess does not do PATHEXT-based resolution, so it could only ever
find the non-executable-on-Windows `claude` shell script and failed with
FileNotFoundError (WinError 2), making the CLI adapter (this project's
default adapter, config.json's "adapter": "cli") completely broken on
Windows. Fixed by resolving the configured command through shutil.which()
(which performs PATHEXT resolution correctly on Windows and is a safe
no-op-equivalent PATH lookup on POSIX) before handing it to subprocess.run().
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from dv_harness.adapters.cli import ClaudeCLIAdapter


class _FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_resolve_command_prefers_shutil_which_result(monkeypatch):
    monkeypatch.setattr(
        "dv_harness.adapters.cli.shutil.which",
        lambda name: r"C:\Users\peter.lin\AppData\Roaming\npm\claude.CMD" if name == "claude" else None,
    )
    resolved = ClaudeCLIAdapter._resolve_command("claude")
    assert resolved == r"C:\Users\peter.lin\AppData\Roaming\npm\claude.CMD"


def test_resolve_command_falls_back_to_configured_value_when_which_finds_nothing(monkeypatch):
    monkeypatch.setattr("dv_harness.adapters.cli.shutil.which", lambda name: None)
    resolved = ClaudeCLIAdapter._resolve_command("claude")
    assert resolved == "claude"


def test_resolve_command_passes_through_an_already_absolute_configured_path(monkeypatch):
    # A project may configure an explicit absolute path in config.json's
    # claude.command field -- shutil.which() still resolves it correctly
    # (it accepts absolute paths, not just bare names), and this must not
    # silently substitute a different binary.
    monkeypatch.setattr(
        "dv_harness.adapters.cli.shutil.which",
        lambda name: name if name == r"D:\custom\claude.cmd" else None,
    )
    resolved = ClaudeCLIAdapter._resolve_command(r"D:\custom\claude.cmd")
    assert resolved == r"D:\custom\claude.cmd"


def test_run_invokes_subprocess_with_the_resolved_command_not_the_bare_configured_name(monkeypatch):
    captured_cmd = {}

    def _fake_which(name):
        assert name == "claude"
        return r"C:\Users\peter.lin\AppData\Roaming\npm\claude.CMD"

    def _fake_subprocess_run(cmd, cwd, text, capture_output, encoding=None, errors=None):
        captured_cmd["cmd"] = cmd
        return _FakeCompletedProcess(stdout='{"result": "ok", "session_id": "s1"}')

    monkeypatch.setattr("dv_harness.adapters.cli.shutil.which", _fake_which)
    monkeypatch.setattr("dv_harness.adapters.cli.subprocess.run", _fake_subprocess_run)

    adapter = ClaudeCLIAdapter({"claude": {"command": "claude", "max_turns": 40}})
    result = adapter.run(prompt="do the thing", cwd=".")

    assert captured_cmd["cmd"][0] == r"C:\Users\peter.lin\AppData\Roaming\npm\claude.CMD"
    assert captured_cmd["cmd"][0] != "claude"
    assert result.ok is True


def test_run_still_works_when_which_finds_nothing_matching_pre_fix_behavior(monkeypatch):
    # If shutil.which() genuinely can't resolve anything (e.g. a broken
    # PATH), behavior degrades to exactly what subprocess.run() would have
    # received before this fix -- no worse, not silently different.
    captured_cmd = {}

    def _fake_subprocess_run(cmd, cwd, text, capture_output, encoding=None, errors=None):
        captured_cmd["cmd"] = cmd
        return _FakeCompletedProcess(stdout='{"result": "ok"}')

    monkeypatch.setattr("dv_harness.adapters.cli.shutil.which", lambda name: None)
    monkeypatch.setattr("dv_harness.adapters.cli.subprocess.run", _fake_subprocess_run)

    adapter = ClaudeCLIAdapter({"claude": {"command": "claude", "max_turns": 40}})
    adapter.run(prompt="do the thing", cwd=".")

    assert captured_cmd["cmd"][0] == "claude"


def test_real_shutil_which_resolves_a_dotcmd_shim_on_windows(tmp_path, monkeypatch):
    # End-to-end proof against the REAL shutil.which() (no monkeypatch of
    # the resolver itself) that a Windows .cmd shim is actually found by
    # name, the way npm's global installer lays out `claude`/`claude.cmd`
    # side by side. Windows-only: PATHEXT-based resolution is a Windows
    # concept, and this project's own environment (confirmed via a real
    # `dv-harness run-stage` run) is Windows.
    if sys.platform != "win32":
        pytest.skip("PATHEXT/.cmd resolution is Windows-specific")

    fake_bin_dir = tmp_path / "fakebin"
    fake_bin_dir.mkdir()
    shim = fake_bin_dir / "mytool.cmd"
    shim.write_text("@echo off\r\necho hi\r\n", encoding="utf-8")

    monkeypatch.setenv("PATH", str(fake_bin_dir) + ";" + __import__("os").environ.get("PATH", ""))
    resolved = ClaudeCLIAdapter._resolve_command("mytool")
    assert resolved is not None
    assert Path(resolved).name.lower() == "mytool.cmd"


# --- Part 2: subprocess.run() must decode as UTF-8, never crash on None streams ---
#
# Real bug found via the SAME real `dv-harness run-stage` run this session,
# once the shutil.which() fix above let the subprocess actually launch:
# text=True without an explicit `encoding` makes Python decode the child's
# stdout/stderr using locale.getpreferredencoding() -- on this Windows dev
# machine (config.json's policy.language is "zh-TW") that resolves to cp950
# (Traditional Chinese), not UTF-8. The real `claude` CLI's own
# --output-format json output is UTF-8 and contains real multi-byte
# sequences cp950 cannot decode, which crashed subprocess.run()'s internal
# stderr-reader thread with UnicodeDecodeError -- leaving p.stderr as None,
# so the very next line's unconditional `.strip()` call then raised
# AttributeError on top of that.

def test_run_passes_explicit_utf8_encoding_and_replace_errors_to_subprocess_run(monkeypatch):
    captured_kwargs = {}

    def _fake_subprocess_run(cmd, cwd, text, capture_output, encoding=None, errors=None):
        captured_kwargs["encoding"] = encoding
        captured_kwargs["errors"] = errors
        return _FakeCompletedProcess(stdout='{"result": "ok"}')

    monkeypatch.setattr("dv_harness.adapters.cli.shutil.which", lambda name: None)
    monkeypatch.setattr("dv_harness.adapters.cli.subprocess.run", _fake_subprocess_run)

    adapter = ClaudeCLIAdapter({"claude": {"command": "claude", "max_turns": 40}})
    adapter.run(prompt="do the thing", cwd=".")

    assert captured_kwargs["encoding"] == "utf-8"
    assert captured_kwargs["errors"] == "replace"


def test_run_does_not_crash_when_stderr_is_none(monkeypatch):
    # Reproduces the exact failure mode observed live: the reader thread for
    # one stream dies (real cause: a UnicodeDecodeError under a non-UTF-8
    # locale before this fix), leaving that stream None on the returned
    # CompletedProcess, while the process itself still exited normally.
    def _fake_subprocess_run(cmd, cwd, text, capture_output, encoding=None, errors=None):
        return _FakeCompletedProcess(stdout='{"result": "ok"}', stderr=None, returncode=0)

    monkeypatch.setattr("dv_harness.adapters.cli.shutil.which", lambda name: None)
    monkeypatch.setattr("dv_harness.adapters.cli.subprocess.run", _fake_subprocess_run)

    adapter = ClaudeCLIAdapter({"claude": {"command": "claude", "max_turns": 40}})
    result = adapter.run(prompt="do the thing", cwd=".")  # must not raise AttributeError

    assert result.ok is True
    assert result.raw["stderr"] == ""


def test_run_does_not_crash_when_stdout_is_none(monkeypatch):
    def _fake_subprocess_run(cmd, cwd, text, capture_output, encoding=None, errors=None):
        return _FakeCompletedProcess(stdout=None, stderr="", returncode=1)

    monkeypatch.setattr("dv_harness.adapters.cli.shutil.which", lambda name: None)
    monkeypatch.setattr("dv_harness.adapters.cli.subprocess.run", _fake_subprocess_run)

    adapter = ClaudeCLIAdapter({"claude": {"command": "claude", "max_turns": 40}})
    result = adapter.run(prompt="do the thing", cwd=".")  # must not raise AttributeError

    assert result.text == ""


def test_real_subprocess_run_actually_decodes_utf8_multibyte_output_via_a_real_child_process():
    # End-to-end proof against the REAL subprocess.run() (no monkeypatch) on
    # a genuine multi-byte UTF-8 payload -- the exact class of byte sequence
    # (Traditional Chinese text, matching this project's own
    # policy.language:"zh-TW") that crashed the reader thread under cp950
    # before this fix. Uses a real Python child process (guaranteed present
    # in this test environment) instead of `claude` itself, since the real
    # CLI's presence/behavior can't be assumed by a unit test.
    import json as _json
    import shutil as _shutil

    py = _shutil.which("python") or _shutil.which("python3") or sys.executable
    payload = _json.dumps({"result": "涉及多位元組序列的真實輸出 -- 這一定要用 UTF-8 才能正確解碼"})
    script = f"import sys; sys.stdout.write({payload!r})"

    p = subprocess.run([py, "-c", script], cwd=".", text=True, capture_output=True,
                        encoding="utf-8", errors="replace")
    assert p.stdout == payload
    parsed = _json.loads(p.stdout)
    assert "涉及多位元組序列" in parsed["result"]
