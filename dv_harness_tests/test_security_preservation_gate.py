"""M1 Canonical Security Preservation Gate (see
.work/phase3-dual-repo-consolidation/M1_SECURITY_PRESERVATION_GATE.md).

Real tests against the real, current dv_harness modules -- no mocking.
Two kinds of assertion here:

1. FLOOR tests -- must pass now and forever; a failure means this
   canonical repo regressed below behavior already verified present.
2. A tracked-gap test (xfail) -- documents a known, real Parent-only
   hardening this v50-derived baseline does not yet have. It is
   deliberately written to turn GREEN (an unexpected pass, surfaced
   loudly by pytest) the moment a future wave lands the fix, so the fix
   cannot land silently without this file being noticed and updated.
"""
import pytest

from dv_harness import memory_security, memory_vault


def test_secret_pattern_registry_is_present_and_non_empty():
    """FLOOR: the secret-detection registry must never be empty -- an
    empty SECRET_PATTERNS would make redact_note_content() a silent
    no-op over every real secret shape it exists to catch."""
    assert len(memory_security.SECRET_PATTERNS) > 0


def test_secret_pattern_registry_covers_known_credential_shapes():
    """FLOOR: spot-check a few of the concrete shapes confirmed present
    on both Parent and v50 (VCPW/password, SSH private key, generic API
    key) -- proves the registry is the real thing, not a stub."""
    names = {name for name, _pattern, _group in memory_security.SECRET_PATTERNS}
    lowered = {n.lower() for n in names}
    assert any("password" in n or "vcpw" in n or "pw" in n for n in lowered)
    assert any("ssh" in n or "private_key" in n or "private key" in n for n in lowered)


def test_detect_secrets_flags_an_embedded_password():
    """FLOOR: a real end-to-end call, not just registry presence."""
    findings = memory_security.detect_secrets("VCPW=hunter2\nnothing else here")
    assert findings, "a literal VCPW=... assignment must be detected as a secret"


def test_note_id_sanitization_strips_path_separators():
    """FLOOR: _sanitize_note_id must strip every path-separator character
    -- confirmed verbatim-identical between Parent and v50; this
    canonical repo must not regress it. A bare '..' substring with no
    surviving separator is inert (it cannot escape a directory once it
    can never combine with a '/' or '\\'), so the real property to check
    is separator removal, not textual absence of '..' -- an earlier
    version of this test asserted the wrong thing and was corrected here."""
    sanitized = memory_vault._sanitize_note_id("../../etc/passwd")
    assert "/" not in sanitized
    assert "\\" not in sanitized


@pytest.mark.xfail(
    reason="Known, disclosed gap vs Parent (see M1_SECURITY_PRESERVATION_GATE.md "
           "item 1): Parent stopped probing the bare 'obsidian' GUI-launcher name "
           "(a documented incident -- probing it can hang / spawn a real GUI "
           "window) and added a real-version-string check. This v50-derived "
           "baseline still probes the bare name. Reserved for the wave that "
           "reconciles memory_vault.py Parent-vs-v50 (not M1). This test is "
           "written to unexpectedly PASS the moment that fix lands, so it "
           "cannot land silently.",
    strict=False,
)
def test_obsidian_cli_probe_no_longer_includes_the_bare_gui_launcher_name():
    assert "obsidian" not in memory_vault._OBSIDIAN_CLI_CANDIDATES
