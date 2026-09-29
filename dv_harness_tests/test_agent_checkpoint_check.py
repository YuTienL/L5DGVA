"""Tests for dv_harness/agent_checkpoint_check.py -- the verification
checker backing CORE/agent-checkpoint-discipline/SKILL.md (Gap #4 closure,
2026-09-03: a long-running build/investigation agent's own resume-state
artifact, distinct from dv_harness/session_snapshot.py's engine-level
CURRENT-RUN state).

Covers, with synthetic fixtures under pytest's tmp_path (never touching any
real project tree):
  - no artifact present at all,
  - a complete single-file RESUME.md,
  - an incomplete single-file artifact (missing citations + decisions-
    pending + files-touched sections),
  - the real dual-file layout (CLAUDE.md trap catalogue + docs/dut-
    request.md), synthesized to mirror usb31_dev_uvm's own real shape,
  - a stale artifact (older than other recently-touched files in the tree).

Plus one READ-ONLY check against the real usb31_dev_uvm tree (per the
workflow's explicit "do not write to that tree" constraint) confirming the
checker recognizes its real, already-existing CLAUDE.md + docs/dut-
request.md as a schema-complete dual-file resume-state artifact -- this is
the concrete "distinguishes a tree with one from a tree without one" proof
against a real, not synthetic, positive case.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from dv_harness.agent_checkpoint_check import (
    check_resume_state_artifact,
    locate_resume_state_artifact,
    check_schema_sections,
)


GOOD_SINGLE_FILE = """\
# RESUME

## Current status
OPEN: investigating the TCA NC->USB hang.

## Evidence gathered so far
- soc_int.svh:108 waits for the register-access bridges to be ready
- MODEL_ALL.v:1756 ifndef DV_UVM force of the SoC APB master
- SS_VOUT_USB_PHY.v:59861 tca_apb_pready tied to 1'b1

## Next planned step
To close: read TCA_INFO (0x1272_00FC) and confirm the APB path is alive.

## Decisions pending user/coordinator confirmation
Owner: DV owner + RTL owner jointly -- ask the user whether disabling the
PHY sub-block is safe before doing it.

## Files touched this session
grep -rn "DV_UVM HOOK" lists the two hook edits applied this session.
"""

INCOMPLETE_SINGLE_FILE = """\
# RESUME

## Current status
OPEN: still looking into the hang.

## Next planned step
Keep reading the RTL.
"""

DUAL_CLAUDE_MD = """\
# Target settings, coordinates, traps

## Trap catalogue

### T-1 -- register bridge readiness
`common/soc_int.svh:108-109` waits for the register-access bridges.

### T-28 -- a completed APB write is not evidence the register took
`tca_apb_pready` is tied to `1'b1` inside `tca_reg`
(`DUT/RTLCAT/SS_VOUT_USB_PHY.v:59861`). `TCA_INFO` at `0x1272_00FC` is the
antidote (`:61060`).
"""

DUAL_DUT_REQUEST_MD = """\
# Open items

## Blocking-verification

### DUT-011 -- the TCA never acknowledges the NC->USB switch

Status: OPEN. Hangs after writing TCA_TCPC = 0x11.

To close: confirm tca_clk is running; check the pending PoR request.

Owner: DV owner, with RTL owner if TCA_INFO reads wrong.

Files touched this session: uvm/tb/top/usb_dev_init.svh:44 (added TCA_INFO
dump on timeout).
"""


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Layout / presence
# ---------------------------------------------------------------------------

def test_empty_tree_has_no_artifact(tmp_path):
    result = check_resume_state_artifact(str(tmp_path))
    assert result.ok is False
    assert result.reason == "NO_RESUME_ARTIFACT_FOUND"
    layout, paths = locate_resume_state_artifact(tmp_path)
    assert layout is None
    assert paths == []


def test_nonexistent_build_tree_path():
    result = check_resume_state_artifact(str(Path("Z:/does/not/exist/at/all")))
    assert result.ok is False
    assert result.reason == "BUILD_TREE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Single-file layout
# ---------------------------------------------------------------------------

def test_single_file_complete_artifact_passes(tmp_path):
    _write(tmp_path / "RESUME.md", GOOD_SINGLE_FILE)
    result = check_resume_state_artifact(str(tmp_path))
    assert result.ok is True
    assert result.reason == "RESUME_ARTIFACT_CURRENT"
    assert result.detail["layout"] == "single"
    assert result.detail["missing_sections"] == []
    assert result.detail["citation_count"] >= 3


def test_single_file_missing_sections_is_incomplete(tmp_path):
    _write(tmp_path / "RESUME.md", INCOMPLETE_SINGLE_FILE)
    result = check_resume_state_artifact(str(tmp_path))
    assert result.ok is False
    assert result.reason == "RESUME_ARTIFACT_INCOMPLETE"
    missing = set(result.detail["missing_sections"])
    assert "evidence_gathered_with_citations" in missing
    assert "decisions_pending_confirmation" in missing
    assert "files_touched_this_session" in missing
    # It DID state a status and a next step -- those must not be flagged.
    assert "current_hypothesis_status" not in missing
    assert "next_planned_step" not in missing


def test_single_file_resolved_from_docs_subdir(tmp_path):
    _write(tmp_path / "docs" / "STATUS.md", GOOD_SINGLE_FILE)
    layout, paths = locate_resume_state_artifact(tmp_path)
    assert layout == "single"
    assert paths[0].name == "STATUS.md"


# ---------------------------------------------------------------------------
# Dual-file layout (the real usb31_dev_uvm-shaped convention)
# ---------------------------------------------------------------------------

def test_dual_file_complete_artifact_passes(tmp_path):
    _write(tmp_path / "CLAUDE.md", DUAL_CLAUDE_MD)
    _write(tmp_path / "docs" / "dut-request.md", DUAL_DUT_REQUEST_MD)
    result = check_resume_state_artifact(str(tmp_path))
    assert result.ok is True
    assert result.reason == "RESUME_ARTIFACT_CURRENT"
    assert result.detail["layout"] == "dual"
    assert result.detail["missing_sections"] == []
    assert len(result.detail["artifact_paths"]) == 2


def test_dual_file_requires_both_halves(tmp_path):
    # CLAUDE.md alone (no open-items file) must not be mistaken for a
    # complete dual-file artifact -- and must not be mistaken for a
    # single-file artifact either, since it is not named RESUME.md/STATUS.md.
    _write(tmp_path / "CLAUDE.md", DUAL_CLAUDE_MD)
    result = check_resume_state_artifact(str(tmp_path))
    assert result.ok is False
    assert result.reason == "NO_RESUME_ARTIFACT_FOUND"


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------

def test_stale_artifact_is_flagged(tmp_path):
    resume = tmp_path / "RESUME.md"
    _write(resume, GOOD_SINGLE_FILE)
    now = time.time()
    old = now - 20 * 3600  # 20 hours old
    os.utime(resume, (old, old))

    # A different file in the tree was touched much more recently -- the
    # signature of an agent that kept working without updating its
    # checkpoint.
    other = tmp_path / "uvm" / "tb" / "usb_dev_init.svh"
    _write(other, "// edited this session\n")
    os.utime(other, (now, now))

    result = check_resume_state_artifact(str(tmp_path), stale_threshold_seconds=6 * 3600)
    assert result.ok is False
    assert result.reason == "RESUME_ARTIFACT_STALE"
    assert result.detail["staleness_gap_seconds"] > 6 * 3600


def test_fresh_artifact_is_not_flagged_stale(tmp_path):
    resume = tmp_path / "RESUME.md"
    _write(resume, GOOD_SINGLE_FILE)
    now = time.time()
    os.utime(resume, (now, now))

    other = tmp_path / "uvm" / "tb" / "usb_dev_init.svh"
    _write(other, "// edited earlier\n")
    os.utime(other, (now - 3600, now - 3600))  # older than the artifact

    result = check_resume_state_artifact(str(tmp_path), stale_threshold_seconds=6 * 3600)
    assert result.ok is True
    assert result.reason == "RESUME_ARTIFACT_CURRENT"


def test_vendor_dirs_excluded_from_staleness_scan(tmp_path):
    # DUT/ and VIP/ are the same two directories IP_UVM_DV_Gen.md's own
    # Step 2 already treats as read-only vendor source -- a file "recently
    # touched" there must never be able to make an otherwise-current
    # checkpoint report as stale.
    resume = tmp_path / "RESUME.md"
    _write(resume, GOOD_SINGLE_FILE)
    now = time.time()
    os.utime(resume, (now - 3600, now - 3600))

    vendor_file = tmp_path / "DUT" / "RTLCAT" / "some_rtl.v"
    _write(vendor_file, "// vendor delivered file\n")
    os.utime(vendor_file, (now, now))  # newer than the artifact

    result = check_resume_state_artifact(str(tmp_path), stale_threshold_seconds=60)
    assert result.ok is True
    assert result.reason == "RESUME_ARTIFACT_CURRENT"
    assert result.detail["newest_other_file_mtime"] is None


# ---------------------------------------------------------------------------
# check_schema_sections unit-level behavior
# ---------------------------------------------------------------------------

def test_check_schema_sections_reports_citation_count():
    out = check_schema_sections([GOOD_SINGLE_FILE])
    assert out["missing_sections"] == []
    assert out["citation_count"] >= 3


def test_check_schema_sections_empty_text_missing_everything():
    out = check_schema_sections([""])
    assert set(out["missing_sections"]) == {
        "evidence_gathered_with_citations",
        "current_hypothesis_status",
        "next_planned_step",
        "decisions_pending_confirmation",
        "files_touched_this_session",
    }


# ---------------------------------------------------------------------------
# Real, read-only check against usb31_dev_uvm (positive case with a REAL
# tree, not a synthetic one) -- confirms the checker recognizes the actual
# artifact that saved the real session, and never writes to that tree.
# ---------------------------------------------------------------------------

USB31_TREE = Path(r"D:\DV\Task\USB\usb31_dev_uvm")


@pytest.mark.skipif(not USB31_TREE.is_dir(), reason="usb31_dev_uvm tree not present on this host")
def test_real_usb31_dev_uvm_tree_has_dual_file_resume_artifact():
    claude_md = USB31_TREE / "CLAUDE.md"
    dut_request = USB31_TREE / "uvm" / "docs" / "dut-request.md"
    mtime_before_claude = claude_md.stat().st_mtime
    mtime_before_dut_request = dut_request.stat().st_mtime

    result = check_resume_state_artifact(str(USB31_TREE))

    # Read-only: neither real file's mtime may have changed.
    assert claude_md.stat().st_mtime == mtime_before_claude
    assert dut_request.stat().st_mtime == mtime_before_dut_request

    assert result.detail["layout"] == "dual"
    assert result.detail["missing_sections"] == []
    # Schema-complete either way; staleness depends on whatever the
    # concurrently-running investigation agent touched most recently in
    # this tree, which this test does not control -- only NOT_FOUND /
    # INCOMPLETE would indicate a real checker defect here.
    assert result.reason in ("RESUME_ARTIFACT_CURRENT", "RESUME_ARTIFACT_STALE")
