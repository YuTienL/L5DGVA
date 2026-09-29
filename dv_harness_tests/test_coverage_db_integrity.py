"""Tests for dv_harness/coverage_db_integrity.py -- the coverage database
merge integrity gate.

Fixtures build REAL files on disk: a synthetic coverage DB (a small
directory tree of real files, standing in for whatever a real coverage tool
merges), and a REAL, schema-valid env.manifest.json produced by the real
`env_manifest.generate_env_manifest()` / `save_env_manifest()` pipeline
against a synthetic $DESIGNWARE_HOME tree (the same fixture shape
`test_env_manifest_fact_sources.py` already uses for
`scan_designware_home()`). Nothing is mocked for the positive paths; every
negative control mutates one real thing (a byte of coverage-DB content, one
recorded VIP version) and asserts the specific finding that mutation should
produce.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import env_manifest
from dv_harness.coverage_db_integrity import (
    CoverageDbIntegrityError,
    FINGERPRINT_MATCH,
    FINGERPRINT_MISMATCH,
    FINGERPRINT_NOT_AVAILABLE,
    MERGE_ALLOWED,
    MERGE_BLOCKED,
    MERGE_NOT_VERIFIABLE,
    TOOL_CONFIG_COMPATIBLE,
    TOOL_CONFIG_INCOMPATIBLE,
    TOOL_CONFIG_NOT_AVAILABLE,
    analyze_coverage_db_merge,
    analyze_tool_config_compatibility,
    collect_coverage_db_files,
    compute_coverage_db_fingerprint,
    execute_verb,
    extract_tool_identity,
    load_merge_request,
    verify_fingerprint_claim,
)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def _make_coverage_db(root: Path, name: str, files: dict) -> Path:
    """A real directory of real files, standing in for one regression run's
    reduced coverage database."""
    db = root / name
    db.mkdir(parents=True)
    for rel, content in files.items():
        p = db / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return db


def _make_designware_home(root: Path, name: str, package: str, version: str) -> Path:
    """A real $DESIGNWARE_HOME tree in the layout scan_designware_home()
    walks -- <root>/vip/svt/<package>/<version>/, one real file inside."""
    home = root / name
    pkg_dir = home / "vip" / "svt" / package / version
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "marker.txt").write_text(f"{package} {version} (synthesized test fixture)\n",
                                          encoding="utf-8")
    return home


def _make_env_manifest(root: Path, name: str, designware_home: Path) -> Path:
    """A REAL, schema-valid env.manifest.json produced by the real
    generation pipeline against a synthetic $DESIGNWARE_HOME -- never a
    hand-typed JSON blob standing in for one."""
    manifest = env_manifest.generate_env_manifest(designware_home=str(designware_home))
    out = root / name
    out.mkdir(parents=True)
    path = out / "env.manifest.json"
    env_manifest.save_env_manifest(manifest, path)
    return path


# --------------------------------------------------------------------------
# (a) content fingerprint
# --------------------------------------------------------------------------

def test_collect_coverage_db_files_directory_and_single_file(tmp_path):
    db = _make_coverage_db(tmp_path, "run_a", {"summary.json": "{}", "sub/detail.txt": "x"})
    files = collect_coverage_db_files(db)
    assert [f.name for f in files] == ["detail.txt", "summary.json"]

    single = tmp_path / "just_one.json"
    single.write_text("{}", encoding="utf-8")
    assert collect_coverage_db_files(single) == [single]

    assert collect_coverage_db_files(tmp_path / "does_not_exist") == []


def test_compute_coverage_db_fingerprint_matches_independent_recomputation(tmp_path):
    """Proves the combination scheme is real (sorted relative path + digest
    folded into one sha256), by rebuilding the fingerprint from scratch in
    the test using plain hashlib -- never asking the module's own function
    whether it agrees with itself."""
    db = _make_coverage_db(tmp_path, "run_a",
                             {"summary.json": '{"categories":[]}', "detail/holes.txt": "none\n"})
    report = compute_coverage_db_fingerprint(db)
    assert report["status"] == "COMPUTED"
    assert report["file_count"] == 2

    h = hashlib.sha256()
    for rel in sorted(["summary.json", "detail/holes.txt"]):
        digest = hashlib.sha256((db / rel).read_bytes()).hexdigest()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\n")
    assert report["fingerprint"] == h.hexdigest()


def test_compute_coverage_db_fingerprint_is_deterministic_across_calls(tmp_path):
    db = _make_coverage_db(tmp_path, "run_a", {"summary.json": "{}"})
    first = compute_coverage_db_fingerprint(db)
    second = compute_coverage_db_fingerprint(db)
    assert first["fingerprint"] == second["fingerprint"]


def test_compute_coverage_db_fingerprint_changes_when_content_changes(tmp_path):
    db = _make_coverage_db(tmp_path, "run_a", {"summary.json": "{}"})
    before = compute_coverage_db_fingerprint(db)["fingerprint"]
    (db / "summary.json").write_text('{"changed": true}', encoding="utf-8")
    after = compute_coverage_db_fingerprint(db)["fingerprint"]
    assert before != after


def test_compute_coverage_db_fingerprint_missing_path_is_not_available(tmp_path):
    report = compute_coverage_db_fingerprint(tmp_path / "nope")
    assert report["status"] == FINGERPRINT_NOT_AVAILABLE
    assert "does not exist" in report["reason"]
    assert report["fingerprint"] is None


def test_compute_coverage_db_fingerprint_empty_directory_is_not_available(tmp_path):
    empty = tmp_path / "empty_run"
    empty.mkdir()
    report = compute_coverage_db_fingerprint(empty)
    assert report["status"] == FINGERPRINT_NOT_AVAILABLE
    assert "no real files" in report["reason"]


def test_compute_coverage_db_fingerprint_reuses_env_manifest_file_ref(tmp_path, monkeypatch):
    """Reuse held as a property, not a claim: patching env_manifest.file_ref
    must change what this module hashes with, the same discipline
    test_env_manifest_generation_provenance.py applies to change_impact.
    resolve_sha()."""
    import dv_harness.coverage_db_integrity as cdi
    db = _make_coverage_db(tmp_path, "run_a", {"summary.json": "{}"})

    calls = []
    real_file_ref = env_manifest.file_ref

    def spy(path):
        calls.append(Path(path))
        return real_file_ref(path)

    monkeypatch.setattr(cdi.env_manifest, "file_ref", spy)
    cdi.compute_coverage_db_fingerprint(db)
    assert calls == [db / "summary.json"]


def test_verify_fingerprint_claim_match(tmp_path):
    db = _make_coverage_db(tmp_path, "run_a", {"summary.json": "{}"})
    claimed = compute_coverage_db_fingerprint(db)["fingerprint"]
    result = verify_fingerprint_claim(db, claimed)
    assert result["status"] == FINGERPRINT_MATCH
    assert result["reason"] is None


def test_verify_fingerprint_claim_mismatch_after_mutation(tmp_path):
    """Negative control: the coverage DB is mutated AFTER its fingerprint was
    claimed (a substituted or altered file) -- must read MISMATCH, never a
    silent MATCH."""
    db = _make_coverage_db(tmp_path, "run_a", {"summary.json": '{"percent": 50}'})
    claimed = compute_coverage_db_fingerprint(db)["fingerprint"]
    (db / "summary.json").write_text('{"percent": 99}', encoding="utf-8")
    result = verify_fingerprint_claim(db, claimed)
    assert result["status"] == FINGERPRINT_MISMATCH
    assert "content changed or was substituted" in result["reason"]
    assert result["computed_fingerprint"] != claimed


def test_verify_fingerprint_claim_no_claim_supplied_is_not_available(tmp_path):
    db = _make_coverage_db(tmp_path, "run_a", {"summary.json": "{}"})
    result = verify_fingerprint_claim(db, None)
    assert result["status"] == FINGERPRINT_NOT_AVAILABLE
    assert "nothing to verify" in result["reason"]


def test_verify_fingerprint_claim_missing_db_is_not_available(tmp_path):
    result = verify_fingerprint_claim(tmp_path / "gone", "deadbeef")
    assert result["status"] == FINGERPRINT_NOT_AVAILABLE


# --------------------------------------------------------------------------
# (b) tool/config identity
# --------------------------------------------------------------------------

def test_extract_tool_identity_recorded_from_real_env_manifest(tmp_path):
    home = _make_designware_home(tmp_path, "dw", "usb_svt", "R-2020.12")
    manifest_path = _make_env_manifest(tmp_path, "run_a", home)
    identity = extract_tool_identity(manifest_path)
    assert identity["status"] == "RECORDED"
    assert identity["tool_version"] == env_manifest.tool_version()
    assert identity["vip_release_status"] == "SCANNED"
    assert identity["vip_packages"] == [{"name": "usb_svt", "version": "R-2020.12"}]


def test_extract_tool_identity_no_manifest_associated_is_not_available():
    identity = extract_tool_identity(None)
    assert identity["status"] == TOOL_CONFIG_NOT_AVAILABLE
    assert "no other producer of tool/config identity" in identity["reason"]


def test_extract_tool_identity_manifest_path_does_not_exist_is_not_available(tmp_path):
    identity = extract_tool_identity(tmp_path / "env.manifest.json")
    assert identity["status"] == TOOL_CONFIG_NOT_AVAILABLE
    assert "does not exist" in identity["reason"]


def test_extract_tool_identity_invalid_manifest_is_not_available(tmp_path):
    """Negative control: a manifest that fails schema validation must never
    be silently treated as identity evidence."""
    bad = tmp_path / "env.manifest.json"
    bad.write_text(json.dumps({"schema_version": "1.2"}), encoding="utf-8")
    identity = extract_tool_identity(bad)
    assert identity["status"] == TOOL_CONFIG_NOT_AVAILABLE
    assert "could not be loaded/validated" in identity["reason"]


def test_analyze_tool_config_compatibility_compatible_when_all_agree(tmp_path):
    home = _make_designware_home(tmp_path, "dw", "usb_svt", "R-2020.12")
    a = extract_tool_identity(_make_env_manifest(tmp_path, "run_a", home))
    b = extract_tool_identity(_make_env_manifest(tmp_path, "run_b", home))
    result = analyze_tool_config_compatibility([a, b])
    assert result["status"] == TOOL_CONFIG_COMPATIBLE
    assert result["mismatches"] == []
    assert result["recorded_count"] == 2


def test_analyze_tool_config_compatibility_incompatible_on_vip_version_mismatch(tmp_path):
    """Negative control: same VIP package, two DIFFERENT recorded versions
    across the entries being merged -- must BLOCK naming the field."""
    home_a = _make_designware_home(tmp_path, "dw_a", "usb_svt", "R-2020.12")
    home_b = _make_designware_home(tmp_path, "dw_b", "usb_svt", "R-2021.06")
    a = extract_tool_identity(_make_env_manifest(tmp_path, "run_a", home_a))
    b = extract_tool_identity(_make_env_manifest(tmp_path, "run_b", home_b))
    result = analyze_tool_config_compatibility([a, b])
    assert result["status"] == TOOL_CONFIG_INCOMPATIBLE
    assert len(result["mismatches"]) == 1
    mismatch = result["mismatches"][0]
    assert mismatch["field"] == "vip_config.vip_release.packages[usb_svt]"
    assert sorted(mismatch["values"]) == ["R-2020.12", "R-2021.06"]


def test_analyze_tool_config_compatibility_not_available_when_none_recorded():
    a = extract_tool_identity(None)
    b = extract_tool_identity(None)
    result = analyze_tool_config_compatibility([a, b])
    assert result["status"] == TOOL_CONFIG_NOT_AVAILABLE
    assert result["recorded_count"] == 0


def test_analyze_tool_config_compatibility_not_available_when_partial(tmp_path):
    """Negative control: one entry recorded identity, one did not -- a
    partial view must not be reported as COMPATIBLE."""
    home = _make_designware_home(tmp_path, "dw", "usb_svt", "R-2020.12")
    a = extract_tool_identity(_make_env_manifest(tmp_path, "run_a", home))
    b = extract_tool_identity(None)
    result = analyze_tool_config_compatibility([a, b])
    assert result["status"] == TOOL_CONFIG_NOT_AVAILABLE
    assert "1 of 2" in result["reason"]


# --------------------------------------------------------------------------
# merge-level analysis
# --------------------------------------------------------------------------

def test_analyze_coverage_db_merge_allowed(tmp_path):
    home = _make_designware_home(tmp_path, "dw", "usb_svt", "R-2020.12")
    db_a = _make_coverage_db(tmp_path, "run_a", {"summary.json": '{"percent": 80}'})
    db_b = _make_coverage_db(tmp_path, "run_b", {"summary.json": '{"percent": 85}'})
    manifest_a = _make_env_manifest(tmp_path, "man_a", home)
    manifest_b = _make_env_manifest(tmp_path, "man_b", home)
    entries = [
        {"label": "run_a", "db_path": str(db_a),
         "claimed_fingerprint": compute_coverage_db_fingerprint(db_a)["fingerprint"],
         "env_manifest_path": str(manifest_a)},
        {"label": "run_b", "db_path": str(db_b),
         "claimed_fingerprint": compute_coverage_db_fingerprint(db_b)["fingerprint"],
         "env_manifest_path": str(manifest_b)},
    ]
    report = analyze_coverage_db_merge(entries)
    assert report["verdict"] == MERGE_ALLOWED
    assert report["entry_count"] == 2
    assert all(e["fingerprint_check"]["status"] == FINGERPRINT_MATCH for e in report["entries"])
    assert report["tool_config_compatibility"]["status"] == TOOL_CONFIG_COMPATIBLE


def test_analyze_coverage_db_merge_blocked_on_fingerprint_mismatch(tmp_path):
    home = _make_designware_home(tmp_path, "dw", "usb_svt", "R-2020.12")
    db_a = _make_coverage_db(tmp_path, "run_a", {"summary.json": '{"percent": 80}'})
    db_b = _make_coverage_db(tmp_path, "run_b", {"summary.json": '{"percent": 85}'})
    manifest_a = _make_env_manifest(tmp_path, "man_a", home)
    manifest_b = _make_env_manifest(tmp_path, "man_b", home)
    claimed_a = compute_coverage_db_fingerprint(db_a)["fingerprint"]
    claimed_b = compute_coverage_db_fingerprint(db_b)["fingerprint"]
    # tamper with run_b's coverage DB AFTER its fingerprint was claimed
    (db_b / "summary.json").write_text('{"percent": 20}', encoding="utf-8")
    entries = [
        {"label": "run_a", "db_path": str(db_a), "claimed_fingerprint": claimed_a,
         "env_manifest_path": str(manifest_a)},
        {"label": "run_b", "db_path": str(db_b), "claimed_fingerprint": claimed_b,
         "env_manifest_path": str(manifest_b)},
    ]
    report = analyze_coverage_db_merge(entries)
    assert report["verdict"] == MERGE_BLOCKED
    assert "run_b" in report["reason"]
    assert "content changed or was substituted" in report["reason"]


def test_analyze_coverage_db_merge_blocked_on_tool_incompatibility(tmp_path):
    home_a = _make_designware_home(tmp_path, "dw_a", "usb_svt", "R-2020.12")
    home_b = _make_designware_home(tmp_path, "dw_b", "usb_svt", "R-2021.06")
    db_a = _make_coverage_db(tmp_path, "run_a", {"summary.json": "{}"})
    db_b = _make_coverage_db(tmp_path, "run_b", {"summary.json": "{}"})
    manifest_a = _make_env_manifest(tmp_path, "man_a", home_a)
    manifest_b = _make_env_manifest(tmp_path, "man_b", home_b)
    entries = [
        {"label": "run_a", "db_path": str(db_a),
         "claimed_fingerprint": compute_coverage_db_fingerprint(db_a)["fingerprint"],
         "env_manifest_path": str(manifest_a)},
        {"label": "run_b", "db_path": str(db_b),
         "claimed_fingerprint": compute_coverage_db_fingerprint(db_b)["fingerprint"],
         "env_manifest_path": str(manifest_b)},
    ]
    report = analyze_coverage_db_merge(entries)
    assert report["verdict"] == MERGE_BLOCKED
    assert "disagreeing tool/VIP versions" in report["reason"]


def test_analyze_coverage_db_merge_not_verifiable_without_claims_or_manifests(tmp_path):
    """The honest middle state: no proven mismatch, but nothing could be
    checked either -- must never read as MERGE_ALLOWED."""
    db_a = _make_coverage_db(tmp_path, "run_a", {"summary.json": "{}"})
    db_b = _make_coverage_db(tmp_path, "run_b", {"summary.json": "{}"})
    entries = [
        {"label": "run_a", "db_path": str(db_a)},
        {"label": "run_b", "db_path": str(db_b)},
    ]
    report = analyze_coverage_db_merge(entries)
    assert report["verdict"] == MERGE_NOT_VERIFIABLE
    assert report["tool_config_compatibility"]["status"] == TOOL_CONFIG_NOT_AVAILABLE
    assert "fingerprint could not be verified" in report["reason"]


def test_analyze_coverage_db_merge_empty_entries_is_not_verifiable():
    report = analyze_coverage_db_merge([])
    assert report["verdict"] == MERGE_NOT_VERIFIABLE
    assert report["entry_count"] == 0


def test_entry_missing_db_path_raises():
    with pytest.raises(CoverageDbIntegrityError) as exc_info:
        analyze_coverage_db_merge([{"label": "no path"}])
    assert exc_info.value.reason == "ENTRY_MISSING_DB_PATH"


def test_load_merge_request_malformed_raises_missing_entries(tmp_path):
    p = tmp_path / "request.json"
    p.write_text(json.dumps({"not_entries": []}), encoding="utf-8")
    with pytest.raises(CoverageDbIntegrityError) as exc_info:
        load_merge_request(p)
    assert exc_info.value.reason == "MERGE_REQUEST_MALFORMED"


def test_load_merge_request_unreadable_raises(tmp_path):
    p = tmp_path / "request.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(CoverageDbIntegrityError) as exc_info:
        load_merge_request(p)
    assert exc_info.value.reason == "MERGE_REQUEST_UNREADABLE"


# --------------------------------------------------------------------------
# real CLI subprocesses
# --------------------------------------------------------------------------

def _run_cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.coverage_db_integrity", *args],
        cwd=cwd or Path(__file__).resolve().parents[1],
        capture_output=True, text=True,
    )


def test_cli_fingerprint_verb(tmp_path):
    db = _make_coverage_db(tmp_path, "run_a", {"summary.json": "{}"})
    proc = _run_cli(["fingerprint", "--db-path", str(db)])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "COMPUTED"
    assert payload["file_count"] == 1


def test_cli_fingerprint_verb_missing_path_exits_not_verifiable(tmp_path):
    proc = _run_cli(["fingerprint", "--db-path", str(tmp_path / "nope")])
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["status"] == FINGERPRINT_NOT_AVAILABLE


def test_cli_check_verb_allowed(tmp_path):
    home = _make_designware_home(tmp_path, "dw", "usb_svt", "R-2020.12")
    db_a = _make_coverage_db(tmp_path, "run_a", {"summary.json": '{"percent": 80}'})
    manifest_a = _make_env_manifest(tmp_path, "man_a", home)
    request = {"entries": [
        {"label": "run_a", "db_path": str(db_a),
         "claimed_fingerprint": compute_coverage_db_fingerprint(db_a)["fingerprint"],
         "env_manifest_path": str(manifest_a)},
    ]}
    req_path = tmp_path / "merge_request.json"
    req_path.write_text(json.dumps(request), encoding="utf-8")
    proc = _run_cli(["check", "--merge-request", str(req_path)])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == MERGE_ALLOWED


def test_cli_check_verb_blocked_on_mismatch(tmp_path):
    db_a = _make_coverage_db(tmp_path, "run_a", {"summary.json": '{"percent": 80}'})
    claimed = compute_coverage_db_fingerprint(db_a)["fingerprint"]
    (db_a / "summary.json").write_text('{"percent": 10}', encoding="utf-8")
    request = {"entries": [{"label": "run_a", "db_path": str(db_a), "claimed_fingerprint": claimed}]}
    req_path = tmp_path / "merge_request.json"
    req_path.write_text(json.dumps(request), encoding="utf-8")
    proc = _run_cli(["check", "--merge-request", str(req_path)])
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == MERGE_BLOCKED


def test_cli_check_verb_not_verifiable_without_claims(tmp_path):
    db_a = _make_coverage_db(tmp_path, "run_a", {"summary.json": "{}"})
    request = {"entries": [{"label": "run_a", "db_path": str(db_a)}]}
    req_path = tmp_path / "merge_request.json"
    req_path.write_text(json.dumps(request), encoding="utf-8")
    proc = _run_cli(["check", "--merge-request", str(req_path)])
    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == MERGE_NOT_VERIFIABLE


def test_cli_check_verb_malformed_request_exits_not_verifiable(tmp_path):
    req_path = tmp_path / "merge_request.json"
    req_path.write_text(json.dumps({"nope": []}), encoding="utf-8")
    proc = _run_cli(["check", "--merge-request", str(req_path)])
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["error"] == "MERGE_REQUEST_MALFORMED"
