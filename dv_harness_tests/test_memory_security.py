"""Tests for dv_harness/memory_security.py -- Phase 19 (Security: secret
detection & redaction) of the Obsidian+Git/Markdown Hybrid Engineering
Memory spec, Workstream 2 of 4.

The three required real-incident-shaped test cases (per the task spec) are
explicit here: a VCPW=<value>-shaped assignment (this project's own real
2026-09-03 credential-leak incident pattern), SSH private key headers, and a
common API-key/token shape -- plus the spec's other named categories
(passwords, generic tokens, license credentials, personal credentials in a
URL) and the idempotency guarantee memory_vault.py's update()/memory_doctor's
re-scan both depend on.
"""
from __future__ import annotations

from dv_harness import memory_security as msec


# --- Phase 19's 3 explicitly-named real-incident-shaped cases ---------------

def test_detects_vc_password_real_incident_shape():
    # This project's own real 2026-09-03 credential-leak incident: a VCPW
    # value embedded directly in a config/permission file.
    text = "allow bash: VCPW=Sup3rSecretPass123 ssh vchost-a"
    findings = msec.detect_secrets(text)
    types = {f["type"] for f in findings}
    assert "vc_password" in types
    # the real secret value itself must never appear in a finding's preview
    assert all("Sup3rSecretPass123" not in f["preview"] for f in findings)


def test_redacts_vc_password_but_preserves_the_key_name():
    text = "VCPW=Sup3rSecretPass123"
    redacted, findings = msec.redact_secrets(text)
    assert "Sup3rSecretPass123" not in redacted
    assert redacted.startswith("VCPW=")
    assert "REDACTED" in redacted
    assert any(f["type"] == "vc_password" for f in findings)


def test_detects_and_redacts_ssh_private_key_header():
    text = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gt\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )
    findings = msec.detect_secrets(text)
    assert any(f["type"] == "ssh_private_key" for f in findings)
    assert findings[0]["preview"] == "<SSH PRIVATE KEY BLOCK>"

    redacted, findings2 = msec.redact_secrets(text)
    assert "BEGIN OPENSSH PRIVATE KEY" not in redacted
    assert "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ" not in redacted
    assert "***REDACTED-SSH_PRIVATE_KEY***" == redacted


def test_detects_common_api_key_and_token_shapes():
    cases = {
        "export API_KEY=abcdEFGH12345678901234": "api_key_or_token",
        "AKIAABCDEFGHIJKLMNOP": "aws_access_key_id",
        "ghp_1234567890abcdefghijklmnopqrstuvwxyz12": "github_token",
        "xoxb-1234567890-abcdefghijklmnop": "slack_token",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c": "jwt",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789": "bearer_token",
    }
    for text, expected_type in cases.items():
        findings = msec.detect_secrets(text)
        types = {f["type"] for f in findings}
        assert expected_type in types, f"expected {expected_type} in {types} for {text!r}"


# --- Other spec-named categories --------------------------------------------

def test_detects_generic_password_assignment():
    findings = msec.detect_secrets("PASSWORD=hunter2")
    assert any(f["type"] == "password" for f in findings)


def test_detects_license_key_assignment_and_shape():
    findings1 = msec.detect_secrets("LICENSE_KEY=ABCD-1234-EFGH-5678")
    assert any(f["type"] in ("license_key_assignment", "license_key_shape") for f in findings1)

    findings2 = msec.detect_secrets("activation code: AB12-CD34-EF56-7890 keep safe")
    assert any(f["type"] == "license_key_shape" for f in findings2)


def test_detects_personal_credential_embedded_in_url():
    findings = msec.detect_secrets("clone https://alice:S3cretPW1@git.example.com/repo.git")
    assert any(f["type"] == "url_embedded_credential" for f in findings)
    redacted, _ = msec.redact_secrets("https://alice:S3cretPW1@git.example.com/repo.git")
    assert "S3cretPW1" not in redacted
    assert "alice" in redacted  # username preserved, only the password redacted


def test_no_false_positive_on_ordinary_prose():
    text = ("The phy clock domain crossing missing a sync flop caused an "
            "endpoint stall during high-speed bulk transfer; fixed by adding "
            "a 2-flop synchronizer in rev2.")
    assert msec.detect_secrets(text) == []
    redacted, findings = msec.redact_secrets(text)
    assert redacted == text
    assert findings == []


# --- Idempotency (critical: memory_vault.update() re-redacts the FULL merged
# content on every call, and memory_doctor.check_secrets() re-scans raw
# on-disk text -- an already-redacted marker must never be re-flagged or
# re-wrapped, or a note would perpetually and incorrectly report BLOCKED). --

def test_redaction_is_idempotent():
    text = "VCPW=hunter2secret"
    once, findings1 = msec.redact_secrets(text)
    assert findings1
    twice, findings2 = msec.redact_secrets(once)
    assert twice == once
    assert findings2 == []  # already-redacted marker is never re-detected as a NEW finding


def test_detect_secrets_does_not_flag_an_already_redacted_marker():
    already = "failure: endpoint stall VCPW=***REDACTED-VC_PASSWORD*** bulk transfer"
    assert msec.detect_secrets(already) == []


# --- Note-level wrappers (redact_frontmatter/redact_sections/redact_note_content) --

def test_redact_frontmatter_only_touches_free_text_fields_not_structural_ones():
    fm = {
        "id": "NOTE-VCPW-LOOKS-LIKE-ID",  # must never be touched -- structural
        "memory_level": "engineering",
        "failure": "stall with VCPW=hunter2 embedded",
        "protocol": "USB",
        "confidence": "MEDIUM",
    }
    out, findings = msec.redact_frontmatter(fm)
    assert out["id"] == "NOTE-VCPW-LOOKS-LIKE-ID"  # untouched
    assert "hunter2" not in out["failure"]
    assert any(f["field"] == "failure" for f in findings)


def test_redact_frontmatter_scans_list_values_too():
    fm = {"tags": ["usb", "VCPW=leaked-tag-value", "clock-domain"]}
    out, findings = msec.redact_frontmatter(fm)
    assert "leaked-tag-value" not in " ".join(out["tags"])
    assert out["tags"][0] == "usb"
    assert out["tags"][2] == "clock-domain"
    assert findings


def test_redact_sections_labels_finding_field_with_section_prefix():
    sections = {"Root Cause": "clean", "Evidence": "log shows PASSWORD=abc123 in the dump"}
    out, findings = msec.redact_sections(sections)
    assert out["Root Cause"] == "clean"
    assert "abc123" not in out["Evidence"]
    assert findings[0]["field"] == "section:Evidence"


def test_redact_note_content_combines_frontmatter_and_sections():
    fm = {"id": "N1", "failure": "VCPW=abc"}
    sections = {"Root Cause": "PASSWORD=def"}
    fm_out, sections_out, findings = msec.redact_note_content(fm, sections)
    assert "abc" not in fm_out["failure"]
    assert "def" not in sections_out["Root Cause"]
    assert len(findings) == 2


def test_redact_note_content_handles_no_sections():
    fm_out, sections_out, findings = msec.redact_note_content({"id": "N1", "failure": "clean"}, None)
    assert sections_out is None
    assert findings == []
