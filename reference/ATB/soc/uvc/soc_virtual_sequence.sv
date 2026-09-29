
/**
 * Abstract:
*/

`ifndef GUARD_SOC_VIRTUAL_SEQUENCE_SV
`define GUARD_SOC_VIRTUAL_SEQUENCE_SV

`include "soc_seq_libs.sv"

class soc_virtual_sequence extends soc_seq_libs;

  /** UVM Object Utility macro */
  `uvm_object_utils(soc_virtual_sequence)
  
  //--------------------------
  // Variable definition here
  //-------------------------

  /** Class Constructor */
  function new (string name = "soc_virtual_sequence");
    super.new(name);
  endfunction : new

  virtual task body();

    //----------------------
    // VIP_INIT
    //----------------------
	soc_slave_init_seq();

	//----------------------
    //MAC_INIT
    //----------------------
	`include "commands/command.txt"

    //----------------------
    //MAC_TEST
	//----------------------
	//soc_init_seq();
    //

  endtask: body

endclass: soc_virtual_sequence 

`endif // GUARD_SOC_VIRTUAL_SEQUENCE_SV

