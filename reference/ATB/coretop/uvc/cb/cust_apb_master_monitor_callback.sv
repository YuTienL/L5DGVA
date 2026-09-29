`ifndef GUARD_CUST_APB_MASTER_MONITOR_CALLBACK_SV
`define GUARD_CUST_APB_MASTER_MONITOR_CALLBACK_SV

/**
 * Abstract:
 */

class cust_apb_master_monitor_callback extends svt_apb_master_monitor_callback;

`uvm_object_utils(cust_apb_master_monitor_callback)

  function new(string name = "cust_apb_master_monitor_callback");
  super.new(name);
  endfunction

  virtual function void access_phase ( svt_apb_master_monitor monitor , svt_apb_transaction xact );
    super.access_phase(monitor, xact);
    `uvm_info(get_name(), $sformatf("Inside APB master monitor transaction_ended callback"), UVM_LOW)
    xact.print(); 
  endfunction

endclass

`endif // GUARD_CUST_APB_MASTER_MONITOR_CALLBACK_SV
