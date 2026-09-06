/**
 * Abstract:
 * Class coretop_base_configuration is used to encapsulate the configuration
 * information for the environment.  It extends uvm_object and contains
 * sub-configuration instances for each component of the environment.
 * The set_initial_values() method sets default values for the VIP
 * configuration to match the DUT configuration.
 */

`define CORETOP_AXI_SYSTEM_ENV_CFG_0_PATH  `DV_ROOT/L3/coretop/uvc/cfg/axi_system_env_cfg_0.cfg
`define CORETOP_AHB_SYSTEM_ENV_CFG_0_PATH  `DV_ROOT/L3/coretop/uvc/cfg/ahb_system_env_cfg_0.cfg
`define CORETOP_APB_SYSTEM_ENV_CFG_0_PATH  `DV_ROOT/L3/coretop/uvc/cfg/apb_system_env_cfg_0.cfg
`define CORETOP_APB_SYSTEM_ENV_CFG_1_PATH  `DV_ROOT/L3/coretop/uvc/cfg/apb_system_env_cfg_1.cfg
`define CORETOP_APB_SYSTEM_ENV_CFG_2_PATH  `DV_ROOT/L3/coretop/uvc/cfg/apb_system_env_cfg_2.cfg
`define CORETOP_APB_SYSTEM_ENV_CFG_3_PATH  `DV_ROOT/L3/coretop/uvc/cfg/apb_system_env_cfg_3.cfg
`define CORETOP_APB_SYSTEM_ENV_CFG_4_PATH  `DV_ROOT/L3/coretop/uvc/cfg/apb_system_env_cfg_4.cfg

`include "dv_util.svi"

`ifndef GUARD_CORETOP_BASE_CONFIGURATION_SV
`define GUARD_CORETOP_BASE_CONFIGURATION_SV

class coretop_base_configuration extends uvm_object;

  // Number of clock cycles to hold in the reset phase after reset is deasserted
  int unsigned num_clock_cycles_after_reset = 10;

  // Configuration for svt_axi_system_env
  svt_axi_system_configuration axi_system_env_cfg_0;

  // Configuration for svt_apb_system_env
  svt_apb_system_configuration apb_system_env_cfg_0;

  // Configuration for svt_ahb_system_env
  svt_ahb_system_configuration ahb_system_env_cfg_0;

  // Configuration for svt_apb_system_env
  svt_apb_system_configuration apb_system_env_cfg_1;

  // Configuration for svt_apb_system_env
  svt_apb_system_configuration apb_system_env_cfg_2;

  // Configuration for svt_apb_system_env
  svt_apb_system_configuration apb_system_env_cfg_3;

  // Configuration for svt_apb_system_env
  svt_apb_system_configuration apb_system_env_cfg_4;

  `uvm_object_utils_begin (coretop_base_configuration)
    `uvm_field_int(num_clock_cycles_after_reset, UVM_ALL_ON)
    `uvm_field_object(axi_system_env_cfg_0, UVM_ALL_ON)
    `uvm_field_object(apb_system_env_cfg_0, UVM_ALL_ON)
    `uvm_field_object(ahb_system_env_cfg_0, UVM_ALL_ON)
    `uvm_field_object(apb_system_env_cfg_1, UVM_ALL_ON)
    `uvm_field_object(apb_system_env_cfg_2, UVM_ALL_ON)
    `uvm_field_object(apb_system_env_cfg_3, UVM_ALL_ON)
    `uvm_field_object(apb_system_env_cfg_4, UVM_ALL_ON)    
  `uvm_object_utils_end

  /** Constructor */
  function new(string name = "coretop_base_configuration");
    super.new(name);
    set_initial_values();
  endfunction : new

  /** Method to set the default values for the configuration */
  extern virtual function void set_initial_values();

endclass: coretop_base_configuration

// -----------------------------------------------------------------------------
function void coretop_base_configuration::set_initial_values();

  string filename;

  // Load the axi_system_env_cfg_0.cfg file  
  if (axi_system_env_cfg_0 == null)
    axi_system_env_cfg_0 = svt_axi_system_configuration::type_id::create("axi_system_env_cfg_0");
  
  filename = `DV_STRINGIFY(`CORETOP_AXI_SYSTEM_ENV_CFG_0_PATH);
  if (axi_system_env_cfg_0.load_prop_vals(filename)) begin
    `uvm_info("set_initial_values", $sformatf("Successfully loaded axi_system_env_cfg_0 using '%0s'.", filename), UVM_HIGH);
    if (axi_system_env_cfg_0.is_valid(1)) begin
      `uvm_info("set_initial_values", $sformatf("axi_system_env_cfg_0 loaded using '%0s' is valid.", filename), UVM_HIGH);
    end else begin
      `uvm_error("set_initial_values", $sformatf("axi_system_env_cfg_0 loaded using '%0s' is NOT valid.", filename));
    end
  end else begin
    `uvm_error("set_initial_values", $sformatf("Failed attempting to load axi_system_env_cfg_0 using '%0s'.", filename));
  end

  // Load the apb_system_env_cfg_0.cfg file
  if (apb_system_env_cfg_0 == null)
    apb_system_env_cfg_0 = svt_apb_system_configuration::type_id::create("apb_system_env_cfg_0");

  filename = `DV_STRINGIFY(`CORETOP_APB_SYSTEM_ENV_CFG_0_PATH);
  if (apb_system_env_cfg_0.load_prop_vals(filename)) begin
    `uvm_info("set_initial_values", $sformatf("Successfully loaded apb_system_env_cfg_0 using '%0s'.", filename), UVM_HIGH);
    if (apb_system_env_cfg_0.is_valid(0)) begin
      `uvm_info("set_initial_values", $sformatf("apb_system_env_cfg_0 loaded using '%0s' is valid.", filename), UVM_HIGH);
    end else begin
      `uvm_error("set_initial_values", $sformatf("apb_system_env_cfg_0 loaded using '%0s' is NOT valid.", filename));
    end
  end else begin
    `uvm_error("set_initial_values", $sformatf("Failed attempting to load apb_system_env_cfg_0 using '%0s'.", filename));
  end

  // Load the ahb_system_env_cfg_0.cfg file
  if (ahb_system_env_cfg_0 == null)
    ahb_system_env_cfg_0 = svt_ahb_system_configuration::type_id::create("ahb_system_env_cfg_0");

  filename = `DV_STRINGIFY(`CORETOP_AHB_SYSTEM_ENV_CFG_0_PATH);
  if (ahb_system_env_cfg_0.load_prop_vals(filename)) begin
    `uvm_info("set_initial_values", $sformatf("Successfully loaded ahb_system_env_cfg_0 using '%0s'.", filename), UVM_HIGH);
    if (ahb_system_env_cfg_0.is_valid(0)) begin
      `uvm_info("set_initial_values", $sformatf("ahb_system_env_cfg_0 loaded using '%0s' is valid.", filename), UVM_HIGH);
    end else begin
      `uvm_error("set_initial_values", $sformatf("ahb_system_env_cfg_0 loaded using '%0s' is NOT valid.", filename));
    end
  end else begin
    `uvm_error("set_initial_values", $sformatf("Failed attempting to load ahb_system_env_cfg_0 using '%0s'.", filename));
  end

  // Load the apb_system_env_cfg_1.cfg file
  if (apb_system_env_cfg_1 == null)
    apb_system_env_cfg_1 = svt_apb_system_configuration::type_id::create("apb_system_env_cfg_1");

  filename = `DV_STRINGIFY(`CORETOP_APB_SYSTEM_ENV_CFG_1_PATH);
  if (apb_system_env_cfg_1.load_prop_vals(filename)) begin
    `uvm_info("set_initial_values", $sformatf("Successfully loaded apb_system_env_cfg_1 using '%0s'.", filename), UVM_HIGH);
    if (apb_system_env_cfg_1.is_valid(0)) begin
      `uvm_info("set_initial_values", $sformatf("apb_system_env_cfg_1 loaded using '%0s' is valid.", filename), UVM_HIGH);
    end else begin
      `uvm_error("set_initial_values", $sformatf("apb_system_env_cfg_1 loaded using '%0s' is NOT valid.", filename));
    end
  end else begin
    `uvm_error("set_initial_values", $sformatf("Failed attempting to load apb_system_env_cfg_1 using '%0s'.", filename));
  end

  // Load the apb_system_env_cfg_2.cfg file
  if (apb_system_env_cfg_2 == null)
    apb_system_env_cfg_2 = svt_apb_system_configuration::type_id::create("apb_system_env_cfg_2");

  filename = `DV_STRINGIFY(`CORETOP_APB_SYSTEM_ENV_CFG_2_PATH);
  if (apb_system_env_cfg_2.load_prop_vals(filename)) begin
    `uvm_info("set_initial_values", $sformatf("Successfully loaded apb_system_env_cfg_2 using '%0s'.", filename), UVM_HIGH);
    if (apb_system_env_cfg_2.is_valid(0)) begin
      `uvm_info("set_initial_values", $sformatf("apb_system_env_cfg_2 loaded using '%0s' is valid.", filename), UVM_HIGH);
    end else begin
      `uvm_error("set_initial_values", $sformatf("apb_system_env_cfg_2 loaded using '%0s' is NOT valid.", filename));
    end
  end else begin
    `uvm_error("set_initial_values", $sformatf("Failed attempting to load apb_system_env_cfg_2 using '%0s'.", filename));
  end

  // Load the apb_system_env_cfg_3.cfg file
  if (apb_system_env_cfg_3 == null)
    apb_system_env_cfg_3 = svt_apb_system_configuration::type_id::create("apb_system_env_cfg_3");

  filename = `DV_STRINGIFY(`CORETOP_APB_SYSTEM_ENV_CFG_3_PATH);
  if (apb_system_env_cfg_3.load_prop_vals(filename)) begin
    `uvm_info("set_initial_values", $sformatf("Successfully loaded apb_system_env_cfg_3 using '%0s'.", filename), UVM_HIGH);
    if (apb_system_env_cfg_3.is_valid(0)) begin
      `uvm_info("set_initial_values", $sformatf("apb_system_env_cfg_3 loaded using '%0s' is valid.", filename), UVM_HIGH);
    end else begin
      `uvm_error("set_initial_values", $sformatf("apb_system_env_cfg_3 loaded using '%0s' is NOT valid.", filename));
    end
  end else begin
    `uvm_error("set_initial_values", $sformatf("Failed attempting to load apb_system_env_cfg_3 using '%0s'.", filename));
  end

  // Load the apb_system_env_cfg_4.cfg file
  if (apb_system_env_cfg_4 == null)
    apb_system_env_cfg_4 = svt_apb_system_configuration::type_id::create("apb_system_env_cfg_4");

  filename = `DV_STRINGIFY(`CORETOP_APB_SYSTEM_ENV_CFG_4_PATH);
  if (apb_system_env_cfg_4.load_prop_vals(filename)) begin
    `uvm_info("set_initial_values", $sformatf("Successfully loaded apb_system_env_cfg_4 using '%0s'.", filename), UVM_HIGH);
    if (apb_system_env_cfg_4.is_valid(0)) begin
      `uvm_info("set_initial_values", $sformatf("apb_system_env_cfg_4 loaded using '%0s' is valid.", filename), UVM_HIGH);
    end else begin
      `uvm_error("set_initial_values", $sformatf("apb_system_env_cfg_4 loaded using '%0s' is NOT valid.", filename));
    end
  end else begin
    `uvm_error("set_initial_values", $sformatf("Failed attempting to load apb_system_env_cfg_4 using '%0s'.", filename));
  end

  //TODO
  axi_system_env_cfg_0.system_monitor_enable = 1; 

  foreach(axi_system_env_cfg_0.master_cfg[i]) begin
    axi_system_env_cfg_0.master_cfg[i].enable_xml_gen = 1;
    axi_system_env_cfg_0.master_cfg[i].pa_format_type = svt_xml_writer::FSDB;  
  end
  foreach(axi_system_env_cfg_0.slave_cfg[i]) begin
    axi_system_env_cfg_0.slave_cfg[i].enable_xml_gen = 1;
    axi_system_env_cfg_0.slave_cfg[i].pa_format_type = svt_xml_writer::FSDB;  
  end
   
  foreach(axi_system_env_cfg_0.master_cfg[i]) begin
    axi_system_env_cfg_0.master_cfg[i].transaction_coverage_enable  = 1;
  end
  foreach(axi_system_env_cfg_0.slave_cfg[i]) begin
    axi_system_env_cfg_0.slave_cfg[i].transaction_coverage_enable  = 1;
  end

  foreach(axi_system_env_cfg_0.master_cfg[i]) begin
    axi_system_env_cfg_0.master_cfg[i].reordering_algorithm = svt_axi_port_configuration::RANDOM;
    axi_system_env_cfg_0.master_cfg[i].write_resp_reordering_depth = `SVT_AXI_MAX_WRITE_RESP_REORDERING_DEPTH;
  end
  foreach(axi_system_env_cfg_0.slave_cfg[i]) begin
    axi_system_env_cfg_0.slave_cfg[i].reordering_algorithm = svt_axi_port_configuration::RANDOM;
    axi_system_env_cfg_0.slave_cfg[i].write_resp_reordering_depth = `SVT_AXI_MAX_WRITE_RESP_REORDERING_DEPTH;
  end
 
  //

  //TODO
  foreach(ahb_system_env_cfg_0.master_cfg[i]) begin
    ahb_system_env_cfg_0.master_cfg[i].enable_xml_gen = 1;
  end
  foreach(ahb_system_env_cfg_0.slave_cfg[i]) begin
    ahb_system_env_cfg_0.slave_cfg[i].enable_xml_gen = 1;
  end

  foreach(ahb_system_env_cfg_0.master_cfg[i]) begin
    ahb_system_env_cfg_0.master_cfg[i].transaction_coverage_enable = 1;
  end
  foreach(ahb_system_env_cfg_0.slave_cfg[i]) begin
    ahb_system_env_cfg_0.slave_cfg[i].transaction_coverage_enable = 1;
  end
  //
  
  //TODO
  apb_system_env_cfg_0.is_active = 0;
  apb_system_env_cfg_0.enable_xml_gen = 1;
  apb_system_env_cfg_0.transaction_coverage_enable = 1;
  apb_system_env_cfg_0.protocol_checks_coverage_enable = 1;
  apb_system_env_cfg_0.trace_enable = 1;
  apb_system_env_cfg_0.disable_x_check_of_pclk    = 1;
  apb_system_env_cfg_0.disable_x_check_of_presetn = 1;
  apb_system_env_cfg_0.slave_cfg[0].enable_xml_gen = 1;
  apb_system_env_cfg_0.slave_cfg[0].is_active = 0;
  apb_system_env_cfg_0.slave_cfg[0].transaction_coverage_enable = 1;
  apb_system_env_cfg_0.slave_cfg[0].protocol_checks_coverage_enable = 1;
  apb_system_env_cfg_0.slave_cfg[0].trace_enable = 1;

  foreach(apb_system_env_cfg_0.slave_cfg[i]) begin
    apb_system_env_cfg_0.slave_cfg[i].protocol_checks_coverage_enable = 1;
  end

  foreach(apb_system_env_cfg_0.slave_cfg[i]) begin
    apb_system_env_cfg_0.slave_cfg[i].trace_enable = 1;
  end

  foreach(apb_system_env_cfg_0.slave_cfg[i]) begin
    apb_system_env_cfg_0.slave_cfg[i].enable_xml_gen = 1;
  end   

  foreach(apb_system_env_cfg_0.slave_cfg[i]) begin
    apb_system_env_cfg_0.slave_cfg[i].transaction_coverage_enable = 1;
  end    
  //

  //TODO
  apb_system_env_cfg_1.is_active = 0;
  apb_system_env_cfg_1.enable_xml_gen = 1;
  apb_system_env_cfg_1.transaction_coverage_enable = 1;
  apb_system_env_cfg_1.protocol_checks_coverage_enable = 1;
  apb_system_env_cfg_1.trace_enable = 1;
  apb_system_env_cfg_1.disable_x_check_of_pclk    = 1;
  apb_system_env_cfg_1.disable_x_check_of_presetn = 1;
  apb_system_env_cfg_1.slave_cfg[0].enable_xml_gen = 1;
  apb_system_env_cfg_1.slave_cfg[0].is_active = 0;
  apb_system_env_cfg_1.slave_cfg[0].transaction_coverage_enable = 1;
  apb_system_env_cfg_1.slave_cfg[0].protocol_checks_coverage_enable = 1;
  apb_system_env_cfg_1.slave_cfg[0].trace_enable = 1;

  foreach(apb_system_env_cfg_1.slave_cfg[i]) begin
    apb_system_env_cfg_1.slave_cfg[i].protocol_checks_coverage_enable = 1;
  end

  foreach(apb_system_env_cfg_1.slave_cfg[i]) begin
    apb_system_env_cfg_1.slave_cfg[i].trace_enable = 1;
  end

  foreach(apb_system_env_cfg_1.slave_cfg[i]) begin
    apb_system_env_cfg_1.slave_cfg[i].enable_xml_gen = 1;
  end   
  
  foreach(apb_system_env_cfg_1.slave_cfg[i]) begin
    apb_system_env_cfg_1.slave_cfg[i].transaction_coverage_enable = 1;
  end    
  //

  //TODO
  apb_system_env_cfg_2.is_active = 0;
  apb_system_env_cfg_2.enable_xml_gen = 1;
  apb_system_env_cfg_2.transaction_coverage_enable = 1;
  apb_system_env_cfg_2.protocol_checks_coverage_enable = 1;
  apb_system_env_cfg_2.trace_enable = 1;
  apb_system_env_cfg_2.disable_x_check_of_pclk    = 1;
  apb_system_env_cfg_2.disable_x_check_of_presetn = 1;
  apb_system_env_cfg_2.slave_cfg[0].enable_xml_gen = 1;
  apb_system_env_cfg_2.slave_cfg[0].is_active = 0;
  apb_system_env_cfg_2.slave_cfg[0].transaction_coverage_enable = 1;
  apb_system_env_cfg_2.slave_cfg[0].protocol_checks_coverage_enable = 1;
  apb_system_env_cfg_2.slave_cfg[0].trace_enable = 1;

  foreach(apb_system_env_cfg_2.slave_cfg[i]) begin
    apb_system_env_cfg_2.slave_cfg[i].protocol_checks_coverage_enable = 1;
  end

  foreach(apb_system_env_cfg_2.slave_cfg[i]) begin
    apb_system_env_cfg_2.slave_cfg[i].trace_enable = 1;
  end

  foreach(apb_system_env_cfg_2.slave_cfg[i]) begin
    apb_system_env_cfg_2.slave_cfg[i].enable_xml_gen = 1;
  end   
  
  foreach(apb_system_env_cfg_2.slave_cfg[i]) begin
    apb_system_env_cfg_2.slave_cfg[i].transaction_coverage_enable = 1;
  end    
  //
  
  //TODO
  apb_system_env_cfg_3.is_active = 0;
  apb_system_env_cfg_3.enable_xml_gen = 1;
  apb_system_env_cfg_3.transaction_coverage_enable = 1;
  apb_system_env_cfg_3.protocol_checks_coverage_enable = 1;
  apb_system_env_cfg_3.trace_enable = 1;
  apb_system_env_cfg_3.disable_x_check_of_pclk    = 1;
  apb_system_env_cfg_3.disable_x_check_of_presetn = 1;
  apb_system_env_cfg_3.slave_cfg[0].enable_xml_gen = 1;
  apb_system_env_cfg_3.slave_cfg[0].is_active = 0;
  apb_system_env_cfg_3.slave_cfg[0].transaction_coverage_enable = 1;
  apb_system_env_cfg_3.slave_cfg[0].protocol_checks_coverage_enable = 1;
  apb_system_env_cfg_3.slave_cfg[0].trace_enable = 1;

  foreach(apb_system_env_cfg_3.slave_cfg[i]) begin
    apb_system_env_cfg_3.slave_cfg[i].protocol_checks_coverage_enable = 1;
  end

  foreach(apb_system_env_cfg_3.slave_cfg[i]) begin
    apb_system_env_cfg_3.slave_cfg[i].trace_enable = 1;
  end

  foreach(apb_system_env_cfg_3.slave_cfg[i]) begin
    apb_system_env_cfg_3.slave_cfg[i].enable_xml_gen = 1;
  end   
  
  foreach(apb_system_env_cfg_3.slave_cfg[i]) begin
    apb_system_env_cfg_3.slave_cfg[i].transaction_coverage_enable = 1;
  end    
  //

  //TODO
  apb_system_env_cfg_4.is_active = 0;
  apb_system_env_cfg_4.enable_xml_gen = 1;
  apb_system_env_cfg_4.transaction_coverage_enable = 1;
  apb_system_env_cfg_4.protocol_checks_coverage_enable = 1;
  apb_system_env_cfg_4.trace_enable = 1;
  apb_system_env_cfg_4.disable_x_check_of_pclk    = 1;
  apb_system_env_cfg_4.disable_x_check_of_presetn = 1;
  apb_system_env_cfg_4.slave_cfg[0].enable_xml_gen = 1;
  apb_system_env_cfg_4.slave_cfg[0].is_active = 0;
  apb_system_env_cfg_4.slave_cfg[0].transaction_coverage_enable = 1;
  apb_system_env_cfg_4.slave_cfg[0].protocol_checks_coverage_enable = 1;
  apb_system_env_cfg_4.slave_cfg[0].trace_enable = 1;

  foreach(apb_system_env_cfg_4.slave_cfg[i]) begin
    apb_system_env_cfg_4.slave_cfg[i].protocol_checks_coverage_enable = 1;
  end

  foreach(apb_system_env_cfg_4.slave_cfg[i]) begin
    apb_system_env_cfg_4.slave_cfg[i].trace_enable = 1;
  end

  foreach(apb_system_env_cfg_4.slave_cfg[i]) begin
    apb_system_env_cfg_4.slave_cfg[i].enable_xml_gen = 1;
  end   
  
  foreach(apb_system_env_cfg_4.slave_cfg[i]) begin
    apb_system_env_cfg_4.slave_cfg[i].transaction_coverage_enable = 1;
  end    
  //
  
  // Insure that the 'is_active' settings are consistent with all active_replace and passive_connect situations.
`ifdef REPLACE_BD_AXI_M_AUDTOP 
  axi_system_env_cfg_0.master_cfg[0].is_active = 1;
`elsif CONNECT_BD_AXI_M_AUDTOP 
  axi_system_env_cfg_0.master_cfg[0].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_AUDTOP 
  apb_system_env_cfg_0.slave_cfg[0].is_active = 1;
`elsif CONNECT_BD_APB_S_AUDTOP 
  apb_system_env_cfg_0.slave_cfg[0].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M_CQTOP 
  axi_system_env_cfg_0.master_cfg[1].is_active = 1;
`elsif CONNECT_BD_AXI_M_CQTOP 
  axi_system_env_cfg_0.master_cfg[1].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M_DMATOP 
  axi_system_env_cfg_0.master_cfg[2].is_active = 1;
`elsif CONNECT_BD_AXI_M_DMATOP 
  axi_system_env_cfg_0.master_cfg[2].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_DMATOP 
  apb_system_env_cfg_0.slave_cfg[1].is_active = 1;
`elsif CONNECT_BD_APB_S_DMATOP 
  apb_system_env_cfg_0.slave_cfg[1].is_active = 0;
`endif
`ifdef REPLACE_BD_AHB_S_FMTOP 
  ahb_system_env_cfg_0.slave_cfg[0].is_active = 1;
`elsif CONNECT_BD_AHB_S_FMTOP 
  ahb_system_env_cfg_0.slave_cfg[0].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M_FMTOP 
  axi_system_env_cfg_0.master_cfg[3].is_active = 1;
`elsif CONNECT_BD_AXI_M_FMTOP 
  axi_system_env_cfg_0.master_cfg[3].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_FMTOP 
  apb_system_env_cfg_0.slave_cfg[2].is_active = 1;
`elsif CONNECT_BD_APB_S_FMTOP 
  apb_system_env_cfg_0.slave_cfg[2].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_GTOP 
  apb_system_env_cfg_0.slave_cfg[3].is_active = 1;
`elsif CONNECT_BD_APB_S_GTOP 
  apb_system_env_cfg_0.slave_cfg[3].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M_PERITOP 
  axi_system_env_cfg_0.master_cfg[4].is_active = 1;
`elsif CONNECT_BD_AXI_M_PERITOP 
  axi_system_env_cfg_0.master_cfg[4].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_M_PERITOP 
  apb_system_env_cfg_1.master_cfg.is_active = 1;
`elsif CONNECT_BD_APB_M_PERITOP 
  apb_system_env_cfg_1.master_cfg.is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S0_PERITOP 
  apb_system_env_cfg_0.slave_cfg[4].is_active = 1;
`elsif CONNECT_BD_APB_S0_PERITOP 
  apb_system_env_cfg_0.slave_cfg[4].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S1_PERITOP 
  apb_system_env_cfg_0.slave_cfg[5].is_active = 1;
`elsif CONNECT_BD_APB_S1_PERITOP 
  apb_system_env_cfg_0.slave_cfg[5].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M_HSMTOP 
  axi_system_env_cfg_0.master_cfg[5].is_active = 1;
`elsif CONNECT_BD_AXI_M_HSMTOP 
  axi_system_env_cfg_0.master_cfg[5].is_active = 0;
`endif
`ifdef REPLACE_BD_AHB_M_HSMTOP 
  ahb_system_env_cfg_0.master_cfg[0].is_active = 1;
`elsif CONNECT_BD_AHB_M_HSMTOP 
  ahb_system_env_cfg_0.master_cfg[0].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_M_HSMTOP 
  apb_system_env_cfg_2.master_cfg.is_active = 1;
`elsif CONNECT_BD_APB_M_HSMTOP 
  apb_system_env_cfg_2.master_cfg.is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_HSMTOP 
  apb_system_env_cfg_0.slave_cfg[6].is_active = 1;
`elsif CONNECT_BD_APB_S_HSMTOP 
  apb_system_env_cfg_0.slave_cfg[6].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_S_UCIE 
  axi_system_env_cfg_0.slave_cfg[0].is_active = 1;
`elsif CONNECT_BD_AXI_S_UCIE 
  axi_system_env_cfg_0.slave_cfg[0].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M_UCIE 
  axi_system_env_cfg_0.master_cfg[6].is_active = 1;
`elsif CONNECT_BD_AXI_M_UCIE 
  axi_system_env_cfg_0.master_cfg[6].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_UCIE 
  apb_system_env_cfg_0.slave_cfg[7].is_active = 1;
`elsif CONNECT_BD_APB_S_UCIE 
  apb_system_env_cfg_0.slave_cfg[7].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M_SS_CDEC 
  axi_system_env_cfg_0.master_cfg[7].is_active = 1;
`elsif CONNECT_D_AXI_M_SS_CDEC 
  axi_system_env_cfg_0.master_cfg[7].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_CDEC 
  apb_system_env_cfg_0.slave_cfg[8].is_active = 1;
`elsif CONNECT_D_APB_S_SS_CDEC 
  apb_system_env_cfg_0.slave_cfg[8].is_active = 0;
`endif
`ifdef REPLACE_BD_ACE_M0_SS_CMP 
  axi_system_env_cfg_0.master_cfg[8].is_active = 1;
`elsif CONNECT_BD_ACE_M0_SS_CMP 
  axi_system_env_cfg_0.master_cfg[8].is_active = 0;
`endif
`ifdef REPLACE_BD_ACE_M1_SS_CMP 
  axi_system_env_cfg_0.master_cfg[9].is_active = 1;
`elsif CONNECT_BD_ACE_M1_SS_CMP 
  axi_system_env_cfg_0.master_cfg[9].is_active = 0;
`endif
`ifdef REPLACE_BD_ACE_M2_SS_CMP 
  axi_system_env_cfg_0.master_cfg[10].is_active = 1;
`elsif CONNECT_BD_ACE_M2_SS_CMP 
  axi_system_env_cfg_0.master_cfg[10].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_CMP 
  apb_system_env_cfg_0.slave_cfg[9].is_active = 1;
`elsif CONNECT_BD_APB_S_SS_CMP 
  apb_system_env_cfg_0.slave_cfg[9].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M_SS_CON 
  axi_system_env_cfg_0.master_cfg[11].is_active = 1;
`elsif CONNECT_BD_AXI_M_SS_CON 
  axi_system_env_cfg_0.master_cfg[11].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_S_SS_CON 
  axi_system_env_cfg_0.slave_cfg[1].is_active = 1;
`elsif CONNECT_BD_AXI_S_SS_CON 
  axi_system_env_cfg_0.slave_cfg[1].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_CON 
  apb_system_env_cfg_0.slave_cfg[10].is_active = 1;
`elsif CONNECT_BD_APB_S_SS_CON 
  apb_system_env_cfg_0.slave_cfg[10].is_active = 0;
`endif
`ifdef REPLACE_BD_ACE_M_SS_CPU 
  axi_system_env_cfg_0.master_cfg[12].is_active = 1;
`elsif CONNECT_BD_ACE_M_SS_CPU 
  axi_system_env_cfg_0.master_cfg[12].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_S_SS_CPU 
  axi_system_env_cfg_0.slave_cfg[2].is_active = 1;
`elsif CONNECT_BD_AXI_S_SS_CPU 
  axi_system_env_cfg_0.slave_cfg[2].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_M_SS_CPU 
  apb_system_env_cfg_3.master_cfg.is_active = 1;
`elsif CONNECT_BD_APB_M_SS_CPU 
  apb_system_env_cfg_3.master_cfg.is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_CPU 
  apb_system_env_cfg_0.slave_cfg[11].is_active = 1;
`elsif CONNECT_BD_APB_S_SS_CPU 
  apb_system_env_cfg_0.slave_cfg[11].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M0_SS_VIS 
  axi_system_env_cfg_0.master_cfg[13].is_active = 1;
`elsif CONNECT_BD_AXI_M0_SS_VIS 
  axi_system_env_cfg_0.master_cfg[13].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M1_SS_VIS 
  axi_system_env_cfg_0.master_cfg[14].is_active = 1;
`elsif CONNECT_BD_AXI_M1_SS_VIS 
  axi_system_env_cfg_0.master_cfg[14].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_VIS 
  apb_system_env_cfg_0.slave_cfg[12].is_active = 1;
`elsif CONNECT_BD_APB_S_SS_VIS 
  apb_system_env_cfg_0.slave_cfg[12].is_active = 0;
`endif
`ifdef REPLACE_AXI_S0_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[3].is_active = 1;
`elsif CONNECT_AXI_S0_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[3].is_active = 0;
`endif
`ifdef REPLACE_AXI_S1_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[4].is_active = 1;
`elsif CONNECT_AXI_S1_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[4].is_active = 0;
`endif
`ifdef REPLACE_AXI_S2_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[5].is_active = 1;
`elsif CONNECT_AXI_S2_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[5].is_active = 0;
`endif
`ifdef REPLACE_AXI_S3_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[6].is_active = 1;
`elsif CONNECT_AXI_S3_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[6].is_active = 0;
`endif
`ifdef REPLACE_AXI_S4_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[7].is_active = 1;
`elsif CONNECT_AXI_S4_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[7].is_active = 0;
`endif
`ifdef REPLACE_AXI_S5_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[8].is_active = 1;
`elsif CONNECT_AXI_S5_DDR_CHIP 
  axi_system_env_cfg_0.slave_cfg[8].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S0_DDR_CHIP 
  apb_system_env_cfg_0.slave_cfg[13].is_active = 1;
`elsif CONNECT_BD_APB_S0_DDR_CHIP 
  apb_system_env_cfg_0.slave_cfg[13].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S1_DDR_CHIP 
  apb_system_env_cfg_0.slave_cfg[14].is_active = 1;
`elsif CONNECT_BD_APB_S1_DDR_CHIP 
  apb_system_env_cfg_0.slave_cfg[14].is_active = 0;
`endif
`ifdef REPLACE_AXI_S_SRAM_SLAVE_GROUP 
  axi_system_env_cfg_0.slave_cfg[9].is_active = 1;
`elsif CONNECT_AXI_S_SRAM_SLAVE_GROUP 
  axi_system_env_cfg_0.slave_cfg[9].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M_SS_SF 
  axi_system_env_cfg_0.master_cfg[15].is_active = 1;
`elsif CONNECT_BD_AXI_M_SS_SF 
  axi_system_env_cfg_0.master_cfg[15].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_S_SS_SF 
  axi_system_env_cfg_0.slave_cfg[10].is_active = 1;
`elsif CONNECT_BD_AXI_S_SS_SF 
  axi_system_env_cfg_0.slave_cfg[10].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_M_SS_SF 
  apb_system_env_cfg_4.master_cfg.is_active = 1;
`elsif CONNECT_BD_APB_M_SS_SF 
  apb_system_env_cfg_4.master_cfg.is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_SF 
  apb_system_env_cfg_0.slave_cfg[15].is_active = 1;
`elsif CONNECT_BD_APB_S_SS_SF 
  apb_system_env_cfg_0.slave_cfg[15].is_active = 0;
`endif
`ifdef REPLACE_BD_AXI_M_SS_VOUT 
  axi_system_env_cfg_0.master_cfg[16].is_active = 1;
`elsif CONNECT_BD_AXI_M_SS_VOUT 
  axi_system_env_cfg_0.master_cfg[16].is_active = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_VOUT 
  apb_system_env_cfg_0.slave_cfg[16].is_active = 1;
`elsif CONNECT_BD_APB_S_SS_VOUT 
  apb_system_env_cfg_0.slave_cfg[16].is_active = 0;
`endif

endfunction


`endif // GUARD_CORETOP_BASE_CONFIGURATION_SV
