class usb_base_test extends uvm_test;
  `uvm_component_utils(usb_base_test)
  usb_env env;
  function new(string name="usb_base_test", uvm_component parent=null); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    env=usb_env::type_id::create("env",this);
  endfunction
endclass
