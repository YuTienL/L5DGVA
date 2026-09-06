"""Tests for SYOSCB-1 / SYOSCB-3 (dv_harness/syoscb_source_audit.py, plus the
THIRD_PARTY_COMPONENT_* half of dv_harness/knowledge_center.py).

Two fixture families, deliberately:

  * A SYNTHETIC upstream tree written to tmp_path -- real SystemVerilog class
    source WITH method bodies in it, so `test_no_method_body_text_is_retained`
    is a check with detection power rather than one that never looked. Written
    by this test, never copied from anywhere.
  * A DEGRADED tree that is missing VERSION.txt, LICENSE.txt, RELEASE_NOTES.txt
    and the out-of-order compare class. This project's own hard-won lesson is
    that a happy-path-only mechanism is not coverage: the degraded tree is what
    proves the module reports REQUIRED_HUMAN_INPUT / NOT_FOUND honestly instead
    of only ever succeeding.

The REAL upstream tree at D:/DV/Scoreboard/uvm_syoscb-1.0.2.4 is additionally
audited read-only when present (skipped otherwise, so this suite still runs on
a machine without it). Those tests assert facts that were verified by hand
against the real files -- version 1.0.2.4, a 15-entry include order, three
compare classes, five known limitations -- so the module is proven against the
library SYOSCB-1 actually names, not only against a fixture shaped to please
it. Nothing is copied out of that tree, and `test_real_source_is_not_vendored`
asserts this repository still contains none of it, which is SYOSCB-2/33's
boundary.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import knowledge_center as kc
from dv_harness import syoscb_source_audit as ssa
from dv_harness.connectivity import REQUIRED_HUMAN_INPUT, BindTier

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_SYOSCB_ROOT = Path("D:/DV/Scoreboard/uvm_syoscb-1.0.2.4")
real_source = pytest.mark.skipif(
    not REAL_SYOSCB_ROOT.is_dir(),
    reason=f"the real upstream tree {REAL_SYOSCB_ROOT} is not present on this machine")


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

_PKG = """\
package pk_fakescb;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  `include "cl_fakescb_cfg.svh"
  `include "cl_fakescb_item.svh"
  `include "cl_fakescb_queue.svh"
  `include "cl_fakescb_queue_std.svh"
  `include "cl_fakescb_compare_base.svh"
  `include "cl_fakescb_compare_io.svh"
  `include "cl_fakescb_compare_iop.svh"
  `include "cl_fakescb_compare_ooo.svh"
  `include "cl_fakescb_subscriber.svh"
  `include "cl_fakescb.svh"
endpackage: pk_fakescb
"""

# Method BODIES are present on purpose: they are what makes the
# "no body text is retained" assertion meaningful.
_SOURCES = {
    "cl_fakescb.svh": """\
class cl_fakescb extends uvm_scoreboard;
  `uvm_component_utils_begin(cl_fakescb)
  `uvm_component_utils_end
  extern function void add_item(string queue_name, string producer, uvm_sequence_item item);
  extern function void compare();
endclass: cl_fakescb

function void cl_fakescb::add_item(string queue_name, string producer, uvm_sequence_item item);
  if (this.cfg.exist_queue(queue_name) == 0) begin
    `uvm_fatal("CFG_ERROR", $sformatf("queue %s not found", queue_name))
  end
endfunction : add_item
""",
    "cl_fakescb_cfg.svh": """\
class cl_fakescb_cfg extends uvm_object;
  `uvm_object_utils_begin(cl_fakescb_cfg)
    `uvm_field_aa_object_string(queues, UVM_DEFAULT)
    `uvm_field_string(primary_queue, UVM_DEFAULT)
  `uvm_object_utils_end
  extern function bit set_producer(string producer, string queue_names[]);
  extern function bit exist_producer(string producer);
endclass: cl_fakescb_cfg
""",
    "cl_fakescb_item.svh": """\
`ifdef FAKE_APPLY_TLM_GP_CMP_WORKAROUND
class cl_fakescb_item extends uvm_object;
  extern function string get_producer();
endclass: cl_fakescb_item
`endif
""",
    "cl_fakescb_queue.svh": """\
class cl_fakescb_queue extends uvm_component;
  extern virtual function bit add_item(string producer, uvm_sequence_item item);
  extern virtual function int unsigned get_size();
endclass: cl_fakescb_queue
""",
    "cl_fakescb_queue_std.svh": """\
class cl_fakescb_queue_std extends cl_fakescb_queue;
  extern virtual function bit empty();
endclass: cl_fakescb_queue_std
""",
    "cl_fakescb_compare_base.svh": """\
class cl_fakescb_compare_base extends uvm_object;
  extern virtual function void compare_do();
endclass: cl_fakescb_compare_base
""",
    "cl_fakescb_compare_io.svh": """\
class cl_fakescb_compare_io extends cl_fakescb_compare_base;
endclass: cl_fakescb_compare_io
""",
    "cl_fakescb_compare_iop.svh": """\
class cl_fakescb_compare_iop extends cl_fakescb_compare_base;
endclass: cl_fakescb_compare_iop
""",
    "cl_fakescb_compare_ooo.svh": """\
class cl_fakescb_compare_ooo extends cl_fakescb_compare_base;
endclass: cl_fakescb_compare_ooo
""",
    "cl_fakescb_subscriber.svh": """\
class cl_fakescb_subscriber extends uvm_subscriber#(uvm_sequence_item);
  uvm_analysis_export#(uvm_sequence_item) sb_export;
endclass: cl_fakescb_subscriber
""",
}

_VERSION_TXT = """\
#######################################################################
#   Copyright 2014-2015 Fake Vendor ApS
#   Licensed under the Apache License, Version 2.0
#######################################################################
9.8.7.6
"""

_RELEASE_NOTES = """\
#######################################################################
# [3]: New Features
#######################################################################
  * something

#######################################################################
# [4]: Know Limitations
#######################################################################
The current known limitations for this relase are:

  1. no vmm sequence item
  2. no item timeout knobs
  3. only a standard SystemVerilog queue is supported

#######################################################################
# [5]: Compatibility List
#######################################################################
  * UVM version 1.2
"""


def _write_tree(root: Path, *, complete: bool = True) -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "pk_fakescb.sv").write_text(_PKG, encoding="utf-8")
    for name, text in _SOURCES.items():
        if not complete and name.endswith("_compare_ooo.svh"):
            continue
        (src / name).write_text(text, encoding="utf-8")
    (src / "fakescb_vc.mk").write_text("UVM_VERSION ?= 1.2\n", encoding="utf-8")
    (root / "Makefile").write_text("UVM_VERSION ?= 1.2\nall:\n\techo hi\n", encoding="utf-8")
    (root / "Makefile.vendor.synopsys").write_text("VENDOR := SYNOPSYS\n", encoding="utf-8")

    tb = root / "tb"
    (tb / "test").mkdir(parents=True)
    (tb / "cl_fakescb_env.svh").write_text("// example env\n", encoding="utf-8")
    (tb / "test" / "cl_fakescb_test_io_simple.svh").write_text("// a test\n", encoding="utf-8")

    (root / "docs").mkdir()
    (root / "docs" / "paper.pdf").write_bytes(b"%PDF-1.4 fake\n")
    (root / "README.txt").write_text("directory structure\n", encoding="utf-8")

    if complete:
        (root / "VERSION.txt").write_text(_VERSION_TXT, encoding="utf-8")
        (root / "LICENSE.txt").write_text(
            "Apache License\nVersion 2.0, January 2004\n"
            "Copyright [yyyy] [name of copyright owner]\n", encoding="utf-8")
        (root / "NOTICE.txt").write_text(
            "#\nCopyright (c) 2014 Fake Vendor ApS. All rights reserved.\n", encoding="utf-8")
        (root / "RELEASE_NOTES.txt").write_text(_RELEASE_NOTES, encoding="utf-8")
    return root


@pytest.fixture
def complete_tree(tmp_path) -> Path:
    return _write_tree(tmp_path / "fake_syoscb-9.8.7.6", complete=True)


@pytest.fixture
def degraded_tree(tmp_path) -> Path:
    """No VERSION.txt, no LICENSE/NOTICE, no RELEASE_NOTES, no out-of-order
    compare class. Everything this tree cannot answer must be reported as
    unanswered, never inferred."""
    return _write_tree(tmp_path / "degraded_syoscb", complete=False)


# ---------------------------------------------------------------------------
# SYOSCB-1: the audit itself
# ---------------------------------------------------------------------------

def test_missing_root_raises_rather_than_reporting_an_empty_library(tmp_path):
    with pytest.raises(ssa.SyoscbSourceAuditError) as exc:
        ssa.audit_syoscb_source(tmp_path / "no_such_tree")
    assert exc.value.reason == "SYOSCB_SOURCE_ROOT_NOT_FOUND"


def test_version_skips_the_license_header_comment_block(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    assert audit.version == "9.8.7.6"
    assert audit.version_evidence == "VERSION.txt:5"


def test_license_and_copyright_come_from_real_lines(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    assert audit.license["spdx_id"] == "Apache-2.0"
    assert audit.license["license_file"] == "LICENSE.txt"
    # The NOTICE holder, not the Apache template's "[name of copyright owner]"
    # placeholder line that sits in LICENSE.txt.
    assert audit.license["copyright"].startswith("Copyright (c) 2014 Fake Vendor ApS")
    assert audit.license["copyright_evidence"] == "NOTICE.txt:2"


def test_compile_order_is_the_package_include_sequence_not_sorted(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    order = audit.package["compile_order"]
    assert order[0] == "cl_fakescb_cfg.svh"
    assert order[-1] == "cl_fakescb.svh"
    assert order != sorted(order), "compile order must be source order, not alphabetical"
    # uvm_macros.svh is a UVM dependency, not part of this library's own order.
    assert "uvm_macros.svh" not in order
    assert audit.package["name"] == "pk_fakescb"
    assert audit.uvm_dependency == {"requires_uvm": True, "uvm_version": "1.2",
                                    "evidence": audit.uvm_dependency["evidence"]}
    assert any(e.endswith("Makefile:1") or e.endswith("fakescb_vc.mk:1")
               for e in audit.uvm_dependency["evidence"])


def test_roles_are_structural_where_the_extends_chain_settles_them(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    by_name = {c["name"]: c for c in audit.classes}

    scb = by_name["cl_fakescb"]
    assert scb["role"] == ssa.ROLE_SCOREBOARD_CORE
    assert scb["tier"] == BindTier.T2_STRUCTURAL_MATCH.value

    sub = by_name["cl_fakescb_subscriber"]
    assert sub["role"] == ssa.ROLE_SUBSCRIBER
    assert sub["tier"] == BindTier.T2_STRUCTURAL_MATCH.value

    # Inherited through a real in-tree `extends` edge -- structural, not naming.
    std = by_name["cl_fakescb_queue_std"]
    assert std["role"] == ssa.ROLE_QUEUE
    assert std["tier"] == BindTier.T2_STRUCTURAL_MATCH.value
    assert "extends cl_fakescb_queue" in std["evidence"]


def test_a_role_resting_only_on_a_class_name_stays_t3(complete_tree):
    """`cl_fakescb_queue extends uvm_component` -- nothing structural says
    "queue". This project's tier rule is that such a conclusion is never
    auto-accepted, and the audit must say so rather than quietly promoting it."""
    audit = ssa.audit_syoscb_source(complete_tree)
    by_name = {c["name"]: c for c in audit.classes}
    assert by_name["cl_fakescb_queue"]["tier"] == BindTier.T3_NAMING_HEURISTIC.value
    assert by_name["cl_fakescb_cfg"]["tier"] == BindTier.T3_NAMING_HEURISTIC.value
    assert by_name["cl_fakescb_cfg"]["role"] == ssa.ROLE_CONFIGURATION


def test_iterator_wins_over_queue_when_a_name_carries_both_tokens(tmp_path):
    root = _write_tree(tmp_path / "iter", complete=True)
    (root / "src" / "cl_fakescb_queue_iterator_base.svh").write_text(
        "class cl_fakescb_queue_iterator_base extends uvm_object;\nendclass\n",
        encoding="utf-8")
    audit = ssa.audit_syoscb_source(root)
    entry = audit.class_named("cl_fakescb_queue_iterator_base")
    assert entry["role"] == ssa.ROLE_QUEUE_ITERATOR


def test_compare_algorithms_map_onto_the_scoreboard_plan_ordering_vocabulary(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    assert set(audit.compare_algorithms) == set(ssa.ORDERING_VALUES)
    assert audit.compare_algorithms[ssa.ORDERING_IN_ORDER]["class"] == "cl_fakescb_compare_io"
    assert (audit.compare_algorithms[ssa.ORDERING_IN_ORDER_PER_PRODUCER]["class"]
            == "cl_fakescb_compare_iop")
    assert audit.compare_algorithms[ssa.ORDERING_OUT_OF_ORDER]["class"] == "cl_fakescb_compare_ooo"
    assert ssa.unresolved_orderings(audit) == []
    assert (ssa.compare_class_for_ordering(audit, ssa.ORDERING_IN_ORDER)["class"]
            == "cl_fakescb_compare_io")


def test_producer_api_is_found_from_declarations_not_from_a_class_name(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    sigs = {(p["class"], p["method"]) for p in audit.producer_apis}
    # add_item carries `producer` only in its ARGUMENT list, not its name.
    assert ("cl_fakescb", "add_item") in sigs
    assert ("cl_fakescb_cfg", "set_producer") in sigs
    assert ("cl_fakescb_queue", "add_item") in sigs
    for entry in audit.producer_apis:
        assert entry["file"] and entry["line"] > 0


def test_macros_and_conditional_compile_are_collected(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    assert "uvm_component_utils_begin" in audit.macros["uvm"]
    assert "uvm_field_aa_object_string" in audit.macros["uvm"]
    assert "FAKE_APPLY_TLM_GP_CMP_WORKAROUND" in audit.macros["conditional_compile"]


def test_tests_examples_scripts_and_docs_are_separated(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    assert "tb/test/cl_fakescb_test_io_simple.svh" in audit.tests
    assert "tb/cl_fakescb_env.svh" in audit.examples
    assert "tb/cl_fakescb_env.svh" not in audit.tests
    assert "Makefile" in audit.scripts and "Makefile.vendor.synopsys" in audit.scripts
    assert "src/fakescb_vc.mk" in audit.scripts
    assert "docs/paper.pdf" in audit.documentation
    # A test file must never also be counted as an example.
    assert not (set(audit.tests) & set(audit.examples))


def test_known_limitations_parse_despite_the_upstream_heading_misspelling(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    assert len(audit.known_limitations) == 3
    assert audit.known_limitations[0] == "no vmm sequence item"
    assert audit.known_limitations[-1].startswith("only a standard SystemVerilog queue")


def test_all_sixteen_checklist_items_are_answered_on_a_complete_tree(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    checklist = ssa.audit_checklist(audit)
    assert tuple(checklist) == ssa.AUDIT_ITEMS
    assert ssa.unanswered_audit_items(audit) == []
    for item, row in checklist.items():
        assert row["status"] == ssa.AUDIT_FOUND, item
        assert row["evidence"], item


def test_no_method_body_text_is_retained(complete_tree):
    """The fixture's `add_item` body contains a `begin`, a `$sformatf` call and
    a literal message string. If any of it reached the audit, this is what
    notices.

    The ONE deliberate exception is `_collect_macros()`: it takes macro
    IDENTIFIERS from the whole file, so `uvm_fatal` appears in `macros["uvm"]`
    even though its invocation sits inside a body. That is SYOSCB-1's "macros"
    item, and the identifier alone carries none of the body -- which is exactly
    what the `$sformatf`/message-string assertions below check."""
    audit = ssa.audit_syoscb_source(complete_tree)
    blob = json.dumps(audit.to_dict())
    assert "$sformatf" not in blob
    assert "queue %s not found" not in blob
    assert "exist_queue" not in blob
    assert "uvm_fatal" in audit.macros["uvm"]
    # The macro NAME, never the invocation it came from.
    assert not any("(" in m for m in audit.macros["uvm"])


# ---------------------------------------------------------------------------
# The missing-evidence case -- the half that actually matters
# ---------------------------------------------------------------------------

def test_degraded_tree_reports_required_human_input_never_a_guess(degraded_tree):
    audit = ssa.audit_syoscb_source(degraded_tree)
    assert audit.version == REQUIRED_HUMAN_INPUT
    assert audit.version_evidence == ""
    assert audit.license["spdx_id"] == REQUIRED_HUMAN_INPUT
    assert audit.license["copyright"] == REQUIRED_HUMAN_INPUT
    assert audit.known_limitations == []


def test_degraded_tree_names_exactly_which_checklist_items_are_unanswered(degraded_tree):
    audit = ssa.audit_syoscb_source(degraded_tree)
    unanswered = ssa.unanswered_audit_items(audit)
    assert set(unanswered) == {"license_copyright_provenance", "version_metadata"}
    checklist = ssa.audit_checklist(audit)
    assert checklist["version_metadata"]["status"] == ssa.AUDIT_NOT_FOUND
    # Everything the tree DOES answer still answers -- a degraded tree must not
    # collapse into a blanket "nothing found".
    assert checklist["compile_order"]["status"] == ssa.AUDIT_FOUND
    assert checklist["scoreboard_classes"]["status"] == ssa.AUDIT_FOUND


def test_a_missing_ordering_is_reported_not_substituted(degraded_tree):
    """Silently comparing an out-of-order stream with an in-order algorithm is
    the most expensive substitution this layer could make, so the missing
    ordering must surface as REQUIRED_HUMAN_INPUT with a reason."""
    audit = ssa.audit_syoscb_source(degraded_tree)
    assert ssa.unresolved_orderings(audit) == [ssa.ORDERING_OUT_OF_ORDER]
    resolved = ssa.compare_class_for_ordering(audit, ssa.ORDERING_OUT_OF_ORDER)
    assert resolved["class"] == REQUIRED_HUMAN_INPUT
    assert resolved["reason"] == "NO_UPSTREAM_COMPARE_CLASS_FOR_THIS_ORDERING"
    # The two the tree DOES implement still resolve to real classes.
    assert ssa.compare_class_for_ordering(audit, ssa.ORDERING_IN_ORDER)["class"]
    with pytest.raises(ssa.SyoscbSourceAuditError) as exc:
        ssa.compare_class_for_ordering(audit, "SOMEHOW_ORDERED")
    assert exc.value.reason == "UNKNOWN_ORDERING_VALUE"


def test_degraded_report_renders_and_states_what_is_unanswered(degraded_tree):
    audit = ssa.audit_syoscb_source(degraded_tree)
    text = ssa.render_source_audit_report(audit)
    assert "UNANSWERED ITEMS: " in text
    assert "version_metadata" in text
    assert REQUIRED_HUMAN_INPUT in text


# ---------------------------------------------------------------------------
# The read-only / not-yet-vendored assertions
# ---------------------------------------------------------------------------

def test_assert_source_unmodified_passes_then_catches_a_real_change(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    ssa.assert_source_unmodified(audit)

    (complete_tree / "README.txt").write_text("touched\n", encoding="utf-8")
    with pytest.raises(ssa.SyoscbSourceAuditError) as exc:
        ssa.assert_source_unmodified(audit)
    assert exc.value.reason == "SYOSCB_SOURCE_MODIFIED_DURING_AUDIT"
    assert exc.value.detail["path"].endswith("README.txt")


def test_assert_source_unmodified_catches_a_disappearance(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    (complete_tree / "README.txt").unlink()
    with pytest.raises(ssa.SyoscbSourceAuditError) as exc:
        ssa.assert_source_unmodified(audit)
    assert exc.value.reason == "SYOSCB_SOURCE_DISAPPEARED_DURING_AUDIT"


def test_assert_not_vendored_is_clean_on_a_repo_with_none_of_it(complete_tree, tmp_path):
    audit = ssa.audit_syoscb_source(complete_tree)
    repo = tmp_path / "repo"
    (repo / "dv_harness").mkdir(parents=True)
    (repo / "dv_harness" / "some_module.py").write_text("x = 1\n", encoding="utf-8")
    result = ssa.assert_not_vendored(repo, audit)
    assert result["name_check"] == "CLEAN"
    assert result["content_check"] == "CLEAN"


def test_assert_not_vendored_catches_a_directory_named_like_upstream(tmp_path):
    repo = tmp_path / "repo"
    (repo / "third_party" / "uvm_syoscb-1.0.2.4" / "src").mkdir(parents=True)
    with pytest.raises(ssa.SyoscbSourceAuditError) as exc:
        ssa.assert_not_vendored(repo)
    assert exc.value.reason == "SYOSCB_UPSTREAM_VENDORED_BEFORE_APPROVAL"
    assert any("uvm_syoscb-1.0.2.4" in p for p in exc.value.detail["name_matches"])


def test_assert_not_vendored_catches_a_RENAMED_copy_by_content_digest(complete_tree, tmp_path):
    """The name check alone is evadable by renaming the copy; the digest check
    is what makes the boundary hold. Both detectors exist for this reason."""
    audit = ssa.audit_syoscb_source(complete_tree)
    repo = tmp_path / "repo"
    (repo / "vendor" / "generic_scoreboard").mkdir(parents=True)
    smuggled = repo / "vendor" / "generic_scoreboard" / "cl_fakescb.svh"
    smuggled.write_bytes((complete_tree / "src" / "cl_fakescb.svh").read_bytes())
    with pytest.raises(ssa.SyoscbSourceAuditError) as exc:
        ssa.assert_not_vendored(repo, audit)
    assert exc.value.detail["name_matches"] == []
    assert exc.value.detail["content_matches"] == ["vendor/generic_scoreboard/cl_fakescb.svh"]


def test_assert_not_vendored_without_an_audit_says_the_content_check_did_not_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert ssa.assert_not_vendored(repo)["content_check"] == "NOT_RUN_NO_AUDIT_SUPPLIED"


def test_no_emittable_systemverilog_in_the_module_or_its_artifacts(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    payload = ssa.build_component_registration_payload(audit)
    for label, text in (("report", ssa.render_source_audit_report(audit, payload)),
                        ("class table", ssa.render_class_table(audit)),
                        ("checklist", ssa.render_checklist_table(audit)),
                        ("compare table", ssa.render_compare_algorithm_table(audit))):
        ssa.assert_no_emittable_sv(text, label=label)
    module_src = (REPO_ROOT / "dv_harness" / "syoscb_source_audit.py").read_text(
        encoding="utf-8")
    assert "bind " not in module_src.replace("bind statement", "").replace(
        "a bind ", "").replace("bind candidate", "")


def test_assert_no_emittable_sv_actually_fires_on_a_class_declaration():
    with pytest.raises(ssa.SyoscbSourceAuditError) as exc:
        ssa.assert_no_emittable_sv("class cl_x extends uvm_scoreboard;\n", label="probe")
    assert exc.value.reason == "SYOSCB_ARTIFACT_CONTAINS_EMITTABLE_SV"
    with pytest.raises(ssa.SyoscbSourceAuditError):
        ssa.assert_no_emittable_sv("bind dut_top mon u_mon(.*);\n", label="probe")


# ---------------------------------------------------------------------------
# SYOSCB-3: the registration payload, built and never published
# ---------------------------------------------------------------------------

def test_registration_payload_uses_the_knowledge_center_field_vocabulary(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    payload = ssa.build_component_registration_payload(audit)
    assert set(kc.THIRD_PARTY_COMPONENT_FIELDS) <= set(payload)
    assert payload["COMPONENT"] == "uvm_syoscb"
    assert payload["VERSION"] == "9.8.7.6"
    assert payload["SOURCE_REFERENCE"] == audit.root
    assert payload["BUILD_STATUS"] == ssa.BUILD_STATUS_NOT_BUILT
    assert payload["KNOWN_LIMITATIONS"] == audit.known_limitations
    assert payload["PROVENANCE"]["spdx_id"] == "Apache-2.0"
    assert payload["PROVENANCE"]["vendored_into_repository"] is False
    assert payload["kind"] == kc.THIRD_PARTY_COMPONENT_KIND


def test_l5_destination_is_required_human_input_until_phase_2_decides_it(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    payload = ssa.build_component_registration_payload(audit)
    assert payload["L5_DESTINATION"] == REQUIRED_HUMAN_INPUT
    assert "L5_DESTINATION" in ssa.registration_blockers(payload)

    decided = ssa.build_component_registration_payload(
        audit, l5_destination="reference/uvm_syoscb-1.0.2.4")
    assert decided["L5_DESTINATION"] == "reference/uvm_syoscb-1.0.2.4"
    assert "L5_DESTINATION" not in ssa.registration_blockers(decided)


def test_registration_blockers_name_every_gap_on_a_degraded_tree(degraded_tree):
    audit = ssa.audit_syoscb_source(degraded_tree)
    payload = ssa.build_component_registration_payload(audit)
    blockers = ssa.registration_blockers(payload)
    assert "VERSION" in blockers
    assert "L5_DESTINATION" in blockers
    assert "KNOWN_LIMITATIONS" in blockers
    assert "PROVENANCE.spdx_id" in blockers
    assert "PROVENANCE.copyright" in blockers
    # Fields the tree really did answer must NOT be listed as blockers.
    assert "COMPONENT" not in blockers and "SOURCE_REFERENCE" not in blockers


def test_building_the_payload_performs_no_transport(complete_tree, monkeypatch):
    """SYOSCB-3 registration is a deliberate, separate act. Building the record
    must never reach the relay -- so any attempt to is made to explode."""
    def explode(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("build_component_registration_payload opened a transport")

    monkeypatch.setattr(kc, "_remote_exec_module", explode)
    audit = ssa.audit_syoscb_source(complete_tree)
    payload = ssa.build_component_registration_payload(audit)
    assert payload["COMPONENT"] == "uvm_syoscb"


def test_registration_evidence_is_bounded_but_says_it_was_truncated(complete_tree):
    """A shared Knowledge Center record must stay readable. Truncation is only
    acceptable if the record says so and carries the real total -- a silently
    shortened list would read as the complete evidence."""
    audit = ssa.audit_syoscb_source(complete_tree)
    for i in range(ssa.MAX_EVIDENCE_CITATIONS_PER_ITEM + 5):
        (complete_tree / "docs" / f"page{i}.html").write_text("<p/>", encoding="utf-8")
    audit = ssa.audit_syoscb_source(complete_tree)
    payload = ssa.build_component_registration_payload(audit)

    docs = payload["EVIDENCE"]["documentation"]
    assert docs["truncated"] is True
    assert len(docs["sample"]) == ssa.MAX_EVIDENCE_CITATIONS_PER_ITEM
    assert docs["total"] == len(audit.documentation) > ssa.MAX_EVIDENCE_CITATIONS_PER_ITEM
    # A short item is kept whole, as a plain list -- not wrapped for no reason.
    assert payload["EVIDENCE"]["version_metadata"] == ["VERSION.txt:5"]
    # The AUDIT itself keeps everything; only the shared record is bounded.
    assert len(ssa.audit_checklist(audit)["documentation"]["evidence"]) == docs["total"]


def test_audit_fingerprint_changes_when_a_file_moves(complete_tree, tmp_path):
    audit = ssa.audit_syoscb_source(complete_tree)
    before = ssa.audit_fingerprint(audit)
    assert before == ssa.audit_fingerprint(ssa.audit_syoscb_source(complete_tree))
    (complete_tree / "src" / "cl_fakescb_compare_io.svh").rename(
        complete_tree / "src" / "cl_fakescb_compare_io_renamed.svh")
    assert ssa.audit_fingerprint(ssa.audit_syoscb_source(complete_tree)) != before


# ---------------------------------------------------------------------------
# knowledge_center.py's THIRD_PARTY_COMPONENT_* half
# ---------------------------------------------------------------------------

def test_component_record_shape_mirrors_the_subsystem_one():
    raw = {"component": "uvm_syoscb", "VERSION": "1.0.2.4", "memory_id": "M-1"}
    norm = kc.normalize_component_record(raw)
    assert norm["COMPONENT"] == "uvm_syoscb"
    assert norm["VERSION"] == "1.0.2.4"
    # Present-and-null, never absent.
    assert "L5_DESTINATION" in norm and norm["L5_DESTINATION"] is None
    assert norm["_kc"]["memory_id"] == "M-1"


def test_record_component_refuses_a_record_nobody_could_look_up():
    client = kc.KnowledgeCenterClient({"knowledge_center": {"enabled": True,
                                                            "remote_root": "/kc"}})
    assert client.record_component({"VERSION": "1.0.2.4"}) == {
        "ok": False, "error": "COMPONENT_REQUIRED"}


def test_record_component_uses_the_existing_add_verb_on_its_own_shard(complete_tree):
    audit = ssa.audit_syoscb_source(complete_tree)
    payload = ssa.build_component_registration_payload(audit)
    client = kc.KnowledgeCenterClient({"knowledge_center": {"enabled": True,
                                                            "remote_root": "/kc"}})
    seen = {}

    def fake_add(category, protocol, record):
        seen.update(category=category, protocol=protocol, record=record)
        return {"ok": True}

    client.add = fake_add  # type: ignore[assignment]
    assert client.record_component(payload, protocol="AMBA4")["ok"] is True
    assert seen["category"] == kc.THIRD_PARTY_COMPONENT_CATEGORY
    assert seen["protocol"] == "AMBA4"
    assert seen["record"]["kind"] == kc.THIRD_PARTY_COMPONENT_KIND
    assert seen["record"]["title"] == "uvm_syoscb 9.8.7.6 third-party component"
    assert set(kc.THIRD_PARTY_COMPONENT_FIELDS) <= set(seen["record"])


def test_component_record_will_not_return_a_substring_match():
    client = kc.KnowledgeCenterClient({"knowledge_center": {"enabled": True,
                                                            "remote_root": "/kc"}})
    client.search = lambda **k: {  # type: ignore[assignment]
        "ok": True, "records": [{"COMPONENT": "uvm_syoscb_amba_adapter"}]}
    res = client.component_record("uvm_syoscb")
    assert res["ok"] is True and res["found"] is False
    assert res["candidates"] == ["uvm_syoscb_amba_adapter"]


def test_an_unconfigured_client_reports_not_configured_rather_than_connecting():
    client = kc.KnowledgeCenterClient({})
    assert client.record_component({"COMPONENT": "uvm_syoscb"})["error"] == "NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# The REAL upstream tree, read-only
# ---------------------------------------------------------------------------

@real_source
def test_real_upstream_version_license_and_class_inventory():
    audit = ssa.audit_syoscb_source(REAL_SYOSCB_ROOT)
    assert audit.version == "1.0.2.4"
    assert audit.version_evidence == "VERSION.txt:19"
    assert audit.license["spdx_id"] == "Apache-2.0"
    assert "SyoSil ApS" in audit.license["copyright"]
    names = {c["name"] for c in audit.classes}
    assert {"cl_syoscb", "cl_syoscb_cfg", "cl_syoscb_cfg_pl", "cl_syoscb_item",
            "cl_syoscb_queue", "cl_syoscb_queue_std", "cl_syoscb_subscriber",
            "cl_syoscb_report_catcher"} <= names
    assert audit.class_named("cl_syoscb")["role"] == ssa.ROLE_SCOREBOARD_CORE
    assert audit.class_named("cl_syoscb")["tier"] == BindTier.T2_STRUCTURAL_MATCH.value
    ssa.assert_source_unmodified(audit)


@real_source
def test_real_upstream_compile_order_and_uvm_dependency():
    audit = ssa.audit_syoscb_source(REAL_SYOSCB_ROOT)
    order = audit.package["compile_order"]
    assert audit.package["name"] == "pk_syoscb"
    assert order[0] == "cl_syoscb_cfg_pl.svh"
    assert order[-1] == "cl_syoscb.svh"
    assert len(order) == 15
    assert audit.uvm_dependency["requires_uvm"] is True
    assert audit.uvm_dependency["uvm_version"] == "1.2"


@real_source
def test_real_upstream_supplies_all_three_orderings_and_five_limitations():
    audit = ssa.audit_syoscb_source(REAL_SYOSCB_ROOT)
    assert ssa.unresolved_orderings(audit) == []
    assert (audit.compare_algorithms[ssa.ORDERING_IN_ORDER_PER_PRODUCER]["class"]
            == "cl_syoscb_compare_iop")
    assert len(audit.known_limitations) == 5
    assert "uvm_sequence_item_vmm" in audit.known_limitations[0]
    assert ssa.unanswered_audit_items(audit) == []


@real_source
def test_real_source_is_vendored_only_under_the_real_approved_destination():
    """SYOSCB-2/SYOSCB-33's boundary, asserted against the live repository:
    the ONLY upstream copy in here is the one a real, on-disk approval
    record names, and it is reported as APPROVED rather than hidden."""
    audit = ssa.audit_syoscb_source(REAL_SYOSCB_ROOT)
    approval = ssa.load_vendoring_approval(REPO_ROOT)
    assert approval is not None
    assert approval["approved"] is True
    result = ssa.assert_not_vendored(REPO_ROOT, audit, approval=approval)
    assert result["name_check"] == "CLEAN"
    assert result["content_check"] == "CLEAN"
    assert result["approved_vendored"], "the real approved copy must be reported, not hidden"


@real_source
def test_an_unapproved_copy_elsewhere_is_still_caught(tmp_path):
    """The approval exempts ONLY its own recorded `l5_destination` -- a second,
    unapproved copy anywhere else in the same repository must still raise."""
    audit = ssa.audit_syoscb_source(REAL_SYOSCB_ROOT)
    approval = ssa.load_vendoring_approval(REPO_ROOT)
    rogue_repo = tmp_path / "repo"
    (rogue_repo / "reference" / "uvm_syoscb-1.0.2.4").mkdir(parents=True)
    (rogue_repo / "reference" / "uvm_syoscb-1.0.2.4" / "VERSION.txt").write_text("1.0.2.4\n")
    # A second, un-approved vendored copy sitting OUTSIDE the approved destination.
    (rogue_repo / "somewhere_else" / "uvm_syoscb_copy").mkdir(parents=True)
    (rogue_repo / "somewhere_else" / "uvm_syoscb_copy" / "VERSION.txt").write_text("1.0.2.4\n")
    with pytest.raises(ssa.SyoscbSourceAuditError) as exc:
        ssa.assert_not_vendored(rogue_repo, audit, approval=approval)
    assert exc.value.reason == "SYOSCB_UPSTREAM_VENDORED_BEFORE_APPROVAL"
    assert any("somewhere_else" in m for m in exc.value.detail["name_matches"])


@real_source
def test_load_vendoring_approval_returns_none_when_no_record_exists(tmp_path):
    assert ssa.load_vendoring_approval(tmp_path) is None


@real_source
def test_load_vendoring_approval_raises_on_a_malformed_record(tmp_path):
    approval_dir = tmp_path / "dv_harness"
    approval_dir.mkdir()
    (approval_dir / "syoscb_vendoring_approval.json").write_text("{\"approved\": true}")
    with pytest.raises(ssa.SyoscbSourceAuditError):
        ssa.load_vendoring_approval(tmp_path)


@real_source
def test_an_approval_record_that_says_approved_false_does_not_exempt_anything(tmp_path):
    audit = ssa.audit_syoscb_source(REAL_SYOSCB_ROOT)
    rogue_repo = tmp_path / "repo"
    dest = rogue_repo / "reference" / "uvm_syoscb-1.0.2.4"
    dest.mkdir(parents=True)
    (dest / "VERSION.txt").write_text("1.0.2.4\n")
    draft_approval = {"approved": False, "l5_destination": "reference/uvm_syoscb-1.0.2.4"}
    with pytest.raises(ssa.SyoscbSourceAuditError):
        ssa.assert_not_vendored(rogue_repo, audit, approval=draft_approval)


@real_source
def test_real_registration_payload_is_built_and_stays_unpublished():
    audit = ssa.audit_syoscb_source(REAL_SYOSCB_ROOT)
    payload = ssa.build_component_registration_payload(audit)
    assert payload["VERSION"] == "1.0.2.4"
    assert payload["SOURCE_REFERENCE"].lower().endswith("uvm_syoscb-1.0.2.4")
    assert payload["BUILD_STATUS"] == ssa.BUILD_STATUS_NOT_BUILT
    assert len(payload["KNOWN_LIMITATIONS"]) == 5
    # The one field the upstream tree cannot supply, and must not invent.
    assert ssa.registration_blockers(payload) == ["L5_DESTINATION"]


@real_source
def test_cli_audits_the_real_tree_without_writing_anything(tmp_path):
    before = {p: p.stat().st_mtime_ns for p in REAL_SYOSCB_ROOT.rglob("*") if p.is_file()}
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.syoscb_source_audit", str(REAL_SYOSCB_ROOT),
         "--registration-payload", "--assert-not-vendored", str(REPO_ROOT)],
        cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "SYOSCB-1 SOURCE AUDIT" in proc.stdout
    assert "1.0.2.4" in proc.stdout
    after = {p: p.stat().st_mtime_ns for p in REAL_SYOSCB_ROOT.rglob("*") if p.is_file()}
    assert before == after
