class pcie_coverage extends uvm_component;
  `uvm_component_utils(pcie_coverage)
  // COVER: {"name": "ltssm_state"}
  // COVER: {"name": "tlp_type"}
  // COVER: {"name": "completion_status"}
  function new(string name="pcie_coverage", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
