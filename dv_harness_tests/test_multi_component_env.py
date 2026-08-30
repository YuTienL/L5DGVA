"""Tests for the vip_components multi-component env extension (2026-08-29,
USB regen-fidelity gap: generator.py's single agent_type/agent_instance slot
cannot represent the real USB_UVM_Handoff env's ~10-component-per-port
composition with real order-dependency comments between instantiation).

Two groups:
  - pure-function tests for topological_build_order (generator.py)
  - generation/integration tests confirming (a) the OLD single-slot manifest
    shape is a byte-identical, untouched code path, and (b) a new
    vip_components manifest produces all components declared and created in
    a valid topological order with the ordering comments present.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.uvm_generator.generator import (
    CircularDependencyError,
    UVMEnvironmentGenerator,
    UnknownDependencyError,
    sv_id,
    topological_build_order,
)
from dv_harness.uvm_generator.protocol_env_generator import ProtocolEnvGenerator


# ---------------------------------------------------------------------------
# topological_build_order -- pure-function tests
# ---------------------------------------------------------------------------

def _c(name, depends_on=None):
    """Minimal vip_components entry -- class_type/instance_name are not used
    by topological_build_order itself (only `name`/`depends_on` matter), but
    are included for realism since real callers always supply them."""
    return {
        "name": name,
        "class_type": name + "_t",
        "instance_name": name + "0",
        "depends_on": depends_on or [],
    }


def test_topological_build_order_linear_chain():
    components = [_c("a"), _c("b", ["a"]), _c("d", ["b"])]
    order = topological_build_order(components)
    assert order == ["a", "b", "d"]


def test_topological_build_order_diamond():
    # a has no deps; b and c both depend on a; d depends on both b and c.
    components = [
        _c("a"),
        _c("b", ["a"]),
        _c("c", ["a"]),
        _c("d", ["b", "c"]),
    ]
    order = topological_build_order(components)
    assert order[0] == "a"
    assert order[-1] == "d"
    assert order.index("a") < order.index("b") < order.index("d")
    assert order.index("a") < order.index("c") < order.index("d")
    # ties broken by input-list order: b appears before c
    assert order.index("b") < order.index("c")
    assert order == ["a", "b", "c", "d"]


def test_topological_build_order_no_dependencies_returns_input_order():
    components = [_c("z"), _c("x"), _c("m"), _c("a")]
    order = topological_build_order(components)
    assert order == ["z", "x", "m", "a"]


def test_topological_build_order_circular_dependency_raises():
    components = [_c("a", ["b"]), _c("b", ["a"])]
    with pytest.raises(CircularDependencyError) as exc_info:
        topological_build_order(components)
    err = exc_info.value
    assert err.reason == "CIRCULAR_DEPENDENCY"
    assert set(err.detail["remaining_components"]) == {"a", "b"}


def test_topological_build_order_circular_dependency_longer_cycle():
    # a -> b -> c -> a, plus an independent, resolvable component "d".
    components = [_c("a", ["c"]), _c("b", ["a"]), _c("c", ["b"]), _c("d")]
    with pytest.raises(CircularDependencyError) as exc_info:
        topological_build_order(components)
    assert set(exc_info.value.detail["remaining_components"]) == {"a", "b", "c"}


def test_topological_build_order_unknown_dependency_raises():
    components = [_c("a", ["ghost"])]
    with pytest.raises(UnknownDependencyError) as exc_info:
        topological_build_order(components)
    err = exc_info.value
    assert err.reason == "UNKNOWN_DEPENDENCY"
    assert err.detail["component"] == "a"
    assert err.detail["unknown_dependency"] == "ghost"
    assert err.detail["known_components"] == ["a"]


# ---------------------------------------------------------------------------
# generation/integration tests
# ---------------------------------------------------------------------------

SINGLE_SLOT_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"], "agent_type": "usb_agent", "agent_instance": "usb_agent0"},
}

EXPECTED_SINGLE_SLOT_ENV_SV = '''class usb3_2_env extends uvm_env;
  `uvm_component_utils(usb3_2_env)
  usb3_2_config cfg;
  usb3_2_virtual_sequencer vseqr;
  usb3_2_scoreboard sb;
  usb3_2_coverage cov;
  usb_agent usb_agent0;

  function new(string name="usb3_2_env", uvm_component parent=null); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if(!uvm_config_db#(usb3_2_config)::get(this,"","cfg",cfg))
      cfg=usb3_2_config::type_id::create("cfg");
    vseqr=usb3_2_virtual_sequencer::type_id::create("vseqr",this);
    sb=usb3_2_scoreboard::type_id::create("sb",this);
    cov=usb3_2_coverage::type_id::create("cov",this);
    usb_agent0=usb_agent::type_id::create("usb_agent0",this);
  endfunction
endclass
'''


def test_old_single_slot_manifest_still_produces_byte_identical_env_sv():
    """Regression pin: a manifest with no vip_components key must still take
    the untouched single-slot branch and produce EXACTLY the pre-existing
    template output (expected string transcribed independently from the
    unchanged code path, not derived by calling env() itself)."""
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        actual = gen.env(SINGLE_SLOT_MANIFEST, sv_id(SINGLE_SLOT_MANIFEST["protocol"]))
        assert actual == EXPECTED_SINGLE_SLOT_ENV_SV
    finally:
        shutil.rmtree(gen.out)


def test_empty_vip_components_list_also_takes_the_single_slot_branch():
    m = dict(SINGLE_SLOT_MANIFEST, vip_components=[])
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        actual = gen.env(m, sv_id(m["protocol"]))
        assert actual == EXPECTED_SINGLE_SLOT_ENV_SV
    finally:
        shutil.rmtree(gen.out)


# Realistic multi-component USB manifest matching the real USB_UVM_Handoff
# evidence structure: clk_rst_agent has no dependencies; several real
# sub-components depend on it (must be built before anything needing a
# clock); dma_env additionally depends on axi_env; reg_seqr depends on
# apb_env.
MULTI_COMPONENT_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "vip_components": [
        {"name": "host_agent0", "class_type": "usb_host_agent", "instance_name": "host_agent0",
         "depends_on": ["clk_rst_agent"]},
        {"name": "host_agent1", "class_type": "usb_host_agent", "instance_name": "host_agent1",
         "depends_on": ["clk_rst_agent"]},
        {"name": "mon_agent0", "class_type": "usb_mon_agent", "instance_name": "mon_agent0",
         "depends_on": ["clk_rst_agent"]},
        {"name": "mon_agent1", "class_type": "usb_mon_agent", "instance_name": "mon_agent1",
         "depends_on": ["clk_rst_agent"]},
        {"name": "apb_env", "class_type": "apb_env_c", "instance_name": "apb_env0",
         "depends_on": ["clk_rst_agent"]},
        {"name": "axi_env", "class_type": "axi_env_c", "instance_name": "axi_env0",
         "depends_on": ["clk_rst_agent"]},
        {"name": "dma_env", "class_type": "dma_env_c", "instance_name": "dma_env0",
         "depends_on": ["clk_rst_agent", "axi_env"]},
        {"name": "clk_rst_agent", "class_type": "usb_clk_rst_agent", "instance_name": "clk_rst_agent0",
         "depends_on": []},
        {"name": "sideband_agent", "class_type": "usb_sideband_agent", "instance_name": "sideband_agent0",
         "depends_on": ["clk_rst_agent"]},
        {"name": "reg_seqr", "class_type": "reg_sequencer", "instance_name": "reg_seqr0",
         "depends_on": ["apb_env"]},
    ],
}


def test_multi_component_manifest_declares_and_creates_all_ten_components():
    tmp = Path(tempfile.mkdtemp())
    try:
        files = ProtocolEnvGenerator(tmp).generate(MULTI_COMPONENT_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")

        components = MULTI_COMPONENT_MANIFEST["vip_components"]
        for c in components:
            # each entry's real class_type/instance_name appears verbatim as
            # a declared handle -- never invented.
            assert "%s %s;" % (c["class_type"], c["instance_name"]) in env_sv
            # and is created via type_id::create using its own instance_name.
            assert '%s=%s::type_id::create("%s",this);' % (
                c["instance_name"], c["class_type"], c["instance_name"]) in env_sv
    finally:
        shutil.rmtree(tmp)


def test_multi_component_env_creation_order_is_a_valid_topological_order():
    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(MULTI_COMPONENT_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")

        by_name = {c["name"]: c for c in MULTI_COMPONENT_MANIFEST["vip_components"]}
        # position of each component's create() call, keyed by component name
        position = {
            name: env_sv.index('%s::type_id::create("%s",this);' % (c["class_type"], c["instance_name"]))
            for name, c in by_name.items()
        }
        for name, c in by_name.items():
            for dep in c["depends_on"]:
                assert position[dep] < position[name], (
                    "%s must be created after its dependency %s" % (name, dep))
        # clk_rst_agent (no depends_on) must be the very first component created.
        creation_positions = sorted(position.items(), key=lambda kv: kv[1])
        assert creation_positions[0][0] == "clk_rst_agent"
    finally:
        shutil.rmtree(tmp)


def test_multi_component_env_has_depends_on_ordering_comments():
    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(MULTI_COMPONENT_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")

        assert "// after clk_rst_agent (depends_on)" in env_sv
        assert "// after clk_rst_agent, axi_env (depends_on)" in env_sv
        assert "// after apb_env (depends_on)" in env_sv
        assert "// no depends_on" in env_sv
    finally:
        shutil.rmtree(tmp)


def test_multi_component_manifest_circular_dependency_raises_during_generation():
    bad = dict(MULTI_COMPONENT_MANIFEST)
    bad["vip_components"] = [
        {"name": "a", "class_type": "a_t", "instance_name": "a0", "depends_on": ["b"]},
        {"name": "b", "class_type": "b_t", "instance_name": "b0", "depends_on": ["a"]},
    ]
    tmp = Path(tempfile.mkdtemp())
    try:
        with pytest.raises(CircularDependencyError):
            ProtocolEnvGenerator(tmp).generate(bad)
    finally:
        shutil.rmtree(tmp)


def test_manifest_component_named_cfg_does_not_collide_with_boilerplate():
    # BUG FIX (2026-08-29, real-USB-evidence round 3): USB_UVM_Handoff's own
    # usb_top_env.sv names its config handle `cfg` (real type `usb_top_cfg`)
    # -- this used to collide with the fixed boilerplate's own
    # `<protocol>_config cfg;` declaration, producing two conflicting `cfg`
    # fields (invalid SystemVerilog). The manifest-supplied component must
    # win: the boilerplate cfg/vseqr/sb/cov line is skipped whenever a
    # vip_components entry already claims that exact instance_name.
    manifest = dict(MULTI_COMPONENT_MANIFEST)
    manifest["vip_components"] = list(MULTI_COMPONENT_MANIFEST["vip_components"]) + [
        {"name": "usb_top_cfg", "class_type": "usb_top_cfg", "instance_name": "cfg", "depends_on": []},
    ]
    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(manifest)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")

        # exactly one `cfg` field declaration -- the real, manifest-supplied
        # one -- never the generic boilerplate's competing declaration.
        assert env_sv.count(" cfg;") == 1
        assert "usb_top_cfg cfg;" in env_sv
        assert "usb3_2_config cfg;" not in env_sv
        # boilerplate creation of cfg must also be gone (no config_db
        # get-or-create for the generic type), but the manifest entry's own
        # create() call is present, and the OTHER boilerplate fields
        # (vseqr/sb/cov) are completely unaffected.
        assert 'cfg=usb3_2_config::type_id::create("cfg");' not in env_sv
        assert 'cfg=usb_top_cfg::type_id::create("cfg",this);' in env_sv
        assert "usb3_2_virtual_sequencer vseqr;" in env_sv
        assert "usb3_2_scoreboard sb;" in env_sv
        assert "usb3_2_coverage cov;" in env_sv
    finally:
        shutil.rmtree(tmp)
