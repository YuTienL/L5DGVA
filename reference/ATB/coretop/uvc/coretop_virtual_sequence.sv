
/**
 * Abstract:
*/

`ifndef GUARD_CORETOP_VIRTUAL_SEQUENCE_SV
`define GUARD_CORETOP_VIRTUAL_SEQUENCE_SV

`include "coretop_seq_libs.sv"

class coretop_virtual_sequence extends coretop_seq_libs;

  /** UVM Object Utility macro */
  `uvm_object_utils(coretop_virtual_sequence)
  
  //--------------------------
  // Variable definition here
  //-------------------------

  /** Class Constructor */
  function new (string name = "coretop_virtual_sequence");
    super.new(name);
  endfunction : new

  virtual task body();

    //TODO
	coretop_slave_init_seq();
	//
	global_init_seq();
	//
	coretop_init_seq();
    //

  endtask: body

endclass: coretop_virtual_sequence 

`endif // GUARD_CORETOP_VIRTUAL_SEQUENCE_SV

