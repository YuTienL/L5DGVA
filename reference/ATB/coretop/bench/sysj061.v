//=========================================================================
//File Name    : sysj061.v
//Author       : Ygliu
//Description  : system of luj061
//Parent Files : none
//Child Files  : modj061.v, luj061.v
//Revision
//2014/10/20   : creation
//=========================================================================

//TODO: Include DV Testbench/*{{{*/
`ifdef DV_UVM
  `include "uvm_dramtop_tb.sv"
`endif
/*}}}*/


//-------------------------------------------------------------------------
module sysj061();
wire   [23:0]  senif               ;
//bus signal declaration
wire   [26:0]  fmgpio              ;
wire   [23:0]  mgpio               ;
wire   [15:0]  tggpio              ;
wire           cke                 ; 
wire   [ 1:0]  odt, mcsnn          ;
wire   [19:0]  ma                  ;
wire   [31:0]  md                  ;
wire   [ 3:0]  dqm, dqs, dqsnn     ;
wire   [29:0]  perigpio            ;
wire   [17:0]  digtv               ;
wire   [28:0]  lmigpio             ;

wire   [ 2:0]  xhdmitmdsdatan      ;
wire   [ 2:0]  xhdmitmdsdatap      ;

wire           sdclk               ;
wire           sdclknn             ;


wire           xdphy_vref          ;
assign xdphy_vref = 1'b0;

//-------------------------------------------------------------------------
// SDF for gate-level simulation
`ifdef POSTSIM
initial
  begin
  `ifdef ES3
    `ifdef FF_CORNER
      $sdf_annotate("/home/dluj061/NETLIST_ES3/luj061_wo_wp2_hmv_cnn_ffm40c.sdf.gz",sysj061.u_luj061,,"luj061_ff.log" ,"MAXIMUM",,"FROM_MTM");
    `elsif SS_CORNER
      $sdf_annotate("/home/dluj061/NETLIST_ES3/luj061_wo_wp2_hmv_cnn_ssgm40c.sdf.gz",sysj061.u_luj061,,"luj061_ss.log" ,"MAXIMUM",,"FROM_MTM");
    `else
      $sdf_annotate("/home/dluj061/NETLIST_ES3/luj061_wo_wp2_hmv_cnn_tt25c.sdf.gz",sysj061.u_luj061,,"luj061_tt.log" ,"MAXIMUM",,"FROM_MTM");
    `endif
  `else
    `ifdef FF_CORNER
      $sdf_annotate("/home/dluj061/NETLIST_ES2/luj061_wo_wp2_hmv_cnn_ffm40c.sdf.gz",sysj061.u_luj061,,"luj061_ff.log" ,"MAXIMUM",,"FROM_MTM");
    `elsif SS_CORNER
      $sdf_annotate("/home/dluj061/NETLIST_ES2/luj061_wo_wp2_hmv_cnn_ssgm40c.sdf.gz",sysj061.u_luj061,,"luj061_ss.log" ,"MAXIMUM",,"FROM_MTM");
    `else
      $sdf_annotate("/home/dluj061/NETLIST_ES2/luj061_wo_wp2_hmv_cnn_tt25c.sdf.gz",sysj061.u_luj061,,"luj061_tt.log" ,"MAXIMUM",,"FROM_MTM");
    `endif
  `endif
  end
`endif


`ifdef WP2_POSTSIM
initial
  begin
  `ifdef ES3
    `ifdef FF_CORNER
    $sdf_annotate("/home/dluj061/NETLIST_ES3/wp2_ffm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_wp2,,"wp2_ff.log" ,"MAXIMUM",,"FROM_MTM");
    `elsif SS_CORNER
    $sdf_annotate("/home/dluj061/NETLIST_ES3/wp2_ssgm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_wp2,,"wp2_ss.log" ,"MAXIMUM",,"FROM_MTM");
    `else
    $sdf_annotate("/home/dluj061/NETLIST_ES3/wp2_tt25c.sdf.gz",sysj061.u_luj061.u_corej061.u_wp2,,"wp2_tt.log" ,"MAXIMUM",,"FROM_MTM");
    `endif
  `else
    `ifdef FF_CORNER
    $sdf_annotate("/home/dluj061/NETLIST_ES2/wp2_ffm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_wp2,,"wp2_ff.log" ,"MAXIMUM",,"FROM_MTM");
    `elsif SS_CORNER
    $sdf_annotate("/home/dluj061/NETLIST_ES2/wp2_ssgm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_wp2,,"wp2_ss.log" ,"MAXIMUM",,"FROM_MTM");
    `else
    $sdf_annotate("/home/dluj061/NETLIST_ES2/wp2_tt25c.sdf.gz",sysj061.u_luj061.u_corej061.u_wp2,,"wp2_tt.log" ,"MAXIMUM",,"FROM_MTM");
    `endif
  `endif
  end
`endif

`ifdef HVMTOP_POSTSIM
initial
  begin
  `ifdef ES3
    `ifdef FF_CORNER
    $sdf_annotate("/home/dluj061/NETLIST_ES3/hvmtop_ffm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_hvmtop,,"hvmtop_ff.log" ,"MAXIMUM",,"FROM_MTM");
    `elsif SS_CORNER
    $sdf_annotate("/home/dluj061/NETLIST_ES3/hvmtop_ssgm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_hvmtop,,"hvmtop_ss.log" ,"MAXIMUM",,"FROM_MTM");
    `else
    $sdf_annotate("/home/dluj061/NETLIST_ES3/hvmtop_tt25c.sdf.gz",sysj061.u_luj061.u_corej061.u_hvmtop,,"hvmtop_tt.log" ,"MAXIMUM",,"FROM_MTM");
    `endif
  `else
    `ifdef FF_CORNER
    $sdf_annotate("/home/dluj061/NETLIST_ES2/hvmtop_ffm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_hvmtop,,"hvmtop_ff.log" ,"MAXIMUM",,"FROM_MTM");
    `elsif SS_CORNER
    $sdf_annotate("/home/dluj061/NETLIST_ES2/hvmtop_ssgm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_hvmtop,,"hvmtop_ss.log" ,"MAXIMUM",,"FROM_MTM");
    `else
    $sdf_annotate("/home/dluj061/NETLIST_ES2/hvmtop_tt25c.sdf.gz",sysj061.u_luj061.u_corej061.u_hvmtop,,"hvmtop_tt.log" ,"MAXIMUM",,"FROM_MTM");
    `endif
  `endif
  end
`endif

`ifdef CNNTOP_POSTSIM
initial
  begin
  `ifdef ES3
    `ifdef FF_CORNER
      $sdf_annotate("/home/dluj061/NETLIST_ES3/cnntop_ffm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_cnntop,,"cnntop_ff.log" ,"MAXIMUM",,"FROM_MTM");
    `elsif SS_CORNER
      $sdf_annotate("/home/dluj061/NETLIST_ES3/cnntop_ssgm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_cnntop,,"cnntop_ss.log" ,"MAXIMUM",,"FROM_MTM");
    `else
      $sdf_annotate("/home/dluj061/NETLIST_ES3/cnntop_tt25c.sdf.gz",sysj061.u_luj061.u_corej061.u_cnntop,,"cnntop_tt.log" ,"MAXIMUM",,"FROM_MTM");
    `endif
  `else
    `ifdef FF_CORNER
      $sdf_annotate("/home/dluj061/NETLIST_ES2/cnntop_ffm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_cnntop,,"cnntop_ff.log" ,"MAXIMUM",,"FROM_MTM");
    `elsif SS_CORNER
      $sdf_annotate("/home/dluj061/NETLIST_ES2/cnntop_ssgm40c.sdf.gz",sysj061.u_luj061.u_corej061.u_cnntop,,"cnntop_ss.log" ,"MAXIMUM",,"FROM_MTM");
    `else
      $sdf_annotate("/home/dluj061/NETLIST_ES2/cnntop_tt25c.sdf.gz",sysj061.u_luj061.u_corej061.u_cnntop,,"cnntop_tt.log" ,"MAXIMUM",,"FROM_MTM");
    `endif
  `endif
  end
`endif

`ifdef DRAM_POSTSIM
initial
  begin
    // +define+CORNER_LT              //used in DDR PHY macro
    // +define+CORNER_ML              //used in DDR PHY macro
    // +define+CORNER_TC              //used in DDR PHY macro
    // +define+CORNER_WC              //used in DDR PHY macro
    // +define+CORNER_WCL             //used in DDR PHY macro

    `ifdef FF_CORNER
      `define CORNER_LT
      $sdf_annotate("/home/dluj061/IP/SUNPLUS/DDR_IP/2020_0903/sim/post_sim/sdf/SP_DDR32PHY16bit_U22OD18_LT_CB.sdf", `DRAMTOP.u_ddr_chip.u_DWC_DDR3PHY_top,, "ddrphy_ff.log", "MAXIMUM",,"FROM_MTM");

    `elsif SS_CORNER
      `define CORNER_WCL
      $sdf_annotate("/home/dluj061/IP/SUNPLUS/DDR_IP/2020_0903/sim/post_sim/sdf/SP_DDR32PHY16bit_U22OD18_WCL_CWT.sdf", `DRAMTOP.u_ddr_chip.u_DWC_DDR3PHY_top,, "ddrphy_ss.log", "MAXIMUM",,"FROM_MTM");

    `elsif TT_CORNER
      `define CORNER_TC
      $sdf_annotate("/home/dluj061/IP/SUNPLUS/DDR_IP/2020_0903/sim/post_sim/sdf/SP_DDR32PHY16bit_U22OD18_TC_CT.sdf", `DRAMTOP.u_ddr_chip.u_DWC_DDR3PHY_top,, "ddrphy_tt.log", "MAXIMUM",,"FROM_MTM");
    `endif

  end
`endif

`ifdef RTC_POSTSIM
initial
  begin
    $sdf_annotate("../MACRO/RTC/rtc.sdf",sysj061.u_luj061.u_ioj061.u_RTC_QAC294.u_rtccore, ,,"TYPICAL","1.0:1.21:1.0");
  end
`endif




`ifdef PATTERN
  `ifdef ES3
    `include "/home/dluj061/TESTSIM_GSI_ES3/luj061mon_rtl.v"
  `elsif ES2
    `include "/home/dluj061/TESTSIM_GSI_ES2/luj061mon_rtl.v"
  `else
    `include "/home/dluj061/TESTSIM_GSI_ES1/luj061mon_rtl.v"
  `endif
`endif

`ifdef DV_UVM
 `include "pattern.txt"
`else
 `include "command.txt"
`endif

`ifdef PRESIM
  `include "/home/dluj061/PRESIM/force.txt"
`endif

`ifdef POSTSIM
  `include "/home/dluj061/POSTSIM/force.txt"
`endif

//-------------------------------------------------------------------------
modj061 u_modj061(
  .prst_n              (prstnn              ),
  .trap                (trap                ),
  .xtali               (xtali               ),
  .xtalo               (xtalo               ),
  .testmode            (testmode            ),
  .xtalrtci            (xtalrtci            ),
  .xtalrtco            (xtalrtco            ),
  .pwron0              (pwron0              ),
  .pwron1              (pwron1              ),
  .pwron2              (pwron2              ),
  .pwron3              (pwron3              ),
  .pwron4              (pwron4              ),
  .dc2dc_en            (dc2dc_en0           ),
  .bat_fb              (bat_fb              ),
  .dc2dc_fb            (dc2dc_fb            ),
  .fuse_pad0           (fuse_pad0           ),
  .fuse_pad1           (fuse_pad1           ),
  .fuse_pad2           (fuse_pad2           ),
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
  .fmgpio              (fmgpio              ),
  .digtv               (digtv               ),
  .lmigpio             (lmigpio             ),
  .perigpio            (perigpio            ),
  .mgpio               (mgpio               ),

  .usbdev_dm           (usbdev_dm           ),
  .usbdev_dp           (usbdev_dp           ),
  .usbdev_rext         (usbdev_rext         ),
  .usbhost_dm          (usbhost_dm          ),
  .usbhost_dp          (usbhost_dp          ),
  .usbhost_rext        (usbhost_rext        ),
`ifdef M31ATPG
  .xusbdev_sstxa1      (xusbdev_sstxa1      ),
  .xusbdev_sstxb1      (xusbdev_sstxb1      ),
  .xusbdev_ssrxa1      (xusbdev_ssrxa1      ),
  .xusbdev_ssrxb1      (xusbdev_ssrxb1      ),
  .xusbdev_sstxa2      (xusbdev_sstxa2      ),
  .xusbdev_sstxb2      (xusbdev_sstxb2      ),
  .xusbdev_ssrxa2      (xusbdev_ssrxa2      ),
  .xusbdev_ssrxb2      (xusbdev_ssrxb2      ),

  .xusbhost_sstxa1     (xusbhost_sstxa1     ),
  .xusbhost_sstxb1     (xusbhost_sstxb1     ),
  .xusbhost_ssrxa1     (xusbhost_ssrxa1     ),
  .xusbhost_ssrxb1     (xusbhost_ssrxb1     ),
  .xusbhost_sstxa2     (xusbhost_sstxa2     ),
  .xusbhost_sstxb2     (xusbhost_sstxb2     ),
  .xusbhost_ssrxa2     (xusbhost_ssrxa2     ),
  .xusbhost_ssrxb2     (xusbhost_ssrxb2     ),
`endif
  .usbin               (usbin               ),

  .saragndref          (saragndref          ),
  .sarvbg              (sarvbg              ),
  .sarvref             (sarvref             ),
  .sarbin0             (sarbin0             ),
  .sarbin1             (sarbin1             ),
  .sarbin6             (sarbin6             ),
  .sarbin7             (sarbin7             ),
  .sarbin8             (sarbin8             ),
  .tpxp                (tpxp                ),
  .tpxn                (tpxn                ),
  .tpyp                (tpyp                ),
  .tpyn                (tpyn                ),
  .tggpio              (tggpio              ),
  .mclk                (mclk                ),
  .flash               (flash               ),
  .mshutter            (mshutter            ),
  .hd                  (hd                  ),
  .vd                  (vd                  ),
  .sen1                (sen1                ),
  .sck                 (sck                 ),
  .sdo                 (sdo                 ),
  .sdi                 (sdi                 ),
  .senif               (senif               )
);
//-------------------------------------------------------------------------
pulldown u_xzq (xzq);

supply1        xddrVREF      ;

luj061 u_luj061(
  .xprstn              (prstnn              ),
  .xtrap               (trap                ),
  .xtali               (xtali               ),
  .xtalo               (xtalo               ),
  .xtestm              (testmode            ),
  .xbat_fb             (bat_fb              ),
  .xtalrtci            (xtalrtci            ),
  .xtalrtco            (xtalrtco            ),
  .xpwron0             (pwron0              ),
  .xpwron1             (pwron1              ),
  .xpwron2             (pwron2              ),
  .xpwron3             (pwron3              ),
  .xpwron4             (pwron4              ),
  .xdc2dc_en0          (dc2dc_en0           ),
  .xdc2dc_en1          (dc2dc_en1           ),
  .xddr_rst_b          (mrstnn              ),
  .xddr_ck             (sdclk               ),
  .xddr_ckb            (sdclknn             ),
  .xddr_cke            (cke                 ),
  .xddr_odt            (odt                 ),
  .xddr_cs             (mcsnn               ),
  .xddr_ras            (rasnn               ),
  .xddr_cas            (casnn               ),
  .xddr_we             (mwenn               ),
  .xddr_a              (ma[15:0]            ),
  .xddr_bgba           (ma[19:16]           ),
  .xddr_dqs            (dqs                 ),
  .xddr_dqsb           (dqsnn               ),
  .xddr_dm             (dqm                 ),
  .xddr_dq             (md                  ),
  .xddr_pzq            (xzq                 ),
  .xddr_vref           (xddrVREF            ),
  .xfmif               (fmgpio              ),
  .xpgpio              (perigpio[28:0]      ),
  .xmgpio              (mgpio               ),
  .xlcdif              (                    ),
  .xegpio              (                    ),
  .xck32k              (                    ),
  .xpir_vref           (                    ),
  .xpwrc_ldoout        (                    ),
  .xusbdev_dm          (usbdev_dm           ),
  .xusbdev_dp          (usbdev_dp           ),
  .xusbdev_cc_0        (xusbdev_cc_0        ),
  .xusbdev_cc_1        (xusbdev_cc_1        ),
  .xusbdev_sstxa1      (xusbdev_sstxa1      ),
  .xusbdev_sstxb1      (xusbdev_sstxb1      ),
  .xusbdev_ssrxa1      (xusbdev_ssrxa1      ),
  .xusbdev_ssrxb1      (xusbdev_ssrxb1      ),
  .xusbdev_sstxa2      (xusbdev_sstxa2      ),
  .xusbdev_sstxb2      (xusbdev_sstxb2      ),
  .xusbdev_ssrxa2      (xusbdev_ssrxa2      ),
  .xusbdev_ssrxb2      (xusbdev_ssrxb2      ),
  .xusbhost_sstxa1     (xusbhost_sstxa1     ),
  .xusbhost_sstxb1     (xusbhost_sstxb1     ),
  .xusbhost_ssrxa1     (xusbhost_ssrxa1     ),
  .xusbhost_ssrxb1     (xusbhost_ssrxb1     ),
  .xusbhost_sstxa2     (xusbhost_sstxa2     ),
  .xusbhost_sstxb2     (xusbhost_sstxb2     ),
  .xusbhost_ssrxa2     (xusbhost_ssrxa2     ),
  .xusbhost_ssrxb2     (xusbhost_ssrxb2     ),
  .xusbhost_dp         (xusbhost_dp         ),
  .xusbhost_dm         (xusbhost_dm         ),
  .xusbhost_cc_0       (xusbhost_cc_0       ),
  .xusbhost_cc_1       (xusbhost_cc_1       ),
  .xusb_in             (usbin               ),
/*
 `ifdef CDNS_TEST
  .xusbdev_dm          (usbdev_dm           ),
  .xusbdev_dp          (usbdev_dp           ),
//  .xusbhdev_rext       (usbdev_rext         ),
//  .xusbhdev_dm         (usbhost_dm          ),
//  .xusbhdev_dp         (usbhost_dp          ),

 `else
//  .xusbhdev_dm         (usbdev_dm           ),
//  .xusbhdev_dp         (usbdev_dp           ),
//  .xusbhdev_rext       (usbdev_rext         ),
 `endif
 
`ifdef M31ATPG
  .xusbdev_sstxa1      (xusbdev_sstxa1      ),
  .xusbdev_sstxb1      (xusbdev_sstxb1      ),
  .xusbdev_ssrxa1      (xusbdev_ssrxa1      ),
  .xusbdev_ssrxb1      (xusbdev_ssrxb1      ),
  .xusbdev_sstxa2      (xusbdev_sstxa2      ),
  .xusbdev_sstxb2      (xusbdev_sstxb2      ),
  .xusbdev_ssrxa2      (xusbdev_ssrxa2      ),
  .xusbdev_ssrxb2      (xusbdev_ssrxb2      ),

  .xusbhost_sstxa1     (xusbhost_sstxa1     ),
  .xusbhost_sstxb1     (xusbhost_sstxb1     ),
  .xusbhost_ssrxa1     (xusbhost_ssrxa1     ),
  .xusbhost_ssrxb1     (xusbhost_ssrxb1     ),
  .xusbhost_sstxa2     (xusbhost_sstxa2     ),
  .xusbhost_sstxb2     (xusbhost_sstxb2     ),
  .xusbhost_ssrxa2     (xusbhost_ssrxa2     ),
  .xusbhost_ssrxb2     (xusbhost_ssrxb2     ),
`endif
  .xusbhost_dp         (xusbhost_dp         ),
  .xusbhost_dm         (xusbhost_dm         ),
  .xusbhost_cc_0       (xusbhost_cc_0       ),
  .xusbhost_cc_1       (xusbhost_cc_1       ),
  .xusb_in             (usbin               ),
*/
`ifdef PATTERN
  .xsarin0             (sarbin0             ),
  .xsarin1             (sarbin1             ),
  .xsarin2             (tpxp                ),
  .xsarin3             (tpxn                ),
  .xsarin4             (tpyp                ),
  .xsarin5             (tpyn                ),
  .xsarin6             (                    ),
`else 
  .xsarin0             (sarbin0             ),
  .xsarin1             (sarbin1             ),
  .xsarin2             (tpxp                ),
  .xsarin3             (tpxn                ),
  .xsarin4             (tpyp                ),
  .xsarin5             (tpyn                ),
  .xsarin6             (                    ),
`endif //PATTERN
  .xtggpio             (tggpio              ),
  .xsenif              (senif               ),
  .xsdldo_out          (                    ),
  .xsenmclk            (mclk                ),

  .xtx_lppr            ()

);

//TODO: DV Testbench Instantiation/*{{{*/
`ifdef DV_UVM
  uvm_dramtop_tb u_uvm_dramtop_tb ();
`endif
/*}}}*/

endmodule
