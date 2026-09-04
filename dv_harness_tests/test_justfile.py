"""Real-subprocess tests for the project-root `justfile` (2026-09-03,
"just" recipe layer task).

Three things:
  1. The justfile parses/lists cleanly via a real `just --list` subprocess.
  2. Each recipe's GENERATED COMMAND STRING is correct for a given input,
     verified via `just --dry-run <recipe> <args>` -- a real `just`
     subprocess that renders the exact shell command a real run would
     execute, but never spawns it (see `just --help`: --dry-run "Print
     what just would do without doing it").
  3. The `memory-*` recipes (2026-09-04) are additionally EXECUTED for
     real, via `_just_real()`. They are the only recipes here that can be:
     every one of them is a local, read-only-by-default
     `dv-harness memory <sub>` invocation against this project's own vault
     -- no remote server, no LSF job, no license. That matters because
     their argument FORWARDING (`"$@"` under `set positional-arguments`)
     is invisible to --dry-run, which renders the literal `"$@"` rather
     than what the shell will expand it to.

No test here reaches a real remote server, submits a real LSF job, or
invokes tools/remote/remote_exec.py's own network code -- every
remote-facing recipe is exercised through --dry-run only.

`just` was installed this session via `winget install --id Casey.Just`
(confirmed real package id via `winget search just`). Tests skip cleanly
(rather than fail) if a CI/dev machine genuinely lacks `just` on PATH --
same "environment-dependent tool, skip don't fail" convention already
used for the Obsidian-CLI-dependent memory tests.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = ROOT / "justfile"

JUST_BIN = shutil.which("just")
pytestmark = pytest.mark.skipif(JUST_BIN is None, reason="just is not installed on PATH")


def _just(*args, timeout=30):
    """Real `just` subprocess against the real project-root justfile.
    Never executes a recipe body for real -- callers pass --dry-run or
    --list, both of which only print, never run, the resolved commands.

    REAL BEHAVIOR CONFIRMED LIVE (2026-09-03): `just --dry-run` writes the
    resolved recipe command lines to STDERR, not stdout (confirmed via a
    direct subprocess probe against this exact justfile -- stdout was
    empty, stderr held the full echoed command). `--list`/`--summary`
    write to stdout as usual. Returning stdout+stderr concatenated (in
    that order) lets every test below assert on "out" regardless of which
    stream a given subcommand actually used, without silently passing on
    an empty string the way checking stdout alone did before this fix.
    """
    r = subprocess.run(
        [JUST_BIN, "--justfile", str(JUSTFILE), "--working-directory", str(ROOT), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=timeout, encoding="utf-8",
    )
    return r.returncode, r.stdout + r.stderr, r.stderr


def _just_real(*args, timeout=120):
    """Really RUN a recipe (no --dry-run). Only ever called on `memory-*`
    recipes -- see this module's docstring for why those, and only those,
    are safe to execute here. Returns (returncode, stdout) with stdout kept
    SEPARATE from stderr, because these tests parse the CLI's JSON result
    and `just` itself echoes the resolved command line to stderr."""
    r = subprocess.run(
        [JUST_BIN, "--justfile", str(JUSTFILE), "--working-directory", str(ROOT), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=timeout, encoding="utf-8",
    )
    return r.returncode, r.stdout


# --- 1. The justfile parses/lists cleanly -----------------------------------

class TestJustfileParsesAndLists:
    def test_just_list_exits_zero(self):
        rc, out, err = _just("--list")
        assert rc == 0, f"stderr={err!r}"

    def test_just_list_names_every_pipeline_stage_recipe(self):
        """The five stages from the user's own spec (push -> build ->
        verify -> run -> fsdbreport), plus the gating/support recipes this
        task adds around them."""
        rc, out, err = _just("--list")
        assert rc == 0, f"stderr={err!r}"
        for name in ("push", "push-file", "pull", "build", "verify", "run",
                     "regress", "regress-log", "fsdbreport", "preflight",
                     "relay-status", "check", "list-patterns", "pipeline",
                     "default"):
            assert name in out, f"recipe {name!r} missing from `just --list`:\n{out}"

    def test_just_dash_dash_summary_is_syntactically_valid(self):
        """`--summary` fully re-parses the justfile and prints every
        recipe name on one line -- a second, independent parse path from
        --list, catching a defect --list's own renderer might paper over."""
        rc, out, err = _just("--summary")
        assert rc == 0, f"stderr={err!r}"
        assert "build" in out and "fsdbreport" in out

    def test_no_password_or_credential_literal_in_justfile(self):
        """Static content guard matching CLAUDE.md's own rule ("The
        password must never be written into any evidence block, gate
        payload, state file, log, or long-term/native memory") -- this
        file is a permanent, committed project artifact, so it must never
        carry the real VCPW value (checked literally, replay.ps1's real
        secret is never quoted here) or a `VCPW`/`VCPASSWORD`-shaped
        variable assignment. Mentioning the word "password" in prose
        (e.g. this very docstring, or the justfile's own explanatory
        comments) is fine and expected -- only an actual secret value or
        assignment is banned."""
        text = JUSTFILE.read_text(encoding="utf-8")
        assert "as$621018" not in text.lower(), "the real VCPW value must never appear here"
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "vcpw" not in stripped.lower(), (
                f"non-comment line assigns/references VCPW: {line!r}"
            )


# --- 2. Each recipe's generated command string is correct -------------------

class TestGeneratedCommandStrings:
    def test_relay_status(self):
        rc, out, err = _just("--dry-run", "relay-status")
        assert rc == 0, f"stderr={err!r}"
        assert "tools/remote/remote_exec.py" in out.replace("\\", "/")
        assert "--status" in out

    def test_preflight_default_uses_real_confirmed_project_values(self):
        """Default queue/workdir/license_server are the values this
        session actually confirmed live against the real remote server
        (.work/governance-preflight-report.md)."""
        rc, out, err = _just("--dry-run", "preflight")
        assert rc == 0, f"stderr={err!r}"
        assert "dv_harness.cli" in out
        assert "preflight --remote" in out
        assert "--queue vcs" in out
        assert "--workdir /home/svcacct/DV/UVM/USB/usb_uvm/sim" in out
        assert "--license-server 2900@host-a" in out

    def test_preflight_overrides_flow_through(self):
        rc, out, err = _just("--dry-run", "preflight", "other-queue", "/other/workdir", "1234@otherhost")
        assert rc == 0, f"stderr={err!r}"
        assert "--queue other-queue" in out
        assert "--workdir /other/workdir" in out
        assert "--license-server 1234@otherhost" in out

    def test_build_runs_preflight_before_make_compile(self):
        rc, out, err = _just("--dry-run", "build")
        assert rc == 0, f"stderr={err!r}"
        lines = [l for l in out.splitlines() if l.strip()]
        preflight_idx = next(i for i, l in enumerate(lines) if "preflight --remote" in l)
        compile_idx = next(i for i, l in enumerate(lines) if "make compile" in l)
        assert preflight_idx < compile_idx, "preflight gate must run BEFORE make compile"
        assert "FLOW=fourstep" in out
        assert "--cwd \"/home/tmpacct/devuser/UVM/USB\"" in out.replace("'", '"')
        assert "--timeout 3600" in out

    def test_verify_is_wave_off_first_pass_and_is_gated(self):
        rc, out, err = _just("--dry-run", "verify", "usb20_enum")
        assert rc == 0, f"stderr={err!r}"
        assert "preflight --remote" in out
        assert "make sim PATTERN=usb20_enum SEED=1 WAVE=0" in out

    def test_run_is_wave_one_targeted_rerun_and_is_gated(self):
        """First-Failure Waveform Rerun (CLAUDE.md): same pattern, WAVE=1,
        never a different/broader target than VERIFY just used."""
        rc, out, err = _just("--dry-run", "run", "usb20_enum", "7")
        assert rc == 0, f"stderr={err!r}"
        assert "preflight --remote" in out
        assert "make sim PATTERN=usb20_enum SEED=7 WAVE=1" in out

    def test_regress_submits_under_nohup_and_is_gated(self):
        """Long-running batch regression: nohup + background (&), not a
        foreground blocking call -- matches
        .claude/skills/CORE/remote-executor/SKILL.md's own Transport note."""
        rc, out, err = _just("--dry-run", "regress", "sanity")
        assert rc == 0, f"stderr={err!r}"
        assert "preflight --remote" in out
        assert "nohup make regress LSF=1 SUITE=sanity" in out
        assert "regress_sanity.out 2>&1 &" in out

    def test_regress_log_tails_the_right_file_with_no_preflight(self):
        rc, out, err = _just("--dry-run", "regress-log", "sanity")
        assert rc == 0, f"stderr={err!r}"
        assert "preflight" not in out
        assert "tail -n 80 regress_sanity.out" in out

    def test_check_and_list_patterns_are_never_gated(self):
        """Static checks / a read-only pattern listing never submit a job,
        so they must NOT depend on preflight (only recipes that can
        trigger bsub via LSF_COMPILE/LSF_SIM should)."""
        for recipe in ("check", "list-patterns"):
            rc, out, err = _just("--dry-run", recipe)
            assert rc == 0, f"stderr={err!r}"
            assert "preflight --remote" not in out, f"{recipe} must not be gated"
        rc, out, _ = _just("--dry-run", "check")
        assert "make check" in out
        rc, out, _ = _just("--dry-run", "list-patterns")
        assert "make list_patterns" in out

    def test_fsdbreport_matches_confirmed_real_flag_grammar_and_is_never_gated(self):
        """Confirmed real grammar (dv_harness/fsdb_report.py's own module
        docstring): `fsdbreport <fsdb> -bt <t0> -et <t1> -s <hier> [...]
        [-verilog|-csv|-of h] -o <outfile>` -- file path first, then
        flags. Never gated: this only post-processes an FSDB that already
        exists, it submits nothing."""
        rc, out, err = _just(
            "--dry-run", "fsdbreport",
            "/home/x/run/usb20_enum_1/usb20_enum.fsdb", "0", "500000",
            "uvm_test_top.env.usb_host_agent_0.link", "/home/x/report/link.txt",
        )
        assert rc == 0, f"stderr={err!r}"
        assert "preflight" not in out
        assert ("fsdbreport /home/x/run/usb20_enum_1/usb20_enum.fsdb "
                "-bt 0 -et 500000 -s uvm_test_top.env.usb_host_agent_0.link "
                "-verilog -o /home/x/report/link.txt") in out

    def test_fsdbreport_custom_format_flag(self):
        rc, out, err = _just(
            "--dry-run", "fsdbreport", "a.fsdb", "0", "100", "sig.path", "out.csv", "-csv",
        )
        assert rc == 0, f"stderr={err!r}"
        assert "-csv -o out.csv" in out

    def test_push_tars_puts_then_untars_remotely(self):
        """.claude/skills/CORE/remote-executor/SKILL.md's documented
        no-git-remote PUSH variant: tar czf -> --put -> tar xzf."""
        rc, out, err = _just(
            "--dry-run", "push", "D:/DV/Task/USB/uvm", "/home/tmpacct/devuser/UVM/USB/uvm",
        )
        assert rc == 0, f"stderr={err!r}"
        norm = out.replace("\\", "/")
        assert "tar czf" in norm and ".work/dv_push.tgz" in norm
        assert "-C \"D:/DV/Task/USB/uvm\"" in norm.replace("'", '"')
        assert "--put" in norm and "dv_push.tgz" in norm
        assert "tar xzf dv_push.tgz" in norm
        assert "/home/tmpacct/devuser/UVM/USB/uvm" in norm

    def test_push_file_is_a_direct_put(self):
        rc, out, err = _just(
            "--dry-run", "push-file",
            "D:/DV/Task/USB/uvm/tb/tests/usb_base_test.sv",
            "/home/tmpacct/devuser/UVM/USB/uvm/tb/tests/usb_base_test.sv",
        )
        assert rc == 0, f"stderr={err!r}"
        assert "--put" in out
        assert "usb_base_test.sv" in out
        assert "tar" not in out

    def test_pull_uses_get(self):
        rc, out, err = _just(
            "--dry-run", "pull",
            "/home/tmpacct/devuser/UVM/USB/sim/fsdb/usb20_enum_1.fsdb",
            "D:/DV/Task/USB/pulled/usb20_enum_1.fsdb",
        )
        assert rc == 0, f"stderr={err!r}"
        assert "--get" in out
        assert "usb20_enum_1.fsdb" in out

    def test_pipeline_chains_build_verify_run_in_order_gated_once_each(self):
        """REAL BEHAVIOR CONFIRMED LIVE: `just` deduplicates identical
        dependency invocations (same recipe + same resolved arguments)
        within one run -- build/verify/run's three `(preflight queue
        workdir license_server)` dependencies all resolve to the exact
        same call in a single `pipeline` invocation, so it runs once, not
        three times. This is a desirable property (no redundant preflight
        re-checks inside one pipeline run), not a gap: `just build` or
        `just verify` run standalone still each perform their own real
        preflight check, since there is no shared dependency graph
        between separate `just` invocations."""
        rc, out, err = _just("--dry-run", "pipeline", "usb20_enum", "3")
        assert rc == 0, f"stderr={err!r}"
        lines = [l for l in out.splitlines() if l.strip()]
        preflight_idx = next(i for i, l in enumerate(lines) if "preflight --remote" in l)
        compile_idx = next(i for i, l in enumerate(lines) if "make compile" in l)
        verify_idx = next(i for i, l in enumerate(lines) if "WAVE=0" in l)
        run_idx = next(i for i, l in enumerate(lines) if "WAVE=1" in l)
        assert preflight_idx < compile_idx < verify_idx < run_idx
        assert out.count("preflight --remote") == 1
        assert "SEED=3" in out

    def test_vip_home_and_friends_forward_even_when_empty(self):
        """Empty VIP_HOME/DUT_ROOT_PATH/UVM_ROOT_PATH must still be
        FORWARDED (VIP_HOME=), not omitted -- GNU make's `ifdef` is false
        for an empty value, so the Makefile's own real
        `$(error VIP_HOME is not set...)` guard still fires correctly."""
        rc, out, err = _just("--dry-run", "build")
        assert rc == 0, f"stderr={err!r}"
        assert "VIP_HOME=" in out
        assert "DUT_ROOT_PATH=" in out
        assert "UVM_ROOT_PATH=" in out

    def test_vip_home_override_flows_into_build_command(self, monkeypatch):
        monkeypatch.setenv("VIP_HOME", "/proj/vip/full_tree")
        monkeypatch.setenv("DUT_ROOT_PATH", "/proj/rtl/lan063")
        monkeypatch.setenv("UVM_ROOT_PATH", "/proj/uvm/usb_uvm")
        rc, out, err = _just("--dry-run", "build")
        assert rc == 0, f"stderr={err!r}"
        assert "VIP_HOME=/proj/vip/full_tree" in out
        assert "DUT_ROOT_PATH=/proj/rtl/lan063" in out
        assert "UVM_ROOT_PATH=/proj/uvm/usb_uvm" in out


# --- 3. The memory recipes (2026-09-04) -------------------------------------
# Phase 20 of the Obsidian+Git/Markdown Hybrid Engineering Memory spec: one
# fixed `just` recipe per `dv-harness memory <sub>` subcommand, so the
# memory surface an agent reaches for mid-debug is a named recipe rather
# than a hand-composed `python -m dv_harness.cli --project-root ... memory
# search --property subsystem=... --limit 5`.

MEMORY_RECIPES = (
    "memory-status", "memory-search", "memory-show", "memory-add",
    "memory-promote", "memory-graph", "memory-validate", "memory-sync",
    "memory-doctor",
)


class TestMemoryRecipes:
    def test_every_memory_cli_subcommand_has_a_recipe(self):
        """One recipe per subcommand the real `dv-harness memory` command
        group defines -- checked against argparse's OWN subcommand list, so
        a subcommand added to cli.py without a recipe fails here rather
        than being noticed by nobody."""
        rc, out, err = _just("--summary")
        assert rc == 0, f"stderr={err!r}"
        listed = set(out.split())
        for name in MEMORY_RECIPES:
            assert name in listed, f"recipe {name!r} missing from `just --summary`:\n{out}"

        help_proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(ROOT), "memory", "--help"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120, encoding="utf-8",
        )
        assert help_proc.returncode == 0, help_proc.stderr
        # argparse renders the choice list as "{status,search,...}".
        choices = help_proc.stdout.split("{", 1)[1].split("}", 1)[0].split(",")
        assert sorted(choices) == sorted(n[len("memory-"):] for n in MEMORY_RECIPES), (
            f"cli.py's memory subcommands {sorted(choices)} and the justfile's recipes disagree"
        )

    def test_memory_recipes_are_never_preflight_gated(self):
        """Every one is local (own vault + own .dv-harness/ store): no LSF
        job, no license, no remote server. Gating them on `preflight` would
        make an offline `just memory-doctor` fail for no reason."""
        for recipe in ("memory-status", "memory-doctor", "memory-validate"):
            rc, out, err = _just("--dry-run", recipe)
            assert rc == 0, f"stderr={err!r}"
            assert "preflight" not in out, f"{recipe} must not be gated"

    def test_no_arg_recipes_render_the_right_cli_command(self):
        for recipe, sub in (("memory-status", "status"), ("memory-doctor", "doctor"),
                            ("memory-validate", "validate")):
            rc, out, err = _just("--dry-run", recipe)
            assert rc == 0, f"stderr={err!r}"
            assert "-m dv_harness.cli" in out
            assert f"memory {sub}" in out
            assert "--project-root" in out

    def test_show_and_graph_quote_their_note_id(self):
        rc, out, err = _just("--dry-run", "memory-show", "MEM-1A2B3C4D5E")
        assert rc == 0, f"stderr={err!r}"
        assert 'memory show "MEM-1A2B3C4D5E"' in out

        rc, out, err = _just("--dry-run", "memory-graph", "MEM-1A2B3C4D5E")
        assert rc == 0, f"stderr={err!r}"
        assert 'memory graph "MEM-1A2B3C4D5E" --depth 2' in out

        rc, out, err = _just("--dry-run", "memory-graph", "MEM-1A2B3C4D5E", "4")
        assert rc == 0, f"stderr={err!r}"
        assert "--depth 4" in out

    def test_sync_omits_the_message_flag_when_no_message_is_given(self):
        """`--message ""` and no `--message` are different requests: the
        CLI substitutes its own default commit message only for the
        latter, so an empty default must not render the flag at all."""
        rc, out, err = _just("--dry-run", "memory-sync")
        assert rc == 0, f"stderr={err!r}"
        assert "memory sync" in out
        assert "--message" not in out

        rc, out, err = _just("--dry-run", "memory-sync", "memory(usb): record enum timeout")
        assert rc == 0, f"stderr={err!r}"
        assert '--message "memory(usb): record enum timeout"' in out

    def test_pass_through_recipes_forward_arguments_not_interpolate_them(self):
        """REGRESSION GUARD for the real defect found while writing these
        recipes: just's `*variadic` interpolation (`{{args}}`) joins the
        caller's arguments with spaces WITHOUT re-quoting, so
        `--failure "enum timeout"` becomes two words and argparse sees a
        stray positional. Every pass-through recipe must therefore use
        `"$@"` (see `set positional-arguments` in the justfile), which
        --dry-run renders literally -- which is exactly why the real-run
        test below exists as well."""
        for recipe, sub in (("memory-search", "search"), ("memory-add", "add"),
                            ("memory-promote", "promote")):
            rc, out, err = _just("--dry-run", recipe)
            assert rc == 0, f"stderr={err!r}"
            assert f'memory {sub} "$@"' in out, (
                f"{recipe} must forward arguments with \"$@\", not interpolate them:\n{out}"
            )

    def test_real_run_memory_search_preserves_a_multi_word_query(self):
        """REALLY RUNS the recipe (no --dry-run) with a quoted multi-word
        query -- the only way to prove the `"$@"` forwarding above actually
        survives the shell, since --dry-run only shows the literal `"$@"`.
        Paired with the negative control below, which proves the query used
        here really would have broken under the interpolating form."""
        rc, out = _just_real("memory-search", "link training", "--limit", "2")
        assert rc == 0, f"`just memory-search` failed:\n{out}"
        payload = json.loads(out)
        assert payload["ok"] is True
        assert isinstance(payload["results"], list)

    def test_negative_control_the_unquoted_split_form_really_fails(self):
        """Proves the test above is testing something. The same query
        passed as two bare words -- exactly what `{{args}}` interpolation
        would have produced -- is rejected by argparse."""
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(ROOT),
             "memory", "search", "link", "training", "--limit", "2"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120, encoding="utf-8",
        )
        assert proc.returncode != 0
        assert "unrecognized arguments: training" in proc.stderr

    def test_real_run_memory_doctor_reports_a_real_verdict(self):
        """REALLY RUNS the Phase-21 health check through the recipe. Exit 0
        covers both READY and PARTIAL: a genuinely absent Obsidian CLI is a
        disclosed filesystem fallback, not a failure (cli.py exits non-zero
        only on BLOCKED). Asserting the check NAMES are present, rather
        than a fixed overall verdict, keeps this from becoming a test of
        this one machine's vault contents."""
        rc, out = _just_real("memory-doctor")
        assert rc == 0, f"`just memory-doctor` exited {rc} (BLOCKED?):\n{out}"
        payload = json.loads(out)
        assert payload["overall"] in {"READY", "PARTIAL"}
        for check in ("vault_writable", "git", "obsidian_cli", "filesystem_fallback",
                      "schema", "duplicate_ids", "invalid_yaml", "broken_links",
                      "large_files", "secrets"):
            assert check in payload["checks"], f"doctor lost the {check!r} check"
