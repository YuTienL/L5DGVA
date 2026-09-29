`ifndef GUARD_CUST_AHB_MASTER_MONITOR_CALLBACK_SV
`define GUARD_CUST_AHB_MASTER_MONITOR_CALLBACK_SV

/**
 * Abstract:
 */

class cust_ahb_master_monitor_callback extends svt_ahb_master_monitor_callback;

`uvm_object_utils(cust_ahb_master_monitor_callback)

  function new(string name = "cust_ahb_master_monitor_callback");
  super.new(name);
  endfunction

  virtual function void transaction_ended ( svt_ahb_master_monitor monitor , svt_ahb_master_transaction xact );
    super.transaction_ended(monitor, xact); 
	`uvm_info(get_name(), $sformatf("Inside AHB master monitor transaction_ended callback"), UVM_LOW)
    xact.print(); 
  endfunction

endclass

`endif // GUARD_CUST_AHB_MASTER_MONITOR_CALLBACK_SV
