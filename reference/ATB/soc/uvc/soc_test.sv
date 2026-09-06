
/**
 * Abstract:
 * Class soc_test is the top TEST class, incorporating
 * the base TEST class plus any user extensions.
 */

`ifndef GUARD_SOC_TEST_SV
`define GUARD_SOC_TEST_SV

`ifdef ENABLE_USER_SOC_BASE_TEST
`define SOC_BASE_TEST user_soc_base_test
`include "user_soc_base_test.sv"
`else
`define SOC_BASE_TEST soc_base_test
`include "soc_base_test.sv"
`endif

class soc_test extends `SOC_BASE_TEST;

  /** UVM Component Utility macro */
  `uvm_component_utils (soc_test)

  /** Class Constructor */
  function new(string name="soc_test", uvm_component parent=null);
    super.new(name, parent);
  endfunction : new

endclass: soc_test

`endif // GUARD_SOC_TEST_SV
