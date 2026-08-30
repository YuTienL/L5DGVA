class usb_env extends uvm_env;
  `uvm_component_utils(usb_env)
  usb_virtual_sequencer vseqr;
  usb_scoreboard sb;
  usb_coverage cov;
  virtual svt_usb_if usb_if[2];
  usb_clk_rst_agent clk_rst_agent;
`ifdef USB_UVM_DMA_MON
  usb_dma_cfg dma_cfg;
`endif
  usb_top_cfg cfg;
  svt_err_catcher err_catcher;
  usb_sideband_agent sideband_agent;
  svt_usb_agent usb_host_agent[2];
  svt_apb_system_env apb_env;
  svt_axi_system_env axi_env;
  svt_usb_system_virtual_sequencer sys_virt_seqr[2];
  usb_ep_check ep_check[2];
  usb_perf_monitor perf_mon[2];
  usb_xfer_scoreboard xfer_sb[2];
  usb_frame_util_monitor frame_util[2];
`ifdef USB_UVM_DMA_MON
  usb_dma_scoreboard dma_sb[2];
`endif
  svt_usb_agent usb_mon_agent[2];
  usb_payload_publish_cb payload_cb[2];
  svt_axi_system_env dma_env;
  usb_reg_sequencer reg_seqr;
`ifdef USB_UVM_DMA_MON
  usb_dma_ssmem_scoreboard ssmem_sb;
`endif
  usb_virtual_sequencer virt_seqr;

  function new(string name="usb_env", uvm_component parent=null); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    vseqr=usb_virtual_sequencer::type_id::create("vseqr",this);
    sb=usb_scoreboard::type_id::create("sb",this);
    cov=usb_coverage::type_id::create("cov",this);
    // no depends_on
    for (int p = 0; p < 2; p++) begin
      if (!uvm_config_db#(virtual svt_usb_if)::get(this, "", $sformatf("usb%0d_if", p), usb_if[p]))
        `uvm_fatal(get_type_name(), "virtual interface usb_if not found in config_db")
    end
    // no depends_on
    clk_rst_agent=usb_clk_rst_agent::type_id::create("clk_rst_agent",this);
`ifdef USB_UVM_DMA_MON
    // no depends_on
    dma_cfg=usb_dma_cfg::type_id::create("dma_cfg",this);
`endif
    // no depends_on
    cfg=usb_top_cfg::type_id::create("cfg",this);
    // no depends_on
    err_catcher = new({get_full_name(), ".err_catcher"});
    // after clk_rst_agent (depends_on)
    sideband_agent=usb_sideband_agent::type_id::create("sideband_agent",this);
    // after clk_rst_agent (depends_on)
    for (int p = 0; p < 2; p++) begin
      usb_host_agent[p] = svt_usb_agent::type_id::create($sformatf("usb_host_agent_%0d", p), this);
    end
    // after clk_rst_agent (depends_on)
    apb_env=svt_apb_system_env::type_id::create("apb_env",this);
    // after clk_rst_agent (depends_on)
    axi_env=svt_axi_system_env::type_id::create("axi_env",this);
    // after usb_top_cfg (depends_on)
    for (int p = 0; p < 2; p++) begin
      sys_virt_seqr[p] = svt_usb_system_virtual_sequencer::type_id::create($sformatf("sys_virt_seqr_%0d", p), this);
    end
    // after usb_top_cfg (depends_on)
    for (int p = 0; p < 2; p++) begin
      ep_check[p] = usb_ep_check::type_id::create($sformatf("ep_check_%0d", p), this);
    end
    // after usb_top_cfg (depends_on)
    for (int p = 0; p < 2; p++) begin
      perf_mon[p] = usb_perf_monitor::type_id::create($sformatf("perf_mon_%0d", p), this);
    end
    // after usb_top_cfg (depends_on)
    for (int p = 0; p < 2; p++) begin
      xfer_sb[p] = usb_xfer_scoreboard::type_id::create($sformatf("xfer_sb_%0d", p), this);
    end
    // after usb_top_cfg (depends_on)
    for (int p = 0; p < 2; p++) begin
      frame_util[p] = usb_frame_util_monitor::type_id::create($sformatf("frame_util_%0d", p), this);
    end
`ifdef USB_UVM_DMA_MON
    // after usb_top_cfg (depends_on)
    for (int p = 0; p < 2; p++) begin
      dma_sb[p] = usb_dma_scoreboard::type_id::create($sformatf("dma_sb_%0d", p), this);
    end
`endif
    // after host_agent (depends_on)
    for (int p = 0; p < 2; p++) begin
      usb_mon_agent[p] = svt_usb_agent::type_id::create($sformatf("usb_mon_agent_%0d", p), this);
    end
    // after host_agent (depends_on)
    for (int p = 0; p < 2; p++) begin
      payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);
    end
    // after axi_env (depends_on)
    dma_env=svt_axi_system_env::type_id::create("dma_env",this);
    // after apb_env, axi_env (depends_on)
    reg_seqr=usb_reg_sequencer::type_id::create("reg_seqr",this);
`ifdef USB_UVM_DMA_MON
    // after dma_env (depends_on)
    ssmem_sb=usb_dma_ssmem_scoreboard::type_id::create("ssmem_sb",this);
`endif
    // after host_agent, apb_env, axi_env, reg_seqr (depends_on)
    virt_seqr=usb_virtual_sequencer::type_id::create("virt_seqr",this);
  endfunction
  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    // evidence: usb_top_env.sv:472: if (apb_env != null) virt_seqr.apb_seqr = apb_env.master.sequencer; -- the `apb_env != null` guard is NOT reproduced (connections schema has no conditional-wrap support for a scalar entry); the emitted assignment is unconditional.
    virt_seqr.apb_seqr = apb_env.master.sequencer;
    // evidence: usb_top_env.sv:473: if (axi_env != null) virt_seqr.axi_seqr = axi_env.master[0].sequencer; -- same null-guard-dropped caveat as apb_seqr above. Real evidence for the asymmetric svt_apb_system_env.master (single agent) vs svt_axi_system_env.master[0] (queue) shape is usb_top_env.sv's own comment at lines 468-471, citing svt_apb_system_env.sv:31 / svt_axi_system_env.sv:49.
    virt_seqr.axi_seqr = axi_env.master[0].sequencer;
    // evidence: usb_top_env.sv:475: virt_seqr.reg_seqr = reg_seqr; -- unconditional in the real file too, no guard dropped here.
    virt_seqr.reg_seqr = reg_seqr;
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:461-465: for (int p = 0; p < NUM_USB_PORTS; p++) begin if (!cfg.enable_port[p]) continue; if (usb_host_agent[p] == null) continue; virt_seqr.usb_xfer_seqr[p] = usb_host_agent[p].xfer_sequencer; end -- BOTH continue-guards dropped; the connections schema's port_indexed wrap is a bare for-loop with one unconditional assignment, no conditional body.
      virt_seqr.usb_xfer_seqr[p] = usb_host_agent[p].xfer_sequencer;
    end
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:485-488: foreach (sys_virt_seqr[p]) begin if (usb_host_agent[p] != null && sys_virt_seqr[p] != null) sys_virt_seqr[p].host_virt_sequencer = usb_host_agent[p].virt_sequencer; end -- the double null-guard dropped, same schema limitation. svt_usb_agent declares virt_sequencer at svt_usb_agent.sv:1294 per the real file's own comment at lines 478-479.
      sys_virt_seqr[p].host_virt_sequencer = usb_host_agent[p].virt_sequencer;
    end
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:492-493: foreach (sys_virt_seqr[p]) if (virt_seqr != null) virt_seqr.usb_sys_seqr[p] = sys_virt_seqr[p]; -- the `virt_seqr != null` guard dropped. Real comment at lines 490-491: this is what usb_seq_launcher_seq::resolve_target looks in for 'vseq0'/'vseq1'.
      virt_seqr.usb_sys_seqr[p] = sys_virt_seqr[p];
    end
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:504-507: foreach (usb_host_agent[p]) begin if (usb_host_agent[p] != null) begin payload_cb[p] = new($sformatf("payload_cb_%0d", p), p); payload_cb[p].filter = usb_payload_publish_cb::OUT_ONLY; ... end end -- the `usb_host_agent[p] != null` guard dropped. The `payload_cb[p] = new(...)` construction itself is already modeled separately by this manifest's own payload_cb vip_components entry (kind=plain_object), not duplicated here. Real comment at lines 499-501: OUT_ONLY so an IN transfer cannot overwrite the record between a pattern sending a Bulk OUT and checking the device buffer -- the filter applies to PUBLICATION only.
      payload_cb[p].filter = usb_payload_publish_cb::OUT_ONLY;
    end
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:570-580: foreach (perf_mon[p]) begin if (perf_mon[p] == null) continue; if (payload_cb[p] == null) begin `uvm_warning(...); continue; end payload_cb[p].perf_mon = perf_mon[p]; ... end -- both continue-guards (and the warning they gate) dropped, same schema limitation. Real comment at lines 558-561: deliberately OUTSIDE the DMA_MON ifdef guard, so this wire is unconditional in the real file regardless of +define+USB_UVM_DMA_MON.
      payload_cb[p].perf_mon = perf_mon[p];
    end
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:585 (same foreach (perf_mon[p]) loop as payload_cb[p].perf_mon above, lines 570-586): perf_mon[p].agent = usb_host_agent[p]; -- same continue-guards dropped as the entry above. Real comment at lines 582-584: hands the monitor the agent so it can read the VIP's own performance figures, which live on svt_usb_agent.shared_status (svt_usb_agent.sv:1036), not on the agent configuration.
      perf_mon[p].agent = usb_host_agent[p];
    end
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:592-602: foreach (xfer_sb[p]) begin if (xfer_sb[p] == null) continue; if (payload_cb[p] == null) begin `uvm_warning(...); continue; end payload_cb[p].xfer_sb = xfer_sb[p]; end -- guards dropped, same schema limitation. Real comment at lines 588-591: same handle-assignment shape as perf_mon above, same reason (no analysis port to connect to); kept its own loop deliberately so a change to one does not require touching the other.
      payload_cb[p].xfer_sb = xfer_sb[p];
    end
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:609-619: foreach (frame_util[p]) begin if (frame_util[p] == null) continue; if (payload_cb[p] == null) begin `uvm_warning(...); continue; end payload_cb[p].frame_util = frame_util[p]; end -- guards dropped, same schema limitation. Real comment at lines 605-608: same handle-assignment shape as perf_mon/xfer_sb above, its own loop for the same isolation reason.
      payload_cb[p].frame_util = frame_util[p];
    end
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:504-506: foreach (usb_host_agent[p]) begin if (usb_host_agent[p] != null) begin payload_cb[p] = new($sformatf("payload_cb_%0d", p), p); ... end end -- kind="construct" per round-9 Multi-Agent Evidence Consensus; ctor_class=usb_payload_publish_cb resolved from the member's declared type at usb_top_env.sv:85 (usb_payload_publish_cb payload_cb [2];), confirmed by direct grep this pass. KNOWN DUPLICATION (see this manifest's own v9 evidence note): this same construction is ALSO already emitted in build_phase by this manifest's pre-existing payload_cb vip_components entry (kind=plain_object) -- adding it here per the consensus spec means payload_cb[p] is constructed twice in generated output, once per phase, unlike the real file's single connect_phase construction.
      if (usb_host_agent[p] != null) payload_cb[p] = new($sformatf("payload_cb_%0d", p), p);
    end
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:508: uvm_callbacks#(svt_usb_protocol)::add(usb_host_agent[p].prot, payload_cb[p]); -- same foreach(usb_host_agent[p])/if(usb_host_agent[p]!=null) guard as the construct entry above (lines 504-509). Not ifdef-guarded: line 508 sits above the `ifdef USB_UVM_DMA_MON` span, which starts at line 512 (verified directly this pass).
      if (usb_host_agent[p] != null) uvm_callbacks#(svt_usb_protocol)::add(usb_host_agent[p].prot, payload_cb[p]);
    end
`ifdef USB_UVM_DMA_MON
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:535: if (payload_cb[p] != null) payload_cb[p].dma_sb = dma_sb[p]; -- inside foreach(dma_sb[p]) (line 522), itself inside `ifdef USB_UVM_DMA_MON` (512-556). kind stays "assign" (default, omitted) -- the proof case that ifdef_macro is orthogonal to kind. dma_sb only exists under this same ifdef (see this manifest's own dma_sb vip_components entry); wiring it unconditionally (as v7/v8 were forced to omit this statement entirely to avoid) would be a real compile error in a build without +define+USB_UVM_DMA_MON. Closes the exact gap the v7 evidence notes flagged as 'genuine, currently-unclosed'.
      if (payload_cb[p] != null) payload_cb[p].dma_sb = dma_sb[p];
    end
`endif
`ifdef USB_UVM_DMA_MON
    for (int p = 0; p < 2; p++) begin
      // evidence: usb_top_env.sv:531: dma_env.master[p].monitor.item_observed_port.connect(dma_sb[p].dma_export); -- inside foreach(dma_sb[p]) (522), itself inside `ifdef USB_UVM_DMA_MON` (512-556). guard left empty: the dma_sb[p]==null / dma_env==null||p>=dma_env.master.size() checks at lines 523-530 are loop-plumbing continue-guards (with an uvm_error), not a runtime condition wrapping this one statement -- excluded from `guard` per the same convention already applied to every other port_indexed connections entry in this manifest.
      dma_env.master[p].monitor.item_observed_port.connect(dma_sb[p].dma_export);
    end
`endif
`ifdef USB_UVM_DMA_MON
    // evidence: usb_top_env.sv:550-552: if (ssmem_sb != null) begin if (dma_env != null && dma_env.master.size() > 0) dma_env.master[0].monitor.item_observed_port.connect(ssmem_sb.dma_export_p0); ... end -- inside `ifdef USB_UVM_DMA_MON` (512-556). The two nested real `if`s are AND-joined into one combined `if` per the generator's documented guard-rendering convention: the real source nests them around TWO SIBLING statements (this one and line 554) sharing one outer condition, but this schema models each statement independently, so AND-joining is the logically-equivalent per-statement rendering, not a literal transcription of the nested shape. Not port_indexed: dma_env.master[0] is one specific textual statement, not a loop body.
    if (ssmem_sb != null && dma_env != null && dma_env.master.size() > 0) dma_env.master[0].monitor.item_observed_port.connect(ssmem_sb.dma_export_p0);
`endif
`ifdef USB_UVM_DMA_MON
    // evidence: usb_top_env.sv:550,553-554: if (ssmem_sb != null) begin ... if (dma_env != null && dma_env.master.size() > 1) dma_env.master[1].monitor.item_observed_port.connect(ssmem_sb.dma_export_p1); end -- same AND-joining rationale and ifdef span as the master[0] entry above. Not port_indexed: dma_env.master[1] is the sibling statement to master[0], not a loop body.
    if (ssmem_sb != null && dma_env != null && dma_env.master.size() > 1) dma_env.master[1].monitor.item_observed_port.connect(ssmem_sb.dma_export_p1);
`endif
  endfunction
endclass
