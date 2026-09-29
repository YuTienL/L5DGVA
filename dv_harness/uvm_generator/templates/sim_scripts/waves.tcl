#=============================================================================
# waves.tcl -- Verdi signal setup for a target-IP UVM environment
#
# GENERIC TEMPLATE NOTE: this file is a protocol-agnostic Verdi setup
# grouped by the QUESTION each group answers (per IP_UVM_DV_Gen.md Step 9),
# copied from this template's original USB proving-ground project. The
# GROUPING STRUCTURE (bring-up, bridges, register bus, DMA bus, pads, VIP
# interfaces, controller/link state, interrupts) generalizes to any
# protocol; the literal hierarchical signal paths inside each group are a
# real worked EXAMPLE from that USB project's own DUT and must be
# re-derived from the CURRENT DUT's own RTL (Step 3 evidence rules apply
# here too -- do not assume a path carries over from a different chip).
# TARGET_IP/IP_PREFIX below follow the same vocabulary as the Makefile.
#
# Loaded by  make verdi PATTERN=<n>  /  make debug PATTERN=<n>
# as         verdi ... -play waves.tcl
#
# Manually:  verdi -dbdir <simv>.daidir -ssf <pattern>.fsdb -play waves.tcl &
#
# NOT -sswr. -sswr's own documented meaning (verdi -h) is "Load waveform
# restore file(s) (*.rc)" -- a different, non-Tcl internal grammar. Verdi
# opened with -sswr on this file (proc/set/foreach/wvCreateGroup/wvSetMarker)
# parses every line through that grammar instead and reports "Unrecognized
# keyword" on every single statement (confirmed live, 2026-08-25) -- this file
# had silently never loaded through `make verdi`/`make debug` until that flag
# was fixed in sim/scripts/Makefile's WAVES_TCL. -play (aka -script) is what
# actually sources a real Tcl script.
#
#-----------------------------------------------------------------------------
# WHY THIS FILE EXISTS
#
# The first useful question in this environment is almost never "what is this
# one signal doing". It is one of:
#
#   Did the Verilog side even reach UVM?          -> group 2, the bridges
#   Did the register write land on the bus?       -> group 3, APB
#   Did the DUT come out of reset with a clock?   -> group 1, SoC
#   Is there anything at all on the target-IP pads? -> group 5, and see A2 below
#   Did the link train?                           -> group 7, LTSSM
#
# Each group below answers one of those, in the order you would ask them.
# Loading all of them at once is deliberate: the failure mode of this
# environment is usually a stage that never started, and that is visible as a
# flat trace in one group while the group above it is busy.
#
#-----------------------------------------------------------------------------
# WHAT IS DELIBERATELY NOT HERE
#
# Nothing inside the UVM component tree. UVM components are heap objects
# created by run_test() after time 0; they are not in the design database and
# Verdi cannot see them (CLAUDE.md Sec.3.1 of docs/command-txt-uvm-migration).
# The bridge request slots in group 2 are the observable boundary -- they are
# real module-scope variables, so they DO appear, and they tell you which side
# of the boundary is stuck.
#
#-----------------------------------------------------------------------------
# SCOPE DEPENDS ON THE DUMP, NOT ON THIS FILE
#
# wave.txt dumps only the target-IP blocks by default. Groups 6 and 7 reach
# inside u_udc_usb31_top (this template's example DUT sub-block; re-derive
# the equivalent for the current DUT) and are covered by that default.
# Groups 3, 4 and 8 are at the lan063 level and need +fsdb_full:
#
#     make sim PATTERN=<n> WAVE=full
#
# A group whose signals were never dumped shows up in Verdi as red "not
# found" entries. That is not an error in this file -- it means the scope was
# too narrow for what you are asking.
#=============================================================================

#-----------------------------------------------------------------------------
# Protocol-target parameterization, same vocabulary as the Makefile
# (TARGET_IP/IP_PREFIX). Used below only for the bridge/bind instance names
# that follow THIS harness's own generated naming convention
# (<ip>_uvm_bind.sv etc, IP_UVM_DV_Gen.md Step 11) -- the DUT-side signal
# paths further down are real RTL facts from this template's original USB
# project and are NOT derived from these variables; re-derive them from the
# current DUT's own RTL.
#-----------------------------------------------------------------------------
set TARGET_IP "USB"
set IP_PREFIX "usb_"

#-----------------------------------------------------------------------------
# Paths. Change TB and DUT here rather than editing every line below.
#
# sysn063 is the SoC testbench top and is a DUT deliverable
# (MODEL/MODEL_ALL.v:157). Note the 'n': it is sysn063, not sys063.
#-----------------------------------------------------------------------------
set TB      "sysn063"
set DUT     "$TB.u_lan063"
set SSVOUT  "$DUT.u_ss_vout"
set BIND    "$TB.u_${IP_PREFIX}uvm_bind"
set APBARB  "$TB.u_${IP_PREFIX}apb_arb"
set LAUNCH  "$TB.u_${IP_PREFIX}seq_launcher"

# u_<ip>top is an array unless HAPS is defined, and vcs.opt does not define it
# (CLAUDE.md, DUT configuration). Set IPTOP_IDX to "" for a HAPS build.
# u_udc_usb31_top below is this template's original USB project's real
# per-instance sub-block name -- re-derive the equivalent for the current
# DUT/TARGET_IP.
set IPTOP_IDX0 "\[0\]"
set IPTOP_IDX1 "\[1\]"
set IP0     "$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX0.u_udc_usb31_top"
set IP1     "$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX1.u_udc_usb31_top"

#-----------------------------------------------------------------------------
# addGroup <name> <signal> ...
#
# Adds only the signals that exist in the loaded FSDB, and reports the ones
# that do not instead of failing. A missing signal here is almost always a
# dump-scope question (see above) or the HAPS index, and neither should stop
# the rest of the setup from loading.
#-----------------------------------------------------------------------------
set wv_missing {}

proc addGroup {gname args} {
    global wv_missing
    wvCreateGroup -name $gname
    set n 0
    foreach sig $args {
        if {[catch {wvAddSignal -win $::wv "$sig"} err]} {
            lappend wv_missing $sig
        } else {
            incr n
        }
    }
    if {$n == 0} {
        puts "\[waves.tcl\] group '$gname' is empty -- widen the dump scope with WAVE=full"
    }
}

#=============================================================================
# 1. SoC bring-up  --  "is the DUT even alive"
#
# xtali is the only clock UVM drives; everything else is generated inside the
# SoC. xprstn is ACTIVE LOW and is named xprstn, not xprst.
#
# These four are implicit wires created by the modn063 port connections
# (MODEL_ALL.v:357-361), so searching the file for a declaration finds
# nothing -- but the hierarchical path resolves.
#
# The PLL lock bits are what GLOBAL_INIT waits on. If they never rise, no USB
# clock is produced and everything below this group stays flat.
#=============================================================================
addGroup "1 SoC bringup" \
    "$TB.xtali" \
    "$TB.xprstn" \
    "$TB.xtrap" \
    "$TB.xtestmode" \
    "$DUT.u_gtop.u_ion063.u_plltop.spll0_mo_rdy_clk" \
    "$DUT.u_gtop.u_ion063.u_plltop.spll1_mo_rdy_clk" \
    "$DUT.bypasspll" \
    "$DUT.ss_vout_clki" \
    "$DUT.ss_vout_shdclki" \
    "$SSVOUT.usb0_clki" \
    "$SSVOUT.usb1_clki"

#=============================================================================
# 2. Verilog-to-UVM bridges  --  "did the pattern reach UVM at all"
#
# THIS IS THE GROUP TO LOOK AT FIRST when a pattern hangs or ends instantly.
#
#   bridge_ready / ready    0 forever  -> UVM never started. Check
#                                          +UVM_TESTNAME and that the bridge
#                                          sequences were started (usb_top_env)
#   req_posted with no matching req_done -> the request crossed and UVM never
#                                          answered; cur_owner / req_seq_name
#                                          names who is stuck
#   dv_uvm_pattern_done rising at t=0    -> the pattern returned immediately.
#                                          Traps 22 and 40 in CLAUDE.md
#   n_background non-zero at the end     -> FORK_SEQ without WAIT_SEQ_ALL
#=============================================================================
addGroup "2 Bridges (Verilog to UVM)" \
    "$TB.dv_uvm_pattern_done" \
    "$APBARB.bridge_ready" \
    "$APBARB.req_posted" \
    "$APBARB.req_done" \
    "$APBARB.req_write" \
    "$APBARB.req_addr" \
    "$APBARB.req_wdata" \
    "$APBARB.req_rdata" \
    "$APBARB.req_strb" \
    "$APBARB.cur_owner" \
    "$APBARB.n_write" \
    "$APBARB.n_read" \
    "$LAUNCH.ready" \
    "$LAUNCH.req_posted" \
    "$LAUNCH.req_done" \
    "$LAUNCH.req_seq_name" \
    "$LAUNCH.req_target" \
    "$LAUNCH.req_arg0" \
    "$LAUNCH.req_arg1" \
    "$LAUNCH.req_background" \
    "$LAUNCH.req_ok" \
    "$LAUNCH.n_background" \
    "$LAUNCH.n_launched"

#=============================================================================
# 3. APB register access  --  "did the write reach the bus"
#
# ss_cpu_m_p* is where the APB VIP forces. Every `CPUWRITE / `CPUREAD in every
# pattern, and every register access inside the 21 gmodel tasks, ends up here.
#
# paddr is 32-bit (TOP_ALL.v:23997), NOT CPU_APBAW=24, which is what makes
# 0x1270_0000 reachable at all.
#
# pslverr is tied to 1'b0 inside lan063 (TOP_ALL.v:25955), so it is here to
# confirm that -- not to catch errors. It cannot report one.
#
# Needs WAVE=full.
#=============================================================================
addGroup "3 APB (ss_cpu_m_p*)" \
    "$DUT.ss_cpu_m_pclk" \
    "$DUT.ss_cpu_m_psel" \
    "$DUT.ss_cpu_m_penable" \
    "$DUT.ss_cpu_m_pwrite" \
    "$DUT.ss_cpu_m_paddr" \
    "$DUT.ss_cpu_m_pwdata" \
    "$DUT.ss_cpu_m_prdata" \
    "$DUT.ss_cpu_m_pready" \
    "$DUT.ss_cpu_m_pslverr" \
    "$DUT.ss_cpu_m_pprot" \
    "$DUT.ss_cpu_m_pstrb"

# The per-port APB slave select, downstream of the apbsplit_rep decoder.
# usb0 is nibble 7 (0x1270_0000) and usb1 is nibble 8 (0x1280_0000);
# paddr is broadcast to all seven slaves and only psel differs, so THIS is
# the signal that says which port a given access actually went to.
addGroup "3b APB slave decode" \
    "$SSVOUT.ss_vout_m_psel" \
    "$SSVOUT.ss_vout_m_paddr" \
    "$SSVOUT.usb0_s_psel" \
    "$SSVOUT.usb0_s_penable" \
    "$SSVOUT.usb0_s_pready" \
    "$SSVOUT.usb1_s_psel" \
    "$SSVOUT.usb1_s_penable" \
    "$SSVOUT.usb1_s_pready"

#=============================================================================
# 4. AXI, the two buses  --  "our stimulus" versus "the DUT's DMA"
#
# These are NOT the same bus and the distinction matters:
#
#   ss_cpu_m_*  128-bit, forced by the AXI VIP. What appears here is the
#               pattern we wrote. An error means the testbench is wrong.
#   usb{0,1}_m_* 256-bit, driven by the DUT's own DMA engine. What appears
#               here is the design's behaviour. An error means the DESIGN is
#               wrong. This is the one worth verifying.
#
# CLAUDE.md trap 63. usb_dma_scoreboard subscribes to the second one.
# Needs WAVE=full.
#=============================================================================
addGroup "4 AXI cpu master (our stimulus, 128b)" \
    "$DUT.ss_cpu_aclk" \
    "$DUT.ss_cpu_m_awvalid" \
    "$DUT.ss_cpu_m_awready" \
    "$DUT.ss_cpu_m_awaddr" \
    "$DUT.ss_cpu_m_awlen" \
    "$DUT.ss_cpu_m_awsize" \
    "$DUT.ss_cpu_m_awburst" \
    "$DUT.ss_cpu_m_awuser" \
    "$DUT.ss_cpu_m_wvalid" \
    "$DUT.ss_cpu_m_wready" \
    "$DUT.ss_cpu_m_wlast" \
    "$DUT.ss_cpu_m_wstrb" \
    "$DUT.ss_cpu_m_bvalid" \
    "$DUT.ss_cpu_m_bresp" \
    "$DUT.ss_cpu_m_arvalid" \
    "$DUT.ss_cpu_m_araddr" \
    "$DUT.ss_cpu_m_rvalid" \
    "$DUT.ss_cpu_m_rlast" \
    "$DUT.ss_cpu_m_rresp"

addGroup "4b AXI usb DMA (the DUT, 256b)" \
    "$SSVOUT.usb0_m_awvalid" \
    "$SSVOUT.usb0_m_awready" \
    "$SSVOUT.usb0_m_awaddr" \
    "$SSVOUT.usb0_m_awlen" \
    "$SSVOUT.usb0_m_awsize" \
    "$SSVOUT.usb0_m_wvalid" \
    "$SSVOUT.usb0_m_wlast" \
    "$SSVOUT.usb0_m_wstrb" \
    "$SSVOUT.usb0_m_bresp" \
    "$SSVOUT.usb0_m_arvalid" \
    "$SSVOUT.usb0_m_araddr" \
    "$SSVOUT.usb0_m_rvalid" \
    "$SSVOUT.usb0_m_rlast" \
    "$SSVOUT.usb0_m_rresp" \
    "$SSVOUT.usb1_m_awvalid" \
    "$SSVOUT.usb1_m_awaddr" \
    "$SSVOUT.usb1_m_wvalid" \
    "$SSVOUT.usb1_m_arvalid" \
    "$SSVOUT.usb1_m_araddr" \
    "$SSVOUT.usb1_m_rvalid"

#=============================================================================
# 5. USB pads  --  "is there anything on the wire"
#
# THIS GROUP ANSWERS OPEN ITEM A2.
#
# Whether the SS PHY produces serial waveforms at all is still unproven, and
# it decides whether the testbench works at the serial layer or has to move
# to the PIPE layer -- for which there is no fallback (CLAUDE.md trap 1).
# If tx_p/tx_m stay flat through usb31_sscon while the controller is clearly
# running, that is the answer.
#
# wave.txt dumps sysn063 at depth 1 precisely so that these stay visible even
# if the PHY internals turn out to be encrypted and undumpable.
#
# dp/dm are wor and connected with tran; tx/rx are logic and connected with
# assign (CLAUDE.md trap 25).
#=============================================================================
addGroup "5 USB0 pads" \
    "$TB.xusb0_dp" \
    "$TB.xusb0_dm" \
    "$TB.xusb0_vbus0" \
    "$TB.xusb0_tx_p" \
    "$TB.xusb0_tx_m" \
    "$TB.xusb0_rx_p" \
    "$TB.xusb0_rx_m" \
    "$TB.xusb0_refclk_p" \
    "$TB.xusb0_refclk_m"

addGroup "5b USB1 pads" \
    "$TB.xusb1_dp" \
    "$TB.xusb1_dm" \
    "$TB.xusb1_vbus0" \
    "$TB.xusb1_tx_p" \
    "$TB.xusb1_tx_m" \
    "$TB.xusb1_rx_p" \
    "$TB.xusb1_rx_m"

#-----------------------------------------------------------------------------
# The VIP side of the same wires. Comparing this group against group 5 is how
# a polarity or lane-swap mistake becomes visible: the DUT transmits and the
# VIP receives nothing, or receives the inverse.
#
# A wrong LANE_SWAP / LANE_FLIP fails in EXACTLY the same way as A2 above
# (CLAUDE.md trap 2), so always read these two groups together before
# concluding the PHY is silent.
#-----------------------------------------------------------------------------
addGroup "5c VIP interfaces" \
    "$BIND.usb0_if.usb_20_serial_if.dp" \
    "$BIND.usb0_if.usb_20_serial_if.dm" \
    "$BIND.usb0_if.usb_20_serial_if.vbus" \
    "$BIND.usb0_if.usb_20_serial_if.clk" \
    "$BIND.usb0_if.usb_ss_serial_if.sstxp" \
    "$BIND.usb0_if.usb_ss_serial_if.sstxm" \
    "$BIND.usb0_if.usb_ss_serial_if.ssrxp" \
    "$BIND.usb0_if.usb_ss_serial_if.ssrxm" \
    "$BIND.usb0_if.usb_ss_serial_if.ssclk" \
    "$BIND.usb1_if.usb_20_serial_if.dp" \
    "$BIND.usb1_if.usb_20_serial_if.dm" \
    "$BIND.usb1_if.usb_ss_serial_if.sstxp" \
    "$BIND.usb1_if.usb_ss_serial_if.ssrxp" \
    "$BIND.ss0_clk_4x" \
    "$BIND.ss1_clk_4x" \
    "$BIND.usb20_clk_4x"

#=============================================================================
# 6. <ip>top wrapper  --  reset and PHY readiness
#
# phy0_sram_init_done is what every BFM pattern waits on before touching the
# controller. If it never rises, the controller registers are being written
# into a block that is still held in reset and every later step is
# meaningless.
#=============================================================================
addGroup "6 ${IP_PREFIX}top wrapper" \
    "$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX0.phy0_sram_init_done" \
    "$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX0.usb_rst_n" \
    "$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX0.usb_ref_pad_clk_p" \
    "$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX0.usb_ref_pad_clk_m" \
    "$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX1.phy0_sram_init_done" \
    "$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX1.usb_rst_n"

#=============================================================================
# 7. DWC_usb31 controller and link state  --  "did the link train"
#
# Reading order when a transfer times out on the host side:
#   link state    is the link in U0 / Configured?
#   ep enable     DALEPENA -- traps 52 and 53. 18 patterns had no DALEPENA at
#                 all before RunStop, and 6 more enabled only 0x3 while
#                 configuring data endpoints. Symptom: host-side timeout,
#                 no error message anywhere.
#   event ring    is the controller posting events the pattern never reads?
#
# These are inside the controller and covered by the default dump scope.
# Signal names below are the common DWC_usb31 internals; a build with
# different parameters may name them differently, in which case they appear
# in the missing list at the end and can be adjusted here.
#=============================================================================
addGroup "7 USB0 controller / link" \
    "$IP0.u_udc_DWC_usb31.ltssm_state" \
    "$IP0.u_udc_DWC_usb31.link_state" \
    "$IP0.u_udc_DWC_usb31.dev_speed" \
    "$IP0.u_udc_DWC_usb31.run_stop" \
    "$IP0.u_udc_DWC_usb31.dalepena" \
    "$IP0.u_udc_DWC_usb31.dev_addr" \
    "$IP0.u_udc_DWC_usb31.gevntcount" \
    "$IP0.u_udc_usb2_phy.utmi_linestate" \
    "$IP0.u_udc_usb2_phy.utmi_xcvrselect" \
    "$IP0.u_udc_usb2_phy.utmi_termselect" \
    "$IP0.u_udc_usb2_phy.utmi_opmode"

addGroup "7b USB1 controller / link" \
    "$IP1.u_udc_DWC_usb31.ltssm_state" \
    "$IP1.u_udc_DWC_usb31.link_state" \
    "$IP1.u_udc_DWC_usb31.dev_speed" \
    "$IP1.u_udc_DWC_usb31.run_stop" \
    "$IP1.u_udc_DWC_usb31.dalepena" \
    "$IP1.u_udc_usb2_phy.utmi_linestate"

#=============================================================================
# 8. Interrupts and error status
#
# usb_esmerr[0] is apb_chk_err and [1] is axi_chk_err. Nothing in the
# environment currently checks these -- open item D5 in
# docs/usb-uvm-port-analysis.md -- so watching them here is the only way they
# are seen at all.
#
# Needs WAVE=full.
#=============================================================================
addGroup "8 Interrupts and errors" \
    "$SSVOUT.usb0_irq" \
    "$SSVOUT.usb0_fiq" \
    "$SSVOUT.usb0_esmerr" \
    "$SSVOUT.usb0_cqintevt" \
    "$SSVOUT.usb1_irq" \
    "$SSVOUT.usb1_esmerr"

#=============================================================================
# Report what was not found, then fit the window.
#
# A long missing list with group 3, 4 or 8 in it means the dump scope was too
# narrow -- rerun with WAVE=full. A missing list confined to group 7 means the
# controller's internal signal names differ in this build; fix them here.
#=============================================================================
if {[llength $wv_missing] > 0} {
    puts ""
    puts "\[waves.tcl\] [llength $wv_missing] signal(s) not in this FSDB:"
    foreach s $wv_missing { puts "    $s" }
    puts ""
    puts "\[waves.tcl\] groups 3, 4 and 8 are at the lan063 level and need:"
    puts "               make sim PATTERN=<n> WAVE=full"
    puts "\[waves.tcl\] group 7 reaches inside the controller; adjust the names"
    puts "               near the end of waves.tcl if this build differs."
} else {
    puts "\[waves.tcl\] all signal groups loaded."
}

wvZoomAll -win $::wv
