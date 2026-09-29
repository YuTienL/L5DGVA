/**
 * Abstract: 
 * Class coretop_base_env is extended from uvm_env base class.  It implements
 * the build phase to construct the structural elements of this environment.
 */

`ifndef GUARD_CORETOP_BASE_ENV_SV
`define GUARD_CORETOP_BASE_ENV_SV

`include "coretop_configuration.sv"
`include "coretop_virtual_sequencer.sv"


class coretop_base_env extends uvm_env;

  svt_axi_system_env axi_system_env_0;
  svt_apb_system_env apb_system_env_0;
  svt_ahb_system_env ahb_system_env_0;
  svt_apb_system_env apb_system_env_1;
  svt_apb_system_env apb_system_env_2;
  svt_apb_system_env apb_system_env_3;
  svt_apb_system_env apb_system_env_4;  

  svt_axi_system_env axi_sys_env[$];
  svt_ahb_system_env ahb_sys_env[$];
  svt_apb_system_env apb_sys_env[$];

  /** VC SOC Virtual Sequencer */
  coretop_virtual_sequencer vsqr;

  /** VC SOC System Configuration */
  coretop_configuration cfg;

  svt_axi_system_configuration axi_sys_cfg[$];
  svt_ahb_system_configuration ahb_sys_cfg[$];
  svt_apb_system_configuration apb_sys_cfg[$];

  /** UVM Component Utility macro */
  `uvm_component_utils(coretop_base_env)

  /** Class Constructor */
  function new(string name="coretop_base_env", uvm_component parent=null);
    super.new(name, parent);
  endfunction : new

  /** Build the testbench sub-components */
  extern virtual function void build_phase(uvm_phase phase);

  /** Connect the VC SOC Virtual Sequencer to the VIP components */
  extern virtual function void connect_phase(uvm_phase phase);

  /** Delay the reset phase until reset is deasserted */
  extern virtual task reset_phase(uvm_phase phase);

endclass: coretop_base_env


// -----------------------------------------------------------------------------
function void coretop_base_env::build_phase(uvm_phase phase);
  super.build_phase(phase);

  /**
   * Check if the configuration is passed to the environment.
   * If not then create the configuration and pass it to the agent.
   */
  if (!uvm_config_db#(coretop_configuration)::get(this, "", "cfg", cfg)) begin
    cfg = coretop_configuration::type_id::create("cfg");
  end

  /** Apply the configuration to axi_system_env_0 */
  uvm_config_db#(svt_axi_system_configuration)::set(this, "axi_system_env_0", "cfg", cfg.axi_system_env_cfg_0);
  axi_sys_cfg.push_back(cfg.axi_system_env_cfg_0);

  /** Construct axi_system_env_0 */
  axi_system_env_0 = svt_axi_system_env::type_id::create("axi_system_env_0", this);
  axi_sys_env.push_back(axi_system_env_0);

  /** Apply the configuration to ahb_system_env_0 */
  uvm_config_db#(svt_ahb_system_configuration)::set(this, "ahb_system_env_0", "cfg", cfg.ahb_system_env_cfg_0);
  ahb_sys_cfg.push_back(cfg.ahb_system_env_cfg_0);

  /** Construct ahb_system_env_0 */
  ahb_system_env_0 = svt_ahb_system_env::type_id::create("ahb_system_env_0", this);
  ahb_sys_env.push_back(ahb_system_env_0);

  /** Apply the configuration to apb_system_env_0 */
  uvm_config_db#(svt_apb_system_configuration)::set(this, "apb_system_env_0", "cfg", cfg.apb_system_env_cfg_0);
  apb_sys_cfg.push_back(cfg.apb_system_env_cfg_0);

  /** Construct apb_system_env_0 */
  apb_system_env_0 = svt_apb_system_env::type_id::create("apb_system_env_0", this);
  apb_sys_env.push_back(apb_system_env_0);

  /** Apply the configuration to apb_system_env_1 */
  uvm_config_db#(svt_apb_system_configuration)::set(this, "apb_system_env_1", "cfg", cfg.apb_system_env_cfg_1);
  apb_sys_cfg.push_back(cfg.apb_system_env_cfg_1);

  /** Construct apb_system_env_1 */
  apb_system_env_1 = svt_apb_system_env::type_id::create("apb_system_env_1", this);
  apb_sys_env.push_back(apb_system_env_1);

  /** Apply the configuration to apb_system_env_2 */
  uvm_config_db#(svt_apb_system_configuration)::set(this, "apb_system_env_2", "cfg", cfg.apb_system_env_cfg_2);
  apb_sys_cfg.push_back(cfg.apb_system_env_cfg_2);

  /** Construct apb_system_env_2 */
  apb_system_env_2 = svt_apb_system_env::type_id::create("apb_system_env_2", this);
  apb_sys_env.push_back(apb_system_env_2);

  /** Apply the configuration to apb_system_env_3 */
  uvm_config_db#(svt_apb_system_configuration)::set(this, "apb_system_env_3", "cfg", cfg.apb_system_env_cfg_3);
  apb_sys_cfg.push_back(cfg.apb_system_env_cfg_3);

  /** Construct apb_system_env_3 */
  apb_system_env_3 = svt_apb_system_env::type_id::create("apb_system_env_3", this);
  apb_sys_env.push_back(apb_system_env_3);
 
  /** Apply the configuration to apb_system_env_4 */
  uvm_config_db#(svt_apb_system_configuration)::set(this, "apb_system_env_4", "cfg", cfg.apb_system_env_cfg_4);
  apb_sys_cfg.push_back(cfg.apb_system_env_cfg_4);

  /** Construct apb_system_env_4 */
  apb_system_env_4 = svt_apb_system_env::type_id::create("apb_system_env_4", this);
  apb_sys_env.push_back(apb_system_env_4);
  
  /** Construct the VC SOC Virtual Sequencer */
  vsqr = coretop_virtual_sequencer::type_id::create("vsqr", this);
 
endfunction: build_phase

// -----------------------------------------------------------------------------
function void coretop_base_env::connect_phase(uvm_phase phase);
  super.connect_phase(phase);

  foreach (ahb_sys_cfg[i]) begin		  
	foreach (ahb_sys_cfg[i].master_cfg[j]) begin
      vsqr.ahb_m_sqr[ahb_sys_cfg[i].master_cfg[j].inst] = ahb_sys_env[i].master[j].sequencer;
      vsqr.ahb_m_mon_cb[ahb_sys_cfg[i].master_cfg[j].inst] = new(ahb_sys_cfg[i].master_cfg[j].inst);
      uvm_callbacks #(svt_ahb_master_monitor,svt_ahb_master_monitor_callback)::add(ahb_sys_env[i].master[j].monitor, vsqr.ahb_m_mon_cb[ahb_sys_cfg[i].master_cfg[j].inst]);
    end
  end		
  foreach (ahb_sys_cfg[i]) begin		  
	foreach (ahb_sys_cfg[i].slave_cfg[j]) begin
      vsqr.ahb_s_sqr[ahb_sys_cfg[i].slave_cfg[j].inst] = ahb_sys_env[i].slave[j].sequencer;	   
      vsqr.ahb_s_mon_cb[ahb_sys_cfg[i].slave_cfg[j].inst] = new(ahb_sys_cfg[i].slave_cfg[j].inst);
      uvm_callbacks #(svt_ahb_slave_monitor,svt_ahb_slave_monitor_callback)::add(ahb_sys_env[i].slave[j].monitor, vsqr.ahb_s_mon_cb[ahb_sys_cfg[i].slave_cfg[j].inst]);
	end	
  end

  foreach (axi_sys_cfg[i]) begin		  
	foreach (axi_sys_cfg[i].master_cfg[j]) begin
	  vsqr.axi_m_sqr[axi_sys_cfg[i].master_cfg[j].inst] = axi_sys_env[i].master[j].sequencer;	
	  vsqr.axi_m_mon_cb[axi_sys_cfg[i].master_cfg[j].inst] = new(axi_sys_cfg[i].master_cfg[j].inst);
      uvm_callbacks#(svt_axi_port_monitor)::add(axi_sys_env[i].master[j].monitor, vsqr.axi_m_mon_cb[axi_sys_cfg[i].master_cfg[j].inst]);
	end	
  end		
  foreach (axi_sys_cfg[i]) begin		  
	foreach (axi_sys_cfg[i].slave_cfg[j]) begin 
	  vsqr.axi_s_sqr[axi_sys_cfg[i].slave_cfg[j].inst] = axi_sys_env[i].slave[j].sequencer;	   
	  vsqr.axi_s_mon_cb[axi_sys_cfg[i].slave_cfg[j].inst] = new(axi_sys_cfg[i].slave_cfg[j].inst);
      uvm_callbacks#(svt_axi_port_monitor)::add(axi_sys_env[i].slave[j].monitor, vsqr.axi_s_mon_cb[axi_sys_cfg[i].slave_cfg[j].inst]);
	end	
  end

  foreach (apb_sys_cfg[i]) begin	
	if (apb_sys_cfg[i].inst != "unset_inst") begin
      vsqr.apb_m_sqr[apb_sys_cfg[i].inst] = apb_sys_env[i].master.sequencer;	
      vsqr.apb_m_mon_cb[apb_sys_cfg[i].inst] = new(apb_sys_cfg[i].inst);
      uvm_callbacks #(svt_apb_master_monitor,svt_apb_master_monitor_callback)::add(apb_sys_env[i].master.monitor, vsqr.apb_m_mon_cb[apb_sys_cfg[i].inst]);
	end
	foreach (apb_sys_cfg[i].slave_cfg[j]) begin  
      if (apb_sys_cfg[i].slave_cfg[j].inst != "unset_inst") begin      
	    vsqr.apb_s_sqr[apb_sys_cfg[i].slave_cfg[j].inst] = apb_sys_env[i].slave[j].sequencer;
        vsqr.apb_s_mon_cb[apb_sys_cfg[i].slave_cfg[j].inst] = new(apb_sys_cfg[i].slave_cfg[j].inst);
        uvm_callbacks #(svt_apb_slave_monitor,svt_apb_slave_monitor_callback)::add(apb_sys_env[i].slave[j].monitor, vsqr.apb_s_mon_cb[apb_sys_cfg[i].slave_cfg[j].inst]);
      end   
	end	
  end

endfunction: connect_phase

// -----------------------------------------------------------------------------
task coretop_base_env::reset_phase(uvm_phase phase);
  super.reset_phase(phase);
endtask: reset_phase

`endif // GUARD_CORETOP_BASE_ENV_SV
