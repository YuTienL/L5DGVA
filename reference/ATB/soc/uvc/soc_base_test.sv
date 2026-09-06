/**
 * Abstract:
 * This file creates a base test, which serves as the base class for the rest
 * of the tests in this environment.  This test creates a default configuration
 * and builds the ENV component.
 */

`ifndef GUARD_SOC_BASE_TEST_SV
`define GUARD_SOC_BASE_TEST_SV

`include "soc_virtual_sequencer.sv"

`include "soc_base_env.sv"

//-------------------------
// Sub based test
//-------------------------
`ifdef BD_USED
  `include "coretop_base_test.sv"
`endif  
`ifdef AUDTOP_USED
  `include "audtop_base_test.sv"
`endif  
`ifdef FMTOP_USED
  `include "fmtop_base_test.sv"
`endif 
`ifdef PERITOP_USED
  `include "peritop_base_test.sv"
`endif 
`ifdef HSMTOP_USED
  `include "hsmtop_base_test.sv"
`endif
`ifdef SS_CDEC_USED
  `include "ss_cdec_base_test.sv"
`endif
`ifdef SS_CMP_USED
  `include "ss_cmp_base_test.sv"
`endif
`ifdef SS_CON_USED
  `include "ss_con_base_test.sv"
`endif
`ifdef SS_CPU_USED
  `include "ss_cpu_base_test.sv"
`endif
`ifdef SS_VIS_USED
  `include "ss_vis_base_test.sv"
`endif
`ifdef SS_SF_USED
  `include "ss_sf_base_test.sv"
`endif
`ifdef SS_VOUT_USED
  `include "ss_vout_base_test.sv"
`endif

class soc_base_test extends uvm_test;

  /** UVM Component Utility macro */
  `uvm_component_utils (soc_base_test)

  /** VC SOC Virtual Sequencer */
  soc_virtual_sequencer vsqr;

  /** VC SOC Environment & Configuration*/
  soc_base_env  uvm_soc_base_env;

`ifdef BD_USED 
  coretop_env uvm_coretop_env;
  coretop_configuration  uvm_coretop_cfg;
`endif
`ifdef AUDTOP_USED  
  audtop_env uvm_audtop_env;
  audtop_configuration  uvm_audtop_cfg;
`endif
`ifdef FMTOP_USED  
  fmtop_env uvm_fmtop_env;
  fmtop_configuration  uvm_fmtop_cfg;
`endif
`ifdef PERITOP_USED  
  peritop_env uvm_peritop_env;
  peritop_configuration  uvm_peritop_cfg;
`endif
`ifdef HSMTOP_USED  
  hsmtop_env uvm_hsmtop_env;
  hsmtop_configuration  uvm_hsmtop_cfg;
`endif
`ifdef SS_CDEC_USED  
  ss_cdec_env uvm_ss_cdec_env;
  ss_cdec_configuration  uvm_ss_cdec_cfg;
`endif
`ifdef SS_CMP_USED  
  ss_cmp_env uvm_ss_cmp_env;
  ss_cmp_configuration  uvm_ss_cmp_cfg;
`endif
`ifdef SS_CON_USED  
  ss_con_env uvm_ss_con_env;
  ss_con_configuration  uvm_ss_con_cfg;
`endif
`ifdef SS_CPU_USED  
  ss_cpu_env uvm_ss_cpu_env;
  ss_cpu_configuration  uvm_ss_cpu_cfg;
`endif
`ifdef SS_VIS_USED  
  ss_vis_env uvm_ss_vis_env;
  ss_vis_configuration  uvm_ss_vis_cfg;
`endif
`ifdef SS_SF_USED  
  ss_sf_env uvm_ss_sf_env;
  ss_sf_configuration  uvm_ss_sf_cfg;
`endif
`ifdef SS_VOUT_USED  
  ss_vout_env uvm_ss_vout_env;
  ss_vout_configuration  uvm_ss_vout_cfg;
`endif

  /** Class Constructor */
  function new(string name="soc_base_test", uvm_component parent=null);
    super.new(name, parent);
  endfunction : new

  /**
   * Build Phase
   * - Construct the VC SOC Configuration and pass to the VC SOC ENV
   * - Construct the VC SOC ENV
   */
  extern virtual function void build_phase(uvm_phase phase);

  /** Connect the VC SOC Virtual Sequencer to the VIP components */
  extern virtual function void connect_phase(uvm_phase phase);
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
  
endclass: soc_base_test


// -----------------------------------------------------------------------------
function void soc_base_test::build_phase(uvm_phase phase);
  super.build_phase(phase);

  /**
   * Create the environment class & configuration
   * Apply the configuration to the environment
   *
   */
  uvm_soc_base_env = soc_base_env::type_id::create ("uvm_soc_base_env", this);
  uvm_config_db#(soc_base_env)::set(null, "env_access", "env_handle", uvm_soc_base_env);

 
`ifdef BD_USED 
  uvm_coretop_cfg = coretop_configuration::type_id::create ("uvm_coretop_cfg");
  uvm_config_db#(coretop_configuration)::set(this, "uvm_coretop_env", "cfg", uvm_coretop_cfg);
  uvm_coretop_env = coretop_env::type_id::create ("uvm_coretop_env", this);
  //uvm_coretop_cfg = coretop_configuration::type_id::create ("uvm_coretop_cfg");
  //uvm_config_db#(coretop_configuration)::set(this, "uvm_coretop_env", "cfg", uvm_coretop_cfg);
`endif
`ifdef AUDTOP_USED 
  uvm_audtop_env = audtop_env::type_id::create ("uvm_audtop_env", this);
  uvm_audtop_cfg = audtop_configuration::type_id::create ("uvm_audtop_cfg");
  uvm_config_db#(audtop_configuration)::set(this, "uvm_audtop_env", "cfg", uvm_audtop_cfg);
`endif  
`ifdef FMTOP_USED
  uvm_fmtop_env = fmtop_env::type_id::create ("uvm_fmtop_env", this);
  uvm_fmtop_cfg = fmtop_configuration::type_id::create ("uvm_fmtop_cfg");
  uvm_config_db#(fmtop_configuration)::set(this, "uvm_fmtop_env", "cfg", uvm_fmtop_cfg);
`endif 
`ifdef PERITOP_USED 
  uvm_peritop_env = peritop_env::type_id::create ("uvm_peritop_env", this);
  uvm_peritop_cfg = peritop_configuration::type_id::create ("uvm_peritop_cfg");
  uvm_config_db#(peritop_configuration)::set(this, "uvm_peritop_env", "cfg", uvm_peritop_cfg);
`endif 
`ifdef HSMTOP_USED
  uvm_hsmtop_env = hsmtop_env::type_id::create ("uvm_hsmtop_env", this);
  uvm_hsmtop_cfg = hsmtop_configuration::type_id::create ("uvm_hsmtop_cfg");
  uvm_config_db#(hsmtop_configuration)::set(this, "uvm_hsmtop_env", "cfg", uvm_hsmtop_cfg);
`endif 
`ifdef SS_CDEC_USED 
  uvm_ss_cdec_env = ss_cdec_env::type_id::create ("uvm_ss_cdec_env", this);
  uvm_ss_cdec_cfg = ss_cdec_configuration::type_id::create ("uvm_ss_cdec_cfg");
  uvm_config_db#(ss_cdec_configuration)::set(this, "uvm_ss_cdec_env", "cfg", uvm_ss_cdec_cfg);
`endif 
`ifdef SS_CMP_USED
  uvm_ss_cmp_env = ss_cmp_env::type_id::create ("uvm_ss_cmp_env", this);
  uvm_ss_cmp_cfg = ss_cmp_configuration::type_id::create ("uvm_ss_cmp_cfg");
  uvm_config_db#(ss_cmp_configuration)::set(this, "uvm_ss_cmp_env", "cfg", uvm_ss_cmp_cfg);
`endif 
`ifdef SS_CON_USED 
  uvm_ss_con_env = ss_con_env::type_id::create ("uvm_ss_con_env", this);
  uvm_ss_con_cfg = ss_con_configuration::type_id::create ("uvm_ss_con_cfg");
  uvm_config_db#(ss_con_configuration)::set(this, "uvm_ss_con_env", "cfg", uvm_ss_con_cfg);
`endif 
`ifdef SS_CPU_USED
  uvm_ss_cpu_env = ss_cpu_env::type_id::create ("uvm_ss_cpu_env", this);
  uvm_ss_cpu_cfg = ss_cpu_configuration::type_id::create ("uvm_ss_cpu_cfg");
  uvm_config_db#(ss_cpu_configuration)::set(this, "uvm_ss_cpu_env", "cfg", uvm_ss_cpu_cfg)
`endif 
`ifdef SS_VIS_USED
  uvm_ss_vis_env = ss_vis_env::type_id::create ("uvm_ss_vis_env", this);
  uvm_ss_vis_cfg = ss_vis_configuration::type_id::create ("uvm_ss_vis_cfg");
  uvm_config_db#(ss_vis_configuration)::set(this, "uvm_ss_vis_env", "cfg", uvm_ss_vis_cfg);
`endif 
`ifdef SS_SF_USED 
  uvm_ss_sf_env = ss_sf_env::type_id::create ("uvm_ss_sf_env", this);
  uvm_ss_sf_cfg = ss_sf_configuration::type_id::create ("uvm_ss_sf_cfg");
  uvm_config_db#(ss_sf_configuration)::set(this, "uvm_ss_sf_env", "cfg", uvm_ss_sf_cfg);
`endif 
`ifdef SS_VOUT_USED 
  uvm_ss_vout_env = ss_vout_env::type_id::create ("uvm_ss_vout_env", this);
  uvm_ss_vout_cfg = ss_vout_configuration::type_id::create ("uvm_ss_vout_cfg");
  uvm_config_db#(ss_vout_configuration)::set(this, "uvm_ss_vout_env", "cfg", uvm_ss_vout_cfg);
`endif 

  /** Construct the VC SOC Virtual Sequencer */
  vsqr = soc_virtual_sequencer::type_id::create("vsqr", this);

endfunction: build_phase

// -----------------------------------------------------------------------------
function void soc_base_test::connect_phase(uvm_phase phase);
   super.connect_phase(phase);
  
   uvm_soc_base_env.vsqr = this.vsqr;

  //--------------------------
  // CORETOP Agent Collection 
  //-------------------------
`ifdef BD_USED  
  foreach (uvm_coretop_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_coretop_env.axi_sys_env[i]);
  end  
  foreach (uvm_coretop_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_coretop_env.ahb_sys_env[i]);
  end  
  foreach (uvm_coretop_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_coretop_env.apb_sys_env[i]);
  end  

  foreach (uvm_coretop_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_coretop_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_coretop_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_coretop_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_coretop_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_coretop_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_coretop_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_coretop_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_coretop_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_coretop_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_coretop_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_coretop_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_coretop_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_coretop_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_coretop_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_coretop_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_coretop_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_coretop_env.vsqr.apb_s_mon_cb[i];
  end
  foreach (uvm_coretop_env.vsqr.apb_m_sqr[i])
	`uvm_info("CORETOP Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_coretop_env.vsqr.ahb_m_sqr[i])
	`uvm_info("CORETOP Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_coretop_env.vsqr.axi_m_sqr[i])
	`uvm_info("CORETOP Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_coretop_env.vsqr.apb_s_sqr[i])
	`uvm_info("CORETOP Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_coretop_env.vsqr.ahb_s_sqr[i])
	`uvm_info("CORETOP Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_coretop_env.vsqr.axi_s_sqr[i])
	`uvm_info("CORETOP Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)  
`endif

  //--------------------------
  // AUDTOP Agent Collection 
  //-------------------------
`ifdef AUDTOP_USED 
  foreach (uvm_audtop_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_audtop_env.axi_sys_env[i]);
  end  
  foreach (uvm_audtop_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_audtop_env.ahb_sys_env[i]);
  end  
  foreach (uvm_audtop_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_audtop_env.apb_sys_env[i]);
  end  

  foreach (uvm_audtop_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_audtop_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_audtop_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_audtop_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_audtop_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_audtop_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_audtop_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_audtop_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_audtop_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_audtop_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_audtop_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_adutop_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_audtop_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_audtop_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_audtop_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_audtop_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_audtop_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_audtop_env.vsqr.apb_s_mon_cb[i];
  end 
  foreach (uvm_audtop_env.vsqr.apb_m_sqr[i])
	`uvm_info("AUDTOP Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_audtop_env.vsqr.ahb_m_sqr[i])
	`uvm_info("AUDTOP Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_audtop_env.vsqr.axi_m_sqr[i])
	`uvm_info("AUDTOP Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_audtop_env.vsqr.apb_s_sqr[i])
	`uvm_info("AUDTOP Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_audtop_env.vsqr.ahb_s_sqr[i])
	`uvm_info("AUDTOP Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_audtop_env.vsqr.axi_s_sqr[i])
	`uvm_info("AUDTOP Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)  
`endif

  //--------------------------
  // FMTOP Agent Collection 
  //-------------------------
`ifdef FMTOP_USED  
  foreach (uvm_fmtop_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_fmtop_env.axi_sys_env[i]);
  end  
  foreach (uvm_fmtop_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_fmtop_env.ahb_sys_env[i]);
  end 
  foreach (uvm_fmtop_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_fmtop_env.apb_sys_env[i]);
  end 

  foreach (uvm_fmtop_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_fmtop_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_fmtop_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_fmtop_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_fmtop_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_fmtop_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_fmtop_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_fmtop_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_fmtop_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_fmtop_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_fmtop_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_fmtop_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_fmtop_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_fmtop_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_fmtop_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_fmtop_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_fmtop_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_fmtop_env.vsqr.apb_s_mon_cb[i];
  end 
  foreach (uvm_fmtop_env.vsqr.apb_m_sqr[i])
	`uvm_info("FMTOP Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_fmtop_env.vsqr.ahb_m_sqr[i])
	`uvm_info("FMTOP Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_fmtop_env.vsqr.axi_m_sqr[i])
	`uvm_info("FMTOP Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_fmtop_env.vsqr.apb_s_sqr[i])
	`uvm_info("FMTOP Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_fmtop_env.vsqr.ahb_s_sqr[i])
	`uvm_info("FMTOP Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_fmtop_env.vsqr.axi_s_sqr[i])
	`uvm_info("FMTOP Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)    
`endif

  //--------------------------
  // PERITOP Agent Collection 
  //-------------------------
`ifdef PERITOP_USED  
  foreach (uvm_peritop_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_peritop_env.axi_sys_env[i]);
  end  
  foreach (uvm_peritop_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_peritop_env.ahb_sys_env[i]);
  end 
  foreach (uvm_peritop_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_peritop_env.apb_sys_env[i]);
  end 

  foreach (uvm_peritop_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_peritop_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_peritop_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_peritop_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_peritop_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_peritop_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_peritop_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_peritop_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_peritop_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_peritop_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_peritop_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_peritop_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_peritop_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_peritop_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_peritop_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_peritop_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_peritop_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_peritop_env.vsqr.apb_s_mon_cb[i];
  end 
  foreach (uvm_peritop_env.vsqr.apb_m_sqr[i])
	`uvm_info("PERITOP Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_peritop_env.vsqr.ahb_m_sqr[i])
	`uvm_info("PERITOP Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_peritop_env.vsqr.axi_m_sqr[i])
	`uvm_info("PERITOP Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_peritop_env.vsqr.apb_s_sqr[i])
	`uvm_info("PERITOP Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_peritop_env.vsqr.ahb_s_sqr[i])
	`uvm_info("PERITOP Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_peritop_env.vsqr.axi_s_sqr[i])
	`uvm_info("PERITOP Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)    
`endif

  //--------------------------
  // HSMTOP Agent Collection 
  //-------------------------
`ifdef HSMTOP_USED  
  foreach (uvm_hsmtop_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_hsmtop_env.axi_sys_env[i]);
  end  
  foreach (uvm_hsmtop_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_hsmtop_env.ahb_sys_env[i]);
  end  
  foreach (uvm_hsmtop_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_hsmtop_env.apb_sys_env[i]);
  end  

  foreach (uvm_hsmtop_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_hsmtop_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_hsmtop_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_hsmtop_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_hsmtop_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_hsmtop_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_hsmtop_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_hsmtop_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_hsmtop_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_hsmtop_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_hsmtop_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_hsmtop_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_hsmtop_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_hsmtop_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_hsmtop_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_hsmtop_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_hsmtop_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_hsmtop_env.vsqr.apb_s_mon_cb[i];
  end   
  foreach (uvm_hsmtop_env.vsqr.apb_m_sqr[i])
	`uvm_info("HSMTOP Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_hsmtop_env.vsqr.ahb_m_sqr[i])
	`uvm_info("HSMTOP Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_hsmtop_env.vsqr.axi_m_sqr[i])
	`uvm_info("HSMTOP Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_hsmtop_env.vsqr.apb_s_sqr[i])
	`uvm_info("HSMTOP Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_hsmtop_env.vsqr.ahb_s_sqr[i])
	`uvm_info("HSMTOP Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_hsmtop_env.vsqr.axi_s_sqr[i])
	`uvm_info("HSMTOP Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)    
`endif

  //--------------------------
  // SS_CDEC Agent Collection 
  //-------------------------
`ifdef SS_CDEC_USED  
  foreach (uvm_ss_cdec_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_ss_cdec_env.axi_sys_env[i]);
  end  
  foreach (uvm_ss_cdec_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_ss_cdec_env.ahb_sys_env[i]);
  end 
  foreach (uvm_ss_cdec_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_ss_cdec_env.apb_sys_env[i]);
  end 

  foreach (uvm_ss_cdec_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_ss_cdec_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_ss_cdec_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_cdec_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_ss_cdec_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_ss_cdec_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_ss_cdec_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_ss_cdec_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_ss_cdec_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_cdec_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_ss_cdec_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_ss_cdec_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_ss_cdec_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_ss_cdec_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_ss_cdec_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_cdec_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_ss_cdec_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_ss_cdec_env.vsqr.apb_s_mon_cb[i];
  end 
  foreach (uvm_ss_cdec_env.vsqr.apb_m_sqr[i])
	`uvm_info("SS_CDEC Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cdec_env.vsqr.ahb_m_sqr[i])
	`uvm_info("SS_CDEC Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cdec_env.vsqr.axi_m_sqr[i])
	`uvm_info("SS_CDEC Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cdec_env.vsqr.apb_s_sqr[i])
	`uvm_info("SS_CDEC Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach uvm_ss_cdec_env.(vsqr.ahb_s_sqr[i])
	`uvm_info("SS_CDEC Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cdec_env.vsqr.axi_s_sqr[i])
	`uvm_info("SS_CDEC Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)  \  
`endif

  //--------------------------
  // SS_CMP Agent Collection 
  //-------------------------
`ifdef SS_CMP_USED 
  foreach (uvm_ss_cmp_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_ss_cmp_env.axi_sys_env[i]);
  end  
  foreach (uvm_ss_cmp_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_ss_cmp_env.ahb_sys_env[i]);
  end 
  foreach (uvm_ss_cmp_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_ss_cmp_env.apb_sys_env[i]);
  end 

  foreach (uvm_ss_cmp_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_ss_cmp_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_ss_cmp_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_cmp_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_ss_cmp_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_ss_cmp_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_ss_cmp_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_ss_cmp_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_ss_cmp_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_cmp_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_ss_cmp_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_ss_cmp_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_ss_cmp_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_ss_cmp_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_ss_cmp_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_cmp_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_ss_cmp_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_ss_cmp_env.vsqr.apb_s_mon_cb[i];
  end
  foreach (uvm_ss_cmp_env.vsqr.apb_m_sqr[i])
	`uvm_info("SS_CMP Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cmp_env.vsqr.ahb_m_sqr[i])
	`uvm_info("SS_CMP Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cmp_env.vsqr.axi_m_sqr[i])
	`uvm_info("SS_CMP Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cmp_env.vsqr.apb_s_sqr[i])
	`uvm_info("SS_CMP Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cmp_env.vsqr.ahb_s_sqr[i])
	`uvm_info("SS_CMP Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cmp_env.vsqr.axi_s_sqr[i])
	`uvm_info("SS_CMP Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)    
`endif

  //--------------------------
  // SS_CON Agent Collection 
  //-------------------------
`ifdef SS_CON_USED 
  foreach (uvm_ss_con_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_ss_con_env.axi_sys_env[i]);
  end  
  foreach (uvm_ss_con_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_ss_con_env.ahb_sys_env[i]);
  end  
  foreach (uvm_ss_con_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_ss_con_env.apb_sys_env[i]);
  end  

  foreach (uvm_ss_con_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_ss_con_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_ss_con_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_con_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_ss_con_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_ss_con_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_ss_con_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_ss_con_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_ss_con_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_con_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_ss_con_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_ss_con_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_ss_con_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_ss_con_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_ss_con_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_con_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_ss_con_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_ss_con_env.vsqr.apb_s_mon_cb[i];
  end 
  foreach (uvm_ss_con_env.vsqr.apb_m_sqr[i])
	`uvm_info("SS_CPN Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_con_env.vsqr.ahb_m_sqr[i])
	`uvm_info("SS_CON Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_con_env.vsqr.axi_m_sqr[i])
	`uvm_info("SS_CON Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_con_env.vsqr.apb_s_sqr[i])
	`uvm_info("SS_CON Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_con_env.vsqr.ahb_s_sqr[i])
	`uvm_info("SS_CON Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_con_env.vsqr.axi_s_sqr[i])
	`uvm_info("SS_CON Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)    
`endif

  //--------------------------
  // SS_CPU Agent Collection 
  //-------------------------
`ifdef SS_CPU_USED 
  foreach (uvm_ss_cpu_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_ss_cpu_env.axi_sys_env[i]);
  end  
  foreach (uvm_ss_cpu_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_ss_cpu_env.ahb_sys_env[i]);
  end  
  foreach (uvm_ss_cpu_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_ss_cpu_env.apb_sys_env[i]);
  end  

  foreach (uvm_ss_cpu_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_ss_cpu_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_ss_cpu_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_cpu_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_ss_cpu_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_ss_cpu_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_ss_cpu_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_ss_cpu_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_ss_cpu_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_cpu_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_ss_cpu_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_ss_cpu_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_ss_cpu_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_ss_cpu_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_ss_cpu_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_cpu_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_ss_cpu_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_ss_cpu_env.vsqr.apb_s_mon_cb[i];
  end 
  foreach (uvm_ss_cpu_env.vsqr.apb_m_sqr[i])
	`uvm_info("SS_CPU Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cpu_env.vsqr.ahb_m_sqr[i])
	`uvm_info("SS_CPU Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cpu_env.vsqr.axi_m_sqr[i])
	`uvm_info("SS_CPU Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cpu_env.vsqr.apb_s_sqr[i])
	`uvm_info("SS_CPU Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cpu_env.vsqr.ahb_s_sqr[i])
	`uvm_info("SS_CPU Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_cpu_env.vsqr.axi_s_sqr[i])
	`uvm_info("SS_CPU Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)    
`endif

  //--------------------------
  // SS_VIS Agent Collection 
  //-------------------------
`ifdef SS_VIS_USED  
  foreach (uvm_ss_vis_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_ss_vis_env.axi_sys_env[i]);
  end  
  foreach (uvm_ss_vis_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_ss_vis_env.ahb_sys_env[i]);
  end  
  foreach (uvm_ss_vis_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_ss_vis_env.apb_sys_env[i]);
  end  

  foreach (uvm_ss_vis_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_ss_vis_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_ss_vis_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_vis_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_ss_vis_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_ss_vis_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_ss_vis_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_ss_vis_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_ss_vis_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_vis_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_ss_vis_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_ss_vis_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_ss_vis_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_ss_vis_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_ss_vis_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_vis_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_ss_vis_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_ss_vis_env.vsqr.apb_s_mon_cb[i];
  end 
  foreach (uvm_ss_vis_env.vsqr.apb_m_sqr[i])
	`uvm_info("SS_VIS Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_vis_env.vsqr.ahb_m_sqr[i])
	`uvm_info("SS_VIS Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_vis_env.vsqr.axi_m_sqr[i])
	`uvm_info("SS_VIS Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_vis_env.vsqr.apb_s_sqr[i])
	`uvm_info("SS_VIS Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_vis_env.vsqr.ahb_s_sqr[i])
	`uvm_info("SS_VIS Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_vis_env.vsqr.axi_s_sqr[i])
	`uvm_info("SS_VIS Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)    
`endif

  //--------------------------
  // SS_SF Agent Collection 
  //-------------------------
`ifdef SS_SF_USED 
  foreach (uvm_ss_sf_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_ss_sf_env.axi_sys_env[i]);
  end  
  foreach (uvm_ss_sf_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_ss_sf_env.ahb_sys_env[i]);
  end 
  foreach (uvm_ss_sf_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_ss_sf_env.apb_sys_env[i]);
  end 

  foreach (uvm_ss_sf_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_ss_sf_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_ss_sf_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_sf_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_ss_sf_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_ss_sf_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_ss_sf_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_ss_sf_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_ss_sf_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_sf_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_ss_sf_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_ss_sf_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_ss_sf_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_ss_sf_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_ss_sf_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_sf_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_ss_sf_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_ss_sf_env.vsqr.apb_s_mon_cb[i];
  end 
  foreach (uvm_ss_sf_env.vsqr.apb_m_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_sf_env.vsqr.ahb_m_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_sf_env.vsqr.axi_m_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_sf_env.vsqr.apb_s_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_sf_env.vsqr.ahb_s_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_sf_env.vsqr.axi_s_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)  
`endif

  //--------------------------
  // SS_VOUT Agent Collection 
  //-------------------------
`ifdef SS_VOUT_USED  
  foreach (uvm_ss_vout_env.axi_sys_env[i]) begin
    uvm_soc_base_env.axi_sys_env.push_back(uvm_ss_vout_env.axi_sys_env[i]);
  end  
  foreach (uvm_ss_vout_env.ahb_sys_env[i]) begin
    uvm_soc_base_env.ahb_sys_env.push_back(uvm_ss_vout_env.ahb_sys_env[i]);
  end  
  foreach (uvm_ss_vout_env.apb_sys_env[i]) begin
    uvm_soc_base_env.apb_sys_env.push_back(uvm_ss_vout_env.apb_sys_env[i]);
  end  

  foreach (uvm_ss_vout_env.vsqr.axi_m_sqr[i]) begin
     vsqr.axi_m_sqr[i] =  uvm_ss_vout_env.vsqr.axi_m_sqr[i];
     vsqr.axi_m_mon_cb[i] =  uvm_ss_vout_env.vsqr.axi_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_vout_env.vsqr.axi_s_sqr[i]) begin
     vsqr.axi_s_sqr[i] =  uvm_ss_vout_env.vsqr.axi_s_sqr[i];
     vsqr.axi_s_mon_cb[i] =  uvm_ss_vout_env.vsqr.axi_s_mon_cb[i];
  end 	
  foreach (uvm_ss_vout_env.vsqr.ahb_m_sqr[i]) begin
     vsqr.ahb_m_sqr[i] =  uvm_ss_vout_env.vsqr.ahb_m_sqr[i];
     vsqr.ahb_m_mon_cb[i] =  uvm_ss_vout_env.vsqr.ahb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_vout_env.vsqr.ahb_s_sqr[i]) begin
     vsqr.ahb_s_sqr[i] =  uvm_ss_vout_env.vsqr.ahb_s_sqr[i];
     vsqr.ahb_s_mon_cb[i] =  uvm_ss_vout_env.vsqr.ahb_s_mon_cb[i];
  end 
  foreach (uvm_ss_vout_env.vsqr.apb_m_sqr[i]) begin
     vsqr.apb_m_sqr[i] =  uvm_ss_vout_env.vsqr.apb_m_sqr[i];
     vsqr.apb_m_mon_cb[i] =  uvm_ss_vout_env.vsqr.apb_m_mon_cb[i];
  end 	 
  foreach (uvm_ss_vout_env.vsqr.apb_s_sqr[i]) begin
     vsqr.apb_s_sqr[i] =  uvm_ss_vout_env.vsqr.apb_s_sqr[i];
     vsqr.apb_s_mon_cb[i] =  uvm_ss_vout_env.vsqr.apb_s_mon_cb[i];
  end 
  foreach (uvm_ss_vout_env.vsqr.apb_m_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("APB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_vout_env.vsqr.ahb_m_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("AHB Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_vout_env.vsqr.axi_m_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("AXI Master Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_vout_env.vsqr.apb_s_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("APB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_vout_env.vsqr.ahb_s_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("AHB Slave Agent [%0s]",i), UVM_LOW)
  foreach (uvm_ss_vout_env.vsqr.axi_s_sqr[i])
	`uvm_info("SS_SF Agent Collection", $sformatf("AXI Slave Agent [%0s]",i), UVM_LOW)  
`endif


endfunction: connect_phase
  
// -----------------------------------------------------------------------------
function void soc_base_test::end_of_elaboration_phase(uvm_phase phase);
  super.end_of_elaboration_phase(phase);
  uvm_top.print_topology();
endfunction: end_of_elaboration_phase

// -----------------------------------------------------------------------------
function void soc_base_test::final_phase(uvm_phase phase);
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
 
`endif // GUARD_VCATB_BASE_TEST_SV
