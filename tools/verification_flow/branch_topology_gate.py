#!/usr/bin/env python3
# BUG FIX (2026-08-28, audit-impact-arbitration-naming): canonicalized on the
# user (Project Lead)'s stated branch-naming convention -- underscore
# separator, 0-indexed (branch_a0/branch_a1/..., branch_b0/branch_b1/...),
# symmetric with branch_fw's own underscore naming. This gate previously
# used a dash-separated, 1-indexed convention (branch-a1/branch-a2/...)
# that matched neither branch_fw's naming nor
# project_model_topology_completeness_gate.py's uppercase BRANCH_A_DUT/
# BRANCH_B_VIP category tags, nor tb-topology-planner/SKILL.md's own body
# text (which contradicted itself between 0-indexed and 1-indexed in two
# different sections of the same file) -- three-to-four incompatible real
# conventions coexisted with zero reconciliation. This gate is now the
# single source of truth for the canonical form.
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--topology",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.topology).read_text())
    dut_ports=int(d.get("dut_port_count",0))
    vip_ports=int(d.get("vip_port_count",0))
    branches=set(d.get("branches",[]))
    required={"block","branch_fw"}
    required |= {f"branch_a{i}" for i in range(0,dut_ports)}
    required |= {f"branch_b{i}" for i in range(0,vip_ports)}
    missing=sorted(required-branches)
    if missing:
        print(json.dumps({"status":"FAIL","reason":"MISSING_REQUIRED_BRANCHES","missing":missing})); return 2
    extras=[b for b in branches if b.startswith("branch_a") and b not in required]
    extras += [b for b in branches if b.startswith("branch_b") and b not in required]
    if extras:
        print(json.dumps({"status":"FAIL","reason":"PORT_COUNT_BRANCH_MISMATCH","extra":sorted(set(extras))})); return 3
    if not d.get("branch_fw_interrupt_driven"):
        print(json.dumps({"status":"FAIL","reason":"BRANCH_FW_NOT_INTERRUPT_DRIVEN"})); return 4

    # BUG FIX (2026-08-28, audit-impact-arbitration-naming): when more than
    # one DUT-side branch (block + branch_a0 + branch_a1 + ...) can run
    # concurrently on a shared AMBA bus (APB/AXI/AHB), the topology must
    # actually declare a cross-branch bus contention/arbitration model --
    # otherwise nothing stops an agent from generating branch_a0/branch_a1
    # as if each had silent, uncontended, exclusive bus access.
    protocol=str(d.get("protocol") or "").lower()
    if dut_ports>1 and "amba" in protocol:
        model=d.get("cross_branch_bus_model")
        if not isinstance(model,dict) or not model.get("shared_resources") or not model.get("arbitration_policy"):
            print(json.dumps({"status":"FAIL","reason":"MULTI_BRANCH_BUS_ARBITRATION_UNMODELED",
                              "dut_ports":dut_ports,"protocol":d.get("protocol")})); return 5

    print(json.dumps({"status":"PASS","dut_ports":dut_ports,"vip_ports":vip_ports})); return 0
if __name__=="__main__": sys.exit(main())
