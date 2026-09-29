"""Tests for dv_harness/verification_boundary_ir.py.

Real construction of VerificationBoundaryIR/RoleAssignment objects and a real CLI subprocess
invocation -- no mocks, matching this project's existing house style for a self-contained
classification/IR module with no external evidence store to fake.
"""
import json
import subprocess
import sys

import pytest

from dv_harness.verification_boundary_ir import (
    BOUNDARY_CLASSES,
    CLASS_EXTERNAL_PROTOCOL,
    CLASS_REGISTER_CSR,
    CLASS_DMA,
    CLASS_INTERRUPT,
    ROLE_NAMES,
    ROLE_ACTIVE_DRIVER,
    ROLE_MONITOR,
    ROLE_PREDICTOR,
    ROLE_CHECKER,
    ROLE_SCOREBOARD,
    ROLE_COVERAGE_OWNER,
    ROLE_PERFORMANCE_OWNER,
    ROLE_ASSIGNED,
    ROLE_UNKNOWN,
    RoleAssignment,
    VerificationBoundaryIR,
    VerificationBoundaryIrError,
    build_role_assignment,
    build_verification_boundary_ir,
    build_verification_boundary_irs,
    execute_verb,
)


# ===========================================================================
# Vocabulary sanity
# ===========================================================================

def test_ten_fixed_boundary_classes():
    assert len(BOUNDARY_CLASSES) == 10
    assert len(set(BOUNDARY_CLASSES)) == 10


def test_seven_fixed_roles():
    assert len(ROLE_NAMES) == 7
    assert len(set(ROLE_NAMES)) == 7
    assert set(ROLE_NAMES) == {
        ROLE_ACTIVE_DRIVER, ROLE_MONITOR, ROLE_PREDICTOR, ROLE_CHECKER,
        ROLE_SCOREBOARD, ROLE_COVERAGE_OWNER, ROLE_PERFORMANCE_OWNER,
    }


# ===========================================================================
# build_role_assignment
# ===========================================================================

def test_role_assignment_with_owner_and_citation_is_assigned():
    ra = build_role_assignment(ROLE_ACTIVE_DRIVER, owner="usb_host_agent", evidence="spec.md#4.2")
    assert ra.status == ROLE_ASSIGNED
    assert ra.owner == "usb_host_agent"
    assert ra.evidence == "spec.md#4.2"


def test_role_with_no_owner_is_unknown_never_none_string():
    ra = build_role_assignment(ROLE_CHECKER)
    assert ra.status == ROLE_UNKNOWN
    assert ra.owner is None
    # Explicitly never the literal defaulted string "none".
    assert ra.owner != "none"


def test_role_with_blank_owner_is_unknown():
    ra = build_role_assignment(ROLE_MONITOR, owner="   ", evidence="rtl.sv:10")
    assert ra.status == ROLE_UNKNOWN
    assert ra.owner is None


def test_role_with_evidence_but_no_owner_is_still_unknown():
    # Evidence with nothing for it to support (no owner) is not an ownership assertion.
    ra = build_role_assignment(ROLE_SCOREBOARD, owner=None, evidence="rtl.sv:99")
    assert ra.status == ROLE_UNKNOWN


# ---- negative controls: the module refuses to fabricate a fact ----

def test_owner_with_no_evidence_is_refused():
    with pytest.raises(VerificationBoundaryIrError, match="no real evidence citation"):
        build_role_assignment(ROLE_PREDICTOR, owner="predictor_model_env", evidence=None)


def test_owner_with_blank_evidence_is_refused():
    with pytest.raises(VerificationBoundaryIrError, match="no real evidence citation"):
        build_role_assignment(ROLE_COVERAGE_OWNER, owner="cov_agent", evidence="   ")


def test_unrecognized_role_name_is_refused():
    with pytest.raises(VerificationBoundaryIrError, match="role must be one of"):
        build_role_assignment("data_owner", owner="x", evidence="y")


def test_non_string_owner_type_is_refused():
    with pytest.raises(VerificationBoundaryIrError, match="owner must be a str"):
        build_role_assignment(ROLE_PERFORMANCE_OWNER, owner=123, evidence="doc.md#3")


def test_non_string_evidence_type_is_refused():
    with pytest.raises(VerificationBoundaryIrError, match="evidence must be a str"):
        build_role_assignment(ROLE_PERFORMANCE_OWNER, owner="perf_mon", evidence=456)


# ===========================================================================
# build_verification_boundary_ir
# ===========================================================================

def _full_role_inputs(evidence_prefix: str = "rtl.sv") -> dict:
    return {
        ROLE_ACTIVE_DRIVER: {"owner": "usb_host_drv", "evidence": f"{evidence_prefix}:10"},
        ROLE_MONITOR: {"owner": "usb_mon", "evidence": f"{evidence_prefix}:20"},
        ROLE_PREDICTOR: {"owner": "usb_predictor", "evidence": f"{evidence_prefix}:30"},
        ROLE_CHECKER: {"owner": "usb_checker", "evidence": f"{evidence_prefix}:40"},
        ROLE_SCOREBOARD: {"owner": "usb_scb", "evidence": f"{evidence_prefix}:50"},
        ROLE_COVERAGE_OWNER: {"owner": "usb_cov", "evidence": f"{evidence_prefix}:60"},
        ROLE_PERFORMANCE_OWNER: {"owner": "usb_perf", "evidence": f"{evidence_prefix}:70"},
    }


def test_build_full_boundary_all_roles_assigned():
    ir = build_verification_boundary_ir(
        boundary_id="USB3_HOST_PORT0",
        boundary_class=CLASS_EXTERNAL_PROTOCOL,
        class_evidence="USB3.2 spec section 8.5",
        role_inputs=_full_role_inputs(),
    )
    assert ir.boundary_class == CLASS_EXTERNAL_PROTOCOL
    assert ir.all_roles_assigned()
    assert ir.unassigned_roles() == []
    for name in ROLE_NAMES:
        assert ir.roles[name].status == ROLE_ASSIGNED


def test_build_boundary_with_no_roles_declared_all_unknown():
    ir = build_verification_boundary_ir(
        boundary_id="DMA_CH0",
        boundary_class=CLASS_DMA,
        class_evidence="prog_guide.pdf p12 sec 3.1 DMA descriptor ring",
    )
    assert not ir.all_roles_assigned()
    assert set(ir.unassigned_roles()) == set(ROLE_NAMES)
    for name in ROLE_NAMES:
        assert ir.roles[name].owner is None
        assert ir.roles[name].status == ROLE_UNKNOWN


def test_build_boundary_partial_roles_some_assigned_some_unknown():
    ir = build_verification_boundary_ir(
        boundary_id="IRQ_CTRL0",
        boundary_class=CLASS_INTERRUPT,
        class_evidence="irq_ctrl.v:5 -- module irq_controller",
        role_inputs={
            ROLE_MONITOR: {"owner": "irq_mon", "evidence": "irq_ctrl.v:88"},
            ROLE_CHECKER: {"owner": "irq_checker", "evidence": "irq_ctrl.v:120"},
        },
    )
    assert ir.roles[ROLE_MONITOR].status == ROLE_ASSIGNED
    assert ir.roles[ROLE_CHECKER].status == ROLE_ASSIGNED
    assert ir.roles[ROLE_ACTIVE_DRIVER].status == ROLE_UNKNOWN
    assert ir.roles[ROLE_SCOREBOARD].status == ROLE_UNKNOWN
    assert set(ir.unassigned_roles()) == {
        ROLE_ACTIVE_DRIVER, ROLE_PREDICTOR, ROLE_SCOREBOARD,
        ROLE_COVERAGE_OWNER, ROLE_PERFORMANCE_OWNER,
    }


def test_ownership_never_guessed_from_boundary_class():
    # A DEBUG boundary is a plausible candidate for "no performance_owner needed", but this
    # module must never assume that -- it stays UNKNOWN purely because nothing cited it, not
    # because DEBUG boundaries are assumed to lack one.
    ir = build_verification_boundary_ir(
        boundary_id="JTAG_TAP0",
        boundary_class="DEBUG",
        class_evidence="jtag_tap.v:1 -- module jtag_tap",
    )
    assert ir.roles[ROLE_PERFORMANCE_OWNER].status == ROLE_UNKNOWN
    # And an ownership fact for that exact same role IS honored once cited, proving the UNKNOWN
    # above was an absence-of-evidence fact, not a class-derived rule.
    ir2 = build_verification_boundary_ir(
        boundary_id="JTAG_TAP0",
        boundary_class="DEBUG",
        class_evidence="jtag_tap.v:1 -- module jtag_tap",
        role_inputs={ROLE_PERFORMANCE_OWNER: {"owner": "jtag_perf_mon", "evidence": "jtag_tap.v:200"}},
    )
    assert ir2.roles[ROLE_PERFORMANCE_OWNER].status == ROLE_ASSIGNED


# ---- negative controls ----

def test_empty_boundary_id_refused():
    with pytest.raises(VerificationBoundaryIrError, match="boundary_id must be a non-empty str"):
        build_verification_boundary_ir(boundary_id="", boundary_class=CLASS_DMA, class_evidence="x")


def test_unrecognized_boundary_class_refused():
    with pytest.raises(VerificationBoundaryIrError, match="boundary_class must be one of"):
        build_verification_boundary_ir(boundary_id="B0", boundary_class="MADE_UP_CLASS", class_evidence="x")


def test_uncited_boundary_class_refused():
    with pytest.raises(VerificationBoundaryIrError, match="no real evidence citation"):
        build_verification_boundary_ir(boundary_id="B0", boundary_class=CLASS_REGISTER_CSR, class_evidence="")


def test_uncited_boundary_class_none_refused():
    with pytest.raises(VerificationBoundaryIrError, match="no real evidence citation"):
        build_verification_boundary_ir(boundary_id="B0", boundary_class=CLASS_REGISTER_CSR, class_evidence=None)


def test_unrecognized_role_key_in_role_inputs_refused():
    with pytest.raises(VerificationBoundaryIrError, match="unrecognized role"):
        build_verification_boundary_ir(
            boundary_id="B0",
            boundary_class="MEMORY_MAPPED",
            class_evidence="x",
            role_inputs={"data_owner": {"owner": "x", "evidence": "y"}},
        )


def test_uncited_role_owner_inside_boundary_build_refused():
    with pytest.raises(VerificationBoundaryIrError, match="no real evidence citation"):
        build_verification_boundary_ir(
            boundary_id="B0",
            boundary_class=CLASS_DMA,
            class_evidence="dma.v:1",
            role_inputs={ROLE_ACTIVE_DRIVER: {"owner": "dma_drv"}},
        )


def test_role_inputs_must_be_dict():
    with pytest.raises(VerificationBoundaryIrError, match="role_inputs must be a dict"):
        build_verification_boundary_ir(
            boundary_id="B0", boundary_class=CLASS_DMA, class_evidence="dma.v:1", role_inputs=["not", "a", "dict"],
        )


def test_role_inputs_entry_must_be_dict():
    with pytest.raises(VerificationBoundaryIrError, match="must be a dict"):
        build_verification_boundary_ir(
            boundary_id="B0",
            boundary_class=CLASS_DMA,
            class_evidence="dma.v:1",
            role_inputs={ROLE_ACTIVE_DRIVER: "not_a_dict"},
        )


# ===========================================================================
# build_verification_boundary_irs (list form)
# ===========================================================================

def test_build_list_of_boundaries():
    docs = [
        {
            "boundary_id": "B0",
            "boundary_class": "CLOCK_RESET",
            "class_evidence": "top.v:5 -- reset tree root",
            "roles": {ROLE_MONITOR: {"owner": "rst_mon", "evidence": "top.v:40"}},
        },
        {
            "boundary_id": "B1",
            "boundary_class": "COHERENT",
            "class_evidence": "ace_lite.pdf sec 2",
        },
    ]
    irs = build_verification_boundary_irs(docs)
    assert len(irs) == 2
    assert irs[0].boundary_id == "B0"
    assert irs[0].roles[ROLE_MONITOR].status == ROLE_ASSIGNED
    assert irs[1].boundary_id == "B1"
    assert irs[1].all_roles_assigned() is False


def test_build_list_rejects_non_list():
    with pytest.raises(VerificationBoundaryIrError, match="must be a list"):
        build_verification_boundary_irs({"not": "a list"})


def test_build_list_names_offending_index():
    docs = [
        {"boundary_id": "OK0", "boundary_class": "DMA", "class_evidence": "dma.v:1"},
        {"boundary_id": "BAD1", "boundary_class": "DMA", "class_evidence": ""},
    ]
    with pytest.raises(VerificationBoundaryIrError, match=r"boundaries\[1\]"):
        build_verification_boundary_irs(docs)


def test_build_list_rejects_non_dict_entry():
    with pytest.raises(VerificationBoundaryIrError, match=r"boundaries\[0\] must be a dict"):
        build_verification_boundary_irs(["not a dict"])


# ===========================================================================
# to_dict / round trip shape
# ===========================================================================

def test_to_dict_shape_and_json_serializable():
    ir = build_verification_boundary_ir(
        boundary_id="B0",
        boundary_class="DEBUG",
        class_evidence="debug_tap.v:1",
        role_inputs={ROLE_MONITOR: {"owner": "dbg_mon", "evidence": "debug_tap.v:5"}},
    )
    d = ir.to_dict()
    assert d["boundary_id"] == "B0"
    assert d["boundary_class"] == "DEBUG"
    assert set(d["roles"].keys()) == set(ROLE_NAMES)
    # Must be JSON-serializable end to end.
    text = json.dumps(d)
    reparsed = json.loads(text)
    assert reparsed["roles"][ROLE_MONITOR]["status"] == ROLE_ASSIGNED
    assert reparsed["roles"][ROLE_ACTIVE_DRIVER]["status"] == ROLE_UNKNOWN
    assert reparsed["roles"][ROLE_ACTIVE_DRIVER]["owner"] is None


# ===========================================================================
# CLI front door
# ===========================================================================

def test_execute_verb_classes():
    code, result, _text = execute_verb(["classes"])
    assert code == 0
    assert len(result["boundary_classes"]) == 10


def test_execute_verb_roles():
    code, result, _text = execute_verb(["roles"])
    assert code == 0
    assert len(result["role_names"]) == 7


def test_execute_verb_build_all_assigned_exit_zero(tmp_path):
    doc = [
        {
            "boundary_id": "B0",
            "boundary_class": "DMA",
            "class_evidence": "dma.v:1",
            "roles": _full_role_inputs(),
        }
    ]
    p = tmp_path / "boundaries.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    code, result, _text = execute_verb(["build", "--boundaries", str(p), "--json"])
    assert code == 0
    assert result["boundaries"][0]["boundary_class"] == "DMA"


def test_execute_verb_build_some_unassigned_exit_one(tmp_path):
    doc = [{"boundary_id": "B0", "boundary_class": "DMA", "class_evidence": "dma.v:1"}]
    p = tmp_path / "boundaries.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    code, _result, _text = execute_verb(["build", "--boundaries", str(p)])
    assert code == 1


def test_execute_verb_build_uncited_class_returns_error_exit_two(tmp_path):
    doc = [{"boundary_id": "B0", "boundary_class": "DMA", "class_evidence": ""}]
    p = tmp_path / "boundaries.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    code, result, _text = execute_verb(["build", "--boundaries", str(p)])
    assert code == 2
    assert "error" in result


def test_real_cli_subprocess_classes():
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.verification_boundary_ir", "classes"],
        capture_output=True, text=True, cwd="D:/DV/Task/DV_Agent_Harness_L5/v50",
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert len(payload["boundary_classes"]) == 10


def test_real_cli_subprocess_build(tmp_path):
    doc = [
        {
            "boundary_id": "B0",
            "boundary_class": "EXTERNAL_PROTOCOL",
            "class_evidence": "usb_spec.pdf sec 8",
            "roles": _full_role_inputs(),
        }
    ]
    p = tmp_path / "boundaries.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.verification_boundary_ir", "build", "--boundaries", str(p), "--json"],
        capture_output=True, text=True, cwd="D:/DV/Task/DV_Agent_Harness_L5/v50",
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["boundaries"][0]["boundary_id"] == "B0"
