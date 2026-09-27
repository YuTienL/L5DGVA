"""Adversarial regression tests for Codex's REVIEW-003 findings N1-N6, which
reproduced on code that had been declared fixed for R1-R8 (GAP-V2-011/012/013).
Each test feeds hand-authored / hostile input or a real failure injection."""
from __future__ import annotations

import csv
import dataclasses
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import dv_harness.model_handoff_workflow as wf
import dv_harness.result_ingestion as ri
from dv_harness import execution_contract as ec
from dv_harness import md_kv_codec as codec
from dv_harness.model_handoff import (
    HandoffBuildError, HandoffParseError, build_handoff, canonical_repo_path, from_markdown as h_from,
    read_boundary, to_markdown as h_to,
)
from dv_harness.model_result import (
    ModelResultV1, ResultParseError, from_markdown as r_from, to_markdown as r_to, validate_result,
)
from dv_harness.question_queue import QuestionQueueStore
from dv_harness.task_boundary_conformance import TaskBoundary

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")
CANONICAL_ROOT = Path(__file__).resolve().parents[1]


def _run(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    w = tmp_path / "work"
    w.mkdir()
    _run(w, "init", "-q")
    _run(w, "config", "user.email", "t@example.com")
    _run(w, "config", "user.name", "T")
    (w / "dv_harness").mkdir()
    for n in ("module_a.py", "model_result.py", "engine.py"):
        (w / "dv_harness" / n).write_text("# x\n", encoding="utf-8")
    (w / "README.md").write_text("# readme\n", encoding="utf-8")
    _run(w, "add", "-A")
    _run(w, "commit", "-q", "-m", "i")
    return w


def _hand(repo, allowed=("dv_harness/module_a.py",), forbidden=("dv_harness/engine.py",), task="T-1", inputs=None, **kw):
    return build_handoff(
        repo, task_id=task, task_type="review-route", target_model="codex", project_id="P", objective="x",
        scope=TaskBoundary(task_id=task, allowed_path_prefixes=tuple(allowed), forbidden_paths=tuple(forbidden)),
        input_evidence_refs=list(allowed) if inputs is None else inputs, **kw)


def _res(**kw) -> ModelResultV1:
    base = dict(result_version="1.0", task_id="T-1", producer_model="codex", task_type="review-route",
                result_status="FAIL", claims=["c"], findings=["f"],
                evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])
    base.update(kw)
    return ModelResultV1(**base)


# ================================================================ N1 / N5: canonical paths

@pytest.mark.parametrize("raw,expected", [
    ("dv_harness/module_a.py", "dv_harness/module_a.py"),
    ("./dv_harness//module_a.py", "dv_harness/module_a.py"),
    ("dv_harness\\module_a.py", "dv_harness/module_a.py"),
    ("dv_harness/../README.md", "README.md"),
    ("dv_harness/model_result.py/../../dv_harness/engine.py", "dv_harness/engine.py"),
    ("dv_harness/engine.py.", "dv_harness/engine.py"),
    ("dv_harness/engine.py  ", "dv_harness/engine.py"),
    ("dv_harness/", "dv_harness"),
])
def test_canonical_repo_path_collapses_traversal_and_aliases(raw, expected):
    assert canonical_repo_path(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "..", "../x.py", "dv_harness/../../x.py", "/etc/passwd", "\\\\server\\share\\x.py", "C:/x.py", "C:\\x.py",
    "dv_harness/a\x00b.py", "dv_harness/a:stream.py", "dv_harness/a?.py", ".", "./",
])
def test_canonical_repo_path_rejects_unsafe_paths(raw):
    assert canonical_repo_path(raw) is None


def test_citation_traversing_out_of_an_allowed_directory_is_rejected(repo):
    h = _hand(repo, allowed=("dv_harness",), inputs=["dv_harness"])
    v = validate_result(h, _res(files_referenced=[], evidence_refs=["dv_harness/../README.md:1"]), root=repo)
    assert v.accepted is False and v.verified_evidence_refs == []
    assert v.scope_violations[0]["field"] == "EVIDENCE_REFS"


def test_returned_artifact_that_normalizes_to_a_forbidden_target_is_rejected(repo):
    h = _hand(repo, allowed=("dv_harness/model_result.py",))
    r = _res(files_referenced=[], evidence_refs=["dv_harness/model_result.py:1"],
             returned_artifacts=["dv_harness/model_result.py/../../dv_harness/engine.py"])
    v = validate_result(h, r, root=repo)
    assert v.accepted is False
    assert v.scope_violations == [{"field": "RETURNED_ARTIFACTS",
                                   "path": "dv_harness/model_result.py/../../dv_harness/engine.py",
                                   "classification": "FORBIDDEN_PATH_TOUCHED"}]


def test_files_referenced_that_normalizes_to_a_forbidden_target_is_rejected(repo):
    h = _hand(repo, allowed=("dv_harness/model_result.py",))
    r = _res(files_referenced=["dv_harness/model_result.py/../engine.py"], evidence_refs=["dv_harness/model_result.py:1"])
    v = validate_result(h, r, root=repo)
    assert v.scope_violations[0]["classification"] == "FORBIDDEN_PATH_TOUCHED"


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.py", "C:/Windows/x.py"])
def test_absolute_or_escaping_paths_are_unsafe_in_every_result_field(repo, bad):
    h = _hand(repo, allowed=("dv_harness",), inputs=["dv_harness"])
    for field in ("files_referenced", "returned_artifacts"):
        v = validate_result(h, _res(**{field: [bad]}), root=repo)
        assert v.accepted is False
        assert v.scope_violations[-1]["classification"] == "UNSAFE_PATH"
    v = validate_result(h, _res(evidence_refs=[bad + ":1"]), root=repo)
    assert v.accepted is False


def test_nonexistent_traversal_target_is_rejected_by_the_canonical_layer_alone(repo):
    # No file exists at the collapsed target, so the real-filesystem layer cannot help:
    # only canonicalization prevents `dv_harness/..` from passing as an allowed prefix.
    h = _hand(repo, allowed=("dv_harness",), inputs=["dv_harness"])
    v = validate_result(h, _res(files_referenced=["dv_harness/../not_there_outside.py"]), root=repo)
    assert v.accepted is False and v.scope_violations[0]["classification"] == "OUTSIDE_DECLARED_BOUNDARY"


def test_trailing_dot_alias_of_a_forbidden_file_is_rejected_on_every_platform(repo):
    h = _hand(repo, allowed=("dv_harness",), inputs=["dv_harness"])
    v = validate_result(h, _res(files_referenced=["dv_harness/engine.py."]), root=repo)
    assert v.scope_violations[0]["classification"] == "FORBIDDEN_PATH_TOUCHED"


def test_case_alias_of_a_forbidden_file_is_rejected(repo):
    (repo / "dv_harness" / "Engine.py").exists()
    if not (repo / "DV_HARNESS" / "ENGINE.PY").exists():
        pytest.skip("case-sensitive filesystem: the alias is a different (nonexistent) file")
    h = _hand(repo, allowed=("dv_harness",), inputs=["dv_harness"])
    v = validate_result(h, _res(files_referenced=["dv_harness/ENGINE.PY"]), root=repo)
    assert v.scope_violations and v.scope_violations[0]["classification"] == "FORBIDDEN_PATH_TOUCHED"


def test_symlink_inside_an_allowed_directory_that_escapes_the_root_is_unsafe(repo, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("# outside\n", encoding="utf-8")
    link = repo / "dv_harness" / "link.py"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted")
    h = _hand(repo, allowed=("dv_harness",), inputs=["dv_harness"])
    v = validate_result(h, _res(files_referenced=["dv_harness/link.py"]), root=repo)
    assert v.scope_violations[0]["classification"] == "UNSAFE_PATH"


def test_own_result_exemption_is_compared_on_canonical_paths(repo):
    h = _hand(repo)
    own = ".dv-harness/model_handoffs/T-1/RESULT_V1.md"
    ok = validate_result(h, _res(returned_artifacts=["./.dv-harness/model_handoffs/T-1/RESULT_V1.md"]), root=repo, own_result_path=own)
    assert ok.accepted is True
    sneaky = validate_result(h, _res(returned_artifacts=[".dv-harness/model_handoffs/T-1/../T-2/RESULT_V1.md"]),
                             root=repo, own_result_path=own)
    assert sneaky.accepted is False


@pytest.mark.parametrize("field,scope_kw", [
    ("ALLOWED_FILES", dict(allowed=("dv_harness/../README.md",))),
    ("ALLOWED_FILES", dict(allowed=("/abs/x.py",))),
    ("FORBIDDEN_FILES", dict(forbidden=("dv_harness/../dv_harness/engine.py",))),
    ("INPUT_EVIDENCE_REFS", dict(inputs=["dv_harness/module_a.py/../engine.py"])),
    ("INPUT_EVIDENCE_REFS", dict(inputs=["../secret.py"])),
])
def test_traversal_bearing_boundary_declarations_are_rejected_at_build(repo, field, scope_kw):
    with pytest.raises(HandoffBuildError) as exc:
        _hand(repo, **scope_kw)
    assert exc.value.reason == "UNSAFE_PATH_DECLARATION"
    assert any(d["field"] == field for d in exc.value.detail["declarations"])


def test_traversal_bearing_declaration_in_a_stored_handoff_is_rejected_at_parse(repo):
    md = h_to(_hand(repo)).replace("- dv_harness/engine.py", "- dv_harness/module_a.py/../engine.py", 1)
    with pytest.raises(HandoffParseError) as exc:
        h_from(md)
    assert exc.value.reason == "UNSAFE_PATH_DECLARATION"


def test_input_evidence_line_suffix_is_still_allowed_in_declarations(repo):
    h = _hand(repo, inputs=["dv_harness/module_a.py:10-20"])
    assert "dv_harness/module_a.py" in read_boundary(h).allowed_path_prefixes


def test_governance_ref_traversal_is_invalid(repo):
    (repo / "GOV.md").write_text("# gov\n", encoding="utf-8")
    h = dataclasses.replace(_hand(repo), required_governance_refs=("dv_harness/../GOV.md",))
    v = validate_result(h, _res(), root=repo)
    assert v.governance_validation_status == "VALIDATED"  # canonical form resolves inside the root
    h2 = dataclasses.replace(_hand(repo), required_governance_refs=("../GOV.md",))
    assert validate_result(h2, _res(), root=repo).governance_validation_status == "INVALID_REF"


# ================================================================ N3: empty scalar

def test_empty_and_none_scalars_are_distinct_after_a_round_trip():
    r = _res(result_version="")
    assert r_from(r_to(r)).result_version == ""
    assert codec.parse_scalar(codec.render_scalar(None), True) is None
    assert codec.parse_scalar(codec.render_scalar(""), True) == ""


@pytest.mark.parametrize("value", ["(empty)", "(none)", " (empty)", "(empty) ", "", "x"])
def test_literal_token_text_survives_as_a_scalar(value):
    assert codec.parse_scalar(codec.render_scalar(value), True) == value


def test_empty_scalar_in_a_handoff_round_trips(repo):
    h = dataclasses.replace(_hand(repo), independence_requirement="")
    assert h_from(h_to(h)).independence_requirement == ""


def test_raw_documents_keep_their_verbatim_meaning_for_the_empty_token():
    assert codec.parse_scalar("(empty)", False) == "(empty)"


# ================================================================ N4: document identity

def test_wrong_title_containing_the_schema_token_is_not_a_result_document():
    md = r_to(_res()).replace("# L5DGVA_MODEL_RESULT_V1", "# WRONG-L5DGVA_MODEL_RESULT_V1", 1)
    with pytest.raises(ResultParseError) as exc:
        r_from(md)
    assert exc.value.reason == "NOT_A_RESULT_DOCUMENT"


def test_schema_token_only_inside_content_is_not_a_result_document():
    with pytest.raises(ResultParseError) as exc:
        r_from("some text mentioning L5DGVA_MODEL_RESULT_V1\n\n## TASK_ID\nT-1\n")
    assert exc.value.reason == "NOT_A_RESULT_DOCUMENT"


def test_second_title_is_rejected():
    md = r_to(_res()).replace("# L5DGVA_MODEL_RESULT_V1\n", "# L5DGVA_MODEL_RESULT_V1\n# ANOTHER TITLE\n", 1)
    with pytest.raises(ResultParseError) as exc:
        r_from(md)
    assert exc.value.reason == "DUPLICATE_TITLE"


def test_duplicate_encoding_marker_is_rejected():
    m = codec.ENCODING_MARKER
    md = r_to(_res()).replace(m, m + "\n" + m, 1)
    with pytest.raises(ResultParseError) as exc:
        r_from(md)
    assert exc.value.reason == "DUPLICATE_ENCODING_MARKER"


def test_marker_before_the_title_or_a_section_before_the_title_is_rejected():
    body = r_to(_res())
    with pytest.raises(ResultParseError):
        r_from(codec.ENCODING_MARKER + "\n" + body)
    with pytest.raises(ResultParseError):
        r_from("## TASK_ID\nT-1\n\n" + body)


def test_marker_text_inside_a_value_is_content_not_structure():
    r = _res(findings=[codec.ENCODING_MARKER, "# L5DGVA_MODEL_RESULT_V1"])
    assert list(r_from(r_to(r)).findings) == [codec.ENCODING_MARKER, "# L5DGVA_MODEL_RESULT_V1"]


def test_handoff_wrong_title_is_not_a_handoff_document(repo):
    md = h_to(_hand(repo)).replace("# L5DGVA_MODEL_HANDOFF_V1", "# X-L5DGVA_MODEL_HANDOFF_V1", 1)
    with pytest.raises(HandoffParseError) as exc:
        h_from(md)
    assert exc.value.reason == "NOT_A_HANDOFF_DOCUMENT"


# ================================================================ N2: content identity

def _export(repo: Path, task="T-1"):
    wf.export_handoff(repo, _hand(repo, task=task))
    return repo / ".dv-harness/model_handoffs" / task / "RESULT_V1.md"


def _rows(repo, task="T-1"):
    p = wf._registry_path(repo)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["task_id"] == task]


def test_registry_and_state_record_the_content_digest(repo):
    rp = _export(repo)
    rp.write_text(r_to(_res()), encoding="utf-8")
    out = wf.import_result(repo, "T-1", rp)
    sha = hashlib.sha256(rp.read_bytes()).hexdigest()
    assert out.result_sha256 == sha
    assert _rows(repo)[0]["result_sha256"] == sha
    assert wf._load_state(repo, "T-1")["result_sha256"] == sha


def _crash_at_consumed(monkeypatch):
    real = wf._save_state

    def flaky(root, tid, st):
        if st.get("state") == wf.STATE_RESULT_CONSUMED:
            raise OSError("disk full")
        return real(root, tid, st)

    monkeypatch.setattr(wf, "_save_state", flaky)
    return real


def test_same_path_same_status_but_different_content_is_a_conflict_after_partial_consumption(repo, monkeypatch):
    rp = _export(repo)
    rp.write_text(r_to(_res(findings=["original"])), encoding="utf-8")
    real = _crash_at_consumed(monkeypatch)
    with pytest.raises(OSError):
        wf.import_result(repo, "T-1", rp)
    monkeypatch.setattr(wf, "_save_state", real)
    rp.write_text(r_to(_res(findings=["REPLACEMENT with the same status"])), encoding="utf-8")
    out = wf.import_result(repo, "T-1", rp)
    assert out.state == wf.STATE_RESULT_REJECTED and out.parse_error == "CONSUMPTION_CONFLICT"
    assert len(_rows(repo)) == 1
    # the ORIGINAL content is still retryable to completion (the conflict mutated nothing)
    rp.write_text(r_to(_res(findings=["original"])), encoding="utf-8")
    assert wf.import_result(repo, "T-1", rp).state == wf.STATE_RESULT_CONSUMED


def test_conflict_is_detected_from_the_registry_digest_alone(repo):
    rp = _export(repo)
    rp.write_text(r_to(_res(findings=["original"])), encoding="utf-8")
    wf.import_result(repo, "T-1", rp)
    st = wf._load_state(repo, "T-1")
    st["state"] = wf.STATE_RESULT_ACCEPTED  # simulate a lost final state save
    st.pop("accepted_result_sha256", None)
    st.pop("result_sha256", None)
    wf._save_state(repo, "T-1", st)
    rp.write_text(r_to(_res(findings=["different"])), encoding="utf-8")
    assert wf.import_result(repo, "T-1", rp).parse_error == "CONSUMPTION_CONFLICT"


def test_replay_with_a_different_file_after_consumption_is_flagged_not_silently_cached(repo):
    rp = _export(repo)
    rp.write_text(r_to(_res()), encoding="utf-8")
    wf.import_result(repo, "T-1", rp)
    same = wf.import_result(repo, "T-1", rp)
    assert same.state == wf.STATE_RESULT_CONSUMED and same.parse_error is None
    rp.write_text(r_to(_res(findings=["tampered"])), encoding="utf-8")
    differs = wf.import_result(repo, "T-1", rp)
    assert differs.state == wf.STATE_RESULT_CONSUMED and differs.parse_error == "RESULT_CONTENT_DIFFERS_FROM_CONSUMED"
    assert len(_rows(repo)) == 1


def test_registry_gets_the_digest_column_by_additive_migration_without_losing_rows(repo):
    reg = wf._registry_path(repo)
    reg.parent.mkdir(parents=True, exist_ok=True)
    legacy = ["task_id", "target_model", "task_type", "state", "result_status", "handoff_path", "result_path",
              "consumed_at_head", "question_id"]
    with open(reg, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=legacy)
        w.writeheader()
        w.writerow({k: f"legacy-{k}" for k in legacy})
    rp = _export(repo)
    rp.write_text(r_to(_res()), encoding="utf-8")
    wf.import_result(repo, "T-1", rp)
    with open(reg, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2 and "result_sha256" in rows[0]
    assert rows[0]["task_id"] == "legacy-task_id" and rows[0]["result_sha256"] == ""
    assert rows[1]["task_id"] == "T-1" and len(rows[1]["result_sha256"]) == 64
    assert all(None not in r for r in rows)  # no structurally malformed row


def test_the_hashed_bytes_are_the_parsed_bytes(repo, monkeypatch):
    rp = _export(repo)
    first = r_to(_res(findings=["first"]))
    rp.write_text(first, encoding="utf-8")
    first_bytes = rp.read_bytes()  # the exact on-disk bytes (Windows text mode writes CRLF)
    real_parse = wf._result_mod.from_markdown

    def swap_after_read(text):  # the file changes AFTER the bytes were read: identity must still match what was parsed
        rp.write_text(r_to(_res(findings=["second"])), encoding="utf-8")
        return real_parse(text)

    monkeypatch.setattr(wf._result_mod, "from_markdown", swap_after_read)
    out = wf.import_result(repo, "T-1", rp)
    assert out.result_sha256 == hashlib.sha256(first_bytes).hexdigest()
    assert list(out.result.findings) == ["first"]


# ================================================================ N6: interrupted import + concurrency

def test_exception_mid_consumption_persists_an_auto_retry_next_action(repo, monkeypatch):
    rp = _export(repo)
    rp.write_text(r_to(_res()), encoding="utf-8")
    monkeypatch.setattr(wf, "_append_registry", lambda *a, **k: (_ for _ in ()).throw(OSError("registry down")))
    with pytest.raises(OSError):
        wf.import_result(repo, "T-1", rp)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_ACCEPTED
    rec = ec.read_next_action(repo, "T-1")
    assert rec["next_action"] == "AUTO_RETRY_INTERRUPTED_IMPORT" and rec["auto_actionable"] is True
    assert rec["human_action_required"] == "NO"


def test_retry_after_the_interruption_completes_and_replaces_the_next_action(repo, monkeypatch):
    rp = _export(repo)
    rp.write_text(r_to(_res()), encoding="utf-8")
    real = wf._append_registry
    monkeypatch.setattr(wf, "_append_registry", lambda *a, **k: (_ for _ in ()).throw(OSError("registry down")))
    with pytest.raises(OSError):
        wf.import_result(repo, "T-1", rp)
    monkeypatch.setattr(wf, "_append_registry", real)
    assert wf.import_result(repo, "T-1", rp).state == wf.STATE_RESULT_CONSUMED
    assert ec.read_next_action(repo, "T-1")["next_action"] == "AUTO_REMEDIATE_CONFIRMED_FINDINGS"
    assert len(_rows(repo)) == 1


def test_failure_of_the_next_action_write_never_masks_the_original_error(repo, monkeypatch):
    rp = _export(repo)
    rp.write_text(r_to(_res()), encoding="utf-8")
    monkeypatch.setattr(wf, "_append_registry", lambda *a, **k: (_ for _ in ()).throw(OSError("registry down")))
    monkeypatch.setattr(ec, "persist_next_action", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full too")))
    with pytest.raises(OSError, match="registry down"):
        wf.import_result(repo, "T-1", rp)


def test_concurrent_import_is_refused_with_no_side_effects(repo):
    rp = _export(repo)
    rp.write_text(r_to(_res(result_status="HUMAN_DECISION_REQUIRED", human_decisions_required=["q?"])), encoding="utf-8")
    lock = repo / ".dv-harness/model_handoffs/T-1/import.lock"
    token = wf._acquire_lock(lock)  # another importer holds the task
    assert token is not None
    try:
        out = wf.import_result(repo, "T-1", rp)
        assert out.parse_error == "IMPORT_IN_PROGRESS" and not out.consumed
        assert _rows(repo) == [] and QuestionQueueStore(repo).list_questions() == []
        assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT
    finally:
        wf._release_lock(lock, token)
    assert wf.import_result(repo, "T-1", rp).state == wf.STATE_RESULT_CONSUMED  # released -> proceeds


def test_stale_lock_from_a_crashed_importer_is_broken(repo):
    rp = _export(repo)
    rp.write_text(r_to(_res()), encoding="utf-8")
    lock = repo / ".dv-harness/model_handoffs/T-1/import.lock"
    lock.write_text("999999", encoding="utf-8")
    old = 1_000_000_000
    os.utime(lock, (old, old))
    assert wf.import_result(repo, "T-1", rp).state == wf.STATE_RESULT_CONSUMED
    assert not lock.exists()


def test_the_lock_is_released_even_when_the_import_raises(repo, monkeypatch):
    rp = _export(repo)
    rp.write_text(r_to(_res()), encoding="utf-8")
    monkeypatch.setattr(wf, "_append_registry", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(OSError):
        wf.import_result(repo, "T-1", rp)
    assert not (repo / ".dv-harness/model_handoffs/T-1/import.lock").exists()


def test_manual_ingestion_is_refused_while_the_task_ingestion_lock_is_held(repo):
    rp = _export(repo)
    rp.write_text(r_to(_res()), encoding="utf-8")
    lock = repo / ".dv-harness/model_handoffs/T-1/ingestion.lock"
    token = wf._acquire_lock(lock)
    assert token is not None
    try:
        res = ri.ingest_result_file(repo, "T-1", rp, trigger="MANUAL")
        assert res.action == "LOCKED" and wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT
        rc = wf.execute_verb(["import", "--task-id", "T-1", "--result-file", str(rp), "--root", str(repo)])
        assert rc == 1
    finally:
        wf._release_lock(lock, token)


# ================================================================ production artifacts keep working

@pytest.mark.parametrize("task", ["M7-V1-CODEX-REVIEW-001", "M7-V1-CODEX-REVIEW-002", "M7-V1-CODEX-REVIEW-003"])
def test_stored_production_handoffs_still_parse_under_the_stricter_rules(task):
    p = CANONICAL_ROOT / ".dv-harness/model_handoffs" / task / "HANDOFF_V1.md"
    if not p.exists():
        pytest.skip("not present")
    assert h_from(p.read_text(encoding="utf-8")).task_id == task


@pytest.mark.parametrize("task", ["M7-V1-CODEX-REVIEW-002", "M7-V1-CODEX-REVIEW-003"])
def test_real_returned_results_still_validate_against_their_own_handoffs_unmodified(task):
    d = CANONICAL_ROOT / ".dv-harness/model_handoffs" / task
    if not (d / "RESULT_V1.md").exists():
        pytest.skip("not present")
    h = h_from((d / "HANDOFF_V1.md").read_text(encoding="utf-8"))
    r = r_from((d / "RESULT_V1.md").read_text(encoding="utf-8"))
    v = validate_result(h, r, root=CANONICAL_ROOT, own_result_path=f".dv-harness/model_handoffs/{task}/RESULT_V1.md")
    assert r.result_status == "FAIL"
    assert v.accepted is True, v.to_dict()
