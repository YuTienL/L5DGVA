class usb_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(usb_scoreboard)
  // RULE: {"TODO": "not enough real evidence gathered this pass to state a specific checking rule -- unchanged from v1"}
  function new(string name="usb_scoreboard", uvm_component parent=null);
    super.new(name,parent);
  endfunction
  function void check_ep_eptype_dut_vip_config_agreement(bit [31:0] dut_depcfg_param0_eptype, svt_usb_types::ep_type_enum vip_ep_cfg_ep_type);
    bit [1:0] lhs = dut_depcfg_param0_eptype[2:1];
    int rhs_raw = int'(vip_ep_cfg_ep_type); // Identity mapping, but verified against REAL macro-resolved values, not the enum's textual declaration order: D:/DV/Task/USB/VIP/src/sverilog/vcs/svt_usb_types.sv:701-706 declares ep_type_enum in the order CONTROL, BULK, INTERRUPT, ISOCHRONOUS (NOT sequential 0..3 by that order); the actual bit[1:0] values are resolved at D:/DV/Task/USB/VIP/include/sverilog/svt_usb_common_defines.svi:3076-3079 as CONTROL=2'b00, ISOCHRONOUS=2'b01, BULK=2'b10, INTERRUPT=2'b11, which matches DEPCFG0 EPType's DOC-documented 0=Control/1=Isochronous/2=Bulk/3=Interrupt mapping (DWC_usb31_programming.txt:27498-27503) exactly.
    int rhs;
    case (rhs_raw)
      0: rhs = 0;
      1: rhs = 1;
      2: rhs = 2;
      3: rhs = 3;
      default: begin
        rhs = rhs_raw;
        `uvm_error("SB_EP_EPTYPE_DUT_VIP_CONFIG_AGREEMENT", $sformatf("ep_eptype_dut_vip_config_agreement: unmapped enum_translation value %0d on rhs", rhs_raw))
      end
    endcase
    if (lhs !== rhs)
      `uvm_error("SB_EP_EPTYPE_DUT_VIP_CONFIG_AGREEMENT", $sformatf("EPType config mismatch on %s: DUT DEPCFG Param0[2:1] EPType=%0d VIP svt_usb_endpoint_configuration.ep_type=%0d", "ep_eptype_dut_vip_config_agreement", lhs, rhs))
  endfunction
  function void check_ep_mps_dut_vip_config_agreement(bit [31:0] dut_depcfg_param0_mps, int vip_ep_cfg_max_packet_size);
    bit [10:0] lhs = dut_depcfg_param0_mps[13:3];
    int rhs = int'(vip_ep_cfg_max_packet_size);
    if (lhs !== rhs)
      `uvm_error("SB_EP_MPS_DUT_VIP_CONFIG_AGREEMENT", $sformatf("MaxPacketSize config mismatch on %s: DUT DEPCFG Param0[13:3] MPS=%0d VIP svt_usb_endpoint_configuration.max_packet_size=%0d", "ep_mps_dut_vip_config_agreement", lhs, rhs))
  endfunction
endclass
