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
endclass
