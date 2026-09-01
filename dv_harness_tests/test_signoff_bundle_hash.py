"""Tests for dv_harness/signoff_export.py's compute_bundle_hash -- the real,
independently-recomputable producer of the signoff bundle's "bundle_hash"
field (previously self-reported with zero real producer anywhere in the
codebase). Style mirrors dv_harness_tests/test_source_identity.py's tests
for tools/remote/source_identity.py's aggregate_source_id, which this
function is deliberately modeled on."""
from __future__ import annotations

from dv_harness.signoff_export import compute_bundle_hash


def test_compute_bundle_hash_deterministic_regardless_of_manifest_order():
    m1 = [
        {"artifact": "vplan", "present": True, "bundled_path": "vplan"},
        {"artifact": "telemetry", "present": False, "bundled_path": None},
    ]
    m2 = [
        {"artifact": "telemetry", "present": False, "bundled_path": None},
        {"artifact": "vplan", "present": True, "bundled_path": "vplan"},
    ]
    assert compute_bundle_hash(m1) == compute_bundle_hash(m2)


def test_compute_bundle_hash_changes_when_content_changes():
    base = [{"artifact": "vplan", "present": True, "bundled_path": "vplan"}]
    changed_presence = [{"artifact": "vplan", "present": False, "bundled_path": None}]
    changed_path = [{"artifact": "vplan", "present": True, "bundled_path": "vplan_v2"}]
    h_base = compute_bundle_hash(base)
    assert h_base != compute_bundle_hash(changed_presence)
    assert h_base != compute_bundle_hash(changed_path)


def test_compute_bundle_hash_empty_manifest_is_stable():
    # An empty manifest still produces a real, deterministic digest (the
    # sha256 of an empty string), never an exception or a fabricated value.
    import hashlib
    assert compute_bundle_hash([]) == hashlib.sha256(b"").hexdigest()


def test_compute_bundle_hash_is_a_real_hex_sha256_digest():
    manifest = [{"artifact": "self_audit_result", "present": True, "bundled_path": "self_audit_result.json"}]
    digest = compute_bundle_hash(manifest)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
