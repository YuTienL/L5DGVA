#!/usr/bin/env python3
"""Meta/registry-consistency check for the shared, cross-user knowledge
center (dv_harness/knowledge_center.py, tools/knowledge_center/broker.py) --
NOT a per-DUT run's evidence gate. Registered as a JSON_GATES entry in
dv_harness/self_audit.py, same as its 15 siblings: it checks the harness's
OWN registry/schema/provenance discipline over the shared store's records,
not a single project's stage evidence.

Closest existing gates in spirit (per the registry-docs-audit that motivated
this file): gate_manifest_registry_consistency_gate (structural agreement
between a registry and real entries) and schema_reference_integrity_gate (no
orphans) -- this gate adds what neither of those check: that individual
shared-knowledge records (a) declare a category the taxonomy manifest
actually recognizes, (b) carry a provenance block (who/where wrote it -- the
audit that motivated this feature found ZERO identity fields anywhere in the
pre-existing memory/CCL schemas), (c) use only the lifecycle's known status
vocabulary, and (d) are never silently ACTIVE past their own revalidate_by
expiry -- CLAUDE.md's "memory is prior knowledge, not current evidence"
extends to age, not just explicit retraction, and this catches a broker/
client bug that let a stale record slip through as though still trustworthy.

Payload contract (--catalog):
{
  "manifest": {"schema_version": 1, "categories": ["usb", "pcie", ...]},
  "records": [
    {"memory_id": "...", "category": "usb", "protocol": "usb",
     "status": "ACTIVE", "written_at": 123.0, "revalidate_by": 456.0 | null,
     "provenance": {"origin_user": "...", "origin_host": "..."} },
    ...
  ],
  "now": 999.0   # optional; defaults to the evaluating machine's own clock
}
"""
import argparse, json, pathlib, sys, time

VALID_STATUSES = {"ACTIVE", "NEEDS_REVALIDATION", "SUPERSEDED", "RETRACTED"}

ap = argparse.ArgumentParser()
ap.add_argument("--catalog", required=True)
a = ap.parse_args()
d = json.loads(pathlib.Path(a.catalog).read_text(encoding="utf-8"))

manifest = d.get("manifest") or {}
records = d.get("records") or []
now = d.get("now", time.time())

reasons = []

if not isinstance(manifest.get("schema_version"), int):
    reasons.append("MANIFEST_MISSING_SCHEMA_VERSION")
categories = manifest.get("categories")
if not isinstance(categories, list) or not categories:
    reasons.append("MANIFEST_MISSING_CATEGORIES")
    categories = []
category_set = set(categories)

for rec in records:
    rid = rec.get("memory_id") or "<no-id>"
    cat = rec.get("category")
    if categories and cat not in category_set:
        reasons.append(f"{rid}: category '{cat}' not in manifest.categories")
    if not rec.get("protocol"):
        reasons.append(f"{rid}: missing protocol")
    status = rec.get("status")
    if status not in VALID_STATUSES:
        reasons.append(f"{rid}: status '{status}' not one of {sorted(VALID_STATUSES)}")
    provenance = rec.get("provenance")
    if not isinstance(provenance, dict) or not provenance.get("origin_user"):
        reasons.append(f"{rid}: missing provenance.origin_user "
                        f"(every shared record must be attributable to a user)")
    revalidate_by = rec.get("revalidate_by")
    if status == "ACTIVE" and revalidate_by is not None:
        try:
            if float(revalidate_by) < float(now):
                reasons.append(f"{rid}: status is ACTIVE but revalidate_by ({revalidate_by}) "
                                f"has already passed (now={now}) -- stale record not being filtered")
        except (TypeError, ValueError):
            reasons.append(f"{rid}: revalidate_by is not a number: {revalidate_by!r}")

if reasons:
    print(json.dumps({"status": "FAIL", "reason": "KNOWLEDGE_CENTER_REGISTRY_INCONSISTENT",
                       "problems": reasons}))
    sys.exit(2)
print(json.dumps({"status": "PASS", "records_checked": len(records),
                   "categories": sorted(category_set)}))
