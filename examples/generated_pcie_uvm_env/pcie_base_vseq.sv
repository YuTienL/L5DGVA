class pcie_base_vseq extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils(pcie_base_vseq)
  `uvm_declare_p_sequencer(pcie_virtual_sequencer)
  function new(string name="pcie_base_vseq"); super.new(name); endfunction
  virtual task body();
    `uvm_info(get_type_name(), "Base virtual sequence started", UVM_MEDIUM)
  endtask
endclass
