"""Tests for dv_harness/dependency_supply_chain.py -- PC-5 dependency /
supply-chain governance.

WHAT THESE TESTS ARE HOLDING THE MODULE TO. The dangerous failure for a
supply-chain check is not "it missed a finding"; it is "it reported a clean
security result when no security check ran". So the central assertions are
built around a CLEAN POSITIVE CONTROL and then mutation of that one clean
fixture, one defect at a time:

- `_clean_project()` writes a REAL project root whose pyproject.toml and
  requirements.txt declare only distributions that are REALLY INSTALLED in
  this interpreter, each pinned to the exact version `importlib.metadata`
  reports RIGHT NOW (read at test time, never hardcoded -- a hardcoded
  version would make this suite pass or fail on the developer's environment
  rather than on the module). With a real advisory database declared, that
  project is POLICY_CLEAN and exits 0. Every later test mutates exactly one
  thing about it and asserts exactly one finding appears.
- The same clean project WITHOUT an advisory database is NOT_FULLY_CHECKED
  and exits 2, never POLICY_CLEAN -- that pair is the headline test, because
  the difference between them is the entire point of the module.
- The advisory matcher's detection power comes from a matched/unmatched PAIR
  over the SAME really-installed version: one database whose affected range
  contains it (finding) and one whose range excludes it (no finding).

Nothing here contacts a network advisory API, runs a build, submits a job or
touches an approval gate.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

from dv_harness import dependency_supply_chain as dsc
from dv_harness import env_manifest
from dv_harness.dependency_supply_chain import (
    CHECK_DECLARED_VS_INSTALLED, CHECK_NOT_AVAILABLE, CHECK_PINNED_VERSION, CHECK_RAN,
    CHECK_VULNERABILITY_ADVISORY, ECOSYSTEM_PYTHON, ECOSYSTEM_VIP,
    FINDING_ADVISORY_DB_STALE, FINDING_CONSTRAINT_VIOLATED, FINDING_KNOWN_VULNERABILITY,
    FINDING_NOT_INSTALLED, FINDING_UNPINNED, FINDING_VIP_VERSION_UNKNOWN,
    PIN_BOUNDED, PIN_EXACT, PIN_LOWER_ONLY, PIN_UNCONSTRAINED,
    RESOLUTION_NOT_INSTALLED, RESOLUTION_SATISFIED, RESOLUTION_VIOLATED,
    SEVERITY_HIGH, SEVERITY_LOW, SEVERITY_MEDIUM,
    STATUS_CLEAN, STATUS_FINDINGS, STATUS_NOT_FULLY_CHECKED,
    SupplyChainError,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Two distributions that are really installed for the interpreter running this
#: suite: `packaging` is this module's own version-arithmetic dependency and
#: `jsonschema` is declared by the harness itself. Their versions are READ, not
#: written down, so the fixture describes this environment truthfully.
_REAL_A = "packaging"
_REAL_B = "jsonschema"


def _installed(name: str) -> str:
    return metadata.version(name)


def _clean_project(root: Path, *, advisory_db: Path | None = None) -> Path:
    """A REAL project root whose every declared dependency is exact-pinned to a
    version that is really installed here."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        "[build-system]\n"
        f'requires = ["{_REAL_A}=={_installed(_REAL_A)}"]\n'
        'build-backend = "setuptools.build_meta"\n'
        "\n[project]\n"
        'name = "synthetic-supply-chain-fixture"\n'
        'version = "0.0.0"\n'
        f'dependencies = ["{_REAL_B}=={_installed(_REAL_B)}"]\n',
        encoding="utf-8")
    (root / "requirements.txt").write_text(
        "# a synthetic test fixture, not any real project's requirements\n"
        f"{_REAL_A}=={_installed(_REAL_A)}\n",
        encoding="utf-8")
    policy = {"require_exact_pins": True}
    if advisory_db is not None:
        policy["advisory_database"] = str(advisory_db)
    policy_path = root / dsc.POLICY_RELATIVE_PATH
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(json.dumps(policy, indent=2), encoding="utf-8")
    return root


def _advisory_db(path: Path, *, advisories, as_of: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": dsc.ADVISORY_SCHEMA_VERSION,
        "source": "synthetic test fixture -- not a real advisory feed",
        "as_of": as_of or _dt.date.today().isoformat(),
        "advisories": advisories,
    }, indent=2), encoding="utf-8")
    return path


def _report(root: Path, **kwargs):
    # include_vip=False by default: $DESIGNWARE_HOME is a machine fact and a
    # test of the Python half must not change its answer depending on whether
    # the developer happens to have a VIP install.
    kwargs.setdefault("include_vip", False)
    return dsc.analyze_supply_chain(root, **kwargs)


def _findings_of(report, kind):
    return [f for f in report["findings"] if f["kind"] == kind]


def _snapshot(root: Path):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# --------------------------------------------------------------------------
# the headline pair: a fully-pinned project is CLEAN only when a real
# advisory check really ran
# --------------------------------------------------------------------------

def test_clean_project_with_real_advisory_database_is_policy_clean(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    report = _report(root)
    assert report["findings"] == []
    assert report["checks_not_run"] == []
    assert report["status"] == STATUS_CLEAN


def test_identical_project_without_advisory_database_is_never_clean(tmp_path):
    """The whole point of the module: nothing about the DEPENDENCIES changed,
    only whether a real security check could run, and the verdict must move."""
    root = _clean_project(tmp_path / "proj")  # no advisory_database declared
    report = _report(root)
    assert report["findings"] == [], "the pinning/installed checks still find nothing"
    assert report["status"] == STATUS_NOT_FULLY_CHECKED
    assert report["status"] != STATUS_CLEAN
    advisory = [c for c in report["checks"] if c["check"] == CHECK_VULNERABILITY_ADVISORY][0]
    assert advisory["status"] == CHECK_NOT_AVAILABLE
    assert "NO SECURITY SCAN RAN" in advisory["reason"]


def test_not_fully_checked_exits_two_not_zero(tmp_path):
    root = _clean_project(tmp_path / "proj")
    _text, code = dsc.execute_verb("check", root=root, include_vip=False)
    assert code == 2
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root2 = _clean_project(tmp_path / "proj2", advisory_db=db)
    _text2, code2 = dsc.execute_verb("check", root=root2, include_vip=False)
    assert code2 == 0


def test_no_network_advisory_api_is_ever_named_as_a_source(tmp_path):
    root = _clean_project(tmp_path / "proj")
    advisory = [c for c in _report(root)["checks"]
                if c["check"] == CHECK_VULNERABILITY_ADVISORY][0]
    assert "deliberately NOT contacted" in advisory["reason"]
    assert advisory["database"] is None


def test_advisory_tooling_is_probed_by_name_not_assumed(tmp_path):
    probe = dsc.advisory_tooling_probe()
    assert set(probe) == set(dsc._ADVISORY_TOOL_MODULES)
    for name, present in probe.items():
        import importlib.util
        assert present == (importlib.util.find_spec(name) is not None)


# --------------------------------------------------------------------------
# pinned-version enforcement: every class, driven by mutating the clean fixture
# --------------------------------------------------------------------------

@pytest.mark.parametrize("declared,expected_pin,expected_severity", [
    ("acme-widget", PIN_UNCONSTRAINED, SEVERITY_HIGH),
    ("acme-widget>=2.0", PIN_LOWER_ONLY, SEVERITY_MEDIUM),
    ("acme-widget>=2.0,<3", PIN_BOUNDED, SEVERITY_LOW),
    ("acme-widget~=2.1.3", PIN_BOUNDED, SEVERITY_LOW),
    ("acme-widget==2.1.*", PIN_BOUNDED, SEVERITY_LOW),
])
def test_each_unpinned_class_is_classified_and_severity_ranked(tmp_path, declared,
                                                               expected_pin, expected_severity):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    (root / "requirements.txt").write_text(declared + "\n", encoding="utf-8")
    report = _report(root)
    unpinned = _findings_of(report, FINDING_UNPINNED)
    assert [f["component"] for f in unpinned] == ["acme-widget"]
    assert unpinned[0]["pin_status"] == expected_pin
    assert unpinned[0]["severity"] == expected_severity
    assert report["status"] == STATUS_FINDINGS


def test_exact_pin_is_the_only_pinned_class(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    assert _findings_of(_report(root), FINDING_UNPINNED) == []
    pin_check = [c for c in _report(root)["checks"] if c["check"] == CHECK_PINNED_VERSION][0]
    assert pin_check["pin_counts"][PIN_EXACT] == 3
    assert pin_check["status"] == CHECK_RAN


def test_wildcard_equality_is_not_reported_as_an_exact_pin():
    status, reason = dsc.classify_pin("==2.1.*")
    assert status == PIN_BOUNDED
    assert "==2.1.*" in reason or "bounded" in reason
    status2, _ = dsc.classify_pin("==2.1.3")
    assert status2 == PIN_EXACT


def test_a_finding_names_the_real_file_and_field_it_came_from(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    (root / "requirements.txt").write_text("acme-widget\n", encoding="utf-8")
    finding = _findings_of(_report(root), FINDING_UNPINNED)[0]
    assert finding["source_path"] == str(root / "requirements.txt")
    assert finding["source_field"] == "line 1"


def test_build_requirement_and_runtime_dependency_stay_distinguishable(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    fields = {c["name"]: c["source_field"]
              for c in _report(root)["inventory"]["components"]
              if c["source_path"].endswith("pyproject.toml")}
    assert fields[_REAL_A] == "build-system.requires"
    assert fields[_REAL_B] == "project.dependencies"


def test_optional_dependency_groups_are_inventoried_with_their_group_name(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='x'\nversion='0'\n"
        "[project.optional-dependencies]\ndev = ['acme-widget==1.0']\n", encoding="utf-8")
    inv = dsc.build_inventory(root, include_vip=False)
    assert [c["source_field"] for c in inv["components"]] == \
        ["project.optional-dependencies.dev"]


# --------------------------------------------------------------------------
# declared vs. REALLY installed
# --------------------------------------------------------------------------

def test_declared_but_not_installed_is_a_finding(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    (root / "requirements.txt").write_text(
        "dv-harness-no-such-distribution==1.0.0\n", encoding="utf-8")
    report = _report(root)
    missing = _findings_of(report, FINDING_NOT_INSTALLED)
    assert [f["component"] for f in missing] == ["dv-harness-no-such-distribution"]
    assert _findings_of(report, FINDING_UNPINNED) == [], \
        "it is exact-pinned; only the installed-resolution check may fire"


def test_installed_version_outside_the_declared_range_is_a_high_finding(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    # An exact pin to a version that is definitely NOT what is installed.
    (root / "requirements.txt").write_text(f"{_REAL_A}==0.0.1\n", encoding="utf-8")
    report = _report(root)
    violated = _findings_of(report, FINDING_CONSTRAINT_VIOLATED)
    assert [f["component"] for f in violated] == [_REAL_A]
    assert violated[0]["severity"] == SEVERITY_HIGH
    assert violated[0]["installed_version"] == _installed(_REAL_A)


def test_resolution_reads_the_real_interpreter_not_the_declaration(tmp_path):
    resolved = dsc.resolve_installed(_REAL_A, f"=={_installed(_REAL_A)}")
    assert resolved["resolution"] == RESOLUTION_SATISFIED
    assert resolved["installed_version"] == _installed(_REAL_A)
    missing = dsc.resolve_installed("dv-harness-no-such-distribution", "==1.0")
    assert missing["resolution"] == RESOLUTION_NOT_INSTALLED
    violated = dsc.resolve_installed(_REAL_A, "==0.0.1")
    assert violated["resolution"] == RESOLUTION_VIOLATED


def test_resolution_counts_are_reported_per_class(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    (root / "requirements.txt").write_text(
        "dv-harness-no-such-distribution==1.0.0\n", encoding="utf-8")
    check = [c for c in _report(root)["checks"]
             if c["check"] == CHECK_DECLARED_VS_INSTALLED][0]
    assert check["resolution_counts"][RESOLUTION_NOT_INSTALLED] == 1
    assert check["resolution_counts"][RESOLUTION_SATISFIED] == 2


# --------------------------------------------------------------------------
# the advisory matcher: a matched/unmatched PAIR over the SAME real version
# --------------------------------------------------------------------------

def _bump_major(version: str) -> str:
    from packaging.version import Version
    v = Version(version)
    return f"{v.major + 1}.0.0"


def test_an_advisory_covering_the_really_installed_version_is_reported(tmp_path):
    installed = _installed(_REAL_B)
    db = _advisory_db(tmp_path / "adv.json", advisories=[{
        "id": "SYNTH-0001", "ecosystem": ECOSYSTEM_PYTHON, "package": _REAL_B,
        "affected": [{"introduced": "0", "fixed": _bump_major(installed)}],
        "severity": SEVERITY_HIGH, "summary": "synthetic fixture advisory",
        "reference": "https://example.invalid/SYNTH-0001",
    }])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    report = _report(root)
    hits = _findings_of(report, FINDING_KNOWN_VULNERABILITY)
    assert [h["advisory_id"] for h in hits] == ["SYNTH-0001"]
    assert hits[0]["installed_version"] == installed
    assert hits[0]["component"] == _REAL_B
    assert report["status"] == STATUS_FINDINGS


def test_negative_control_the_same_advisory_whose_range_excludes_it_does_not_fire(tmp_path):
    """Identical database except the affected range stops BELOW the really
    installed version. Without this pair, the test above would pass even if the
    matcher reported every advisory for a named package."""
    installed = _installed(_REAL_B)
    db = _advisory_db(tmp_path / "adv.json", advisories=[{
        "id": "SYNTH-0001", "ecosystem": ECOSYSTEM_PYTHON, "package": _REAL_B,
        "affected": [{"introduced": "0", "fixed": installed}],  # half-open: fixed AT installed
        "severity": SEVERITY_HIGH, "summary": "synthetic fixture advisory",
    }])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    report = _report(root)
    assert _findings_of(report, FINDING_KNOWN_VULNERABILITY) == []
    assert report["status"] == STATUS_CLEAN


def test_an_advisory_for_another_ecosystem_never_matches_a_python_component(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[{
        "id": "SYNTH-0002", "ecosystem": ECOSYSTEM_VIP, "package": _REAL_B,
        "affected": [{"introduced": "0"}], "severity": SEVERITY_HIGH,
    }])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    assert _findings_of(_report(root), FINDING_KNOWN_VULNERABILITY) == []


def test_a_component_with_no_installed_version_is_unmatchable_not_clean(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    (root / "requirements.txt").write_text(
        "dv-harness-no-such-distribution==1.0.0\n", encoding="utf-8")
    check = [c for c in _report(root)["checks"]
             if c["check"] == CHECK_VULNERABILITY_ADVISORY][0]
    names = [e["component"] for e in check["unmatchable_components"]]
    assert names == ["dv-harness-no-such-distribution"]
    assert check["matched_components"] == 2


def test_a_stale_advisory_database_is_a_finding_and_a_current_one_is_not(tmp_path):
    old = (_dt.date.today() - _dt.timedelta(days=dsc.DEFAULT_MAX_ADVISORY_AGE_DAYS + 1)).isoformat()
    db_old = _advisory_db(tmp_path / "old.json", advisories=[], as_of=old)
    root_old = _clean_project(tmp_path / "old_proj", advisory_db=db_old)
    report_old = _report(root_old)
    assert len(_findings_of(report_old, FINDING_ADVISORY_DB_STALE)) == 1

    fresh = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    db_new = _advisory_db(tmp_path / "new.json", advisories=[], as_of=fresh)
    root_new = _clean_project(tmp_path / "new_proj", advisory_db=db_new)
    report_new = _report(root_new)
    assert _findings_of(report_new, FINDING_ADVISORY_DB_STALE) == []
    assert report_new["status"] == STATUS_CLEAN


def test_a_real_advisory_check_still_discloses_that_it_only_speaks_for_that_database(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    check = [c for c in _report(root)["checks"]
             if c["check"] == CHECK_VULNERABILITY_ADVISORY][0]
    assert check["status"] == CHECK_RAN
    assert "not a proof that no vulnerability exists" in check["reason"]
    assert check["database"]["source"].startswith("synthetic test fixture")
    assert check["database"]["file"]["sha256"]


@pytest.mark.parametrize("missing", ["source", "as_of", "advisories", "schema_version"])
def test_an_advisory_database_that_cannot_state_its_own_provenance_is_refused(tmp_path, missing):
    doc = {"schema_version": dsc.ADVISORY_SCHEMA_VERSION, "source": "s",
           "as_of": _dt.date.today().isoformat(), "advisories": [{"id": "X",
           "ecosystem": ECOSYSTEM_PYTHON, "package": "p", "affected": [{"introduced": "0"}]}]}
    doc.pop(missing)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(SupplyChainError) as e:
        dsc.load_advisory_database(path)
    assert missing in str(e.value)


def test_an_empty_but_well_provenanced_advisory_database_is_usable(tmp_path):
    """A real feed that currently carries nothing affecting this ecosystem is a
    usable database. Refusing it would push a project back to having no advisory
    source at all -- i.e. back to NOT_FULLY_CHECKED forever."""
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    loaded = dsc.load_advisory_database(db)
    assert loaded["advisory_count"] == 0
    assert loaded["source"].startswith("synthetic test fixture")


def test_an_advisory_database_with_a_non_iso_as_of_is_refused(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "schema_version": dsc.ADVISORY_SCHEMA_VERSION, "source": "s",
        "as_of": "last tuesday", "advisories": []}), encoding="utf-8")
    with pytest.raises(SupplyChainError):
        dsc.load_advisory_database(path)


def test_a_missing_advisory_database_is_refused_not_treated_as_empty(tmp_path):
    root = _clean_project(tmp_path / "proj")
    with pytest.raises(SupplyChainError):
        _report(root, advisory_db_path=str(tmp_path / "nope.json"))


# --------------------------------------------------------------------------
# VIP half: the REAL $DESIGNWARE_HOME scan, reused rather than rebuilt
# --------------------------------------------------------------------------

def _designware_tree(root: Path, packages) -> Path:
    """A REAL install tree in the layout scan_designware_home() walks."""
    for name, version in packages:
        base = root / "vip" / "svt" / name
        (base / version if version else base).mkdir(parents=True, exist_ok=True)
        if version is None:
            (base / "svt_placeholder.txt").write_text("no version dir", encoding="utf-8")
    return root


def test_installed_vip_packages_are_inventoried_from_the_real_install_tree(tmp_path):
    home = _designware_tree(tmp_path / "dw", [("usb_svt", "T-2022.03"), ("pcie_svt", "U-2023.09")])
    inv = dsc.inventory_vip(str(home))
    assert inv["scan_status"] == "SCANNED"
    by_name = {c["name"]: c for c in inv["components"]}
    assert set(by_name) == {"usb_svt", "pcie_svt"}
    assert by_name["usb_svt"]["specifier"] == "T-2022.03"
    assert by_name["usb_svt"]["pin_status"] == PIN_EXACT
    assert by_name["usb_svt"]["ecosystem"] == ECOSYSTEM_VIP
    assert by_name["usb_svt"]["installed"]["resolution"] == RESOLUTION_SATISFIED


def test_a_vip_package_with_no_version_directory_is_a_finding(tmp_path):
    home = _designware_tree(tmp_path / "dw", [("usb_svt", None)])
    root = _clean_project(tmp_path / "proj",
                          advisory_db=_advisory_db(tmp_path / "adv.json", advisories=[]))
    report = dsc.analyze_supply_chain(root, designware_home=str(home), include_vip=True)
    findings = _findings_of(report, FINDING_VIP_VERSION_UNKNOWN)
    assert [f["component"] for f in findings] == ["usb_svt"]
    assert findings[0]["ecosystem"] == ECOSYSTEM_VIP


def test_an_unset_designware_home_is_a_named_absence_never_a_clean_vip_inventory(monkeypatch):
    monkeypatch.delenv(env_manifest.DESIGNWARE_HOME_ENV, raising=False)
    inv = dsc.inventory_vip(None)
    assert inv["scan_status"] == "NOT_AVAILABLE"
    assert inv["components"] == []
    assert "not set" in inv["reason"]


def test_the_vip_half_really_delegates_to_env_manifest_build_vip_release(monkeypatch):
    """Reuse held as a PROPERTY, not a claim: patching env_manifest's own scan
    must change what the inventory reports. A second hand-rolled VIP walk in
    this module would not respond to this."""
    sentinel = {"status": "SCANNED", "reason": None, "designware_home": "/sentinel",
                "packages": [{"name": "sentinel_svt", "version": "Z-9999.99",
                              "install_path": "/sentinel/vip/svt/sentinel_svt/Z-9999.99",
                              "release_notes": None, "feature_matrix": None}]}
    monkeypatch.setattr(env_manifest, "build_vip_release", lambda *a, **k: sentinel)
    inv = dsc.inventory_vip("/anything")
    assert [c["name"] for c in inv["components"]] == ["sentinel_svt"]


def test_file_refs_really_come_from_env_manifest(monkeypatch, tmp_path):
    """Same property for the integrity records: there is one hashing helper in
    this package and this module calls it."""
    root = _clean_project(tmp_path / "proj")
    monkeypatch.setattr(env_manifest, "file_ref",
                        lambda p: {"path": str(p), "sha256": "SENTINEL", "bytes": 0})
    inv = dsc.build_inventory(root, include_vip=False)
    refs = [s["file"] for s in inv["sources"] if s.get("file")]
    assert refs and all(r["sha256"] == "SENTINEL" for r in refs)


def test_env_manifest_file_ref_is_the_private_helper_not_a_copy():
    assert env_manifest.file_ref is env_manifest._file_ref


def test_source_file_integrity_is_recorded_with_a_real_sha256(tmp_path):
    root = _clean_project(tmp_path / "proj")
    inv = dsc.build_inventory(root, include_vip=False)
    for source in inv["sources"]:
        if not source.get("file"):
            continue
        path = Path(source["file"]["path"])
        assert source["file"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert source["file"]["bytes"] == path.stat().st_size


# --------------------------------------------------------------------------
# policy: exemptions are explained, and a typo cannot silently disable a rule
# --------------------------------------------------------------------------

def test_an_exemption_suppresses_the_finding_but_never_the_fact(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    (root / "requirements.txt").write_text("acme-widget\n", encoding="utf-8")
    policy_path = root / dsc.POLICY_RELATIVE_PATH
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["exempt_unpinned"] = [{"name": "acme-widget",
                                  "reason": "vendor ships no versioned release"}]
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    report = _report(root)
    assert _findings_of(report, FINDING_UNPINNED) == []
    component = [c for c in report["inventory"]["components"] if c["name"] == "acme-widget"][0]
    assert component["pin_status"] == PIN_UNCONSTRAINED
    assert component["exemption"]["reason"] == "vendor ships no versioned release"
    assert report["policy_exemptions"][0]["name"] == "acme-widget"


def test_an_unexplained_exemption_is_refused(tmp_path):
    root = _clean_project(tmp_path / "proj")
    policy_path = root / dsc.POLICY_RELATIVE_PATH
    policy_path.write_text(json.dumps(
        {"exempt_unpinned": [{"name": "acme-widget"}]}), encoding="utf-8")
    with pytest.raises(SupplyChainError) as e:
        dsc.load_policy(root)
    assert "reason" in str(e.value)


def test_a_misspelled_policy_key_is_refused_not_silently_defaulted(tmp_path):
    root = _clean_project(tmp_path / "proj")
    (root / dsc.POLICY_RELATIVE_PATH).write_text(
        json.dumps({"require_exact_pin": False}), encoding="utf-8")
    with pytest.raises(SupplyChainError) as e:
        dsc.load_policy(root)
    assert "require_exact_pin" in str(e.value)


def test_a_project_with_no_policy_gets_the_documented_defaults_marked_undeclared(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    policy = dsc.load_policy(root)
    assert policy["declared"] is False
    assert policy["require_exact_pins"] is True
    assert policy["advisory_database"] is None


def test_turning_off_pin_enforcement_really_suppresses_only_that_check(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    (root / "requirements.txt").write_text(
        "acme-widget\ndv-harness-no-such-distribution==1.0\n", encoding="utf-8")
    before = _report(root)
    # acme-widget is unconstrained AND uninstalled; the second is exact-pinned
    # and uninstalled -- so the two checks start from 1 and 2 findings.
    assert len(_findings_of(before, FINDING_UNPINNED)) == 1
    assert len(_findings_of(before, FINDING_NOT_INSTALLED)) == 2
    policy_path = root / dsc.POLICY_RELATIVE_PATH
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["require_exact_pins"] = False
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    after = _report(root)
    assert _findings_of(after, FINDING_UNPINNED) == []
    assert len(_findings_of(after, FINDING_NOT_INSTALLED)) == 2, \
        "the installed-resolution check is untouched by the pinning policy"


# --------------------------------------------------------------------------
# parsing details that would otherwise silently shrink an inventory
# --------------------------------------------------------------------------

def test_a_pip_directive_is_recorded_as_unfollowed_never_silently_dropped(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "requirements.txt").write_text(
        "-r base.txt\n--index-url https://example.invalid/simple\nacme-widget==1.0\n",
        encoding="utf-8")
    source = dsc.inventory_requirements_file(root / "requirements.txt")
    assert [c["name"] for c in source["components"]] == ["acme-widget"]
    assert [d["raw"] for d in source["directives"]] == \
        ["-r base.txt", "--index-url https://example.invalid/simple"]


def test_comments_and_blank_lines_are_not_components():
    assert dsc.parse_requirement_line("") is None
    assert dsc.parse_requirement_line("   # a comment") is None
    assert dsc.parse_requirement_line("acme==1.0  # trailing")["raw"] == "acme==1.0"


def test_every_root_requirements_file_is_discovered(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    for name in ("requirements.txt", "requirements-dev.txt", "requirements-harness.txt"):
        (root / name).write_text("acme==1.0\n", encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / "requirements.txt").write_text("nested==1.0\n", encoding="utf-8")
    found = [p.name for p in dsc.discover_requirements_files(root)]
    assert found == ["requirements-dev.txt", "requirements-harness.txt", "requirements.txt"]


def test_an_unparseable_requirement_is_recorded_undetermined_not_assumed_pinned(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "requirements.txt").write_text("acme widget !!!\n", encoding="utf-8")
    component = dsc.inventory_requirements_file(root / "requirements.txt")["components"][0]
    assert component["pin_status"] == dsc.PIN_UNDETERMINED
    assert "INVALID_REQUIREMENT" in component["parse_error"]


# --------------------------------------------------------------------------
# boundaries: reads only, and no verdict vocabulary
# --------------------------------------------------------------------------

def test_analyzing_writes_nothing_at_all(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    before = _snapshot(root)
    _report(root)
    _report(root)
    dsc.execute_verb("inventory", root=root, include_vip=False)
    dsc.execute_verb("advisory-status", root=root, include_vip=False)
    assert _snapshot(root) == before


def test_no_state_or_memory_store_is_minted_in_a_bare_project(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    dsc.analyze_supply_chain(root, include_vip=False)
    assert list(root.iterdir()) == []


def test_the_vocabularies_share_no_token_with_the_verification_verdict_enum():
    from dv_harness.models import Status
    verdicts = {s.value for s in Status}
    for vocabulary in (dsc.PIN_STATUSES, dsc.RESOLUTIONS, dsc.REPORT_STATUSES,
                       dsc.FINDING_KINDS, dsc.SEVERITIES):
        assert not verdicts.intersection(vocabulary)
    dsc.assert_no_verification_verdict_vocabulary()


def test_negative_control_the_vocabulary_guard_really_trips(monkeypatch):
    monkeypatch.setattr(dsc, "REPORT_STATUSES", dsc.REPORT_STATUSES + ("PASS",))
    with pytest.raises(SupplyChainError) as e:
        dsc.assert_no_verification_verdict_vocabulary()
    assert "PASS" in str(e.value)


def test_no_human_approval_machinery_is_referenced_by_this_module():
    source = Path(dsc.__file__).read_text(encoding="utf-8")
    import io, tokenize
    code = "".join(
        tok.string for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type not in (tokenize.COMMENT, tokenize.STRING))
    for forbidden in ("ControlPlane", "can_signoff", "assert_human_approval",
                      "HumanApprovalRequiredError", "ProductionWriteNotAuthorizedError",
                      "bsub", "run_stage", "subprocess"):
        assert forbidden not in code, f"{forbidden} must not appear in executable code"


# --------------------------------------------------------------------------
# this repository's own real answer
# --------------------------------------------------------------------------

def test_this_repository_reports_its_own_real_declared_dependencies():
    inv = dsc.build_inventory(REPO_ROOT, include_vip=False)
    names = {c["name"] for c in inv["components"]}
    assert {"setuptools", "claude-code-sdk", "mcp", "jsonschema"} <= names
    sources = {s["source_kind"]: s for s in inv["sources"]}
    assert sources["pyproject"]["present"] is True
    assert sources["requirements"]["path"].endswith("requirements-harness.txt")


def test_this_repository_honestly_reports_no_security_scan_ran():
    report = dsc.analyze_supply_chain(REPO_ROOT, include_vip=False)
    assert report["status"] != STATUS_CLEAN
    assert CHECK_VULNERABILITY_ADVISORY in report["checks_not_run"]
    # And the real pinning state of this repo today: nothing is exact-pinned.
    assert len(_findings_of(report, FINDING_UNPINNED)) == 4


def test_this_repository_is_not_written_to_by_a_report():
    before = hashlib.sha256((REPO_ROOT / "pyproject.toml").read_bytes()).hexdigest()
    dsc.analyze_supply_chain(REPO_ROOT, include_vip=False)
    assert hashlib.sha256((REPO_ROOT / "pyproject.toml").read_bytes()).hexdigest() == before


# --------------------------------------------------------------------------
# both real entry points, driven as real subprocesses
# --------------------------------------------------------------------------

def _run(args, cwd=None):
    env = dict(os.environ)
    env.pop(env_manifest.DESIGNWARE_HOME_ENV, None)
    return subprocess.run([sys.executable, *args], cwd=str(cwd or REPO_ROOT),
                          capture_output=True, text=True, env=env)


def test_module_entry_point_exits_two_when_no_security_check_ran(tmp_path):
    root = _clean_project(tmp_path / "proj")
    proc = _run(["-m", "dv_harness.dependency_supply_chain", "check",
                 "--root", str(root), "--no-vip"])
    assert proc.returncode == 2, proc.stderr
    assert "NOT_FULLY_CHECKED" in proc.stdout
    assert "NO SECURITY SCAN RAN" in proc.stdout


def test_module_entry_point_exits_zero_on_a_really_clean_checked_project(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    proc = _run(["-m", "dv_harness.dependency_supply_chain", "check",
                 "--root", str(root), "--no-vip"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "POLICY_CLEAN" in proc.stdout


def test_module_entry_point_exits_one_on_a_real_finding(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    (root / "requirements.txt").write_text("acme-widget\n", encoding="utf-8")
    proc = _run(["-m", "dv_harness.dependency_supply_chain", "check",
                 "--root", str(root), "--no-vip"])
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert FINDING_UNPINNED in proc.stdout


def test_cli_verb_runs_over_this_real_repository():
    proc = _run(["-m", "dv_harness.cli", "supply-chain", "check", "--no-vip"])
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "dependency supply chain" in proc.stdout
    assert CHECK_VULNERABILITY_ADVISORY in proc.stdout


def test_cli_and_module_share_one_implementation(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    a = _run(["-m", "dv_harness.dependency_supply_chain", "check",
              "--root", str(root), "--no-vip", "--json"])
    b = _run(["-m", "dv_harness.cli", "--project-root", str(root), "supply-chain", "check",
              "--no-vip", "--json"])
    assert a.returncode == b.returncode == 0, a.stdout + b.stdout + b.stderr
    assert json.loads(a.stdout)["status"] == json.loads(b.stdout)["status"]
    assert json.loads(a.stdout)["findings"] == json.loads(b.stdout)["findings"]


def test_json_report_is_serialisable_and_carries_the_disclosure(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    text, code = dsc.execute_verb("check", root=root, include_vip=False, as_json=True)
    doc = json.loads(text)
    assert code == 0
    assert doc["disclosure"] == dsc.REPORT_DISCLOSURE
    assert "NOT an SBOM" in doc["disclosure"]


def test_inventory_verb_lists_every_component_with_its_pin_and_installed_state(tmp_path):
    db = _advisory_db(tmp_path / "adv.json", advisories=[])
    root = _clean_project(tmp_path / "proj", advisory_db=db)
    text, code = dsc.execute_verb("inventory", root=root, include_vip=False)
    assert code == 0
    assert PIN_EXACT in text
    assert _installed(_REAL_B) in text


def test_advisory_status_verb_exits_two_without_a_database(tmp_path):
    root = _clean_project(tmp_path / "proj")
    text, code = dsc.execute_verb("advisory-status", root=root, include_vip=False)
    assert code == 2
    assert "NO SECURITY SCAN RAN" in text


def test_an_unknown_verb_is_refused(tmp_path):
    text, code = dsc.execute_verb("scan-everything", root=tmp_path)
    assert code == 2
    assert "unknown supply-chain verb" in text
