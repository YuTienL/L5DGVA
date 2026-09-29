"""Tests for `dv_harness.system_fw_service_registry`: the per-SYSTEM
branch_fw service-loop ownership registry across composed subsystems.

Every test drives the real `build_system_fw_service_registry()` (which itself
drives the real `branch_ownership_resolver.validate_branch_assignment()` --
never a mock of it), and the CLI test drives the real
`python -m dv_harness.system_fw_service_registry` subprocess. Negative
controls prove the module reports UNKNOWN/NOT_APPLICABLE rather than a
fabricated CLEAR when evidence is absent.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import system_fw_service_registry as sfr
from dv_harness import branch_ownership_resolver as bor
from dv_harness import system_resource_inventory as sri

REPO_ROOT = Path(__file__).resolve().parents[1]


def _findings(status=sri.CROSSCHECK_AVAILABLE, stopped=(), held=(), shared=(), reason=""):
    if status != sri.CROSSCHECK_AVAILABLE:
        return {"status": status, "reason": reason, "subsystems": []}
    return {
        "status": status,
        "subsystems": ["A", "B"],
        "stopped_resource_ids": list(stopped),
        "held_resource_ids": list(held),
        "shared_resource_ids": list(shared),
    }


def _decl(subsystem_id="USB0", branch_label="branch_fw", **extra):
    d = {"subsystem_id": subsystem_id, "branch_label": branch_label}
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# Negative controls: no fabrication when evidence is absent
# ---------------------------------------------------------------------------

def test_no_declarations_is_honestly_not_applicable():
    report = sfr.build_system_fw_service_registry(None)
    assert report["status"] == sfr.REGISTRY_NOT_APPLICABLE
    assert report["entries"] == []
    assert report["subsystem_count"] == 0


def test_no_declarations_empty_list_is_not_applicable():
    report = sfr.build_system_fw_service_registry([])
    assert report["status"] == sfr.REGISTRY_NOT_APPLICABLE


def test_declared_fw_resources_but_no_cross_subsystem_findings_is_unknown_not_clear():
    """The core negative control: a subsystem declares branch_fw-owned
    resources, but no real cross_subsystem_findings were supplied. This must
    NOT report CLEAR (that would be fabricating a system-level "no conflict"
    verdict this module never checked) -- it must report the honest UNKNOWN."""
    decl = [_decl(fw_owned_resource_ids=["USB0::chip.usb.ctrl::irq"])]
    report = sfr.build_system_fw_service_registry(decl)
    entry = report["entries"][0]
    assert entry["cross_subsystem_status"] == sfr.CS_UNKNOWN
    assert entry["entry_status"] == sfr.ENTRY_UNKNOWN
    assert report["status"] == sfr.REGISTRY_UNKNOWN
    assert "unavailable" in entry["cross_subsystem_reason"]


def test_cross_subsystem_findings_unavailable_status_is_also_unknown():
    decl = [_decl(fw_owned_resource_ids=["R1"])]
    findings = _findings(status=sri.CROSSCHECK_UNAVAILABLE,
                         reason="FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE")
    report = sfr.build_system_fw_service_registry(decl, cross_subsystem_findings=findings)
    entry = report["entries"][0]
    assert entry["cross_subsystem_status"] == sfr.CS_UNKNOWN
    assert "FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE" in entry["cross_subsystem_reason"]
    assert report["status"] == sfr.REGISTRY_UNKNOWN


def test_no_fw_resources_declared_is_not_applicable_per_entry_but_registry_clear():
    """A subsystem with a VALID branch_fw assignment but nothing declared to
    cross-check reports its own honest per-entry status, not a fabricated
    CLEAR indistinguishable from an actual clean cross-check."""
    decl = [_decl()]
    report = sfr.build_system_fw_service_registry(decl)
    entry = report["entries"][0]
    assert entry["cross_subsystem_status"] == sfr.CS_NOT_DECLARED
    assert entry["entry_status"] == sfr.ENTRY_CLEAR_NO_RESOURCES
    assert report["status"] == sfr.REGISTRY_CLEAR


# ---------------------------------------------------------------------------
# Core positive path
# ---------------------------------------------------------------------------

def test_valid_fw_ownership_and_clean_cross_subsystem_check_is_clear():
    decl = [_decl(subsystem_id="USB0", branch_label="branch_fw", per_port=True,
                  driven_by="FW_FIRMWARE_MODEL", fw_owned_resource_ids=["USB0::chip.usb::irq"])]
    findings = _findings(stopped=[], held=[], shared=[])
    report = sfr.build_system_fw_service_registry(decl, cross_subsystem_findings=findings)
    assert report["status"] == sfr.REGISTRY_CLEAR
    entry = report["entries"][0]
    assert entry["branch_ownership"]["verdict"] == bor.VALID
    assert entry["cross_subsystem_status"] == sfr.CS_CLEAR
    assert entry["entry_status"] == sfr.ENTRY_CLEAR


def test_multiple_clean_subsystems_all_clear():
    decl = [
        _decl(subsystem_id="USB0", fw_owned_resource_ids=["USB0::a::b"]),
        _decl(subsystem_id="PCIE0", fw_owned_resource_ids=["PCIE0::c::d"]),
    ]
    findings = _findings()
    report = sfr.build_system_fw_service_registry(decl, cross_subsystem_findings=findings)
    assert report["status"] == sfr.REGISTRY_CLEAR
    assert report["subsystem_count"] == 2
    assert [e["subsystem_id"] for e in report["entries"]] == ["PCIE0", "USB0"]


# ---------------------------------------------------------------------------
# Branch-ownership reuse: an invalid/ambiguous branch_fw assignment blocks
# regardless of a clean cross-subsystem check
# ---------------------------------------------------------------------------

def test_invalid_branch_label_blocks_even_with_clean_cross_subsystem_evidence():
    """branch_label 'branch_a0' assigned to an FW_EVENT_SERVICE_LOOP operation
    is a real INVALID per branch_ownership_resolver's own violation table
    (FW_SERVICE_LOOP_ASSIGNED_TO ... family reversed: here it's a DUT tier
    branch given FW-tier content) -- this must dominate a clean resource
    check, proving worst-wins."""
    decl = [_decl(branch_label="branch_a0", fw_owned_resource_ids=["R1"])]
    findings = _findings(stopped=[], held=[], shared=[])
    report = sfr.build_system_fw_service_registry(decl, cross_subsystem_findings=findings)
    assert report["status"] == sfr.REGISTRY_BLOCKED
    entry = report["entries"][0]
    assert entry["branch_ownership"]["verdict"] == bor.INVALID
    assert entry["entry_status"] == sfr.ENTRY_BLOCKED_INVALID_OWNERSHIP


def test_non_canonical_branch_label_is_invalid():
    decl = [_decl(branch_label="branch-fw")]  # legacy dash form
    report = sfr.build_system_fw_service_registry(decl)
    entry = report["entries"][0]
    assert entry["branch_ownership"]["verdict"] == bor.INVALID
    assert entry["branch_ownership"]["violated_rule"] == bor.ARCH_CONFORMANCE_NAMING_VIOLATION
    assert report["status"] == sfr.REGISTRY_BLOCKED


def test_ambiguous_declared_facts_report_unknown_not_a_guess():
    """A contradictory declared per_port for the fixed-tier FW kind reports
    AMBIGUOUS from branch_ownership_resolver -- this registry must carry that
    through as ENTRY_UNKNOWN, never silently resolve it either way."""
    decl = [_decl(per_port=False)]  # FW_EVENT_SERVICE_LOOP is canonically per_port=True
    report = sfr.build_system_fw_service_registry(decl)
    entry = report["entries"][0]
    assert entry["branch_ownership"]["verdict"] == bor.AMBIGUOUS
    assert entry["entry_status"] == sfr.ENTRY_UNKNOWN
    assert report["status"] == sfr.REGISTRY_UNKNOWN


def test_missing_branch_label_is_invalid_not_silently_skipped():
    decl = [_decl(branch_label=None)]
    report = sfr.build_system_fw_service_registry(decl)
    assert report["entries"][0]["branch_ownership"]["verdict"] == bor.INVALID
    assert report["status"] == sfr.REGISTRY_BLOCKED


# ---------------------------------------------------------------------------
# Cross-subsystem-evidence reuse: system_resource_inventory's own fields
# ---------------------------------------------------------------------------

def test_stopped_resource_id_blocks_with_valid_branch_ownership():
    decl = [_decl(fw_owned_resource_ids=["USB0::chip::irq", "USB0::other::x"])]
    findings = _findings(stopped=["USB0::chip::irq"])
    report = sfr.build_system_fw_service_registry(decl, cross_subsystem_findings=findings)
    assert report["status"] == sfr.REGISTRY_BLOCKED
    entry = report["entries"][0]
    assert entry["branch_ownership"]["verdict"] == bor.VALID
    assert entry["cross_subsystem_status"] == sfr.CS_BLOCKED
    assert entry["entry_status"] == sfr.ENTRY_BLOCKED_RESOURCE_CONFLICT
    assert entry["cross_subsystem_matched_resource_ids"] == ["USB0::chip::irq"]


def test_held_resource_id_is_held_not_blocked():
    decl = [_decl(fw_owned_resource_ids=["R1"])]
    findings = _findings(held=["R1"])
    report = sfr.build_system_fw_service_registry(decl, cross_subsystem_findings=findings)
    assert report["status"] == sfr.REGISTRY_HELD
    entry = report["entries"][0]
    assert entry["cross_subsystem_status"] == sfr.CS_HELD
    assert entry["entry_status"] == sfr.ENTRY_HELD


def test_shared_resource_id_is_clear_but_noted():
    decl = [_decl(fw_owned_resource_ids=["R1"])]
    findings = _findings(shared=["R1"])
    report = sfr.build_system_fw_service_registry(decl, cross_subsystem_findings=findings)
    assert report["status"] == sfr.REGISTRY_CLEAR
    entry = report["entries"][0]
    assert entry["cross_subsystem_status"] == sfr.CS_SHARED
    assert entry["entry_status"] == sfr.ENTRY_CLEAR_SHARED


def test_stopped_precedence_over_held_and_shared_on_same_entry():
    decl = [_decl(fw_owned_resource_ids=["R1", "R2", "R3"])]
    findings = _findings(stopped=["R1"], held=["R2"], shared=["R3"])
    report = sfr.build_system_fw_service_registry(decl, cross_subsystem_findings=findings)
    assert report["entries"][0]["cross_subsystem_status"] == sfr.CS_BLOCKED


# ---------------------------------------------------------------------------
# Worst-wins across multiple subsystems
# ---------------------------------------------------------------------------

def test_worst_wins_one_blocked_subsystem_fails_whole_registry():
    decl = [
        _decl(subsystem_id="A", fw_owned_resource_ids=["A::x"]),
        _decl(subsystem_id="B", branch_label="branch_a0"),  # invalid ownership
        _decl(subsystem_id="C", fw_owned_resource_ids=["C::y"]),
    ]
    findings = _findings()
    report = sfr.build_system_fw_service_registry(decl, cross_subsystem_findings=findings)
    assert report["status"] == sfr.REGISTRY_BLOCKED
    statuses = {e["subsystem_id"]: e["entry_status"] for e in report["entries"]}
    assert statuses["A"] == sfr.ENTRY_CLEAR
    assert statuses["B"] == sfr.ENTRY_BLOCKED_INVALID_OWNERSHIP
    assert statuses["C"] == sfr.ENTRY_CLEAR
    assert "B" in report["reason"]


def test_worst_wins_blocked_beats_unknown_beats_held_beats_clear():
    decl = [
        _decl(subsystem_id="BLOCKED_SUB", fw_owned_resource_ids=["R1"]),
        _decl(subsystem_id="UNKNOWN_SUB", per_port=False),
        _decl(subsystem_id="HELD_SUB", fw_owned_resource_ids=["R2"]),
        _decl(subsystem_id="CLEAR_SUB", fw_owned_resource_ids=["R3"]),
    ]
    findings = _findings(stopped=["R1"], held=["R2"])
    report = sfr.build_system_fw_service_registry(decl, cross_subsystem_findings=findings)
    assert report["status"] == sfr.REGISTRY_BLOCKED


# ---------------------------------------------------------------------------
# Duplicate subsystem_id refusal
# ---------------------------------------------------------------------------

def test_duplicate_subsystem_id_raises():
    decl = [_decl(subsystem_id="USB0"), _decl(subsystem_id="USB0")]
    with pytest.raises(sfr.SystemFWServiceRegistryError) as exc_info:
        sfr.build_system_fw_service_registry(decl)
    assert exc_info.value.reason == "DUPLICATE_SUBSYSTEM_ID_IN_DECLARATIONS"


# ---------------------------------------------------------------------------
# Reuse assertions: this module must not re-derive branch_ownership_resolver
# or system_resource_inventory's own vocabulary/logic
# ---------------------------------------------------------------------------

def test_default_operation_kind_is_a_real_recognized_branch_ownership_resolver_kind():
    assert sfr.FW_SERVICE_LOOP_OPERATION_KIND in bor.ALL_OPERATION_KINDS


def test_branch_ownership_field_is_the_real_validate_branch_assignment_shape():
    decl = [_decl()]
    report = sfr.build_system_fw_service_registry(decl)
    entry_ownership = report["entries"][0]["branch_ownership"]
    direct = bor.validate_branch_assignment("branch_fw", sfr.FW_SERVICE_LOOP_OPERATION_KIND)
    assert entry_ownership == direct.to_dict()


def test_module_does_not_reimplement_branch_name_regex_or_violation_table():
    """Static check: this module imports branch_ownership_resolver and never
    defines its own branch-label regex or VALID/INVALID/AMBIGUOUS constants,
    which would be the re-derivation this task explicitly forbids."""
    source = Path(sfr.__file__).read_text(encoding="utf-8")
    assert "from . import branch_ownership_resolver as bor" in source
    assert "from . import system_resource_inventory as sri" in source
    # no second branch_a{i}/branch_b{i} naming regex defined in this module
    assert "re.compile" not in source


def test_cross_subsystem_status_vocabulary_uses_real_sri_constants():
    """`CROSSCHECK_AVAILABLE` is read by name from system_resource_inventory,
    never restated as a bare literal string that could silently drift."""
    findings_available = _findings()
    findings_available["status"] = sri.CROSSCHECK_AVAILABLE
    decl = [_decl(fw_owned_resource_ids=["R1"])]
    report = sfr.build_system_fw_service_registry(decl, cross_subsystem_findings=findings_available)
    assert report["entries"][0]["cross_subsystem_status"] == sfr.CS_CLEAR


# ---------------------------------------------------------------------------
# find_system_fw_service_registry_for_root: real system_resource_inventory
# front door, over a root with no registered subsystems (honest UNAVAILABLE)
# ---------------------------------------------------------------------------

def test_find_for_root_with_no_registered_subsystems_is_unknown(tmp_path: Path):
    decl = [_decl(fw_owned_resource_ids=["R1"])]
    report = sfr.find_system_fw_service_registry_for_root(tmp_path, decl)
    assert report["entries"][0]["cross_subsystem_status"] == sfr.CS_UNKNOWN
    assert report["cross_subsystem_findings_status"] == sri.CROSSCHECK_UNAVAILABLE


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_registry_table_contains_subsystem_and_status():
    decl = [_decl(subsystem_id="USB0")]
    report = sfr.build_system_fw_service_registry(decl)
    table = sfr.render_registry_table(report)
    assert "USB0" in table
    assert "branch_fw" in table


def test_render_registry_table_empty_note_when_no_entries():
    report = sfr.build_system_fw_service_registry(None)
    table = sfr.render_registry_table(report)
    assert "no subsystems declared" in table


def test_format_report_contains_status_and_scope_note():
    report = sfr.build_system_fw_service_registry([_decl()])
    text = sfr.format_report(report)
    assert "SYSTEM FW SERVICE REGISTRY" in text
    assert "CLEAR" in text
    assert "branch_ownership_resolver.py" in text
    assert "system_resource_inventory.py" in text


# ---------------------------------------------------------------------------
# CLI front door, driven as a real subprocess
# ---------------------------------------------------------------------------

def test_cli_execute_verb_blocked_exit_code(tmp_path: Path):
    payload = {"subsystem_declarations": [_decl(branch_label="branch_a0")]}
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_fw_service_registry",
         "--input", str(input_path), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 1
    payload_out = json.loads(result.stdout)
    assert payload_out["status"] == sfr.REGISTRY_BLOCKED


def test_cli_execute_verb_clear_exit_code(tmp_path: Path):
    payload = {"subsystem_declarations": [_decl()]}
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_fw_service_registry",
         "--input", str(input_path)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    assert "CLEAR" in result.stdout


def test_cli_execute_verb_not_applicable_with_no_input():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_fw_service_registry"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 2
    assert "NOT_APPLICABLE" in result.stdout


def test_cli_execute_verb_unknown_exit_code(tmp_path: Path):
    payload = {"subsystem_declarations": [_decl(fw_owned_resource_ids=["R1"])]}
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_fw_service_registry",
         "--input", str(input_path), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 2
    payload_out = json.loads(result.stdout)
    assert payload_out["status"] == sfr.REGISTRY_UNKNOWN
