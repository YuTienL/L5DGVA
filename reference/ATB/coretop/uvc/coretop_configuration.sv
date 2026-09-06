/**
 * Abstract:
 * Class coretop_configuration is the top CFG class, incorporating
 * the base CFG class plus any user extensions.
 */

`ifndef GUARD_CORETOP_CONFIGURATION_SV
`define GUARD_CORETOP_CONFIGURATION_SV

`ifdef ENABLE_USER_CORETOP_BASE_CONFIGURATION
`define CORETOP_BASE_CONFIGURATION user_coretop_base_configuration
`include "user_coretop_base_configuration.sv"
`else
`define CORETOP_BASE_CONFIGURATION coretop_base_configuration
`include "coretop_base_configuration.sv"
`endif

class coretop_configuration extends `CORETOP_BASE_CONFIGURATION;

  /** UVM Object Utility macro */
  `uvm_object_utils(coretop_configuration)

  /** Constructor */
  function new(string name = "coretop_configuration");
    super.new(name);
  endfunction : new

endclass: coretop_configuration

`endif // GUARD_CORETOP_CONFIGURATION_SV
