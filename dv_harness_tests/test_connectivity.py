"""Tests for dv_harness/connectivity.py -- bind-location / VIP-connectivity /
checker-scoreboard planning system (2026-09-03, "mcp-bind-connectivity"
workstream, Part C of the user's env.manifest.json spec).

Covers: the 4-tier bind classifier (all 4 tiers, plus a genuine
T3-must-never-auto-accept regression test), the count-check equations (a
passing case and a deliberately-broken case per interface), the per-row
lock/diff mechanism, the checker/scoreboard planning-table generator's
ORDERING/LEGAL-DROP-never-auto-filled guarantee, the 3 machine gates
(synthetic fixtures + a live-environment honesty check for Gate 1), the
existing-bind grep/parse, the interface-fingerprint protocol matcher, and
the topology/config_db-trace parsers against documented-shape synthetic
fixtures.
"""
from __future__ import annotations

import inspect
import json

import pytest

from dv_harness import connectivity as conn


# ===========================================================================
# 4-tier confidence classifier
# ===========================================================================

def test_tier1_already_decided_from_existing_bind():
    r = conn.classify_bind_tier(existing_bind={"target": "chip.core.usb0"})
    assert r.tier == conn.BindTier.T1_ALREADY_DECIDED
    assert r.auto_acceptable is True
    assert r.requires_human_confirmation is False
    assert r.requires_question_queue_entry is False


def test_tier2_structural_match_auto_acceptable_but_listed():
    match = conn.match_protocol_fingerprint(
        {"AWVALID", "AWREADY", "WLAST", "BRESP", "SOMETHING_ELSE"}, "AXI")
    assert match["matched"] is True
    r = conn.classify_bind_tier(structural_match=match)
    assert r.tier == conn.BindTier.T2_STRUCTURAL_MATCH
    assert r.auto_acceptable is True
    assert r.requires_human_confirmation is False
    # "still LISTED in the report for visibility" -- rationale must name the protocol.
    assert "AXI" in r.rationale


def test_tier3_naming_heuristic_always_requires_human_confirmation():
    r = conn.classify_bind_tier(naming_match="u_usb3_top")
    assert r.tier == conn.BindTier.T3_NAMING_HEURISTIC
    assert r.auto_acceptable is False
    assert r.requires_human_confirmation is True
    assert r.requires_question_queue_entry is False


def test_tier3_never_auto_accepted_even_with_partial_structural_hint():
    """Regression guard: a naming match alone (no FULL structural fingerprint
    match) must classify as T3 and never be nudged to auto-acceptable, even
    when some -- not all -- required structural signals happen to be present."""
    partial = conn.match_protocol_fingerprint({"AWVALID"}, "AXI")  # missing AWREADY/WLAST/BRESP
    assert partial["matched"] is False
    r = conn.classify_bind_tier(naming_match="u_axi_bridge", structural_match=partial)
    assert r.tier == conn.BindTier.T3_NAMING_HEURISTIC
    assert r.auto_acceptable is False
    assert r.requires_human_confirmation is True
    conn.assert_t3_never_auto_accepted(r)  # must not raise


def test_assert_t3_never_auto_accepted_catches_a_corrupted_result():
    bad = conn.BindTierResult(
        tier=conn.BindTier.T3_NAMING_HEURISTIC, rationale="x",
        auto_acceptable=True, requires_human_confirmation=False,
        requires_question_queue_entry=False,
    )
    with pytest.raises(conn.BindTierError) as exc:
        conn.assert_t3_never_auto_accepted(bad)
    assert exc.value.reason == "T3_MUST_NEVER_AUTO_ACCEPT"


def test_tier4_undecidable_routes_to_question_queue():
    r = conn.classify_bind_tier()
    assert r.tier == conn.BindTier.T4_UNDECIDABLE
    assert r.auto_acceptable is False
    assert r.requires_human_confirmation is False
    assert r.requires_question_queue_entry is True


def test_tier_priority_t1_outranks_everything_else():
    match = conn.match_protocol_fingerprint({"AWVALID", "AWREADY", "WLAST", "BRESP"}, "AXI")
    r = conn.classify_bind_tier(existing_bind={"target": "chip.core.axi0"},
                                 structural_match=match, naming_match="u_axi_bridge")
    assert r.tier == conn.BindTier.T1_ALREADY_DECIDED


# ===========================================================================
# Interface fingerprints (extends verible_parser, real port extraction)
# ===========================================================================

def test_build_interface_fingerprints_from_verible_module_info():
    mod = conn.verible_parser.ModuleInfo(
        name="axi_slave_wrap",
        ports=[
            conn.verible_parser.PortInfo(name="awvalid", direction="input", data_type="logic"),
            conn.verible_parser.PortInfo(name="awready", direction="output", data_type="logic"),
            conn.verible_parser.PortInfo(name="wlast", direction="input", data_type="logic"),
            conn.verible_parser.PortInfo(name="bresp", direction="output", data_type="logic [1:0]"),
        ],
    )
    fps = conn.build_interface_fingerprints([mod])
    assert fps["axi_slave_wrap"] == {"AWVALID", "AWREADY", "WLAST", "BRESP"}


def test_match_protocol_fingerprint_partial_never_rounds_up():
    result = conn.match_protocol_fingerprint({"AWVALID", "AWREADY"}, "AXI")
    assert result["matched"] is False
    assert result["missing_signals"] == ["BRESP", "WLAST"]


def test_match_protocol_fingerprint_unknown_protocol_is_honest():
    result = conn.match_protocol_fingerprint({"AWVALID"}, "NOT_A_REAL_PROTOCOL")
    assert result["matched"] is False
    assert result["reason"] == "UNKNOWN_PROTOCOL_FINGERPRINT"


# ===========================================================================
# Existing binds (grep/parse)
# ===========================================================================

def test_parse_bind_line_extracts_target_module_instance():
    parsed = conn.parse_bind_line("  bind chip.core.evt_ctrl dv_uvm_probe u_evt_probe (.a(a));")
    assert parsed == ("chip.core.evt_ctrl", "dv_uvm_probe", "u_evt_probe")


def test_parse_bind_line_rejects_non_bind_line():
    assert conn.parse_bind_line("  wire bind_flag = 1;") is None


def test_grep_existing_binds_real_filesystem_scan(tmp_path):
    bind_dir = tmp_path / "tb"
    bind_dir.mkdir()
    (bind_dir / "usb_bind.sv").write_text(
        "// header\n"
        "bind chip.core.usb0 dv_uvm_probe u_usb0_probe (.clk(clk), .rst_n(rst_n));\n"
        "  bind axi_slave_wrap dv_uvm_axi_probe u_axi_probe (.awvalid(awvalid));\n",
        encoding="utf-8",
    )
    binds = conn.grep_existing_binds(tmp_path)
    assert len(binds) == 2
    assert binds[0].target == "chip.core.usb0"
    assert binds[0].bound_module == "dv_uvm_probe"
    assert binds[0].line_no == 2
    assert binds[1].target == "axi_slave_wrap"  # bare module name -- Rule 1 territory


def test_grep_existing_binds_empty_dir_returns_empty_not_error(tmp_path):
    assert conn.grep_existing_binds(tmp_path / "does_not_exist") == []


def test_find_existing_bind_for_target_exact_path_match():
    binds = [conn.BindStatement(target="chip.core.usb0", bound_module="m", instance_name="u",
                                 source_file="f.sv", line_no=1, raw_line="x")]
    found = conn.find_existing_bind_for_target(binds, "chip.core.usb0")
    assert found is binds[0]
    assert conn.find_existing_bind_for_target(binds, "chip.core.usb1") is None


# ===========================================================================
# Topology dump / config_db trace parsers (documented-shape synthetic fixtures)
# ===========================================================================

TOPOLOGY_FIXTURE = """
Name                    Type                Size
------------------------------------------------------
uvm_test_top            usb3_test           -
  env                   usb3_env            -
    agent0              usb3_agent          -
      driver            usb3_driver         -
      monitor           usb3_monitor        -
------------------------------------------------------
"""


def test_parse_topology_dump_recovers_hierarchy_from_indent():
    components = conn.parse_topology_dump(TOPOLOGY_FIXTURE)
    paths = {c.path: c.type_name for c in components}
    assert paths["uvm_test_top"] == "usb3_test"
    assert paths["uvm_test_top.env"] == "usb3_env"
    assert paths["uvm_test_top.env.agent0"] == "usb3_agent"
    assert paths["uvm_test_top.env.agent0.driver"] == "usb3_driver"
    assert paths["uvm_test_top.env.agent0.monitor"] == "usb3_monitor"


CFGDB_TRACE_FIXTURE = """
UVM_INFO @ 0: reporter [CFGDB/SET] Configuration 'vif' (virtual interface) set in "uvm_test_top.env.agent0" via top
UVM_INFO @ 0: reporter [CFGDB/GET] Configuration 'vif' (virtual interface) get in "uvm_test_top.env.agent0" via driver
UVM_INFO @ 0: reporter [CFGDB/SET] Configuration 'orphan_vif' (virtual interface) set in "uvm_test_top.env.agent1" via top
"""


def test_parse_config_db_trace_and_find_set_with_no_get():
    events = conn.parse_config_db_trace(CFGDB_TRACE_FIXTURE)
    assert len(events) == 3
    orphaned = conn.find_set_with_no_get(events)
    assert len(orphaned) == 1
    assert orphaned[0].field == "orphan_vif"
    assert orphaned[0].context_path == "uvm_test_top.env.agent1"


def test_capture_vip_topology_honest_not_available_with_no_paths():
    result = conn.capture_vip_topology()
    assert result["status"] == "NOT_AVAILABLE"
    assert "detail" in result


def test_capture_vip_topology_real_when_paths_supplied(tmp_path):
    topo_path = tmp_path / "topology.log"
    topo_path.write_text(TOPOLOGY_FIXTURE, encoding="utf-8")
    cfg_path = tmp_path / "cfgdb.log"
    cfg_path.write_text(CFGDB_TRACE_FIXTURE, encoding="utf-8")
    result = conn.capture_vip_topology(str(topo_path), str(cfg_path))
    assert result["status"] == "REAL"
    assert len(result["components"]) == 5
    assert len(result["set_with_no_get"]) == 1


# ===========================================================================
# DUT instance tree (slang) -- honesty check + synthetic-fixture parser test
# ===========================================================================

def test_capture_dut_instance_tree_honest_not_available_in_this_environment():
    """This environment genuinely has no `slang` on PATH (confirmed live,
    2026-09-03) -- this is a real honesty check, not a mocked assumption."""
    result = conn.capture_dut_instance_tree()
    assert result["status"] == "NOT_AVAILABLE"
    assert "slang" in result["detail"]


SLANG_AST_FIXTURE = {
    "kind": "Instance", "name": "",
    "body": {"name": "chip_top", "members": [
        {"kind": "Instance", "name": "usb0",
         "body": {"name": "usb3_subsystem", "members": [
             {"kind": "Instance", "name": "phy",
              "body": {"name": "usb3_phy", "members": []}},
         ]}},
        {"kind": "Port", "name": "clk"},  # non-instance member, must be skipped
    ]},
}


def test_parse_slang_ast_json_against_documented_shape_fixture():
    tree = conn.parse_slang_ast_json(SLANG_AST_FIXTURE)
    assert tree.module_name == "chip_top"
    assert len(tree.children) == 1
    usb0 = tree.children[0]
    assert usb0.instance_name == "usb0"
    assert usb0.module_name == "usb3_subsystem"
    assert usb0.full_path == "usb0"
    assert usb0.children[0].full_path == "usb0.phy"
    assert usb0.children[0].module_name == "usb3_phy"


def test_capture_dut_instance_tree_real_from_ast_json_file(tmp_path):
    ast_path = tmp_path / "ast.json"
    ast_path.write_text(json.dumps(SLANG_AST_FIXTURE), encoding="utf-8")
    result = conn.capture_dut_instance_tree(str(ast_path))
    assert result["status"] == "REAL"
    assert result["tree"].module_name == "chip_top"


def test_capture_dut_instance_tree_not_available_names_both_capture_methods():
    """The NOT_AVAILABLE detail must document BOTH documented capture
    methods, not just slang -- a site with VCS but no slang has to be told
    the `scope -tree` route is genuinely usable, not a docstring promise."""
    result = conn.capture_dut_instance_tree()
    assert result["status"] == "NOT_AVAILABLE"
    assert "slang" in result["detail"]
    assert "scope -tree" in result["detail"]
    assert "scope_tree_path" in result["detail"]


# ===========================================================================
# DUT instance tree, capture method (b): `simv -ucli -do "scope -tree"`
# ===========================================================================

SCOPE_TREE_FIXTURE = """ucli% scope -tree
tb_top
  dut (chip_top)
    usb0 (usb3_subsystem)
      phy (usb3_phy)
    axi0 (axi_slave_wrap)
$unit
"""


def test_parse_scope_tree_dump_recovers_full_instance_paths():
    parsed = conn.parse_scope_tree_dump(SCOPE_TREE_FIXTURE)
    assert parsed.unparsed_lines == []
    paths = {n.full_path: n.module_name
             for r in parsed.roots for n in conn.flatten_instance_tree(r)}
    assert paths["tb_top"] is None            # no annotation -> honest unknown
    assert paths["tb_top.dut"] == "chip_top"
    assert paths["tb_top.dut.usb0"] == "usb3_subsystem"
    assert paths["tb_top.dut.usb0.phy"] == "usb3_phy"
    assert paths["tb_top.dut.axi0"] == "axi_slave_wrap"
    # `$unit` is a second root at indent 0, not a child of tb_top.
    assert [r.full_path for r in parsed.roots] == ["tb_top", "$unit"]
    assert parsed.parsed_node_count == 6


def test_parse_scope_tree_dump_accepts_brace_and_colon_annotation_forms():
    parsed = conn.parse_scope_tree_dump(
        "tb_top {tb_top_module}\n  dut : chip_top\n    usb0    usb3_subsystem\n")
    assert parsed.unparsed_lines == []
    nodes = {n.full_path: n.module_name for n in conn.flatten_instance_tree(parsed.roots[0])}
    assert nodes["tb_top"] == "tb_top_module"
    assert nodes["tb_top.dut"] == "chip_top"
    assert nodes["tb_top.dut.usb0"] == "usb3_subsystem"


def test_parse_scope_tree_dump_ascii_tree_glyph_indentation():
    """Some UCLI builds draw the tree with `|`/`+`/backtick glyphs -- those
    are indentation, and depth must still come from the name's start column."""
    parsed = conn.parse_scope_tree_dump(
        "tb_top\n"
        "|-- dut (chip_top)\n"
        "|   `-- usb0 (usb3_subsystem)\n"
    )
    assert parsed.unparsed_lines == []
    paths = [n.full_path for n in conn.flatten_instance_tree(parsed.roots[0])]
    assert paths == ["tb_top", "tb_top.dut", "tb_top.dut.usb0"]


def test_parse_scope_tree_dump_preserves_literal_generate_array_indices():
    """Bind-Location Rule 4 requires literal indices in a bind target -- the
    parser must carry `phy_array[0]`/`[1]` through verbatim, never collapse
    them to a wildcard or drop the index."""
    parsed = conn.parse_scope_tree_dump(
        "chip\n  phy_array[0] (usb3_phy)\n  phy_array[1] (usb3_phy)\n")
    paths = [n.full_path for n in conn.flatten_instance_tree(parsed.roots[0])]
    assert paths == ["chip", "chip.phy_array[0]", "chip.phy_array[1]"]


def test_parse_scope_tree_dump_escaped_identifier_keeps_its_depth():
    """A SystemVerilog escaped identifier starts with `\\`, which is also an
    ASCII tree-drawing glyph. It must be read as part of the NAME, not as
    one extra column of indentation (which would silently reparent it)."""
    parsed = conn.parse_scope_tree_dump("chip\n  \\u_phy[0] (usb3_phy)\n")
    child = parsed.roots[0].children[0]
    assert child.instance_name == "\\u_phy[0]"
    assert child.full_path == "chip.\\u_phy[0]"


def test_parse_scope_tree_dump_flat_absolute_path_listing_is_not_double_prefixed():
    parsed = conn.parse_scope_tree_dump(
        "tb_top.dut (chip_top)\ntb_top.dut.usb0 (usb3_subsystem)\n")
    assert [r.full_path for r in parsed.roots] == ["tb_top.dut", "tb_top.dut.usb0"]


def test_parse_scope_tree_dump_is_fail_closed_on_unrecognized_lines():
    """An unrecognized line must be REPORTED, never silently dropped: a
    dropped line is a silently-missing bind target."""
    parsed = conn.parse_scope_tree_dump(
        "tb_top\n  dut (chip_top)\nTop level modules:\n")
    assert parsed.parsed_node_count == 2
    assert len(parsed.unparsed_lines) == 1
    assert parsed.unparsed_lines[0] == (3, "Top level modules:")


def test_capture_dut_instance_tree_real_from_scope_tree_file(tmp_path):
    dump = tmp_path / "scope_tree.txt"
    dump.write_text(SCOPE_TREE_FIXTURE, encoding="utf-8")
    result = conn.capture_dut_instance_tree(scope_tree_path=str(dump))
    assert result["status"] == "REAL"
    assert result["source"] == "simv_ucli_scope_tree"
    assert result["instance_paths"] == [
        "tb_top", "tb_top.dut", "tb_top.dut.usb0", "tb_top.dut.usb0.phy",
        "tb_top.dut.axi0", "$unit",
    ]
    assert result["unparsed_lines"] == []


def test_capture_dut_instance_tree_scope_tree_partial_is_flagged_not_hidden(tmp_path):
    dump = tmp_path / "scope_tree.txt"
    dump.write_text("tb_top\n  dut (chip_top)\n?? weird vcs line ??\n", encoding="utf-8")
    result = conn.capture_dut_instance_tree(scope_tree_path=str(dump))
    assert result["status"] == "REAL_PARTIAL"
    assert result["parsed_node_count"] == 2
    assert len(result["unparsed_lines"]) == 1


def test_capture_dut_instance_tree_scope_tree_parse_failed_not_empty_real(tmp_path):
    """A capture whose format this parser does not understand must NOT come
    back as a confident REAL empty hierarchy."""
    dump = tmp_path / "scope_tree.txt"
    dump.write_text("?? 1 ??\n?? 2 ??\n", encoding="utf-8")
    result = conn.capture_dut_instance_tree(scope_tree_path=str(dump))
    assert result["status"] == "PARSE_FAILED"
    assert result["parsed_node_count"] == 0
    assert result["tree"] is None


def test_capture_dut_instance_tree_rejects_both_sources_at_once(tmp_path):
    ast_path = tmp_path / "ast.json"
    ast_path.write_text(json.dumps(SLANG_AST_FIXTURE), encoding="utf-8")
    dump = tmp_path / "scope_tree.txt"
    dump.write_text(SCOPE_TREE_FIXTURE, encoding="utf-8")
    with pytest.raises(conn.BindTierError) as exc:
        conn.capture_dut_instance_tree(str(ast_path), scope_tree_path=str(dump))
    assert exc.value.reason == "AMBIGUOUS_DUT_TREE_SOURCE"


def test_both_capture_methods_yield_the_same_interchangeable_path_list(tmp_path):
    """The point of implementing method (b): both methods must feed the SAME
    flat full-instance-path list downstream, so a site with only VCS gets the
    same Input 1 a site with only slang gets."""
    ast_path = tmp_path / "ast.json"
    ast_path.write_text(json.dumps(SLANG_AST_FIXTURE), encoding="utf-8")
    from_slang = conn.capture_dut_instance_tree(str(ast_path))
    slang_paths = [n.full_path for n in conn.flatten_instance_tree(from_slang["tree"])
                   if n.full_path]

    dump = tmp_path / "scope_tree.txt"
    dump.write_text("usb0 (usb3_subsystem)\n  phy (usb3_phy)\n", encoding="utf-8")
    from_scope = conn.capture_dut_instance_tree(scope_tree_path=str(dump))

    assert slang_paths == ["usb0", "usb0.phy"]
    assert from_scope["instance_paths"] == slang_paths


# ===========================================================================
# Count-check equations
# ===========================================================================

def test_vip_instance_count_matches_active_interfaces_passing_case():
    vips = [conn.VipInstanceRecord(vip_type="AXI", instance_path="a", active_passive="active"),
            conn.VipInstanceRecord(vip_type="AXI", instance_path="b", active_passive="active")]
    result = conn.check_vip_instance_count_matches_active_interfaces(vips, active_interface_count=2)
    assert result["ok"] is True
    assert result["delta"] == 0


def test_vip_instance_count_matches_active_interfaces_broken_case_passive_monitor_excluded():
    """A passive-monitor-only IP is 1 IP instance but 0 active interfaces --
    deliberately broken: 1 VIP instance vs. 0 active interfaces must NOT be
    reported as matching."""
    vips = [conn.VipInstanceRecord(vip_type="APB", instance_path="mon0", active_passive="passive")]
    result = conn.check_vip_instance_count_matches_active_interfaces(vips, active_interface_count=0)
    assert result["ok"] is False
    assert result["vip_instance_count"] == 1
    assert result["delta"] == 1


def test_determine_role_from_port_direction_output_means_dut_initiator():
    assert "slave_responder" in conn.determine_role_from_port_direction("output")


def test_determine_role_from_port_direction_input_means_dut_target():
    assert "master_initiator" in conn.determine_role_from_port_direction("input")


def test_determine_role_from_port_direction_inout_is_honest_not_guessed():
    assert "AMBIGUOUS" in conn.determine_role_from_port_direction("inout")


def test_determine_role_from_port_direction_never_takes_a_name_parameter():
    sig = inspect.signature(conn.determine_role_from_port_direction)
    assert list(sig.parameters) == ["dut_port_direction"]


def test_determine_role_from_port_direction_rejects_unknown_value():
    with pytest.raises(conn.ConnectivityError):
        conn.determine_role_from_port_direction("weird")


def test_compute_path_combination_count_full_mesh_default():
    result = conn.compute_path_combination_count(["m0", "m1"], ["s0", "s1", "s2"])
    assert result["total_path_combinations"] == 6
    assert result["per_master"]["m0"] == ["s0", "s1", "s2"]


def test_compute_path_combination_count_with_restricted_reachability():
    """A passive monitor on a shared fabric is NOT the same dimension as
    master count -- this checks the real path-combination sizing when
    reachability is restricted (not full mesh)."""
    reach = {"m0": {"s0", "s1"}, "m1": {"s2"}}
    result = conn.compute_path_combination_count(["m0", "m1"], ["s0", "s1", "s2"], reachability=reach)
    assert result["total_path_combinations"] == 3
    assert result["per_master"]["m1"] == ["s2"]


def test_verify_self_check_identity_passing_case():
    exemptions = [{"interface": "chip.dbg0", "reason": "debug-only port, intentionally unconnected to any VIP"}]
    assert conn.verify_self_check_identity(3, 2, exemptions) is True


def test_verify_self_check_identity_fails_loudly_on_mismatch():
    """Deliberately-broken case: 3 verified interfaces, 1 VIP instance, no
    exemptions -- must raise, not return False/print a warning."""
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.verify_self_check_identity(3, 1, [])
    assert exc.value.reason == "SELF_CHECK_IDENTITY_MISMATCH"
    assert exc.value.detail["gap"] == 2


def test_verify_self_check_identity_rejects_exemption_without_reason():
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.verify_self_check_identity(2, 1, [{"interface": "chip.dbg0"}])
    assert exc.value.reason == "EXEMPTION_MISSING_EXPLANATION"


# ===========================================================================
# Connectivity matrix
# ===========================================================================

def _sample_row(tier="T2_STRUCTURAL_MATCH"):
    return conn.ConnectivityRow(
        dut_instance="chip.core.usb0", interface="usb3_if", direction="output",
        role="vip_role=slave_responder", vip_type="USB3", count=1,
        active_passive="active", bind_target="chip.core.usb0", tier=tier,
    )


def test_build_connectivity_matrix_fixed_columns():
    rows = [_sample_row()]
    matrix = conn.build_connectivity_matrix(rows)
    assert list(matrix[0].keys()) == conn.MATRIX_COLUMNS


def test_render_matrix_table_contains_all_values():
    table = conn.render_matrix_table([_sample_row()])
    assert "chip.core.usb0" in table
    assert "USB3" in table
    assert "T2_STRUCTURAL_MATCH" in table


def test_render_matrix_table_empty_is_honest():
    assert conn.render_matrix_table([]) == "(empty connectivity matrix)"


def test_write_connectivity_manifest_round_trips(tmp_path):
    out_path = tmp_path / "manifest.json"
    conn.write_connectivity_manifest(out_path, [_sample_row()], metadata={"project": "test"})
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["columns"] == conn.MATRIX_COLUMNS
    assert loaded["rows"][0]["dut_instance"] == "chip.core.usb0"
    assert loaded["metadata"]["project"] == "test"


def test_render_hierarchy_diagram_is_valid_mermaid_flowchart():
    diagram = conn.render_hierarchy_diagram([_sample_row()])
    assert diagram.startswith("flowchart LR")
    assert "chip.core.usb0" in diagram
    assert "USB3" in diagram


# ===========================================================================
# 3 machine gates
# ===========================================================================

def test_detect_elaboration_tool_prefers_slang_over_vcs():
    which_fn = lambda name: "/usr/bin/slang" if name == "slang" else "/usr/bin/vcs"
    assert conn.detect_elaboration_tool(which_fn) == "slang"


def test_run_gate1_elaboration_check_honest_not_available_in_this_environment():
    """Real, live check against this actual machine: neither slang nor vcs
    is installed here (confirmed 2026-09-03)."""
    result = conn.run_gate1_elaboration_check(["dut.f"], "chip_top")
    assert result.status == conn.GateStatus.NOT_AVAILABLE
    assert "slang" in result.detail["instructions"]
    assert "vcs" in result.detail["instructions"]


def test_run_gate1_elaboration_check_pass_with_injected_tool(monkeypatch):
    which_fn = lambda name: "/usr/bin/slang" if name == "slang" else None

    class FakeProc:
        returncode = 0
        stdout = "{}"
        stderr = ""

    run_fn = lambda argv, **kw: FakeProc()
    result = conn.run_gate1_elaboration_check(["dut.f"], "chip_top", which_fn=which_fn, run_fn=run_fn)
    assert result.status == conn.GateStatus.PASS
    assert result.detail["tool"] == "slang"


def test_run_gate1_elaboration_check_fail_on_nonzero_exit():
    which_fn = lambda name: "/usr/bin/slang" if name == "slang" else None

    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "error: unknown module 'chip_top_wrong'"

    run_fn = lambda argv, **kw: FakeProc()
    result = conn.run_gate1_elaboration_check(["dut.f"], "chip_top_wrong", which_fn=which_fn, run_fn=run_fn)
    assert result.status == conn.GateStatus.FAIL
    assert "chip_top_wrong" in result.detail["stderr"]


def test_evaluate_zero_time_connectivity_passing_fixture():
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "1"), (2, "0"), (3, "1")],
        "rst_n": [(0, "0"), (5, "1")],
        "data_valid": [(0, "0"), (6, "1")],
    })
    result = conn.evaluate_zero_time_connectivity(trace, "clk", "rst_n", ["data_valid"])
    assert result.status == conn.GateStatus.PASS
    assert result.detail["clock_toggles"] is True
    assert result.detail["reset_deasserts"] is True


def test_evaluate_zero_time_connectivity_flags_dead_clock():
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "0"), (2, "0")],  # never toggles -- silent/dead interface
        "rst_n": [(0, "0"), (5, "1")],
        "data_valid": [(0, "0")],
    })
    result = conn.evaluate_zero_time_connectivity(trace, "clk", "rst_n", ["data_valid"])
    assert result.status == conn.GateStatus.FAIL
    assert result.detail["clock_toggles"] is False


def test_evaluate_zero_time_connectivity_flags_x_at_time_zero():
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "1")],
        "rst_n": [(0, "0"), (5, "1")],
        "addr": [(0, "xxxx")],  # X at time zero specifically
    })
    result = conn.evaluate_zero_time_connectivity(trace, "clk", "rst_n", ["addr"])
    assert result.status == conn.GateStatus.FAIL
    assert any("addr" in p for p in result.detail["nonx_at_t0_problems"])


def test_run_gate2_against_live_simv_honest_not_available():
    result = conn.run_gate2_against_live_simv()
    assert result.status == conn.GateStatus.NOT_AVAILABLE


def test_evaluate_transaction_activity_passing_fixture():
    result = conn.evaluate_transaction_activity({"env.agent0.monitor": 5, "env.agent1.monitor": 1})
    assert result.status == conn.GateStatus.PASS
    assert result.detail["silent_monitors"] == {}


def test_evaluate_transaction_activity_flags_silent_monitor():
    """The specific case Part C calls out: a path that's syntactically legal
    and structurally wired but connected to the WRONG instance -- its
    monitor sees zero real transactions."""
    result = conn.evaluate_transaction_activity({"env.agent0.monitor": 5, "env.agent1.monitor": 0})
    assert result.status == conn.GateStatus.FAIL
    assert result.detail["silent_monitors"] == {"env.agent1.monitor": 0}


def test_run_gate3_against_live_simv_honest_not_available():
    result = conn.run_gate3_against_live_simv()
    assert result.status == conn.GateStatus.NOT_AVAILABLE


def test_run_machine_gates_pipeline_runs_all_three_in_order():
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "1")], "rst_n": [(0, "0"), (2, "1")], "addr": [(0, "0")],
    })
    report = conn.run_machine_gates(
        ["dut.f"], "chip_top", trace, required_nonx_signals=["addr"],
        monitor_transaction_counts={"mon0": 1},
    )
    assert report.gate1.gate == "gate1_elaboration"
    assert report.gate2.gate == "gate2_zero_time_connectivity"
    assert report.gate3.gate == "gate3_transaction_activity"
    # Gate1 NOT_AVAILABLE in this real environment; gate2/gate3 real PASS.
    assert report.gate1.status == conn.GateStatus.NOT_AVAILABLE
    assert report.gate2.status == conn.GateStatus.PASS
    assert report.gate3.status == conn.GateStatus.PASS
    assert report.ready_for_human_review() is True  # NOT_AVAILABLE alone does not block
    assert "gate1_elaboration" in report.not_available_gates()


def test_run_machine_gates_pipeline_blocks_on_a_real_fail():
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "0")],  # dead clock -> gate2 FAIL
        "rst_n": [(0, "0"), (2, "1")], "addr": [(0, "0")],
    })
    report = conn.run_machine_gates(["dut.f"], "chip_top", trace, required_nonx_signals=["addr"],
                                     monitor_transaction_counts={"mon0": 1})
    assert report.gate2.status == conn.GateStatus.FAIL
    assert report.ready_for_human_review() is False


def test_run_machine_gates_defaults_to_not_available_gates_without_live_evidence():
    """No signal_trace / no monitor_transaction_counts supplied -> gate2/
    gate3 must honestly report NOT_AVAILABLE, never a fabricated PASS."""
    report = conn.run_machine_gates(["dut.f"], "chip_top", signal_trace=None)
    assert report.gate2.status == conn.GateStatus.NOT_AVAILABLE
    assert report.gate3.status == conn.GateStatus.NOT_AVAILABLE


# ===========================================================================
# Gate-status PENDING/NOT_YET_RUN (2026-09-03, Gap #2 -- mandatory-gate-
# checkpoint workstream: the TCA-hang situation, where no pattern has
# completed yet, must be trackable as PENDING, never conflated with FAIL,
# NOT_AVAILABLE, or silently omitted).
# ===========================================================================

def test_evaluate_transaction_activity_status_pending_when_no_pattern_completed():
    """The exact TCA-hang shape this workstream exists to make trackable:
    no pattern has reached a terminal PASS/FAIL yet -- Gate 3 must report
    PENDING, never FAIL (nothing has actually failed a check) and never
    NOT_AVAILABLE (this is not a tooling gap)."""
    result = conn.evaluate_transaction_activity_status(pattern_completed=False)
    assert result.status == conn.GateStatus.PENDING
    assert result.status != conn.GateStatus.FAIL
    assert result.status != conn.GateStatus.NOT_AVAILABLE
    assert "pattern" in result.detail["reason"]


def test_evaluate_transaction_activity_status_pending_ignores_stray_counts():
    """pattern_completed is the real evidence this function trusts -- a
    caller accidentally passing a (stale/irrelevant) counts dict alongside
    pattern_completed=False must not flip the result to PASS/FAIL."""
    result = conn.evaluate_transaction_activity_status(
        pattern_completed=False, monitor_transaction_counts={"mon0": 5})
    assert result.status == conn.GateStatus.PENDING


def test_evaluate_transaction_activity_status_delegates_to_real_verdict_once_completed():
    passing = conn.evaluate_transaction_activity_status(
        pattern_completed=True, monitor_transaction_counts={"mon0": 3})
    assert passing.status == conn.GateStatus.PASS

    failing = conn.evaluate_transaction_activity_status(
        pattern_completed=True, monitor_transaction_counts={"mon0": 0})
    assert failing.status == conn.GateStatus.FAIL


def test_evaluate_transaction_activity_status_not_available_when_completed_but_no_counts():
    """Pattern finished, but no tooling path exists to source counts from --
    a genuine capability gap, distinct from PENDING."""
    result = conn.evaluate_transaction_activity_status(pattern_completed=True)
    assert result.status == conn.GateStatus.NOT_AVAILABLE


def test_run_machine_gates_reports_gate3_pending_when_pattern_completed_is_false():
    report = conn.run_machine_gates(["dut.f"], "chip_top", signal_trace=None, pattern_completed=False)
    assert report.gate3.status == conn.GateStatus.PENDING
    assert "gate3_transaction_activity" in report.pending_gates()
    # PENDING must never block presenting for human review the way FAIL does.
    assert report.ready_for_human_review() is True


def test_gate_status_enum_has_all_four_required_distinct_values():
    """The explicit requirement: NOT_YET_RUN / PENDING / PASS / FAIL must all
    exist as genuinely distinct enum members, extending the SAME GateStatus
    every gate result already used (not a parallel status type)."""
    values = {s.value for s in conn.GateStatus}
    assert {"NOT_YET_RUN", "PENDING", "PASS", "FAIL", "NOT_AVAILABLE"} == values
    assert conn.GateStatus.PENDING != conn.GateStatus.FAIL
    assert conn.GateStatus.PENDING != conn.GateStatus.NOT_AVAILABLE
    assert conn.GateStatus.NOT_YET_RUN != conn.GateStatus.PENDING


# ===========================================================================
# Mandatory build-status checkpoint (2026-09-03, Gap #2): bind_verification_
# status_block() / render_bind_verification_status_markdown() /
# assert_bind_gates_checkpoint(). This is the code-level half of the
# mechanism; dv_harness_tests/test_bind_verification_lint.py covers the
# standalone report-artifact lint script that operates on the actual
# prose-driven build-status reports IP_UVM_DV_Gen.md's agent produces.
# ===========================================================================

def test_bind_verification_status_block_all_not_yet_run_when_gate_report_is_none():
    """Before the checkpoint (no gate ever invoked): every key must
    explicitly report NOT_YET_RUN -- the block is never simply empty, which
    would be indistinguishable from "the report omitted this section"."""
    block = conn.bind_verification_status_block(None)
    assert block == {
        "gate1_elaboration": "NOT_YET_RUN",
        "gate2_zero_time_connectivity": "NOT_YET_RUN",
        "gate3_transaction_activity": "NOT_YET_RUN",
    }


def test_bind_verification_status_block_reflects_real_gate_report():
    report = conn.run_machine_gates(["dut.f"], "chip_top", signal_trace=None, pattern_completed=False)
    block = conn.bind_verification_status_block(report)
    assert block["gate1_elaboration"] == "NOT_AVAILABLE"  # no slang/vcs in this environment
    assert block["gate3_transaction_activity"] == "PENDING"


def test_render_bind_verification_status_markdown_contains_all_three_gate_lines():
    md = conn.render_bind_verification_status_markdown(None)
    assert "## Bind Verification Status" in md
    assert "Gate 1" in md and "NOT_YET_RUN" in md
    assert "Gate 2" in md
    assert "Gate 3" in md


def test_assert_bind_gates_checkpoint_noop_before_first_compile_succeeds():
    """The checkpoint only fires once first_compile_succeeded=True -- an
    in-progress, not-yet-compiled build is not itself a violation."""
    conn.assert_bind_gates_checkpoint(first_compile_succeeded=False, gate_report=None)  # must not raise


def test_assert_bind_gates_checkpoint_raises_when_gates_never_invoked_at_first_compile():
    """The exact confirmed gap: a build reaches first successful compile but
    the 3-gate standard was never applied -- this must raise, not pass
    silently."""
    with pytest.raises(conn.BindGateCheckpointError) as exc:
        conn.assert_bind_gates_checkpoint(first_compile_succeeded=True, gate_report=None)
    assert exc.value.reason == "GATES_NEVER_INVOKED_AT_FIRST_COMPILE_CHECKPOINT"


def test_assert_bind_gates_checkpoint_accepts_pending_gate3_at_first_compile():
    """Gate 3 PENDING (no pattern completed yet -- the TCA-hang shape) must
    be ACCEPTED at this checkpoint, as long as Gates 1/2 were genuinely
    invoked -- PENDING is an expected, not a violating, state here."""
    report = conn.run_machine_gates(["dut.f"], "chip_top", signal_trace=None, pattern_completed=False)
    conn.assert_bind_gates_checkpoint(first_compile_succeeded=True, gate_report=report)  # must not raise


def test_assert_bind_gates_checkpoint_accepts_any_real_gate1_gate2_status():
    """PASS, FAIL, and NOT_AVAILABLE all count as "genuinely invoked" for
    Gates 1/2 -- only NOT_YET_RUN is the violation this checkpoint guards
    against."""
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "1")], "rst_n": [(0, "0"), (2, "1")], "addr": [(0, "0")],
    })
    report = conn.run_machine_gates(["dut.f"], "chip_top", trace, required_nonx_signals=["addr"],
                                     pattern_completed=False)
    assert report.gate1.status == conn.GateStatus.NOT_AVAILABLE  # real env: no slang/vcs
    assert report.gate2.status == conn.GateStatus.PASS
    conn.assert_bind_gates_checkpoint(first_compile_succeeded=True, gate_report=report)  # must not raise


# ===========================================================================
# Simulated IP_UVM_DV_Gen-style build reaching "first successful compile"
# (2026-09-03, Gap #2 -- the concrete fault-injection proof requested for
# this gap closure: a build that skips running Gates 1/2 must be caught).
# ===========================================================================

def test_simulated_build_workflow_blocked_from_proceeding_when_gates_skipped():
    """Models the exact real incident: an IP_UVM_DV_Gen-style build reaches
    first successful compile/elaboration, then tries to move on to the next
    documented step (Step 10's static self-check / Step 11's deliverables)
    WITHOUT having run Gates 1/2 first. The checkpoint must block this."""
    class FakeBuildWorkflow:
        def __init__(self):
            self.first_compile_succeeded = False
            self.gate_report = None
            self.advanced_past_checkpoint = False

        def compile_succeeds(self):
            self.first_compile_succeeded = True
            # NOTE: deliberately does NOT run Gates 1/2 here -- the real
            # confirmed defect this test reproduces.

        def try_advance_to_next_step(self):
            conn.assert_bind_gates_checkpoint(self.first_compile_succeeded, self.gate_report)
            self.advanced_past_checkpoint = True

    wf = FakeBuildWorkflow()
    wf.compile_succeeds()
    with pytest.raises(conn.BindGateCheckpointError):
        wf.try_advance_to_next_step()
    assert wf.advanced_past_checkpoint is False


def test_simulated_build_workflow_proceeds_once_gates_1_and_2_actually_run():
    """Same simulated workflow, this time genuinely running Gates 1/2 (Gate 3
    legitimately still PENDING -- no pattern has completed) before advancing
    -- the checkpoint must let this through."""
    class FakeBuildWorkflow:
        def __init__(self):
            self.first_compile_succeeded = False
            self.gate_report = None
            self.advanced_past_checkpoint = False

        def compile_succeeds(self):
            self.first_compile_succeeded = True

        def run_gates_1_and_2_as_required_checkpoint(self):
            self.gate_report = conn.run_machine_gates(
                ["dut.f"], "chip_top", signal_trace=None, pattern_completed=False)

        def try_advance_to_next_step(self):
            conn.assert_bind_gates_checkpoint(self.first_compile_succeeded, self.gate_report)
            self.advanced_past_checkpoint = True

    wf = FakeBuildWorkflow()
    wf.compile_succeeds()
    wf.run_gates_1_and_2_as_required_checkpoint()
    wf.try_advance_to_next_step()  # must not raise
    assert wf.advanced_past_checkpoint is True
    assert wf.gate_report.gate3.status == conn.GateStatus.PENDING  # still explicit, never omitted


# ===========================================================================
# Per-row lock/diff mechanism
# ===========================================================================

def test_row_lock_confirm_then_no_op_regeneration_needs_zero_reconfirmation(tmp_path):
    store = conn.RowLockStore(tmp_path / "locks.json")
    row = _sample_row()
    store.confirm_row(row.row_id(), row.to_dict())

    # regenerate with NO change
    regenerated = [_sample_row()]
    needing = store.diff_rows_needing_reconfirmation(regenerated, lambda r: r.row_id())
    assert needing == []


def test_row_lock_changed_row_is_flagged_for_reconfirmation_others_are_not(tmp_path):
    store = conn.RowLockStore(tmp_path / "locks.json")
    row_a = _sample_row()
    row_b = conn.ConnectivityRow(
        dut_instance="chip.core.axi0", interface="axi_if", direction="input",
        role="vip_role=master_initiator", vip_type="AXI", count=1,
        active_passive="active", bind_target="chip.core.axi0", tier="T1_ALREADY_DECIDED",
    )
    store.confirm_row(row_a.row_id(), row_a.to_dict())
    store.confirm_row(row_b.row_id(), row_b.to_dict())

    # regenerate: row_a changes tier (simulated RTL-driven reclassification), row_b unchanged
    row_a_changed = _sample_row(tier="T1_ALREADY_DECIDED")
    needing = store.diff_rows_needing_reconfirmation([row_a_changed, row_b], lambda r: r.row_id())
    assert len(needing) == 1
    assert needing[0].row_id() == row_a.row_id()


def test_row_lock_never_confirmed_row_needs_reconfirmation(tmp_path):
    store = conn.RowLockStore(tmp_path / "locks.json")
    needing = store.diff_rows_needing_reconfirmation([_sample_row()], lambda r: r.row_id())
    assert len(needing) == 1


def test_row_lock_persists_across_store_reload(tmp_path):
    path = tmp_path / "locks.json"
    row = _sample_row()
    store1 = conn.RowLockStore(path)
    store1.confirm_row(row.row_id(), row.to_dict())

    store2 = conn.RowLockStore(path)  # fresh instance, same file
    assert store2.is_locked(row.row_id())
    needing = store2.diff_rows_needing_reconfirmation([_sample_row()], lambda r: r.row_id())
    assert needing == []


# ===========================================================================
# Checker/scoreboard planning-table generator
# ===========================================================================

def test_generate_protocol_check_entry_lists_disabled_with_reason():
    entry = conn.generate_protocol_check_entry(
        "chip.core.usb0::usb3_if", "USB3",
        builtin_checks=["protocol_state_check", "crc_check", "timeout_check"],
        disabled_checks={"timeout_check": "DUT intentionally holds bus past spec timeout during calibration; VIP timeout disabled for this test only"},
    )
    assert entry["kind"] == "protocol_check"
    assert "timeout_check" not in entry["enabled_builtin_checks"]
    assert entry["disabled_builtin_checks"][0]["check"] == "timeout_check"
    assert entry["disabled_builtin_checks"][0]["reason"]


def test_generate_protocol_check_entry_rejects_disabled_check_without_reason():
    with pytest.raises(conn.ConnectivityError) as exc:
        conn.generate_protocol_check_entry(
            "row1", "AXI", builtin_checks=["addr_check"], disabled_checks={"addr_check": ""})
    assert exc.value.reason == "DISABLED_CHECK_MISSING_REASON"


def test_generate_protocol_check_entry_rejects_disabling_unknown_check():
    with pytest.raises(conn.ConnectivityError) as exc:
        conn.generate_protocol_check_entry(
            "row1", "AXI", builtin_checks=["addr_check"], disabled_checks={"not_a_real_check": "because"})
    assert exc.value.reason == "DISABLED_CHECK_NOT_IN_BUILTIN_LIST"


def test_generate_scoreboard_entry_ordering_and_legal_drop_default_to_required_human_input():
    """The core never-auto-filled guarantee: with no explicit ordering/
    legal_drop supplied, both fields must be exactly the REQUIRED_HUMAN_INPUT
    sentinel -- never a guessed value, never silently None with no signal."""
    entry = conn.generate_scoreboard_entry(
        "sb_usb0_axi0", endpoint_pairs=[("chip.core.usb0", "chip.core.axi0")],
        matching_key="transaction_id",
    )
    assert entry["ordering"] == conn.REQUIRED_HUMAN_INPUT
    assert entry["legal_drop_conditions"] == conn.REQUIRED_HUMAN_INPUT
    assert entry["reset_flush_behavior"] == conn.REQUIRED_HUMAN_INPUT
    assert entry["orphan_unmatched_threshold"] == conn.REQUIRED_HUMAN_INPUT
    assert entry["orphan_unmatched_timeout"] == conn.REQUIRED_HUMAN_INPUT


def test_generate_scoreboard_entry_accepts_explicit_human_supplied_values():
    entry = conn.generate_scoreboard_entry(
        "sb_usb0_axi0", endpoint_pairs=[("chip.core.usb0", "chip.core.axi0")],
        matching_key="transaction_id", ordering="in_order", legal_drop_conditions="none permitted",
    )
    assert entry["ordering"] == "in_order"
    assert entry["legal_drop_conditions"] == "none permitted"


def test_generate_scoreboard_entry_structural_fields_never_defaulted():
    """endpoint_pairs/matching_key are structural facts, not part of the
    never-auto-fill guarantee -- they are always required, real arguments."""
    with pytest.raises(TypeError):
        conn.generate_scoreboard_entry("sb0")  # missing required endpoint_pairs/matching_key


def test_generate_system_level_entry_basic_shape():
    entry = conn.generate_system_level_entry(
        "sys0", "performance_check", ["chip.core.usb0", "chip.core.ddr0"],
        "End-to-end USB3-to-DDR bandwidth check under sustained bulk transfer")
    assert entry["kind"] == "system_level"
    assert entry["system_level_kind"] == "performance_check"


def test_build_checker_scoreboard_plan_groups_by_kind():
    plan = conn.build_checker_scoreboard_plan(
        protocol_entries=[{"kind": "protocol_check"}],
        scoreboard_entries=[{"kind": "data_integrity_scoreboard"}],
        system_entries=[{"kind": "system_level"}],
    )
    assert len(plan["protocol_checks"]) == 1
    assert len(plan["data_integrity_scoreboards"]) == 1
    assert len(plan["system_level_checks"]) == 1


# ===========================================================================
# T4 question queue -- real delegation into dv_harness/question_queue.py
# (2026-09-03 review defect F6: this used to hand-build a dict that failed
# question_queue.validate_question() outright, with a caller-supplied q_id
# and a hardcoded blocking=True)
# ===========================================================================

_T4_OPTIONS = [
    {"label": "bind to phy0 (generate-loop index 0)"},
    {"label": "bind to phy1 (generate-loop index 1)"},
]


def _ask_t4(root, **overrides):
    kwargs = dict(
        domain="dut",
        question="Which DUT instance does the second USB3 PHY VIP bind to -- phy0 or phy1?",
        context_path="chip.core.usb_subsys.phy_array[*]",
        options=_T4_OPTIONS,
        recommendation="bind to phy0 (generate-loop index 0)",
        assumption_if_unanswered="assume phy0; re-run connectivity check once designer confirms",
    )
    kwargs.update(overrides)
    return conn.build_t4_question_queue_entry(root, **kwargs)


def test_build_t4_question_queue_entry_output_passes_real_validate_question(tmp_path):
    """The whole point of the F6 fix: the entry this produces is a record the
    REAL question queue accepted, not a look-alike dict."""
    from dv_harness import question_queue as qq

    entry = _ask_t4(tmp_path)
    qq.validate_question(entry)  # raises QuestionValidationError if it does not conform
    assert entry["owner"] == "designer"  # DUT-domain -> designer, via route_owner()


def test_build_t4_question_queue_entry_id_is_derived_not_caller_supplied(tmp_path):
    """No q_id parameter exists any more -- the id is derived from the
    question key, which is what keeps repeat-question-rate=0 provable."""
    from dv_harness import question_queue as qq

    assert "q_id" not in inspect.signature(conn.build_t4_question_queue_entry).parameters
    entry = _ask_t4(tmp_path)
    key = qq.make_question_key("dut", entry["question"], entry["context_path"])
    assert entry["id"] == qq.make_question_id("dut", key)
    # Asking the identical question again derives the identical id.
    assert _ask_t4(tmp_path)["id"] == entry["id"]


def test_build_t4_question_queue_entry_blocking_is_derived_from_tier_classification(tmp_path):
    """`blocking` used to be a hardcoded True default. It is now whatever the
    queue's own classify_tier() derives -- Tier 3 for a T4 bind question,
    because guessing a bind target is a real false-PASS risk."""
    entry = _ask_t4(tmp_path)
    assert entry["tier"] == 3
    assert entry["blocking"] is True
    assert entry["status"] == "OPEN"
    assert "affects_pass_fail_verdict" in entry["tier_reason"]


def test_build_t4_question_queue_entry_is_really_persisted_in_the_queue(tmp_path):
    from dv_harness import question_queue as qq

    entry = _ask_t4(tmp_path)
    store = qq.QuestionQueueStore(tmp_path)
    assert store.get_question(entry["id"]) == entry


def test_build_t4_question_queue_entry_accepts_a_prebuilt_store(tmp_path):
    from dv_harness import question_queue as qq

    store = qq.QuestionQueueStore(tmp_path)
    entry = _ask_t4(store)
    assert store.get_question(entry["id"]) is not None


def test_build_t4_question_queue_entry_routes_vip_domain_to_dv_owner_synopsys_ae(tmp_path):
    entry = _ask_t4(tmp_path, domain="vip")
    assert entry["owner"] == "DV-owner/Synopsys-AE"


def test_build_t4_question_queue_entry_rejects_open_ended_options(tmp_path):
    with pytest.raises(conn.ConnectivityError) as exc:
        _ask_t4(tmp_path, options=[{"label": "only_one_option"}],
                recommendation="only_one_option")
    assert exc.value.reason == "OPTIONS_MUST_BE_PRE_RESEARCHED_2_TO_3"


def test_build_t4_question_queue_entry_rejects_unknown_domain(tmp_path):
    with pytest.raises(conn.ConnectivityError) as exc:
        _ask_t4(tmp_path, domain="not_a_domain")
    assert exc.value.reason == "UNKNOWN_QUESTION_DOMAIN"


def test_build_t4_question_queue_entry_rejects_recommendation_outside_options(tmp_path):
    with pytest.raises(conn.ConnectivityError) as exc:
        _ask_t4(tmp_path, recommendation="bind to some third thing nobody listed")
    assert exc.value.reason == "RECOMMENDATION_MUST_BE_ONE_OF_OPTIONS"


def test_build_t4_question_queue_entry_accepts_plain_string_options(tmp_path):
    """Plain strings are normalized to the queue's {"label": ...} shape."""
    entry = _ask_t4(tmp_path, options=["bind to phy0", "bind to phy1"],
                    recommendation="bind to phy0")
    assert entry["options"] == [{"label": "bind to phy0"}, {"label": "bind to phy1"}]
