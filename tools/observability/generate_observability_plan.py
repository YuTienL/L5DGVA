#!/usr/bin/env python3
import argparse,json,pathlib
ap=argparse.ArgumentParser()
ap.add_argument('--plan',required=True)
ap.add_argument('--out-dir',required=True)
a=ap.parse_args()
plan=json.loads(pathlib.Path(a.plan).read_text())
out=pathlib.Path(a.out_dir); out.mkdir(parents=True,exist_ok=True)

scoreboards=[]; checkers=[]; assertions=[]
for t in plan.get("targets",[]):
    tid=t["target_id"].lower().replace("-","_")
    for m in t.get("recommended_mechanisms",[]):
        typ=m["type"]
        purpose=m.get("purpose","")
        placement=m.get("placement","")
        if typ=="SCOREBOARD":
            scoreboards.append(
f"""class {tid}_scoreboard extends uvm_scoreboard;
  `uvm_component_utils({tid}_scoreboard)
  // Purpose: {purpose}
  // Placement: {placement}
  // TODO: connect analysis ports, reference model, queues and compare policy.
  function new(string name="{tid}_scoreboard", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
""")
        elif typ=="CHECKER":
            checkers.append(
f"""class {tid}_checker extends uvm_subscriber #(uvm_sequence_item);
  `uvm_component_utils({tid}_checker)
  // Purpose: {purpose}
  // Placement: {placement}
  function new(string name="{tid}_checker", uvm_component parent=null);
    super.new(name,parent);
  endfunction
  function void write(uvm_sequence_item t);
    // TODO: implement evidence-backed semantic checks.
  endfunction
endclass
""")
        elif typ=="ASSERTION":
            assertions.append(
f"""// {tid}: {purpose}
// Placement: {placement}
property {tid}_property;
  @(posedge clk) disable iff (!rst_n)
    1'b1; // TODO: replace with evidence-backed temporal property
endproperty
{tid}_assert: assert property ({tid}_property);
""")

(out/"generated_scoreboards.sv").write_text("\n".join(scoreboards))
(out/"generated_checkers.sv").write_text("\n".join(checkers))
(out/"generated_assertions.sv").write_text("\n".join(assertions))
(out/"implementation_manifest.json").write_text(json.dumps({
  "scoreboards":len(scoreboards),"checkers":len(checkers),"assertions":len(assertions),
  "source_plan":a.plan
},indent=2))
