#!/usr/bin/env python3
# STATE_MACHINE_CHECKS DSL WIRING (checker-sva-generator task, see
# .work/checker-sva-generator-design-report.md): the ASSERTION branch below
# used to emit a literal, unconditional `1'b1; // TODO: replace with
# evidence-backed temporal property` for EVERY target -- zero generation
# mechanics. A `recommended_mechanisms[]` entry of type "ASSERTION" that
# additionally carries an opt-in "state_machine_check" key (a full
# dv_harness/uvm_generator/state_machine_checks.py entry -- see that
# module's own docstring for the 3-idiom schema and the 3-question decision
# procedure in the OBSERVABILITY/semantic-checker-planner,
# assertion-placement-planner, scoreboard-checker-assertion-analyzer
# SKILL.md files that decides when a requirement qualifies) now compiles
# to a REAL property/assert instead. An entry with no "state_machine_check"
# key is completely unaffected -- byte-identical TODO placeholder output,
# same as before this change -- so this is purely additive.
#
# RULING: each `recommended_mechanisms[]` entry may also carry an optional
# "classification" field -- the planner skill's OWN 3-question-decision-
# procedure verdict (one of "PROTOCOL_STATE_MACHINE_LEGALITY" /
# "INTERRUPT_RESPONSE_SEMANTIC" / "CROSS_CYCLE_TEMPORAL_INVARIANT" /
# "OTHER_HAND_AUTHORED", see the SKILL.md files above) -- propagated
# verbatim into each implementation_manifest.json "assertion_entries[]"
# row alongside "generation_method". This is not itself spelled out by the
# design report's field list (only "generation_method" is named there) but
# is required for assertion_placeholder_closure_gate.py
# (STAGE_GATES["VERIFICATION_ARCHITECTURE"]) to do the one check the design
# report assigns it -- "FAILs if any assertion entry classified as
# 'protocol-state-machine legality' still shows
# 'generation_method':'placeholder'" -- without inventing a second,
# undocumented data source. A mechanism entry that omits "classification"
# records `null` here (never guessed), and the gate never flags a `null`
# classification (only an explicit PROTOCOL_STATE_MACHINE_LEGALITY one).
#
# `sys.path` is extended so this script (a standalone tools/ CLI, not part
# of the dv_harness package) can import the dv_harness package's real
# state_machine_checks module -- the same sys.path.insert shape already
# used by other tools/ scripts that reach into dv_harness (e.g.
# tools/vplan/vplan_writer_validation_gate.py).
import argparse,json,pathlib,sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from dv_harness.uvm_generator import state_machine_checks

ap=argparse.ArgumentParser()
ap.add_argument('--plan',required=True)
ap.add_argument('--out-dir',required=True)
a=ap.parse_args()
plan=json.loads(pathlib.Path(a.plan).read_text())
out=pathlib.Path(a.out_dir); out.mkdir(parents=True,exist_ok=True)

# Same "clocks"/"resets" manifest-field convention generator.py's tb_top()
# already uses -- reused here rather than inventing a new plan-level field.
# A plan with neither key defaults to the exact "clk"/"rst_n" names the old
# unconditional TODO placeholder text already hardcoded, so this default is
# itself byte-identical-in-spirit with pre-existing behavior.
_clk=(plan.get('clocks') or [{'name':'clk'}])[0].get('name','clk')
_rst=(plan.get('resets') or [{'name':'rst_n'}])[0].get('name','rst_n')

scoreboards=[]; checkers=[]; assertions=[]; assertion_entries=[]
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
            smc=m.get("state_machine_check")
            if smc:
                # additive opt-in: "state_machine_check" is a full
                # state_machine_checks.py entry (see that module's schema).
                # "assertion_name" defaults to this target's tid when the
                # entry itself omits it, so a plan author does not have to
                # redundantly repeat the target_id-derived name.
                smc=dict(smc)
                smc.setdefault("assertion_name", tid)
                sv_text=state_machine_checks.emit_check(smc, _clk, _rst)
                assertions.append(f"// {tid}: {purpose}\n// Placement: {placement}\n{sv_text}")
                assertion_entries.append({
                    "target_id": tid, "generation_method": "state_machine_checks_dsl:"+smc["kind"],
                    "classification": m.get("classification"),
                })
            else:
                assertions.append(
f"""// {tid}: {purpose}
// Placement: {placement}
property {tid}_property;
  @(posedge clk) disable iff (!rst_n)
    1'b1; // TODO: replace with evidence-backed temporal property
endproperty
{tid}_assert: assert property ({tid}_property);
""")
                assertion_entries.append({
                    "target_id": tid, "generation_method": "placeholder",
                    "classification": m.get("classification"),
                })

(out/"generated_scoreboards.sv").write_text("\n".join(scoreboards))
(out/"generated_checkers.sv").write_text("\n".join(checkers))
(out/"generated_assertions.sv").write_text("\n".join(assertions))
(out/"implementation_manifest.json").write_text(json.dumps({
  "scoreboards":len(scoreboards),"checkers":len(checkers),"assertions":len(assertions),
  "assertion_entries":assertion_entries,
  "source_plan":a.plan
},indent=2))
