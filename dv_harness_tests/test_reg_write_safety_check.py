"""Tests for dv_harness/uvm_generator/templates/sim_scripts/check/reg_write_safety.py
(gap-close-register-write-safety, 2026-09-03).

Confirmed finding this closes: a blind literal register write
(`\\`CPUWRITE4B(\\`TCA_CTRLSYNCMODE(0), 32'h00000400)\\`` instead of read-modify-
write) silently clobbered 4 unexamined bits at their non-zero reset defaults
in the live usb31_dev_uvm build, and produced a WRONG "fix is ineffective"
root-cause conclusion because "the write landed but the symptom didn't
change" is not sound evidence when other live bits were corrupted by the
same write. See .work/gap-close-register-write-safety-report.md.

This is a real subprocess run of the actual template script (mirrors
test_makefile_patterns_stub_targets.py's established style: exercise the
real generic tool, not a reimplementation of its logic in the test), against
small synthetic fixtures written here -- never real project content.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "dv_harness" / "uvm_generator" / "templates" / "sim_scripts"
          / "check" / "reg_write_safety.py")

REGMAP = {
    "FAKE_SCALEMODE": {
        "width": 32,
        "reset": "0x00000045",
        "fields": [
            {"name": "EN", "hi": 0, "lo": 0},
            {"name": "POL", "hi": 2, "lo": 2},
            {"name": "SCALEEN", "hi": 4, "lo": 4},
            {"name": "GATE", "hi": 6, "lo": 6},
        ],
    },
    # The real historical register: reset default has 4 fields non-zero
    # (EN/POL/MODE/SEL) that the intended fix (set SYNCEN, bit 10) never
    # touches; a straight literal write zeroes all 4 of them.
    "TCA_CTRLSYNCMODE": {
        "width": 32,
        "reset": "0x00100111",
        "fields": [
            {"name": "EN", "hi": 0, "lo": 0},
            {"name": "POL", "hi": 4, "lo": 4},
            {"name": "MODE", "hi": 8, "lo": 8},
            {"name": "SYNCEN", "hi": 10, "lo": 10},
            {"name": "SEL", "hi": 20, "lo": 20},
        ],
    },
}


def _build_fixture(tmp_path: Path) -> Path:
    tb = tmp_path / "tb"
    tb.mkdir()
    (tb / "good_rmw.svh").write_text(
        "// real read-modify-write pattern -- must NOT be flagged\n"
        "task automatic set_syncmode_bit(int port);\n"
        "    logic [31:0] reg_val;\n"
        "    reg_val = `CPUREAD4B(`TCA_CTRLSYNCMODE(port));\n"
        "    reg_val = reg_val | 32'h00000400;\n"
        "    `CPUWRITE4B(`TCA_CTRLSYNCMODE(port), reg_val);\n"
        "endtask\n",
        encoding="utf-8",
    )
    (tb / "bad_blind_write.svh").write_text(
        "// blind literal write to a multi-field register -- SHOULD be flagged\n"
        "task automatic set_scalemode(int port);\n"
        "    `CPUWRITE4B(`FAKE_SCALEMODE(port), 32'h00000010);\n"
        "endtask\n",
        encoding="utf-8",
    )
    (tb / "historical_bug.svh").write_text(
        "// replicates the REAL historical bug: TCA_CTRLSYNCMODE written as a\n"
        "// bare literal instead of RMW. reset default is non-zero on 4 fields.\n"
        "// TCA_CTRLSYNCMODE reset default = 32'h00100111\n"
        "task automatic tca_enable_syncmode(int port);\n"
        "    `CPUWRITE4B(`TCA_CTRLSYNCMODE(port), 32'h00000400);\n"
        "endtask\n",
        encoding="utf-8",
    )
    regmap = tmp_path / "regmap.json"
    regmap.write_text(json.dumps(REGMAP), encoding="utf-8")
    return tmp_path


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False,
    )


class TestNoRegTable:
    """No table supplied: never silently passes -- both blind writes come
    back as WARN with the exact 'verify manually' phrasing, and the real
    RMW pattern is not mentioned at all."""

    def test_blind_writes_flagged_verify_manually(self, tmp_path):
        fixture = _build_fixture(tmp_path)
        result = _run(str(fixture))
        assert "bad_blind_write.svh" in result.stdout
        assert "historical_bug.svh" in result.stdout
        assert "verify manually" in result.stdout
        assert result.stdout.count("verify manually") == 2

    def test_real_rmw_not_mentioned(self, tmp_path):
        fixture = _build_fixture(tmp_path)
        result = _run(str(fixture))
        assert "good_rmw.svh" not in result.stdout

    def test_exit_code_is_zero_when_only_warn(self, tmp_path):
        # No table -> no ERROR-severity finding is possible, only WARN.
        fixture = _build_fixture(tmp_path)
        result = _run(str(fixture))
        assert result.returncode == 0


class TestWithRegTable:
    """A register/bit-field table is supplied: real clobbers against a
    non-zero reset default sharpen into a named ERROR, and the process exits
    non-zero -- this is the CI-blocking case."""

    def test_synthetic_multi_field_register_flagged_as_error(self, tmp_path):
        fixture = _build_fixture(tmp_path)
        result = _run(str(fixture), "--reg-table", str(fixture / "regmap.json"))
        assert "[ERROR]" in result.stdout
        assert "bad_blind_write.svh" in result.stdout
        assert "FAKE_SCALEMODE" in result.stdout
        # EN and POL and GATE (bits 0, 2, 6) sit at reset=1 and are not part
        # of the literal (bit 4 only) -- all three must be named as clobbered.
        assert "EN: reset=0x1 -> 0x0" in result.stdout
        assert "POL: reset=0x1 -> 0x0" in result.stdout
        assert "GATE: reset=0x1 -> 0x0" in result.stdout

    def test_historical_bug_shape_is_caught(self, tmp_path):
        """This is the 'would it have caught the real bug' proof: the exact
        historical shape (CPUWRITE4B of a bare 32'h00000400 literal to a
        register whose reset default has other non-zero fields) must come
        back as ERROR, naming the 4 clobbered fields (EN, POL, MODE, SEL) --
        matching "4 unexamined bits...at their non-zero reset defaults" from
        the real incident."""
        fixture = _build_fixture(tmp_path)
        result = _run(str(fixture), "--reg-table", str(fixture / "regmap.json"))
        assert result.returncode == 1
        assert "[ERROR]" in result.stdout
        assert "historical_bug.svh" in result.stdout
        assert "TCA_CTRLSYNCMODE" in result.stdout
        assert "clobbers 4 field(s)" in result.stdout
        for field in ("EN", "POL", "MODE", "SEL"):
            assert ("%s: reset=" % field) in result.stdout
        # SYNCEN is the field the write actually targets (reset=0 there) --
        # it must NOT be reported as clobbered.
        assert "SYNCEN: reset=" not in result.stdout

    def test_real_rmw_pattern_never_flagged(self, tmp_path):
        """The core distinction this checker exists to make: a genuine
        read-modify-write (CPUREAD into a variable, OR'd with a literal,
        written back as that variable) must never appear in the output at
        all, table or no table."""
        fixture = _build_fixture(tmp_path)
        result = _run(str(fixture), "--reg-table", str(fixture / "regmap.json"))
        assert "good_rmw.svh" not in result.stdout

    def test_exit_code_nonzero_signals_ci_blocking(self, tmp_path):
        fixture = _build_fixture(tmp_path)
        result = _run(str(fixture), "--reg-table", str(fixture / "regmap.json"))
        assert result.returncode == 1


class TestGenericMacroNamePattern:
    """The macro-name match is a generic '...WRITE<digits>B' regex, not a
    hardcoded USB macro list -- a differently-prefixed write macro (as a
    non-USB protocol would use) must still be caught."""

    def test_non_usb_style_macro_name_is_still_caught(self, tmp_path):
        tb = tmp_path / "tb"
        tb.mkdir()
        (tb / "pcie_init.svh").write_text(
            "task automatic pcie_set_ltssm(int lane);\n"
            "    `HOSTWRITE4B(`PCIE_LTSSMCTRL(lane), 32'h00000004);\n"
            "endtask\n",
            encoding="utf-8",
        )
        result = _run(str(tmp_path))
        assert "pcie_init.svh" in result.stdout
        assert "HOSTWRITE4B" in result.stdout

    def test_no_help_argv_prints_docstring_and_exits_2(self, tmp_path):
        result = _run()
        assert result.returncode == 2
        assert "reg_write_safety.py" in result.stderr or "WHY THIS EXISTS" in result.stderr
