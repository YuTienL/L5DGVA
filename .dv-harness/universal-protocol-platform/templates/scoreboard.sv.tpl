class {{SB_CLASS}} extends uvm_scoreboard;
  `uvm_component_utils({{SB_CLASS}})
  function new(string name="{{SB_CLASS}}", uvm_component parent=null);
    super.new(name,parent);
  endfunction
  // Protocol-specific prediction/checking MUST be generated from verified evidence.
endclass
