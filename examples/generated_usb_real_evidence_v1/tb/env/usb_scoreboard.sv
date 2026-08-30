class usb_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(usb_scoreboard)
  // RULE: {"TODO": "not enough real evidence gathered this pass to state a specific checking rule; real VIP example env at D:/DV/Task/USB/VIP/examples/tb_usb_svt_uvm_20_b2b_phy/env/usb_transfer_scoreboard.sv and usb_packet_scoreboard.sv show the NAMING convention a real scoreboard split uses (transfer-level vs packet-level), but that example is a PHY-level VIP<->VIP topology, not this project's VIP-host<->DUT-device topology, so its actual rule content is not evidence for this DUT"}
  function new(string name="usb_scoreboard", uvm_component parent=null);
    super.new(name,parent);
  endfunction
endclass
