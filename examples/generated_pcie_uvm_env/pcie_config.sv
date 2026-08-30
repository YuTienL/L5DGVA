class pcie_config extends uvm_object;
  `uvm_object_utils(pcie_config)
  bit is_active = 1'b1;
  string role = "EP";
  function new(string name="pcie_config"); super.new(name); endfunction
endclass
