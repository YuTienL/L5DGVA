"""Tests for two additive vip_components schema extensions (2026-08-29),
following the multi-component / port_indexed / interface / ifdef_macro
extensions in test_multi_component_env.py / test_per_port_env.py /
test_interface_and_conditional_components.py.

Real evidence closed by this task, from D:/DV/Task/DV_Agent_Harness_L5/
USB_UVM_Handoff/uvm/tb/env/usb_top_env.sv (re-verified this session):

1. config_db_key_pattern. The generator's existing kind="interface" +
   port_indexed extension hardcodes its per-port config_db get() key as
   $sformatf("<instance_name>_%0d", p) -- but the REAL file does NOT use that
   shape. Lines 371-377:
       port_name = $sformatf("usb%0d_if", p);
       if (!uvm_config_db#(virtual svt_usb_if)::get(null, get_full_name(),
                                                    port_name, usb_if[p])) begin
         `uvm_fatal("build_phase", ...)
       end
   The real key format string is "usb%0d_if" (line 371) -- %0d embedded
   before a fixed "_if" suffix. Since the real instance_name is `usb_if`, the
   generator's guessed default would have produced "usb_if_%0d" (keys
   "usb_if_0"/"usb_if_1"), NOT the real "usb0_if"/"usb1_if". New optional
   per-component field: "config_db_key_pattern": "<pattern>", used verbatim
   via $sformatf instead of the guessed default -- for both the port_indexed
   get() (formatted with `p`) and the scalar get() (formatted with no args;
   default absent behaviour, the original bare quoted instance_name with no
   $sformatf wrapper, is unchanged).

2. kind="plain_object". Two real fields in usb_top_env.sv are NOT
   uvm_component/factory-created objects -- built via a direct new(...) call
   rather than ::type_id::create():
     - line 178/182 (scalar): `svt_err_catcher err_catcher;` constructed in
       the env's own `function new()` (not build_phase) as
       `err_catcher = new({get_full_name(), ".err_catcher"});`
     - line 85/506 (port-indexed): `usb_payload_publish_cb payload_cb [2];`
       constructed in connect_phase (not build_phase) inside a `foreach` as
       `payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);` -- real
       evidence DOES support a port-indexed plain object, so both the scalar
       and port_indexed shapes are implemented (not scoped to scalar-only).
   New optional per-component field: "kind": "plain_object" (alongside the
   existing implicit class-handle kind and "interface"), combined with an
   optional "constructor_args" list of raw SV expression strings,
   comma-joined verbatim into the emitted new(...) call (an arg may reference
   the port loop variable `p` directly, as the real payload_cb call does).
   The generator always places its emitted instantiation in build_phase
   (a generator-composition choice) regardless of which phase the cited real
   new() call happens to use -- only the "plain new(), not
   type_id::create()" shape and the real constructor-arg lists are
   reproduced verbatim, never the real file's own phase placement.

Groups:
  - config_db_key_pattern, scalar interface: custom pattern used verbatim
  - config_db_key_pattern, port_indexed interface: the real cited
    "usb%0d_if" pattern used verbatim instead of the guessed default
  - config_db_key_pattern absent: unchanged default behaviour (scalar and
    port_indexed)
  - kind="plain_object", scalar: declaration + new() call, no
    type_id::create(), reproducing the real err_catcher constructor args
  - kind="plain_object" with no constructor_args: bare new()
  - kind="plain_object" + port_indexed: array declaration + per-port new()
    for-loop, reproducing the real payload_cb constructor args
  - full backward-compatibility regression: every existing fixture from
    test_multi_component_env.py / test_per_port_env.py /
    test_interface_and_conditional_components.py still produces its
    previously-pinned output, byte-identical, with neither new field
    anywhere in those manifests.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from dv_harness.uvm_generator.generator import UVMEnvironmentGenerator, sv_id
from dv_harness.uvm_generator.protocol_env_generator import ProtocolEnvGenerator

from dv_harness_tests.test_multi_component_env import MULTI_COMPONENT_MANIFEST
from dv_harness_tests.test_per_port_env import (
    EXPECTED_MULTI_COMPONENT_ENV_SV,
    MIXED_MANIFEST,
    SINGLE_PORT_INDEXED_MANIFEST,
)
from dv_harness_tests.test_interface_and_conditional_components import (
    IFDEF_MANIFEST,
    IFDEF_PORT_INDEXED_MANIFEST,
    PORT_INDEXED_INTERFACE_MANIFEST,
    SCALAR_INTERFACE_MANIFEST,
)


# ---------------------------------------------------------------------------
# config_db_key_pattern -- scalar interface
# ---------------------------------------------------------------------------

SCALAR_KEY_PATTERN_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "vip_components": [
        {"name": "usb_if", "class_type": "svt_usb_if", "instance_name": "usb_if",
         "kind": "interface", "config_db_key_pattern": "usb_if_custom_key",
         "depends_on": []},
    ],
}


def test_scalar_config_db_key_pattern_used_verbatim():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(SCALAR_KEY_PATTERN_MANIFEST, sv_id(SCALAR_KEY_PATTERN_MANIFEST["protocol"]))
        assert (
            '    if (!uvm_config_db#(virtual svt_usb_if)::get(this, "", $sformatf("usb_if_custom_key"), usb_if))'
            in env_sv
        )
        # never the bare-quoted default key (that shape is only for the field
        # being absent)
        assert '::get(this, "", "usb_if", usb_if)' not in env_sv
        assert (
            '      `uvm_fatal(get_type_name(), "virtual interface usb_if not found in config_db")'
            in env_sv
        )
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# config_db_key_pattern -- port_indexed interface, using the REAL cited
# pattern "usb%0d_if" (usb_top_env.sv:371) instead of the generator's
# guessed default "usb_if_%0d"
# ---------------------------------------------------------------------------

PORT_INDEXED_KEY_PATTERN_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "port_count": 2,
    "vip_components": [
        {"name": "usb_if", "class_type": "svt_usb_if", "instance_name": "usb_if",
         "kind": "interface", "port_indexed": True,
         "config_db_key_pattern": "usb%0d_if", "depends_on": []},
    ],
}


def test_port_indexed_config_db_key_pattern_uses_real_cited_pattern():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(PORT_INDEXED_KEY_PATTERN_MANIFEST, sv_id(PORT_INDEXED_KEY_PATTERN_MANIFEST["protocol"]))
        assert "    for (int p = 0; p < 2; p++) begin" in env_sv
        assert (
            '      if (!uvm_config_db#(virtual svt_usb_if)::get(this, "", $sformatf("usb%0d_if", p), usb_if[p]))'
            in env_sv
        )
        # never the generator's guessed default pattern once the real one is supplied
        assert '$sformatf("usb_if_%0d", p)' not in env_sv
        assert (
            '        `uvm_fatal(get_type_name(), "virtual interface usb_if not found in config_db")'
            in env_sv
        )
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# config_db_key_pattern absent -- unchanged default behaviour (scalar and
# port_indexed), reusing the sibling task's own interface fixtures
# ---------------------------------------------------------------------------

def test_config_db_key_pattern_absent_scalar_default_unchanged():
    assert "config_db_key_pattern" not in str(SCALAR_INTERFACE_MANIFEST)
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(SCALAR_INTERFACE_MANIFEST, sv_id(SCALAR_INTERFACE_MANIFEST["protocol"]))
        assert (
            '    if (!uvm_config_db#(virtual svt_usb_if)::get(this, "", "usb_if", usb_if))'
            in env_sv
        )
        # still no $sformatf wrapper at all when the field is absent
        assert '$sformatf("usb_if"' not in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_config_db_key_pattern_absent_port_indexed_default_unchanged():
    assert "config_db_key_pattern" not in str(PORT_INDEXED_INTERFACE_MANIFEST)
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(PORT_INDEXED_INTERFACE_MANIFEST, sv_id(PORT_INDEXED_INTERFACE_MANIFEST["protocol"]))
        assert (
            '      if (!uvm_config_db#(virtual svt_usb_if)::get(this, "", $sformatf("usb_if_%0d", p), usb_if[p]))'
            in env_sv
        )
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# kind="plain_object" -- scalar, reproducing the real err_catcher evidence
# (usb_top_env.sv:178/182)
# ---------------------------------------------------------------------------

PLAIN_OBJECT_SCALAR_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "vip_components": [
        {"name": "err_catcher", "class_type": "svt_err_catcher", "instance_name": "err_catcher",
         "kind": "plain_object",
         "constructor_args": ['{get_full_name(), ".err_catcher"}'],
         "depends_on": []},
    ],
}


def test_plain_object_scalar_declaration_is_plain_handle():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(PLAIN_OBJECT_SCALAR_MANIFEST, sv_id(PLAIN_OBJECT_SCALAR_MANIFEST["protocol"]))
        assert "  svt_err_catcher err_catcher;" in env_sv
        assert "virtual svt_err_catcher" not in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_plain_object_scalar_build_phase_uses_new_not_type_id_create():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(PLAIN_OBJECT_SCALAR_MANIFEST, sv_id(PLAIN_OBJECT_SCALAR_MANIFEST["protocol"]))
        assert '    err_catcher = new({get_full_name(), ".err_catcher"});' in env_sv
        assert "svt_err_catcher::type_id::create" not in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_plain_object_with_no_constructor_args_emits_bare_new():
    m = dict(PLAIN_OBJECT_SCALAR_MANIFEST)
    m["vip_components"] = [
        {"name": "plain_thing", "class_type": "some_plain_t", "instance_name": "plain_thing",
         "kind": "plain_object", "depends_on": []},
    ]
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(m, sv_id(m["protocol"]))
        assert "  some_plain_t plain_thing;" in env_sv
        assert "    plain_thing = new();" in env_sv
        assert "some_plain_t::type_id::create" not in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# kind="plain_object" + port_indexed -- reproducing the real payload_cb
# evidence (usb_top_env.sv:85/506), which IS port-indexed in the real file
# ---------------------------------------------------------------------------

PLAIN_OBJECT_PORT_INDEXED_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "port_count": 2,
    "vip_components": [
        {"name": "payload_cb", "class_type": "usb_payload_publish_cb", "instance_name": "payload_cb",
         "kind": "plain_object", "port_indexed": True,
         "constructor_args": ['$sformatf("payload_cb_%0d", p)', 'p'],
         "depends_on": []},
    ],
}


def test_plain_object_port_indexed_declaration_is_plain_array():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(PLAIN_OBJECT_PORT_INDEXED_MANIFEST, sv_id(PLAIN_OBJECT_PORT_INDEXED_MANIFEST["protocol"]))
        assert "  usb_payload_publish_cb payload_cb[2];" in env_sv
        assert "virtual usb_payload_publish_cb" not in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_plain_object_port_indexed_build_phase_new_for_loop():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(PLAIN_OBJECT_PORT_INDEXED_MANIFEST, sv_id(PLAIN_OBJECT_PORT_INDEXED_MANIFEST["protocol"]))
        assert "    for (int p = 0; p < 2; p++) begin" in env_sv
        assert '      payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);' in env_sv
        assert "usb_payload_publish_cb::type_id::create" not in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# full backward-compatibility regression: every existing fixture from the
# three sibling extension tasks, byte-identical, neither new field present
# ---------------------------------------------------------------------------

def test_multi_component_manifest_unaffected_byte_identical():
    assert "kind" not in str(MULTI_COMPONENT_MANIFEST)
    assert "config_db_key_pattern" not in str(MULTI_COMPONENT_MANIFEST)
    assert "constructor_args" not in str(MULTI_COMPONENT_MANIFEST)

    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(MULTI_COMPONENT_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")
        assert env_sv == EXPECTED_MULTI_COMPONENT_ENV_SV
    finally:
        shutil.rmtree(tmp)


def test_single_port_indexed_manifest_unaffected():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(SINGLE_PORT_INDEXED_MANIFEST, sv_id(SINGLE_PORT_INDEXED_MANIFEST["protocol"]))
        assert "  svt_usb_agent host_agent[2];" in env_sv
        assert (
            '      host_agent[p] = svt_usb_agent::type_id::create($sformatf("host_agent_%0d", p), this);'
            in env_sv
        )
        assert " = new(" not in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_mixed_manifest_unaffected():
    tmp = Path(tempfile.mkdtemp())
    try:
        ProtocolEnvGenerator(tmp).generate(MIXED_MANIFEST)
        env_sv = (tmp / "tb" / "env" / "usb3_2_env.sv").read_text(encoding="utf-8")
        assert "  usb_clk_rst_agent clk_rst_agent0;" in env_sv
        assert "  svt_usb_agent host_agent[2];" in env_sv
        assert "  svt_usb_agent mon_agent[2];" in env_sv
        assert " = new(" not in env_sv
    finally:
        shutil.rmtree(tmp)


def test_scalar_interface_manifest_unaffected():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(SCALAR_INTERFACE_MANIFEST, sv_id(SCALAR_INTERFACE_MANIFEST["protocol"]))
        assert "  virtual svt_usb_if usb_if;" in env_sv
        assert (
            '    if (!uvm_config_db#(virtual svt_usb_if)::get(this, "", "usb_if", usb_if))'
            in env_sv
        )
    finally:
        shutil.rmtree(gen.out)


def test_port_indexed_interface_manifest_unaffected():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(PORT_INDEXED_INTERFACE_MANIFEST, sv_id(PORT_INDEXED_INTERFACE_MANIFEST["protocol"]))
        assert "  virtual svt_usb_if usb_if[2];" in env_sv
        assert (
            '      if (!uvm_config_db#(virtual svt_usb_if)::get(this, "", $sformatf("usb_if_%0d", p), usb_if[p]))'
            in env_sv
        )
    finally:
        shutil.rmtree(gen.out)


def test_ifdef_manifest_unaffected():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(IFDEF_MANIFEST, sv_id(IFDEF_MANIFEST["protocol"]))
        assert "`ifdef USB_UVM_DMA_MON\n  usb_dma_ssmem_scoreboard ssmem_sb;\n`endif" in env_sv
        assert " = new(" not in env_sv
    finally:
        shutil.rmtree(gen.out)


def test_ifdef_port_indexed_manifest_unaffected():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        env_sv = gen.env(IFDEF_PORT_INDEXED_MANIFEST, sv_id(IFDEF_PORT_INDEXED_MANIFEST["protocol"]))
        expected = (
            '`ifdef USB_UVM_DMA_MON\n'
            '    // no depends_on\n'
            '    for (int p = 0; p < 2; p++) begin\n'
            '      dma_sb[p] = usb_dma_scoreboard::type_id::create($sformatf("dma_sb_%0d", p), this);\n'
            '    end\n'
            '`endif'
        )
        assert expected in env_sv
    finally:
        shutil.rmtree(gen.out)
