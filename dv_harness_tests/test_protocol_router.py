"""Tests for dv_harness/protocol_router.py -- the real, input-driven
protocol/profile resolver that transcribes .claude/skills/CORE/
protocol-router/SKILL.md's normalization rules and tie-break order into
code (see that module's own docstring for the full gap/ruling this closes).

test_two_structurally_different_evidence_dicts_pick_different_real_routes
is the crux test this module exists to prove -- mirroring
dv_harness_tests/test_react_loop.py's
test_two_runs_with_different_gate_failures_pick_different_actions: the SAME
real function, given two genuinely different real evidence dicts, must walk
different branches and land on different real PRIMARY_ROUTES entries, not a
static answer."""
from dv_harness.protocol_router import resolve_protocol, PRIMARY_ROUTES, FIELD_ORDER


def test_two_structurally_different_evidence_dicts_pick_different_real_routes():
    usb_evidence = {"protocol_hint": "Investigate a USB3 link training failure on port 0"}
    pcie_evidence = {"protocol_hint": "Investigate a PCIe LTSSM link training failure on port 0"}

    usb_decision = resolve_protocol(usb_evidence)
    pcie_decision = resolve_protocol(pcie_evidence)

    assert usb_decision["resolved"] is True
    assert pcie_decision["resolved"] is True
    assert usb_decision["protocol"] == "usb"
    assert pcie_decision["protocol"] == "pcie"
    assert usb_decision["protocol"] != pcie_decision["protocol"]
    assert usb_decision["route"] == "USB/usb-profile"
    assert pcie_decision["route"] == "PCIe/pcie-profile"
    assert usb_decision["route"] != pcie_decision["route"]
    # Mandatory non-empty evidence string on every real decision.
    assert usb_decision["evidence"] and isinstance(usb_decision["evidence"], str)
    assert pcie_decision["evidence"] and isinstance(pcie_decision["evidence"], str)


def test_primary_routes_table_matches_skill_md_verbatim():
    assert PRIMARY_ROUTES["usb"]["route"] == "USB/usb-profile"
    assert PRIMARY_ROUTES["pcie"]["route"] == "PCIe/pcie-profile"
    assert PRIMARY_ROUTES["ethernet"]["route"] == "Ethernet/ethernet-profile"
    assert PRIMARY_ROUTES["amba"]["route"] == "AMBA/amba-profile"
    assert PRIMARY_ROUTES["mipi_csi2"]["route"] == "MIPI/csi2-profile"
    assert PRIMARY_ROUTES["mipi_dsi"]["route"] == "MIPI/dsi-profile"
    assert PRIMARY_ROUTES["canfd"]["route"] == "CAN/canfd-profile"
    assert PRIMARY_ROUTES["emmc"]["route"] == "PROTOCOL_BUILDERS/emmc-environment-builder"
    assert PRIMARY_ROUTES["sdio"]["route"] == "PROTOCOL_BUILDERS/sd-environment-builder"


def test_tie_break_order_matches_skill_md():
    assert FIELD_ORDER == (
        "protocol_hint", "failing_test_name", "active_config",
        "modified_files", "subsystem_boundary",
    )


def test_higher_priority_field_wins_over_lower_priority_field_with_different_protocol():
    # "user intent" (protocol_hint) is empty/absent here, so the resolver
    # must fall through to "failing test" (higher priority than "modified
    # files") -- PCIe from failing_test_name must win over USB mentioned
    # only in the lower-priority modified_files field.
    evidence = {
        "failing_test_name": "test_pcie_ltssm_gen4_link_train",
        "modified_files": ["usb_host_controller.sv", "usb_top_env.sv"],
    }
    decision = resolve_protocol(evidence)
    assert decision["resolved"] is True
    assert decision["protocol"] == "pcie"
    assert decision["matched_field"] == "failing_test_name"


def test_protocol_hint_wins_over_every_lower_priority_field():
    evidence = {
        "protocol_hint": "please debug the USB device",
        "failing_test_name": "test_pcie_link_train",
        "modified_files": ["ethernet_mac.sv"],
        "subsystem_boundary": "CAN-FD arbitration subsystem",
    }
    decision = resolve_protocol(evidence)
    assert decision["protocol"] == "usb"
    assert decision["matched_field"] == "protocol_hint"


def test_amba_is_not_chosen_merely_because_an_axi_backend_is_mentioned():
    # SKILL.md: "Do not make AMBA the primary protocol merely because
    # another DUT uses an AXI/APB backend."
    evidence = {"protocol_hint": "the USB controller's register interface uses an AXI backend"}
    decision = resolve_protocol(evidence)
    assert decision["protocol"] == "usb"


def test_amba_wins_when_it_is_the_only_protocol_present():
    evidence = {"protocol_hint": "verify the AXI4 interconnect fabric"}
    decision = resolve_protocol(evidence)
    assert decision["protocol"] == "amba"
    assert decision["route"] == "AMBA/amba-profile"


def test_unresolved_when_no_field_has_a_recognizable_protocol():
    decision = resolve_protocol({"protocol_hint": "please continue the regression"})
    assert decision["resolved"] is False
    assert decision["protocol"] is None
    assert decision["route"] is None
    assert decision["reason"] == "UNRESOLVED_NEEDS_ROUTING_QUESTION"
    assert decision["evidence"]


def test_unresolved_when_evidence_dict_is_empty():
    decision = resolve_protocol({})
    assert decision["resolved"] is False
    assert decision["reason"] == "UNRESOLVED_NEEDS_ROUTING_QUESTION"


def test_modified_files_list_is_scanned_as_evidence():
    decision = resolve_protocol({"modified_files": ["src/canfd_arbitration.sv", "src/canfd_top.sv"]})
    assert decision["protocol"] == "canfd"
    assert decision["matched_field"] == "modified_files"


def test_usb_profile_flags_host_vs_device_further_resolution():
    decision = resolve_protocol({"protocol_hint": "USB device controller"})
    assert decision["further_resolution_required"] == "Host vs Device"


def test_amba_profile_flags_bus_type_further_resolution():
    decision = resolve_protocol({"protocol_hint": "AMBA fabric"})
    assert "APB2" in decision["further_resolution_required"]


# --- Normalization aliases, one per documented SKILL.md rule ----------------

def test_normalize_pci_express_alias():
    assert resolve_protocol({"protocol_hint": "PCI Express link"})["protocol"] == "pcie"


def test_normalize_usb3_and_superspeed_aliases():
    assert resolve_protocol({"protocol_hint": "USB3 SuperSpeed device"})["protocol"] == "usb"


def test_normalize_csi2_alias():
    assert resolve_protocol({"protocol_hint": "MIPI CSI-2 receiver"})["protocol"] == "mipi_csi2"


def test_normalize_canfd_alias():
    assert resolve_protocol({"protocol_hint": "CAN FD bus-off recovery"})["protocol"] == "canfd"


def test_normalize_amab4_typo_alias():
    assert resolve_protocol({"protocol_hint": "AMAB4 fabric review"})["protocol"] == "amba"


def test_normalize_aix4_typo_alias():
    assert resolve_protocol({"protocol_hint": "AIX4 interconnect review"})["protocol"] == "amba"


def test_normalize_axi_stream_alias():
    assert resolve_protocol({"protocol_hint": "AXI Stream FIFO underflow"})["protocol"] == "amba"


def test_normalize_mmc_alias():
    assert resolve_protocol({"protocol_hint": "MMC boot partition"})["protocol"] == "emmc"


def test_normalize_sdio_alias():
    assert resolve_protocol({"protocol_hint": "SDIO interrupt function"})["protocol"] == "sdio"
