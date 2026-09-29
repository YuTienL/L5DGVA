`ifndef GUARD_CUST_AXI_SLAVE_MONITOR_CALLBACK_SV
`define GUARD_CUST_AXI_SLAVE_MONITOR_CALLBACK_SV

/**
 * Abstract:
 */

class cust_axi_slave_monitor_callback extends svt_axi_port_monitor_callback;

`uvm_object_utils(cust_axi_slave_monitor_callback)

  function new(string name = "cust_axi_slave_monitor_callback");
  super.new(name);
  endfunction

  virtual function void transaction_ended ( svt_axi_port_monitor monitor , svt_axi_transaction xact );
    super.transaction_ended(monitor, xact);
	`uvm_info(get_name(), $sformatf("Inside AXI slave monitor transaction_ended callback"), UVM_LOW)
    xact.print(); 
  endfunction

endclass

`endif // GUARD_CUST_AXI_SLAVE_MONITOR_CALLBACK_SV
