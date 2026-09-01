# Regression tests for the cross-adapter-token-tracking-tests-and-final-
# verification pass (2026-09-01, final task of the runtime-progress-
# visibility workflow).
#
# Context: an earlier audit confirmed token counting is REAL for the default
# CLI adapter (dv_harness/adapters/cli.py parses `claude -p --output-format
# json`'s genuine `response.usage` block) but stage_profile.py's own
# extract_provider_usage() docstring already ACKNOWLEDGES that the SDK
# adapter (dv_harness/adapters/sdk.py) never surfaces usage at all -- it
# returns an all-None dict for that adapter by design, not as a bug. That
# was previously only a docstring claim with no dedicated regression test
# exercising the SDK adapter's own raw-response shape (the one existing test,
# test_engine_gates_and_routing.py::test_extract_provider_usage_and_profiler_
# round_trip, only ever constructs a CLI-shaped raw dict). This file:
#
#   1. Proves extract_provider_usage() returns an all-None dict for every
#      real raw-response shape dv_harness/adapters/sdk.py's
#      ClaudeCodeSDKAdapter.run() actually produces (success, SDK-not-
#      installed ImportError, and an in-flight exception) -- not just the
#      CLI path.
#   2. Drives DVHarness.run_stage() end-to-end with a REAL
#      ClaudeCodeSDKAdapter instance (never a hand-built raw dict standing
#      in for it) on both the "package genuinely absent" branch (true in
#      this environment -- see the module-level SDK_INSTALLED check) and a
#      "package present and returns real messages" branch (simulated via a
#      minimal fake `claude_code_sdk` module injected into sys.modules,
#      exercising sdk.py's actual asyncio/query/AgentResult-construction
#      code, not a monkeypatched run() method), and confirms the persisted
#      StageExecutionProfiler record carries all-None token fields on both
#      branches.
#   3. Proves stage_profile_report.render() -- the one real rendering
#      surface both `dv-harness stage-profile` (cli.py) and dashboard.py's
#      "Stage Execution Profile" card serve verbatim (see dashboard.py's
#      GET /api/stage-profile handler) -- visibly labels an SDK-adapter-
#      configured project's N/A token columns as a known adapter limitation
#      instead of leaving an unexplained blank/N/A a user could mistake for
#      a broken measurement, and that a CLI-adapter-configured project (or a
#      project with no config.json at all) never shows that label.
#
# RULING: this task's job is explicitly NOT to make the SDK adapter suddenly
# report real tokens (that needs upstream claude-code-sdk changes, out of
# scope) -- every assertion below confirms the all-None/labeled-limitation
# behavior is correct and regression-tested, never that real SDK token
# counts appear.
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

import pytest

from dv_harness.stage_profile import StageExecutionProfiler, extract_provider_usage
from dv_harness.adapters.sdk import ClaudeCodeSDKAdapter
from dv_harness.adapters.base import AgentResult
from dv_harness import stage_profile_report
from dv_harness.config import load_config, save_config

from dv_harness_tests.test_engine_gates_and_routing import (
    _mk_smoke_project, _DISCOVERY_EXTRA_GATES,
)

try:
    import claude_code_sdk  # noqa: F401
    SDK_INSTALLED = True
except ImportError:
    SDK_INSTALLED = False

_ALL_NONE_USAGE = {
    "input_tokens": None, "output_tokens": None,
    "cache_read_tokens": None, "cache_write_tokens": None,
}


# --- Part 1: extract_provider_usage() against every real sdk.py raw shape ---

def test_extract_provider_usage_all_none_for_real_sdk_success_raw_shape():
    # Exact literal shape ClaudeCodeSDKAdapter.run() returns on success (see
    # adapters/sdk.py: `AgentResult(True, text, {"messages": [str(m) for m
    # in messages]})`) -- no "response" key at all, unlike the CLI adapter's
    # raw["response"]["usage"] shape.
    raw = {"messages": ["assistant: analysis done."]}
    assert extract_provider_usage(raw) == _ALL_NONE_USAGE


def test_extract_provider_usage_all_none_for_real_sdk_import_error_raw_shape():
    # Exact literal shape when `claude_code_sdk` is not installed (the real,
    # current state of this environment -- see SDK_INSTALLED above):
    # `AgentResult(False, "...", {"error": str(e)}, is_error=True)`.
    raw = {"error": "No module named 'claude_code_sdk'"}
    assert extract_provider_usage(raw) == _ALL_NONE_USAGE


def test_extract_provider_usage_all_none_for_real_sdk_runtime_exception_raw_shape():
    # Exact literal shape of sdk.py's outer `except Exception as e` branch:
    # `AgentResult(False, str(e), {"error": repr(e)}, is_error=True)`.
    raw = {"error": "RuntimeError('boom')"}
    assert extract_provider_usage(raw) == _ALL_NONE_USAGE


def test_extract_provider_usage_all_none_for_empty_or_none_raw():
    # Degenerate inputs extract_provider_usage() must never raise on.
    assert extract_provider_usage({}) == _ALL_NONE_USAGE
    assert extract_provider_usage(None) == _ALL_NONE_USAGE


def test_sdk_adapter_not_installed_in_this_environment_returns_all_none_usage_directly():
    # Real (unmocked) call: claude_code_sdk is genuinely absent from this
    # environment's site-packages (see SDK_INSTALLED at module top), so this
    # exercises adapters/sdk.py's actual ImportError branch end-to-end, with
    # no faking at all, and feeds its real .raw straight through
    # extract_provider_usage() -- the same call sequence engine.py's
    # run_stage() makes.
    if SDK_INSTALLED:
        pytest.skip("claude_code_sdk is installed in this environment; "
                    "see test_sdk_adapter_success_path_via_injected_fake_module "
                    "for the installed-and-succeeding case instead.")
    adapter = ClaudeCodeSDKAdapter({"claude": {"max_turns": 40, "allowed_tools": []}})
    result = adapter.run("do the thing", cwd=str(Path(tempfile.gettempdir())))
    assert result.ok is False
    assert result.is_error is True
    assert extract_provider_usage(result.raw) == _ALL_NONE_USAGE


def _install_fake_claude_code_sdk(monkeypatch, reply_text):
    """Injects a minimal fake `claude_code_sdk` module into sys.modules so
    ClaudeCodeSDKAdapter.run()'s real code (the asyncio.run(_run()) loop,
    the `async for message in query(...)` iteration, and the real
    AgentResult({"messages": [...]}) construction) executes for real --
    only the external pip package itself is faked, not sdk.py's own logic.
    Mirrors the standard sys.modules-injection pattern for testing an
    optional-dependency adapter without requiring the real package."""
    class _FakeMessage:
        def __init__(self, text):
            self._text = text
        def __str__(self):
            return self._text

    class _FakeOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def _fake_query(prompt, options):
        yield _FakeMessage(reply_text)

    fake_mod = types.ModuleType("claude_code_sdk")
    fake_mod.query = _fake_query
    fake_mod.ClaudeCodeOptions = _FakeOptions
    monkeypatch.setitem(sys.modules, "claude_code_sdk", fake_mod)


def test_sdk_adapter_success_path_via_injected_fake_module_still_all_none_usage(monkeypatch):
    # Simulates claude-code-sdk being installed AND returning a genuine
    # successful response, by injecting a fake module (see helper above) so
    # sdk.py's real success-path code runs unmodified. Proves the "no
    # response.usage block" limitation holds even on a clean success, not
    # only on the ImportError/exception branches -- the SDK's raw response
    # shape (`{"messages": [...]}`) simply never carries usage data,
    # regardless of whether the call itself succeeded.
    _install_fake_claude_code_sdk(monkeypatch, "assistant: analysis done.")
    adapter = ClaudeCodeSDKAdapter({"claude": {"max_turns": 40, "allowed_tools": []}})
    result = adapter.run("do the thing", cwd=str(Path(tempfile.gettempdir())))
    assert result.ok is True
    assert "messages" in result.raw
    assert "response" not in result.raw
    assert extract_provider_usage(result.raw) == _ALL_NONE_USAGE


# --- Part 2: end-to-end through DVHarness.run_stage() with a REAL SDK adapter ---

def test_run_stage_with_real_sdk_adapter_not_installed_persists_all_none_tokens():
    # DISCOVERY, via a genuinely-not-installed claude_code_sdk (this
    # environment's real state) -- run_stage() hits ADAPTER_FAIL, but the
    # persisted stage profile record must still carry a well-formed,
    # all-None token entry (never a crash, never a fabricated 0).
    if SDK_INSTALLED:
        pytest.skip("claude_code_sdk is installed in this environment.")
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        h = DVHarness(tmp)
        h.adapter = ClaudeCodeSDKAdapter(h.cfg)
        h.blackboard.write("project", {"target_name": "usb_dev"}, source="INTAKE")
        h.set_stage("DISCOVERY")
        h.run_stage("verify the USB device controller")

        assert h.state.stages["DISCOVERY"]["status"] == "FAIL"

        recs = h.profiler.all_stages()
        assert len(recs) == 1
        agents = recs[0]["agents"]
        assert len(agents) == 1
        assert agents[0]["input_tokens"] is None
        assert agents[0]["output_tokens"] is None
        assert agents[0]["cache_read_tokens"] is None
        assert agents[0]["cache_write_tokens"] is None
        assert agents[0]["total_tokens"] is None
        assert recs[0]["total_tokens"] is None
    finally:
        shutil.rmtree(tmp)


def test_run_stage_with_real_sdk_adapter_success_still_persists_all_none_tokens(monkeypatch):
    # Same end-to-end path, but the fake-module injection makes the SDK
    # adapter genuinely PASS the stage (real evidence text, real gate
    # verification) -- proving the all-None token limitation is not an
    # artifact of the adapter failing; it holds on a real successful run
    # too, because the SDK's raw response shape structurally has nowhere to
    # carry usage data.
    _install_fake_claude_code_sdk(
        monkeypatch, "analysis done.\n" + _DISCOVERY_EXTRA_GATES)
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        h = DVHarness(tmp)
        h.adapter = ClaudeCodeSDKAdapter(h.cfg)
        h.blackboard.write("project", {"target_name": "usb_dev"}, source="INTAKE")
        h.set_stage("DISCOVERY")
        h.run_stage("verify the USB device controller")

        assert h.state.stages["DISCOVERY"]["status"] == "PASS"

        recs = h.profiler.all_stages()
        assert len(recs) == 1
        agents = recs[0]["agents"]
        assert len(agents) == 1
        assert agents[0]["input_tokens"] is None
        assert agents[0]["output_tokens"] is None
        assert agents[0]["total_tokens"] is None
        assert recs[0]["total_tokens"] is None
    finally:
        shutil.rmtree(tmp)


def test_run_stage_with_cli_adapter_by_contrast_persists_real_tokens():
    # Direct contrast fixture (same stage, same fixture project, CLI-shaped
    # raw response) proving this file's SDK-side all-None assertions are
    # genuinely adapter-specific, not a bug that would swallow CLI tokens
    # too. Mirrors test_engine_gates_and_routing.py's own
    # test_run_stage_records_add_agent_run_with_real_resolved_agent_name_not_stage_agent.
    tmp = _mk_smoke_project()
    try:
        from dv_harness.engine import DVHarness

        class _FakeCLIShapedAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(
                    ok=True, text="analysis done.\n" + _DISCOVERY_EXTRA_GATES,
                    raw={"response": {"model": "claude-x",
                                      "usage": {"input_tokens": 42, "output_tokens": 7}}},
                    session_id="sess-1")

        h = DVHarness(tmp)
        h.adapter = _FakeCLIShapedAdapter()
        h.blackboard.write("project", {"target_name": "usb_dev"}, source="INTAKE")
        h.set_stage("DISCOVERY")
        h.run_stage("verify the USB device controller")

        recs = h.profiler.all_stages()
        assert recs[0]["agents"][0]["input_tokens"] == 42
        assert recs[0]["agents"][0]["output_tokens"] == 7
    finally:
        shutil.rmtree(tmp)


# --- Part 3: stage_profile_report.render() surfaces the SDK-adapter limitation ---

def test_stage_profile_report_labels_sdk_adapter_token_limitation():
    tmp = Path(tempfile.mkdtemp())
    try:
        cfg = load_config(tmp)
        cfg["adapter"] = "sdk"
        save_config(tmp, cfg)

        profiler = StageExecutionProfiler(tmp)
        rec = profiler.begin_stage("DISCOVERY", "DISCOVERY")
        profiler.add_agent_run(rec["profile_id"], "analysis-agent", 1.0,
                                usage=_ALL_NONE_USAGE, status="PASS")
        profiler.end_stage(rec["profile_id"], status="PASS")

        report = stage_profile_report.render(str(tmp))
        assert "N/A" in report
        assert stage_profile_report.SDK_ADAPTER_TOKEN_NOTE in report
        assert "sdk" in report.lower()
    finally:
        shutil.rmtree(tmp)


def test_stage_profile_report_does_not_label_cli_adapter_projects():
    # A CLI-adapter-configured project's genuine N/A (e.g. a stage that
    # simply hasn't run an agent yet) must NEVER be mislabeled as the SDK
    # limitation -- the note is adapter-config-gated, not N/A-value-gated.
    tmp = Path(tempfile.mkdtemp())
    try:
        cfg = load_config(tmp)
        assert cfg["adapter"] == "cli"
        save_config(tmp, cfg)

        profiler = StageExecutionProfiler(tmp)
        rec = profiler.begin_stage("DISCOVERY", "DISCOVERY")
        profiler.end_stage(rec["profile_id"], status="PASS")

        report = stage_profile_report.render(str(tmp))
        assert "N/A" in report
        assert stage_profile_report.SDK_ADAPTER_TOKEN_NOTE not in report
    finally:
        shutil.rmtree(tmp)


def test_stage_profile_report_defaults_to_no_label_with_no_config_file_at_all():
    # No .dv-harness/config.json at all (report run against a bare project
    # root) must degrade to the documented "cli" default, never crash and
    # never fabricate the SDK note.
    tmp = Path(tempfile.mkdtemp())
    try:
        assert not (tmp / ".dv-harness" / "config.json").exists()
        report = stage_profile_report.render(str(tmp))
        assert stage_profile_report.SDK_ADAPTER_TOKEN_NOTE not in report
    finally:
        shutil.rmtree(tmp)


def test_configured_adapter_name_helper_direct():
    tmp = Path(tempfile.mkdtemp())
    try:
        assert stage_profile_report._configured_adapter_name(str(tmp)) == "cli"
        cfg = load_config(tmp)
        cfg["adapter"] = "sdk"
        save_config(tmp, cfg)
        assert stage_profile_report._configured_adapter_name(str(tmp)) == "sdk"
    finally:
        shutil.rmtree(tmp)
