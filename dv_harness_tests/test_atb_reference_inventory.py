"""Tests for dv_harness/atb_reference_inventory.py.

Two fixture families, deliberately, mirroring `test_syoscb_source_audit.py`'s
own convention:

  * A SYNTHETIC ATB-shaped tree written to `tmp_path` for every core-logic
    assertion (duplicate detection, subsystem scoping, the reuse-then-block
    rule, drift detection, malformed-input refusals) -- so each one is a
    check with real detection power over a fixture built to exercise it,
    never a fixture shaped to please the module.
  * The REAL ATB tree at `D:/DV/Task/DV_Agent_Harness_L5/ATB`, audited
    read-only when present (skipped otherwise, so this suite still passes
    on a machine without it -- the same `@real_source`-style guard
    `test_syoscb_source_audit.py` already uses). Those tests assert facts
    independently verified by hand against the real tree (a real, present,
    unreferenced-outside-its-own-directory SyoSil scoreboard under
    `soc/uvc/scb/`; a real content drift between that copy and this
    project's own already-approved vendored `reference/uvm_syoscb-1.0.2.4`
    copy; a real file -- `cl_syoscb_report_catcher.svh` -- present ONLY in
    the vendored copy and absent from ATB itself) -- so the module is
    proven against the real tree it names, not only against a fixture
    shaped to please it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import atb_reference_inventory as ari

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_ATB_ROOT = Path(__file__).resolve().parents[2] / "ATB"
real_source = pytest.mark.skipif(
    not REAL_ATB_ROOT.is_dir(),
    reason=f"the real ATB reference tree {REAL_ATB_ROOT} is not present on this machine")
real_atb_vendoring_approval = pytest.mark.skipif(
    not (REPO_ROOT / "dv_harness" / "atb_vendoring_approval.json").is_file(),
    reason="no real ATB-itself vendoring-approval record exists yet in this checkout")


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_atb_fixture(root: Path) -> Path:
    """A small, ATB-shaped tree with the exact real-world properties this
    module's classification logic has to get right: a bind interface that
    IS `` `include ``d from a bench top file (so it must read
    IMPLEMENTED_UNPROVEN), a scoreboard family that is internally
    self-consistent but referenced by NOTHING outside its own `scb/`
    directory (so it must read PRESENT_UNUSED, matching the real ATB
    tree's own scoreboard), a genuine same-subsystem class-name collision
    (DUPLICATE), and the identical bind-interface basename intentionally
    duplicated across the `coretop` and `soc` subsystems (which must NOT
    be flagged DUPLICATE -- that is by design, not a defect)."""
    atb = root / "ATB"

    _write(atb / "coretop" / "uvc" / "bind" / "user_svt_apb_master_bind_if.svi",
           "interface svt_apb_master_bind_if(); endinterface\n")
    _write(atb / "coretop" / "uvc" / "cb" / "cust_apb_master_monitor_callback.sv",
           "class cust_apb_master_monitor_callback extends uvm_callback;\n"
           "endclass\n")
    _write(atb / "coretop" / "uvc" / "coretop_virtual_sequencer.sv",
           "class coretop_virtual_sequencer extends uvm_sequencer;\n"
           "  cust_apb_master_monitor_callback cb;\n"
           "endclass\n")

    _write(atb / "soc" / "uvc" / "bind" / "user_svt_apb_master_bind_if.svi",
           "interface svt_apb_master_bind_if(); endinterface\n")
    _write(atb / "soc" / "bench" / "uvm_soc_tb.sv",
           "module uvm_soc_tb;\n"
           '  `include "user_svt_apb_master_bind_if.svi"\n'
           "endmodule\n")

    _write(atb / "soc" / "uvc" / "scb" / "cl_fakescb_queue_base.svh",
           "class cl_fakescb_queue_base extends uvm_object;\n"
           "  extern virtual function bit add_item(uvm_sequence_item item);\n"
           "endclass\n")
    _write(atb / "soc" / "uvc" / "scb" / "cl_fakescb_queue_std.svh",
           "class cl_fakescb_queue_std extends cl_fakescb_queue_base;\n"
           "  extern function new(string name);\n"
           "endclass\n")

    # A genuine, same-subsystem name collision -- two DIFFERENT files, both
    # under "soc", both declaring `class cl_dup_widget`.
    _write(atb / "soc" / "uvc" / "cl_dup_widget_a.sv",
           "class cl_dup_widget extends uvm_object;\nendclass\n")
    _write(atb / "soc" / "uvc" / "cl_dup_widget_b.sv",
           "class cl_dup_widget extends uvm_component;\nendclass\n")

    return atb


# ---------------------------------------------------------------------------
# discover_atb_capabilities: core discovery + classification
# ---------------------------------------------------------------------------

def test_root_not_found_raises(tmp_path):
    with pytest.raises(ari.AtbReferenceInventoryError) as exc:
        ari.discover_atb_capabilities(tmp_path / "does_not_exist")
    assert exc.value.code == "ATB_ROOT_NOT_FOUND"


def test_bind_interface_wired_in_is_implemented_unproven(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    soc_bind = [c for c in m.capabilities
                if c.kind == ari.KIND_BIND_INTERFACE and c.subsystem == "soc"]
    assert len(soc_bind) == 1
    assert soc_bind[0].status == ari.STATUS_IMPLEMENTED_UNPROVEN
    assert soc_bind[0].referenced_elsewhere is True


def test_scoreboard_family_unreferenced_outside_its_own_dir_is_present_unused(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    scb = [c for c in m.capabilities if c.kind == ari.KIND_SCOREBOARD_COMPONENT]
    assert len(scb) == 2
    # Both scb classes reference each other WITHIN scb/ (extends), but
    # nothing OUTSIDE scb/ ever references either -- so both must read
    # PRESENT_UNUSED, never IMPLEMENTED_UNPROVEN on the strength of their
    # own sibling's extends alone.
    for cap in scb:
        assert cap.status == ari.STATUS_PRESENT_UNUSED, cap.to_dict()
        assert cap.referenced_elsewhere is False


def test_same_subsystem_name_collision_is_duplicate(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    dups = m.capability_named("cl_dup_widget")
    assert len(dups) == 2
    for cap in dups:
        assert cap.status == ari.STATUS_DUPLICATE
        assert "cl_dup_widget" in cap.status_evidence
        assert "soc" in cap.status_evidence


def test_cross_subsystem_same_basename_is_not_duplicate(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    bind = m.capability_named("svt_apb_master_bind_if")
    assert len(bind) == 2
    assert {c.subsystem for c in bind} == {"coretop", "soc"}
    for cap in bind:
        assert cap.status != ari.STATUS_DUPLICATE


def test_module_discovery_disabled_reports_not_available_with_reason(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    assert m.module_discovery_status == "NOT_AVAILABLE"
    assert m.module_discovery_reason


def test_module_discovery_reports_not_available_when_verible_module_missing(tmp_path, monkeypatch):
    atb = _build_atb_fixture(tmp_path)
    monkeypatch.setattr(ari, "verible_parser", None)
    m = ari.discover_atb_capabilities(atb, use_verible=True)
    assert m.module_discovery_status == "NOT_AVAILABLE"
    assert "not importable" in m.module_discovery_reason


def test_module_discovery_reports_not_available_when_binary_missing(tmp_path, monkeypatch):
    atb = _build_atb_fixture(tmp_path)
    monkeypatch.setattr(ari.verible_parser, "get_verible_version", lambda *_a, **_k: None)
    m = ari.discover_atb_capabilities(atb, use_verible=True,
                                       verible_bin="definitely-not-a-real-binary")
    assert m.module_discovery_status == "NOT_AVAILABLE"
    assert "not found on PATH" in m.module_discovery_reason


def test_cross_tool_name_ambiguity_is_unknown(tmp_path):
    """A name verible reports as a MODULE that vip_symbol_index ALSO
    reports as a CLASS somewhere in the tree is genuinely UNKNOWN -- two
    independent structural scans disagreeing about what the name is,
    never resolved by picking one."""
    root = tmp_path / "ambig"
    _write(root / "soc" / "uvc" / "seq" / "ambiguous_thing.sv",
           "class ambiguous_thing extends uvm_object;\nendclass\n")
    _write(root / "soc" / "bench" / "ambiguous_thing_top.sv",
           "module ambiguous_thing;\nendmodule\n")
    m = ari.discover_atb_capabilities(root, use_verible=True)
    hits = m.capability_named("ambiguous_thing")
    assert len(hits) == 2
    for cap in hits:
        assert cap.status == ari.STATUS_UNKNOWN
        assert "ambiguous" in cap.status_evidence.lower()


# ---------------------------------------------------------------------------
# assert_source_unmodified
# ---------------------------------------------------------------------------

def test_assert_source_unmodified_passes_on_untouched_tree(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    ari.assert_source_unmodified(m)  # must not raise


def test_assert_source_unmodified_raises_on_content_change(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    target = atb / "soc" / "uvc" / "scb" / "cl_fakescb_queue_std.svh"
    target.write_text(target.read_text(encoding="utf-8") + "\n// mutated\n", encoding="utf-8")
    with pytest.raises(ari.AtbReferenceInventoryError) as exc:
        ari.assert_source_unmodified(m)
    assert exc.value.code == "ATB_SOURCE_MODIFIED_DURING_AUDIT"


def test_assert_source_unmodified_raises_on_deleted_file(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    (atb / "soc" / "uvc" / "scb" / "cl_fakescb_queue_std.svh").unlink()
    with pytest.raises(ari.AtbReferenceInventoryError) as exc:
        ari.assert_source_unmodified(m)
    assert exc.value.code == "ATB_SOURCE_DISAPPEARED_DURING_AUDIT"


# ---------------------------------------------------------------------------
# apply_proof_evidence
# ---------------------------------------------------------------------------

def test_apply_proof_evidence_promotes_only_with_real_citation(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    promoted = ari.apply_proof_evidence(m, {
        "cl_fakescb_queue_std": "job_id=42, evidence.duckdb normalized_evidence row, PASS",
        "cl_dup_widget": "an unearned attempt to promote a DUPLICATE",
        "cust_apb_master_monitor_callback": "   ",  # blank after strip -- refused
    })
    proven = promoted.capability_named("cl_fakescb_queue_std")[0]
    assert proven.status == ari.STATUS_PROVEN
    assert "job_id=42" in proven.status_evidence

    # A DUPLICATE is never promoted, even with a citation -- the ambiguity
    # itself must be resolved first.
    for cap in promoted.capability_named("cl_dup_widget"):
        assert cap.status == ari.STATUS_DUPLICATE

    cb = promoted.capability_named("cust_apb_master_monitor_callback")[0]
    assert cb.status != ari.STATUS_PROVEN

    # The original manifest's own capability objects are untouched.
    original = m.capability_named("cl_fakescb_queue_std")[0]
    assert original.status == ari.STATUS_PRESENT_UNUSED


def test_apply_proof_evidence_is_a_no_op_on_empty_input(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    same = ari.apply_proof_evidence(m, {})
    assert same is m


# ---------------------------------------------------------------------------
# evaluate_expected_capabilities
# ---------------------------------------------------------------------------

def test_evaluate_expected_capabilities_requires_a_real_declared_list(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    with pytest.raises(ari.AtbReferenceInventoryError) as exc:
        ari.evaluate_expected_capabilities(m, [])
    assert exc.value.code == "NO_EXPECTED_CAPABILITIES_DECLARED"


def test_evaluate_expected_capabilities_complete(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    result = ari.evaluate_expected_capabilities(m, ["cl_fakescb_queue_std", "cl_fakescb_queue_base"])
    assert result["family_status"] == "COMPLETE"
    assert result["missing"] == []


def test_evaluate_expected_capabilities_partial(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    result = ari.evaluate_expected_capabilities(
        m, ["cl_fakescb_queue_std", "cl_fakescb_nonexistent"])
    assert result["family_status"] == ari.STATUS_PARTIAL
    assert result["present"] == ["cl_fakescb_queue_std"]
    assert [mc.name for mc in result["missing"]] == ["cl_fakescb_nonexistent"]
    assert "not discovered" in result["missing"][0].reason


def test_evaluate_expected_capabilities_missing(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    result = ari.evaluate_expected_capabilities(m, ["totally_absent_one", "totally_absent_two"])
    assert result["family_status"] == "MISSING"
    assert result["present"] == []
    assert len(result["missing"]) == 2


# ---------------------------------------------------------------------------
# find_project_vendoring_approval_records
# ---------------------------------------------------------------------------

def test_find_project_vendoring_approval_records_none_when_no_dv_harness_dir(tmp_path):
    assert ari.find_project_vendoring_approval_records(tmp_path) == []


def test_find_project_vendoring_approval_records_reads_real_records(tmp_path):
    _write(tmp_path / "dv_harness" / "fake_vendoring_approval.json", json.dumps({
        "approved": True, "component": "fakescb", "l5_destination": "reference/fakescb",
        "source_reference": "some/upstream/path"}))
    records = ari.find_project_vendoring_approval_records(tmp_path)
    assert len(records) == 1
    assert records[0]["component"] == "fakescb"
    assert records[0]["_approval_file"].endswith("fake_vendoring_approval.json")


def test_find_project_vendoring_approval_records_raises_on_invalid_json(tmp_path):
    _write(tmp_path / "dv_harness" / "broken_vendoring_approval.json", "{not valid json")
    with pytest.raises(ari.AtbReferenceInventoryError) as exc:
        ari.find_project_vendoring_approval_records(tmp_path)
    assert exc.value.code == "VENDORING_APPROVAL_UNREADABLE"


def test_find_project_vendoring_approval_records_raises_on_malformed_shape(tmp_path):
    _write(tmp_path / "dv_harness" / "shapeless_vendoring_approval.json",
           json.dumps({"component": "x"}))
    with pytest.raises(ari.AtbReferenceInventoryError) as exc:
        ari.find_project_vendoring_approval_records(tmp_path)
    assert exc.value.code == "VENDORING_APPROVAL_MALFORMED"


# ---------------------------------------------------------------------------
# atb_vendoring_approval_status
# ---------------------------------------------------------------------------

def test_atb_vendoring_approval_status_honestly_absent(tmp_path):
    atb_root = tmp_path / "ATB"
    atb_root.mkdir()
    _write(tmp_path / "dv_harness" / "syoscb_vendoring_approval.json", json.dumps({
        "approved": True, "component": "uvm_syoscb", "l5_destination": "reference/uvm_syoscb",
        "source_reference": str(tmp_path / "unrelated_upstream")}))
    status = ari.atb_vendoring_approval_status(tmp_path, atb_root)
    assert status["approved"] is False
    assert "no vendoring-approval record" in status["reason"]


def test_atb_vendoring_approval_status_honestly_present(tmp_path):
    atb_root = tmp_path / "ATB"
    atb_root.mkdir()
    _write(tmp_path / "dv_harness" / "atb_vendoring_approval.json", json.dumps({
        "approved": True, "component": "ATB", "l5_destination": "reference/ATB",
        "source_reference": str(atb_root)}))
    status = ari.atb_vendoring_approval_status(tmp_path, atb_root)
    assert status["approved"] is True
    assert status["record"]["component"] == "ATB"


def test_atb_vendoring_approval_status_unapproved_record_never_counts(tmp_path):
    atb_root = tmp_path / "ATB"
    atb_root.mkdir()
    _write(tmp_path / "dv_harness" / "atb_vendoring_approval.json", json.dumps({
        "approved": False, "component": "ATB", "l5_destination": "reference/ATB",
        "source_reference": str(atb_root)}))
    status = ari.atb_vendoring_approval_status(tmp_path, atb_root)
    assert status["approved"] is False


# ---------------------------------------------------------------------------
# The literal reuse-then-block rule
# ---------------------------------------------------------------------------

def _vendored_reference_fixture(tmp_path):
    """A project_root carrying one real approved vendoring record whose
    `l5_destination` holds a `cl_fakescb_report_catcher` class ATB itself
    does NOT have, plus a `cl_fakescb_queue_std` whose content DIFFERS
    from ATB's own copy of the same name (for drift/STALE detection)."""
    project_root = tmp_path / "project"
    _write(project_root / "dv_harness" / "fakescb_vendoring_approval.json", json.dumps({
        "approved": True, "component": "fakescb", "l5_destination": "reference/fakescb",
        "source_reference": "D:/some/upstream/fakescb"}))
    _write(project_root / "reference" / "fakescb" / "cl_fakescb_report_catcher.svh",
           "class cl_fakescb_report_catcher extends uvm_report_catcher;\nendclass\n")
    _write(project_root / "reference" / "fakescb" / "cl_fakescb_queue_std.svh",
           "class cl_fakescb_queue_std extends cl_fakescb_queue_upstream_base;\n"
           "  // upstream implementation differs from ATB's own copy\n"
           "endclass\n")
    return project_root


def test_resolve_capability_reuse_prefers_local_atb(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    project_root = _vendored_reference_fixture(tmp_path)
    approvals = ari.find_project_vendoring_approval_records(project_root)
    result = ari.resolve_capability_reuse("cl_fakescb_queue_std", m, approvals, project_root)
    assert result["resolution"] == ari.RESOLUTION_REUSE_LOCAL
    assert "cl_fakescb_queue_std.svh" in result["citation"]


def test_resolve_capability_reuse_falls_back_to_approved_vendored_copy(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    project_root = _vendored_reference_fixture(tmp_path)
    approvals = ari.find_project_vendoring_approval_records(project_root)
    result = ari.resolve_capability_reuse("cl_fakescb_report_catcher", m, approvals, project_root)
    assert result["resolution"] == ari.RESOLUTION_REUSE_VENDORED
    assert "cl_fakescb_report_catcher.svh" in result["citation"]
    assert result["approval_file"].endswith("fakescb_vendoring_approval.json")


def test_resolve_capability_reuse_blocked_when_nothing_has_it(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    project_root = _vendored_reference_fixture(tmp_path)
    approvals = ari.find_project_vendoring_approval_records(project_root)
    result = ari.resolve_capability_reuse("cl_totally_nonexistent_widget", m, approvals, project_root)
    assert result["resolution"] == ari.RESOLUTION_BLOCKED
    assert str(atb).replace("\\", "/") in result["checked_locations"][0] or \
        m.root in result["checked_locations"]
    assert "reference/fakescb" in " ".join(result["checked_locations"])


def test_resolve_capability_reuse_blocked_with_zero_approval_records(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    result = ari.resolve_capability_reuse("cl_totally_nonexistent_widget", m, [], tmp_path)
    assert result["resolution"] == ari.RESOLUTION_BLOCKED
    assert result["checked_locations"] == [m.root]


def test_resolve_capability_reuse_ignores_unapproved_records(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    project_root = tmp_path / "project2"
    _write(project_root / "dv_harness" / "draft_vendoring_approval.json", json.dumps({
        "approved": False, "component": "fakescb", "l5_destination": "reference/fakescb",
        "source_reference": "D:/some/upstream/fakescb"}))
    _write(project_root / "reference" / "fakescb" / "cl_fakescb_report_catcher.svh",
           "class cl_fakescb_report_catcher extends uvm_report_catcher;\nendclass\n")
    approvals = ari.find_project_vendoring_approval_records(project_root)
    result = ari.resolve_capability_reuse("cl_fakescb_report_catcher", m, approvals, project_root)
    assert result["resolution"] == ari.RESOLUTION_BLOCKED


# ---------------------------------------------------------------------------
# evaluate_drift_against_vendored (STALE)
# ---------------------------------------------------------------------------

def test_evaluate_drift_against_vendored_flags_stale_on_real_content_difference(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    project_root = _vendored_reference_fixture(tmp_path)
    approvals = ari.find_project_vendoring_approval_records(project_root)
    # KNOWN_VENDORED_FAMILIES keys on the real "cl_syoscb" prefix; extend it
    # for this fixture's own "cl_fakescb" family without touching the
    # module-level constant other tests rely on.
    families = dict(ari.KNOWN_VENDORED_FAMILIES)
    families["FAKESCB"] = {"dir_marker": "scb", "name_prefix": "cl_fakescb"}
    orig = ari.KNOWN_VENDORED_FAMILIES
    ari.KNOWN_VENDORED_FAMILIES = families
    try:
        drift = ari.evaluate_drift_against_vendored(m, approvals, project_root)
    finally:
        ari.KNOWN_VENDORED_FAMILIES = orig
    stale = [d for d in drift if d["status"] == ari.STATUS_STALE]
    assert len(stale) == 1
    assert stale[0]["capability"] == "cl_fakescb_queue_std"
    assert "differs from" in stale[0]["evidence"]


def test_evaluate_drift_against_vendored_reports_match_when_identical(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    project_root = tmp_path / "project3"
    _write(project_root / "dv_harness" / "fakescb_vendoring_approval.json", json.dumps({
        "approved": True, "component": "fakescb", "l5_destination": "reference/fakescb",
        "source_reference": "D:/some/upstream/fakescb"}))
    identical_text = (atb / "soc" / "uvc" / "scb" / "cl_fakescb_queue_std.svh").read_text(
        encoding="utf-8")
    _write(project_root / "reference" / "fakescb" / "cl_fakescb_queue_std.svh", identical_text)
    approvals = ari.find_project_vendoring_approval_records(project_root)
    families = dict(ari.KNOWN_VENDORED_FAMILIES)
    families["FAKESCB"] = {"dir_marker": "scb", "name_prefix": "cl_fakescb"}
    orig = ari.KNOWN_VENDORED_FAMILIES
    ari.KNOWN_VENDORED_FAMILIES = families
    try:
        drift = ari.evaluate_drift_against_vendored(m, approvals, project_root)
    finally:
        ari.KNOWN_VENDORED_FAMILIES = orig
    assert all(d["status"] == "MATCHES_VENDORED_COPY" for d in drift
               if d["capability"] == "cl_fakescb_queue_std")


def test_evaluate_drift_against_vendored_empty_when_no_family_matches(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    project_root = _vendored_reference_fixture(tmp_path)
    approvals = ari.find_project_vendoring_approval_records(project_root)
    # Real KNOWN_VENDORED_FAMILIES only recognizes "cl_syoscb", so this
    # fixture's "cl_fakescb" family matches nothing without the monkeypatch
    # the two tests above apply.
    drift = ari.evaluate_drift_against_vendored(m, approvals, project_root)
    assert drift == []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_inventory_report_produces_readable_text(tmp_path):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    vs = ari.atb_vendoring_approval_status(tmp_path, atb)
    text = ari.render_inventory_report(m, vendoring_status=vs)
    assert "ATB REFERENCE INVENTORY" in text
    assert "cl_fakescb_queue_std" in text
    assert "STATUS COUNTS" in text


def test_render_capability_table_degrades_honestly_without_connectivity(tmp_path, monkeypatch):
    atb = _build_atb_fixture(tmp_path)
    m = ari.discover_atb_capabilities(atb, use_verible=False)
    monkeypatch.setattr(ari, "render_markdown_table", None)
    text = ari.render_capability_table(m)
    assert "not importable" in text


# ---------------------------------------------------------------------------
# Real ATB tree (read-only, guarded)
# ---------------------------------------------------------------------------

@real_source
def test_real_atb_tree_discovers_capabilities():
    m = ari.discover_atb_capabilities(REAL_ATB_ROOT, use_verible=False)
    assert len(m.files) > 0
    assert len(m.capabilities) > 0
    ari.assert_source_unmodified(m)  # this audit really is read-only


@real_source
def test_real_atb_scoreboard_family_is_present_unused():
    """Independently confirmed by hand (`grep -rln syoscb ATB/soc/uvc/*.sv
    ATB/soc/bench/*.sv ATB/coretop/bench/*.sv` returns nothing): the real,
    vendored-looking SyoSil scoreboard under `soc/uvc/scb/` is present and
    internally self-consistent, but genuinely referenced by NOTHING outside
    its own directory in this real tree -- so every one of its real,
    discovered components must read PRESENT_UNUSED, never
    IMPLEMENTED_UNPROVEN on the strength of its own internal extends chain
    alone."""
    m = ari.discover_atb_capabilities(REAL_ATB_ROOT, use_verible=False)
    scb = m.capabilities_with_status(ari.STATUS_PRESENT_UNUSED)
    scb = [c for c in scb if c.kind == ari.KIND_SCOREBOARD_COMPONENT]
    assert len(scb) > 10
    all_scb = [c for c in m.capabilities if c.kind == ari.KIND_SCOREBOARD_COMPONENT]
    assert all(c.status == ari.STATUS_PRESENT_UNUSED for c in all_scb)


@real_source
def test_real_atb_bind_interfaces_wired_in_are_implemented_unproven():
    """Independently confirmed by hand: `soc/bench/uvm_soc_tb.sv` really
    `` `include ``s `user_svt_apb_master_bind_if.svi`, so that real bind
    interface really is IMPLEMENTED_UNPROVEN, not PRESENT_UNUSED."""
    m = ari.discover_atb_capabilities(REAL_ATB_ROOT, use_verible=False)
    hits = [c for c in m.capabilities
            if c.name == "svt_apb_master_bind_if" and c.subsystem == "soc"]
    assert hits
    assert all(c.status == ari.STATUS_IMPLEMENTED_UNPROVEN for c in hits)


@real_source
def test_real_atb_scoreboard_reuse_falls_back_to_this_projects_own_vendored_copy():
    """`cl_syoscb_report_catcher` is real and present under this project's
    OWN already-approved `reference/uvm_syoscb-1.0.2.4/src/` (independently
    confirmed: `comm -23` against ATB's own `soc/uvc/scb/*.svh` file list
    names it as one of exactly two files ATB genuinely lacks), so resolving
    it must fall back to REUSE_VENDORED, never BLOCKED, and never a
    fabricated local hit."""
    m = ari.discover_atb_capabilities(REAL_ATB_ROOT, use_verible=False)
    assert m.capability_named("cl_syoscb_report_catcher") == []
    approvals = ari.find_project_vendoring_approval_records(REPO_ROOT)
    result = ari.resolve_capability_reuse(
        "cl_syoscb_report_catcher", m, approvals, REPO_ROOT)
    assert result["resolution"] == ari.RESOLUTION_REUSE_VENDORED
    assert "uvm_syoscb-1.0.2.4" in result["citation"]


@real_source
def test_real_atb_scoreboard_reuse_prefers_local_when_atb_has_it():
    m = ari.discover_atb_capabilities(REAL_ATB_ROOT, use_verible=False)
    assert m.capability_named("cl_syoscb_queue_std")
    approvals = ari.find_project_vendoring_approval_records(REPO_ROOT)
    result = ari.resolve_capability_reuse("cl_syoscb_queue_std", m, approvals, REPO_ROOT)
    assert result["resolution"] == ari.RESOLUTION_REUSE_LOCAL


@real_source
def test_real_atb_scoreboard_content_has_drifted_from_this_projects_own_vendored_copy():
    """Independently confirmed by hand (`diff
    reference/uvm_syoscb-1.0.2.4/src/cl_syoscb_queue_std.svh
    ATB/soc/uvc/scb/cl_syoscb_queue_std.svh`): the two real files genuinely
    differ (different copyright year, a different base class name). This
    is the module's real STALE finding, over real evidence, with no
    fixture involved."""
    m = ari.discover_atb_capabilities(REAL_ATB_ROOT, use_verible=False)
    approvals = ari.find_project_vendoring_approval_records(REPO_ROOT)
    drift = ari.evaluate_drift_against_vendored(m, approvals, REPO_ROOT)
    stale = [d for d in drift if d["capability"] == "cl_syoscb_queue_std"]
    assert stale, "expected a real drift finding for cl_syoscb_queue_std"
    assert stale[0]["status"] == ari.STATUS_STALE


@real_source
def test_real_atb_totally_absent_capability_is_blocked():
    m = ari.discover_atb_capabilities(REAL_ATB_ROOT, use_verible=False)
    approvals = ari.find_project_vendoring_approval_records(REPO_ROOT)
    result = ari.resolve_capability_reuse(
        "cl_this_capability_does_not_exist_anywhere", m, approvals, REPO_ROOT)
    assert result["resolution"] == ari.RESOLUTION_BLOCKED
    assert "not found in ATB" in result["reason"]


@real_source
def test_real_atb_vendoring_approval_status_is_grounded_in_real_files():
    """This module never creates an approval record -- it only ever reads
    real ones on disk. Whatever the real, current answer is (approved or
    not), the reason it gives must be grounded in real files it actually
    checked."""
    status = ari.atb_vendoring_approval_status(REPO_ROOT, REAL_ATB_ROOT)
    assert isinstance(status["approved"], bool)
    assert status["reason"]
    if status["approved"]:
        assert status["record"] is not None
        assert Path(status["record"]["_approval_file"]).is_file()


@real_source
@real_atb_vendoring_approval
def test_real_atb_vendoring_approval_is_honestly_reported_present():
    """This project's own real, on-disk approval record for vendoring ATB
    itself (`dv_harness/atb_vendoring_approval.json`) is read honestly by
    this module, without this module having created it -- the exact same
    read-only boundary `syoscb_source_audit.py`'s own tests hold for the
    upstream SyoSil tree."""
    status = ari.atb_vendoring_approval_status(REPO_ROOT, REAL_ATB_ROOT)
    assert status["approved"] is True
    assert status["record"]["component"] == "ATB"
    assert "atb_vendoring_approval.json" in status["reason"]


@real_source
def test_real_atb_module_kind_discovery_when_verible_is_available():
    """Best-effort module-level discovery over the real tree. Written to
    pass whether or not `verible-verilog-syntax` is on THIS machine's
    PATH -- an honest NOT_AVAILABLE is asserted explicitly rather than the
    test silently doing nothing."""
    m = ari.discover_atb_capabilities(REAL_ATB_ROOT, use_verible=True)
    assert m.module_discovery_status in ("AVAILABLE", "NOT_AVAILABLE")
    if m.module_discovery_status == "AVAILABLE":
        connectors = [c for c in m.capabilities if c.kind == ari.KIND_CONNECTOR_MODULE]
        assert len(connectors) > 0
    else:
        assert m.module_discovery_reason


@real_source
def test_real_atb_cli_module_is_importable_and_report_renders():
    m = ari.discover_atb_capabilities(REAL_ATB_ROOT, use_verible=False)
    vs = ari.atb_vendoring_approval_status(REPO_ROOT, REAL_ATB_ROOT)
    text = ari.render_inventory_report(m, vendoring_status=vs)
    assert "ATB REFERENCE INVENTORY" in text
    assert str(len(m.capabilities)) in text
