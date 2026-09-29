`include "soc_test.sv"
`include "soc_virtual_sequence.sv"


/**
 * Abstract:
 * This file test runs the default base test without modification.  This
 * test validates that the environment can be compiled and that the VIP
 * components can be started.
 */
class soc_sanity_test extends soc_test;

  /** UVM Component Utility macro */
  `uvm_component_utils(soc_sanity_test)

  /** Class Constructor */
  function new(string name = "soc_sanity_test", uvm_component parent=null);
    super.new(name,parent);
  endfunction: new

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
  endfunction

  task run_phase(uvm_phase phase);
     soc_virtual_sequence  soc_vseq = soc_virtual_sequence::type_id::create("soc_vseq");
     phase.raise_objection(this);
  	 soc_vseq.start(vsqr);	
     phase.phase_done.set_drain_time(this, 1us); //!!! because of timescale 1ps/1fs
	 phase.drop_objection(this);
  endtask

endclass
