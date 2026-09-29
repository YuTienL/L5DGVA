"""Real tests for dv_harness/vip_version_drift_detection.py -- cross-environment
VIP version drift detection across a project's MULTIPLE subsystem environments.

Every fixture builds a REAL $DESIGNWARE_HOME tree (the same
`dw_vip_setup`-shaped layout `test_env_manifest_fact_sources.py`'s own
`fake_designware_home` fixture uses) and a REAL, schema-valid env.manifest.json
via `env_manifest.generate_and_write()` -- never a hand-typed manifest dict.
"""
import json
import subprocess
import sys

import pytest

from dv_harness import env_manifest
from dv_harness import environment_mode_router
from dv_harness import vip_version_drift_detection as vvd


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _make_designware_home(base, package="usb_svt", version="R-2020.12"):
    """A real $DESIGNWARE_HOME tree: <base>/vip/svt/<package>/<version>/doc/...
    Mirrors test_env_manifest_fact_sources.py's own fake_designware_home
    fixture exactly, parameterized so different subsystems can be pointed at
    different real installed versions of the "same" package."""
    home = base
    pkg_dir = home / "vip" / "svt" / package / version
    (pkg_dir / "doc").mkdir(parents=True)
    (pkg_dir / "doc" / f"{package}_release_notes.txt").write_text(
        f"{package} {version} release notes (synthesized test fixture)\n", encoding="utf-8")
    return home


def _make_designware_home_no_version(base, package="usb_svt"):
    """A package directory with NO version sub-directory -- the real, honest
    version=None case scan_designware_home() itself documents."""
    home = base
    pkg_dir = home / "vip" / "svt" / package
    (pkg_dir / "doc").mkdir(parents=True)
    (pkg_dir / "doc" / f"{package}_release_notes.txt").write_text(
        f"{package} release notes, no version dir (synthesized test fixture)\n", encoding="utf-8")
    return home


def _write_manifest(out_path, designware_home):
    """A real, schema-valid env.manifest.json built entirely from a real
    designware_home scan -- every other layer honestly NOT_AVAILABLE, which
    is fine: this module only ever reads vip_config.vip_release."""
    env_manifest.generate_and_write(out_path, designware_home=designware_home)
    return out_path


@pytest.fixture()
def subsystem_a_manifest(tmp_path):
    dw = _make_designware_home(tmp_path / "dw_a", "usb_svt", "R-2019.06")
    out = tmp_path / "subsystem_a" / "env.manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    return _write_manifest(out, dw)


@pytest.fixture()
def subsystem_b_manifest_same_version(tmp_path):
    dw = _make_designware_home(tmp_path / "dw_b_same", "usb_svt", "R-2019.06")
    out = tmp_path / "subsystem_b_same" / "env.manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    return _write_manifest(out, dw)


@pytest.fixture()
def subsystem_b_manifest_drifted(tmp_path):
    dw = _make_designware_home(tmp_path / "dw_b_drift", "usb_svt", "R-2020.12")
    out = tmp_path / "subsystem_b_drift" / "env.manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    return _write_manifest(out, dw)


# ---------------------------------------------------------------------------
# load_subsystem_vip_release_fact
# ---------------------------------------------------------------------------

def test_load_subsystem_vip_release_fact_scanned(subsystem_a_manifest):
    fact = vvd.load_subsystem_vip_release_fact("subsystem_a", subsystem_a_manifest)
    assert fact["status"] == vvd.STATUS_SCANNED
    assert fact["reason"] is None
    assert fact["subsystem"] == "subsystem_a"
    names_versions = {(p["name"], p["version"]) for p in fact["packages"]}
    assert ("usb_svt", "R-2019.06") in names_versions


def test_load_subsystem_vip_release_fact_missing_file(tmp_path):
    fact = vvd.load_subsystem_vip_release_fact(
        "ghost", tmp_path / "does_not_exist" / "env.manifest.json")
    assert fact["status"] == vvd.STATUS_SUBSYSTEM_NOT_AVAILABLE
    assert "could not be read" in fact["reason"]
    assert fact["packages"] == []


def test_load_subsystem_vip_release_fact_schema_invalid(tmp_path):
    bad = tmp_path / "bad.manifest.json"
    bad.write_text(json.dumps({"not": "a real manifest"}), encoding="utf-8")
    fact = vvd.load_subsystem_vip_release_fact("bad_subsystem", bad)
    assert fact["status"] == vvd.STATUS_SUBSYSTEM_NOT_AVAILABLE
    assert "failed schema validation" in fact["reason"]


def test_load_subsystem_vip_release_fact_vip_release_not_scanned(tmp_path, monkeypatch):
    monkeypatch.delenv(env_manifest.DESIGNWARE_HOME_ENV, raising=False)
    out = tmp_path / "env.manifest.json"
    env_manifest.generate_and_write(out)  # no designware_home at all -> NOT_AVAILABLE layer
    fact = vvd.load_subsystem_vip_release_fact("no_dw", out)
    assert fact["status"] == vvd.STATUS_SUBSYSTEM_NOT_AVAILABLE
    # the manifest's OWN real reason must be carried through verbatim, never guessed
    manifest = env_manifest.load_env_manifest(out)
    assert fact["reason"] == manifest["vip_config"]["vip_release"]["reason"]
    assert "is not set" in fact["reason"]


def test_load_subsystem_vip_release_fact_relative_path_resolved_against_root(
        tmp_path, subsystem_a_manifest):
    rel = subsystem_a_manifest.relative_to(tmp_path)
    fact = vvd.load_subsystem_vip_release_fact("subsystem_a", rel, project_root=tmp_path)
    assert fact["status"] == vvd.STATUS_SCANNED


# ---------------------------------------------------------------------------
# find_package_version_drift -- pure function over subsystem facts
# ---------------------------------------------------------------------------

def _scanned_fact(subsystem, packages):
    return {"subsystem": subsystem, "manifest_path": f"{subsystem}.json",
            "status": vvd.STATUS_SCANNED, "reason": None,
            "designware_home": None, "packages": packages}


def _pkg(name, version, install_path="/dw/pkg"):
    return {"name": name, "version": version, "install_path": install_path,
            "release_notes": {"path": None, "sha256": None, "bytes": None},
            "feature_matrix": {"path": None, "sha256": None, "bytes": None}}


def test_find_package_version_drift_detects_conflicting_versions():
    facts = [
        _scanned_fact("A", [_pkg("usb_svt", "R-2019.06", "/dw/a")]),
        _scanned_fact("B", [_pkg("usb_svt", "R-2020.12", "/dw/b")]),
    ]
    findings = vvd.find_package_version_drift(facts)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["package_name"] == "usb_svt"
    assert finding["distinct_versions"] == ["R-2019.06", "R-2020.12"]
    subsystems_cited = {occ["subsystem"] for occ in finding["occurrences"]}
    assert subsystems_cited == {"A", "B"}
    versions_cited = {occ["version"] for occ in finding["occurrences"]}
    assert versions_cited == {"R-2019.06", "R-2020.12"}


def test_find_package_version_drift_no_conflict_when_versions_match():
    facts = [
        _scanned_fact("A", [_pkg("usb_svt", "R-2019.06")]),
        _scanned_fact("B", [_pkg("usb_svt", "R-2019.06")]),
    ]
    assert vvd.find_package_version_drift(facts) == []


def test_find_package_version_drift_excludes_single_subsystem_package():
    """A package used by only ONE subsystem has nothing to compare against --
    this is not drift, it is a package only one subsystem happens to use."""
    facts = [
        _scanned_fact("A", [_pkg("amba_svt", "Q-2019.06")]),
        _scanned_fact("B", [_pkg("usb_svt", "R-2020.12")]),
    ]
    assert vvd.find_package_version_drift(facts) == []


def test_find_package_version_drift_none_version_counts_as_distinct():
    """A package directory with no version level (version=None) is a real,
    distinct fact -- never silently treated as equal to a real version
    string, and never silently dropped from comparison."""
    facts = [
        _scanned_fact("A", [_pkg("usb_svt", None)]),
        _scanned_fact("B", [_pkg("usb_svt", "R-2020.12")]),
    ]
    findings = vvd.find_package_version_drift(facts)
    assert len(findings) == 1
    assert findings[0]["distinct_versions"] == ["NO_VERSION_DIRECTORY", "R-2020.12"]
    none_occurrences = [o for o in findings[0]["occurrences"] if o["version"] is None]
    assert len(none_occurrences) == 1
    assert none_occurrences[0]["subsystem"] == "A"


def test_find_package_version_drift_ignores_unavailable_subsystems():
    """A NOT_AVAILABLE subsystem contributes no packages at all to the
    comparison -- it cannot manufacture a finding out of evidence it never
    had."""
    facts = [
        _scanned_fact("A", [_pkg("usb_svt", "R-2019.06")]),
        {"subsystem": "B", "manifest_path": "b.json", "status": vvd.STATUS_SUBSYSTEM_NOT_AVAILABLE,
         "reason": "no designware home", "designware_home": None, "packages": []},
    ]
    assert vvd.find_package_version_drift(facts) == []


def test_find_package_version_drift_normalizes_package_name_case():
    facts = [
        _scanned_fact("A", [_pkg("USB_SVT", "R-2019.06")]),
        _scanned_fact("B", [_pkg("usb_svt", "R-2020.12")]),
    ]
    findings = vvd.find_package_version_drift(facts)
    assert len(findings) == 1
    assert findings[0]["package_name"] == "usb_svt"


# ---------------------------------------------------------------------------
# aggregate_vip_version_drift -- overall status, worst-wins honesty
# ---------------------------------------------------------------------------

def test_overall_status_not_available_zero_subsystems(tmp_path):
    report = vvd.aggregate_vip_version_drift(tmp_path, subsystem_manifests={})
    assert report["status"] == vvd.STATUS_NOT_AVAILABLE
    assert "no subsystem environments were supplied" in report["reason"]
    assert report["findings"] == []
    assert report["subsystems"] == []


def test_overall_status_not_available_single_subsystem(tmp_path, subsystem_a_manifest):
    report = vvd.aggregate_vip_version_drift(
        tmp_path, subsystem_manifests={"A": str(subsystem_a_manifest)})
    assert report["status"] == vvd.STATUS_NOT_AVAILABLE
    assert "fewer than two" in report["reason"]


def test_overall_status_no_drift(tmp_path, subsystem_a_manifest, subsystem_b_manifest_same_version):
    report = vvd.aggregate_vip_version_drift(
        tmp_path,
        subsystem_manifests={"A": str(subsystem_a_manifest),
                              "B": str(subsystem_b_manifest_same_version)})
    assert report["status"] == vvd.STATUS_NO_DRIFT
    assert report["findings"] == []
    assert report["subsystem_count"] == 2


def test_overall_status_drift_detected(tmp_path, subsystem_a_manifest, subsystem_b_manifest_drifted):
    report = vvd.aggregate_vip_version_drift(
        tmp_path,
        subsystem_manifests={"A": str(subsystem_a_manifest),
                              "B": str(subsystem_b_manifest_drifted)})
    assert report["status"] == vvd.STATUS_DRIFT_DETECTED
    assert len(report["findings"]) == 1
    assert "usb_svt" in report["reason"]


def test_overall_status_incomplete_evidence_never_fabricates_no_drift(
        tmp_path, subsystem_a_manifest, subsystem_b_manifest_same_version):
    """THE REQUIRED NEGATIVE CONTROL: two subsystems agree, but a third
    declared subsystem's own env.manifest.json cannot be read at all -- the
    overall verdict must be INCOMPLETE_EVIDENCE, never a fabricated
    NO_DRIFT, because that unchecked subsystem might have drifted too."""
    report = vvd.aggregate_vip_version_drift(
        tmp_path,
        subsystem_manifests={
            "A": str(subsystem_a_manifest),
            "B": str(subsystem_b_manifest_same_version),
            "C": str(tmp_path / "no_such_manifest.json"),
        })
    assert report["status"] == vvd.STATUS_INCOMPLETE_EVIDENCE
    assert report["findings"] == []
    assert "1 of 3" in report["reason"]
    c_fact = next(s for s in report["subsystems"] if s["subsystem"] == "C")
    assert c_fact["status"] == vvd.STATUS_SUBSYSTEM_NOT_AVAILABLE


def test_overall_status_drift_detected_outranks_incomplete_evidence(
        tmp_path, subsystem_a_manifest, subsystem_b_manifest_drifted):
    """A real conflicting-version finding is reported regardless of how many
    OTHER subsystems could not be checked -- DRIFT_DETECTED outranks
    INCOMPLETE_EVIDENCE, worst-wins."""
    report = vvd.aggregate_vip_version_drift(
        tmp_path,
        subsystem_manifests={
            "A": str(subsystem_a_manifest),
            "B": str(subsystem_b_manifest_drifted),
            "C": str(tmp_path / "no_such_manifest.json"),
        })
    assert report["status"] == vvd.STATUS_DRIFT_DETECTED
    assert len(report["findings"]) == 1


def test_aggregate_vip_version_drift_malformed_subsystem_manifests_raises(tmp_path):
    with pytest.raises(vvd.VipVersionDriftDetectionError):
        vvd.aggregate_vip_version_drift(tmp_path, subsystem_manifests=["not", "a", "dict"])


# ---------------------------------------------------------------------------
# real registry discovery -- environment_mode_router.
# read_registered_subsystem_entries()
# ---------------------------------------------------------------------------

def _write_registry(root, entries):
    path = environment_mode_router.registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"subsystems": entries}), encoding="utf-8")
    return path


def test_discover_subsystem_manifest_paths_reads_real_registry(
        tmp_path, subsystem_a_manifest, subsystem_b_manifest_drifted):
    _write_registry(tmp_path, [
        {"name": "subsystem_a", "environment_manifest": str(subsystem_a_manifest),
         "release_sha": "deadbeef", "qualification_state": "SMOKE_QUALIFIED",
         "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"},
        {"name": "subsystem_b", "environment_manifest": str(subsystem_b_manifest_drifted),
         "release_sha": "cafef00d", "qualification_state": "SMOKE_QUALIFIED",
         "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"},
        # an incomplete entry -- no name -- must be skipped, never guessed
        {"environment_manifest": "somewhere.json"},
        # an incomplete entry -- no environment_manifest -- must be skipped
        {"name": "no_manifest_declared"},
    ])
    mapping = vvd.discover_subsystem_manifest_paths(tmp_path)
    assert mapping == {
        "subsystem_a": str(subsystem_a_manifest),
        "subsystem_b": str(subsystem_b_manifest_drifted),
    }


def test_discover_subsystem_manifest_paths_empty_registry(tmp_path):
    assert vvd.discover_subsystem_manifest_paths(tmp_path) == {}


def test_aggregate_vip_version_drift_uses_registry_when_no_explicit_manifests(
        tmp_path, subsystem_a_manifest, subsystem_b_manifest_drifted):
    _write_registry(tmp_path, [
        {"name": "subsystem_a", "environment_manifest": str(subsystem_a_manifest),
         "release_sha": "x", "qualification_state": "SMOKE_QUALIFIED",
         "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"},
        {"name": "subsystem_b", "environment_manifest": str(subsystem_b_manifest_drifted),
         "release_sha": "y", "qualification_state": "SMOKE_QUALIFIED",
         "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"},
    ])
    report = vvd.aggregate_vip_version_drift(tmp_path)
    assert report["source"] == "subsystem_environment_registry"
    assert report["status"] == vvd.STATUS_DRIFT_DETECTED
    assert report["subsystem_count"] == 2


def test_aggregate_vip_version_drift_explicit_manifests_overrides_registry(
        tmp_path, subsystem_a_manifest, subsystem_b_manifest_same_version,
        subsystem_b_manifest_drifted):
    """An explicit caller-declared manifest mapping is a real, distinct
    caller fact and REPLACES registry discovery entirely -- it is never
    merged with it."""
    # registry points at the CLEAN pair (no drift)
    _write_registry(tmp_path, [
        {"name": "subsystem_a", "environment_manifest": str(subsystem_a_manifest),
         "release_sha": "x", "qualification_state": "SMOKE_QUALIFIED",
         "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"},
        {"name": "subsystem_b", "environment_manifest": str(subsystem_b_manifest_same_version),
         "release_sha": "y", "qualification_state": "SMOKE_QUALIFIED",
         "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"},
    ])
    # explicit override points at the DRIFTED pair
    report = vvd.aggregate_vip_version_drift(
        tmp_path,
        subsystem_manifests={"A": str(subsystem_a_manifest),
                              "B": str(subsystem_b_manifest_drifted)})
    assert report["source"] == "caller_declared"
    assert report["status"] == vvd.STATUS_DRIFT_DETECTED


# ---------------------------------------------------------------------------
# vocabulary-collision guard -- proven to have real detection power
# ---------------------------------------------------------------------------

def test_status_vocabulary_disjoint_from_models_status():
    vvd.assert_no_status_vocabulary_collision()  # must not raise


def test_status_vocabulary_guard_has_real_detection_power():
    with pytest.raises(AssertionError):
        vvd.assert_no_status_vocabulary_collision(("PASS", "DRIFT_DETECTED"))


# ---------------------------------------------------------------------------
# markdown rendering
# ---------------------------------------------------------------------------

def test_render_report_markdown_includes_findings(
        tmp_path, subsystem_a_manifest, subsystem_b_manifest_drifted):
    report = vvd.aggregate_vip_version_drift(
        tmp_path,
        subsystem_manifests={"A": str(subsystem_a_manifest),
                              "B": str(subsystem_b_manifest_drifted)})
    text = vvd.render_report_markdown(report)
    assert "DRIFT_DETECTED" in text
    assert "usb_svt" in text
    assert "R-2019.06" in text
    assert "R-2020.12" in text


def test_render_report_markdown_no_findings_note(
        tmp_path, subsystem_a_manifest, subsystem_b_manifest_same_version):
    report = vvd.aggregate_vip_version_drift(
        tmp_path,
        subsystem_manifests={"A": str(subsystem_a_manifest),
                              "B": str(subsystem_b_manifest_same_version)})
    text = vvd.render_report_markdown(report)
    assert "no conflicting VIP package versions found" in text


# ---------------------------------------------------------------------------
# CLI (real subprocess)
# ---------------------------------------------------------------------------

def test_cli_no_drift_exit_0(tmp_path, subsystem_a_manifest, subsystem_b_manifest_same_version):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_version_drift_detection",
         "--root", str(tmp_path),
         "--manifests", f"A={subsystem_a_manifest},B={subsystem_b_manifest_same_version}",
         "--json"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["status"] == "NO_DRIFT"


def test_cli_drift_detected_exit_1(tmp_path, subsystem_a_manifest, subsystem_b_manifest_drifted):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_version_drift_detection",
         "--root", str(tmp_path),
         "--manifests", f"A={subsystem_a_manifest},B={subsystem_b_manifest_drifted}",
         "--json"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stderr
    out = json.loads(proc.stdout)
    assert out["status"] == "DRIFT_DETECTED"
    assert out["findings"][0]["package_name"] == "usb_svt"


def test_cli_not_available_exit_2(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_version_drift_detection",
         "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2, proc.stderr
    assert "NOT_AVAILABLE" in proc.stdout


def test_cli_malformed_manifests_arg_exit_2(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_version_drift_detection",
         "--root", str(tmp_path), "--manifests", "not_a_pair_at_all"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "not name=path" in proc.stderr


def test_cli_default_text_output(tmp_path, subsystem_a_manifest, subsystem_b_manifest_drifted):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_version_drift_detection",
         "--root", str(tmp_path),
         "--manifests", f"A={subsystem_a_manifest},B={subsystem_b_manifest_drifted}"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stderr
    assert "VIP Version Drift Report" in proc.stdout
    assert "usb_svt" in proc.stdout
