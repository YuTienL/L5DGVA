"""Tests for dv_harness/signoff_export.py -- closes the "一鍵最終 Signoff 匯出"
poster-compliance gap (bundle vPlan/blackboard signoff state/telemetry/
pattern registry/UVM testbench source/regression manifest + a fresh
self-audit result into one out dir with an honest manifest of what was
actually present)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import question_queue
from dv_harness import signoff_export
from dv_harness.uvm_generator.protocol_env_generator import ProtocolEnvGenerator

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")

ROOT = Path(__file__).resolve().parents[1]

USB_MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"], "agent_type": "usb_agent", "agent_instance": "usb_agent0"},
    "smoke_tests": [{"name": "smoke"}],
}


def _fresh_project_with_tools():
    """self_audit.py's ROOT_GATES/JSON_GATES resolve gate scripts as
    `project_root/tools/verification_flow/...` (see dv_harness/self_audit.py
    and dv_harness_tests/test_cli_remote_control.py's identical fixture), so
    a fake project root needs its own copy of tools/ for run_self_audit() to
    execute without raising."""
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "tools", tmp / "tools")
    return tmp


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_partial_project():
    """SOME (not all) of the 11 candidate artifacts present:
    - blackboard/signoff_state.json, blackboard/findings.json: present
    - blackboard/regression_state.json, blackboard/requirements.json: absent
    - vplan/: present (one real schema-shaped file)
    - telemetry/: present (one real stage profile file)
    - pattern_registry/: absent (no such convention exists in this project)
    - tb_source: absent (no generated UVM environment present)
    - regression_manifest: absent (no .dv-harness/regression.list present)
    - signoff_stage_status: present (always generated fresh, like self_audit_result)
    """
    tmp = _fresh_project_with_tools()
    _write_json(tmp / ".dv-harness" / "blackboard" / "signoff_state.json",
                {"topic": "signoff_state", "value": {"status": "PENDING"}})
    _write_json(tmp / ".dv-harness" / "blackboard" / "findings.json",
                {"topic": "findings", "value": []})
    _write_json(tmp / ".dv-harness" / "vplan" / "vplan.schema.json",
                {"vplan_id": "string", "requirements": []})
    _write_json(tmp / ".dv-harness" / "telemetry" / "workflow_profile.json",
                {"stage_count": 0})
    return tmp


def test_bundles_only_present_artifacts_and_manifest_marks_rest_absent():
    tmp = _make_partial_project()
    out_dir = tmp / "signoff_out"
    try:
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)

        assert result["status"] == "OK"
        assert result["out_dir"] == str(out_dir.resolve())

        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        assert len(by_artifact) == 11

        present_expected = {
            "blackboard/signoff_state.json", "blackboard/findings.json",
            "vplan", "telemetry", "self_audit_result", "signoff_stage_status",
        }
        absent_expected = {
            "blackboard/regression_state.json", "blackboard/requirements.json",
            "pattern_registry", "tb_source", "regression_manifest",
        }
        for artifact in present_expected:
            assert by_artifact[artifact]["present"] is True, artifact
            assert by_artifact[artifact]["bundled_path"] is not None
            assert (out_dir / by_artifact[artifact]["bundled_path"]).exists()
        for artifact in absent_expected:
            assert by_artifact[artifact]["present"] is False, artifact
            assert by_artifact[artifact]["bundled_path"] is None

        assert result["bundled_count"] == len(present_expected)
        assert result["missing_count"] == len(absent_expected)

        # manifest.json itself is written into out_dir and matches the return
        # value, including the real recomputable bundle_hash (see
        # signoff_export.compute_bundle_hash / test_signoff_bundle_hash.py).
        manifest_on_disk = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest_on_disk["manifest"] == result["manifest"]
        assert manifest_on_disk["bundle_hash"] == result["bundle_hash"]
        assert result["bundle_hash"] == signoff_export.compute_bundle_hash(result["manifest"])

        # self-audit result is always included, and is real self_audit output
        # (has the same summary/gates shape run_self_audit produces), not a
        # fabricated placeholder.
        audit_path = out_dir / by_artifact["self_audit_result"]["bundled_path"]
        audit_json = json.loads(audit_path.read_text(encoding="utf-8"))
        assert "summary" in audit_json and "gates" in audit_json
        assert audit_json["summary"]["total"] == len(audit_json["gates"])

        # bundled blackboard file content actually matches the source.
        bundled_signoff = json.loads(
            (out_dir / by_artifact["blackboard/signoff_state.json"]["bundled_path"]).read_text(encoding="utf-8"))
        assert bundled_signoff["value"]["status"] == "PENDING"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_exception_when_nothing_at_all_is_present():
    tmp = _fresh_project_with_tools()
    out_dir = tmp / "signoff_out"
    try:
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        assert result["status"] == "OK"
        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        # self_audit_result and signoff_stage_status are the two always
        # freshly-generated artifacts -- everything else is a real absent
        # artifact under this bare project root.
        assert result["bundled_count"] == 2
        assert result["missing_count"] == 9
        assert by_artifact["self_audit_result"]["present"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_signoff_bundle_includes_tb_source_when_present():
    """Generate a real tb/ tree via ProtocolEnvGenerator (the actual USB_
    UVM_Handoff-shaped subdirectory layout: tb/agents,env,seq,tests,top --
    see protocol_env_generator.py) at an ARBITRARY location under the
    project root (deliberately NOT any specific convention path -- proves
    collect_signoff_bundle() discovers it via its real
    environment_manifest.json marker, per _find_tb_source_dir, rather than
    matching one hardcoded guessed path), and confirm the real generated
    files get bundled, not a placeholder."""
    tmp = _fresh_project_with_tools()
    out_dir = tmp / "signoff_out"
    try:
        generated_dir = tmp / "build" / "some_arbitrary_output_location" / "usb3_2_uvm_env"
        generated_files = ProtocolEnvGenerator(generated_dir).generate(USB_MANIFEST)

        result = signoff_export.collect_signoff_bundle(tmp, out_dir)

        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        assert by_artifact["tb_source"]["present"] is True
        bundled_rel = by_artifact["tb_source"]["bundled_path"]
        assert bundled_rel is not None
        assert (out_dir / bundled_rel).is_dir()

        tb_files = [f for f in generated_files if f.startswith("tb/")]
        assert tb_files, "fixture sanity check: ProtocolEnvGenerator must emit tb/ files"
        for rel in tb_files:
            src = generated_dir / rel
            dst = out_dir / bundled_rel / Path(rel).relative_to("tb")
            assert dst.exists(), f"missing bundled tb source file: {rel}"
            assert dst.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_signoff_bundle_honestly_reports_missing_tb_source():
    """No generated tb/ tree present -- the manifest must explicitly report
    tb_source absent (matching the existing pattern_registry "reported
    absent" convention), and no bundled_path/fabricated content may appear."""
    tmp = _fresh_project_with_tools()
    out_dir = tmp / "signoff_out"
    try:
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        assert by_artifact["tb_source"]["present"] is False
        assert by_artifact["tb_source"]["bundled_path"] is None
        assert not (out_dir / "tb_source").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_signoff_bundle_ignores_flat_layout_manifest_without_tb_dir():
    """A real environment_manifest.json can carry qualification_status
    ENV_GENERATED without ever having a tb/ subdirectory -- confirmed on
    disk at examples/generated_pcie_uvm_env/environment_manifest.json,
    written by the older deprecated flat generator.py path. Reproduce that
    exact shape (manifest present, no tb/ sibling) and confirm it is
    correctly NOT mistaken for real TB source."""
    tmp = _fresh_project_with_tools()
    out_dir = tmp / "signoff_out"
    try:
        flat_dir = tmp / "examples" / "generated_pcie_uvm_env"
        flat_dir.mkdir(parents=True, exist_ok=True)
        _write_json(flat_dir / "environment_manifest.json",
                    {"protocol": "PCIe", "generated_files": ["pcie_env_pkg.sv"],
                     "qualification_status": "ENV_GENERATED"})
        (flat_dir / "pcie_env_pkg.sv").write_text("// flat-layout file, no tb/\n", encoding="utf-8")

        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        assert by_artifact["tb_source"]["present"] is False
        assert by_artifact["tb_source"]["bundled_path"] is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_signoff_bundle_tb_source_picks_most_recently_generated_when_multiple():
    """Two real ProtocolEnvGenerator outputs exist under the project root --
    the freshest (most recently modified environment_manifest.json) must be
    the one bundled as tb_source."""
    tmp = _fresh_project_with_tools()
    out_dir = tmp / "signoff_out"
    try:
        older_dir = tmp / "old_run" / "usb_uvm_env"
        newer_dir = tmp / "new_run" / "usb_uvm_env"
        ProtocolEnvGenerator(older_dir).generate(USB_MANIFEST)
        newer_files = ProtocolEnvGenerator(newer_dir).generate(USB_MANIFEST)

        # Force a real, observable mtime gap between the two manifests so
        # "most recent" has an unambiguous real answer.
        import os
        import time
        older_manifest = older_dir / "environment_manifest.json"
        newer_manifest = newer_dir / "environment_manifest.json"
        now = time.time()
        os.utime(older_manifest, (now - 3600, now - 3600))
        os.utime(newer_manifest, (now, now))

        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        assert by_artifact["tb_source"]["present"] is True
        bundled_rel = by_artifact["tb_source"]["bundled_path"]

        newer_tb_file = next(f for f in newer_files if f.startswith("tb/"))
        dst = out_dir / bundled_rel / Path(newer_tb_file).relative_to("tb")
        src = newer_dir / newer_tb_file
        assert dst.exists()
        assert dst.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_signoff_bundle_excludes_examples_demo_tb_tree(tmp_path=None):
    """Finding C1 regression test: a demo/example tree under `examples/`
    that carries the EXACT real ProtocolEnvGenerator marker shape (a real
    environment_manifest.json with qualification_status ENV_GENERATED, next
    to a real tb/ subdirectory -- confirmed on the real repo as the shape of
    examples/generated_usb_real_evidence_v*/) must NOT be discovered as
    tb_source. Before the C1 fix, `_find_tb_source_dir`'s unrestricted
    root.rglob() bundled exactly this kind of demo tree into the signoff
    deliverable as if it were real TB source -- a confident false positive.
    Only example-shaped content exists here (no real generation anywhere
    else under root), so the correct, honest result is ABSENT, not bundled.
    """
    tmp = _fresh_project_with_tools()
    out_dir = tmp / "signoff_out"
    try:
        demo_dir = tmp / "examples" / "generated_usb_real_evidence_v1" / "usb3_2_uvm_env"
        ProtocolEnvGenerator(demo_dir).generate(USB_MANIFEST)
        assert (demo_dir / "environment_manifest.json").exists()
        assert (demo_dir / "tb").is_dir()

        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        assert by_artifact["tb_source"]["present"] is False
        assert by_artifact["tb_source"]["bundled_path"] is None
        assert not (out_dir / "tb_source").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_signoff_bundle_still_finds_real_tb_source_outside_excluded_dirs():
    """Positive-control companion to the C1 exclusion test above: a real
    generation at a path NOT under any excluded directory must still be
    discovered and bundled -- the C1 fix must narrow the search scope, not
    break discovery entirely."""
    tmp = _fresh_project_with_tools()
    out_dir = tmp / "signoff_out"
    try:
        generated_dir = tmp / "runs" / "usb3_2_uvm_env"
        generated_files = ProtocolEnvGenerator(generated_dir).generate(USB_MANIFEST)

        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        assert by_artifact["tb_source"]["present"] is True
        bundled_rel = by_artifact["tb_source"]["bundled_path"]
        assert bundled_rel is not None

        tb_files = [f for f in generated_files if f.startswith("tb/")]
        assert tb_files
        for rel in tb_files:
            dst = out_dir / bundled_rel / Path(rel).relative_to("tb")
            assert dst.exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_signoff_export_real_repo_root_does_not_bundle_examples_tree():
    """Live check against the REAL repo root (not a tmp_path fixture): the
    real repo has multiple examples/generated_usb_real_evidence_v*/ demo
    trees on disk. _find_tb_source_dir must never resolve into one of them.
    Does not assert presence/absence of tb_source overall (that depends on
    whatever real generation output happens to exist under ROOT outside
    examples/ at test time) -- only that IF a tb_source is found, it is not
    rooted under examples/, .claude/worktrees/, or .claude/skills/_deprecated/."""
    found = signoff_export._find_tb_source_dir(ROOT, None)
    if found is not None:
        rel = found.resolve().relative_to(ROOT).parts
        assert "examples" not in rel
        assert not (len(rel) >= 2 and rel[0] == ".claude" and rel[1] == "worktrees")
        assert not (len(rel) >= 3 and rel[0] == ".claude" and rel[1] == "skills" and rel[2] == "_deprecated")


def test_signoff_bundle_includes_regression_manifest_when_present():
    """A real .dv-harness/regression.list (the plain grep/comm-friendly
    format regression_list_manager.py's record_verdict/record_suite produce,
    written at the Makefile.patterns.mk-documented default REGRESSION_LIST
    path) must be bundled verbatim, not fabricated."""
    tmp = _fresh_project_with_tools()
    out_dir = tmp / "signoff_out"
    try:
        regression_list = tmp / ".dv-harness" / "regression.list"
        regression_list.parent.mkdir(parents=True, exist_ok=True)
        regression_list.write_text("smoke_test\nenum_test\n", encoding="utf-8")

        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        assert by_artifact["regression_manifest"]["present"] is True
        bundled_rel = by_artifact["regression_manifest"]["bundled_path"]
        assert bundled_rel is not None
        assert (out_dir / bundled_rel).read_text(encoding="utf-8") == "smoke_test\nenum_test\n"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_cli(tmp, *args):
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), "signoff-export", *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60, encoding="utf-8",
    )
    return r


def test_cli_signoff_export_subcommand():
    tmp = _make_partial_project()
    out_dir = tmp / "cli_signoff_out"
    try:
        r = _run_cli(tmp, "--out", str(out_dir))
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip())
        assert out["status"] == "OK"
        assert out["bundled_count"] == 6
        assert out["missing_count"] == 5
        assert (out_dir / "manifest.json").exists()
        assert (out_dir / "self_audit_result.json").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- file_bundle_artifact_question / file_freeze_finding_question ----------
# (2026-09-07, "signoff-reviewer-cannot-ask-question-about-specific-
# evidence" gap closure): a human reviewing a real, already-produced bundle
# manifest or freeze-invalidation report now has a reachable, real path to
# file a NEW question tied to one specific evidence item, reusing question_
# queue.file_signoff_evidence_question() unmodified.

def test_file_bundle_artifact_question_cites_a_present_artifact(tmp_path):
    tmp = _make_partial_project()
    try:
        out_dir = tmp / "signoff_out"
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        store = question_queue.QuestionQueueStore(tmp)

        rec = signoff_export.file_bundle_artifact_question(
            store, result["manifest"], "vplan",
            question="Does this bundled vplan/ directory reflect the reviewed vPlan revision?",
            options=["Yes -- matches reviewed revision", "No -- stale, must regenerate"],
            recommendation="No -- stale, must regenerate",
            raised_by="dv-reviewer",
        )

        assert rec["tier"] == question_queue.TIER3_CANNOT_ASSUME
        assert rec["blocking"] is True
        assert rec["grounding_evidence"]["evidence_path"] == (
            "manifest.json#manifest[artifact='vplan']")
        assert "present=True" in rec["grounding_evidence"]["summary"]
        assert "dv-reviewer" in rec["grounding_evidence"]["summary"]
        question_queue.validate_question(rec)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_file_bundle_artifact_question_cites_an_absent_artifact_honestly(tmp_path):
    """An absent artifact is still a real, citable manifest entry --
    present=False, bundled_path=None -- and the question's own grounding
    evidence must say so honestly, never claim a bundled_path that does not
    exist."""
    tmp = _make_partial_project()
    try:
        out_dir = tmp / "signoff_out"
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        assert by_artifact["tb_source"]["present"] is False  # fixture sanity

        store = question_queue.QuestionQueueStore(tmp)
        rec = signoff_export.file_bundle_artifact_question(
            store, result["manifest"], "tb_source",
            question="Is tb_source genuinely absent, or was generation skipped?",
            options=["Genuinely absent", "Mistake -- regenerate before signoff"],
            recommendation="Mistake -- regenerate before signoff",
        )
        assert "present=False" in rec["grounding_evidence"]["summary"]
        assert "bundled_path=None" in rec["grounding_evidence"]["summary"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_file_bundle_artifact_question_unknown_artifact_is_refused(tmp_path):
    tmp = _make_partial_project()
    try:
        out_dir = tmp / "signoff_out"
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        store = question_queue.QuestionQueueStore(tmp)
        with pytest.raises(KeyError):
            signoff_export.file_bundle_artifact_question(
                store, result["manifest"], "this_artifact_does_not_exist",
                question="q?", options=["a", "b"], recommendation="a",
            )
        assert store.list_questions() == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_file_bundle_artifact_question_is_idempotent_on_re_review(tmp_path):
    tmp = _make_partial_project()
    try:
        out_dir = tmp / "signoff_out"
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        store = question_queue.QuestionQueueStore(tmp)
        kwargs = dict(question="q?", options=["a", "b"], recommendation="a")
        first = signoff_export.file_bundle_artifact_question(store, result["manifest"], "vplan", **kwargs)
        second = signoff_export.file_bundle_artifact_question(store, result["manifest"], "vplan", **kwargs)
        assert first["id"] == second["id"]
        assert len(store.list_questions()) == 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_file_bundle_artifact_question_accepts_a_root_path_for_store(tmp_path):
    """`store` may be a project root (str/Path), the same convenience
    source_authority.escalate_conflict() already offers, rather than
    requiring the caller to construct a QuestionQueueStore first."""
    tmp = _make_partial_project()
    try:
        out_dir = tmp / "signoff_out"
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        rec = signoff_export.file_bundle_artifact_question(
            tmp, result["manifest"], "vplan",
            question="q?", options=["a", "b"], recommendation="a",
        )
        store = question_queue.QuestionQueueStore(tmp)
        assert store.get_question(rec["id"]) is not None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _make_git_freeze_project(tmp_path):
    root = tmp_path / "freeze_proj"
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "top.v").write_text(
        "module top(input clk, output reg q); always @(posedge clk) q <= 1'b0; endmodule\n",
        encoding="utf-8")
    (root / ".gitignore").write_text(".dv-harness/\n", encoding="utf-8")
    subprocess.run([GIT, "init", "-q", "-b", "master", str(root)], check=True, timeout=60)
    subprocess.run([GIT, "config", "user.email", "signoff-question-test@example.invalid"],
                   cwd=str(root), check=True, timeout=30)
    subprocess.run([GIT, "config", "user.name", "signoff-question-test"],
                   cwd=str(root), check=True, timeout=30)
    subprocess.run([GIT, "add", "-A"], cwd=str(root), check=True, timeout=30)
    subprocess.run([GIT, "commit", "-qm", "initial DUT"], cwd=str(root), check=True, timeout=30)
    return root


@requires_git
def test_file_freeze_finding_question_cites_a_real_invalidating_finding(tmp_path):
    root = _make_git_freeze_project(tmp_path)
    frozen = signoff_export.freeze_signoff_baseline(root, frozen_by="dv-lead")

    # a real RTL edit + commit -> a real, HIGH-risk POST_FREEZE_MATERIAL_CHANGE finding
    (root / "rtl" / "top.v").write_text(
        "module top(input clk, output reg q); always @(posedge clk) q <= ~q; endmodule\n",
        encoding="utf-8")
    subprocess.run([GIT, "add", "-A"], cwd=str(root), check=True, timeout=30)
    subprocess.run([GIT, "commit", "-qm", "edit rtl"], cwd=str(root), check=True, timeout=30)

    evaluation = signoff_export.evaluate_freeze_invalidation(root, frozen)
    assert evaluation["status"] == signoff_export.FREEZE_INVALIDATED  # fixture sanity
    assert evaluation["findings"], "fixture sanity: a real finding must exist"

    store = question_queue.QuestionQueueStore(root)
    rec = signoff_export.file_freeze_finding_question(
        store, evaluation, 0,
        question="Is this baseline divergence expected, or does the freeze need re-review?",
        options=["Expected -- proceed with signoff", "Unexpected -- block signoff"],
        recommendation="Unexpected -- block signoff",
        raised_by="qa-reviewer",
    )

    assert rec["tier"] == question_queue.TIER3_CANNOT_ASSUME
    assert rec["blocking"] is True
    real_code = evaluation["findings"][0]["code"]
    assert evaluation["freeze_id"] in rec["grounding_evidence"]["evidence_path"]
    assert real_code in rec["grounding_evidence"]["evidence_path"]
    assert "qa-reviewer" in rec["grounding_evidence"]["summary"]
    question_queue.validate_question(rec)

    # idempotent: re-reviewing the same finding returns the same record
    again = signoff_export.file_freeze_finding_question(
        store, evaluation, 0,
        question="Is this baseline divergence expected, or does the freeze need re-review?",
        options=["Expected -- proceed with signoff", "Unexpected -- block signoff"],
        recommendation="Unexpected -- block signoff",
        raised_by="qa-reviewer",
    )
    assert again["id"] == rec["id"]
    assert len(store.list_questions()) == 1


@requires_git
def test_file_freeze_finding_question_out_of_range_index_is_refused(tmp_path):
    """Negative control: a freshly-frozen, unmutated project's real
    evaluate_freeze_invalidation() report carries zero findings (VALID) --
    asking for finding index 0 against zero real findings must raise
    IndexError rather than fabricate a citation for a finding that does not
    exist."""
    root = _make_git_freeze_project(tmp_path)
    frozen = signoff_export.freeze_signoff_baseline(root, frozen_by="dv-lead")
    evaluation = signoff_export.evaluate_freeze_invalidation(root, frozen)
    assert evaluation["status"] == signoff_export.FREEZE_VALID  # fixture sanity
    assert evaluation["findings"] == []

    store = question_queue.QuestionQueueStore(root)
    with pytest.raises(IndexError):
        signoff_export.file_freeze_finding_question(
            store, evaluation, 0,
            question="q?", options=["a", "b"], recommendation="a",
        )
    assert store.list_questions() == []
