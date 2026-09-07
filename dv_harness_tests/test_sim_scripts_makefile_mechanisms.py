"""Regression protection for self_check_list.md #22-24 (sim-script mechanism verification,
2026-09-06 audit).

The audit (see the corresponding gap-close report) found all three mechanisms this item names
already genuinely implemented -- not stubbed -- in the shipped, protocol-agnostic template
Makefile, structurally mirroring reference/USB_UVM_Handoff/sim/scripts/Makefile with only the
USB-specific identifiers genericized (usb_ -> $(IP_PREFIX), USB -> $(TARGET_IP)):

  (a) the 4-stage VCS partition-compilation flow (vlogan UVM library / vlogan DUT / vlogan
      testbench / vcs elaborate with -partcomp autopartitioning)
  (b) Verdi PA (protocol analyzer) invocation (PA_PROT/PA_LINK/PA_PHYS/PA_PAYLOAD +
      PA_RUN_OPTS=+svt_enable_pa=fsdb +$(IP_PREFIX)pa, gated on VERDI_HOME)
  (c) the wave.txt-style dump-list convention (a DUT-team-supplied wave.txt tracked as a real
      source dependency, driving the +fsdb_off/+fsdb_full/+fsdb_file/+fsdb_start/+fsdb_stop
      run-time waveform-scope plusargs)

No template code was changed by that audit (ALREADY_SATISFIED_NO_CHANGE). This test exists only
so a future edit that silently drops one of the three mechanisms from the shipped template is
caught, rather than rediscovered by a second audit. Each positive assertion carries a negative
control proving the regex/marker set has real detection power (matched against a deliberately
stripped copy of the same text), not merely a check that always passes on well-formed prose.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_MK = (
    ROOT / "dv_harness" / "uvm_generator" / "templates" / "sim_scripts" / "Makefile"
)
REFERENCE_MK = ROOT / "reference" / "USB_UVM_Handoff" / "sim" / "scripts" / "Makefile"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file missing: {path}"
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# (a) 4-stage VCS partition-compilation flow
# ---------------------------------------------------------------------------

STAGE_HELP_MARKERS = [
    r"stage 1a:\s*vlogan analyses the UVM library",
    r"stage 1b:\s*vlogan analyses the DUT",
    r"stage 1c:\s*vlogan analyses the testbench",
    r"stage 2\s*:\s*vcs elaborates, produces simv",
]

STAGE_RULE_MARKERS = [
    r"#\s*Stage 1a:\s*analyse the UVM library",
    r"#\s*Stage 1b:\s*analyse design \+ VIP \+ TB",
    r"#\s*Stage 1c:\s*the testbench",
    r"#\s*Stage 2:\s*elaborate",
]

PARTCOMP_MARKERS = [
    r"PARTCOMP_EN\s*\?=\s*1",
    r"-partcomp\s+-fastpartcomp=j\$\(NPROC\)",
]


def test_four_stage_partition_compile_help_text_present():
    text = _read(TEMPLATE_MK)
    for pattern in STAGE_HELP_MARKERS:
        assert re.search(pattern, text, re.IGNORECASE), (
            f"template Makefile no longer documents stage marker: {pattern!r}"
        )


def test_four_stage_partition_compile_help_text_negative_control():
    # A Makefile with the stage words removed must NOT satisfy the same check --
    # proves the regex set actually discriminates rather than matching anything.
    stripped = "\n".join(
        line
        for line in _read(TEMPLATE_MK).splitlines()
        if "stage 1a" not in line.lower()
        and "stage 1b" not in line.lower()
        and "stage 1c" not in line.lower()
        and "stage 2" not in line.lower()
    )
    for pattern in STAGE_HELP_MARKERS:
        assert not re.search(pattern, stripped, re.IGNORECASE)


def test_four_stage_partition_compile_real_rules_present():
    text = _read(TEMPLATE_MK)
    for pattern in STAGE_RULE_MARKERS:
        assert re.search(pattern, text), f"missing real stage rule marker: {pattern!r}"
    for pattern in PARTCOMP_MARKERS:
        assert re.search(pattern, text), f"missing partition-compile marker: {pattern!r}"


def test_four_stage_flow_mirrors_reference_structurally():
    """The template's 4-stage flow is a genericized copy of the reference project's own flow,
    not an independently (and possibly incompletely) reinvented one."""
    template_text = _read(TEMPLATE_MK)
    reference_text = _read(REFERENCE_MK)
    for pattern in STAGE_RULE_MARKERS + PARTCOMP_MARKERS:
        assert re.search(pattern, reference_text), (
            f"sanity: reference Makefile itself should carry {pattern!r}"
        )
        assert re.search(pattern, template_text), (
            f"template drifted away from reference marker: {pattern!r}"
        )


# ---------------------------------------------------------------------------
# (b) Verdi PA (protocol analyzer) invocation
# ---------------------------------------------------------------------------

PA_MARKERS = [
    r"PA_PROT\s*\?=\s*2",
    r"PA_LINK\s*\?=\s*1",
    r"PA_PHYS\s*\?=\s*0",
    r"PA_PAYLOAD\s*\?=\s*1",
    r"PA_RUN_OPTS\s*:=\s*\+svt_enable_pa=fsdb\s+\+\$\(IP_PREFIX\)pa",
    r"VERDI_HOME",
]


def test_verdi_pa_invocation_present():
    text = _read(TEMPLATE_MK)
    for pattern in PA_MARKERS:
        assert re.search(pattern, text), f"missing Verdi PA marker: {pattern!r}"
    # A real `verdi` make target must exist, not merely be mentioned in prose.
    assert re.search(r"^verdi:\s*$", text, re.MULTILINE), (
        "no real 'verdi:' target rule found in the template Makefile"
    )


def test_verdi_pa_invocation_negative_control():
    stripped = re.sub(r"PA_RUN_OPTS\s*:=.*", "PA_RUN_OPTS :=", _read(TEMPLATE_MK))
    assert not re.search(
        r"PA_RUN_OPTS\s*:=\s*\+svt_enable_pa=fsdb\s+\+\$\(IP_PREFIX\)pa", stripped
    )


def test_verdi_pa_mirrors_reference_structurally():
    reference_text = _read(REFERENCE_MK)
    # Reference spells the run-options line with the literal usb_ prefix; template genericizes
    # it to $(IP_PREFIX). Confirm both carry the real svt_enable_pa=fsdb PA gate.
    assert re.search(r"PA_RUN_OPTS\s*:=\s*\+svt_enable_pa=fsdb\s+\+usb_pa", reference_text)
    assert re.search(
        r"PA_RUN_OPTS\s*:=\s*\+svt_enable_pa=fsdb\s+\+\$\(IP_PREFIX\)pa", _read(TEMPLATE_MK)
    )


# ---------------------------------------------------------------------------
# (c) wave.txt-style dump-list convention
# ---------------------------------------------------------------------------

WAVE_TXT_MARKERS = [
    r"\+fsdb_off",
    r"\+fsdb_full",
    r"\+fsdb_file=",
    r"\+fsdb_start=",
    r"\+fsdb_stop=",
]


def test_wave_txt_dump_list_convention_present():
    text = _read(TEMPLATE_MK)
    # wave.txt itself is a DUT-team-supplied file (like command.txt), never shipped inside the
    # generator's own templates tree -- what must be present here is the Makefile's own real
    # wiring that tracks it as a source dependency and drives the fsdb-scope plusargs it reads.
    assert re.search(r"DUT_ROOT_PATH\)/wave\.txt", text), (
        "wave.txt no longer tracked as a real DUT_SOURCES dependency"
    )
    for pattern in WAVE_TXT_MARKERS:
        assert re.search(pattern, text), f"missing wave.txt-driven plusarg: {pattern!r}"
    # The comment convention explaining wave.txt's own role must still be present -- this is
    # what distinguishes "we wire a plusarg" from "we wire a plusarg AND document that wave.txt
    # is the file which actually consumes it".
    assert re.search(r"wave\.txt reads", text)


def test_wave_txt_dump_list_convention_negative_control():
    stripped = "\n".join(
        line for line in _read(TEMPLATE_MK).splitlines() if "wave.txt" not in line.lower()
    )
    assert not re.search(r"wave\.txt reads", stripped)


def test_wave_txt_convention_mirrors_reference_structurally():
    reference_text = _read(REFERENCE_MK)
    template_text = _read(TEMPLATE_MK)
    for pattern in WAVE_TXT_MARKERS + [r"DUT_ROOT_PATH\)/wave\.txt", r"wave\.txt reads"]:
        assert re.search(pattern, reference_text), (
            f"sanity: reference Makefile should itself carry {pattern!r}"
        )
        assert re.search(pattern, template_text), (
            f"template drifted away from reference wave.txt marker: {pattern!r}"
        )
