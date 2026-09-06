/**
 * Abstract:
 * Class coretop_test is the top TEST class, incorporating
 * the base TEST class plus any user extensions.
 */

`ifndef GUARD_CORETOP_TEST_SV
`define GUARD_CORETOP_TEST_SV

`ifdef ENABLE_USER_CORETOP_BASE_TEST
`define CORETOP_BASE_TEST user_coretop_base_test
`include "user_coretop_base_test.sv"
`else
`define CORETOP_BASE_TEST coretop_base_test
`include "coretop_base_test.sv"
`endif

class coretop_test extends `CORETOP_BASE_TEST;

  /** UVM Component Utility macro */
  `uvm_component_utils (coretop_test)

  /** Class Constructor */
  function new(string name="coretop_test", uvm_component parent=null);
    super.new(name, parent);
  endfunction : new

endclass: coretop_test

`endif // GUARD_CORETOP_TEST_SV
