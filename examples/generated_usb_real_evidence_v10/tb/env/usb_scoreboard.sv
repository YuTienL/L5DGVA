class usb_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(usb_scoreboard)
  // RULE: {"TODO": "not enough real evidence gathered this pass to state a specific checking rule -- unchanged from v1"}
  function new(string name="usb_scoreboard", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
