"""Proves mechanism #13 (generic multi-protocol DV Harness scope) is wired
into the REAL generation path -- which is exactly what was never true before
(2026-09-04 re-audit).

The gap these tests exist to keep closed: this package has five real,
unit-tested protocol-model generators (PCIe LTSSM, MIPI D-PHY, CAN-FD
arbitration, AMBA fabric, eMMC/SD command queue), and
`protocol_capability.py` reports them on a production surface -- but a grep
for their non-test callers found only their own five standalone
`tools/generate_*.py` scripts. `create_environment.py`, the entry point
`tools/generate_protocol_uvm_environment.py` and every
`.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` invoke, imported none of them,
so a `protocol: "PCIe"` manifest produced byte-for-byte the same
protocol-agnostic skeleton a `protocol: "Ethernet"` manifest produced. Their
unit tests passed the whole time; that is the PARTIALLY_WIRED shape.

So nothing here calls a protocol model directly to prove it still works --
that was never the gap. Every test drives `create_environment()`, the real
entry point, and asks what actually reached the generated environment. One
test (test_entry_point_runs_the_real_generator_not_a_copy) byte-compares the
entry point's output against the standalone tool's own generator call, so a
future reimplementation-instead-of-reuse would fail rather than pass.
"""
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import protocol_capability as pc
from dv_harness.uvm_generator.create_environment import create_environment
from dv_harness.uvm_generator.protocol_env_generator import ProtocolEnvGenerator
from dv_harness.uvm_generator.protocol_model_layer import (
    PROTOCOL_MODEL_DIR,
    STATE_SIGNAL_KEY,
    STATUS_LAYERED,
    STATUS_NO_MODEL,
    STATUS_NO_TOPOLOGY,
    STATUS_UNKNOWN_PROTOCOL,
    TOPOLOGY_KEY,
    ProtocolModelLayerError,
)

ROOT = Path(__file__).resolve().parents[1]

# The real PCIe manifest shape examples/generated_pcie_uvm_env/
# environment_manifest.json carries (protocol/clocks/resets/smoke_tests),
# plus the per-DUT topology the LTSSM model needs. lane_width/gen_speed/role
# are DUT facts, which is why they live in the manifest and are never
# defaulted by the layer.
_PCIE_TOPOLOGY = {
    "name": "pcie_ep",
    "lane_width": 4,
    "gen_speed": "Gen3",
    "role": "EP",
    STATE_SIGNAL_KEY: "u_pcie_ctrl.ltssm_state_q",
}


def _pcie_manifest(**extra):
    m = {
        "protocol": "PCIe",
        "clocks": [{"name": "refclk"}],
        "resets": [{"name": "perst_n"}],
        "smoke_tests": [{"name": "link_training"}],
    }
    m.update(extra)
    return m


def _tmp():
    return Path(tempfile.mkdtemp())


# --- the layering itself, through the real entry point -----------------------


def test_pcie_manifest_through_the_entry_point_layers_the_ltssm_model():
    """The core regression. A PCIe manifest handed to create_environment()
    now produces the LTSSM model's own SV alongside the generic skeleton;
    before this wiring it produced only the skeleton."""
    tmp = _tmp()
    try:
        result = create_environment(
            tmp, _pcie_manifest(**{TOPOLOGY_KEY: dict(_PCIE_TOPOLOGY)}),
            out_dir=tmp / "out")
        record = result["protocol_model"]
        assert record["status"] == STATUS_LAYERED
        assert record["protocol_model_generator"] == \
            "dv_harness.uvm_generator.pcie_ltssm_generator"
        pkg = tmp / "out" / PROTOCOL_MODEL_DIR / "pcie_ep_ltssm_pkg.sv"
        assert pkg.exists(), "the LTSSM package never reached the generated environment"
        assert (tmp / "out" / PROTOCOL_MODEL_DIR / "pcie_ep_ltssm_state_reg.sv").exists()
        assert f"{PROTOCOL_MODEL_DIR}/pcie_ep_ltssm_pkg.sv" in record["generated_files"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_emitted_sv_carries_the_real_transition_table_not_a_placeholder():
    """The layered content is the model's own computed output: every state in
    pcie_ltssm_generator.LTSSM_TRANSITIONS, with its real legal-target set,
    appears in the emitted legality function."""
    from dv_harness.uvm_generator import pcie_ltssm_generator as ltssm
    tmp = _tmp()
    try:
        create_environment(tmp, _pcie_manifest(**{TOPOLOGY_KEY: dict(_PCIE_TOPOLOGY)}),
                           out_dir=tmp / "out")
        text = (tmp / "out" / PROTOCOL_MODEL_DIR / "pcie_ep_ltssm_pkg.sv").read_text(
            encoding="utf-8")
        for state in ltssm.LTSSM_STATE_ORDER:
            targets = ", ".join(sorted(ltssm.LTSSM_TRANSITIONS[state]))
            assert f"{state}: return (to_state inside {{{targets}}});" in text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_entry_point_runs_the_real_generator_not_a_copy():
    """Byte-identical to what the standalone tool
    (tools/generate_pcie_ltssm_environment.py -> PCIeLTSSMGenerator(out)
    .generate(topology)) produces from the same topology. This is the test
    that fails if someone ever "wires in" a protocol model by reimplementing
    its output inside the generation path instead of calling it."""
    from dv_harness.uvm_generator.pcie_ltssm_generator import PCIeLTSSMGenerator
    tmp = _tmp()
    try:
        create_environment(tmp, _pcie_manifest(**{TOPOLOGY_KEY: dict(_PCIE_TOPOLOGY)}),
                           out_dir=tmp / "out")
        standalone = tmp / "standalone"
        emitted = PCIeLTSSMGenerator(standalone).generate(dict(_PCIE_TOPOLOGY))
        assert emitted, "the standalone generator produced nothing to compare against"
        for name in emitted:
            via_entry_point = tmp / "out" / PROTOCOL_MODEL_DIR / name
            assert via_entry_point.exists(), f"{name} missing from the layered environment"
            assert via_entry_point.read_text(encoding="utf-8") == \
                (standalone / name).read_text(encoding="utf-8"), name
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_model_reaches_the_main_environment_assertions_file():
    """Emitting protocol_model/*.sv alone would leave the generated testbench
    itself unchanged. The state graph is compiled through the EXISTING
    state_machine_checks DSL into tb/env/<p>_assertions.sv -- the file
    generator.assertions() emits -- typed against the package the same run
    layered."""
    from dv_harness.uvm_generator import pcie_ltssm_generator as ltssm
    tmp = _tmp()
    try:
        result = create_environment(
            tmp, _pcie_manifest(**{TOPOLOGY_KEY: dict(_PCIE_TOPOLOGY)}),
            out_dir=tmp / "out")
        assert result["protocol_model"]["state_machine_check"]["injected"] is True
        sva = (tmp / "out" / "tb" / "env" / "pcie_assertions.sv").read_text(encoding="utf-8")
        assert "pcie_ep_ltssm_pkg::ltssm_state_e" in sva, \
            "the assertion is not typed against the layered package"
        assert "u_pcie_ctrl.ltssm_state_q" in sva, "the real DUT state signal is not checked"
        assert "assert property" in sva
        for state in ltssm.LTSSM_STATE_ORDER:
            assert f"{state}: return (to_state inside" in sva
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_model_package_is_prepended_to_the_environment_filelist():
    """An SV package must compile before the file that references its type.
    The layered package is a DEPENDENCY of the skeleton's assertions file, so
    it goes at the head of the filelist, not appended after it."""
    tmp = _tmp()
    try:
        create_environment(tmp, _pcie_manifest(**{TOPOLOGY_KEY: dict(_PCIE_TOPOLOGY)}),
                           out_dir=tmp / "out")
        lines = (tmp / "out" / "filelist" / "dv_uvm_files.f").read_text(
            encoding="utf-8").splitlines()
        pkg = f"{PROTOCOL_MODEL_DIR}/pcie_ep_ltssm_pkg.sv"
        state_reg = f"{PROTOCOL_MODEL_DIR}/pcie_ep_ltssm_state_reg.sv"
        assert pkg in lines and state_reg in lines
        assert lines.index(pkg) < lines.index(state_reg), \
            "the model's own filelist.f compile order was not honoured"
        assert lines.index(pkg) < lines.index("tb/env/pcie_assertions.sv")
        # The JSON the model also emits is evidence, not compilable source.
        assert not any(line.endswith(".json") for line in lines)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- what must NOT change -----------------------------------------------------


def test_usb_generation_is_unchanged_apart_from_the_honest_record():
    """USB is the only DUT_PROVEN protocol and has no protocol-model module
    by design. Every SV file it generates must stay byte-identical to what
    ProtocolEnvGenerator produces directly; the only difference anywhere is
    the protocol_model RECORD inside environment_manifest.json."""
    tmp = _tmp()
    try:
        manifest = {"protocol": "usb", "smoke_tests": [{"name": "smoke"}]}
        result = create_environment(tmp, dict(manifest), out_dir=tmp / "dispatch")
        direct = ProtocolEnvGenerator(tmp / "direct").generate(dict(manifest))

        assert result["generated_files"] == direct
        assert result["protocol_model_files"] == []
        assert not (tmp / "dispatch" / PROTOCOL_MODEL_DIR).exists()
        for rel in direct:
            if rel == "environment_manifest.json":
                continue
            assert (tmp / "dispatch" / rel).read_text(encoding="utf-8") == \
                (tmp / "direct" / rel).read_text(encoding="utf-8"), rel

        record = json.loads(
            (tmp / "dispatch" / "environment_manifest.json").read_text(encoding="utf-8")
        )["protocol_model"]
        assert record["status"] == STATUS_NO_MODEL
        assert record["protocol"] == "USB_2_3x"
        assert record["capability_status"] == "DUT_PROVEN"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_missing_topology_is_recorded_in_the_generated_manifest():
    """A PCIe manifest with no topology is the state every manifest written
    before this wiring is in. It still generates -- but the environment says
    so, naming the module that would have run and the key that was missing,
    so a skeleton can never be mistaken for a modelled environment."""
    tmp = _tmp()
    try:
        result = create_environment(tmp, _pcie_manifest(), out_dir=tmp / "out")
        record = result["protocol_model"]
        assert record["status"] == STATUS_NO_TOPOLOGY
        assert record["required_manifest_key"] == TOPOLOGY_KEY
        assert record["protocol_model_generator"] == \
            "dv_harness.uvm_generator.pcie_ltssm_generator"
        assert record["capability_status"] == "PROTOCOL_MODEL_PARTIAL"
        assert not (tmp / "out" / PROTOCOL_MODEL_DIR).exists()
        on_disk = json.loads(
            (tmp / "out" / "environment_manifest.json").read_text(encoding="utf-8"))
        assert on_disk["protocol_model"]["status"] == STATUS_NO_TOPOLOGY
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_assertion_is_emitted_against_an_unconfirmed_state_signal():
    """The DUT signal carrying the LTSSM state is RTL evidence. Without it
    the model still layers, but no assertion is invented against a signal
    name nobody confirmed -- and the refusal is recorded, not silent."""
    tmp = _tmp()
    try:
        topology = {k: v for k, v in _PCIE_TOPOLOGY.items() if k != STATE_SIGNAL_KEY}
        result = create_environment(tmp, _pcie_manifest(**{TOPOLOGY_KEY: topology}),
                                    out_dir=tmp / "out")
        check = result["protocol_model"]["state_machine_check"]
        assert check["injected"] is False
        assert check["required_topology_field"] == STATE_SIGNAL_KEY
        sva = (tmp / "out" / "tb" / "env" / "pcie_assertions.sv").read_text(encoding="utf-8")
        assert "assert property" not in sva
        # ...but the model itself still layered.
        assert (tmp / "out" / PROTOCOL_MODEL_DIR / "pcie_ep_ltssm_pkg.sv").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_hand_written_check_of_the_same_name_is_never_overwritten():
    """A manifest-supplied state_machine_checks entry is author evidence
    about this DUT. The generated one yields to it rather than replacing it
    (and generator.assertions() would raise DUPLICATE_ASSERTION_NAME on two
    entries sharing a name)."""
    tmp = _tmp()
    try:
        hand_written = {
            "assertion_name": "pcie_ep_transition_legal_check",
            "kind": "legal_value_set",
            "value_signal": "link_up",
            "legal_values": ["1'b0", "1'b1"],
            "evidence": "hand-written from this DUT's RTL",
        }
        result = create_environment(
            tmp, _pcie_manifest(**{TOPOLOGY_KEY: dict(_PCIE_TOPOLOGY),
                                   "state_machine_checks": [hand_written]}),
            out_dir=tmp / "out")
        check = result["protocol_model"]["state_machine_check"]
        assert check["injected"] is False
        sva = (tmp / "out" / "tb" / "env" / "pcie_assertions.sv").read_text(encoding="utf-8")
        assert "link_up inside" in sva
        assert "ltssm_state_e" not in sva
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_rejected_topology_refuses_instead_of_producing_a_bare_skeleton():
    """The model's own validator judges the topology. x3 is not a legal PCIe
    link width, and the caller who asked for an LTSSM model is told that --
    not handed a skeleton that looks like the environment they requested."""
    tmp = _tmp()
    try:
        bad = dict(_PCIE_TOPOLOGY, lane_width=3)
        with pytest.raises(ProtocolModelLayerError) as exc:
            create_environment(tmp, _pcie_manifest(**{TOPOLOGY_KEY: bad}),
                               out_dir=tmp / "out")
        assert exc.value.reason == "PROTOCOL_MODEL_TOPOLOGY_REJECTED"
        assert exc.value.detail["model_reason"] == "INVALID_LANE_WIDTH"
        assert exc.value.detail["model_detail"]["lane_width"] == 3
        # The model runs before the skeleton precisely so a refusal leaves no
        # half-written environment that could be mistaken for a generated one.
        assert not (tmp / "out" / "tb").exists()
        assert not (tmp / "out" / "environment_manifest.json").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_generated_manifest_records_the_layered_files():
    """The record is written to disk by ProtocolEnvGenerator, so the emitted
    file list has to be in it by then -- an environment_manifest.json that
    said LAYERED but listed nothing would be the same unverifiable claim this
    whole mechanism exists to prevent."""
    tmp = _tmp()
    try:
        create_environment(tmp, _pcie_manifest(**{TOPOLOGY_KEY: dict(_PCIE_TOPOLOGY)}),
                           out_dir=tmp / "out")
        record = json.loads(
            (tmp / "out" / "environment_manifest.json").read_text(encoding="utf-8")
        )["protocol_model"]
        assert record["status"] == STATUS_LAYERED
        assert f"{PROTOCOL_MODEL_DIR}/pcie_ep_ltssm_pkg.sv" in record["generated_files"]
        assert record["state_machine_check"]["injected"] is True
        for rel in record["generated_files"]:
            assert (tmp / "out" / rel).exists(), rel
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- not a PCIe special case --------------------------------------------------

# One real minimal topology per remaining protocol model, in each model's own
# schema (the same dicts their standalone tools take). Together with PCIe
# these cover all five protocol-model modules protocol_capability declares.
_OTHER_PROTOCOLS = [
    ("CAN_FD", "dv_harness.uvm_generator.canfd_arbitration_generator",
     {"bus_name": "canfd_bus", "id_format": "STANDARD", "node_ids": ["ecu_a", "ecu_b"]}),
    ("MIPI_CSI2", "dv_harness.uvm_generator.mipi_dphy_generator",
     {"module_name": "csi2_dphy", "role": "RX", "lane_count": 4}),
    ("MIPI_DSI", "dv_harness.uvm_generator.mipi_dphy_generator",
     {"module_name": "dsi_dphy", "role": "TX", "lane_count": 2}),
    ("AMBA4_MULTI_MASTER_MULTI_SLAVE", "dv_harness.uvm_generator.amba_fabric_generator",
     {"fabric_name": "soc_fabric", "addr_width": 12,
      "masters": [{"id": "cpu", "id_width": 4}],
      "slaves": [{"id": "sram", "base_addr": "0x0", "size": "0x1000"}],
      "assume_full_connectivity": True}),
    ("eMMC", "dv_harness.uvm_generator.emmc_cmdq_generator",
     {"module_name": "emmc_cmdq", "num_tags": 32}),
    ("SD_SDIO", "dv_harness.uvm_generator.emmc_cmdq_generator",
     {"module_name": "sdio_cmdq", "num_tags": 32}),
]


@pytest.mark.parametrize("protocol,module,topology", _OTHER_PROTOCOLS)
def test_every_modelled_protocol_layers_through_the_entry_point(protocol, module, topology):
    """PCIe is the recommended first non-USB pilot, not the only protocol
    that got wired: each of the five protocol-model modules is reachable from
    the one CREATE ENVIRONMENT entry point."""
    tmp = _tmp()
    try:
        result = create_environment(
            tmp, {"protocol": protocol, "smoke_tests": [{"name": "smoke"}],
                  TOPOLOGY_KEY: topology},
            out_dir=tmp / "out")
        record = result["protocol_model"]
        assert record["status"] == STATUS_LAYERED
        assert record["protocol_model_generator"] == module
        emitted = list((tmp / "out" / PROTOCOL_MODEL_DIR).glob("*.sv"))
        assert emitted, f"{protocol} layered nothing compilable"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_protocol_with_no_model_is_reported_as_such_not_as_modelled():
    """Ethernet has no protocol-specific module anywhere in dv_harness/. The
    generated environment says GENERIC_SKELETON_ONLY rather than leaving the
    absence to be inferred."""
    tmp = _tmp()
    try:
        result = create_environment(
            tmp, {"protocol": "Ethernet", "smoke_tests": [{"name": "smoke"}]},
            out_dir=tmp / "out")
        record = result["protocol_model"]
        assert record["status"] == STATUS_NO_MODEL
        assert record["capability_status"] == "GENERIC_SKELETON_ONLY"
        assert record["protocol_model_generator"] == "NONE"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_unrecognised_protocol_claims_nothing():
    tmp = _tmp()
    try:
        result = create_environment(
            tmp, {"protocol": "SomeInternalBus", "smoke_tests": [{"name": "smoke"}]},
            out_dir=tmp / "out")
        record = result["protocol_model"]
        assert record["status"] == STATUS_UNKNOWN_PROTOCOL
        assert "PCIe" in record["known_protocols"]
        assert (tmp / "out" / "tb" / "env" / "someinternalbus_env.sv").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- protocol resolution + the registry that drives it ------------------------


@pytest.mark.parametrize("spelling,expected", [
    ("PCIe", "PCIe"), ("pcie", "PCIe"), ("PCI Express", "PCIe"),
    ("usb", "USB_2_3x"), ("USB3", "USB_2_3x"), ("SuperSpeed", "USB_2_3x"),
    ("CAN FD", "CAN_FD"), ("canfd", "CAN_FD"),
    ("AXI4", "AMBA4_MULTI_MASTER_MULTI_SLAVE"), ("amba", "AMBA4_MULTI_MASTER_MULTI_SLAVE"),
    ("MIPI CSI-2", "MIPI_CSI2"), ("emmc", "eMMC"), ("SDIO", "SD_SDIO"),
])
def test_manifest_protocol_spellings_resolve_to_the_capability_entry(spelling, expected):
    """The layer resolves a manifest's protocol string through the two
    resolvers this repo already has -- the capability registry's key/alias
    table and protocol_router's evidence classifier -- so the registry's
    `PCIe`/`eMMC` casing, protocol_router's lowercase canon, and a
    hand-written `PCI Express` all land on the same capability entry rather
    than silently reporting a modelled protocol as unmodelled."""
    from dv_harness.uvm_generator.protocol_model_layer import plan_protocol_model
    record = plan_protocol_model({"protocol": spelling})
    assert record.get("protocol") == expected, record


def test_every_declared_protocol_model_resolves_its_generator_entry_point():
    """The layer invokes `generator_class` off each PROTOCOL_CAPABILITIES
    entry. A renamed class must fail here (and in --check), not at generation
    time."""
    declared = [c for c in pc.PROTOCOL_CAPABILITIES if c.model is not None]
    assert len(declared) >= 5
    for cap in declared:
        cls = pc.resolve_generator_class(cap.model)
        assert hasattr(cls, "generate"), f"{cap.protocol}: {cap.model.generator_class}"


def test_the_shipped_registry_still_matches_the_code():
    """This repo's own registry must stay in sync after the capability
    entries gained generator_class and PCIe's note changed -- the same
    `python -m dv_harness.protocol_capability --check` contract."""
    pc.assert_registry_matches_code(ROOT)
