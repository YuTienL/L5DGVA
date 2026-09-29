/**
 * Abstract:
 * Class soc_virtual_sequencer is the top-level virtual sequencer for the
 * environment.  It contains references to the top-level virtual sequencers
 * in each VIP instance.
 */

`ifndef GUARD_SOC_VIRTUAL_SEQUENCER_SV
`define GUARD_SOC_VIRTUAL_SEQUENCER_SV

`include "cust_ahb_master_monitor_callback.sv"
`include "cust_ahb_slave_monitor_callback.sv"
`include "cust_apb_master_monitor_callback.sv"
`include "cust_apb_slave_monitor_callback.sv"
`include "cust_axi_master_monitor_callback.sv"
`include "cust_axi_slave_monitor_callback.sv"

class soc_virtual_sequencer extends uvm_sequencer;

  `uvm_component_utils(soc_virtual_sequencer)

  //svt_ahb_system_sequencer ahb_system_env_0_sequencer;
  //svt_axi_system_sequencer axi_system_env_0_sequencer;

  svt_ahb_master_transaction_sequencer   ahb_m_sqr[string];
  svt_ahb_slave_sequencer   ahb_s_sqr[string];
  svt_axi_master_sequencer  axi_m_sqr[string];
  svt_axi_slave_sequencer   axi_s_sqr[string];
  svt_apb_master_sequencer  apb_m_sqr[string];
  svt_apb_slave_sequencer   apb_s_sqr[string]; 

  cust_ahb_master_monitor_callback ahb_m_mon_cb [string];
  cust_ahb_slave_monitor_callback  ahb_s_mon_cb [string];
  cust_apb_master_monitor_callback apb_m_mon_cb [string];
  cust_apb_slave_monitor_callback  apb_s_mon_cb [string];
  cust_axi_master_monitor_callback axi_m_mon_cb [string];
  cust_axi_slave_monitor_callback  axi_s_mon_cb [string];

  function new(string name="soc_virtual_sequencer", uvm_component parent=null);
    super.new(name, parent);
  endfunction

endclass: soc_virtual_sequencer

`endif // GUARD_SOC_VIRTUAL_SEQUENCER_SV
