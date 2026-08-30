"""Tests for the CONSTRUCT/BUILD-PHASE DEDUP EXTENSION to
_env_multi_component (2026-08-29), plus multi-condition "guard" rendering on
"assign"-kind connections entries.

Real evidence (Multi-Agent Evidence Consensus, re-verified this session
against D:/DV/Task/DV_Agent_Harness_L5/USB_UVM_Handoff/uvm/tb/env/
usb_top_env.sv):

  DEFECT (payload_cb double-construction): a manifest can carry BOTH
    (a) a vip_components entry for payload_cb (kind="plain_object",
        port_indexed) -- which, before this fix, always emitted a
        build_phase `new(...)` call, and
    (b) a top-level "connections" entry with kind="construct" targeting
        payload_cb[p] -- added so connect_phase's real statement list is
        complete (usb_top_env.sv:506).
  Real usb_top_env.sv constructs payload_cb[p] EXACTLY ONCE, in
  connect_phase, at line 506 -- there is no separate build_phase
  construction anywhere in the real file. With both (a) and (b) present and
  no dedup, the generator emitted TWO `new(...)` calls for the same real
  object. The fix: when a "connections" entry's kind="construct" "lhs"
  (array-index suffix stripped, e.g. "payload_cb[{p}]" -> "payload_cb")
  matches a vip_components entry's instance_name, and that component's kind
  is "plain_object", its build_phase creation is skipped entirely
  (declaration kept) -- connect_phase's own `new(...)` is the sole
  construction site. A colliding component of any OTHER kind (class-handle
  default, or "interface") instead raises ConstructionCollisionError
  ("AMBIGUOUS_CONSTRUCT_COLLISION"): for those kinds build_phase IS the only
  real construction site, so a colliding "construct" connections entry is a
  manifest authoring mistake, not a documented real pattern, and must not
  pass silently.

  Real guard evidence for the multi-condition "assign"-kind case
  (usb_top_env.sv:461-465):
    for (int p = 0; p < NUM_USB_PORTS; p++) begin
      if (!cfg.enable_port[p]) continue;
      if (usb_host_agent[p] == null) continue;
      virt_seqr.usb_xfer_seqr[p] = usb_host_agent[p].xfer_sequencer;
    end
  i.e. the real, effective per-statement guard is the AND of both
  continue-conditions: `cfg.enable_port[p] && usb_host_agent[p] != null`.

Groups:
  - positive dedup case: plain_object + colliding construct entry -> exactly
    one `new(...)` for the instance (in connect_phase), zero in build_phase
  - backward-compat, no-collision case: the same plain_object component with
    NO colliding construct entry still gets its build_phase `new(...)`
    exactly as before (regression against the pre-existing behaviour
    test_plain_object_and_key_pattern.py already pins)
  - backward-compat, construct-entry-with-no-vip_components-match case: a
    "construct" connections entry whose "lhs" matches no vip_components
    instance_name at all is unaffected (no dedup, no error -- the pre-9
    behaviour for a manifest that only ever used "construct" standalone)
  - collision against a non-plain_object (class-handle) component ->
    ConstructionCollisionError, reason AMBIGUOUS_CONSTRUCT_COLLISION
  - collision against an "interface"-kind component -> same error
  - multi-condition guard on an "assign"-kind, port_indexed entry renders as
    one AND-joined `if (...)` line, matching the real usb_xfer_seqr wiring
"""
from __future__ import annotations

import shutil
import tempfile

import pytest

from dv_harness.uvm_generator.generator import (
    ConstructionCollisionError,
    UVMEnvironmentGenerator,
    sv_id,
)


def _gen_env(manifest):
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        return gen.env(manifest, sv_id(manifest["protocol"])), gen
    except Exception:
        shutil.rmtree(gen.out)
        raise


_BASE = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"]},
    "port_count": 2,
    "vip_components": [
        {"name": "clk_rst_agent", "class_type": "usb_clk_rst_agent",
         "instance_name": "clk_rst_agent0", "depends_on": []},
    ],
}


# ---------------------------------------------------------------------------
# positive dedup case: plain_object payload_cb + colliding construct entry
# ---------------------------------------------------------------------------

PAYLOAD_CB_DEDUP_MANIFEST = dict(_BASE, vip_components=_BASE["vip_components"] + [
    {"name": "host_agent", "class_type": "svt_usb_agent", "instance_name": "usb_host_agent",
     "port_indexed": True, "depends_on": []},
    {"name": "payload_cb", "class_type": "usb_payload_publish_cb", "instance_name": "payload_cb",
     "kind": "plain_object", "port_indexed": True,
     "constructor_args": ['$sformatf("payload_cb_%0d", p)', "p"],
     "depends_on": ["host_agent"]},
], connections=[
    {"kind": "construct",
     "lhs": "payload_cb[{p}]",
     "ctor_class": "usb_payload_publish_cb",
     "ctor_args": ['$sformatf("payload_cb_%0d", {p})', "{p}"],
     "guard": ["usb_host_agent[{p}] != null"],
     "port_indexed": True,
     "evidence": "usb_top_env.sv:506"},
])


def test_colliding_plain_object_build_phase_construction_is_skipped():
    env_sv, gen = _gen_env(PAYLOAD_CB_DEDUP_MANIFEST)
    try:
        # declaration is kept -- only the build_phase creation is dropped
        assert "  usb_payload_publish_cb payload_cb[2];" in env_sv
        # exactly ONE new() for payload_cb across the whole file, matching
        # real evidence (usb_top_env.sv constructs it exactly once)
        assert env_sv.count("payload_cb[p] = new(") == 1
        # and that one occurrence is the connect_phase construct entry, not
        # a build_phase one: it sits after "connect_phase(uvm_phase phase)"
        connect_pos = env_sv.index("function void connect_phase")
        new_pos = env_sv.index("payload_cb[p] = new(")
        assert new_pos > connect_pos
        assert (
            '      if (usb_host_agent[p] != null) payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);'
            in env_sv
        )
    finally:
        shutil.rmtree(gen.out)


def test_colliding_plain_object_leaves_no_depends_on_comment_or_ifdef_for_it():
    """The whole per-component build_phase block (ordering comment included)
    is skipped, not just the new() line -- there is nothing left to comment
    on once the component contributes no build_phase code."""
    env_sv, gen = _gen_env(PAYLOAD_CB_DEDUP_MANIFEST)
    try:
        assert "after host_agent (depends_on)" not in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# backward-compat: same plain_object component, NO colliding construct entry
# -> build_phase new() still emitted exactly as before this fix
# ---------------------------------------------------------------------------

PAYLOAD_CB_NO_COLLISION_MANIFEST = dict(_BASE, vip_components=_BASE["vip_components"] + [
    {"name": "payload_cb", "class_type": "usb_payload_publish_cb", "instance_name": "payload_cb",
     "kind": "plain_object", "port_indexed": True,
     "constructor_args": ['$sformatf("payload_cb_%0d", p)', "p"],
     "depends_on": []},
])


def test_plain_object_without_colliding_construct_entry_still_constructs_in_build_phase():
    env_sv, gen = _gen_env(PAYLOAD_CB_NO_COLLISION_MANIFEST)
    try:
        assert '      payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);' in env_sv
        assert "function void connect_phase" not in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# backward-compat: a "construct" connections entry whose "lhs" matches no
# vip_components instance_name at all -- unaffected, no dedup, no error
# ---------------------------------------------------------------------------

STANDALONE_CONSTRUCT_MANIFEST = dict(_BASE, connections=[
    {"kind": "construct", "lhs": "err_catcher",
     "evidence": "usb_top_env.sv:182"},
])


def test_construct_entry_with_no_matching_vip_component_is_unaffected():
    env_sv, gen = _gen_env(STANDALONE_CONSTRUCT_MANIFEST)
    try:
        assert "    err_catcher = new();" in env_sv
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# collision against a non-plain_object (default class-handle) component ->
# ConstructionCollisionError
# ---------------------------------------------------------------------------

CLASS_HANDLE_COLLISION_MANIFEST = dict(_BASE, vip_components=_BASE["vip_components"] + [
    {"name": "reg_seqr", "class_type": "usb_reg_sequencer", "instance_name": "reg_seqr",
     "depends_on": []},
], connections=[
    {"kind": "construct", "lhs": "reg_seqr",
     "evidence": "manifest-authoring-mistake-fixture"},
])


def test_construct_collision_against_class_handle_component_raises():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(ConstructionCollisionError) as exc_info:
            gen.env(CLASS_HANDLE_COLLISION_MANIFEST, sv_id(CLASS_HANDLE_COLLISION_MANIFEST["protocol"]))
        assert exc_info.value.reason == "AMBIGUOUS_CONSTRUCT_COLLISION"
        assert exc_info.value.detail["instance_name"] == "reg_seqr"
        assert exc_info.value.detail["kind"] == "class_handle"
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# collision against an "interface"-kind component -> same error
# ---------------------------------------------------------------------------

INTERFACE_COLLISION_MANIFEST = dict(_BASE, vip_components=_BASE["vip_components"] + [
    {"name": "usb_if", "class_type": "svt_usb_if", "instance_name": "usb_if",
     "kind": "interface", "depends_on": []},
], connections=[
    {"kind": "construct", "lhs": "usb_if",
     "evidence": "manifest-authoring-mistake-fixture"},
])


def test_construct_collision_against_interface_component_raises():
    gen = UVMEnvironmentGenerator(tempfile.mkdtemp())
    try:
        with pytest.raises(ConstructionCollisionError) as exc_info:
            gen.env(INTERFACE_COLLISION_MANIFEST, sv_id(INTERFACE_COLLISION_MANIFEST["protocol"]))
        assert exc_info.value.reason == "AMBIGUOUS_CONSTRUCT_COLLISION"
        assert exc_info.value.detail["kind"] == "interface"
    finally:
        shutil.rmtree(gen.out)


# ---------------------------------------------------------------------------
# multi-condition guard on an "assign"-kind, port_indexed entry: real evidence
# is usb_top_env.sv:461-465 (virt_seqr.usb_xfer_seqr[p] wiring), whose two
# continue-guards collapse into one AND-joined `if`
# ---------------------------------------------------------------------------

MULTI_GUARD_ASSIGN_MANIFEST = dict(_BASE, connections=[
    {"from": "virt_seqr.usb_xfer_seqr[{p}]",
     "to": "usb_host_agent[{p}].xfer_sequencer",
     "guard": ["cfg.enable_port[{p}]", "usb_host_agent[{p}] != null"],
     "port_indexed": True,
     "evidence": "usb_top_env.sv:461-465"},
])


def test_multi_condition_guard_on_assign_kind_is_anded_into_one_if():
    env_sv, gen = _gen_env(MULTI_GUARD_ASSIGN_MANIFEST)
    try:
        assert (
            "      if (cfg.enable_port[p] && usb_host_agent[p] != null) "
            "virt_seqr.usb_xfer_seqr[p] = usb_host_agent[p].xfer_sequencer;"
            in env_sv
        )
        assert "{p}" not in env_sv
    finally:
        shutil.rmtree(gen.out)
