"""Tests for the semantic RTL diff extension of dv_harness/change_impact.py
("Semantic Change Impact Engine (verify-first)", 2026-09-06).

The pre-existing half of change_impact.py (classify_risk(), compute_change_impact(),
select_regression(), ...) is FILE-PATH-DRIVEN and untouched by this addition --
this file tests only the new, additive functions: rtl_file_content_at_revision(),
semantic_diff_rtl_file(), compute_semantic_change_impact(), and the standalone
`python -m dv_harness.change_impact semantic-diff` CLI.

Discipline, matching this project's own convention (test_uvm_structural_lint.py,
test_verible_parser.py): every test that needs the REAL `verible-verilog-syntax`
subprocess is SKIPPED, never mocked, on a machine without it -- a missing real
tool is a reported gap, never a reason to fabricate what its output would have
been. Tests that do not need verible (no-git, non-RTL files, and the explicit
"verible unavailable" negative control) always run, and are exactly the tests
that prove this module refuses to fabricate an answer when real evidence
(git, or verible) is absent.

Every real git repo here is a genuine throwaway repository built with real
commits, never a hand-typed diff or a mocked git call.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import change_impact as ci

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")
VERIBLE_BIN = "verible-verilog-syntax"
requires_git = pytest.mark.skipif(GIT is None, reason="git not on PATH")
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)


def _git(root, *args, check=True):
    r = subprocess.run([GIT, *args], cwd=str(root), capture_output=True, text=True,
                        timeout=120, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _init_repo(root):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q", "-b", "master", str(root)], check=True, timeout=60)
    _git(root, "config", "user.email", "semantic-change-impact@example.invalid")
    _git(root, "config", "user.name", "semantic-change-impact-test")


MODULE_V1 = (
    "module usb3_link_ctrl (\n"
    "    input  logic        clk,\n"
    "    input  logic        rst_n,\n"
    "    output logic [7:0]  status\n"
    ");\n"
    "  // straightforward status register\n"
    "  logic [7:0] internal_count;\n"
    "  always_ff @(posedge clk) begin\n"
    "    if (!rst_n) internal_count <= 8'h0;\n"
    "    else internal_count <= internal_count + 1'b1;\n"
    "  end\n"
    "  assign status = internal_count;\n"
    "endmodule\n"
)

BROKEN_SV = "module broken (\n  input logic clk\n// missing endmodule and closing paren\n"


# --- tests that never need verible (no-git, non-RTL, and the explicit -------
# "verible unavailable" negative control) ------------------------------------


def test_no_git_repo_reports_not_available(tmp_path):
    """A bare directory with no .git: the underlying diff() is NO_GIT, and
    compute_semantic_change_impact() must report NOT_AVAILABLE, never a
    fabricated empty-but-clean COMPUTED result."""
    report = ci.compute_semantic_change_impact(tmp_path, base_sha="HEAD~1", head_sha="HEAD")
    assert report["status"] == "NOT_AVAILABLE"
    assert report["per_file"] == []
    assert "NO_GIT" in report["detail"]


@requires_git
def test_unresolvable_base_reports_not_available(tmp_path):
    """A real repo, but base_sha does not resolve to a commit: the underlying
    diff() is UNKNOWN_BASE, and this must propagate as NOT_AVAILABLE rather
    than silently reporting no changes."""
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "a.sv").write_text("module a; endmodule\n", encoding="utf-8")
    _commit(root, "init")
    report = ci.compute_semantic_change_impact(root, base_sha="not-a-real-sha")
    assert report["status"] == "NOT_AVAILABLE"
    assert "UNKNOWN_BASE" in report["detail"]


@requires_git
def test_non_rtl_files_are_skipped_never_silently_dropped(tmp_path):
    """A changed .md file is not RTL/SV -- it must be reported under
    non_rtl_files_skipped (visible), never merged into per_file or dropped
    entirely, and this path needs no verible at all."""
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "notes.md").write_text("# v1\n", encoding="utf-8")
    sha1 = _commit(root, "v1")
    (root / "notes.md").write_text("# v2\n", encoding="utf-8")
    sha2 = _commit(root, "v2")

    report = ci.compute_semantic_change_impact(root, base_sha=sha1, head_sha=sha2)
    assert report["status"] == "COMPUTED"
    assert report["per_file"] == []
    assert report["non_rtl_files_skipped"] == ["notes.md"]
    assert report["interface_impacting_files"] == []


@requires_git
def test_verible_unavailable_never_fabricates_an_answer(tmp_path, monkeypatch):
    """The central negative control this house-style rule requires: with
    verible_parser genuinely unimportable, a real, genuinely-changed RTL file
    across two real commits must report NOT_AVAILABLE, changes=[],
    interface_impacting=False -- never a guessed CHANGED/BODY_ONLY_CHANGE
    result manufactured from file-path evidence alone."""
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "u.sv").write_text(MODULE_V1, encoding="utf-8")
    sha1 = _commit(root, "v1")
    (root / "u.sv").write_text(MODULE_V1.replace("[7:0]  status", "[15:0] status"),
                                encoding="utf-8")
    sha2 = _commit(root, "v2 widened status port")

    monkeypatch.setattr(ci, "_import_verible_parser", lambda: None)
    result = ci.semantic_diff_rtl_file(root, sha1, sha2, "u.sv")
    assert result["status"] == "NOT_AVAILABLE"
    assert result["changes"] == []
    assert result["interface_impacting"] is False
    assert "verible_parser" in result["detail"]


@requires_git
def test_file_added_reports_status_never_diffed_against_nothing(tmp_path):
    """A brand-new file (absent at base): reported FILE_ADDED, every module
    it introduces is a MODULE_ADDED finding, interface_impacting True -- no
    verible needed since there is nothing to structurally parse against."""
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "keep.sv") .write_text("module keep; endmodule\n", encoding="utf-8")
    sha1 = _commit(root, "v1")
    (root / "new_file.sv").write_text("module brand_new; endmodule\n", encoding="utf-8")
    sha2 = _commit(root, "v2 add new_file.sv")

    # This path only needs verible if the file is present at BOTH revisions
    # to compare content; here it needs to PARSE the head content once to
    # enumerate its modules, so skip cleanly if verible is unavailable.
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")

    result = ci.semantic_diff_rtl_file(root, sha1, sha2, "new_file.sv")
    assert result["status"] == "FILE_ADDED"
    assert result["interface_impacting"] is True
    kinds = {c["kind"] for c in result["changes"]}
    assert kinds == {ci.RTL_CHANGE_MODULE_ADDED}


# --- tests requiring the real verible-verilog-syntax subprocess -------------


@requires_git
@requires_verible
def test_file_unchanged_structurally_on_byte_identical_content(tmp_path):
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "u.sv").write_text(MODULE_V1, encoding="utf-8")
    sha1 = _commit(root, "v1")

    result = ci.semantic_diff_rtl_file(root, sha1, sha1, "u.sv")
    assert result["status"] == "FILE_UNCHANGED_STRUCTURALLY"
    assert result["changes"] == []
    assert result["interface_impacting"] is False


@requires_git
@requires_verible
def test_port_width_change_detected_as_interface_impacting(tmp_path):
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "u.sv").write_text(MODULE_V1, encoding="utf-8")
    sha1 = _commit(root, "v1")
    (root / "u.sv").write_text(MODULE_V1.replace("[7:0]  status", "[15:0] status"),
                                encoding="utf-8")
    sha2 = _commit(root, "v2 widened status port")

    result = ci.semantic_diff_rtl_file(root, sha1, sha2, "u.sv")
    assert result["status"] == "CHANGED"
    assert result["interface_impacting"] is True
    changes = result["changes"]
    assert len(changes) == 1
    c = changes[0]
    assert c["kind"] == ci.RTL_CHANGE_PORT_TYPE_OR_WIDTH_CHANGED
    assert c["module"] == "usb3_link_ctrl"
    assert "status" in c["detail"]
    assert "[7:0]" in c["detail"] and "[15:0]" in c["detail"]


@requires_git
@requires_verible
def test_port_added_and_port_removed(tmp_path):
    root = tmp_path / "proj"
    _init_repo(root)
    v1 = "module m (input logic clk, input logic rst_n); endmodule\n"
    (root / "u.sv").write_text(v1, encoding="utf-8")
    sha1 = _commit(root, "v1")
    v2 = "module m (input logic clk, output logic irq); endmodule\n"
    (root / "u.sv").write_text(v2, encoding="utf-8")
    sha2 = _commit(root, "v2 drop rst_n, add irq")

    result = ci.semantic_diff_rtl_file(root, sha1, sha2, "u.sv")
    assert result["status"] == "CHANGED"
    assert result["interface_impacting"] is True
    kinds = {c["kind"] for c in result["changes"]}
    assert ci.RTL_CHANGE_PORT_ADDED in kinds
    assert ci.RTL_CHANGE_PORT_REMOVED in kinds
    added = [c for c in result["changes"] if c["kind"] == ci.RTL_CHANGE_PORT_ADDED][0]
    removed = [c for c in result["changes"] if c["kind"] == ci.RTL_CHANGE_PORT_REMOVED][0]
    assert "irq" in added["detail"]
    assert "rst_n" in removed["detail"]


@requires_git
@requires_verible
def test_parameter_default_change_detected(tmp_path):
    root = tmp_path / "proj"
    _init_repo(root)
    v1 = "module m #(parameter WIDTH = 8) (input logic clk); endmodule\n"
    (root / "u.sv").write_text(v1, encoding="utf-8")
    sha1 = _commit(root, "v1")
    v2 = "module m #(parameter WIDTH = 32) (input logic clk); endmodule\n"
    (root / "u.sv").write_text(v2, encoding="utf-8")
    sha2 = _commit(root, "v2 widen default WIDTH")

    result = ci.semantic_diff_rtl_file(root, sha1, sha2, "u.sv")
    assert result["status"] == "CHANGED"
    assert result["interface_impacting"] is True
    kinds = {c["kind"] for c in result["changes"]}
    assert ci.RTL_CHANGE_PARAM_DEFAULT_CHANGED in kinds


@requires_git
@requires_verible
def test_internal_signal_change_is_not_interface_impacting(tmp_path):
    """An internal (non-port) module-level signal changing is a real,
    reported CHANGED finding -- but it must NOT be interface_impacting,
    because nothing outside the module can ever legally reference it."""
    root = tmp_path / "proj"
    _init_repo(root)
    v1 = "module m (input logic clk);\n  logic [7:0] scratch;\nendmodule\n"
    (root / "u.sv").write_text(v1, encoding="utf-8")
    sha1 = _commit(root, "v1")
    v2 = "module m (input logic clk);\n  logic [15:0] scratch;\nendmodule\n"
    (root / "u.sv").write_text(v2, encoding="utf-8")
    sha2 = _commit(root, "v2 widen internal scratch reg")

    result = ci.semantic_diff_rtl_file(root, sha1, sha2, "u.sv")
    assert result["status"] == "CHANGED"
    assert result["interface_impacting"] is False
    kinds = {c["kind"] for c in result["changes"]}
    assert kinds == {ci.RTL_CHANGE_SIGNAL_TYPE_CHANGED}


@requires_git
@requires_verible
def test_comment_only_change_reports_body_only_change(tmp_path):
    """The file's own bytes genuinely differ, but no module/port/parameter/
    signal declaration differs -- the honest BODY_ONLY_CHANGE bucket, never
    silently folded into "nothing changed" (that is reserved for byte-
    identical content) or "an interface changed" (it did not)."""
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "u.sv").write_text(MODULE_V1, encoding="utf-8")
    sha1 = _commit(root, "v1")
    v2 = MODULE_V1.replace("// straightforward status register",
                            "// straightforward status register (renamed comment)")
    (root / "u.sv").write_text(v2, encoding="utf-8")
    sha2 = _commit(root, "v2 comment tweak only")

    result = ci.semantic_diff_rtl_file(root, sha1, sha2, "u.sv")
    assert result["status"] == "BODY_ONLY_CHANGE"
    assert result["changes"] == []
    assert result["interface_impacting"] is False
    assert "procedural body" in result["detail"] or "comment" in result["detail"]


@requires_git
@requires_verible
def test_file_removed_reports_module_removed(tmp_path):
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "keep.sv").write_text("module keep; endmodule\n", encoding="utf-8")
    (root / "doomed.sv").write_text("module doomed; endmodule\n", encoding="utf-8")
    sha1 = _commit(root, "v1")
    (root / "doomed.sv").unlink()
    sha2 = _commit(root, "v2 delete doomed.sv")

    result = ci.semantic_diff_rtl_file(root, sha1, sha2, "doomed.sv")
    assert result["status"] == "FILE_REMOVED"
    assert result["interface_impacting"] is True
    kinds = {c["kind"] for c in result["changes"]}
    assert kinds == {ci.RTL_CHANGE_MODULE_REMOVED}


@requires_git
@requires_verible
def test_real_syntax_error_reports_not_available_never_a_guess(tmp_path):
    """A genuinely malformed .sv file at head: verible reports a real parse
    error, and this must surface as NOT_AVAILABLE (never a fabricated
    CHANGED/BODY_ONLY_CHANGE result) -- the same 'absence of proof is not
    proof of safety' rule this module states for itself."""
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "u.sv").write_text(MODULE_V1, encoding="utf-8")
    sha1 = _commit(root, "v1")
    (root / "u.sv").write_text(BROKEN_SV, encoding="utf-8")
    sha2 = _commit(root, "v2 introduce a real syntax error")

    result = ci.semantic_diff_rtl_file(root, sha1, sha2, "u.sv")
    assert result["status"] == "NOT_AVAILABLE"
    assert result["changes"] == []
    assert "PARSE_ERROR" in result["detail"]


@requires_git
@requires_verible
def test_compute_semantic_change_impact_aggregates_across_files(tmp_path):
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "iface.sv").write_text(MODULE_V1, encoding="utf-8")
    (root / "notes.md").write_text("# v1\n", encoding="utf-8")
    sha1 = _commit(root, "v1")
    (root / "iface.sv").write_text(
        MODULE_V1.replace("[7:0]  status", "[15:0] status"), encoding="utf-8")
    (root / "notes.md").write_text("# v2\n", encoding="utf-8")
    sha2 = _commit(root, "v2 widen status port + update notes")

    report = ci.compute_semantic_change_impact(root, base_sha=sha1, head_sha=sha2)
    assert report["status"] == "COMPUTED"
    assert report["interface_impacting_files"] == ["iface.sv"]
    assert report["non_rtl_files_skipped"] == ["notes.md"]
    assert report["body_only_files"] == []
    assert report["unverifiable_files"] == []
    assert len(report["per_file"]) == 1
    assert report["per_file"][0]["file"] == "iface.sv"


@requires_git
@requires_verible
def test_cli_semantic_diff_exit_code_and_json(tmp_path):
    """Drives the real python -m dv_harness.change_impact semantic-diff
    subprocess end to end -- a real interface-impacting change must exit 1
    and produce valid, matching JSON."""
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "u.sv").write_text(MODULE_V1, encoding="utf-8")
    sha1 = _commit(root, "v1")
    (root / "u.sv").write_text(
        MODULE_V1.replace("[7:0]  status", "[15:0] status"), encoding="utf-8")
    sha2 = _commit(root, "v2 widen status port")

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.change_impact", "semantic-diff",
         "--root", str(root), "--base", sha1, "--head", sha2, "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "COMPUTED"
    assert payload["interface_impacting_files"] == ["u.sv"]


@requires_git
@requires_verible
def test_cli_semantic_diff_no_interface_change_exits_zero(tmp_path):
    root = tmp_path / "proj"
    _init_repo(root)
    (root / "u.sv").write_text(MODULE_V1, encoding="utf-8")
    sha1 = _commit(root, "v1")
    v2 = MODULE_V1.replace("// straightforward status register",
                            "// straightforward status register (v2)")
    (root / "u.sv").write_text(v2, encoding="utf-8")
    sha2 = _commit(root, "v2 comment only")

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.change_impact", "semantic-diff",
         "--root", str(root), "--base", sha1, "--head", sha2, "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["interface_impacting_files"] == []
    assert payload["body_only_files"] == ["u.sv"]
