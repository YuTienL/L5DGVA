#!/usr/bin/env python3
"""signoff_bundle_completeness_gate.py -- SIGNOFF-stage completeness check.

HARDENING (2026-09-01, trust-boundary-hardening design pass): "bundle_hash"
used to be a bare self-reported string -- dv_harness/signoff_export.py's
collect_signoff_bundle() had no hash field at all, so nothing in this
codebase could ever have produced the value being checked. Now requires a
real "bundle_dir" evidence field (a real collect_signoff_bundle() out_dir),
reads its real manifest.json off disk, recomputes
dv_harness.signoff_export.compute_bundle_hash() over that real manifest
content itself, and requires the agent's claimed "bundle_hash" to equal the
real recomputed value exactly (BUNDLE_HASH_MISMATCH otherwise) -- the
self-reported value is never trusted on its own. Also requires the real
manifest to show a "self_audit_result" entry with present:true -- the one
artifact collect_signoff_bundle() always freshly generates in-process,
doubling as a tripwire that bundle_dir is real signoff-export output and
not an arbitrary directory with a hand-crafted manifest.json dropped in it.

RULING (per design doc's scope_boundary, "OUT OF SCOPE"): the pre-existing
per-class evidence check below (SPEC_TRACE/BUILD/TEST/ASSERTION/SCOREBOARD/
COVERAGE/REGRESSION/RCA_FIX/ENV_FINGERPRINT, each needing an agent-attested
"hash") is left exactly as-is -- no mapping from these 9 class names to
collect_signoff_bundle()'s 10 real candidate artifacts exists anywhere in
this codebase, and inventing one here would be exactly the kind of
plausible-looking-but-unverified mapping CLAUDE.md's Evidence Truth Rule
warns against. Out of scope for this pass; left unmapped.

RULING: deliberately reads the already-produced manifest.json rather than
re-invoking collect_signoff_bundle() fresh inside this gate -- re-invocation
would re-run real file-copy I/O plus a fresh self_audit.run_self_audit()
inside run_gate()'s 30s subprocess timeout. Flagged as a hardening
follow-up, not v1.
"""
import argparse, json, pathlib, sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
from dv_harness.signoff_export import compute_bundle_hash  # noqa: E402

REQUIRED_CLASSES = {"SPEC_TRACE", "BUILD", "TEST", "ASSERTION", "SCOREBOARD",
                    "COVERAGE", "REGRESSION", "RCA_FIX", "ENV_FINGERPRINT"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.bundle).read_text())

    got = {e.get("class") for e in d.get("evidence", []) if e.get("hash")}
    missing = sorted(REQUIRED_CLASSES - got)
    if missing:
        print(json.dumps({"status": "FAIL", "reason": "INCOMPLETE_SIGNOFF_BUNDLE", "missing": missing}))
        return 2
    if d.get("final_verdict") != "PASS":
        print(json.dumps({"status": "FAIL", "reason": "INVALID_FINAL_SIGNOFF_BUNDLE"}))
        return 3

    claimed_bundle_hash = d.get("bundle_hash")
    if not claimed_bundle_hash:
        print(json.dumps({"status": "FAIL", "reason": "INVALID_FINAL_SIGNOFF_BUNDLE"}))
        return 3

    bundle_dir_str = d.get("bundle_dir")
    if not bundle_dir_str:
        print(json.dumps({"status": "FAIL", "reason": "MISSING_BUNDLE_DIR"}))
        return 4

    manifest_path = pathlib.Path(bundle_dir_str) / "manifest.json"
    if not manifest_path.is_file():
        print(json.dumps({"status": "FAIL", "reason": "BUNDLE_DIR_MANIFEST_NOT_FOUND",
                           "bundle_dir": bundle_dir_str}))
        return 5

    try:
        manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError:
        print(json.dumps({"status": "FAIL", "reason": "BUNDLE_MANIFEST_MALFORMED",
                           "bundle_dir": bundle_dir_str}))
        return 6

    # manifest.json's real shape (see signoff_export.collect_signoff_bundle):
    # {"manifest": [...], "bundle_hash": "..."}.
    manifest_list = manifest_doc.get("manifest") if isinstance(manifest_doc, dict) else None
    if not isinstance(manifest_list, list):
        print(json.dumps({"status": "FAIL", "reason": "BUNDLE_MANIFEST_MALFORMED",
                           "bundle_dir": bundle_dir_str}))
        return 6

    self_audit_entry = next((m for m in manifest_list if m.get("artifact") == "self_audit_result"), None)
    if not self_audit_entry or not self_audit_entry.get("present"):
        print(json.dumps({"status": "FAIL", "reason": "BUNDLE_SELF_AUDIT_RESULT_MISSING",
                           "bundle_dir": bundle_dir_str}))
        return 7

    real_bundle_hash = compute_bundle_hash(manifest_list)
    if claimed_bundle_hash != real_bundle_hash:
        print(json.dumps({"status": "FAIL", "reason": "BUNDLE_HASH_MISMATCH",
                           "claimed": claimed_bundle_hash, "real": real_bundle_hash}))
        return 8

    print(json.dumps({"status": "PASS", "bundle_hash": real_bundle_hash}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
