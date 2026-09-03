"""Tests for run_profile_to_justfile: the justfile generator and its
standalone (dv_harness-independent) argument validator.

Where the underlying `just` binary is available, tests also exercise the
generated justfile for real (not just string-match its text) -- this
directly regression-guards the two real bugs found while building this
generator: just recipe parameters are positional, not KEY=value (a typed
named-parameter design silently produced `SPEED=speed=gen1`), and
{{justfile_directory()}} mangles under `set shell := ["bash", "-uc"]` on
Windows.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dv_harness.uvm_generator.makefile_to_run_profile import extract_run_profile
from dv_harness.uvm_generator.run_profile import save_run_profile
from dv_harness.uvm_generator.run_profile_to_justfile import (
    _STANDALONE_VALIDATOR_TEMPLATE,
    HUMAN_OVERRIDE_ACK_TOKEN,
    copy_standalone_validator,
    generate_and_write,
    generate_justfile,
    main as validator_main,
)

_TEMPLATE_MAKEFILE = (
    Path(__file__).resolve().parents[1]
    / "dv_harness"
    / "uvm_generator"
    / "templates"
    / "sim_scripts"
    / "Makefile"
)

_JUST = shutil.which("just")


@pytest.fixture(scope="module")
def profile() -> dict:
    return extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")


def test_standalone_validator_template_exists_and_has_no_dv_harness_import():
    assert _STANDALONE_VALIDATOR_TEMPLATE.is_file()
    lines = _STANDALONE_VALIDATOR_TEMPLATE.read_text(encoding="utf-8").splitlines()
    # The module's own docstring is allowed to explain the no-dependency
    # rule in prose (and does); what must never appear is an actual import
    # statement pulling in the Harness package.
    import_lines = [ln for ln in lines if ln.strip().startswith(("import ", "from "))]
    assert import_lines, "expected at least the stdlib json/sys imports"
    assert not any("dv_harness" in ln for ln in import_lines), (
        "the standalone validator ships into delivered environments without the "
        f"Harness package installed -- found a dv_harness import: {import_lines}"
    )


def test_generate_justfile_uses_variadic_passthrough_not_named_params(profile):
    text = generate_justfile(profile)
    assert "compile *args:" in text
    assert "sim *args:" in text
    # Regression guard: an earlier design used typed named parameters with
    # defaults (`compile speed="ss_capable" ...`), which a real `just
    # --dry-run compile speed=gen1` proved binds the WHOLE token
    # "speed=gen1" positionally rather than reading it as KEY=value.
    assert 'speed="ss_capable"' not in text


def test_generate_justfile_never_uses_justfile_directory_in_a_recipe_body(profile):
    text = generate_justfile(profile)
    # Explanatory comments are allowed to name the rejected approach (and do,
    # for the "why" -- see the _validate recipe's own header comment); what
    # must never appear is an actual recipe BODY line (tab-indented) using
    # it, since that is the literal construct proven to mangle under
    # `set shell := ["bash", "-uc"]` on Windows.
    recipe_body_lines = [ln for ln in text.splitlines() if ln.startswith("\t")]
    assert not any("justfile_directory()" in ln for ln in recipe_body_lines)


def test_generate_justfile_references_standalone_validator_by_relative_path(profile):
    text = generate_justfile(profile)
    assert "python3 validate_run_profile_args.py" in text
    recipe_body_lines = [ln for ln in text.splitlines() if ln.startswith("\t")]
    assert not any("dv_harness" in ln for ln in recipe_body_lines), (
        "no recipe body may invoke `python3 -m dv_harness...` -- only the "
        "standalone validate_run_profile_args.py script"
    )


def test_generate_justfile_only_models_known_targets(profile):
    text = generate_justfile(profile)
    # A real but unmodeled target (e.g. "cov_gui" is modeled; "unr" is real
    # but not in _MODELED_TARGETS) must not get its own typed recipe --
    # only the human_raw_override escape hatch reaches it.
    assert "\nunr" not in text


def test_generate_justfile_has_human_override_escape_hatch(profile):
    text = generate_justfile(profile)
    # The recipe now takes an `ack` parameter ahead of the target: the escape
    # hatch still exists (an unmodeled target is reachable no other way), but
    # it can no longer be invoked without stating the bypass out loud.
    assert "human_raw_override ack target *args:" in text
    assert "HUMAN OVERRIDE ONLY" in text
    assert HUMAN_OVERRIDE_ACK_TOKEN in text


def test_generate_and_write_copies_standalone_validator(tmp_path):
    profile_path = tmp_path / "run_profile.json"
    profile_dict = extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")
    save_run_profile(profile_dict, profile_path)
    generate_and_write(profile_path, tmp_path / "justfile")
    assert (tmp_path / "justfile").is_file()
    assert (tmp_path / "validate_run_profile_args.py").is_file()


def test_copy_standalone_validator_is_byte_identical_to_template(tmp_path):
    dest = copy_standalone_validator(tmp_path)
    assert dest.read_bytes() == _STANDALONE_VALIDATOR_TEMPLATE.read_bytes()


# --- standalone validator behavior, exercised directly (no dv_harness import) ---


def test_standalone_validator_rejects_bad_enum(tmp_path, capsys):
    profile_dict = extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")
    profile_path = tmp_path / "run_profile.json"
    save_run_profile(profile_dict, profile_path)
    rc = validator_main(["validate", str(profile_path), "compile", "SPEED=gen5"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "gen5" in err
    assert "usb20, usb20fs, gen1, gen2 or ss_capable" in err


def test_standalone_validator_accepts_good_enum(tmp_path):
    profile_dict = extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")
    profile_path = tmp_path / "run_profile.json"
    save_run_profile(profile_dict, profile_path)
    rc = validator_main(["validate", str(profile_path), "compile", "SPEED=gen1"])
    assert rc == 0


def test_standalone_validator_rejects_retired_knob(tmp_path, capsys):
    profile_dict = extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")
    profile_path = tmp_path / "run_profile.json"
    save_run_profile(profile_dict, profile_path)
    rc = validator_main(["validate", str(profile_path), "sim", "VIP_TUCH_US=2"])
    assert rc == 1
    assert "retired" in capsys.readouterr().err.lower() or "RETIRED" in capsys.readouterr().err


def test_standalone_validator_process_has_no_dv_harness_on_path(tmp_path):
    """Run the copied standalone script as a real subprocess with a bare
    PYTHONPATH, proving it truly has no import dependency on dv_harness --
    the whole reason it exists separately from run_profile_to_justfile.py's
    own _cli_validate.
    """
    profile_dict = extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")
    profile_path = tmp_path / "run_profile.json"
    save_run_profile(profile_dict, profile_path)
    script = copy_standalone_validator(tmp_path)

    result = subprocess.run(
        ["python", str(script), str(profile_path), "compile", "SPEED=gen5"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PATH": __import__("os").environ.get("PATH", "")},
    )
    assert result.returncode == 1
    assert "gen5" in result.stderr


@pytest.mark.skipif(_JUST is None, reason="just binary not installed on this machine")
def test_real_just_rejects_bad_enum_before_reaching_make(tmp_path):
    profile_dict = extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")
    profile_path = tmp_path / "run_profile.json"
    save_run_profile(profile_dict, profile_path)
    generate_and_write(profile_path, tmp_path / "justfile")

    result = subprocess.run(
        [_JUST, "compile", "SPEED=gen5"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "gen5" in result.stdout + result.stderr
    assert "usb20, usb20fs, gen1, gen2 or ss_capable" in result.stdout + result.stderr


@pytest.mark.skipif(_JUST is None, reason="just binary not installed on this machine")
def test_real_just_accepts_good_args_and_reaches_make_invocation(tmp_path):
    profile_dict = extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")
    profile_path = tmp_path / "run_profile.json"
    save_run_profile(profile_dict, profile_path)
    generate_and_write(profile_path, tmp_path / "justfile")

    result = subprocess.run(
        [_JUST, "compile", "SPEED=gen1"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Validation must have passed (no rejection message); whether `make`
    # itself is even installed on the test machine is irrelevant to what
    # this test is checking.
    assert "is invalid" not in (result.stdout + result.stderr)
    assert "Rejected args" not in (result.stdout + result.stderr)


@pytest.mark.skipif(_JUST is None, reason="just binary not installed on this machine")
def test_real_just_list_parses_without_error(tmp_path):
    profile_dict = extract_run_profile(_TEMPLATE_MAKEFILE, target_ip="USB", ip_prefix="usb_")
    profile_path = tmp_path / "run_profile.json"
    save_run_profile(profile_dict, profile_path)
    generate_and_write(profile_path, tmp_path / "justfile")

    result = subprocess.run([_JUST, "--list"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0
    for recipe in ("compile", "sim", "regress", "check", "clean", "distclean"):
        assert recipe.replace("_", "-") in result.stdout
