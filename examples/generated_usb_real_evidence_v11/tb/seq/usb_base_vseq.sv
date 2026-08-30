class usb_base_vseq extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils(usb_base_vseq)
  `uvm_declare_p_sequencer(usb_virtual_sequencer)
  function new(string name="usb_base_vseq"); super.new(name); endfunction
  virtual task body();
    `uvm_info(get_type_name(), "Base virtual sequence started", UVM_MEDIUM)
  endtask
endclass

class usb_device_enumeration_vseq extends usb_base_vseq;
  `uvm_object_utils(usb_device_enumeration_vseq)
  function new(string name="usb_device_enumeration_vseq"); super.new(name); endfunction
  virtual task body();
    bit status;
    int new_device_addr;
    svt_usb_transfer get_device_descriptor_short_xfer;
    // evidence: usb_directed_transfers_sequence.sv:148 (svt_configuration get_cfg;)
    svt_configuration get_cfg;
    // evidence: usb_directed_transfers_sequence.sv:149 (svt_usb_configuration cfg;)
    svt_usb_configuration cfg;
    // evidence: ts.basic_additional_20_enumeration.sv:158 (svt_usb_agent l_agent;)
    svt_usb_agent l_agent;
    // evidence: usb_directed_transfers_sequence.sv:166 (p_sequencer.get_cfg(get_cfg);), routed through this manifest's own usb_xfer_seqr[0] virtual_sequencer_fields entry -- see this entry's own top-level 'evidence' field for the full adaptation rationale.
    p_sequencer.usb_xfer_seqr[0].get_cfg(get_cfg);
    // evidence: usb_directed_transfers_sequence.sv:168-170, verbatim.
    if (!$cast(cfg, get_cfg)) `uvm_fatal("body", "Unable to $cast the configuration to a svt_usb_configuration class");
    // evidence: ts.basic_additional_20_enumeration.sv:183-185, routed through usb_xfer_seqr[0] the same way as get_cfg above.
    if (!$cast(l_agent, p_sequencer.usb_xfer_seqr[0].find_first_agent(this)) || (l_agent == null)) `uvm_fatal("body", "Agent handle is null");
    // evidence: USB 2.0 spec 9.4.6 (p.256): 'the specified device address is greater than 127...behavior...not specified' and 'Device response to SetAddress() with a value of 0 is undefined' -- 1 is the smallest legal non-zero address; no VIP example gives a specific default, this is a spec-derived choice, not a copied one, and is overridable below.
    int unsigned device_address = 1;
    // evidence: usb_directed_transfers_sequence.sv:161 / ts.basic_additional_20_enumeration.sv:187, same config_db-parameter-override idiom (there applied to sequence_length), applied here to device_address so a calling test can inject a specific legal address (1-127).
    status = uvm_config_db#(int unsigned)::get(null, get_full_name(), "device_address", device_address);
    // evidence: USB 2.0 spec 9.4.7 (p.257): 'This configuration value must be zero or match a configuration value from a configuration descriptor' -- 1 is the common single-configuration-device convention; the real legal value is only knowable after this vseq's own get_config_descriptor step below decodes the just-fetched descriptor's bConfigurationValue (Table 9-10 offset 5), which this DSL's capture[]/field_values shape has no accessor for (capture[] can only read back a request-side field of the just-randomized ITEM via a get_<field>_val() accessor, e.g. get_setup_data_w_value_val() below, never a received response PAYLOAD byte) -- recorded here as a real, currently-unclosed DSL gap, not silently hidden, same evidence-discipline convention as this manifest's own v7 notes.
    int unsigned configuration_value = 1;
    // evidence: same config_db-override idiom as device_address above.
    status = uvm_config_db#(int unsigned)::get(null, get_full_name(), "configuration_value", configuration_value);
    `uvm_create_on(get_device_descriptor_short_xfer, p_sequencer.usb_xfer_seqr[0])
    get_device_descriptor_short_xfer.cfg = cfg;
    // evidence: usb_directed_transfers_sequence.sv:239,276,305 -- fix_anchors(0,0,0) for every CONTROL transfer, targeting the default control endpoint (device index 0); fix_anchors takes INDICES not address/ep-number values (that file's own comment, lines 192-195).
    get_device_descriptor_short_xfer.fix_anchors(0,0,0);
    status = get_device_descriptor_short_xfer.randomize() with {
      xfer_type == svt_usb_transfer::CONTROL_TRANSFER;
      setup_data_bmrequesttype_dir == svt_usb_types::DEVICE_TO_HOST;
      setup_data_bmrequesttype_type == svt_usb_types::STANDARD;
      setup_data_bmrequesttype_recipient == svt_usb_types::BMREQ_DEVICE;
      setup_data_brequest == svt_usb_types::GET_DESCRIPTOR;
      setup_data_w_value == 16'h0100;
      setup_data_w_index == 16'h0000;
      setup_data_w_length == 8;
    };
    if (!status) `uvm_fatal("body", "get_device_descriptor_short Randomization failed!!!")
    `uvm_send_on(get_device_descriptor_short_xfer, p_sequencer.usb_xfer_seqr[0])
    svt_usb_transfer set_address_xfer;
    `uvm_create_on(set_address_xfer, p_sequencer.usb_xfer_seqr[0])
    set_address_xfer.cfg = cfg;
    // evidence: same fix_anchors(0,0,0) convention as above; 9.4.6 (p.256): this transfer itself must still address the OLD value, the device does not change its address until AFTER this request's own Status stage completes -- so targeting device index 0 here (the pre-SET_ADDRESS index) is correct.
    set_address_xfer.fix_anchors(0,0,0);
    status = set_address_xfer.randomize() with {
      xfer_type == svt_usb_transfer::CONTROL_TRANSFER;
      setup_data_bmrequesttype_dir == svt_usb_types::HOST_TO_DEVICE;
      setup_data_bmrequesttype_type == svt_usb_types::STANDARD;
      setup_data_bmrequesttype_recipient == svt_usb_types::BMREQ_DEVICE;
      setup_data_brequest == svt_usb_types::SET_ADDRESS;
      setup_data_w_value == device_address;
      setup_data_w_index == 16'h0000;
      setup_data_w_length == 16'h0000;
    };
    if (!status) `uvm_fatal("body", "set_address Randomization failed!!!")
    new_device_addr = set_address_xfer.get_setup_data_w_value_val();
    `uvm_send_on(set_address_xfer, p_sequencer.usb_xfer_seqr[0])
    svt_usb_transfer get_device_descriptor_full_xfer;
    // evidence: ts.basic_additional_20_enumeration.sv:250: post_enumeration_cfg.remote_device_cfg[0].device_address = usb_xfer[0].get_setup_data_w_value_val(); -- same field path and accessor convention, applied to the SAME cfg object every step's <step>.cfg = cfg; assignment shares (declared once, step get_device_descriptor_short's own wait_conditions above), so this step's fix_anchors(0,0,0)-targeted transfer picks up the new address through cfg.
    cfg.remote_device_cfg[0].device_address = new_device_addr;
    // evidence: ts.basic_additional_20_enumeration.sv:253: l_agent.reconfigure(post_enumeration_cfg); -- svt_agent::reconfigure(svt_configuration cfg) real at D:/DV/Task/USB/VIP/src/sverilog/vcs/svt_agent.sv:282, inherited by svt_usb_agent. Placed in THIS step's wait_conditions (before this step's own item is created) rather than as a post_action on the set_address step itself: uvm_send_on (issuing set_address's item, previous step) blocks until the sequencer/driver reports item_done, which per 9.4.6 (p.256, 'the device does not change its device address until after the Status stage of this request is completed successfully') is exactly the point the address change may safely be applied -- the real file's own separate wait_trigger()+timing-delay dance (lines 238,244) is needed there only to bridge its own non-blocking custom-callback path, not needed here given this DSL's already-blocking uvm_send_on/uvm_do_with macro semantics.
    l_agent.reconfigure(cfg);
    `uvm_create_on(get_device_descriptor_full_xfer, p_sequencer.usb_xfer_seqr[0])
    get_device_descriptor_full_xfer.cfg = cfg;
    // evidence: same fix_anchors(0,0,0) convention; now issued AFTER the reconfigure above, so it correctly targets the device's new address.
    get_device_descriptor_full_xfer.fix_anchors(0,0,0);
    status = get_device_descriptor_full_xfer.randomize() with {
      xfer_type == svt_usb_transfer::CONTROL_TRANSFER;
      setup_data_bmrequesttype_dir == svt_usb_types::DEVICE_TO_HOST;
      setup_data_bmrequesttype_type == svt_usb_types::STANDARD;
      setup_data_bmrequesttype_recipient == svt_usb_types::BMREQ_DEVICE;
      setup_data_brequest == svt_usb_types::GET_DESCRIPTOR;
      setup_data_w_value == 16'h0100;
      setup_data_w_index == 16'h0000;
      setup_data_w_length == 18;
    };
    if (!status) `uvm_fatal("body", "get_device_descriptor_full Randomization failed!!!")
    `uvm_send_on(get_device_descriptor_full_xfer, p_sequencer.usb_xfer_seqr[0])
    svt_usb_transfer get_config_descriptor_xfer;
    `uvm_create_on(get_config_descriptor_xfer, p_sequencer.usb_xfer_seqr[0])
    get_config_descriptor_xfer.cfg = cfg;
    // evidence: same fix_anchors(0,0,0) convention.
    get_config_descriptor_xfer.fix_anchors(0,0,0);
    status = get_config_descriptor_xfer.randomize() with {
      xfer_type == svt_usb_transfer::CONTROL_TRANSFER;
      setup_data_bmrequesttype_dir == svt_usb_types::DEVICE_TO_HOST;
      setup_data_bmrequesttype_type == svt_usb_types::STANDARD;
      setup_data_bmrequesttype_recipient == svt_usb_types::BMREQ_DEVICE;
      setup_data_brequest == svt_usb_types::GET_DESCRIPTOR;
      setup_data_w_value == 16'h0200;
      setup_data_w_index == 16'h0000;
      setup_data_w_length == 16'd255;
    };
    if (!status) `uvm_fatal("body", "get_config_descriptor Randomization failed!!!")
    `uvm_send_on(get_config_descriptor_xfer, p_sequencer.usb_xfer_seqr[0])
    svt_usb_transfer set_configuration_xfer;
    `uvm_create_on(set_configuration_xfer, p_sequencer.usb_xfer_seqr[0])
    set_configuration_xfer.cfg = cfg;
    // evidence: same fix_anchors(0,0,0) convention.
    set_configuration_xfer.fix_anchors(0,0,0);
    status = set_configuration_xfer.randomize() with {
      xfer_type == svt_usb_transfer::CONTROL_TRANSFER;
      setup_data_bmrequesttype_dir == svt_usb_types::HOST_TO_DEVICE;
      setup_data_bmrequesttype_type == svt_usb_types::STANDARD;
      setup_data_bmrequesttype_recipient == svt_usb_types::BMREQ_DEVICE;
      setup_data_brequest == svt_usb_types::SET_CONFIGURATION;
      setup_data_w_value == configuration_value;
      setup_data_w_index == 16'h0000;
      setup_data_w_length == 16'h0000;
    };
    if (!status) `uvm_fatal("body", "set_configuration Randomization failed!!!")
    `uvm_send_on(set_configuration_xfer, p_sequencer.usb_xfer_seqr[0])
  endtask
endclass
