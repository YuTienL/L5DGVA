`include "coretop_test.sv"
`include "coretop_virtual_sequence.sv"

/**
 * Abstract:
 * This file test runs the default base test without modification.  This
 * test validates that the environment can be compiled and that the VIP
 * components can be started.
 */
class coretop_sanity_test extends coretop_test;

  /** UVM Component Utility macro */
  `uvm_component_utils(coretop_sanity_test)

  /** Class Constructor */
  function new(string name = "coretop_sanity_test", uvm_component parent=null);
    super.new(name,parent);
  endfunction: new

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
  endfunction

  task run_phase(uvm_phase phase);
     coretop_virtual_sequence  coretop_vseq = coretop_virtual_sequence::type_id::create("coretop_vseq");
     phase.raise_objection(this);
  	 coretop_vseq.start(env.vsqr);	
	 phase.drop_objection(this);
  endtask

endclass
