`ifndef GUARD_CUST_APB_SLAVE_MONITOR_CALLBACK_SV
`define GUARD_CUST_APB_SLAVE_MONITOR_CALLBACK_SV

/**
 * Abstract:
 */

class cust_apb_slave_monitor_callback extends svt_apb_slave_monitor_callback;

`uvm_object_utils(cust_apb_slave_monitor_callback)

  function new(string name = "cust_apb_slave_monitor_callback");
  super.new(name);
  endfunction

  virtual function void access_phase ( svt_apb_slave_monitor monitor , svt_apb_transaction xact );
    super.access_phase(monitor, xact);
	if (xact.curr_state == `SVT_APB_TRANSACTION_STATE_ENABLE) begin
      `uvm_info(get_name(), $sformatf("APB_SLV:%0s ADDR:%0h",xact.xact_type.name(), xact.address ), UVM_NONE)
	  `uvm_info(get_name(), $sformatf("Inside APB slave monitor transaction_ended callback:\n%0s",xact.sprint()), UVM_HIGH)
	end  
  endfunction

endclass

`endif // GUARD_CUST_APB_SLAVE_MONITOR_CALLBACK_SV
