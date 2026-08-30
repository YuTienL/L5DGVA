class usb_env extends uvm_env;
  `uvm_component_utils(usb_env)
  usb_config cfg;
  usb_virtual_sequencer vseqr;
  usb_scoreboard sb;
  usb_coverage cov;
  usb_clk_rst_agent clk_rst_agent;
  usb_sideband_agent sideband_agent;
  svt_usb_agent usb_host_agent[2];
  svt_apb_system_env apb_env;
  svt_axi_system_env axi_env;
  svt_usb_agent usb_mon_agent[2];
  svt_axi_system_env dma_env;
  usb_reg_sequencer reg_seqr;

  function new(string name="usb_env", uvm_component parent=null); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if(!uvm_config_db#(usb_config)::get(this,"","cfg",cfg))
      cfg=usb_config::type_id::create("cfg");
    vseqr=usb_virtual_sequencer::type_id::create("vseqr",this);
    sb=usb_scoreboard::type_id::create("sb",this);
    cov=usb_coverage::type_id::create("cov",this);
    // no depends_on
    clk_rst_agent=usb_clk_rst_agent::type_id::create("clk_rst_agent",this);
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
    // after host_agent (depends_on)
    for (int p = 0; p < 2; p++) begin
      usb_mon_agent[p] = svt_usb_agent::type_id::create($sformatf("usb_mon_agent_%0d", p), this);
    end
    // after axi_env (depends_on)
    dma_env=svt_axi_system_env::type_id::create("dma_env",this);
    // after apb_env, axi_env (depends_on)
    reg_seqr=usb_reg_sequencer::type_id::create("reg_seqr",this);
  endfunction
endclass
