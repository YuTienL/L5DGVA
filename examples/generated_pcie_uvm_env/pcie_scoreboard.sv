class pcie_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(pcie_scoreboard)
  // RULE: {"name": "completion_matching"}
  // RULE: {"name": "memory_data_integrity"}
  function new(string name="pcie_scoreboard", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
