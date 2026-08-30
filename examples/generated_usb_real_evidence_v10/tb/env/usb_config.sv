class usb_config extends uvm_object;
  `uvm_object_utils(usb_config)
  bit is_active = 1'b1;
  string role = "device";
  function new(string name="usb_config"); super.new(name); endfunction
endclass
