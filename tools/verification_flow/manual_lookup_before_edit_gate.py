#!/usr/bin/env python3
# BUG FIX (2026-08-29, 9-policy audit, policies 2/3): two real gaps closed
# together, both found while auditing this exact gate against the user's
# 9-policy list --
#
# (a) branch naming used the pre-canonicalization convention
#     (BRANCH_B_VIP/BRANCH_A_DUT/BRANCH_FW) this session already replaced
#     everywhere else with branch_a{i}/branch_b{i}/branch_fw (see
#     branch_topology_gate.py's own BUG FIX note) -- this script alone was
#     missed, so it silently matched NOTHING against a real evidence block
#     carrying the canonical branch name.
# (b) the user's policy 2/3 each name several DISTINCT reference sources
#     ("VIP examples 和 VIP 使用手冊和 VIP source code 和 class reference" --
#     4 items; "DUT RTL source code, PHY documents 和任何 programming guide
#     或相關資料" -- RTL plus PHY-or-programming-guide-or-related-material),
#     but the old schema only tracked ONE merged boolean per side
#     (vip_examples_checked + vip_manual_or_source_checked;
#     dut_rtl_or_design_material_checked) -- an agent could satisfy the gate
#     having genuinely checked only one of several required sources. Each
#     named source is now its own required field.
import argparse, json, pathlib, sys

# BUG FIX (2026-08-31, final whole-branch review, Critical finding): B1's
# reference-tree barrier used to live ONLY in protocol_isolation_gate.py,
# which reads its OWN separate `protocol_isolation_gate` evidence block --
# not this gate's `vip_evidence_refs`/`dut_rtl_evidence_refs`, which is the
# block an agent is actually FORCED to supply for a VIP/DUT edit (that other
# gate's own block is agent-optional and PASSes empty by design). An agent
# could therefore cite USB_UVM_Handoff content right here, in the evidence
# this gate itself verifies, and still pass IMPLEMENT as long as it left the
# separate isolation-gate block empty. Importing the same forbidden-tree
# check protocol_isolation_gate.py already defines and applying it inside
# _verify_evidence_refs() below closes that: it now runs on the real refs,
# not a parallel block nothing forces an agent to fill in. This gate script
# and protocol_isolation_gate.py live in the same directory
# (tools/verification_flow/), and Python auto-adds a directly-run script's
# own directory to sys.path[0], so this plain import resolves without any
# path manipulation.
from protocol_isolation_gate import FORBIDDEN_REFERENCE_TREES, _cites_forbidden_tree  # noqa: E402

# BUG FIX (2026-08-29, poster-compliance-audit "gate 只驗證格式，不反查 RTL"
# finding): every boolean flag below (vip_examples_checked, dut_rtl_checked,
# ...) was previously a bare, self-reported claim -- an agent that fabricated
# a well-formed evidence block with no real lookup would pass identically to
# one that actually did the work. This does not (and cannot, from a static
# gate alone) prove an agent genuinely UNDERSTOOD what it read -- but it does
# close the cheapest, most common fabrication case: a claim that names no
# real file at all, or a file that does not exist, or a quote that never
# appears in the file it claims to be from. Any `*_evidence_refs` list
# supplied is independently, deterministically verified against the real
# filesystem (cwd == project root, matching STAGE_GATES' subprocess
# convention) -- never trusted as agent-attested text.


def _verify_evidence_refs(refs, field_name):
    """Deterministically verifies each {"path": ..., "quote": ...} ref
    against the real filesystem: the path must exist as a real file, and
    (when `quote` is supplied) that exact string must appear in the file's
    real content. Returns None on success, or a FAIL detail dict citing the
    first ref that doesn't check out -- never silently skips a bad ref."""
    if not isinstance(refs, list) or not refs:
        return {"reason": "EVIDENCE_REFS_MISSING_OR_EMPTY", "field": field_name}
    for i, ref in enumerate(refs):
        if not isinstance(ref, dict) or not ref.get("path"):
            return {"reason": "EVIDENCE_REF_MISSING_PATH", "field": field_name, "index": i}
        # Checked BEFORE file-existence: a confident citation into a
        # forbidden reference-environment tree (e.g. USB_UVM_Handoff) is
        # worse than an honest missing/nonexistent file, and must FAIL even
        # if the cited path happens not to exist on disk -- matching
        # protocol_isolation_gate.py's own no-existence-check design.
        forbidden = _cites_forbidden_tree(ref["path"])
        if forbidden:
            return {"reason": "REFERENCE_TREE_CITATION_FORBIDDEN", "field": field_name,
                     "path": ref["path"], "forbidden_tree": forbidden}
        p = pathlib.Path(ref["path"])
        if not p.is_file():
            return {"reason": "EVIDENCE_FILE_NOT_FOUND", "field": field_name, "path": ref["path"]}
        quote = ref.get("quote")
        if quote:
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return {"reason": "EVIDENCE_FILE_UNREADABLE", "field": field_name, "path": ref["path"]}
            if quote not in content:
                return {"reason": "EVIDENCE_QUOTE_NOT_FOUND_IN_FILE", "field": field_name,
                         "path": ref["path"], "quote": quote}
    return None


def _classify(branch):
    if branch is None:
        return None
    if branch.startswith("branch_b"):
        return "VIP"
    if branch == "branch_fw" or branch.startswith("branch_a"):
        return "DUT"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edit", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.edit).read_text())
    branch = d.get("branch")
    kind = _classify(branch)

    if kind == "VIP":
        required = ["vip_examples_checked", "vip_manual_checked",
                    "vip_source_checked", "vip_class_reference_checked"]
        missing = [f for f in required if not d.get(f)]
        if missing:
            print(json.dumps({"status": "FAIL", "reason": "VIP_EDIT_WITHOUT_REFERENCE_LOOKUP",
                               "missing": missing})); return 2
        fail = _verify_evidence_refs(d.get("vip_evidence_refs"), "vip_evidence_refs")
        if fail:
            print(json.dumps({"status": "FAIL", **fail})); return 5

    elif kind == "DUT":
        if not d.get("dut_rtl_checked"):
            print(json.dumps({"status": "FAIL", "reason": "DUT_SIDE_EDIT_WITHOUT_DUT_REFERENCE_LOOKUP",
                               "missing": ["dut_rtl_checked"]})); return 3
        fail = _verify_evidence_refs(d.get("dut_rtl_evidence_refs"), "dut_rtl_evidence_refs")
        if fail:
            print(json.dumps({"status": "FAIL", **fail})); return 6
        phy_or_pg = (d.get("phy_documents_checked") or d.get("programming_guide_checked")
                     or d.get("related_material_checked"))
        if not phy_or_pg and not d.get("phy_programming_guide_not_applicable_reason"):
            print(json.dumps({
                "status": "FAIL", "reason": "DUT_SIDE_EDIT_WITHOUT_PHY_OR_PROGRAMMING_GUIDE_LOOKUP",
                "detail": "supply phy_documents_checked, programming_guide_checked, or "
                          "related_material_checked -- or, if genuinely none apply, an explicit "
                          "phy_programming_guide_not_applicable_reason",
            })); return 4

    print(json.dumps({"status": "PASS", "branch": branch}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
