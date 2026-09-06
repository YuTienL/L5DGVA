"""Tests for dv_harness/vplan_baseline.py -- a vPlan-scoped freeze/baseline
mirroring signoff_export.py's content-hash based freeze/invalidation pattern.

Every fixture is a REAL project: a real throwaway git repository with real
commits, a real vPlan JSON document, a real requirement-contract-shaped
records file (declares_contract_shape() is the real discriminator this
module calls, not re-derived), and a real configuration-IR JSON document.
Nothing is mocked -- a freeze whose inputs were stubs would prove only the
record shape, never whether a post-freeze change is really detectable.

The central proofs are (1) `test_capture_full_baseline_all_four_fields_real_
evidence`, that all four fields are read from real content, never invented,
and (2) the pair `test_field_content_change_invalidates_independently_of_git`
/ `test_post_freeze_git_change_invalidates_independently_of_field_content`,
proving the two invalidation mechanisms (baseline-field digest divergence,
post-freeze git impact analysis) each fire on their own.

Negative controls throughout prove absent evidence reads as NOT_AVAILABLE,
never a false CAPTURED, and that "we could not check" (no git HEAD recorded)
reads as UNKNOWN, never VALID.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import vplan_baseline as vb

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")


# --- real fixture ------------------------------------------------------------

def _git(root, *args, check=True):
    r = subprocess.run([GIT, *args], cwd=str(root), capture_output=True, text=True,
                       timeout=120, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _vplan_doc(spec_revision="spec-2.1"):
    return {
        "vplan_id": "VP-USB3-1",
        "protocol_or_domain": "usb3",
        "scope": "SUBSYSTEM",
        "spec_revision": spec_revision,
        "requirements": [
            {"req_id": "REQ-1", "title": "LFPS handshake", "status": "VERIFIED"},
            {"req_id": "REQ-2", "title": "U1/U2 entry", "status": "PLANNED"},
        ],
        "coverage_goal": "100_PERCENT_SPEC_ACCOUNTING",
    }


def _contract_record(req_id, contract_schema_version="1.0"):
    return {
        "contract_schema_version": contract_schema_version,
        "requirement_id": req_id,
        "protocol": "USB3",
        "feature": "LFPS handshake",
        "expected_behavior": "link enters Polling.LFPS within spec timeout",
        "verification_method": "assertion+coverage",
        "coverage_intent": "cover LFPS retry paths",
        "priority": "P1",
        "criticality": "MAJOR",
        "confidence": "HIGH",
        "status": "COMPLETE",
    }


def _config_ir_doc():
    return {
        "space_id": "cfg-usb3",
        "dimensions": [
            {"name": "speed", "values": ["gen1", "gen2"], "source": "spec"},
            {"name": "lane_width", "values": ["x1", "x2"], "source": "spec"},
        ],
    }


def _make_project(tmp_path, *, name="proj", with_git=True):
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / "rtl").mkdir()
    (root / "docs").mkdir()
    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk); endmodule\n", encoding="utf-8")
    (root / "docs" / "notes.md").write_text("# notes\n", encoding="utf-8")
    (root / ".gitignore").write_text(".dv-harness/\n__pycache__/\n*.pyc\n", encoding="utf-8")

    paths = {
        "vplan": root / "vplan.json",
        "requirements": root / "requirements_ir.json",
        "config_ir": root / "config_ir.json",
    }
    _write_json(paths["vplan"], _vplan_doc())
    _write_json(paths["requirements"], [_contract_record("REQ-1"), _contract_record("REQ-2")])
    _write_json(paths["config_ir"], _config_ir_doc())

    sha = None
    if with_git:
        subprocess.run([GIT, "init", "-q", "-b", "master", str(root)], check=True, timeout=60)
        _git(root, "config", "user.email", "vplan-baseline@example.invalid")
        _git(root, "config", "user.name", "vplan-baseline-test")
        sha = _commit(root, "initial vPlan + requirement IR + configuration IR")
    return root, paths, sha


def _capture(root, paths, **kw):
    return vb.capture_vplan_baseline(
        root, vplan_path=paths["vplan"], requirements_path=paths["requirements"],
        configuration_ir_path=paths["config_ir"], **kw)


# --- module-level invariants -------------------------------------------------

def test_declared_fields_and_capture_table_are_held_equal_both_ways():
    assert len(vb.VPLAN_BASELINE_FIELDS) == 4
    assert set(vb.VPLAN_BASELINE_FIELDS) == set(vb.VPLAN_BASELINE_CAPTURES)


def test_freeze_vocabulary_is_imported_from_signoff_export_not_retyped():
    from dv_harness import signoff_export as sx
    assert vb.CAPTURED is sx.CAPTURED
    assert vb.NOT_AVAILABLE is sx.NOT_AVAILABLE
    assert vb.FREEZE_VALID is sx.FREEZE_VALID
    assert vb.FREEZE_INVALIDATED is sx.FREEZE_INVALIDATED
    assert vb.FREEZE_UNKNOWN is sx.FREEZE_UNKNOWN


# --- positive path: all four real -------------------------------------------

@requires_git
def test_capture_full_baseline_all_four_fields_real_evidence(tmp_path):
    root, paths, sha = _make_project(tmp_path)
    b = _capture(root, paths)

    assert b["captured_field_count"] == 4
    assert b["not_available_field_count"] == 0
    assert b["repo_head_sha"] == sha

    spec = b["fields"]["spec_version"]
    assert spec["status"] == vb.CAPTURED
    assert spec["reason"] == "REAL_VPLAN_SPEC_REVISION_FIELD"
    assert spec["digest"] == hashlib.sha256(b"spec-2.1").hexdigest()

    req_ir = b["fields"]["requirement_ir_version"]
    assert req_ir["status"] == vb.CAPTURED
    assert req_ir["detail"]["contract_record_count"] == 2
    assert req_ir["detail"]["mixed_contract_schema_versions"] is False
    assert req_ir["detail"]["contract_schema_versions"] == ["1.0"]

    cfg_ir = b["fields"]["configuration_ir_version"]
    assert cfg_ir["status"] == vb.CAPTURED
    assert cfg_ir["detail"]["dimension_count"] == 2
    assert cfg_ir["detail"]["space_id"] == "cfg-usb3"

    items = b["fields"]["vplan_items"]
    assert items["status"] == vb.CAPTURED
    assert items["detail"]["item_count"] == 2


# --- negative controls: absent evidence never a false CAPTURED -------------

def test_no_paths_supplied_all_four_fields_read_not_available(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    b = vb.capture_vplan_baseline(root)
    assert b["captured_field_count"] == 0
    assert b["not_available_field_count"] == 4
    assert b["fields"]["spec_version"]["reason"] == "NO_SPEC_VERSION_IN_VPLAN_OR_DECLARED"
    assert b["fields"]["requirement_ir_version"]["reason"] == "NO_REQUIREMENT_CONTRACT_FILE_SUPPLIED"
    assert b["fields"]["configuration_ir_version"]["reason"] == "NO_CONFIGURATION_IR_FILE_SUPPLIED"
    assert b["fields"]["vplan_items"]["reason"] == "NO_VPLAN_FILE_SUPPLIED"


def test_vplan_file_with_zero_items_is_not_available(tmp_path):
    root, paths, _ = _make_project(tmp_path, with_git=False)
    _write_json(paths["vplan"], {"spec_revision": "spec-2.1", "requirements": []})
    b = _capture(root, paths)
    assert b["fields"]["vplan_items"]["status"] == vb.NOT_AVAILABLE
    assert b["fields"]["vplan_items"]["reason"] == "VPLAN_FILE_HAS_ZERO_ITEMS"
    # spec_version is unaffected -- an empty item list does not sink an
    # otherwise-real spec_revision field.
    assert b["fields"]["spec_version"]["status"] == vb.CAPTURED


def test_requirements_file_with_no_contract_shaped_records(tmp_path):
    root, paths, _ = _make_project(tmp_path, with_git=False)
    _write_json(paths["requirements"], [{"req_id": "REQ-1", "note": "legacy shape, no version"}])
    b = _capture(root, paths)
    f = b["fields"]["requirement_ir_version"]
    assert f["status"] == vb.NOT_AVAILABLE
    assert f["reason"] == "NO_CONTRACT_SHAPED_RECORDS"
    assert f["detail"]["record_count"] == 1


def test_requirements_file_empty_list_is_not_available(tmp_path):
    root, paths, _ = _make_project(tmp_path, with_git=False)
    _write_json(paths["requirements"], [])
    b = _capture(root, paths)
    assert b["fields"]["requirement_ir_version"]["reason"] == "REQUIREMENT_CONTRACT_FILE_EMPTY"


def test_configuration_ir_file_not_found(tmp_path):
    root, paths, _ = _make_project(tmp_path, with_git=False)
    b = vb.capture_vplan_baseline(
        root, vplan_path=paths["vplan"], requirements_path=paths["requirements"],
        configuration_ir_path=root / "does_not_exist.json")
    assert b["fields"]["configuration_ir_version"]["reason"] == "CONFIGURATION_IR_FILE_NOT_FOUND"


def test_malformed_json_files_report_malformed_never_crash(tmp_path):
    root, paths, _ = _make_project(tmp_path, with_git=False)
    paths["vplan"].write_text("{not valid json", encoding="utf-8")
    paths["requirements"].write_text("[also not valid", encoding="utf-8")
    paths["config_ir"].write_text("still not json}}}", encoding="utf-8")
    b = _capture(root, paths)
    assert b["fields"]["vplan_items"]["reason"] == "VPLAN_FILE_MALFORMED"
    assert b["fields"]["requirement_ir_version"]["reason"] == "REQUIREMENT_CONTRACT_FILE_MALFORMED"
    assert b["fields"]["configuration_ir_version"]["reason"] == "CONFIGURATION_IR_FILE_MALFORMED"
    assert b["captured_field_count"] == 0


def test_declared_spec_version_used_when_vplan_has_no_spec_revision(tmp_path):
    root, paths, _ = _make_project(tmp_path, with_git=False)
    _write_json(paths["vplan"], {"requirements": [{"req_id": "REQ-1"}]})  # no spec_revision
    b = _capture(root, paths, declared={"spec_version": "human-declared-1.0"})
    spec = b["fields"]["spec_version"]
    assert spec["status"] == vb.CAPTURED
    assert spec["reason"] == "DECLARED_BY_FREEZING_HUMAN"
    assert spec["detail"]["attested"] is True
    assert spec["detail"]["machine_verified"] is False


def test_mixed_contract_schema_versions_still_captured_but_flagged(tmp_path):
    root, paths, _ = _make_project(tmp_path, with_git=False)
    _write_json(paths["requirements"],
               [_contract_record("REQ-1", "1.0"), _contract_record("REQ-2", "2.0")])
    b = _capture(root, paths)
    f = b["fields"]["requirement_ir_version"]
    assert f["status"] == vb.CAPTURED
    assert f["detail"]["mixed_contract_schema_versions"] is True
    assert f["detail"]["contract_schema_versions"] == ["1.0", "2.0"]


# --- reuse proof: the digest really goes through source_identity -----------

def _load_source_identity_module():
    spec = importlib.util.spec_from_file_location(
        "source_identity_independent_copy", ROOT / "tools" / "remote" / "source_identity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vplan_items_digest_is_produced_by_the_real_aggregate_source_id(tmp_path):
    """Independently reconstructs the manifest this module's own capture
    function builds and feeds it to the REAL tools/remote/source_identity.py
    (loaded fresh from disk, not the one dv_harness re-exports), asserting
    byte-identical output. If vplan_baseline ever hand-rolled a second
    hashing scheme (a different digest algorithm, or an order-sensitive
    join) this test would catch the divergence."""
    root, paths, _ = _make_project(tmp_path, with_git=False)
    b = _capture(root, paths)
    doc = json.loads(paths["vplan"].read_text(encoding="utf-8"))
    manifest = {
        str(item["req_id"]): hashlib.sha256(
            json.dumps(item, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        for item in doc["requirements"]
    }
    si = _load_source_identity_module()
    expected = si.aggregate_source_id(manifest)
    assert b["fields"]["vplan_items"]["digest"] == expected

    # order-independence: aggregate_source_id sorts internally.
    reordered = dict(reversed(list(manifest.items())))
    assert si.aggregate_source_id(reordered) == expected


# --- freeze ------------------------------------------------------------------

@requires_git
def test_freeze_requires_a_named_human(tmp_path):
    root, paths, _ = _make_project(tmp_path)
    with pytest.raises(ValueError):
        vb.freeze_vplan_baseline(
            root, frozen_by=None, vplan_path=paths["vplan"],
            requirements_path=paths["requirements"],
            configuration_ir_path=paths["config_ir"])
    assert vb.list_freezes(root) == []


@requires_git
def test_freeze_then_evaluate_is_valid_with_no_changes(tmp_path):
    root, paths, sha = _make_project(tmp_path)
    frozen = vb.freeze_vplan_baseline(
        root, frozen_by="dv-lead", vplan_path=paths["vplan"],
        requirements_path=paths["requirements"], configuration_ir_path=paths["config_ir"])
    assert frozen["baseline"]["repo_head_sha"] == sha

    result = vb.evaluate_vplan_freeze_invalidation(root, frozen)
    assert result["status"] == vb.FREEZE_VALID
    assert result["findings"] == []
    assert vb.load_freeze(root, frozen["freeze_id"])["freeze_id"] == frozen["freeze_id"]


@requires_git
def test_field_content_change_invalidates_independently_of_git(tmp_path):
    """Changing what a field's own file says, with NO git commit at all,
    still invalidates -- the field-divergence mechanism on its own."""
    root, paths, _ = _make_project(tmp_path)
    frozen = vb.freeze_vplan_baseline(
        root, frozen_by="dv-lead", vplan_path=paths["vplan"],
        requirements_path=paths["requirements"], configuration_ir_path=paths["config_ir"])

    doc = json.loads(paths["vplan"].read_text(encoding="utf-8"))
    doc["requirements"].append({"req_id": "REQ-3", "title": "new item"})
    _write_json(paths["vplan"], doc)  # deliberately NOT committed to git

    result = vb.evaluate_vplan_freeze_invalidation(root, frozen)
    assert result["status"] == vb.FREEZE_INVALIDATED
    codes = {f["code"] for f in result["findings"]}
    assert "BASELINE_FIELD_CHANGED" in codes
    changed_fields = {f["field"] for f in result["findings"] if f["code"] == "BASELINE_FIELD_CHANGED"}
    assert changed_fields == {"vplan_items"}
    # the frozen record on disk is untouched -- the verdict is derived, never stored.
    on_disk = json.loads((vb.freeze_dir(root) / (frozen["freeze_id"] + ".json")).read_text())
    assert on_disk == frozen


@requires_git
def test_post_freeze_git_change_invalidates_independently_of_field_content(tmp_path):
    """A real git commit that touches a HIGH-risk file, with every field's
    OWN file left byte-identical, still invalidates -- the post-freeze
    impact-analysis mechanism on its own."""
    root, paths, _ = _make_project(tmp_path)
    frozen = vb.freeze_vplan_baseline(
        root, frozen_by="dv-lead", vplan_path=paths["vplan"],
        requirements_path=paths["requirements"], configuration_ir_path=paths["config_ir"])

    (root / "rtl" / "new_block.v").write_text("module new_block(); endmodule\n", encoding="utf-8")
    _commit(root, "add a new RTL block")

    result = vb.evaluate_vplan_freeze_invalidation(root, frozen)
    assert result["status"] == vb.FREEZE_INVALIDATED
    codes = {f["code"] for f in result["findings"]}
    assert "POST_FREEZE_MATERIAL_CHANGE" in codes
    assert not any(f["code"] == "BASELINE_FIELD_CHANGED" for f in result["findings"])
    material = next(f for f in result["findings"] if f["code"] == "POST_FREEZE_MATERIAL_CHANGE")
    paths_seen = {m["path"] for m in material["detail"]["material_changes"]}
    assert "rtl/new_block.v" in paths_seen
    risks = {m["risk"] for m in material["detail"]["material_changes"] if m["path"] == "rtl/new_block.v"}
    assert risks == {"HIGH"}


@requires_git
def test_low_risk_doc_only_change_does_not_invalidate(tmp_path):
    root, paths, _ = _make_project(tmp_path)
    frozen = vb.freeze_vplan_baseline(
        root, frozen_by="dv-lead", vplan_path=paths["vplan"],
        requirements_path=paths["requirements"], configuration_ir_path=paths["config_ir"])

    (root / "docs" / "notes.md").write_text("# notes\nmore words\n", encoding="utf-8")
    _commit(root, "docs only")

    result = vb.evaluate_vplan_freeze_invalidation(root, frozen)
    assert result["status"] == vb.FREEZE_VALID
    assert result["findings"] == []


def test_no_recorded_git_head_reads_as_unknown_never_valid(tmp_path):
    """'We could not check' is UNKNOWN, never VALID -- a project with no git
    history at all cannot have its post-freeze impact analysed, and that
    must not be silently read as 'nothing changed'."""
    root, paths, sha = _make_project(tmp_path, with_git=False)
    assert sha is None
    frozen = vb.freeze_vplan_baseline(
        root, frozen_by="dv-lead", vplan_path=paths["vplan"],
        requirements_path=paths["requirements"], configuration_ir_path=paths["config_ir"])
    assert frozen["baseline"]["repo_head_sha"] is None

    result = vb.evaluate_vplan_freeze_invalidation(root, frozen)
    assert result["status"] == vb.FREEZE_UNKNOWN
    assert not any(f["severity"] == vb.SEV_INVALIDATING for f in result["findings"])
    assert any(f["code"] == "POST_FREEZE_IMPACT_ANALYSIS_UNAVAILABLE" for f in result["findings"])


def test_field_absent_from_an_older_frozen_record_is_indeterminate_not_valid(tmp_path):
    """Simulates a freeze recorded under a hypothetically shorter schema
    (one baseline field missing entirely) -- must read as UNKNOWN, not as a
    silently-passing VALID."""
    root, paths, _ = _make_project(tmp_path, with_git=False)
    frozen = vb.freeze_vplan_baseline(
        root, frozen_by="dv-lead", vplan_path=paths["vplan"],
        requirements_path=paths["requirements"], configuration_ir_path=paths["config_ir"])
    del frozen["baseline"]["fields"]["configuration_ir_version"]

    result = vb.evaluate_vplan_freeze_invalidation(root, frozen)
    assert result["status"] == vb.FREEZE_UNKNOWN
    assert any(f["code"] == "FIELD_NOT_IN_FROZEN_BASELINE" and f["field"] == "configuration_ir_version"
              for f in result["findings"])


def test_evaluate_all_freezes_on_a_bare_project_is_not_available(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    report = vb.evaluate_all_vplan_freezes(root)
    assert report["status"] == "NOT_AVAILABLE"
    assert report["reason"] == "NO_FROZEN_VPLAN_BASELINE"
    assert vb.load_freeze(root) is None


@requires_git
def test_evaluate_all_freezes_reports_the_worst_across_multiple(tmp_path):
    root, paths, _ = _make_project(tmp_path)
    f1 = vb.freeze_vplan_baseline(
        root, frozen_by="dv-lead", vplan_path=paths["vplan"],
        requirements_path=paths["requirements"], configuration_ir_path=paths["config_ir"])
    (root / "rtl" / "new_block.v").write_text("module new_block(); endmodule\n", encoding="utf-8")
    _commit(root, "add rtl")
    f2 = vb.freeze_vplan_baseline(
        root, frozen_by="dv-lead", vplan_path=paths["vplan"],
        requirements_path=paths["requirements"], configuration_ir_path=paths["config_ir"])

    report = vb.evaluate_all_vplan_freezes(root)
    assert report["freeze_count"] == 2
    # f1 is now stale against the newer commit; f2 was frozen fresh.
    ids = {r["freeze_id"]: r["status"] for r in report["freezes"]}
    assert ids[f1["freeze_id"]] == vb.FREEZE_INVALIDATED
    assert ids[f2["freeze_id"]] == vb.FREEZE_VALID
    assert report["status"] == vb.FREEZE_INVALIDATED  # worst wins


# --- front door ---------------------------------------------------------------

def _run_module(root, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "dv_harness.vplan_baseline",
                          *args, "--root", str(root)],
                         capture_output=True, text=True, timeout=300,
                         env=env, cwd=str(ROOT), encoding="utf-8", errors="replace")


@requires_git
def test_module_entry_point_fields_freeze_status(tmp_path):
    root, paths, _ = _make_project(tmp_path)

    r = _run_module(root, "fields")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["vplan_baseline_fields"] == list(vb.VPLAN_BASELINE_FIELDS)

    r = _run_module(root, "status")
    assert r.returncode == 2, r.stdout
    assert json.loads(r.stdout)["reason"] == "NO_FROZEN_VPLAN_BASELINE"

    r = _run_module(root, "freeze",
                    "--vplan", str(paths["vplan"]), "--requirements", str(paths["requirements"]),
                    "--configuration-ir", str(paths["config_ir"]))
    assert r.returncode == 2
    assert json.loads(r.stdout)["reason"] == "FROZEN_BY_REQUIRED"
    assert vb.list_freezes(root) == []

    r = _run_module(root, "freeze", "--frozen-by", "dv-lead",
                    "--vplan", str(paths["vplan"]), "--requirements", str(paths["requirements"]),
                    "--configuration-ir", str(paths["config_ir"]))
    assert r.returncode == 0, r.stderr
    fid = json.loads(r.stdout)["freeze_id"]

    r = _run_module(root, "status")
    assert r.returncode == 0, r.stdout
    assert json.loads(r.stdout)["status"] == vb.FREEZE_VALID

    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk, input rst_n); endmodule\n", encoding="utf-8")
    _commit(root, "rtl moved")

    r = _run_module(root, "status", "--freeze-id", fid)
    assert r.returncode == 1, r.stdout
    assert json.loads(r.stdout)["status"] == vb.FREEZE_INVALIDATED


def test_module_entry_point_baseline_verb_exit_codes(tmp_path):
    root, paths, _ = _make_project(tmp_path, with_git=False)
    r = _run_module(root, "baseline",
                    "--vplan", str(paths["vplan"]), "--requirements", str(paths["requirements"]),
                    "--configuration-ir", str(paths["config_ir"]))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["captured_field_count"] == 4

    r = _run_module(root, "baseline")
    assert r.returncode == 2
    assert json.loads(r.stdout)["captured_field_count"] == 0


# --- boundaries ---------------------------------------------------------------

@requires_git
def test_evaluating_a_freeze_writes_nothing(tmp_path):
    root, paths, _ = _make_project(tmp_path)
    frozen = vb.freeze_vplan_baseline(
        root, frozen_by="dv-lead", vplan_path=paths["vplan"],
        requirements_path=paths["requirements"], configuration_ir_path=paths["config_ir"])

    def snapshot():
        return {str(p.relative_to(root)): p.read_bytes()
                for p in sorted(root.rglob("*"))
                if p.is_file() and ".git" not in p.parts}

    before = snapshot()
    vb.evaluate_vplan_freeze_invalidation(root, frozen)
    vb.evaluate_all_vplan_freezes(root)
    assert snapshot() == before


def test_the_module_touches_no_approval_machinery():
    src = (ROOT / "dv_harness" / "vplan_baseline.py").read_text(encoding="utf-8")
    for forbidden in ("ControlPlane", "can_signoff", "assert_human_approval",
                      "HumanApprovalRequiredError", "bsub", "run_preflight",
                      "ProductionWriteNotAuthorizedError"):
        assert forbidden not in src, forbidden


def test_the_module_does_not_import_config_variant_coverage():
    """File-safety scope: config_variant_coverage.py was under concurrent
    edit by a separate batch when this module was written, so
    configuration_ir_version must be generic/duck-typed rather than importing
    it. Docstrings are allowed to NAME it in prose (explaining the boundary
    and how a caller could validate through it later); what must never exist
    is an actual `import`/`from ... import` statement naming it -- checked
    via a real AST walk over every Import/ImportFrom node, which cannot be
    fooled by a docstring merely mentioning the name."""
    import ast
    src_path = ROOT / "dv_harness" / "vplan_baseline.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    imported_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported_names.append(node.module or "")
    assert not any("config_variant_coverage" in name for name in imported_names), imported_names


def test_does_not_edit_signoff_export():
    """Reuse only -- signoff_export.py's own content must be byte-identical
    to what this task started from (spot-checked via its own declared
    section-238 field count, which this test does not modify)."""
    from dv_harness import signoff_export as sx
    assert len(sx.SECTION_238_FIELDS) == 15
