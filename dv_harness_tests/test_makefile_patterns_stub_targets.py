"""Tests for .claude/templates/Makefile.patterns.mk (make-pattern-api-stub-targets-implementation,
2026-09-01): run-pattern/verify-pattern/regression/regression-monitor/regression-report used to be
silent `@echo`-only no-ops that always exited 0 with no real logic behind them -- an agent running
e.g. `make run-pattern` got a confident-looking "Run foo ..." line and a clean exit, with NO
simulator ever invoked. See .work/make-pattern-api-doc-fix-report.md, which first found this, and
.work/make-pattern-api-stub-targets-implementation-report.md for the fix.

`make` itself is not installed in this sandbox (`command -v make` finds nothing), so these tests
verify the fragment two ways instead of a live `make <target>` run:
  1. Static structural assertions on the recipe text (regex over the real file) -- no bare-echo-only
     body remains, each fixed target either fails loudly via $(error) or calls a real, generic
     tool.
  2. Direct subprocess execution of the exact `python3 -m dv_harness[.regression_reporter] ...`
     command lines the regression-monitor/regression-report recipes now contain, proving the
     generic (no-SIM_DIR-needed) half of the fix actually runs and exits 0 -- bypassing `make`,
     since it is unavailable here, but exercising the real underlying command.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MK_PATH = ROOT / ".claude" / "templates" / "Makefile.patterns.mk"

STUB_TARGETS = ["run-pattern", "verify-pattern", "regression", "regression-monitor", "regression-report"]
REAL_TARGETS = ["add-pattern", "validate-pattern", "list-patterns", "show-pattern",
                "regression-add", "regression-remove"]


def _mk_text() -> str:
    return MK_PATH.read_text(encoding="utf-8")


def _recipe_body(text: str, target: str) -> str:
    """Extract the recipe lines (tab-indented) directly under `<target>:` up to the next
    top-level (column-0, non-comment, non-blank) line. Mirrors how Make itself associates a
    recipe with its rule header."""
    pattern = re.compile(
        r"^" + re.escape(target) + r":[^\n]*\n((?:[ \t]+.*\n?|[ \t]*\n)*)",
        re.MULTILINE,
    )
    m = pattern.search(text)
    assert m, f"could not find a `{target}:` rule in {MK_PATH}"
    return m.group(1)


def _real_subcommands_in(cli_source: str) -> set:
    return set(re.findall(r'sub\.add_parser\(\s*"([^"]+)"', cli_source))


class TestNoSilentNoOpStubsRemain:
    """The core bug: a body that is ONLY `@echo` lines (optionally with `--` continuation echoes)
    always exits 0 having done nothing real. None of the five fixed targets may still look like
    that."""

    @pytest.mark.parametrize("target", STUB_TARGETS)
    def test_body_is_not_echo_only(self, target):
        text = _mk_text()
        body = _recipe_body(text, target)
        real_lines = [ln for ln in body.splitlines() if ln.strip()]
        assert real_lines, f"{target}: recipe body is empty"
        non_echo_lines = [ln for ln in real_lines if "echo" not in ln]
        assert non_echo_lines, (
            f"{target}: every recipe line still contains 'echo' -- this is exactly the silent "
            f"no-op stub shape the fix was supposed to remove. Body was:\n{body}"
        )

    @pytest.mark.parametrize("target", STUB_TARGETS)
    def test_body_either_errors_loudly_or_calls_a_real_tool(self, target):
        text = _mk_text()
        body = _recipe_body(text, target)
        has_error_guard = "$(error" in body
        has_real_invocation = bool(re.search(r"\$\(MAKE\)\s+-C\s+\$\(SIM_DIR\)|python3\s+-m\s+dv_harness", body))
        assert has_error_guard or has_real_invocation, (
            f"{target}: neither an $(error ...) loud-failure guard nor a real "
            f"`$(MAKE) -C $(SIM_DIR) ...` / `python3 -m dv_harness...` invocation was found -- "
            f"this looks like it is still (or newly) a silent no-op. Body was:\n{body}"
        )


class TestErrorGuardedLayer1Delegation:
    """run-pattern/verify-pattern/regression cannot know a project's real VCS/simulator
    invocation generically (see the file's own header comment / CLAUDE.md's Evidence Truth Rule)
    -- they must fail loudly via $(error) when SIM_DIR is unset, and actually delegate to the
    real generated per-IP sim Makefile's own target once it is set."""

    @pytest.mark.parametrize("target,real_layer1_target", [
        ("run-pattern", "run"),
        ("verify-pattern", "check"),
        ("regression", "regress"),
    ])
    def test_has_sim_dir_error_guard(self, target, real_layer1_target):
        body = _recipe_body(_mk_text(), target)
        assert "$(if $(SIM_DIR)" in body and "$(error" in body, (
            f"{target}: missing a SIM_DIR-unset $(error) guard -- it must fail loudly, not "
            f"silently succeed, when the one genuinely project-specific fact it needs is absent"
        )
        assert "SIM_DIR" in re.search(r"\$\(error[^)]*\)", body, re.DOTALL).group(0), (
            f"{target}: $(error ...) message does not mention SIM_DIR -- it must explain exactly "
            f"what project-specific configuration is missing, per the task's requirement"
        )

    @pytest.mark.parametrize("target,real_layer1_target", [
        ("run-pattern", "run"),
        ("verify-pattern", "check"),
        ("regression", "regress"),
    ])
    def test_delegates_to_the_real_layer1_target_when_configured(self, target, real_layer1_target):
        body = _recipe_body(_mk_text(), target)
        assert re.search(r"\$\(MAKE\)\s+-C\s+\$\(SIM_DIR\)\s+" + re.escape(real_layer1_target) + r"\b", body), (
            f"{target}: does not delegate to Layer 1's real `{real_layer1_target}` target via "
            f"`$(MAKE) -C $(SIM_DIR) {real_layer1_target}`"
        )

    def test_verify_pattern_chains_check_then_recorded_sim(self):
        """The doc-fix report's own finding: verify-pattern has NO single Layer-1 equivalent --
        closest is check (static) + sim/RECORD=1 (dynamic). This is what must actually run."""
        body = _recipe_body(_mk_text(), "verify-pattern")
        assert re.search(r"\$\(MAKE\)\s+-C\s+\$\(SIM_DIR\)\s+check\b", body)
        sim_call = re.search(r"\$\(MAKE\)\s+-C\s+\$\(SIM_DIR\)\s+sim\b.*", body)
        assert sim_call, "verify-pattern must also invoke the real `sim` target"
        assert "RECORD=1" in sim_call.group(0), (
            "verify-pattern's dynamic step must pass RECORD=1 so the verdict is actually recorded "
            "(the whole point of 'verify', not just 'run')"
        )

    @pytest.mark.parametrize("real_layer1_target,real_sim_makefile_targets", [
        ("run", None), ("check", None), ("regress", None),
    ])
    def test_real_layer1_target_actually_exists(self, real_layer1_target, real_sim_makefile_targets):
        """Cross-check against the actual generated sim Makefile template so a rename on that
        side cannot silently leave this fragment delegating to a target that no longer exists."""
        sim_mk = (ROOT / "dv_harness" / "uvm_generator" / "templates" / "sim_scripts" / "Makefile").read_text(encoding="utf-8")
        assert re.search(r"^" + re.escape(real_layer1_target) + r":", sim_mk, re.MULTILINE), (
            f"Layer-1 sim Makefile template no longer defines a `{real_layer1_target}:` target -- "
            f"Makefile.patterns.mk's delegation is now stale"
        )


class TestGenericRegressionMonitorAndReport:
    """regression-monitor/regression-report need no project-specific SIM_DIR -- dv_harness itself
    is the generic, already-tested tool that reads/reports .dv-harness/lsf/jobs/*.json, the same
    state tree this fragment's own REGRESSION_LIST bookkeeping lives next to."""

    def test_regression_monitor_calls_real_dv_harness_cli_subcommands(self):
        body = _recipe_body(_mk_text(), "regression-monitor")
        cli_source = (ROOT / "dv_harness" / "cli.py").read_text(encoding="utf-8")
        real_subcommands = _real_subcommands_in(cli_source)
        invoked = re.findall(r"python3\s+-m\s+dv_harness\s+--project-root\s+\S+\s+([a-z-]+)", body)
        assert invoked, "regression-monitor does not invoke `python3 -m dv_harness ... <subcommand>` at all"
        for cmd in invoked:
            assert cmd in real_subcommands, (
                f"regression-monitor invokes `dv-harness {cmd}`, which is not a real subcommand "
                f"registered in dv_harness/cli.py (real ones: {sorted(real_subcommands)})"
            )
        assert "lsf-watch-status" in invoked, "regression-monitor should report background-watcher liveness"
        assert "lsf" in invoked, "regression-monitor should report the actual per-job state table"

    def test_regression_report_calls_the_real_regression_reporter_module(self):
        body = _recipe_body(_mk_text(), "regression-report")
        assert re.search(r"python3\s+-m\s+dv_harness\.regression_reporter\s+--project-root\s+\S+", body), (
            "regression-report does not invoke the real dv_harness.regression_reporter CLI entry point"
        )
        assert (ROOT / "dv_harness" / "regression_reporter.py").exists()
        reporter_src = (ROOT / "dv_harness" / "regression_reporter.py").read_text(encoding="utf-8")
        assert "if __name__" in reporter_src and "--project-root" in reporter_src, (
            "dv_harness/regression_reporter.py no longer exposes the --project-root CLI entry "
            "point Makefile.patterns.mk's regression-report now depends on"
        )


class TestExactCommandsActuallyRun:
    """Bypassing `make` (not installed in this sandbox) but running the EXACT command lines the
    fixed recipes now contain, against a real empty project root, to prove the generic half of the
    fix is not just syntactically present but functionally correct."""

    def test_regression_monitor_commands_exit_zero_on_empty_project(self, tmp_path):
        for cmd in (
            [sys.executable, "-m", "dv_harness", "--project-root", str(tmp_path), "lsf-watch-status"],
            [sys.executable, "-m", "dv_harness", "--project-root", str(tmp_path), "lsf"],
        ):
            result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, f"{cmd} failed: stdout={result.stdout!r} stderr={result.stderr!r}"
            assert result.stdout.strip(), f"{cmd} produced no output at all"

    def test_regression_report_command_exits_zero_and_renders_a_real_snapshot(self, tmp_path):
        cmd = [sys.executable, "-m", "dv_harness.regression_reporter", "--project-root", str(tmp_path)]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"{cmd} failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "Periodic Regression Snapshot" in result.stdout
        assert "Total: 0" in result.stdout

    def test_regression_report_reflects_a_real_registered_job(self, tmp_path):
        """Same command, but against a project root that actually has a registered LSF job state
        -- proving this is a real report, not a hardcoded string."""
        from dv_harness import lsf_client

        lsf_client.save_job_state(
            tmp_path,
            lsf_client.JobState(job_id=4242, pattern="usb2_enum", lsf_status="DONE", sim_status="PASS"),
        )
        cmd = [sys.executable, "-m", "dv_harness.regression_reporter", "--project-root", str(tmp_path)]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        assert "4242" in result.stdout
        assert "usb2_enum" in result.stdout
        assert "Total: 1" in result.stdout


class TestPreExistingRealTargetsUntouched:
    """The 6 already-real targets from the prior doc-fix pass must not have regressed."""

    @pytest.mark.parametrize("target,must_contain", [
        ("add-pattern", "tools/generate_pattern_registry.py"),
        ("validate-pattern", "tools/verification_flow/pattern_registry_completeness_gate.py"),
        ("list-patterns", "$(PATTERN_REGISTRY_OUT)/pattern_list.txt"),
        ("show-pattern", "$(PATTERN_REGISTRY_OUT)/pattern_list.txt"),
        ("regression-add", "tools/regression_list_cli.py"),
        ("regression-remove", "tools/regression_list_cli.py"),
    ])
    def test_real_target_unchanged(self, target, must_contain):
        body = _recipe_body(_mk_text(), target)
        assert must_contain in body

    def test_phony_declaration_still_lists_all_eleven_targets(self):
        text = _mk_text()
        phony_block = re.search(r"\.PHONY:\s*((?:[^\n]*\\\n)*[^\n]*)", text).group(1)
        names = set(re.findall(r"[a-zA-Z-]+", phony_block))
        for t in STUB_TARGETS + REAL_TARGETS:
            assert t in names, f"{t} missing from .PHONY declaration"
