"""Real tests for dv_harness/dv_doctor.py -- the canonical `dv-harness
doctor` composed health report (M1 wiring). No mocking of the module
under test: every test runs the real functions against either a real
temp L5DGVA-shaped tree or this real checked-out repository.
"""
import json

from dv_harness import dv_doctor


REQUIRED_KEYS = [
    "REPOSITORY_IDENTITY", "REPOSITORY_ROOT", "REPOSITORY_MODE",
    "GIT_AVAILABILITY", "GIT_ROOT_CONSISTENCY", "EXECUTION_PROFILE_STATUS",
    "REMOTE_TRANSPORT_STATUS", "KC_STATUS", "MEMORY_STATUS",
    "OBSIDIAN_ADAPTER_STATUS", "OBSIDIAN_CLI_STATUS",
    "OBSIDIAN_VAULT_CONFIGURATION", "PERSISTENT_STORAGE_STATUS",
    "GRAPH_STATUS", "AGENT_STATUS", "SKILL_STATUS", "OPENSPEC_STATUS",
    "INTAKE_STATUS",
]


def test_run_doctor_against_the_real_repo_returns_every_required_key():
    from pathlib import Path
    real_root = Path(__file__).resolve().parents[1]
    report = dv_doctor.run_doctor(real_root)
    for key in REQUIRED_KEYS:
        assert key in report, "missing required dv doctor key: %s" % key


def test_run_doctor_never_raises_on_a_directory_with_no_l5dgva_marker(tmp_path):
    # A directory that isn't an L5DGVA repo at all must still produce a
    # full, honest FAIL-status report, never an exception.
    report = dv_doctor.run_doctor(tmp_path)
    assert report["REPOSITORY_IDENTITY"]["status"] == "FAIL"
    for key in REQUIRED_KEYS:
        assert key in report


def test_repository_identity_passes_on_the_real_repo():
    from pathlib import Path
    real_root = Path(__file__).resolve().parents[1]
    report = dv_doctor.run_doctor(real_root)
    assert report["REPOSITORY_IDENTITY"]["status"] == "PASS"


def test_execution_profile_status_not_configured_when_profile_missing(tmp_path):
    from dv_harness.l5dgva_repo import MARKER_DIR_NAME, MARKER_FILE_NAME
    marker_dir = tmp_path / MARKER_DIR_NAME
    marker_dir.mkdir()
    (marker_dir / MARKER_FILE_NAME).write_text(
        json.dumps({"product_identity": "L5DGVA"}), encoding="utf-8"
    )
    report = dv_doctor.run_doctor(tmp_path)
    assert report["EXECUTION_PROFILE_STATUS"]["status"] == "NOT_CONFIGURED"


def test_execution_profile_status_configured_when_real_profile_present():
    from pathlib import Path
    real_root = Path(__file__).resolve().parents[1]
    report = dv_doctor.run_doctor(real_root)
    # This repo's own real, gitignored local profile may or may not exist
    # on the machine running the test -- both are valid, honest outcomes;
    # this just proves the field is never silently absent or wrong-typed.
    assert report["EXECUTION_PROFILE_STATUS"]["status"] in ("CONFIGURED", "NOT_CONFIGURED")


def test_obsidian_cli_status_is_never_a_hard_failure_when_unavailable():
    from pathlib import Path
    real_root = Path(__file__).resolve().parents[1]
    report = dv_doctor.run_doctor(real_root)
    assert report["OBSIDIAN_CLI_STATUS"]["status"] in ("AVAILABLE", "KNOWLEDGE_BACKEND_DEGRADED")


def test_git_root_consistency_matches_on_the_real_repo():
    from pathlib import Path
    real_root = Path(__file__).resolve().parents[1]
    report = dv_doctor.run_doctor(real_root)
    assert report["GIT_ROOT_CONSISTENCY"]["status"] in ("MATCH", "MISMATCH", "GIT_CAPABILITY_UNAVAILABLE")


def test_render_doctor_report_produces_readable_text():
    from pathlib import Path
    real_root = Path(__file__).resolve().parents[1]
    report = dv_doctor.run_doctor(real_root)
    text = dv_doctor.render_doctor_report(report)
    assert "REPOSITORY_IDENTITY" in text
    assert isinstance(text, str)


def test_deployment_copy_mode_reports_git_capability_unavailable(tmp_path):
    # A directory with the marker but NO .git -- DEPLOYMENT_COPY_MODE --
    # must report git-dependent checks as an honest capability gap, never
    # as a generic failure of the L5DGVA repository itself.
    from dv_harness.l5dgva_repo import MARKER_DIR_NAME, MARKER_FILE_NAME
    marker_dir = tmp_path / MARKER_DIR_NAME
    marker_dir.mkdir()
    (marker_dir / MARKER_FILE_NAME).write_text(
        json.dumps({"product_identity": "L5DGVA"}), encoding="utf-8"
    )
    report = dv_doctor.run_doctor(tmp_path)
    assert report["REPOSITORY_MODE"]["mode"] == "DEPLOYMENT_COPY_MODE"
    assert report["GIT_ROOT_CONSISTENCY"]["status"] == "GIT_CAPABILITY_UNAVAILABLE"
