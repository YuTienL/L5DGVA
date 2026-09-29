#!/usr/bin/env python3
import argparse, importlib.util, json, pathlib, re, sys

# WIRING FIX (2026-09-01, command-semantic-parser-wiring task): this gate
# previously trusted "command_expectations" as pure agent-attested text --
# nothing anywhere in the live VERIFY chain ever independently re-derived
# what command.txt actually requires (command_intent_semantic_closure_gate
# also VERIFY-stage compares two agent-self-reported strings to each other,
# not to a real parse of the file). command_semantic_expectation_parser.py
# is a real, deterministic, already-written command.txt-intent extractor
# that sat orphaned (referenced only from the non-executed documentation
# registry .dv-harness/workflow/verification_flow_v13.json's
# "simulation_pass_semantics.order" list, never imported by any live gate).
# load_command_semantic_expectation_parser() below wires it in directly:
# 'command_file_path' (same "read the real file on disk" pattern as
# load_sim_log()'s 'sim_log_path' just below) drives
# cross_check_against_command_file(), which re-derives each line's minimum
# required evidence/contradiction patterns from the actual file and fails
# closed if the agent's own command_expectations under-report them.
#
# MANDATORY-FIELD FIX (2026-09-02, TRUE_PASS prompt-gap closure): the field
# was originally OPTIONAL/additive so existing callers that never supplied a
# command.txt path stayed unaffected -- but the real VERIFY-stage prompt
# (dv_harness/prompts.py) never asked the agent for 'command_file_path' or
# 'sim_log_path' either, so in production no real evidence block has ever
# actually supplied them: the independent cross-check this wiring exists for
# has never once fired outside of tests that deliberately construct the
# field by hand. Optionality without a prompt that asks for the field is
# indistinguishable from the field not existing at all. Both
# 'command_file_path' and 'sim_log_path' are now REQUIRED: their absence is
# INSUFFICIENT_EVIDENCE, same failure-closed treatment as a bad path. This
# is a real, intentional behavior change, not backward compatible with the
# prior optional design -- see MEM-<pending> / the prompt template update in
# the same commit for the other half of this fix.
_PARSER_SCRIPT = pathlib.Path(__file__).resolve().parent / "command_semantic_expectation_parser.py"


def load_command_semantic_expectation_parser():
    """Loads the sibling command_semantic_expectation_parser.py module by
    file path (not a package import -- these gate scripts are standalone
    files with no package __init__, invoked individually via subprocess) so
    its real parse_line() can be called in-process instead of reimplementing
    or re-guessing its extraction rules here."""
    spec = importlib.util.spec_from_file_location(
        "command_semantic_expectation_parser", _PARSER_SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pattern_key(req):
    return (str(req.get("pattern", "")).strip().lower(), str(req.get("match_mode", "TOKEN")).upper())


def cross_check_against_command_file(command_file_path, exps):
    """Re-derives, from the REAL command.txt on disk, the minimum
    evidence/contradiction patterns command_semantic_expectation_parser.py
    deterministically extracts per line, then verifies the agent-supplied
    `exps` (already-parsed command_expectations, matched by source_line)
    covers at least that minimum set. The agent may supply MORE requirements
    than the deterministic parser found (it is a necessary-minimum baseline,
    not an exhaustive one) but may not supply fewer -- that would be
    self-reported evidence quietly watered down versus what the actual
    command.txt line requires.

    Returns (error, under_reported): `error` is a (reason, detail) pair for
    a hard failure reading the file (never None AND populated together with
    under_reported); `under_reported` is a list of per-line gap dicts, empty
    when every derived requirement is covered."""
    p = pathlib.Path(command_file_path)
    if not p.is_file():
        return ("COMMAND_FILE_PATH_NOT_FOUND", f"COMMAND_FILE_PATH_NOT_FOUND:{command_file_path}"), []
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as ex:
        return ("COMMAND_FILE_PATH_UNREADABLE", f"COMMAND_FILE_PATH_UNREADABLE:{command_file_path}:{ex}"), []

    parser_mod = load_command_semantic_expectation_parser()
    by_line_agent = {}
    for e in exps:
        ln = e.get("source_line")
        if ln is not None:
            by_line_agent.setdefault(ln, []).append(convert_legacy(dict(e)))

    under_reported = []
    for line_no, line in enumerate(lines, 1):
        derived = parser_mod.parse_line(line, line_no)
        if not derived:
            continue
        derived_reqs = {_pattern_key(r) for r in derived.get("evidence_requirements", [])}
        derived_anti = {_pattern_key(r) for r in derived.get("contradiction_requirements", [])}
        if not derived_reqs and not derived_anti:
            continue  # deterministic parser could establish nothing for this line -- no baseline to enforce
        agent_entries = by_line_agent.get(line_no, [])
        agent_reqs, agent_anti = set(), set()
        for e in agent_entries:
            agent_reqs |= {_pattern_key(r) for r in e.get("evidence_requirements", [])}
            agent_anti |= {_pattern_key(r) for r in e.get("contradiction_requirements", [])}
        missing_reqs = sorted(f"{pat}|{mode}" for pat, mode in (derived_reqs - agent_reqs))
        missing_anti = sorted(f"{pat}|{mode}" for pat, mode in (derived_anti - agent_anti))
        if missing_reqs or missing_anti:
            under_reported.append({
                "source_line": line_no,
                "raw_command": derived.get("raw_command"),
                "missing_evidence_requirements": missing_reqs,
                "missing_contradiction_requirements": missing_anti,
            })
    return None, under_reported


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

    command_file_path = d.get("command_file_path")
    if not command_file_path:
        print(json.dumps({"status":"FAIL","final_state":"INSUFFICIENT_EVIDENCE",
                          "reason":"MISSING_COMMAND_FILE_PATH","signoff_credit_allowed":False}))
        return 10

    cc_error, under_reported = cross_check_against_command_file(command_file_path, exps)
    if cc_error:
        reason, detail = cc_error
        print(json.dumps({"status":"FAIL","final_state":"INSUFFICIENT_EVIDENCE",
                          "reason":detail,"signoff_credit_allowed":False}))
        return 8
    if under_reported:
        print(json.dumps({"status":"FAIL","final_state":"COMMAND_TXT_INTENT_UNDER_REPORTED",
                          "reason":"COMMAND_EXPECTATIONS_UNDER_REPORT_COMMAND_TXT",
                          "signoff_credit_allowed":False,"under_reported":under_reported}))
        return 9

    if not d.get("sim_log_path"):
        print(json.dumps({"status":"FAIL","final_state":"INSUFFICIENT_EVIDENCE",
                          "reason":"MISSING_SIM_LOG_PATH","signoff_credit_allowed":False}))
        return 11

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
