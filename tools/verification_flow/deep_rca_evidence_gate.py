#!/usr/bin/env python3
import argparse,hashlib,json,pathlib,sys
REQ={"SIM_LOG","TRACE","RTL","TESTBENCH","COMMAND","SCOREBOARD","PHY_MODEL","STANDARD_SPEC","VIP_EXAMPLE","VIP_SOURCE","VIP_DOCUMENT"}
ap=argparse.ArgumentParser(); ap.add_argument("--rca",required=True); ap.add_argument("--root",required=True); a=ap.parse_args()
root=pathlib.Path(a.root)
d=json.loads(pathlib.Path(a.rca).read_text())

# Independent hash recompute (2026-09-02, RE_AUDIT evidence-gate audit
# follow-up): before this, an evidence_sources[] entry only had to carry a
# non-empty `evidence_hash` string -- nothing here ever recomputed a hash of
# the real current sim.log/RTL/waveform file on disk, so an agent could cite
# a stale hash recalled from memory (or a fabricated one) and still PASS.
# A source entry may now additionally carry `evidence_path` (relative to the
# real project root -- harness-supplied via ContextFlag("--root", ...) in
# gates.STAGE_GATES, never agent-attested, same convention already used by
# feature_continuity_gate/protocol_builder_registry_conformance_gate): when
# present, this gate independently reads that real file and compares its
# current sha256 against the agent's claimed evidence_hash, FAILing
# EVIDENCE_HASH_STALE_OR_FABRICATED on any mismatch. `evidence_path` stays
# OPTIONAL: sources like STANDARD_SPEC/VIP_DOCUMENT/VIP_EXAMPLE often cite
# text outside this project's own repo (a datasheet, a VIP vendor doc) with
# no single canonical on-disk path to hash, and older callers may not supply
# it yet -- those fall back to the original non-empty evidence_hash check
# below, which is the weaker/legacy path.
for x in d.get("evidence_sources", []):
    ep = x.get("evidence_path")
    if not ep:
        continue
    fp = root / ep
    if not fp.is_file():
        print(json.dumps({"status": "FAIL", "reason": "EVIDENCE_PATH_NOT_FOUND",
                          "source": x.get("source"), "evidence_path": ep})); sys.exit(8)
    real_hash = hashlib.sha256(fp.read_bytes()).hexdigest()
    if real_hash != x.get("evidence_hash"):
        print(json.dumps({"status": "FAIL", "reason": "EVIDENCE_HASH_STALE_OR_FABRICATED",
                          "source": x.get("source"), "evidence_path": ep,
                          "claimed_hash": x.get("evidence_hash"), "actual_hash": real_hash})); sys.exit(9)

p={x.get("source") for x in d.get("evidence_sources",[]) if x.get("checked") and x.get("evidence_hash")}
m=sorted(REQ-p)
if m: print(json.dumps({"status":"FAIL","reason":"DEEP_RCA_EVIDENCE_INCOMPLETE","missing":m})); sys.exit(2)
if not d.get("first_bad_event"): print(json.dumps({"status":"FAIL","reason":"NO_FIRST_BAD_EVENT"})); sys.exit(3)
if len(d.get("causal_chain",[]))<2: print(json.dumps({"status":"FAIL","reason":"NO_CAUSAL_CHAIN"})); sys.exit(4)
if d.get("confidence") not in ("HIGH","VERIFIED","BLOCKED"):
 print(json.dumps({"status":"FAIL","reason":"RCA_CONFIDENCE_TOO_LOW"})); sys.exit(5)
if d.get("confidence")=="BLOCKED" and not (d.get("missing_evidence") and d.get("next_action")):
 print(json.dumps({"status":"FAIL","reason":"BLOCKED_WITHOUT_NEXT_ACTION"})); sys.exit(6)
print(json.dumps({"status":"PASS"}))
