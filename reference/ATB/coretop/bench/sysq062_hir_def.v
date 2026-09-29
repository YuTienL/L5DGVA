//`define F24M_PERIOD   1000.0/24
`define F24M_PERIOD   41.666
`define F27M_PERIOD   37.037
`define F48M_PERIOD   1000.0/48
`define F32K_PERIOD   1000.0/0.032768

`ifdef PATTERN
  `timescale 1ns/1fs
`else
  `ifdef FREQ500
  `timescale 1ns/10ps
  `else
  `timescale 1ns/100ps
  `endif
`endif

`ifdef PATTERN
`define TIMEBASE      `F24M_PERIOD
`else
`define TIMEBASE      20
`endif

`define TOP           sysj061.u_luj061
`define CORE          sysj061.u_luj061.u_corej061
`define IO            sysj061.u_luj061.u_ioj061
`define IO_A          sysj061.u_luj061.u_ioj061
`define IO_B          sysj061.u_luj061.u_ioj061
`define GCKRST        sysj061.u_luj061.u_gckrst
`define GLOBAL        sysj061.u_luj061.u_corej061.u_global
`define GREG          sysj061.u_luj061.u_corej061.u_gtop
`define GMUX          sysj061.u_luj061.u_corej061.u_gmux
`define CPUTOP        sysj061.u_luj061.u_corej061.u_cputop
`define CQTOP         sysj061.u_luj061.u_corej061.u_cqtop
`define WP2           sysj061.u_luj061.u_corej061.u_wp2
`define FM            sysj061.u_luj061.u_corej061.u_fmtop
`define USBTOP        sysj061.u_luj061.u_corej061.u_wp45.u_usbtop
`define AUDTOP        sysj061.u_luj061.u_corej061.u_audtop
`define DMATOP        sysj061.u_luj061.u_corej061.u_dmatop
`define DRAMTOP       sysj061.u_luj061.u_corej061.u_dramtop
`define MJPGTOP       sysj061.u_luj061.u_corej061.u_hvmtop.u_mjpgtop
`define FRONTTOP      sysj061.u_luj061.u_corej061.u_fronttop.u_fronttop_d
`define DISPTOP       sysj061.u_luj061.u_corej061.u_wp45.u_disptop.U_DISPD_LUI056
`define GPETOP        sysj061.u_luj061.u_corej061.u_gpetop
`define MACTOP        sysj061.u_luj061.u_corej061.u_mactop
`define METOP         sysj061.u_luj061.u_corej061.u_wp45.u_maetop.u_maecore0.u_metop
`define MAETOP        sysj061.u_luj061.u_corej061.u_wp45.u_maetop.u_maecore0
`define SETOP         sysj061.u_luj061.u_corej061.u_wp45.u_setop
`define GPUTOP        sysj061.u_luj061.u_corej061.u_wp45.u_gputop
`define PERITOP       sysj061.u_luj061.u_corej061.u_peritop
`define MCUTOP        sysj061.u_luj061.u_corej061.u_mcutop
`define CNNTOP        sysj061.u_luj061.u_corej061.u_cnntop
`define MODEL         sysj061.u_modj061
`define GMODEL        sysj061.u_modj061.u_gmodel
`define CDSPMODEL     sysj061.u_modj061.u_cdspmodel
`define SENSORMODEL   sysj061.u_modj061.u_sensormodel
`define DRAMMODEL     sysj061.u_modj061.u_drammodel
`define CPUMODEL      sysj061.u_modj061.u_cpumodel
`define FMMODEL       sysj061.u_modj061.u_fmmodel
`define USBMODEL      sysj061.u_modj061.u_usb20model
`define HCIMODEL      sysj061.u_modj061.u_hcimodel
`define AUDMODEL      sysj061.u_modj061.u_audmodel
`define UARTMODEL     sysj061.u_modj061.u_uartmodel
`define EJTAGMODEL    sysj061.u_modj061.u_ejtagmodel
`define FRONTMODEL    sysj061.u_modj061.u_frontmodel
`define TVINMODEL     sysj061.u_modj061.u_tvinmodel
`define I2CMODEL      sysj061.u_modj061.u_si2cmodel
`define CQMODEL       sysj061.u_modj061.u_cqmodel
`define H264TOP       sysj061.u_luj061.u_corej061.u_h264top
`define H264CORE      sysj061.u_luj061.u_corej061.u_h264top.u_h264codec_core
`define H264ME        sysj061.u_luj061.u_corej061.u_h264top.u_h264codec_core.u_me_top
`define H264MR        sysj061.u_luj061.u_corej061.u_h264top.u_h264codec_core.u_mr_top
`define H264IP        sysj061.u_luj061.u_corej061.u_h264top.u_h264codec_core.u_ip_top
`define H264QT        sysj061.u_luj061.u_corej061.u_h264top.u_h264codec_core.u_qt_top
`define H264LF        sysj061.u_luj061.u_corej061.u_h264top.u_h264codec_core.u_lf_top
`define H264MP        sysj061.u_luj061.u_corej061.u_h264top.u_h264codec_core.u_mp_top
`define H264RC        sysj061.u_luj061.u_corej061.u_h264top.u_h264codec_core.u_rc_top
`define H264DM        sysj061.u_luj061.u_corej061.u_h264top.u_h264codec_core.u_dm_top
`define H264DP        sysj061.u_luj061.u_corej061.u_h264top.u_h264codec_core.u_dp_top
`define H264DPDM      sysj061.u_luj061.u_corej061.u_h264top.u_h264codec_core.u_dpdm_top
`define PWRCRTC       sysj061.u_luj061.u_corej061.u_wp45.u_wp45io.u_PWRC_RTC_OT_LAI053

`ifdef CEVAMODELEN
`define CEVAMODEL     sysj061.u_modj061.u_cevamodel
`endif


//-------------------------------------------------------------------------
//define CPUREAD,CPUWRITE

// EJTAG group
`ifdef EJTAG
  `define CPUWRITE4B  `EJTAGMODEL.EJWRITE4B
  `define CPUWRITE2B  `EJTAGMODEL.EJWRITE2B
  `define CPUWRITE1B  `EJTAGMODEL.EJWRITE1B
  `define CPUREAD4B   `EJTAGMODEL.EJREAD4B
  `define CPUREAD2B   `EJTAGMODEL.EJREAD2B
  `define CPUREAD1B   `EJTAGMODEL.EJREAD1B
`elsif GSIAPB
  `define CPUWRITE4B   sysj061.u_modj061.u_gsihostmodel2apb.GSIHOSTWRITE4B
  `define CPUWRITE2B   sysj061.u_modj061.u_gsihostmodel2apb.GSIHOSTWRITE2B
  `define CPUWRITE1B   sysj061.u_modj061.u_gsihostmodel2apb.GSIHOSTWRITE1B
  `define CPUREAD4B    sysj061.u_modj061.u_gsihostmodel2apb.GSIHOSTREAD4B
  `define CPUREAD2B    sysj061.u_modj061.u_gsihostmodel2apb.GSIHOSTREAD2B
  `define CPUREAD1B    sysj061.u_modj061.u_gsihostmodel2apb.GSIHOSTREAD1B
`elsif I2CAPB
  `define CPUWRITE4B   sysj061.u_modj061.u_i2chostmodel2apb.HOSTWRITE4B
  `define CPUWRITE2B   sysj061.u_modj061.u_i2chostmodel2apb.HOSTWRITE2B
  `define CPUWRITE1B   sysj061.u_modj061.u_i2chostmodel2apb.HOSTWRITE1B
  `define CPUREAD4B    sysj061.u_modj061.u_i2chostmodel2apb.HOSTREAD4B
  `define CPUREAD2B    sysj061.u_modj061.u_i2chostmodel2apb.HOSTREAD2B
  `define CPUREAD1B    sysj061.u_modj061.u_i2chostmodel2apb.HOSTREAD1B
`else
  `define CPUWRITE4B   sysj061.u_modj061.u_cpumodel.CPUWRITE4BYTE
  `define CPUWRITE2B   sysj061.u_modj061.u_cpumodel.CPUWRITE2BYTE
  `define CPUWRITE1B   sysj061.u_modj061.u_cpumodel.CPUWRITE1BYTE
  `define CPUREAD4B    sysj061.u_modj061.u_cpumodel.CPUREAD4BYTE
  `define CPUREAD2B    sysj061.u_modj061.u_cpumodel.CPUREAD2BYTE
  `define CPUREAD1B    sysj061.u_modj061.u_cpumodel.CPUREAD1BYTE
`endif

`define CPUREADLINE  sysj061.u_modj061.u_cpumodel.CPUREADLINE
`define CPUWRITELINE sysj061.u_modj061.u_cpumodel.CPUWRITELINE

`ifdef CPUI2CAPB
  `define APB_CPUWRITE4B   sysj061.u_modj061.u_i2chostmodel2apb.HOSTWRITE4B
  `define APB_CPUWRITE2B   sysj061.u_modj061.u_i2chostmodel2apb.HOSTWRITE2B
  `define APB_CPUWRITE1B   sysj061.u_modj061.u_i2chostmodel2apb.HOSTWRITE1B
  `define APB_CPUREAD4B    sysj061.u_modj061.u_i2chostmodel2apb.HOSTREAD4B
  `define APB_CPUREAD2B    sysj061.u_modj061.u_i2chostmodel2apb.HOSTREAD2B
  `define APB_CPUREAD1B    sysj061.u_modj061.u_i2chostmodel2apb.HOSTREAD1B
`endif
