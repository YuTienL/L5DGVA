`ifndef GUARD_CUST_AXI_MASTER_MONITOR_CALLBACK_SV
`define GUARD_CUST_AXI_MASTER_MONITOR_CALLBACK_SV

/**
 * Abstract:
 */

class cust_axi_master_monitor_callback extends svt_axi_port_monitor_callback;

`uvm_object_utils(cust_axi_master_monitor_callback)

  function new(string name = "cust_axi_master_monitor_callback");
  super.new(name);
  endfunction

  virtual function void transaction_ended ( svt_axi_port_monitor monitor , svt_axi_transaction xact );
    super.transaction_ended(monitor, xact);
    `uvm_info(get_name(), $sformatf("AXI_MST:%0s ADDR:%0h BURST:%0s LEN:%0h SIZE:%0s",xact.xact_type.name(), xact.addr, xact.burst_type.name(), xact.burst_length, xact.burst_size.name()), UVM_NONE)
	`uvm_info(get_name(), $sformatf("Inside AXI master monitor transaction_ended callback:\n%0s",xact.sprint()), UVM_HIGH)
  endfunction

endclass

`endif // GUARD_CUST_AXI_MASTER_MONITOR_CALLBACK_SV
