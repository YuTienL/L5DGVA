from __future__ import annotations
import argparse, json
from pathlib import Path
from .memory import (
    MEMORY_LEVELS, MemoryStore, MemoryRetriever, MemoryGC, CornerCaseLibrary,
    CornerCaseLibraryConsolidator, PropertyFilterError, parse_property_filters,
)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--project-root",default=".")
    sp=ap.add_subparsers(dest="cmd",required=True)
    s=sp.add_parser("search")
    s.add_argument("--protocol",default="")
    s.add_argument("--scope",default="")
    s.add_argument("--symptom",action="append",default=[])
    s.add_argument("--text",default="")
    s.add_argument("--level",action="append",default=[],choices=MEMORY_LEVELS,
                    help="Restrict to one or more memory tiers (repeatable).")
    s.add_argument("--confidence",default="",
                    help="Exact confidence filter (CONFIRMED/HIGH/MEDIUM/LOW/UNKNOWN). "
                         "Without it confidence only ranks, never filters.")
    s.add_argument("--status",default="",
                    help="Record status to match; default ACTIVE-only. Use ANY to include "
                         "DEPRECATED/SUPERSEDED records too.")
    s.add_argument("--property",action="append",default=[],dest="properties",metavar="KEY=VALUE",
                    help="Arbitrary record-field filter, repeatable (e.g. --property kind=root_cause). "
                         "Reads the record file for fields index.json does not carry.")
    s.add_argument("--limit",type=int,default=8)
    g=sp.add_parser("get"); g.add_argument("memory_id")
    d=sp.add_parser("deprecate"); d.add_argument("memory_id"); d.add_argument("--reason",required=True)

    ccs=sp.add_parser("corner-case-search")
    ccs.add_argument("--protocol",default="")
    ccs.add_argument("--category",default="")
    ccs.add_argument("--text",default="")
    ccg=sp.add_parser("corner-case-get"); ccg.add_argument("ccl_id")
    cca=sp.add_parser("corner-case-add")
    cca.add_argument("--record",required=True,help="path to a JSON file with the corner_case fields")
    cca.add_argument("--resolution",default=None,
                      help="optional path to a JSON file with {test_mapping,semantic_verdict,runtime_evidence_hash} "
                           "-- when given, goes through CornerCaseLibraryConsolidator's validation gate")
    ccd=sp.add_parser("corner-case-deprecate"); ccd.add_argument("ccl_id"); ccd.add_argument("--reason",required=True)

    sp.add_parser("index-check",help="Read-only drift report between the per-tier record files on disk "
                                      "and index.json's rows (MemoryStore.index_integrity()). Repairs nothing.")
    rix=sp.add_parser("reindex",help="Rebuild index.json from the real record files on disk, restoring any "
                                      "record that had no index row to MemoryRetriever.search() visibility "
                                      "(MemoryStore.reindex()).")
    rix.add_argument("--prune-missing",action="store_true",dest="prune_missing",
                      help="Also DROP index rows whose record file no longer exists (off by default -- such a "
                           "row is already inert for search, and dropping it is destructive).")

    a=ap.parse_args()
    store=MemoryStore(Path(a.project_root))
    if a.cmd=="search":
        try:
            property_filters=parse_property_filters(a.properties)
        except PropertyFilterError as e:
            print(json.dumps({"ok":False,"error":"BAD_PROPERTY_FILTER","detail":str(e)},ensure_ascii=False))
            raise SystemExit(2)
        print(json.dumps(MemoryRetriever(store).search({
            "protocol":a.protocol,"scope":a.scope,"symptoms":a.symptom,"text":a.text,
            "level":a.level,"confidence":a.confidence,"status":a.status,
            "property":property_filters,
        },limit=a.limit),ensure_ascii=False,indent=2))
    elif a.cmd=="get":
        print(json.dumps(store.get(a.memory_id),ensure_ascii=False,indent=2))
    elif a.cmd=="deprecate":
        print("OK" if MemoryGC(store).deprecate(a.memory_id,a.reason) else "NOT_FOUND")
    elif a.cmd=="corner-case-search":
        library=CornerCaseLibrary(Path(a.project_root))
        print(json.dumps(library.search({
            "protocol":a.protocol,"category":a.category,"text":a.text
        }),ensure_ascii=False,indent=2))
    elif a.cmd=="corner-case-get":
        library=CornerCaseLibrary(Path(a.project_root))
        print(json.dumps(library.get(a.ccl_id),ensure_ascii=False,indent=2))
    elif a.cmd=="corner-case-add":
        library=CornerCaseLibrary(Path(a.project_root))
        record=json.loads(Path(a.record).read_text(encoding="utf-8"))
        if a.resolution:
            resolution=json.loads(Path(a.resolution).read_text(encoding="utf-8"))
            rec=CornerCaseLibraryConsolidator(library).from_resolved_corner_case(record,resolution)
        else:
            rec=library.add(record)
        print(json.dumps(rec,ensure_ascii=False,indent=2))
    elif a.cmd=="corner-case-deprecate":
        library=CornerCaseLibrary(Path(a.project_root))
        print("OK" if library.deprecate(a.ccl_id,a.reason) else "NOT_FOUND")
    elif a.cmd=="index-check":
        print(json.dumps(store.index_integrity(),ensure_ascii=False,indent=2))
    elif a.cmd=="reindex":
        print(json.dumps(store.reindex(prune_missing=a.prune_missing),ensure_ascii=False,indent=2))

if __name__=="__main__": main()
