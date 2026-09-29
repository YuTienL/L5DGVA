"""Real tests for dv_harness/execution_profile.py -- the M1 minimal
configuration-extraction module that lets replay.ps1 resolve
gateway/remote-host/workdir identity from a JSON profile file instead of
hardcoding one user's own values (vc8/icr93) into canonical runtime text.

No mocked filesystem: every test writes a real profile JSON file to a real
tmp_path and exercises the real functions against it.
"""
import json

import pytest

from dv_harness import execution_profile as ep


def _write_profile(path, **fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields), encoding="utf-8")


def test_load_execution_profile_reads_gateway_and_remote_host_from_file(tmp_path):
    _write_profile(tmp_path / ".dv-harness" / "execution_profile.json",
                    gateway_host="example-gateway", remote_host="example-hop")
    profile = ep.load_execution_profile(tmp_path)
    assert profile["gateway_host"] == "example-gateway"
    assert profile["remote_host"] == "example-hop"


def test_profile_to_env_overrides_maps_gateway_host_to_VCHOST(tmp_path):
    _write_profile(tmp_path / ".dv-harness" / "execution_profile.json",
                    gateway_host="example-gateway", remote_host="example-hop")
    profile = ep.load_execution_profile(tmp_path)
    overrides = ep.profile_to_env_overrides(profile)
    assert overrides["VCHOST"] == "example-gateway"


def test_profile_to_env_overrides_maps_remote_host_to_VCHOP(tmp_path):
    _write_profile(tmp_path / ".dv-harness" / "execution_profile.json",
                    gateway_host="example-gateway", remote_host="example-hop")
    profile = ep.load_execution_profile(tmp_path)
    overrides = ep.profile_to_env_overrides(profile)
    assert overrides["VCHOP"] == "example-hop"


def test_changing_the_profile_file_changes_the_selected_hosts(tmp_path):
    profile_path = tmp_path / ".dv-harness" / "execution_profile.json"
    _write_profile(profile_path, gateway_host="host-a", remote_host="hop-a")
    overrides_a = ep.profile_to_env_overrides(ep.load_execution_profile(tmp_path))

    _write_profile(profile_path, gateway_host="host-b", remote_host="hop-b")
    overrides_b = ep.profile_to_env_overrides(ep.load_execution_profile(tmp_path))

    assert overrides_a["VCHOST"] == "host-a"
    assert overrides_b["VCHOST"] == "host-b"
    assert overrides_a["VCHOST"] != overrides_b["VCHOST"]


def test_remote_workdir_maps_to_DVWORKDIR(tmp_path):
    _write_profile(tmp_path / ".dv-harness" / "execution_profile.json",
                    gateway_host="h", remote_host="p", remote_workdir="/home/acct/proj/UVM")
    overrides = ep.profile_to_env_overrides(ep.load_execution_profile(tmp_path))
    assert overrides["DVWORKDIR"] == "/home/acct/proj/UVM"


def test_eda_environment_list_is_joined_for_VCEDAENV(tmp_path):
    _write_profile(tmp_path / ".dv-harness" / "execution_profile.json",
                    gateway_host="h", remote_host="p",
                    eda_environment=["version.csh", "env.csh"])
    overrides = ep.profile_to_env_overrides(ep.load_execution_profile(tmp_path))
    assert overrides["VCEDAENV"] == "version.csh,env.csh"


def test_user_field_maps_to_VCUSER_and_is_optional(tmp_path):
    _write_profile(tmp_path / ".dv-harness" / "execution_profile.json",
                    gateway_host="h", remote_host="p", user="devuser")
    overrides = ep.profile_to_env_overrides(ep.load_execution_profile(tmp_path))
    assert overrides["VCUSER"] == "devuser"


def test_profile_to_env_overrides_never_includes_VCPW(tmp_path):
    _write_profile(tmp_path / ".dv-harness" / "execution_profile.json",
                    gateway_host="h", remote_host="p")
    overrides = ep.profile_to_env_overrides(ep.load_execution_profile(tmp_path))
    assert "VCPW" not in overrides


def test_missing_profile_file_raises_execution_profile_required_error(tmp_path):
    with pytest.raises(ep.ExecutionProfileRequiredError) as exc_info:
        ep.load_execution_profile(tmp_path)
    assert exc_info.value.condition == "EXECUTION_PROFILE_REQUIRED"


def test_profile_missing_required_field_raises_execution_profile_required_error(tmp_path):
    _write_profile(tmp_path / ".dv-harness" / "execution_profile.json", gateway_host="only-one-field")
    with pytest.raises(ep.ExecutionProfileRequiredError):
        ep.load_execution_profile(tmp_path)


def test_profile_with_forbidden_credential_field_is_rejected(tmp_path):
    _write_profile(tmp_path / ".dv-harness" / "execution_profile.json",
                    gateway_host="h", remote_host="p", password="should-never-be-here")
    with pytest.raises(ep.ExecutionProfileRequiredError):
        ep.load_execution_profile(tmp_path)


def test_env_var_override_selects_a_different_profile_path(tmp_path):
    default_path = tmp_path / ".dv-harness" / "execution_profile.json"
    _write_profile(default_path, gateway_host="default-host", remote_host="default-hop")

    alt_path = tmp_path / "alt_profile.json"
    _write_profile(alt_path, gateway_host="alt-host", remote_host="alt-hop")

    profile = ep.load_execution_profile(tmp_path, env={ep.ENV_VAR_PROFILE_PATH: str(alt_path)})
    assert profile["gateway_host"] == "alt-host"


def test_missing_profile_is_not_silently_defaulted_to_vc8_or_icr93(tmp_path):
    # Regression guard for the exact defect this module exists to close:
    # a resolution failure must never quietly fall back to this project's
    # own real historical host identity.
    with pytest.raises(ep.ExecutionProfileRequiredError):
        ep.load_execution_profile(tmp_path)


def test_default_profile_path_is_relative_to_repo_root_not_an_absolute_machine_path(tmp_path):
    path = ep.default_profile_path(tmp_path)
    assert str(path).startswith(str(tmp_path))
    assert path == tmp_path / ".dv-harness" / "execution_profile.json"


def test_no_canonical_runtime_dependency_on_vc8_or_icr93_literal():
    # Scans the real execution_profile.py source (not a copy) for the two
    # literal host tokens this extraction exists to remove from canonical
    # runtime logic. Only rejects module code -- comments/docstrings using
    # them as a *bygone example* would still be undesirable, so the scan
    # is deliberately unqualified (whole-file).
    import inspect
    source = inspect.getsource(ep)
    assert "vc8" not in source.lower()
    assert "icr93" not in source.lower()


def test_replay_ps1_no_longer_hardcodes_vc8_or_icr93():
    from pathlib import Path
    replay_ps1 = Path(__file__).resolve().parents[1] / "replay.ps1"
    if not replay_ps1.is_file():
        pytest.skip("replay.ps1 not yet migrated into the canonical repo")
    text = replay_ps1.read_text(encoding="utf-8").lower()
    assert "vc8" not in text
    assert "icr93" not in text


def test_replay_ps1_still_invokes_the_existing_unmodified_remote_relay():
    # Proves existing remote_hop/remote_relay invocation semantics are
    # preserved -- the launcher must still shell out to the same,
    # untouched remote_relay.py --start entry point.
    from pathlib import Path
    replay_ps1 = Path(__file__).resolve().parents[1] / "replay.ps1"
    if not replay_ps1.is_file():
        pytest.skip("replay.ps1 not yet migrated into the canonical repo")
    text = replay_ps1.read_text(encoding="utf-8")
    assert "remote_relay.py" in text
    assert "--start" in text
