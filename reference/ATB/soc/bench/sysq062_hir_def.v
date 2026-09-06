//`define F24M_PERIOD   1000.0/24
`define F24M_PERIOD   41.666
`define F27M_PERIOD   37.037
`define F48M_PERIOD   1000.0/48
`define F32K_PERIOD   1000.0/0.032768

`timescale 1ns/10ps
//`ifdef PATTERN
//  `timescale 1ns/1fs
//`else
//  `ifdef FREQ500
//  `timescale 1ns/10ps
//  `else
//  `timescale 1ns/100ps
//  `endif
//`endif

`ifdef PATTERN
`define TIMEBASE      `F24M_PERIOD
`else
`define TIMEBASE      20
`endif

`define TOP           sysq062.u_waq062
//`define CORE          sysq062.u_waq062.u_coreq062
`define IO            sysq062.u_waq062.u_gtop.u_ioq062
//`define IO_A          sysq062.u_waq062.u_ioq062
//`define IO_B          sysq062.u_waq062.u_ioq062
`define GCKRST        sysq062.u_waq062.u_gtop.u_gckrst
//`define GLOBAL        sysq062.u_waq062.u_coreq062.u_global
`define GREG          sysq062.u_waq062.u_gtop.u_gregtop
`define GMUX          sysq062.u_waq062.u_gtop.u_gmux
//`define CPUTOP        sysq062.u_waq062.u_coreq062.u_cputop
`define CQTOP         sysq062.u_waq062.u_cqtop
//`define WP2           sysq062.u_waq062.u_coreq062.u_wp2
`define FM            sysq062.u_waq062.u_fmtop
//`define USBTOP        sysq062.u_waq062.u_coreq062.u_wp45.u_usbtop
`define AUDTOP        sysq062.u_waq062.u_audtop
`define DMATOP        sysq062.u_waq062.u_dmatop
`define DRAMTOP       sysq062.u_waq062.u_ss_mem
//`define MJPGTOP       sysq062.u_waq062.u_hvmtop.u_mjpgtop
`define FRONTTOP      sysq062.u_waq062.u_ss_vis.u_fronttop
//`define DISPTOP       sysq062.u_waq062.u_wp45.u_disptop.U_DISPD_LUI056
//`define GPETOP        sysq062.u_waq062.u_gpetop
//`define MACTOP        sysq062.u_waq062.u_mactop
//`define METOP         sysq062.u_waq062.u_wp45.u_maetop.u_maecore0.u_metop
//`define MAETOP        sysq062.u_waq062.u_wp45.u_maetop.u_maecore0
//`define SETOP         sysq062.u_waq062.u_wp45.u_setop
//`define GPUTOP        sysq062.u_waq062.u_wp45.u_gputop
`define PERITOP       sysq062.u_waq062.u_peritop
//`define MCUTOP        sysq062.u_waq062.u_mcutop
//`define CNNTOP        sysq062.u_waq062.u_cnntop

`define SS_CDEC       sysq062.u_waq062.u_ss_cdec
`define SS_CMP        sysq062.u_waq062.u_ss_cmp
`define SS_CON        sysq062.u_waq062.u_ss_con
`define SS_CPU        sysq062.u_waq062.u_ss_cpu
`define SS_VOUT       sysq062.u_waq062.u_ss_vout
`define SS_VIS        sysq062.u_waq062.u_ss_vis
`define SS_SF         sysq062.u_waq062.u_ss_sf
`define SS_MEMTOP     sysq062.u_waq062.u_ss_mem

`define MODEL         sysq062.u_modq062
`define GMODEL        sysq062.u_modq062.u_gmodel
//`define CDSPMODEL     sysq062.u_modq062.u_cdspmodel
`define ISPMODEL      sysq062.u_modq062.u_ispmodel
`define SENSORMODEL   sysq062.u_modq062.u_sensormodel
`define DRAMMODEL     sysq062.u_modq062.u_drammodel
`define CPUMODEL      sysq062.u_modq062.u_cpumodel
`define FMMODEL       sysq062.u_modq062.u_fmmodel
`define USBMODEL      sysq062.u_modq062.u_usb20model
`define HCIMODEL      sysq062.u_modq062.u_hcimodel
`define AUDMODEL      sysq062.u_modq062.u_audmodel
`define UARTMODEL     sysq062.u_modq062.u_uartmodel
`define EJTAGMODEL    sysq062.u_modq062.u_ejtagmodel
`define FRONTMODEL    sysq062.u_modq062.u_frontmodel
`define TVINMODEL     sysq062.u_modq062.u_tvinmodel
`define I2CMODEL      sysq062.u_modq062.u_si2cmodel
`define CQMODEL       sysq062.u_modq062.u_cqmodel


//`define H264TOP       sysq062.u_waq062.u_coreq062.u_h264top
//`define H264CORE      sysq062.u_waq062.u_coreq062.u_h264top.u_h264codec_core
//`define H264ME        sysq062.u_waq062.u_coreq062.u_h264top.u_h264codec_core.u_me_top
//`define H264MR        sysq062.u_waq062.u_coreq062.u_h264top.u_h264codec_core.u_mr_top
//`define H264IP        sysq062.u_waq062.u_coreq062.u_h264top.u_h264codec_core.u_ip_top
//`define H264QT        sysq062.u_waq062.u_coreq062.u_h264top.u_h264codec_core.u_qt_top
//`define H264LF        sysq062.u_waq062.u_coreq062.u_h264top.u_h264codec_core.u_lf_top
//`define H264MP        sysq062.u_waq062.u_coreq062.u_h264top.u_h264codec_core.u_mp_top
//`define H264RC        sysq062.u_waq062.u_coreq062.u_h264top.u_h264codec_core.u_rc_top
//`define H264DM        sysq062.u_waq062.u_coreq062.u_h264top.u_h264codec_core.u_dm_top
//`define H264DP        sysq062.u_waq062.u_coreq062.u_h264top.u_h264codec_core.u_vout_top
//`define H264DPDM      sysq062.u_waq062.u_coreq062.u_h264top.u_h264codec_core.u_dpdm_top
//`define PWRCRTC       sysq062.u_waq062.u_coreq062.u_wp45.u_wp45io.u_PWRC_RTC_OT_LAI053

//`ifdef CEVAMODELEN
//`define CEVAMODEL     sysq062.u_modq062.u_cevamodel
//`endif


//-------------------------------------------------------------------------
//define CPUREAD,CPUWRITE

`ifndef DV_UVM
// EJTAG group
`ifdef EJTAG
  `define CPUWRITE4B  `EJTAGMODEL.EJWRITE4B
  `define CPUWRITE2B  `EJTAGMODEL.EJWRITE2B
  `define CPUWRITE1B  `EJTAGMODEL.EJWRITE1B
  `define CPUREAD4B   `EJTAGMODEL.EJREAD4B
  `define CPUREAD2B   `EJTAGMODEL.EJREAD2B
  `define CPUREAD1B   `EJTAGMODEL.EJREAD1B
`elsif GSIAPB
  `define CPUWRITE4B   sysq062.u_modq062.u_gsihostmodel2apb.GSIHOSTWRITE4B
  `define CPUWRITE2B   sysq062.u_modq062.u_gsihostmodel2apb.GSIHOSTWRITE2B
  `define CPUWRITE1B   sysq062.u_modq062.u_gsihostmodel2apb.GSIHOSTWRITE1B
  `define CPUREAD4B    sysq062.u_modq062.u_gsihostmodel2apb.GSIHOSTREAD4B
  `define CPUREAD2B    sysq062.u_modq062.u_gsihostmodel2apb.GSIHOSTREAD2B
  `define CPUREAD1B    sysq062.u_modq062.u_gsihostmodel2apb.GSIHOSTREAD1B
`elsif I2CAPB
  `define CPUWRITE4B   sysq062.u_modq062.u_i2chostmodel2apb.HOSTWRITE4B
  `define CPUWRITE2B   sysq062.u_modq062.u_i2chostmodel2apb.HOSTWRITE2B
  `define CPUWRITE1B   sysq062.u_modq062.u_i2chostmodel2apb.HOSTWRITE1B
  `define CPUREAD4B    sysq062.u_modq062.u_i2chostmodel2apb.HOSTREAD4B
  `define CPUREAD2B    sysq062.u_modq062.u_i2chostmodel2apb.HOSTREAD2B
  `define CPUREAD1B    sysq062.u_modq062.u_i2chostmodel2apb.HOSTREAD1B
`else
  `define CPUWRITE4B   sysq062.u_modq062.u_cpumodel.CPUWRITE4BYTE
  `define CPUWRITE2B   sysq062.u_modq062.u_cpumodel.CPUWRITE2BYTE
  `define CPUWRITE1B   sysq062.u_modq062.u_cpumodel.CPUWRITE1BYTE
  `define CPUREAD4B    sysq062.u_modq062.u_cpumodel.CPUREAD4BYTE
  `define CPUREAD2B    sysq062.u_modq062.u_cpumodel.CPUREAD2BYTE
  `define CPUREAD1B    sysq062.u_modq062.u_cpumodel.CPUREAD1BYTE
`endif

`define CPUREADLINE  sysq062.u_modq062.u_cpumodel.CPUREADLINE
`define CPUWRITELINE sysq062.u_modq062.u_cpumodel.CPUWRITELINE

`ifdef CPUI2CAPB
  `define APB_CPUWRITE4B   sysq062.u_modq062.u_i2chostmodel2apb.HOSTWRITE4B
  `define APB_CPUWRITE2B   sysq062.u_modq062.u_i2chostmodel2apb.HOSTWRITE2B
  `define APB_CPUWRITE1B   sysq062.u_modq062.u_i2chostmodel2apb.HOSTWRITE1B
  `define APB_CPUREAD4B    sysq062.u_modq062.u_i2chostmodel2apb.HOSTREAD4B
  `define APB_CPUREAD2B    sysq062.u_modq062.u_i2chostmodel2apb.HOSTREAD2B
  `define APB_CPUREAD1B    sysq062.u_modq062.u_i2chostmodel2apb.HOSTREAD1B
`endif
`else
  `define CPUWRITE4B   uvm_soc_tb.base_env_h.CPUWRITE4B
  `define CPUWRITE2B   uvm_soc_tb.base_env_h.CPUWRITE2B
  `define CPUWRITE1B   uvm_soc_tb.base_env_h.CPUWRITE1B
  `define CPUREAD4B    uvm_soc_tb.base_env_h.CPUREAD4B
  `define CPUREAD2B    uvm_soc_tb.base_env_h.CPUREAD2B
  `define CPUREAD1B    uvm_soc_tb.base_env_h.CPUREAD1B
  `define CORETOP      sysq062.u_waq062
`endif
