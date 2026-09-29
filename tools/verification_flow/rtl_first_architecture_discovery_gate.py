#!/usr/bin/env python3
# BUG FIX (2026-09-01, RTL-first-architecture-discovery provenance audit):
# every check below this point used to validate only the SHAPE of the
# self-reported architecture evidence (which category flags were set, which
# unknown_items had a next_action, ...) -- nothing tied any of it back to
# real RTL text. An agent could invent plausible-looking module/port/
# interface/register-block facts with no RTL backing and pass identically to
# one that had actually read the source, because "architecture evidence
# database generated" was itself just another self-reported boolean
# (architecture_evidence_db_generated).
#
# `architectural_claims` (new, REQUIRED, non-empty list) closes the cheapest
# fabrication case, matching the existing `*_evidence_refs` pattern already
# used by manual_lookup_before_edit_gate.py: every concrete architecture fact
# the agent asserts (a module, port, interface, or register-block name) must
# carry an `rtl_citation` of the form "path/to/file:start[-end]" naming a
# real file under the project root (cwd, per run_gate()'s subprocess
# convention -- see dv_harness/gates.py) whose content, within a small
# tolerance window around the cited line range, actually contains the
# claimed name. This is a lightweight grep/text spot-check, not a real RTL
# parse -- it cannot prove the agent understood what it read, but it closes
# the "cited a file/line range that has nothing to do with the claim, or
# doesn't exist at all" fabrication case, the same bar
# manual_lookup_before_edit_gate.py already holds VIP/DUT reference lookups
# to.
#
# RULING: `architectural_claims` is made unconditionally mandatory (a
# missing/empty list is a hard FAIL), not an optional/additive field that
# defaults to a no-op when absent. An optional citation requirement an agent
# can simply omit would not close the fabrication gap this check exists for
# -- the whole point is that *some* concrete, citable claim must exist for
# this gate to pass. No existing test or STAGE_GATES caller supplies a full
# evidence payload for this gate (confirmed by repo-wide search), so this is
# not a breaking change to any currently-exercised path -- only to the
# prompt contract in dv_harness/prompts.py's ARCH_DISCOVERY template, which
# is updated alongside this change to show agents the new required shape.
#
# Building a real RTL-parsing chain to verify claims (rather than this
# spot-check) is explicitly OUT OF SCOPE here: tools/dut_architecture/
# build_architecture_model.py and tools/real_env/dut_interface_extractor.py
# already exist as a real regex-based RTL-parsing pipeline, but produce an
# output schema (flat ports/modules/parameters lists, "UNKNOWN"-heavy
# heuristic interface/clock/reset grouping) that does not line up with this
# gate's per-claim citation shape without real design work -- deferred as a
# follow-up, per the earlier audit's finding that they are "too crude/
# schema-mismatched to wire in as-is".
import argparse, json, pathlib, re, sys

ALLOWED_CLAIM_KINDS = {"MODULE", "PORT", "INTERFACE", "REGISTER_BLOCK"}

# citation shape: "path/to/file.v:123" or "path/to/file.v:123-145". The path
# itself is whatever text precedes the LAST ":<digits>[-<digits>]" -- greedy
# ".+" lets a path containing no other trailing digit-run resolve correctly.
_CITATION_RE = re.compile(r'^(?P<path>.+):(?P<start>\d+)(?:-(?P<end>\d+))?$')

# Lines of slack on either side of the cited range a name is allowed to
# appear in -- a lightweight spot-check, not an exact-line requirement (an
# agent citing "the module declaration around line 40" when the identifier
# sits on line 42 is still a real, honest citation).
_LINE_TOLERANCE = 5


def _verify_architectural_claim(claim):
    """Returns None on a claim that checks out, or a FAIL detail dict for
    the first thing wrong with it. Never trusts the claim's own text --
    every fact checked here is re-derived from the real filesystem."""
    if not isinstance(claim, dict):
        return {"reason": "ARCHITECTURAL_CLAIM_MALFORMED", "detail": "claim is not an object"}
    kind = claim.get("kind")
    name = claim.get("name")
    citation = claim.get("rtl_citation")
    if kind not in ALLOWED_CLAIM_KINDS:
        return {"reason": "ARCHITECTURAL_CLAIM_MALFORMED", "claim": claim,
                "detail": f"kind must be one of {sorted(ALLOWED_CLAIM_KINDS)}"}
    if not name or not isinstance(name, str):
        return {"reason": "ARCHITECTURAL_CLAIM_MALFORMED", "claim": claim,
                "detail": "missing non-empty 'name'"}
    if not citation or not isinstance(citation, str):
        return {"reason": "ARCHITECTURAL_CLAIM_MALFORMED", "claim": claim,
                "detail": "missing non-empty 'rtl_citation'"}

    m = _CITATION_RE.match(citation)
    if not m:
        return {"reason": "UNVERIFIABLE_RTL_CITATION", "claim": claim,
                "detail": "rtl_citation is not 'path:line' or 'path:start-end'"}
    path_str, start_s, end_s = m.group("path"), m.group("start"), m.group("end")
    start = int(start_s)
    end = int(end_s) if end_s else start
    if start < 1 or end < start:
        return {"reason": "UNVERIFIABLE_RTL_CITATION", "claim": claim,
                "detail": "line range must have start>=1 and end>=start"}

    # Path existence is checked relative to cwd (the project root under
    # run_gate()'s subprocess convention -- see dv_harness/gates.py's
    # run_gate(), which always subprocess.run()s gate scripts with
    # cwd=str(root)), the same convention manual_lookup_before_edit_gate.py
    # already relies on for its *_evidence_refs paths.
    p = pathlib.Path(path_str)
    if not p.is_file():
        return {"reason": "UNVERIFIABLE_RTL_CITATION", "claim": claim,
                "detail": f"cited file does not exist: {path_str}"}
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return {"reason": "UNVERIFIABLE_RTL_CITATION", "claim": claim,
                "detail": f"cited file could not be read: {path_str}"}
    if start > len(lines):
        return {"reason": "UNVERIFIABLE_RTL_CITATION", "claim": claim,
                "detail": f"cited line range starts past end of file ({len(lines)} lines)"}

    window_start = max(0, start - 1 - _LINE_TOLERANCE)
    window_end = min(len(lines), end + _LINE_TOLERANCE)
    window_text = "\n".join(lines[window_start:window_end])
    if not re.search(r'\b' + re.escape(name) + r'\b', window_text):
        return {"reason": "UNVERIFIABLE_RTL_CITATION", "claim": claim,
                "detail": f"'{name}' not found near {path_str}:{start_s}"
                          + (f"-{end_s}" if end_s else "")}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.state).read_text())
    if not d.get("rtl_source_available"):
        print(json.dumps({"status": "FAIL", "reason": "RTL_SOURCE_REQUIRED_FOR_STEP5"})); return 2
    if d.get("architecture_document_required"):
        print(json.dumps({"status": "FAIL", "reason": "ARCHITECTURE_DOCUMENT_MUST_BE_OPTIONAL"})); return 3
    auto = set(d.get("auto_discovered_fields", []))
    minimum = {"TOP", "HIERARCHY", "INTERFACE", "CLOCK_RESET", "PARAM_DEFINE", "PORT_CHANNEL"}
    if not minimum.issubset(auto):
        print(json.dumps({"status": "FAIL", "reason": "RTL_DISCOVERY_TOO_SHALLOW",
                           "missing": sorted(minimum - auto)})); return 4
    if d.get("asked_user_before_rtl_analysis"):
        print(json.dumps({"status": "FAIL", "reason": "USER_ASKED_BEFORE_RTL_EVIDENCE_SEARCH"})); return 5
    for item in d.get("unknown_items", []):
        if item.get("confidence") in ("LOW", "UNKNOWN") and not item.get("next_action"):
            print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_ARCHITECTURE_WITHOUT_CALIBRATION_ACTION",
                               "item": item.get("name")})); return 6
    if not d.get("architecture_evidence_db_generated"):
        print(json.dumps({"status": "FAIL", "reason": "NO_ARCHITECTURE_EVIDENCE_DATABASE"})); return 7

    claims = d.get("architectural_claims")
    if not isinstance(claims, list) or not claims:
        print(json.dumps({"status": "FAIL", "reason": "ARCHITECTURAL_CLAIMS_MISSING",
                           "detail": "at least one module/port/interface/register_block claim with an "
                                     "rtl_citation is required -- self-reported category flags alone "
                                     "(auto_discovered_fields) are not RTL provenance"})); return 9
    for claim in claims:
        fail = _verify_architectural_claim(claim)
        if fail:
            print(json.dumps({"status": "FAIL", **fail})); return 10

    if d.get("lock_requested") and not d.get("calibration_complete"):
        print(json.dumps({"status": "FAIL", "reason": "ARCHITECTURE_LOCK_BEFORE_CALIBRATION"})); return 8
    print(json.dumps({"status": "PASS"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
