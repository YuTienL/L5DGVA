`ifndef GUARD_CUST_AHB_SLAVE_MONITOR_CALLBACK_SV
`define GUARD_CUST_AHB_SLAVE_MONITOR_CALLBACK_SV

/**
 * Abstract:
 */

class cust_ahb_slave_monitor_callback extends svt_ahb_slave_monitor_callback;

`uvm_object_utils(cust_ahb_slave_monitor_callback)

  function new(string name = "cust_ahb_slave_monitor_callback");
  super.new(name);
  endfunction

  virtual function void transaction_ended ( svt_ahb_slave_monitor monitor , svt_ahb_slave_transaction xact );
    super.transaction_ended(monitor, xact);
    `uvm_info(get_name(), $sformatf("AHB_SLV:%0s ADDR:%0h BURST:%0s SIZE:%0s",xact.xact_type.name(), xact.addr, xact.burst_type.name(), xact.burst_size.name()), UVM_NONE)
    `uvm_info(get_name(), $sformatf("Inside AHB slave monitor transaction_ended callback:\n%0s",xact.sprint()), UVM_HIGH)
  endfunction

endclass

`endif // GUARD_CUST_AHB_SLAVE_MONITOR_CALLBACK_SV
