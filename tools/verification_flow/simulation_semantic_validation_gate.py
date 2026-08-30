#!/usr/bin/env python3
import argparse, json, pathlib, re, sys

def norm(s):
    return re.sub(r"\s+"," ",str(s)).strip().lower()

def token_present(pattern, text):
    p=norm(pattern)
    # Treat punctuation separators as boundaries; exact token/attribute matching.
    return re.search(r'(?<![a-z0-9_])'+re.escape(p)+r'(?![a-z0-9_])', text) is not None

def matches(req, text):
    p=norm(req.get("pattern",""))
    mode=req.get("match_mode","TOKEN").upper()
    if not p:
        return False
    if mode=="EXACT_LINE":
        return any(norm(line)==p for line in text.splitlines())
    if mode=="SUBSTRING":
        return p in norm(text)
    if mode=="TOKEN":
        return token_present(p, norm(text))
    return False

def load_sim_log(d):
    """Prefer a real file on disk when the agent supplies one via
    'sim_log_path'. This does NOT prove the file is genuinely this run's
    simulator output (vs a fabricated/stale file at a plausible path) --
    closing that fully needs cross-referencing against lsf_client.py's
    JobState.sim_log, out of scope here. It does close the weaker gap where
    an agent could paste arbitrary text: a bad/missing path now fails
    closed (INSUFFICIENT_EVIDENCE) rather than silently returning ""."""
    path = d.get("sim_log_path")
    if path:
        try:
            p = pathlib.Path(path)
            if not p.is_file():
                return None, f"SIM_LOG_PATH_NOT_FOUND:{path}"
            return p.read_text(encoding="utf-8", errors="replace"), None
        except Exception as ex:
            return None, f"SIM_LOG_PATH_UNREADABLE:{path}:{ex}"
    return d.get("sim_log", ""), None

def convert_legacy(e):
    if "evidence_requirements" not in e:
        e["evidence_requirements"]=[
            {"pattern":x,"match_mode":"SUBSTRING","evidence_type":"LEGACY"}
            for x in e.get("evidence_patterns",[])
        ]
    if "contradiction_requirements" not in e:
        e["contradiction_requirements"]=[
            {"pattern":x,"match_mode":"SUBSTRING","evidence_type":"LEGACY_CONTRADICTION"}
            for x in e.get("contradiction_patterns",[])
        ]
    return e

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.input).read_text())

    if not d.get("simulation_passed"):
        print(json.dumps({"status":"FAIL","final_state":"SIMULATION_FAIL","signoff_credit_allowed":False}))
        return 2

    exps=d.get("command_expectations") or d.get("expectations") or []
    if not exps:
        print(json.dumps({"status":"FAIL","final_state":"INSUFFICIENT_EVIDENCE",
                          "reason":"NO_COMMAND_EXPECTATIONS","signoff_credit_allowed":False}))
        return 3

    ids=[e.get("expectation_id") for e in exps]
    if None in ids or len(ids)!=len(set(ids)):
        print(json.dumps({"status":"FAIL","final_state":"INSUFFICIENT_EVIDENCE",
                          "reason":"DUPLICATE_OR_MISSING_EXPECTATION_ID","signoff_credit_allowed":False}))
        return 6

    log_raw, log_err = load_sim_log(d)
    if log_err:
        print(json.dumps({"status":"FAIL","final_state":"INSUFFICIENT_EVIDENCE",
                          "reason":log_err,"signoff_credit_allowed":False}))
        return 7
    results=[]; missing=[]; contradicted=[]; unobservable=[]

    for raw_e in exps:
        e=convert_legacy(dict(raw_e))
        eid=e["expectation_id"]
        reqs=e.get("evidence_requirements",[])
        antis=e.get("contradiction_requirements",[])
        required=bool(e.get("required",True))

        matched=[r for r in reqs if matches(r,log_raw)]
        anti_hit=[r for r in antis if matches(r,log_raw)]

        if required and not reqs:
            status="UNOBSERVABLE"; unobservable.append(eid)
        elif anti_hit:
            status="CONTRADICTED"; contradicted.append(eid)
        elif len(matched)==len(reqs):
            status="MATCH"
        else:
            status="MISSING"
            if required: missing.append(eid)

        results.append({
            "expectation_id":eid,
            "source_file":e.get("source_file","command.txt"),
            "source_line":e.get("source_line"),
            "testcase_id":e.get("testcase_id"),
            "vplan_ids":e.get("vplan_ids",[]),
            "status":status,
            "evidence_source":"sim.log",
            "matched_requirements":matched,
            "required_requirements":reqs,
            "contradictions_found":anti_hit
        })

    if contradicted or missing:
        print(json.dumps({"status":"FAIL","final_state":"SEMANTIC_MISMATCH",
                          "signoff_credit_allowed":False,
                          "missing":missing,"contradicted":contradicted,"results":results}))
        return 4

    if unobservable:
        print(json.dumps({"status":"FAIL","final_state":"INSUFFICIENT_EVIDENCE",
                          "signoff_credit_allowed":False,
                          "unobservable":unobservable,"results":results}))
        return 5

    print(json.dumps({"status":"PASS","final_state":"TRUE_PASS",
                      "signoff_credit_allowed":True,"results":results}))
    return 0

if __name__=="__main__":
    sys.exit(main())
