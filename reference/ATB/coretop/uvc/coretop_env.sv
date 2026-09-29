/**
 * Abstract: 
 * Class coretop_env is the top ENV class, incorporating
 * the base ENV class plus any user extensions.
 */

`ifndef GUARD_CORETOP_ENV_SV
`define GUARD_CORETOP_ENV_SV

`ifdef ENABLE_USER_CORETOP_BASE_ENV
`define CORETOP_BASE_ENV user_coretop_base_env
`include "user_coretop_base_env.sv"
`else
`define CORETOP_BASE_ENV coretop_base_env
`include "coretop_base_env.sv"
`endif

class coretop_env extends `CORETOP_BASE_ENV;

  /** UVM Component Utility macro */
  `uvm_component_utils(coretop_env)

  /** Class Constructor */
  function new(string name="coretop_env", uvm_component parent=null);
    super.new(name, parent);
  endfunction : new

endclass: coretop_env

`endif // GUARD_CORETOP_ENV_SV
