#!/usr/bin/env python3
import argparse, json, pathlib, sys

VALID_STATUSES = {"IMPLEMENTED", "WAIVED", "NOT_APPLICABLE"}
VALID_OWNER_KINDS = {"SLAVE", "RESERVED", "DECODE_ERROR"}

def parse_addr(v):
    if isinstance(v, int):
        return v
    s = str(v).strip().replace("_", "")
    return int(s, 0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topology", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.topology).read_text())

    if d.get("topology_applicable") is False:
        reason = d.get("topology_not_applicable_reason")
        if not reason:
            print(json.dumps({"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}))
            return 2
        print(json.dumps({"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}))
        return 0

    required_top = ["masters", "slaves", "scoreboard_matrix", "address_map"]
    missing = [k for k in required_top if k not in d]
    if missing:
        print(json.dumps({"status": "FAIL", "reason": "MISSING_FIELDS", "missing": missing}))
        return 3

    masters = d.get("masters") or []
    slaves = d.get("slaves") or []
    matrix = d.get("scoreboard_matrix") or []
    amap = d.get("address_map") or []

    if not masters:
        print(json.dumps({"status": "FAIL", "reason": "NO_MASTERS"}))
        return 4
    if not slaves:
        print(json.dumps({"status": "FAIL", "reason": "NO_SLAVES"}))
        return 5
    if len(set(masters)) != len(masters):
        dup = sorted({m for m in masters if masters.count(m) > 1})
        print(json.dumps({"status": "FAIL", "reason": "DUPLICATE_MASTER_ID", "duplicates": dup}))
        return 6
    if len(set(slaves)) != len(slaves):
        dup = sorted({s for s in slaves if slaves.count(s) > 1})
        print(json.dumps({"status": "FAIL", "reason": "DUPLICATE_SLAVE_ID", "duplicates": dup}))
        return 7

    master_set = set(masters)
    slave_set = set(slaves)

    # ---- scoreboard matrix M x N completeness ----
    expected_pairs = {(m, s) for m in masters for s in slaves}
    seen_pairs = {}
    for i, entry in enumerate(matrix):
        mid = entry.get("master_id")
        sid = entry.get("slave_id")
        status = entry.get("status")
        if mid not in master_set:
            print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_MASTER_IN_SCOREBOARD_MATRIX",
                              "index": i, "master_id": mid}))
            return 8
        if sid not in slave_set:
            print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_SLAVE_IN_SCOREBOARD_MATRIX",
                              "index": i, "slave_id": sid}))
            return 9
        if status not in VALID_STATUSES:
            print(json.dumps({"status": "FAIL", "reason": "INVALID_SCOREBOARD_STATUS",
                              "index": i, "master_id": mid, "slave_id": sid, "status": status}))
            return 10
        if status in ("WAIVED", "NOT_APPLICABLE") and not (entry.get("waiver_approved") and entry.get("waiver_evidence")):
            print(json.dumps({"status": "FAIL", "reason": "UNAPPROVED_SCOREBOARD_WAIVER",
                              "master_id": mid, "slave_id": sid}))
            return 11
        pair = (mid, sid)
        if pair in seen_pairs:
            print(json.dumps({"status": "FAIL", "reason": "DUPLICATE_SCOREBOARD_ENTRY",
                              "master_id": mid, "slave_id": sid}))
            return 12
        seen_pairs[pair] = status

    missing_pairs = sorted(expected_pairs - set(seen_pairs))
    if missing_pairs:
        print(json.dumps({"status": "FAIL", "reason": "MISSING_SCOREBOARD_PAIRS",
                          "expected_pair_count": len(expected_pairs),
                          "missing_pairs": [f"{m}->{s}" for m, s in missing_pairs]}))
        return 13

    # ---- address map completeness (no gap / no overlap) ----
    regions = []
    for i, r in enumerate(amap):
        owner = r.get("owner")
        owner_kind = r.get("owner_kind") or ("SLAVE" if owner in slave_set else None)
        if owner_kind not in VALID_OWNER_KINDS:
            print(json.dumps({"status": "FAIL", "reason": "INVALID_ADDRESS_MAP_OWNER_KIND",
                              "index": i, "owner": owner, "owner_kind": owner_kind}))
            return 14
        if owner_kind == "SLAVE" and owner not in slave_set:
            print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_SLAVE_IN_ADDRESS_MAP",
                              "index": i, "owner": owner}))
            return 15
        try:
            start = parse_addr(r.get("start_addr"))
            end = parse_addr(r.get("end_addr"))
        except Exception:
            print(json.dumps({"status": "FAIL", "reason": "UNPARSEABLE_ADDRESS", "index": i,
                              "start_addr": r.get("start_addr"), "end_addr": r.get("end_addr")}))
            return 16
        if end <= start:
            print(json.dumps({"status": "FAIL", "reason": "NON_POSITIVE_ADDRESS_RANGE", "index": i,
                              "start_addr": r.get("start_addr"), "end_addr": r.get("end_addr")}))
            return 17
        regions.append({"index": i, "owner": owner, "owner_kind": owner_kind, "start": start, "end": end})

    missing_slave_range = sorted(slave_set - {r["owner"] for r in regions if r["owner_kind"] == "SLAVE"})
    if missing_slave_range:
        print(json.dumps({"status": "FAIL", "reason": "SLAVE_WITHOUT_ADDRESS_RANGE", "slaves": missing_slave_range}))
        return 18

    regions.sort(key=lambda r: r["start"])
    for prev, cur in zip(regions, regions[1:]):
        if cur["start"] < prev["end"]:
            print(json.dumps({"status": "FAIL", "reason": "ADDRESS_MAP_OVERLAP",
                              "region_a": {"owner": prev["owner"], "start": prev["start"], "end": prev["end"]},
                              "region_b": {"owner": cur["owner"], "start": cur["start"], "end": cur["end"]}}))
            return 19
        if cur["start"] > prev["end"]:
            print(json.dumps({"status": "FAIL", "reason": "ADDRESS_MAP_GAP",
                              "after": {"owner": prev["owner"], "end": prev["end"]},
                              "before": {"owner": cur["owner"], "start": cur["start"]},
                              "gap_size": cur["start"] - prev["end"]}))
            return 20

    print(json.dumps({"status": "PASS", "masters": len(masters), "slaves": len(slaves),
                      "scoreboard_pairs": len(expected_pairs), "address_regions": len(regions)}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
