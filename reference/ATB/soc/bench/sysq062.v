//=========================================================================
//File Name    : sysq062.v
//Author       : 
//Description  : system of dwaq062
//Parent Files : none
//Revision
//=========================================================================

//TODO: Include DV Testbench/*{{{*/
`ifdef DV_UVM
  `include "uvm_soc_tb.sv"
`endif
/*}}}*/

module sysq062();
wire   [11:0]  senif               ;
//bus signal declaration
wire   [26:0]  fmgpio              ;
wire   [18:0]  sfgpio              ;
wire   [ 5:0]  tggpio              ;
`ifdef V77P_DRAM
wire           cke                 ;
wire   [ 1:0]  odt, mcsnn          ;
wire   [19:0]  ma                  ;
wire   [31:0]  md                  ;
wire   [ 3:0]  dqm, dqs, dqsnn     ;
wire           sdclk               ;
wire           sdclknn             ;
`else
wire           ddr_clk     [1:0]   ;
wire           ddr_clk_n   [1:0]   ;
wire [1:0]     ddr_cke     [1:0]   ;
wire [1:0]     ddr_cs_n    [1:0]   ;
wire [6-1:0]   ddr_addr    [1:0]   ;
wire [7:0]     ddr_dq      [3:0]   ;
wire [3:0]     ddr_dqs             ;
wire [3:0]     ddr_dqs_n           ;
wire [3:0]     ddr_dqm             ;
wire           ddr_rst_n           ;
wire [3:0]     ddr_wck_t           ;  // LPDDR5 only
wire [3:0]     ddr_wck_c           ;  // LPDDR5 only
wire           ddr_zn              ;
wire           ddr_ato             ;
wire           ddr_dto             ;
`endif
wire   [ 8:0]  saradcio            = 0;
wire   [22:0]  pgpio               ;
wire   [17:0]  digtv               ;
wire   [28:0]  lmigpio             ;

wire   [ 2:0]  xhdmitmdsdatan      ;
wire   [ 2:0]  xhdmitmdsdatap      ;


//wire           xdphy_vref          ;
//assign xdphy_vref = 1'b0;

//-------------------------------------------------------------------------
// SDF for gate-level simulation
////`ifdef POSTSIM
////initial
////  begin
////   `ifdef FF_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/waq062_wo_wp2_hmv_cnn_mae_cpu_ffm40c.sdf.gz",sysq062.u_waq062,,"waq062_ff.log" ,"MAXIMUM",,"FROM_MTM");
////   `elsif SS_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/waq062_wo_wp2_hmv_cnn_mae_cpu_ssgm40c.sdf.gz",sysq062.u_waq062,,"waq062_ss.log" ,"MAXIMUM",,"FROM_MTM");
////   `else
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/waq062_wo_wp2_hmv_cnn_mae_cpu_tt25c.sdf.gz",sysq062.u_waq062,,"waq062_tt.log" ,"MAXIMUM",,"FROM_MTM");
////   `endif
////  end
////`endif
////
////`ifdef WP2_POSTSIM
////initial
////  begin
////   `ifdef FF_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/wp2_ffm40c.sdf.gz" ,sysq062.u_waq062.u_coreq062.u_wp2,,"wp2_ff.log" ,"MAXIMUM",,"FROM_MTM");
////   `elsif SS_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/wp2_ssgm40c.sdf.gz",sysq062.u_waq062.u_coreq062.u_wp2,,"wp2_ss.log" ,"MAXIMUM",,"FROM_MTM");
////   `else
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/wp2_tt25c.sdf.gz"  ,sysq062.u_waq062.u_coreq062.u_wp2,,"wp2_tt.log" ,"MAXIMUM",,"FROM_MTM");
////   `endif
////  end
////`endif
////
////`ifdef HVMTOP_POSTSIM
////initial
////  begin
////   `ifdef FF_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/hvmtop_ffm40c.sdf.gz" ,sysq062.u_waq062.u_coreq062.u_hvmtop,,"hvmtop_ff.log" ,"MAXIMUM",,"FROM_MTM");
////   `elsif SS_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/hvmtop_ssgm40c.sdf.gz",sysq062.u_waq062.u_coreq062.u_hvmtop,,"hvmtop_ss.log" ,"MAXIMUM",,"FROM_MTM");
////   `else
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/hvmtop_tt25c.sdf.gz"  ,sysq062.u_waq062.u_coreq062.u_hvmtop,,"hvmtop_tt.log" ,"MAXIMUM",,"FROM_MTM");
////   `endif
////  end
////`endif
////
////`ifdef CNNTOP_POSTSIM
////initial
////  begin
////   `ifdef FF_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/cnntop_ffm40c.sdf.gz" ,sysq062.u_waq062.u_coreq062.u_wpcnn.u_cnntop,,"cnntop_ff.log" ,"MAXIMUM",,"FROM_MTM");
////   `elsif SS_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/cnntop_ssgm40c.sdf.gz",sysq062.u_waq062.u_coreq062.u_wpcnn.u_cnntop,,"cnntop_ss.log" ,"MAXIMUM",,"FROM_MTM");
////   `else
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/cnntop_tt25c.sdf.gz"  ,sysq062.u_waq062.u_coreq062.u_wpcnn.u_cnntop,,"cnntop_tt.log" ,"MAXIMUM",,"FROM_MTM");
////   `endif
////  end
////`endif
////
////`ifdef MAETOP_POSTSIM
////initial
////  begin
////   `ifdef FF_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/maetop_ffm40c.sdf.gz" ,sysq062.u_waq062.u_coreq062.u_wp45.u_maetop,,"maetop_ff.log" ,"MAXIMUM",,"FROM_MTM");
////   `elsif SS_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/maetop_ssgm40c.sdf.gz",sysq062.u_waq062.u_coreq062.u_wp45.u_maetop,,"maetop_ss.log" ,"MAXIMUM",,"FROM_MTM");
////   `else
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/maetop_tt25c.sdf.gz"  ,sysq062.u_waq062.u_coreq062.u_wp45.u_maetop,,"maetop_tt.log" ,"MAXIMUM",,"FROM_MTM");
////   `endif
////  end
////`endif
////
////`ifdef CPUTOP_POSTSIM
////initial
////  begin
////   `ifdef FF_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/cputop_ffm40c.sdf.gz" ,sysq062.u_waq062.u_coreq062.u_cputop,,"cputop_ff.log" ,"MAXIMUM",,"FROM_MTM");
////   `elsif SS_CORNER
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/cputop_ssgm40c.sdf.gz",sysq062.u_waq062.u_coreq062.u_cputop,,"cputop_ss.log" ,"MAXIMUM",,"FROM_MTM");
////   `else
////     $sdf_annotate("/home/dwaq062/NETLIST_ES1/cputop_tt25c.sdf.gz"  ,sysq062.u_waq062.u_coreq062.u_cputop,,"cputop_tt.log" ,"MAXIMUM",,"FROM_MTM");
////   `endif
////  end
////`endif
////
////`ifdef DRAM_POSTSIM
////initial
////  begin
////   `ifdef FF_CORNER
////     $sdf_annotate("/home/dwaq062/IP/INNOSILICON/DDR_PHY/INNO_PKG_DDR3_4_LPDDR3_4_PRJ2412CCS1_S2412_U22ULP_V1P0_R20241218/FRONTEND/MODEL/postsim_model/netlist_sdf/sdf/inno_ddr_digtop.ff_cmin_m40_func.sdf",sysq062.u_waq062.u_coreq062.u_dramtop.u_ddr_chip.u_inno_ddr_phy.u_digitl,, "ddrphy_ff.log", "MAXIMUM",,"FROM_MTM");
////   `elsif SS_CORNER
////     $sdf_annotate("/home/dwaq062/IP/INNOSILICON/DDR_PHY/INNO_PKG_DDR3_4_LPDDR3_4_PRJ2412CCS1_S2412_U22ULP_V1P0_R20241218/FRONTEND/MODEL/postsim_model/netlist_sdf/sdf/inno_ddr_digtop.ss_cmax_m40_func.sdf",sysq062.u_waq062.u_coreq062.u_dramtop.u_ddr_chip.u_inno_ddr_phy.u_digitl,, "ddrphy_ss.log", "MAXIMUM",,"FROM_MTM");
////   `elsif TT_CORNER
////     $sdf_annotate("/home/dwaq062/IP/INNOSILICON/DDR_PHY/INNO_PKG_DDR3_4_LPDDR3_4_PRJ2412CCS1_S2412_U22ULP_V1P0_R20241218/FRONTEND/MODEL/postsim_model/netlist_sdf/sdf/inno_ddr_digtop.tt_typ_25_func.sdf"  ,sysq062.u_waq062.u_coreq062.u_dramtop.u_ddr_chip.u_inno_ddr_phy.u_digitl,, "ddrphy_tt.log", "MAXIMUM",,"FROM_MTM");
////   `endif
////  end
////`endif
////
////`ifdef PATTERN
////  `ifdef ES3
////    `include "/home/dwaq062/TESTSIM_GSI_ES3/waq062mon_rtl.v"
////  `elsif ES2
////    `include "/home/dwaq062/TESTSIM_GSI_ES2/waq062mon_rtl.v"
////  `else
////    `include "/home/dwaq062/TESTSIM_GSI_ES1/waq062mon_rtl.v"
////  `endif
////`endif
////
////
////`ifdef PRESIM
////  `include "/home/dwaq062/PRESIM/force.txt"
////`endif
////
////`ifdef POSTSIM
////  `include "/home/dwaq062/POSTSIM/force.txt"
////`endif

`include "ASSERT_INFO.v"
`define ASSERT_INFO sysq062.ASSERT_INFO

//-------------------------------------------------------------------------
modq062 u_modq062(
  .xprstn              (xprstn              ),
  .xtrap               (xtrap               ),
  .xtali               (xtali               ),
  .xtalo               (xtalo               ),
  .xtestmode           (xtestmode           ),
//  .xtalrtci            (xtalrtci            ),
//  .xtalrtco            (xtalrtco            ),
//  .pwron0              (pwron0              ),
//  .pwron1              (pwron1              ),
//  .pwron2              (pwron2              ),
//  .pwron3              (pwron3              ),
//  .pwron4              (pwron4              ),
//  .dc2dc_en            (dc2dc_en0           ),
//  .bat_fb              (bat_fb              ),
//  .dc2dc_fb            (dc2dc_fb            ),
//  .fuse_pad0           (fuse_pad0           ),
//  .fuse_pad1           (fuse_pad1           ),
//  .fuse_pad2           (fuse_pad2           ),
`ifdef V77P_DRAM
  .mrstnn              (mrstnn              ),
  .sdclk               (sdclk               ),
  .sdclknn             (sdclknn             ),
  .cke                 (cke                 ),
  .odt                 (odt                 ),
  .mcsnn               (mcsnn               ),
  .rasnn               (rasnn               ),
  .casnn               (casnn               ),
  .mwenn               (mwenn               ),
  .ma                  (ma                  ),
  .dqs                 (dqs                 ),
  .dqsnn               (dqsnn               ),
  .dqm                 (dqm                 ),
  .md                  (md                  ),
`else
/*inout wire          */ .ddr_clk     /*[0:1]*/ (ddr_clk     ),  // [0]-> dfi0     [1]-> dfi1       bp_dfi0_ck_c_0
/*inout wire          */ .ddr_clk_n   /*[0:1]*/ (ddr_clk_n   ),  // [0]-> dfi0     [1]-> dfi1       bp_dfi0_ck_c_0
/*inout wire [1:0]    */ .ddr_cke     /*[0:1]*/ (ddr_cke     ),  // [0]-> dfi0     [1]-> dfi1       bp_dfi0_lp4cke_lp5cs_0[1:0]
/*inout wire [1:0]    */ .ddr_cs_n    /*[0:1]*/ (ddr_cs_n    ),  // [0]-> dfi0     [1]-> dfi1       bp_dfi0_ca_0[7:6]
/*inout wire [6-1:0]  */ .ddr_addr    /*[0:1]*/ (ddr_addr    ),  // [0]-> dfi0     [1]-> dfi1       bp_dfi0_ca_0[5:0]   // lpddr4: 6 bit
/*inout  wire [7:0]   */ .ddr_dq      /*[0:3]*/ (ddr_dq      ),  // [7:0][0]-> bp_dfi0_b0  [7:0][1]-> bp_dfi0_b1   [7:0][2]-> bp_dfi1_b0    [7:0][3]-> bp_dfi1_b1
/*inout  wire [3:0]   */ .ddr_dqs     /*     */ (ddr_dqs     ),  // [0]-> bp_dfi0_b0      [1]-> bp_dfi0_b1       [3]-> bp_dfi1_b1         [2]-> bp_dfi1_b0
/*inout  wire [3:0]   */ .ddr_dqs_n   /*     */ (ddr_dqs_n   ),  // [0]-> bp_dfi0_b0      [1]-> bp_dfi0_b1       [3]-> bp_dfi1_b1         [2]-> bp_dfi1_b0
/*inout  wire [3:0]   */ .ddr_dqm     /*     */ (ddr_dqm     ),  // [0]-> bp_dfi0_b0      [1]-> bp_dfi0_b1       [3]-> bp_dfi1_b1         [2]-> bp_dfi1_b0
/*inout  wire         */ .ddr_rst_n   /*     */ (ddr_rst_n   ),
/*inout  wire [3:0]   */ .ddr_wck_t             (ddr_wck_t   ),  // LPDDR5 only
/*inout  wire [3:0]   */ .ddr_wck_c             (ddr_wck_c   ),  // LPDDR5 only



`endif
//  .fmgpio              (fmgpio              ),
//  .digtv               (digtv               ),
//  .lmigpio             (lmigpio             ),
  .perigpio            (pgpio               ),
  .sfgpio              (sfgpio              ),
//
//  .usbdev_dm           (usbdev_dm           ),
//  .usbdev_dp           (usbdev_dp           ),
//  .usbdev_rext         (usbdev_rext         ),
//  .usbhost_dm          (usbhost_dm          ),
//  .usbhost_dp          (usbhost_dp          ),
//  .usbhost_rext        (usbhost_rext        ),
//`ifdef M31ATPG
//  .xusbdev_sstxa1      (xusbdev_sstxa1      ),
//  .xusbdev_sstxb1      (xusbdev_sstxb1      ),
//  .xusbdev_ssrxa1      (xusbdev_ssrxa1      ),
//  .xusbdev_ssrxb1      (xusbdev_ssrxb1      ),
//  .xusbdev_sstxa2      (xusbdev_sstxa2      ),
//  .xusbdev_sstxb2      (xusbdev_sstxb2      ),
//  .xusbdev_ssrxa2      (xusbdev_ssrxa2      ),
//  .xusbdev_ssrxb2      (xusbdev_ssrxb2      ),
//
//  .xusbhost_sstxa1     (xusbhost_sstxa1     ),
//  .xusbhost_sstxb1     (xusbhost_sstxb1     ),
//  .xusbhost_ssrxa1     (xusbhost_ssrxa1     ),
//  .xusbhost_ssrxb1     (xusbhost_ssrxb1     ),
//  .xusbhost_sstxa2     (xusbhost_sstxa2     ),
//  .xusbhost_sstxb2     (xusbhost_sstxb2     ),
//  .xusbhost_ssrxa2     (xusbhost_ssrxa2     ),
//  .xusbhost_ssrxb2     (xusbhost_ssrxb2     ),
//`endif
//  .usbin               (usbin               ),
//
//  .saragndref          (saragndref          ),
//  .sarvbg              (sarvbg              ),
//  .sarvref             (sarvref             ),
//  .sarbin0             (sarbin0             ),
//  .sarbin1             (sarbin1             ),
//  .sarbin6             (sarbin6             ),
//  .sarbin7             (sarbin7             ),
//  .sarbin8             (sarbin8             ),
//  .tpxp                (tpxp                ),
//  .tpxn                (tpxn                ),
//  .tpyp                (tpyp                ),
//  .tpyn                (tpyn                ),
  .tggpio              (tggpio              ),
//  .mclk                (mclk                ),
//  .flash               (flash               ),
//  .mshutter            (mshutter            ),
//  .hd                  (hd                  ),
//  .vd                  (vd                  ),
//  .sen1                (sen1                ),
//  .sck                 (sck                 ),
//  .sdo                 (sdo                 ),
//  .sdi                 (sdi                 ),
//  .senif               (senif               ),

  .endmarker           (                    )
);

//-------------------------------------------------------------------------
//pulldown u_xzq (xzq);

//supply1        xddrVREF      ;

waq062 u_waq062(
/*inout  wire         */         .xtestmode           (xtestmode           ),
/*inout  wire         */         .xprstn              (xprstn              ),
/*inout  wire         */         .xtrap               (xtrap               ),
/*inout  wire         */         .xtali               (xtali               ),
/*inout  wire         */         .xtalo               (xtalo               ),
                                 .xpvtio              (                    ),
//PGPIO interface-------------------------------------------------------------
                                 .saradcio            (saradcio            ),
                                 .xpgpio              (pgpio               ),
//FMGPIO interface
/*inout  wire [`FMIO_N-1:0]*/    .xfmgpio             (                    ),
//====================== SD IO ====================================
/*inout  wire         */         .sd_dat0             (),
/*inout  wire         */         .sd_dat1             (),
/*inout  wire         */         .sd_dat2             (),
/*inout  wire         */         .sd_dat3             (),
/*inout  wire         */         .sd_dat4             (),
/*inout  wire         */         .sd_dat5             (),
/*inout  wire         */         .sd_dat6             (),
/*inout  wire         */         .sd_dat7             (),
/*inout  wire         */         .sd_datstrb          (),
/*inout  wire         */         .sd_rst_n            (),
/*inout  wire         */         .sd_cmd              (),
/*inout  wire         */         .sd_sdoclk           (),
///*inout  wire         */         .sd_sd_carddt        (),
///*inout  wire         */         .sd_sd_wp            (),
//Senor interface-------------------------------------------------------------
/*inout  wire [XSENIF_N-1:0]*/   .xsenif              (senif               ),
                                 .xsenmclk            (                    ),
                                 .xtggpio             (tggpio              ),
//SS_SF interface-------------------------------------------------------------
                                 .xsfgpio             (sfgpio              ),
//SS_VOUT interface-------------------------------------------------------------
/*inout  wire               */   .vout_ref_clk_p        (                    ),
/*inout  wire               */   .vout_ref_clk_m        (                    ),
/*inout  wire               */   .vout_sink_hpd         (                    ), // DPTX hot plug
/*inout  wire    [    11:0] */   .vout_xlcdif           (                    ),
/*inout  wire               */   .vout_dp0_a0           (                    ),
/*inout  wire               */   .vout_dn0_b0           (                    ),
/*inout  wire               */   .vout_dp1_c0           (                    ),
/*inout  wire               */   .vout_dn1_c1           (                    ),
/*inout  wire               */   .vout_ckn_b1           (                    ),
/*inout  wire               */   .vout_ckp_a1           (                    ),
/*inout  wire               */   .vout_dp2_a2           (                    ),
/*inout  wire               */   .vout_dn2_b2           (                    ),
/*inout  wire               */   .vout_dp3_c2           (                    ),
/*inout  wire               */   .vout_dn3              (                    ),
/*inout  wire               */   .vout_atb              (                    ),
/*inout  wire               */   .vout_rext             (                    ),
/*inout  wire               */   .vout_AUX_PADP         (                    ),
/*inout  wire               */   .vout_AUX_PADN         (                    ),
///*inout  wire               */   .vout_phy0_atb_f_p     (                    ),
///*inout  wire               */   .vout_phy0_atb_s_m     (                    ),
///*inout  wire               */   .vout_phy0_atb_s_p     (                    ),
/*inout  wire               */   .vout_phy_resref       (                    ),
/*output wire               */   .vout_phy_tx0_m        (                    ),
/*output wire               */   .vout_phy_tx0_p        (                    ),
/*output wire               */   .vout_phy_tx3_m        (                    ),
/*output wire               */   .vout_phy_tx3_p        (                    ),
/*inout  wire               */   .vout_phy_txrx1_m      (                    ),
/*inout  wire               */   .vout_phy_txrx1_p      (                    ),
/*inout  wire               */   .vout_phy_txrx2_m      (                    ),
/*inout  wire               */   .vout_phy_txrx2_p      (                    ),
//====================== USB2.0 IO ==============================
/*inout    wire             */  .usb_dp               (),
/*inout    wire             */  .usb_dm               (),
//====================== USB3.1 IO ==============================
/*input    wire              */ .usb_refclk_p         (1'b0), // PHY Low-Swing differential input clock pair with pad
/*input    wire              */ .usb_refclk_m         (1'b0), // PHY Low-Swing differential input clock pair with pad
/*output   wire  [      1:0] */ .usb_tx_m             (), // usb3.1 phy IO for eDP
/*output   wire  [      1:0] */ .usb_tx_p             (), // usb3.1 phy IO for eDP
/*inout    wire  [      2:1]*/  .usb_txrx_m           (), // usb3.1 phy IO for USB or eDP
/*inout    wire  [      2:1]*/  .usb_txrx_p           (), // usb3.1 phy IO for USB or eDP
/*inout    wire             */  .usb_phy_resref       (),
//====================== MAC(Ethernet) IO =======================
/*inout   wire [`ENIO_N-1:0]*/  .xegpio                  (),
//====================== UCIe IO ================================
/*inout    wire              */ .ucie0_RXCKSB            (),
/*inout    wire              */ .ucie0_RXDATASB          (),
/*inout    wire              */ .ucie0_TXCKSB            (),
/*inout    wire              */ .ucie0_TXDATASB          (),
/*inout    wire              */ .ucie0_TXCKP             (),
/*inout    wire              */ .ucie0_TXCKN             (),
/*inout    wire              */ .ucie0_TXTRK             (),
/*inout    wire              */ .ucie0_TXVLD             (),
/*inout    wire [`UCIO_N-1:0]*/ .ucie0_TXDATA            (),
/*inout    wire              */ .ucie0_RXCKP             (),
/*inout    wire              */ .ucie0_RXCKN             (),
/*inout    wire              */ .ucie0_RXTRK             (),
/*inout    wire              */ .ucie0_RXVLD             (),
/*inout    wire [`UCIO_N-1:0]*/ .ucie0_RXDATA            (),
`ifdef EMUL_UCIE
/*inout    wire              */ .ucie1_RXCKSB            (),
/*inout    wire              */ .ucie1_RXDATASB          (),
/*inout    wire              */ .ucie1_TXCKSB            (),
/*inout    wire              */ .ucie1_TXDATASB          (),
/*inout    wire              */ .ucie1_TXCKP             (),
/*inout    wire              */ .ucie1_TXCKN             (),
/*inout    wire              */ .ucie1_TXTRK             (),
/*inout    wire              */ .ucie1_TXVLD             (),
/*inout    wire [`UCIO_N-1:0]*/ .ucie1_TXDATA            (),
/*inout    wire              */ .ucie1_RXCKP             (),
/*inout    wire              */ .ucie1_RXCKN             (),
/*inout    wire              */ .ucie1_RXTRK             (),
/*inout    wire              */ .ucie1_RXVLD             (),
/*inout    wire [`UCIO_N-1:0]*/ .ucie1_RXDATA            (),
`endif
//====================== PCIe IO ================================
/*inout    wire             */  .pcie_refclk_m        (), // PCIE_DM0_PHY0_REF_PAD_CLK_M
/*inout    wire             */  .pcie_refclk_p        (), // PCIE_DM0_PHY0_REF_PAD_CLK_P
/*inout    wire             */  .pcie_resref          (), // PCIE_DM0_PHY_RESREF
/*inout    wire             */  .pcie_rx0_m           (), // PCIE_DM0_PHY_RX0_M
/*inout    wire             */  .pcie_rx0_p           (), // PCIE_DM0_PHY_RX0_P
/*inout    wire             */  .pcie_rx1_m           (), // PCIE_DM0_PHY_RX1_M
/*inout    wire             */  .pcie_rx1_p           (), // PCIE_DM0_PHY_RX1_P
/*inout    wire             */  .pcie_rx2_m           (), // PCIE_DM0_PHY_RX2_M
/*inout    wire             */  .pcie_rx2_p           (), // PCIE_DM0_PHY_RX2_P
/*inout    wire             */  .pcie_rx3_m           (), // PCIE_DM0_PHY_RX3_M
/*inout    wire             */  .pcie_rx3_p           (), // PCIE_DM0_PHY_RX3_P
/*inout    wire             */  .pcie_tx0_m           (), // PCIE_DM0_PHY_TX0_M
/*inout    wire             */  .pcie_tx0_p           (), // PCIE_DM0_PHY_TX0_P
/*inout    wire             */  .pcie_tx1_m           (), // PCIE_DM0_PHY_TX1_M
/*inout    wire             */  .pcie_tx1_p           (), // PCIE_DM0_PHY_TX1_P
/*inout    wire             */  .pcie_tx2_m           (), // PCIE_DM0_PHY_TX2_M
/*inout    wire             */  .pcie_tx2_p           (), // PCIE_DM0_PHY_TX2_P
/*inout    wire             */  .pcie_tx3_m           (), // PCIE_DM0_PHY_TX3_M
/*inout    wire             */  .pcie_tx3_p           (), // PCIE_DM0_PHY_TX3_P
//DRAM interface--------------------------------------------------------------
`ifdef V77P_DRAM
/*inout  wire         */         .xddr_rst_n          (mrstnn              ),
/*inout  wire         */         .xddr_clk            (sdclk               ),
/*inout  wire         */         .xddr_clk_n          (sdclknn             ),
/*inout  wire         */         .xddr_cke            (cke                 ),
/*inout  wire [ 1:0]  */         .xddr_odt            (odt                 ),
/*inout  wire [ 1:0]  */         .xddr_cs_n           (mcsnn               ),
/*inout  wire         */         .xddr_ras_n          (rasnn               ),
/*inout  wire         */         .xddr_cas_n          (casnn               ),
/*inout  wire         */         .xddr_we_n           (mwenn               ),
/*inout  wire [ 19:0] */         .xddr_ca             (ma[19:0]            ),
/*inout  wire [  3:0] */         .xddr_dqs            (dqs                 ),
/*inout  wire [  3:0] */         .xddr_dqs_n          (dqsnn               ),
/*inout  wire [  3:0] */         .xddr_dqm            (dqm                 ),
/*inout  wire [ 31:0] */         .xddr_dq             (md                  ),
/*inout  wire         */         .xddr_zq             (xzq                 )
`else
/*inout wire          */ .ddr_clk     /*[0:1]*/ (ddr_clk     ),  // [0]-> dfi0     [1]-> dfi1       bp_dfi0_ck_c_0
/*inout wire          */ .ddr_clk_n   /*[0:1]*/ (ddr_clk_n   ),  // [0]-> dfi0     [1]-> dfi1       bp_dfi0_ck_c_0
/*inout wire [1:0]    */ .ddr_cke     /*[0:1]*/ (ddr_cke     ),  // [0]-> dfi0     [1]-> dfi1       bp_dfi0_lp4cke_lp5cs_0[1:0]
/*inout wire [1:0]    */ .ddr_cs_n    /*[0:1]*/ (ddr_cs_n    ),  // [0]-> dfi0     [1]-> dfi1       bp_dfi0_ca_0[7:6]
/*inout wire [6-1:0]  */ .ddr_addr    /*[0:1]*/ (ddr_addr    ),  // [0]-> dfi0     [1]-> dfi1       bp_dfi0_ca_0[5:0]   // lpddr4: 6 bit
/*inout  wire [7:0]   */ .ddr_dq      /*[0:3]*/ (ddr_dq      ),  // [7:0][0]-> bp_dfi0_b0  [7:0][1]-> bp_dfi0_b1   [7:0][2]-> bp_dfi1_b0    [7:0][3]-> bp_dfi1_b1
/*inout  wire [3:0]   */ .ddr_dqs     /*     */ (ddr_dqs     ),  // [0]-> bp_dfi0_b0      [1]-> bp_dfi0_b1       [3]-> bp_dfi1_b1         [2]-> bp_dfi1_b0
/*inout  wire [3:0]   */ .ddr_dqs_n   /*     */ (ddr_dqs_n   ),  // [0]-> bp_dfi0_b0      [1]-> bp_dfi0_b1       [3]-> bp_dfi1_b1         [2]-> bp_dfi1_b0
/*inout  wire [3:0]   */ .ddr_dqm     /*     */ (ddr_dqm     ),  // [0]-> bp_dfi0_b0      [1]-> bp_dfi0_b1       [3]-> bp_dfi1_b1         [2]-> bp_dfi1_b0
/*inout  wire         */ .ddr_rst_n   /*     */ (ddr_rst_n   ),
/*inout  wire [3:0]   */ .ddr_wck_t             (ddr_wck_t   ),  // LPDDR5 only
/*inout  wire [3:0]   */ .ddr_wck_c             (ddr_wck_c   ),  // LPDDR5 only
/*inout wire          */ .ddr_zn                (ddr_zn      ),
/*inout wire          */ .ddr_ato               (ddr_ato     ),
/*inout wire          */ .ddr_dto               (ddr_dto     )
`endif
//  .xprstn              (prstnn              ), //LUJ061 IF
//  .xtrap               (trap                ), //LUJ061 IF
//  .xtali               (xtali               ), //LUJ061 IF
//  .xtalo               (xtalo               ), //LUJ061 IF
//  .xtestm              (testmode            ), //LUJ061 IF
//  .xbat_fb             (bat_fb              ), //LUJ061 IF
//  .xtalrtci            (xtalrtci            ), //LUJ061 IF
//  .xtalrtco            (xtalrtco            ), //LUJ061 IF
//  .xpwron0             (pwron0              ), //LUJ061 IF
//  .xpwron1             (pwron1              ), //LUJ061 IF
//  .xpwron2             (pwron2              ), //LUJ061 IF
//  .xpwron3             (pwron3              ), //LUJ061 IF
//  .xpwron4             (pwron4              ), //LUJ061 IF
//  .xdc2dc_en0          (dc2dc_en0           ), //LUJ061 IF
//  .xdc2dc_en1          (dc2dc_en1           ), //LUJ061 IF
//  .xddr_rst_b          (mrstnn              ), //LUJ061 IF
//  .xddr_ck             (sdclk               ), //LUJ061 IF
//  .xddr_ckb            (sdclknn             ), //LUJ061 IF
//  .xddr_cke            (cke                 ), //LUJ061 IF
//  .xddr_odt            (odt                 ), //LUJ061 IF
//  .xddr_cs             (mcsnn               ), //LUJ061 IF
//  .xddr_ras            (rasnn               ), //LUJ061 IF
//  .xddr_cas            (casnn               ), //LUJ061 IF
//  .xddr_we             (mwenn               ), //LUJ061 IF
//  .xddr_a              (ma[15:0]            ), //LUJ061 IF
//  .xddr_bgba           (ma[19:16]           ), //LUJ061 IF
//  .xddr_dqs            (dqs                 ), //LUJ061 IF
//  .xddr_dqsb           (dqsnn               ), //LUJ061 IF
//  .xddr_dm             (dqm                 ), //LUJ061 IF
//  .xddr_dq             (md                  ), //LUJ061 IF
//  .xddr_pzq            (xzq                 ), //LUJ061 IF
//  .xddr_vref           (xddrVREF            ), //LUJ061 IF
//  .xfmif               (fmgpio              ), //LUJ061 IF

//  .xmgpio              (mgpio               ), //LUJ061 IF
//  .xlcdif              (                    ), //LUJ061 IF
//  .xegpio              (                    ), //LUJ061 IF
//  .xck32k              (                    ), //LUJ061 IF
//  .xpir_vref           (                    ), //LUJ061 IF
//  .xpwrc_ldoout        (                    ), //LUJ061 IF
//  .xusbdev_dm          (usbdev_dm           ), //LUJ061 IF
//  .xusbdev_dp          (usbdev_dp           ), //LUJ061 IF
//  .xusbdev_cc_0        (xusbdev_cc_0        ), //LUJ061 IF
//  .xusbdev_cc_1        (xusbdev_cc_1        ), //LUJ061 IF
//  .xusbdev_sstxa1      (xusbdev_sstxa1      ), //LUJ061 IF
//  .xusbdev_sstxb1      (xusbdev_sstxb1      ), //LUJ061 IF
//  .xusbdev_ssrxa1      (xusbdev_ssrxa1      ), //LUJ061 IF
//  .xusbdev_ssrxb1      (xusbdev_ssrxb1      ), //LUJ061 IF
//  .xusbdev_sstxa2      (xusbdev_sstxa2      ), //LUJ061 IF
//  .xusbdev_sstxb2      (xusbdev_sstxb2      ), //LUJ061 IF
//  .xusbdev_ssrxa2      (xusbdev_ssrxa2      ), //LUJ061 IF
//  .xusbdev_ssrxb2      (xusbdev_ssrxb2      ), //LUJ061 IF
//  .xusbhost_sstxa1     (xusbhost_sstxa1     ), //LUJ061 IF
//  .xusbhost_sstxb1     (xusbhost_sstxb1     ), //LUJ061 IF
//  .xusbhost_ssrxa1     (xusbhost_ssrxa1     ), //LUJ061 IF
//  .xusbhost_ssrxb1     (xusbhost_ssrxb1     ), //LUJ061 IF
//  .xusbhost_sstxa2     (xusbhost_sstxa2     ), //LUJ061 IF
//  .xusbhost_sstxb2     (xusbhost_sstxb2     ), //LUJ061 IF
//  .xusbhost_ssrxa2     (xusbhost_ssrxa2     ), //LUJ061 IF
//  .xusbhost_ssrxb2     (xusbhost_ssrxb2     ), //LUJ061 IF
//  .xusbhost_dp         (xusbhost_dp         ), //LUJ061 IF
//  .xusbhost_dm         (xusbhost_dm         ), //LUJ061 IF
//  .xusbhost_cc_0       (xusbhost_cc_0       ), //LUJ061 IF
//  .xusbhost_cc_1       (xusbhost_cc_1       ), //LUJ061 IF
//  .xusb_in             (usbin               ), //LUJ061 IF
//                                               //LUJ061 IF
//  .xsarin0             (sarbin0             ), //LUJ061 IF
//  .xsarin1             (sarbin1             ), //LUJ061 IF
//  .xsarin2             (tpxp                ), //LUJ061 IF
//  .xsarin3             (tpxn                ), //LUJ061 IF
//  .xsarin4             (tpyp                ), //LUJ061 IF
//  .xsarin5             (tpyn                ), //LUJ061 IF
//  .xsarin6             (                    ), //LUJ061 IF
//  .xtggpio             (tggpio              ), //LUJ061 IF
//  .xsenif              (senif               ), //LUJ061 IF
//  .xsdldo_out          (                    ), //LUJ061 IF
//  .xsenmclk            (mclk                ), //LUJ061 IF
//                                               //LUJ061 IF
//  .xtx_lppr            ()                      //LUJ061 IF

);

`ifndef DV_UVM
 `include "command.txt"
`endif

endmodule
