/**
 * Abstract:
 * This file creates a base test, which serves as the base class for the rest
 * of the tests in this environment.  This test creates a default configuration
 * and builds the ENV component.
 */

`ifndef GUARD_CORETOP_BASE_TEST_SV
`define GUARD_CORETOP_BASE_TEST_SV

`include "coretop_env.sv"

class coretop_base_test extends uvm_test;

  /** UVM Component Utility macro */
  `uvm_component_utils (coretop_base_test)

  /** VC SOC Environment */
  coretop_env uvm_coretop_env;
  
  /** VC SOC System Configuration */
  coretop_configuration uvm_coretop_cfg;

  /** Class Constructor */
  function new(string name="coretop_base_test", uvm_component parent=null);
    super.new(name, parent);
  endfunction : new

  /**
   * Build Phase
   * - Construct the VC SOC Configuration and pass to the VC SOC ENV
   * - Construct the VC SOC ENV
   */
  extern virtual function void build_phase(uvm_phase phase);

  /**
   * Display the component hiearchy
   */
  extern virtual function void end_of_elaboration_phase(uvm_phase phase);

  /**
   * Calculate the pass or fail status for the test in the final phase method of the
   * test. If a UVM_FATAL, UVM_ERROR, or a UVM_WARNING message has been generated the
   * test will fail.
   */
  extern virtual function void final_phase(uvm_phase phase);
  
endclass: coretop_base_test


// -----------------------------------------------------------------------------
function void coretop_base_test::build_phase(uvm_phase phase);
  super.build_phase(phase);

  /**
   * Create the environment class
   */
  uvm_coretop_env = coretop_env::type_id::create ("uvm_coretop_env", this);
    
  /**
   * Create the environment configuration
   */
  uvm_coretop_cfg = coretop_configuration::type_id::create("uvm_coretop_cfg");

  /** Apply the configuration to the environment */
  uvm_config_db#(coretop_configuration)::set(this, "uvm_coretop_env", "cfg", uvm_coretop_cfg);
 
endfunction: build_phase
  
// -----------------------------------------------------------------------------
function void coretop_base_test::end_of_elaboration_phase(uvm_phase phase);
  super.end_of_elaboration_phase(phase);
  uvm_top.print_topology();
endfunction: end_of_elaboration_phase

// -----------------------------------------------------------------------------
function void coretop_base_test::final_phase(uvm_phase phase);
  uvm_report_server svr;
  super.final_phase(phase);
  svr = uvm_report_server::get_server();
  if ((svr.get_severity_count(UVM_FATAL) +
       svr.get_severity_count(UVM_WARNING)+
       svr.get_severity_count(UVM_ERROR)>0))
    $display("\nSvtTestEpilog: Failed\n");
  else
    $display("\nSvtTestEpilog: Passed\n");
endfunction
 
`endif // GUARD_CORETOP_BASE_TEST_SV
