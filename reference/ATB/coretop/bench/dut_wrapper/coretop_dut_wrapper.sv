// Set up the replace/connect infrastructure for `CORETOP.u_audtop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M_AUDTOP 
`define BIND_BD_AXI_M_AUDTOP 
`elsif CONNECT_BD_AXI_M_AUDTOP 
`define BIND_BD_AXI_M_AUDTOP 
`endif

`ifdef BIND_BD_AXI_M_AUDTOP 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_audtop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_AUDTOP 
`define BIND_BD_APB_S_AUDTOP 
`elsif CONNECT_BD_APB_S_AUDTOP 
`define BIND_BD_APB_S_AUDTOP 
`endif

`ifdef BIND_BD_APB_S_AUDTOP 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_cqtop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M_CQTOP 
`define BIND_BD_AXI_M_CQTOP 
`elsif CONNECT_BD_AXI_M_CQTOP 
`define BIND_BD_AXI_M_CQTOP 
`endif

`ifdef BIND_BD_AXI_M_CQTOP 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_dmatop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M_DMATOP 
`define BIND_BD_AXI_M_DMATOP 
`elsif CONNECT_BD_AXI_M_DMATOP 
`define BIND_BD_AXI_M_DMATOP 
`endif

`ifdef BIND_BD_AXI_M_DMATOP 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_dmatop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_DMATOP 
`define BIND_BD_APB_S_DMATOP 
`elsif CONNECT_BD_APB_S_DMATOP 
`define BIND_BD_APB_S_DMATOP 
`endif

`ifdef BIND_BD_APB_S_DMATOP 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_fmtop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AHB_S_FMTOP 
`define BINDP_BD_AHB_S_FMTOP 
`elsif CONNECT_BD_AHB_S_FMTOP 
`define BINDP_BD_AHB_S_FMTOP 
`endif

`ifdef BINDP_BD_AHB_S_FMTOP 
`ifndef INCLUDE_SVT_AHB_SLAVE_BIND_IF 
`define INCLUDE_SVT_AHB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_fmtop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M_FMTOP 
`define BINDP_BD_AXI_M_FMTOP 
`elsif CONNECT_BD_AXI_M_FMTOP 
`define BINDP_BD_AXI_M_FMTOP 
`endif

`ifdef BINDP_BD_AXI_M_FMTOP 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_fmtop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_FMTOP 
`define BINDP_BD_APB_S_FMTOP 
`elsif CONNECT_BD_APB_S_FMTOP 
`define BINDP_BD_APB_S_FMTOP 
`endif

`ifdef BINDP_BD_APB_S_FMTOP 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_gtop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_GTOP 
`define BIND_BD_APB_S_GTOP 
`elsif CONNECT_BD_APB_S_GTOP 
`define BIND_BD_APB_S_GTOP 
`endif

`ifdef BIND_BD_APB_S_GTOP 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_peritop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M_PERITOP 
`define BIND_BD_AXI_M_PERITOP 
`elsif CONNECT_BD_AXI_M_PERITOP 
`define BIND_BD_AXI_M_PERITOP 
`endif

`ifdef BIND_BD_AXI_M_PERITOP 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_peritop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_M_PERITOP 
`define BIND_BD_APB_M_PERITOP 
`elsif CONNECT_BD_APB_M_PERITOP 
`define BIND_BD_APB_M_PERITOP 
`endif

`ifdef BIND_BD_APB_M_PERITOP 
`ifndef INCLUDE_SVT_APB_MASTER_BIND_IF 
`define INCLUDE_SVT_APB_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_peritop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S0_PERITOP 
`define BIND_BD_APB_S0_PERITOP 
`elsif CONNECT_BD_APB_S0_PERITOP 
`define BIND_BD_APB_S0_PERITOP 
`endif

`ifdef BIND_BD_APB_S0_PERITOP 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_peritop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S1_PERITOP 
`define BIND_BD_APB_S1_PERITOP 
`elsif CONNECT_BD_APB_S1_PERITOP 
`define BIND_BD_APB_S1_PERITOP 
`endif

`ifdef BIND_BD_APB_S1_PERITOP 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_hsmtop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M_HSMTOP 
`define BIND_BD_AXI_M_HSMTOP 
`elsif CONNECT_BD_AXI_M_HSMTOP 
`define BIND_BD_AXI_M_HSMTOP 
`endif

`ifdef BIND_BD_AXI_M_HSMTOP 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_hsmtop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AHB_M_HSMTOP 
`define BIND_BD_AHB_M_HSMTOP 
`elsif CONNECT_BD_AHB_M_HSMTOP 
`define BIND_BD_AHB_M_HSMTOP 
`endif

`ifdef BIND_BD_AHB_M_HSMTOP 
`ifndef INCLUDE_SVT_AHB_MASTER_BIND_IF 
`define INCLUDE_SVT_AHB_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_hsmtop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_M_HSMTOP 
`define BIND_BD_APB_M_HSMTOP 
`elsif CONNECT_BD_APB_M_HSMTOP 
`define BIND_BD_APB_M_HSMTOP 
`endif

`ifdef BIND_BD_APB_M_HSMTOP 
`ifndef INCLUDE_SVT_APB_MASTER_BIND_IF 
`define INCLUDE_SVT_APB_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_hsmtop 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_HSMTOP 
`define BIND_BD_APB_S_HSMTOP 
`elsif CONNECT_BD_APB_S_HSMTOP 
`define BIND_BD_APB_S_HSMTOP 
`endif

`ifdef BIND_BD_APB_S_HSMTOP 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ucie_0 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_S_UCIE 
`define BIND_BD_AXI_S_UCIE 
`elsif CONNECT_BD_AXI_S_UCIE 
`define BIND_BD_AXI_S_UCIE 
`endif

`ifdef BIND_BD_AXI_S_UCIE 
`ifndef INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`define INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ucie_0 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M_UCIE 
`define BIND_BD_AXI_M_UCIE 
`elsif CONNECT_BD_AXI_M_UCIE 
`define BIND_BD_AXI_M_UCIE 
`endif

`ifdef BIND_BD_AXI_M_UCIE 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ucie_0 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_UCIE 
`define BIND_BD_APB_S_UCIE 
`elsif CONNECT_BD_APB_S_UCIE 
`define BIND_BD_APB_S_UCIE 
`endif

`ifdef BIND_BD_APB_S_UCIE 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_cdec 
// -----------------------------------------------------------------------------
`ifdef REPLACEC_BD_AXI_M_SS_CDEC 
`define BIND_BD_AXI_M_SS_CDEC 
`elsif CONNECT_BD_AXI_M_SS_CDEC 
`define BIND_BD_AXI_M_SS_CDEC 
`endif

`ifdef BIND_BD_AXI_M_SS_CDEC 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_cdec 
// -----------------------------------------------------------------------------
`ifdef REPLACEC_BD_APB_S_SS_CDEC 
`define BIND_BD_APB_S_SS_CDEC 
`elsif CONNECT_BD_APB_S_SS_CDEC 
`define BIND_BD_APB_S_SS_CDEC 
`endif

`ifdef BIND_BD_APB_S_SS_CDEC 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_cmp 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_ACE_M0_SS_CMP 
`define BIND_BD_ACE_M0_SS_CMP 
`elsif CONNECT_BD_ACE_M0_SS_CMP 
`define BIND_BD_ACE_M0_SS_CMP 
`endif

`ifdef BIND_BD_ACE_M0_SS_CMP 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_cmp 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_ACE_M1_SS_CMP 
`define BIND_BD_ACE_M1_SS_CMP 
`elsif CONNECT_BD_ACE_M1_SS_CMP 
`define BIND_BD_ACE_M1_SS_CMP 
`endif

`ifdef BIND_BD_ACE_M1_SS_CMP 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_cmp 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_ACE_M2_SS_CMP 
`define BIND_BD_ACE_M2_SS_CMP 
`elsif CONNECT_BD_ACE_M2_SS_CMP 
`define BIND_BD_ACE_M2_SS_CMP 
`endif

`ifdef BIND_BD_ACE_M2_SS_CMP 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_cmp 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_SS_CMP 
`define BIND_BD_APB_S_SS_CMP 
`elsif CONNECT_BD_APB_S_SS_CMP 
`define BIND_BD_APB_S_SS_CMP 
`endif

`ifdef BIND_BD_APB_S_SS_CMP 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_con 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M_SS_CON 
`define BIND_BD_AXI_M_SS_CON 
`elsif CONNECT_BD_AXI_M_SS_CON 
`define BIND_BD_AXI_M_SS_CON 
`endif

`ifdef BIND_BD_AXI_M_SS_CON 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_con 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_S_SS_CON 
`define BIND_BD_AXI_S_SS_CON 
`elsif CONNECT_BD_AXI_S_SS_CON 
`define BIND_BD_AXI_S_SS_CON 
`endif

`ifdef BIND_BD_AXI_S_SS_CON 
`ifndef INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`define INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_con 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_SS_CON 
`define BIND_BD_APB_S_SS_CON 
`elsif CONNECT_BD_APB_S_SS_CON 
`define BIND_BD_APB_S_SS_CON 
`endif

`ifdef BIND_BD_APB_S_SS_CON 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_cpu 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_ACE_M_SS_CPU 
`define BIND_BD_ACE_M_SS_CPU 
`elsif CONNECT_BD_ACE_M_SS_CPU 
`define BIND_BD_ACE_M_SS_CPU 
`endif

`ifdef BIND_BD_ACE_M_SS_CPU 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_cpu 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_S_SS_CPU 
`define BIND_BD_AXI_S_SS_CPU 
`elsif CONNECT_BD_AXI_S_SS_CPU 
`define BIND_BD_AXI_S_SS_CPU 
`endif

`ifdef BIND_BD_AXI_S_SS_CPU 
`ifndef INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`define INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_cpu 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_M_SS_CPU 
`define BIND_BD_APB_M_SS_CPU 
`elsif CONNECT_BD_APB_M_SS_CPU 
`define BIND_BD_APB_M_SS_CPU 
`endif

`ifdef BIND_BD_APB_M_SS_CPU 
`ifndef INCLUDE_SVT_APB_MASTER_BIND_IF 
`define INCLUDE_SVT_APB_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_cpu 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_SS_CPU 
`define BIND_BD_APB_S_SS_CPU 
`elsif CONNECT_BD_APB_S_SS_CPU 
`define BIND_BD_APB_S_SS_CPU 
`endif

`ifdef BIND_BD_APB_S_SS_CPU 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_vis 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M0_SS_VIS 
`define BIND_BD_AXI_M0_SS_VIS 
`elsif CONNECT_BD_AXI_M0_SS_VIS 
`define BIND_BD_AXI_M0_SS_VIS 
`endif

`ifdef BIND_BD_AXI_M0_SS_VIS 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_vis 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M1_SS_VIS 
`define BIND_BD_AXI_M1_SS_VIS 
`elsif CONNECT_BD_AXI_M1_SS_VIS 
`define BIND_BD_AXI_M1_SS_VIS 
`endif

`ifdef BIND_BD_AXI_M1_SS_VIS 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_vis 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_SS_VIS 
`define BIND_BD_APB_S_SS_VIS 
`elsif CONNECT_BD_APB_S_SS_VIS 
`define BIND_BD_APB_S_SS_VIS 
`endif

`ifdef BIND_BD_APB_S_SS_VIS 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip 
// -----------------------------------------------------------------------------
`ifdef REPLACE_AXI_S0_DDR_CHIP 
`define BIND_AXI_S0_DDR_CHIP 
`elsif CONNECT_AXI_S0_DDR_CHIP 
`define BIND_AXI_S0_DDR_CHIP 
`endif

`ifdef BIND_AXI_S0_DDR_CHIP 
`ifndef INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`define INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip 
// -----------------------------------------------------------------------------
`ifdef REPLACE_AXI_S1_DDR_CHIP 
`define BIND_AXI_S1_DDR_CHIP 
`elsif CONNECT_AXI_S1_DDR_CHIP 
`define BIND_AXI_S1_DDR_CHIP 
`endif

`ifdef BIND_AXI_S1_DDR_CHIP 
`ifndef INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`define INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip 
// -----------------------------------------------------------------------------
`ifdef REPLACE_AXI_S2_DDR_CHIP 
`define BIND_AXI_S2_DDR_CHIP 
`elsif CONNECT_AXI_S2_DDR_CHIP 
`define BIND_AXI_S2_DDR_CHIP 
`endif

`ifdef BIND_AXI_S2_DDR_CHIP 
`ifndef INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`define INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip 
// -----------------------------------------------------------------------------
`ifdef REPLACE_AXI_S3_DDR_CHIP 
`define BIND_AXI_S3_DDR_CHIP 
`elsif CONNECT_AXI_S3_DDR_CHIP 
`define BIND_AXI_S3_DDR_CHIP 
`endif

`ifdef BIND_AXI_S3_DDR_CHIP 
`ifndef INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`define INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip 
// -----------------------------------------------------------------------------
`ifdef REPLACE_AXI_S4_DDR_CHIP 
`define BIND_AXI_S4_DDR_CHIP 
`elsif CONNECT_AXI_S4_DDR_CHIP 
`define BIND_AXI_S4_DDR_CHIP 
`endif

`ifdef BIND_AXI_S4_DDR_CHIP 
`ifndef INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`define INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip 
// -----------------------------------------------------------------------------
`ifdef REPLACE_AXI_S5_DDR_CHIP 
`define BIND_AXI_S5_DDR_CHIP 
`elsif CONNECT_AXI_S5_DDR_CHIP 
`define BIND_AXI_S5_DDR_CHIP 
`endif

`ifdef BIND_AXI_S5_DDR_CHIP 
`ifndef INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`define INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S0_DDR_CHIP 
`define BIND_BD_APB_S0_DDR_CHIP 
`elsif CONNECT_BD_APB_S0_DDR_CHIP 
`define BIND_BD_APB_S0_DDR_CHIP 
`endif

`ifdef BIND_BD_APB_S0_DDR_CHIP 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S1_DDR_CHIP 
`define BIND_BD_APB_S1_DDR_CHIP 
`elsif CONNECT_BD_APB_S1_DDR_CHIP 
`define BIND_BD_APB_S1_DDR_CHIP 
`endif

`ifdef BIND_BD_APB_S1_DDR_CHIP 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_mem.u_sram_slave_group 
// -----------------------------------------------------------------------------
`ifdef REPLACE_AXI_S_SRAM_SLAVE_GROUP 
`define BIND_AXI_S_SRAM_SLAVE_GROUP 
`elsif CONNECT_AXI_S_SRAM_SLAVE_GROUP 
`define BIND_AXI_S_SRAM_SLAVE_GROUP 
`endif

`ifdef BIND_AXI_S_SRAM_SLAVE_GROUP 
`ifndef INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`define INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_sf 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M_SS_SF 
`define BIND_BD_AXI_M_SS_SF 
`elsif CONNECT_BD_AXI_M_SS_SF 
`define BIND_BD_AXI_M_SS_SF 
`endif

`ifdef BIND_BD_AXI_M_SS_SF 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_sf 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_S_SS_SF 
`define BIND_BD_AXI_S_SS_SF 
`elsif CONNECT_BD_AXI_S_SS_SF 
`define BIND_BD_AXI_S_SS_SF 
`endif

`ifdef BIND_BD_AXI_S_SS_SF 
`ifndef INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`define INCLUDE_SVT_AXI_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_sf 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_M_SS_SF 
`define BIND_BD_APB_M_SS_SF 
`elsif CONNECT_BD_APB_M_SS_SF 
`define BIND_BD_APB_M_SS_SF 
`endif

`ifdef BIND_BD_APB_M_SS_SF 
`ifndef INCLUDE_SVT_APB_MASTER_BIND_IF 
`define INCLUDE_SVT_APB_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_sf 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_SS_SF 
`define BIND_BD_APB_S_SS_SF 
`elsif CONNECT_BD_APB_S_SS_SF 
`define BIND_BD_APB_S_SS_SF 
`endif

`ifdef BIND_BD_APB_S_SS_SF 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_vout 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_AXI_M_SS_VOUT 
`define BIND_BD_AXI_M_SS_VOUT 
`elsif CONNECT_BD_AXI_M_SS_VOUT 
`define BIND_BD_AXI_M_SS_VOUT 
`endif

`ifdef BIND_BD_AXI_M_SS_VOUT 
`ifndef INCLUDE_SVT_AXI_MASTER_BIND_IF 
`define INCLUDE_SVT_AXI_MASTER_BIND_IF 
`endif
`endif

// Set up the replace/connect infrastructure for `CORETOP.u_ss_vout 
// -----------------------------------------------------------------------------
`ifdef REPLACE_BD_APB_S_SS_VOUT 
`define BIND_BD_APB_S_SS_VOUT 
`elsif CONNECT_BD_APB_S_SS_VOUT 
`define BIND_BD_APB_S_SS_VOUT 
`endif

`ifdef BIND_BD_APB_S_SS_VOUT 
`ifndef INCLUDE_SVT_APB_SLAVE_BIND_IF 
`define INCLUDE_SVT_APB_SLAVE_BIND_IF 
`endif
`endif

module coretop_dut_wrapper();

  // VIP Interface for axi_system_env_0
  svt_axi_if coretop_axi_if_0();

  // VIP Interface for apb_system_env_0
  svt_apb_if coretop_apb_if_0();

  // VIP Interface for ahb_system_env_0
  svt_ahb_if coretop_ahb_if_0();

  // VIP Interface for apb_system_env_1
  svt_apb_if coretop_apb_if_1();

  // VIP Interface for apb_system_env_2
  svt_apb_if coretop_apb_if_2();

  // VIP Interface for apb_system_env_3
  svt_apb_if coretop_apb_if_3();

  // VIP Interface for apb_system_env_4
  svt_apb_if coretop_apb_if_4();

  // XMR clock connections for coretop_axi_if_0 
`ifdef REPLACE_BD_AXI_M_AUDTOP 
  assign coretop_axi_if_0.master_if[0].aclk = `CORETOP.u_audtop.aclk; 
`elsif CONNECT_BD_AXI_M_AUDTOP 
  assign coretop_axi_if_0.master_if[0].aclk = `CORETOP.u_audtop.aclk; 
`else
  assign coretop_axi_if_0.master_if[0].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_M_CQTOP 
  assign coretop_axi_if_0.master_if[1].aclk = `CORETOP.u_cqtop.aclk; 
`elsif CONNECT_BD_AXI_M_CQTOP 
  assign coretop_axi_if_0.master_if[1].aclk = `CORETOP.u_cqtop.aclk; 
`else
  assign coretop_axi_if_0.master_if[1].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_M_DMATOP 
  assign coretop_axi_if_0.master_if[2].aclk = `CORETOP.u_dmatop.aclk; 
`elsif CONNECT_BD_AXI_M_DMATOP 
  assign coretop_axi_if_0.master_if[2].aclk = `CORETOP.u_dmatop.aclk; 
`else
  assign coretop_axi_if_0.master_if[2].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_M_FMTOP 
  assign coretop_axi_if_0.master_if[3].aclk = `CORETOP.u_fmtop.aclk; 
`elsif CONNECT_BD_AXI_M_FMTOP 
  assign coretop_axi_if_0.master_if[3].aclk = `CORETOP.u_fmtop.aclk; 
`else
  assign coretop_axi_if_0.master_if[3].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_M_PERITOP 
  assign coretop_axi_if_0.master_if[4].aclk = `CORETOP.u_peritop.aclk; 
`elsif CONNECT_BD_AXI_M_PERITOP 
  assign coretop_axi_if_0.master_if[4].aclk = `CORETOP.u_peritop.aclk; 
`else
  assign coretop_axi_if_0.master_if[4].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_M_HSMTOP 
  assign coretop_axi_if_0.master_if[5].aclk = `CORETOP.u_hsmtop.aclk; 
`elsif CONNECT_BD_AXI_M_HSMTOP 
  assign coretop_axi_if_0.master_if[5].aclk = `CORETOP.u_hsmtop.aclk; 
`else
  assign coretop_axi_if_0.master_if[5].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_S_UCIE 
  assign coretop_axi_if_0.slave_if[0].aclk = `CORETOP.u_ucie_0.aclk; 
`elsif CONNECT_BD_AXI_S_UCIE 
  assign coretop_axi_if_0.slave_if[0].aclk = `CORETOP.u_ucie_0.aclk; 
`else
  assign coretop_axi_if_0.slave_if[0].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_M_UCIE 
  assign coretop_axi_if_0.master_if[6].aclk = `CORETOP.u_ucie_0.aclk; 
`elsif CONNECT_BD_AXI_M_UCIE 
  assign coretop_axi_if_0.master_if[6].aclk = `CORETOP.u_ucie_0.aclk; 
`else
  assign coretop_axi_if_0.master_if[6].aclk = 0;
`endif
`ifdef REPLACEC_BD_AXI_M_SS_CDEC 
  assign coretop_axi_if_0.master_if[7].aclk = `CORETOP.u_ss_cdec.aclk; 
`elsif CONNECT_BD_AXI_M_SS_CDEC 
  assign coretop_axi_if_0.master_if[7].aclk = `CORETOP.u_ss_cdec.aclk; 
`else
  assign coretop_axi_if_0.master_if[7].aclk = 0;
`endif
`ifdef REPLACE_BD_ACE_M0_SS_CMP 
  assign coretop_axi_if_0.master_if[8].aclk = `CORETOP.u_ss_cmp.aclk; 
`elsif CONNECT_BD_ACE_M0_SS_CMP 
  assign coretop_axi_if_0.master_if[8].aclk = `CORETOP.u_ss_cmp.aclk; 
`else
  assign coretop_axi_if_0.master_if[8].aclk = 0;
`endif
`ifdef REPLACE_BD_ACE_M1_SS_CMP 
  assign coretop_axi_if_0.master_if[9].aclk = `CORETOP.u_ss_cmp.aclk; 
`elsif CONNECT_BD_ACE_M1_SS_CMP 
  assign coretop_axi_if_0.master_if[9].aclk = `CORETOP.u_ss_cmp.aclk; 
`else
  assign coretop_axi_if_0.master_if[9].aclk = 0;
`endif
`ifdef REPLACE_BD_ACE_M2_SS_CMP 
  assign coretop_axi_if_0.master_if[10].aclk = `CORETOP.u_ss_cmp.aclk; 
`elsif CONNECT_BD_ACE_M2_SS_CMP 
  assign coretop_axi_if_0.master_if[10].aclk = `CORETOP.u_ss_cmp.aclk; 
`else
  assign coretop_axi_if_0.master_if[10].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_M_SS_CON 
  assign coretop_axi_if_0.master_if[11].aclk = `CORETOP.u_ss_con.aclk; 
`elsif CONNECT_BD_AXI_M_SS_CON 
  assign coretop_axi_if_0.master_if[11].aclk = `CORETOP.u_ss_con.aclk; 
`else
  assign coretop_axi_if_0.master_if[11].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_S_SS_CON 
  assign coretop_axi_if_0.slave_if[1].aclk = `CORETOP.u_ss_con.aclk; 
`elsif CONNECT_BD_AXI_S_SS_CON 
  assign coretop_axi_if_0.slave_if[1].aclk = `CORETOP.u_ss_con.aclk; 
`else
  assign coretop_axi_if_0.slave_if[1].aclk = 0;
`endif
`ifdef REPLACE_BD_ACE_M_SS_CPU 
  assign coretop_axi_if_0.master_if[12].aclk = `CORETOP.u_ss_cpu.aclk; 
`elsif CONNECT_BD_ACE_M_SS_CPU 
  assign coretop_axi_if_0.master_if[12].aclk = `CORETOP.u_ss_cpu.aclk; 
`else
  assign coretop_axi_if_0.master_if[12].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_S_SS_CPU 
  assign coretop_axi_if_0.slave_if[2].aclk = `CORETOP.u_ss_cpu.aclk; 
`elsif CONNECT_BD_AXI_S_SS_CPU 
  assign coretop_axi_if_0.slave_if[2].aclk = `CORETOP.u_ss_cpu.aclk; 
`else
  assign coretop_axi_if_0.slave_if[2].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_M0_SS_VIS 
  assign coretop_axi_if_0.master_if[13].aclk = `CORETOP.u_ss_vis.aclk; 
`elsif CONNECT_BD_AXI_M0_SS_VIS 
  assign coretop_axi_if_0.master_if[13].aclk = `CORETOP.u_ss_vis.aclk; 
`else
  assign coretop_axi_if_0.master_if[13].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_M1_SS_VIS 
  assign coretop_axi_if_0.master_if[14].aclk = `CORETOP.u_ss_vis.aclk; 
`elsif CONNECT_BD_AXI_M1_SS_VIS 
  assign coretop_axi_if_0.master_if[14].aclk = `CORETOP.u_ss_vis.aclk; 
`else
  assign coretop_axi_if_0.master_if[14].aclk = 0;
`endif
`ifdef REPLACE_AXI_S0_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[3].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_0; 
`elsif CONNECT_AXI_S0_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[3].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_0; 
`else
  assign coretop_axi_if_0.slave_if[3].aclk = 0;
`endif
`ifdef REPLACE_AXI_S1_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[4].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_1; 
`elsif CONNECT_AXI_S1_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[4].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_1; 
`else
  assign coretop_axi_if_0.slave_if[4].aclk = 0;
`endif
`ifdef REPLACE_AXI_S2_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[5].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_2; 
`elsif CONNECT_AXI_S2_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[5].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_2; 
`else
  assign coretop_axi_if_0.slave_if[5].aclk = 0;
`endif
`ifdef REPLACE_AXI_S3_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[6].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_3; 
`elsif CONNECT_AXI_S3_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[6].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_3; 
`else
  assign coretop_axi_if_0.slave_if[6].aclk = 0;
`endif
`ifdef REPLACE_AXI_S4_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[7].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_4; 
`elsif CONNECT_AXI_S4_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[7].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_4; 
`else
  assign coretop_axi_if_0.slave_if[7].aclk = 0;
`endif
`ifdef REPLACE_AXI_S5_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[8].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_5; 
`elsif CONNECT_AXI_S5_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[8].aclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aclk_5; 
`else
  assign coretop_axi_if_0.slave_if[8].aclk = 0;
`endif
`ifdef REPLACE_AXI_S_SRAM_SLAVE_GROUP 
  assign coretop_axi_if_0.slave_if[9].aclk = `CORETOP.u_ss_mem.u_sram_slave_group.clk; 
`elsif CONNECT_AXI_S_SRAM_SLAVE_GROUP 
  assign coretop_axi_if_0.slave_if[9].aclk = `CORETOP.u_ss_mem.u_sram_slave_group.clk; 
`else
  assign coretop_axi_if_0.slave_if[9].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_M_SS_SF 
  assign coretop_axi_if_0.master_if[15].aclk = `CORETOP.u_ss_sf.aclk; 
`elsif CONNECT_BD_AXI_M_SS_SF 
  assign coretop_axi_if_0.master_if[15].aclk = `CORETOP.u_ss_sf.aclk; 
`else
  assign coretop_axi_if_0.master_if[15].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_S_SS_SF 
  assign coretop_axi_if_0.slave_if[10].aclk = `CORETOP.u_ss_sf.aclk; 
`elsif CONNECT_BD_AXI_S_SS_SF 
  assign coretop_axi_if_0.slave_if[10].aclk = `CORETOP.u_ss_sf.aclk; 
`else
  assign coretop_axi_if_0.slave_if[10].aclk = 0;
`endif
`ifdef REPLACE_BD_AXI_M_SS_VOUT 
  assign coretop_axi_if_0.master_if[16].aclk = `CORETOP.u_ss_vout.aclk; 
`elsif CONNECT_BD_AXI_M_SS_VOUT 
  assign coretop_axi_if_0.master_if[16].aclk = `CORETOP.u_ss_vout.aclk; 
`else
  assign coretop_axi_if_0.master_if[16].aclk = 0;
`endif

  // XMR reset connections for coretop_axi_if_0 
`ifdef REPLACE_BD_AXI_M_AUDTOP 
  assign coretop_axi_if_0.master_if[0].aresetn = ~`CORETOP.u_audtop.rst_aud;
`elsif CONNECT_BD_AXI_M_AUDTOP 
  assign coretop_axi_if_0.master_if[0].aresetn = ~`CORETOP.u_audtop.rst_aud;
`else
  assign coretop_axi_if_0.master_if[0].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_M_CQTOP 
  assign coretop_axi_if_0.master_if[1].aresetn = ~`CORETOP.u_cqtop.rst_cq; 
`elsif CONNECT_BD_AXI_M_CQTOP 
  assign coretop_axi_if_0.master_if[1].aresetn = ~`CORETOP.u_cqtop.rst_cq; 
`else
  assign coretop_axi_if_0.master_if[1].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_M_DMATOP 
  assign coretop_axi_if_0.master_if[2].aresetn = ~`CORETOP.u_dmatop.rst_dma; 
`elsif CONNECT_BD_AXI_M_DMATOP 
  assign coretop_axi_if_0.master_if[2].aresetn = ~`CORETOP.u_dmatop.rst_dma; 
`else
  assign coretop_axi_if_0.master_if[2].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_M_FMTOP 
  assign coretop_axi_if_0.master_if[3].aresetn = ~`CORETOP.u_fmtop.rst_fm; 
`elsif CONNECT_BD_AXI_M_FMTOP 
  assign coretop_axi_if_0.master_if[3].aresetn = ~`CORETOP.u_fmtop.rst_fm; 
`else
  assign coretop_axi_if_0.master_if[3].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_M_PERITOP 
  assign coretop_axi_if_0.master_if[4].aresetn = ~`CORETOP.u_peritop.reset; 
`elsif CONNECT_BD_AXI_M_PERITOP 
  assign coretop_axi_if_0.master_if[4].aresetn = ~`CORETOP.u_peritop.reset; 
`else
  assign coretop_axi_if_0.master_if[4].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_M_HSMTOP 
  assign coretop_axi_if_0.master_if[5].aresetn = ~`CORETOP.u_hsmtop.rst_hsm; 
`elsif CONNECT_BD_AXI_M_HSMTOP 
  assign coretop_axi_if_0.master_if[5].aresetn = ~`CORETOP.u_hsmtop.rst_hsm; 
`else
  assign coretop_axi_if_0.master_if[5].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_S_UCIE 
  assign coretop_axi_if_0.slave_if[0].aresetn = ~`CORETOP.u_ucie_0.rst_ucie; 
`elsif CONNECT_BD_AXI_S_UCIE 
  assign coretop_axi_if_0.slave_if[0].aresetn = ~`CORETOP.u_ucie_0.rst_ucie; 
`else
  assign coretop_axi_if_0.slave_if[0].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_M_UCIE 
  assign coretop_axi_if_0.master_if[6].aresetn = ~`CORETOP.u_ucie_0.rst_ucie; 
`elsif CONNECT_BD_AXI_M_UCIE 
  assign coretop_axi_if_0.master_if[6].aresetn = ~`CORETOP.u_ucie_0.rst_ucie; 
`else
  assign coretop_axi_if_0.master_if[6].aresetn = 0;
`endif
`ifdef REPLACEC_BD_AXI_M_SS_CDEC 
  assign coretop_axi_if_0.master_if[7].aresetn = ~`CORETOP.u_ss_cdec.rst_ss_cdec; 
`elsif CONNECT_BD_AXI_M_SS_CDEC 
  assign coretop_axi_if_0.master_if[7].aresetn = ~`CORETOP.u_ss_cdec.rst_ss_cdec; 
`else
  assign coretop_axi_if_0.master_if[7].aresetn = 0;
`endif
`ifdef REPLACE_BD_ACE_M0_SS_CMP 
  assign coretop_axi_if_0.master_if[8].aresetn = ~`CORETOP.u_ss_cmp.rst_ss_cmp; 
`elsif CONNECT_BD_ACE_M0_SS_CMP 
  assign coretop_axi_if_0.master_if[8].aresetn = ~`CORETOP.u_ss_cmp.rst_ss_cmp; 
`else
  assign coretop_axi_if_0.master_if[8].aresetn = 0;
`endif
`ifdef REPLACE_BD_ACE_M1_SS_CMP 
  assign coretop_axi_if_0.master_if[9].aresetn = ~`CORETOP.u_ss_cmp.rst_ss_cmp; 
`elsif CONNECT_BD_ACE_M1_SS_CMP 
  assign coretop_axi_if_0.master_if[9].aresetn = ~`CORETOP.u_ss_cmp.rst_ss_cmp; 
`else
  assign coretop_axi_if_0.master_if[9].aresetn = 0;
`endif
`ifdef REPLACE_BD_ACE_M2_SS_CMP 
  assign coretop_axi_if_0.master_if[10].aresetn = ~`CORETOP.u_ss_cmp.rst_ss_cmp; 
`elsif CONNECT_BD_ACE_M2_SS_CMP 
  assign coretop_axi_if_0.master_if[10].aresetn = ~`CORETOP.u_ss_cmp.rst_ss_cmp; 
`else
  assign coretop_axi_if_0.master_if[10].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_M_SS_CON 
  assign coretop_axi_if_0.master_if[11].aresetn = ~`CORETOP.u_ss_con.rst_ss_con; 
`elsif CONNECT_BD_AXI_M_SS_CON 
  assign coretop_axi_if_0.master_if[11].aresetn = ~`CORETOP.u_ss_con.rst_ss_con; 
`else
  assign coretop_axi_if_0.master_if[11].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_S_SS_CON 
  assign coretop_axi_if_0.slave_if[1].aresetn = ~`CORETOP.u_ss_con.rst_ss_con; 
`elsif CONNECT_BD_AXI_S_SS_CON 
  assign coretop_axi_if_0.slave_if[1].aresetn = ~`CORETOP.u_ss_con.rst_ss_con; 
`else
  assign coretop_axi_if_0.slave_if[1].aresetn = 0;
`endif
`ifdef REPLACE_BD_ACE_M_SS_CPU 
  assign coretop_axi_if_0.master_if[12].aresetn = ~`CORETOP.u_ss_cpu.rst_ss_cpu; 
`elsif CONNECT_BD_ACE_M_SS_CPU 
  assign coretop_axi_if_0.master_if[12].aresetn = ~`CORETOP.u_ss_cpu.rst_ss_cpu; 
`else
  assign coretop_axi_if_0.master_if[12].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_S_SS_CPU 
  assign coretop_axi_if_0.slave_if[2].aresetn = ~`CORETOP.u_ss_cpu.rst_ss_cpu; 
`elsif CONNECT_BD_AXI_S_SS_CPU 
  assign coretop_axi_if_0.slave_if[2].aresetn = ~`CORETOP.u_ss_cpu.rst_ss_cpu; 
`else
  assign coretop_axi_if_0.slave_if[2].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_M0_SS_VIS 
  assign coretop_axi_if_0.master_if[13].aresetn = ~`CORETOP.u_ss_vis.rst_ss_vis; 
`elsif CONNECT_BD_AXI_M0_SS_VIS 
  assign coretop_axi_if_0.master_if[13].aresetn = ~`CORETOP.u_ss_vis.rst_ss_vis; 
`else
  assign coretop_axi_if_0.master_if[13].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_M1_SS_VIS 
  assign coretop_axi_if_0.master_if[14].aresetn = ~`CORETOP.u_ss_vis.rst_ss_vis; 
`elsif CONNECT_BD_AXI_M1_SS_VIS 
  assign coretop_axi_if_0.master_if[14].aresetn = ~`CORETOP.u_ss_vis.rst_ss_vis; 
`else
  assign coretop_axi_if_0.master_if[14].aresetn = 0;
`endif
`ifdef REPLACE_AXI_S0_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[3].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_0; 
`elsif CONNECT_AXI_S0_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[3].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_0; 
`else
  assign coretop_axi_if_0.slave_if[3].aresetn = 0;
`endif
`ifdef REPLACE_AXI_S1_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[4].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_1; 
`elsif CONNECT_AXI_S1_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[4].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_1; 
`else
  assign coretop_axi_if_0.slave_if[4].aresetn = 0;
`endif
`ifdef REPLACE_AXI_S2_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[5].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_2; 
`elsif CONNECT_AXI_S2_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[5].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_2; 
`else
  assign coretop_axi_if_0.slave_if[5].aresetn = 0;
`endif
`ifdef REPLACE_AXI_S3_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[6].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_3; 
`elsif CONNECT_AXI_S3_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[6].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_3; 
`else
  assign coretop_axi_if_0.slave_if[6].aresetn = 0;
`endif
`ifdef REPLACE_AXI_S4_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[7].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_4; 
`elsif CONNECT_AXI_S4_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[7].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_4; 
`else
  assign coretop_axi_if_0.slave_if[7].aresetn = 0;
`endif
`ifdef REPLACE_AXI_S5_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[8].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_5; 
`elsif CONNECT_AXI_S5_DDR_CHIP 
  assign coretop_axi_if_0.slave_if[8].aresetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.aresetn_5; 
`else
  assign coretop_axi_if_0.slave_if[8].aresetn = 0;
`endif
`ifdef REPLACE_AXI_S_SRAM_SLAVE_GROUP 
  assign coretop_axi_if_0.slave_if[9].aresetn = ~`CORETOP.u_ss_mem.u_sram_slave_group.rst; 
`elsif CONNECT_AXI_S_SRAM_SLAVE_GROUP 
  assign coretop_axi_if_0.slave_if[9].aresetn = ~`CORETOP.u_ss_mem.u_sram_slave_group.rst; 
`else
  assign coretop_axi_if_0.slave_if[9].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_M_SS_SF 
  assign coretop_axi_if_0.master_if[15].aresetn = ~`CORETOP.u_ss_sf.rst_ss_sf; 
`elsif CONNECT_BD_AXI_M_SS_SF 
  assign coretop_axi_if_0.master_if[15].aresetn = ~`CORETOP.u_ss_sf.rst_ss_sf; 
`else
  assign coretop_axi_if_0.master_if[15].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_S_SS_SF 
  assign coretop_axi_if_0.slave_if[10].aresetn = ~`CORETOP.u_ss_sf.rst_ss_sf; 
`elsif CONNECT_BD_AXI_S_SS_SF 
  assign coretop_axi_if_0.slave_if[10].aresetn = ~`CORETOP.u_ss_sf.rst_ss_sf; 
`else
  assign coretop_axi_if_0.slave_if[10].aresetn = 0;
`endif
`ifdef REPLACE_BD_AXI_M_SS_VOUT 
  assign coretop_axi_if_0.master_if[16].aresetn = ~`CORETOP.u_ss_vout.reset; 
`elsif CONNECT_BD_AXI_M_SS_VOUT 
  assign coretop_axi_if_0.master_if[16].aresetn = ~`CORETOP.u_ss_vout.reset; 
`else
  assign coretop_axi_if_0.master_if[16].aresetn = 0;
`endif

  // XMR clock connections for coretop_apb_if_0 
`ifdef REPLACE_BD_APB_S_AUDTOP 
  assign coretop_apb_if_0.slave_if[0].pclk = `CORETOP.u_audtop.pclk; 
`elsif CONNECT_BD_APB_S_AUDTOP 
  assign coretop_apb_if_0.slave_if[0].pclk = `CORETOP.u_audtop.pclk; 
`else
  assign coretop_apb_if_0.slave_if[0].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S_DMATOP 
  assign coretop_apb_if_0.slave_if[1].pclk = `CORETOP.u_dmatop.pclk; 
`elsif CONNECT_BD_APB_S_DMATOP 
  assign coretop_apb_if_0.slave_if[1].pclk = `CORETOP.u_dmatop.pclk; 
`else
  assign coretop_apb_if_0.slave_if[1].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S_FMTOP 
  assign coretop_apb_if_0.slave_if[2].pclk = `CORETOP.u_fmtop.pclk; 
`elsif CONNECT_BD_APB_S_FMTOP 
  assign coretop_apb_if_0.slave_if[2].pclk = `CORETOP.u_fmtop.pclk; 
`else
  assign coretop_apb_if_0.slave_if[2].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S_GTOP 
  assign coretop_apb_if_0.slave_if[3].pclk = `CORETOP.u_gtop.pclk;
`elsif CONNECT_BD_APB_S_GTOP 
  assign coretop_apb_if_0.slave_if[3].pclk = `CORETOP.u_gtop.pclk; 
`else
  assign coretop_apb_if_0.slave_if[3].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S0_PERITOP 
  assign coretop_apb_if_0.slave_if[4].pclk = `CORETOP.u_peritop.pclk; 
`elsif CONNECT_BD_APB_S0_PERITOP 
  assign coretop_apb_if_0.slave_if[4].pclk = `CORETOP.u_peritop.pclk; 
`else
  assign coretop_apb_if_0.slave_if[4].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S1_PERITOP 
  assign coretop_apb_if_0.slave_if[5].pclk = `CORETOP.u_peritop.pclk_s1_peri; 
`elsif CONNECT_BD_APB_S1_PERITOP 
  assign coretop_apb_if_0.slave_if[5].pclk = `CORETOP.u_peritop.pclk_s1_peri; 
`else
  assign coretop_apb_if_0.slave_if[5].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S_HSMTOP 
  assign coretop_apb_if_0.slave_if[6].pclk = `CORETOP.u_hsmtop.pclk_s_hsm; 
`elsif CONNECT_BD_APB_S_HSMTOP 
  assign coretop_apb_if_0.slave_if[6].pclk = `CORETOP.u_hsmtop.pclk_s_hsm; 
`else
  assign coretop_apb_if_0.slave_if[6].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S_UCIE 
  assign coretop_apb_if_0.slave_if[7].pclk = `CORETOP.u_ucie_0.pclk; 
`elsif CONNECT_BD_APB_S_UCIE 
  assign coretop_apb_if_0.slave_if[7].pclk = `CORETOP.u_ucie_0.pclk; 
`else
  assign coretop_apb_if_0.slave_if[7].pclk = 0;
`endif
`ifdef REPLACEC_BD_APB_S_SS_CDEC 
  assign coretop_apb_if_0.slave_if[8].pclk = `CORETOP.u_ss_cdec.pclk; 
`elsif CONNECT_BD_APB_S_SS_CDEC 
  assign coretop_apb_if_0.slave_if[8].pclk = `CORETOP.u_ss_cdec.pclk; 
`else
  assign coretop_apb_if_0.slave_if[8].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_CMP 
  assign coretop_apb_if_0.slave_if[9].pclk = `CORETOP.u_ss_cmp.pclk; 
`elsif CONNECT_BD_APB_S_SS_CMP 
  assign coretop_apb_if_0.slave_if[9].pclk = `CORETOP.u_ss_cmp.pclk; 
`else
  assign coretop_apb_if_0.slave_if[9].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_CON 
  assign coretop_apb_if_0.slave_if[10].pclk = `CORETOP.u_ss_con.pclk; 
`elsif CONNECT_BD_APB_S_SS_CON 
  assign coretop_apb_if_0.slave_if[10].pclk = `CORETOP.u_ss_con.pclk; 
`else
  assign coretop_apb_if_0.slave_if[10].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_CPU 
  assign coretop_apb_if_0.slave_if[11].pclk = `CORETOP.u_ss_cpu.pclk; 
`elsif CONNECT_BD_APB_S_SS_CPU 
  assign coretop_apb_if_0.slave_if[11].pclk = `CORETOP.u_ss_cpu.pclk; 
`else
  assign coretop_apb_if_0.slave_if[11].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_VIS 
  assign coretop_apb_if_0.slave_if[12].pclk = `CORETOP.u_ss_vis.pclk; 
`elsif CONNECT_BD_APB_S_SS_VIS 
  assign coretop_apb_if_0.slave_if[12].pclk = `CORETOP.u_ss_vis.pclk; 
`else
  assign coretop_apb_if_0.slave_if[12].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S0_DDR_CHIP 
  assign coretop_apb_if_0.slave_if[13].pclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.pclk_ctl; 
`elsif CONNECT_BD_APB_S0_DDR_CHIP 
  assign coretop_apb_if_0.slave_if[13].pclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.pclk_ctl; 
`else
  assign coretop_apb_if_0.slave_if[13].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S1_DDR_CHIP 
  assign coretop_apb_if_0.slave_if[14].pclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.pclk_phy; 
`elsif CONNECT_BD_APB_S1_DDR_CHIP 
  assign coretop_apb_if_0.slave_if[14].pclk = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.pclk_phy; 
`else
  assign coretop_apb_if_0.slave_if[14].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_SF 
  assign coretop_apb_if_0.slave_if[15].pclk = `CORETOP.u_ss_sf.pclk; 
`elsif CONNECT_BD_APB_S_SS_SF 
  assign coretop_apb_if_0.slave_if[15].pclk = `CORETOP.u_ss_sf.pclk; 
`else
  assign coretop_apb_if_0.slave_if[15].pclk = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_VOUT 
  assign coretop_apb_if_0.slave_if[16].pclk = `CORETOP.u_ss_vout.pclk; 
`elsif CONNECT_BD_APB_S_SS_VOUT 
  assign coretop_apb_if_0.slave_if[16].pclk = `CORETOP.u_ss_vout.pclk; 
`else
  assign coretop_apb_if_0.slave_if[16].pclk = 0;
`endif

  // XMR reset connections for coretop_apb_if_0 
`ifdef REPLACE_BD_APB_S_AUDTOP 
  assign coretop_apb_if_0.slave_if[0].presetn = ~`CORETOP.u_audtop.rst_aud; 
`elsif CONNECT_BD_APB_S_AUDTOP 
  assign coretop_apb_if_0.slave_if[0].presetn = ~`CORETOP.u_audtop.rst_aud; 
`else
  assign coretop_apb_if_0.slave_if[0].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S_DMATOP 
  assign coretop_apb_if_0.slave_if[1].presetn = ~`CORETOP.u_dmatop.rst_dma; 
`elsif CONNECT_BD_APB_S_DMATOP 
  assign coretop_apb_if_0.slave_if[1].presetn = ~`CORETOP.u_dmatop.rst_dma; 
`else
  assign coretop_apb_if_0.slave_if[1].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S_FMTOP 
  assign coretop_apb_if_0.slave_if[2].presetn = ~`CORETOP.u_fmtop.rst_fm; 
`elsif CONNECT_BD_APB_S_FMTOP 
  assign coretop_apb_if_0.slave_if[2].presetn = ~`CORETOP.u_fmtop.rst_fm; 
`else
  assign coretop_apb_if_0.slave_if[2].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S_GTOP 
  assign coretop_apb_if_0.slave_if[3].presetn = `CORETOP.u_gtop.xprstn; 
`elsif CONNECT_BD_APB_S_GTOP 
  assign coretop_apb_if_0.slave_if[3].presetn = `CORETOP.u_gtop.xprstn; 
`else
  assign coretop_apb_if_0.slave_if[3].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S0_PERITOP 
  assign coretop_apb_if_0.slave_if[4].presetn = ~`CORETOP.u_peritop.reset; 
`elsif CONNECT_BD_APB_S0_PERITOP 
  assign coretop_apb_if_0.slave_if[4].presetn = ~`CORETOP.u_peritop.reset; 
`else
  assign coretop_apb_if_0.slave_if[4].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S1_PERITOP 
  assign coretop_apb_if_0.slave_if[5].presetn = ~`CORETOP.u_peritop.reset; 
`elsif CONNECT_BD_APB_S1_PERITOP 
  assign coretop_apb_if_0.slave_if[5].presetn = ~`CORETOP.u_peritop.reset; 
`else
  assign coretop_apb_if_0.slave_if[5].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S_HSMTOP 
  assign coretop_apb_if_0.slave_if[6].presetn = ~`CORETOP.u_hsmtop.rst_hsm; 
`elsif CONNECT_BD_APB_S_HSMTOP 
  assign coretop_apb_if_0.slave_if[6].presetn = ~`CORETOP.u_hsmtop.rst_hsm; 
`else
  assign coretop_apb_if_0.slave_if[6].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S_UCIE 
  assign coretop_apb_if_0.slave_if[7].presetn = ~`CORETOP.u_ucie_0.rst_ucie; 
`elsif CONNECT_BD_APB_S_UCIE 
  assign coretop_apb_if_0.slave_if[7].presetn = ~`CORETOP.u_ucie_0.rst_ucie; 
`else
  assign coretop_apb_if_0.slave_if[7].presetn = 0;
`endif
`ifdef REPLACEC_BD_APB_S_SS_CDEC 
  assign coretop_apb_if_0.slave_if[8].presetn = ~`CORETOP.u_ss_cdec.rst_ss_cdec; 
`elsif CONNECT_BD_APB_S_SS_CDEC 
  assign coretop_apb_if_0.slave_if[8].presetn = ~`CORETOP.u_ss_cdec.rst_ss_cdec; 
`else
  assign coretop_apb_if_0.slave_if[8].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_CMP 
  assign coretop_apb_if_0.slave_if[9].presetn = ~`CORETOP.u_ss_cmp.rst_ss_cmp; 
`elsif CONNECT_BD_APB_S_SS_CMP 
  assign coretop_apb_if_0.slave_if[9].presetn = ~`CORETOP.u_ss_cmp.rst_ss_cmp; 
`else
  assign coretop_apb_if_0.slave_if[9].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_CON 
  assign coretop_apb_if_0.slave_if[10].presetn = ~`CORETOP.u_ss_con.rst_ss_con; 
`elsif CONNECT_BD_APB_S_SS_CON 
  assign coretop_apb_if_0.slave_if[10].presetn = ~`CORETOP.u_ss_con.rst_ss_con; 
`else
  assign coretop_apb_if_0.slave_if[10].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_CPU 
  assign coretop_apb_if_0.slave_if[11].presetn = ~`CORETOP.u_ss_cpu.rst_ss_cpu; 
`elsif CONNECT_BD_APB_S_SS_CPU 
  assign coretop_apb_if_0.slave_if[11].presetn = ~`CORETOP.u_ss_cpu.rst_ss_cpu; 
`else
  assign coretop_apb_if_0.slave_if[11].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_VIS 
  assign coretop_apb_if_0.slave_if[12].presetn = ~`CORETOP.u_ss_vis.rst_ss_vis; 
`elsif CONNECT_BD_APB_S_SS_VIS 
  assign coretop_apb_if_0.slave_if[12].presetn = ~`CORETOP.u_ss_vis.rst_ss_vis; 
`else
  assign coretop_apb_if_0.slave_if[12].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S0_DDR_CHIP 
  assign coretop_apb_if_0.slave_if[13].presetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.presetn_ctl; 
`elsif CONNECT_BD_APB_S0_DDR_CHIP 
  assign coretop_apb_if_0.slave_if[13].presetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.presetn_ctl; 
`else
  assign coretop_apb_if_0.slave_if[13].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S1_DDR_CHIP 
  assign coretop_apb_if_0.slave_if[14].presetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.presetn_phy; 
`elsif CONNECT_BD_APB_S1_DDR_CHIP 
  assign coretop_apb_if_0.slave_if[14].presetn = `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.presetn_phy; 
`else
  assign coretop_apb_if_0.slave_if[14].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_SF 
  assign coretop_apb_if_0.slave_if[15].presetn = ~`CORETOP.u_ss_sf.rst_ss_sf; 
`elsif CONNECT_BD_APB_S_SS_SF 
  assign coretop_apb_if_0.slave_if[15].presetn = ~`CORETOP.u_ss_sf.rst_ss_sf; 
`else
  assign coretop_apb_if_0.slave_if[15].presetn = 0;
`endif
`ifdef REPLACE_BD_APB_S_SS_VOUT 
  assign coretop_apb_if_0.slave_if[16].presetn = ~`CORETOP.u_ss_vout.reset; 
`elsif CONNECT_BD_APB_S_SS_VOUT 
  assign coretop_apb_if_0.slave_if[16].presetn = ~`CORETOP.u_ss_vout.reset; 
`else
  assign coretop_apb_if_0.slave_if[16].presetn = 0;
`endif

  // XMR clock connections for coretop_ahb_if_0 
`ifdef REPLACE_BD_AHB_S_FMTOP 
  assign coretop_ahb_if_0.slave_if[0].hclk = `CORETOP.u_fmtop.hclk; 
`elsif CONNECT_BD_AHB_S_FMTOP 
  assign coretop_ahb_if_0.slave_if[0].hclk = `CORETOP.u_fmtop.hclk; 
`else
  assign coretop_ahb_if_0.slave_if[0].hclk = 0;
`endif
`ifdef REPLACE_BD_AHB_M_HSMTOP 
  assign coretop_ahb_if_0.master_if[0].hclk = `CORETOP.u_hsmtop.hclk;
`elsif CONNECT_BD_AHB_M_HSMTOP 
  assign coretop_ahb_if_0.master_if[0].hclk = `CORETOP.u_hsmtop.hclk;
`else
  assign coretop_ahb_if_0.master_if[0].hclk = 0;
`endif

  // XMR reset connections for coretop_ahb_if_0 
`ifdef REPLACE_BD_AHB_S_FMTOP 
  assign coretop_ahb_if_0.slave_if[0].hresetn = ~`CORETOP.u_fmtop.rst_fm; 
`elsif CONNECT_BD_AHB_S_FMTOP 
  assign coretop_ahb_if_0.slave_if[0].hresetn = ~`CORETOP.u_fmtop.rst_fm; 
`else
  assign coretop_ahb_if_0.slave_if[0].hresetn = 0;
`endif
`ifdef REPLACE_BD_AHB_M_HSMTOP 
  assign coretop_ahb_if_0.master_if[0].hresetn = ~`CORETOP.u_hsmtop.rst_hsm; 
`elsif CONNECT_BD_AHB_M_HSMTOP 
  assign coretop_ahb_if_0.master_if[0].hresetn = ~`CORETOP.u_hsmtop.rst_hsm; 
`else
  assign coretop_ahb_if_0.master_if[0].hresetn = 0;
`endif

  // XMR clock connections for coretop_apb_if_1 
`ifdef REPLACE_BD_APB_M_PERITOP 
  assign coretop_apb_if_1.pclk = `CORETOP.u_peritop.pclk; 
`elsif CONNECT_BD_APB_M_PERITOP 
  assign coretop_apb_if_1.pclk = `CORETOP.u_peritop.pclk; 
`else
  assign coretop_apb_if_1.pclk = 0;
`endif

  // XMR reset connections for coretop_apb_if_1 
`ifdef REPLACE_BD_APB_M_PERITOP 
  assign coretop_apb_if_1.presetn = ~`CORETOP.u_peritop.reset; 
`elsif CONNECT_BD_APB_M_PERITOP 
  assign coretop_apb_if_1.presetn = ~`CORETOP.u_peritop.reset; 
`else
  assign coretop_apb_if_1.presetn = 0;
`endif

  // XMR clock connections for coretop_apb_if_2 
`ifdef REPLACE_BD_APB_M_HSMTOP 
  assign coretop_apb_if_2.pclk = `CORETOP.u_hsmtop.pclk_m_hsm;
`elsif CONNECT_BD_APB_M_HSMTOP 
  assign coretop_apb_if_2.pclk = `CORETOP.u_hsmtop.pclk_m_hsm;
`else
  assign coretop_apb_if_2.pclk = 0;
`endif

  // XMR reset connections for coretop_apb_if_2 
`ifdef REPLACE_BD_APB_M_HSMTOP 
  assign coretop_apb_if_2.presetn = ~`CORETOP.u_hsmtop.rst_hsm; 
`elsif CONNECT_BD_APB_M_HSMTOP 
  assign coretop_apb_if_2.presetn = ~`CORETOP.u_hsmtop.rst_hsm; 
`else
  assign coretop_apb_if_2.presetn = 0;
`endif

  // XMR clock connections for coretop_apb_if_3 
`ifdef REPLACE_BD_APB_M_SS_CPU 
  assign coretop_apb_if_3.pclk = `CORETOP.u_ss_cpu.pclk; 
`elsif CONNECT_BD_APB_M_SS_CPU 
  assign coretop_apb_if_3.pclk = `CORETOP.u_ss_cpu.pclk; 
`else
  assign coretop_apb_if_3.pclk = 0;
`endif

  // XMR reset connections for coretop_apb_if_3 
`ifdef REPLACE_BD_APB_M_SS_CPU 
  assign coretop_apb_if_3.presetn = ~`CORETOP.u_ss_cpu.rst_ss_cpu; 
`elsif CONNECT_BD_APB_M_SS_CPU 
  assign coretop_apb_if_3.presetn = ~`CORETOP.u_ss_cpu.rst_ss_cpu; 
`else
  assign coretop_apb_if_3.presetn = 0;
`endif

  // XMR clock connections for coretop_apb_if_4 
`ifdef REPLACE_BD_APB_M_SS_SF 
  assign coretop_apb_if_4.pclk = `CORETOP.u_ss_sf.pclk; 
`elsif CONNECT_BD_APB_M_SS_SF 
  assign coretop_apb_if_4.pclk = `CORETOP.u_ss_sf.pclk; 
`else
  assign coretop_apb_if_4.pclk = 0;
`endif

  // XMR reset connections for coretop_apb_if_4 
`ifdef REPLACE_BD_APB_M_SS_SF 
  assign coretop_apb_if_4.presetn = ~`CORETOP.u_ss_sf.rst_ss_sf; 
`elsif CONNECT_BD_APB_M_SS_SF 
  assign coretop_apb_if_4.presetn = ~`CORETOP.u_ss_sf.rst_ss_sf; 
`else
  assign coretop_apb_if_4.presetn = 0;
`endif

`ifdef BIND_BD_AXI_M_AUDTOP 
  bind `CORETOP.u_audtop svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(3), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(64), 
    .WSTRB_WIDTH_PARAM(8), 
    .BID_WIDTH_PARAM(3), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(3), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(3), 
    .RDATA_WIDTH_PARAM(64), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m_audtop_bind_if (
    .awid(awid_m_aud), 
    .awaddr(awaddr_m_aud), 
    .awlen(awlen_m_aud), 
    .awsize(awsize_m_aud), 
    .awburst(awburst_m_aud), 
    .awlock(awlock_m_aud), 
    .awcache(awcache_m_aud), 
    .awprot(awprot_m_aud), 
    .awqos(awqos_m_aud), 
    .awvalid(awvalid_m_aud), 
    .awready(awready_m_aud), 
    .wdata(wdata_m_aud), 
    .wstrb(wstrb_m_aud), 
    .wlast(wlast_m_aud), 
    .wvalid(wvalid_m_aud), 
    .wready(wready_m_aud), 
    .bid(bid_m_aud), 
    .bresp(bresp_m_aud), 
    .bvalid(bvalid_m_aud), 
    .bready(bready_m_aud), 
    .arid(arid_m_aud), 
    .araddr(araddr_m_aud), 
    .arlen(arlen_m_aud), 
    .arsize(arsize_m_aud), 
    .arburst(arburst_m_aud), 
    .arlock(arlock_m_aud), 
    .arcache(arcache_m_aud), 
    .arprot(arprot_m_aud), 
    .arqos(arqos_m_aud), 
    .arvalid(arvalid_m_aud), 
    .arready(arready_m_aud), 
    .rid(rid_m_aud), 
    .rdata(rdata_m_aud), 
    .rresp(rresp_m_aud), 
    .rlast(rlast_m_aud), 
    .rvalid(rvalid_m_aud), 
    .rready(rready_m_aud) 
  );
`endif

`ifdef REPLACE_BD_AXI_M_AUDTOP 

  svt_axi_master_connector#(1) bd_axi_m_audtop(
    .master_if(coretop_axi_if_0.master_if[0]), 
    .master_bind_if(`CORETOP.u_audtop.bd_axi_m_audtop_bind_if) 
  );

`elsif CONNECT_BD_AXI_M_AUDTOP 

  svt_axi_master_connector#(0) bd_axi_m_audtop(
    .master_if(coretop_axi_if_0.master_if[0]), 
    .master_bind_if(`CORETOP.u_audtop.bd_axi_m_audtop_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_AUDTOP 
  bind `CORETOP.u_audtop svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(20), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_audtop_bind_if (
    .paddr(paddr_s_aud), 
    .psel(psel_s_aud), 
    .penable(penable_s_aud), 
    .pwrite(pwrite_s_aud), 
    .prdata(prdata_s_aud), 
    .pwdata(pwdata_s_aud), 
    .pprot(pprot_s_aud), 
    .pstrb(pstrb_s_aud), 
    .pready(pready_s_aud) 
  );
`endif

`ifdef REPLACE_BD_APB_S_AUDTOP 

  svt_apb_slave_connector#(1) bd_apb_s_audtop(
    .slave_if(coretop_apb_if_0.slave_if[0]), 
    .slave_bind_if(`CORETOP.u_audtop.bd_apb_s_audtop_bind_if) 
  );

`elsif CONNECT_BD_APB_S_AUDTOP 

  svt_apb_slave_connector#(0) bd_apb_s_audtop(
    .slave_if(coretop_apb_if_0.slave_if[0]), 
    .slave_bind_if(`CORETOP.u_audtop.bd_apb_s_audtop_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_M_CQTOP 
  bind `CORETOP.u_cqtop svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(3), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(64), 
    .WSTRB_WIDTH_PARAM(8), 
    .BID_WIDTH_PARAM(3), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(3), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(3), 
    .RDATA_WIDTH_PARAM(64), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m_cqtop_bind_if (
    .awid(awid_m_cq), 
    .awaddr(awaddr_m_cq), 
    .awlen(awlen_m_cq), 
    .awsize(awsize_m_cq), 
    .awburst(awburst_m_cq), 
    .awlock(awlock_m_cq), 
    .awcache(awcache_m_cq), 
    .awprot(awprot_m_cq), 
    .awqos(awqos_m_cq), 
    .awvalid(awvalid_m_cq), 
    .awready(awready_m_cq), 
    .wdata(wdata_m_cq), 
    .wstrb(wstrb_m_cq), 
    .wlast(wlast_m_cq), 
    .wvalid(wvalid_m_cq), 
    .wready(wready_m_cq), 
    .bid(bid_m_cq), 
    .bresp(bresp_m_cq), 
    .bvalid(bvalid_m_cq), 
    .bready(bready_m_cq), 
    .arid(arid_m_cq), 
    .araddr(araddr_m_cq), 
    .arlen(arlen_m_cq), 
    .arsize(arsize_m_cq), 
    .arburst(arburst_m_cq), 
    .arlock(arlock_m_cq), 
    .arcache(arcache_m_cq), 
    .arprot(arprot_m_cq), 
    .arqos(arqos_m_cq), 
    .arvalid(arvalid_m_cq), 
    .arready(arready_m_cq), 
    .rid(rid_m_cq), 
    .rdata(rdata_m_cq), 
    .rresp(rresp_m_cq), 
    .rlast(rlast_m_cq), 
    .rvalid(rvalid_m_cq), 
    .rready(rready_m_cq) 
  );
`endif

`ifdef REPLACE_BD_AXI_M_CQTOP 

  svt_axi_master_connector#(1) bd_axi_m_cqtop(
    .master_if(coretop_axi_if_0.master_if[1]), 
    .master_bind_if(`CORETOP.u_cqtop.bd_axi_m_cqtop_bind_if) 
  );

`elsif CONNECT_BD_AXI_M_CQTOP 

  svt_axi_master_connector#(0) bd_axi_m_cqtop(
    .master_if(coretop_axi_if_0.master_if[1]), 
    .master_bind_if(`CORETOP.u_cqtop.bd_axi_m_cqtop_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_M_DMATOP 
  bind `CORETOP.u_dmatop svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(3), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(128), 
    .WSTRB_WIDTH_PARAM(16), 
    .BID_WIDTH_PARAM(3), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(3), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(3), 
    .RDATA_WIDTH_PARAM(128), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m_dmatop_bind_if (
    .awid(awid_m_dma), 
    .awaddr(awaddr_m_dma), 
    .awlen(awlen_m_dma), 
    .awsize(awsize_m_dma), 
    .awburst(awburst_m_dma), 
    .awlock(awlock_m_dma), 
    .awcache(awcache_m_dma), 
    .awprot(awprot_m_dma), 
    .awqos(awqos_m_dma), 
    .awvalid(awvalid_m_dma), 
    .awready(awready_m_dma), 
    .wdata(wdata_m_dma), 
    .wstrb(wstrb_m_dma), 
    .wlast(wlast_m_dma), 
    .wvalid(wvalid_m_dma), 
    .wready(wready_m_dma), 
    .bid(bid_m_dma), 
    .bresp(bresp_m_dma), 
    .bvalid(bvalid_m_dma), 
    .bready(bready_m_dma), 
    .arid(arid_m_dma), 
    .araddr(araddr_m_dma), 
    .arlen(arlen_m_dma), 
    .arsize(arsize_m_dma), 
    .arburst(arburst_m_dma), 
    .arlock(arlock_m_dma), 
    .arcache(arcache_m_dma), 
    .arprot(arprot_m_dma), 
    .arqos(arqos_m_dma), 
    .arvalid(arvalid_m_dma), 
    .arready(arready_m_dma), 
    .rid(rid_m_dma), 
    .rdata(rdata_m_dma), 
    .rresp(rresp_m_dma), 
    .rlast(rlast_m_dma), 
    .rvalid(rvalid_m_dma), 
    .rready(rready_m_dma) 
  );
`endif

`ifdef REPLACE_BD_AXI_M_DMATOP 

  svt_axi_master_connector#(1) bd_axi_m_dmatop(
    .master_if(coretop_axi_if_0.master_if[2]), 
    .master_bind_if(`CORETOP.u_dmatop.bd_axi_m_dmatop_bind_if) 
  );

`elsif CONNECT_BD_AXI_M_DMATOP 

  svt_axi_master_connector#(0) bd_axi_m_dmatop(
    .master_if(coretop_axi_if_0.master_if[2]), 
    .master_bind_if(`CORETOP.u_dmatop.bd_axi_m_dmatop_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_DMATOP 
  bind `CORETOP.u_dmatop svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(20), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_dmatop_bind_if (
    .paddr(paddr_s_dma), 
    .psel(psel_s_dma), 
    .penable(penable_s_dma), 
    .pwrite(pwrite_s_dma), 
    .prdata(prdata_s_dma), 
    .pwdata(pwdata_s_dma), 
    .pprot(pprot_s_dma), 
    .pstrb(pstrb_s_dma), 
    .pready(pready_s_dma) 
  );
`endif

`ifdef REPLACE_BD_APB_S_DMATOP 

  svt_apb_slave_connector#(1) bd_apb_s_dmatop(
    .slave_if(coretop_apb_if_0.slave_if[1]), 
    .slave_bind_if(`CORETOP.u_dmatop.bd_apb_s_dmatop_bind_if) 
  );

`elsif CONNECT_BD_APB_S_DMATOP 

  svt_apb_slave_connector#(0) bd_apb_s_dmatop(
    .slave_if(coretop_apb_if_0.slave_if[1]), 
    .slave_bind_if(`CORETOP.u_dmatop.bd_apb_s_dmatop_bind_if) 
  );

`endif

`ifdef BINDP_BD_AHB_S_FMTOP 
  bind `CORETOP.u_fmtop svt_ahb_slave_bind_if #(
    .HADDR_WIDTH_PARAM(32), 
    .HBURST_WIDTH_PARAM(3), 
    .HSIZE_WIDTH_PARAM(3), 
    .HTRANS_WIDTH_PARAM(2), 
    .HWDATA_WIDTH_PARAM(32), 
    .HRDATA_WIDTH_PARAM(32) 
  ) bd_ahb_s_fmtop_bind_if (
    .haddr(haddr_s_fm), 
    .hburst(hburst_s_fm), 
    .hsize(hsize_s_fm), 
    .htrans(htrans_s_fm), 
    .hwdata(hwdata_s_fm), 
    .hwrite(hwrite_s_fm), 
    .hrdata(hrdata_s_fm), 
    .hready(hready_s_fm), 
    .hresp(hresp_s_fm) 
  );
`endif

initial begin
    force coretop_ahb_if_0.slave_if[0].hmastlock = 0;
    force coretop_ahb_if_0.slave_if[0].hprot     = 0;
    force coretop_ahb_if_0.slave_if[0].hsel      = 1;
    force coretop_ahb_if_0.slave_if[0].hready_in = coretop_ahb_if_0.slave_if[0].hready;
end

`ifdef REPLACE_BD_AHB_S_FMTOP 

  svt_ahb_slave_connector#(1) bd_ahb_s_fmtop(
    .slave_if(coretop_ahb_if_0.slave_if[0]), 
    .slave_bind_if(`CORETOP.u_fmtop.bd_ahb_s_fmtop_bind_if) 
  );

`elsif CONNECT_BD_AHB_S_FMTOP 

  svt_ahb_slave_connector#(0) bd_ahb_s_fmtop(
    .slave_if(coretop_ahb_if_0.slave_if[0]), 
    .slave_bind_if(`CORETOP.u_fmtop.bd_ahb_s_fmtop_bind_if) 
  );

`endif

`ifdef BINDP_BD_AXI_M_FMTOP 
  bind `CORETOP.u_fmtop svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(3), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(64), 
    .WSTRB_WIDTH_PARAM(8), 
    .BID_WIDTH_PARAM(3), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(3), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(3), 
    .RDATA_WIDTH_PARAM(64), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m_fmtop_bind_if (
    .awid(awid_m_fm), 
    .awaddr(awaddr_m_fm), 
    .awlen(awlen_m_fm), 
    .awsize(awsize_m_fm), 
    .awburst(awburst_m_fm), 
    .awlock(awlock_m_fm), 
    .awcache(awcache_m_fm), 
    .awprot(awprot_m_fm), 
    .awqos(awqos_m_fm), 
    .awvalid(awvalid_m_fm), 
    .awready(awready_m_fm), 
    .wdata(wdata_m_fm), 
    .wstrb(wstrb_m_fm), 
    .wlast(wlast_m_fm), 
    .wvalid(wvalid_m_fm), 
    .wready(wready_m_fm), 
    .bid(bid_m_fm), 
    .bresp(bresp_m_fm), 
    .bvalid(bvalid_m_fm), 
    .bready(bready_m_fm), 
    .arid(arid_m_fm), 
    .araddr(araddr_m_fm), 
    .arlen(arlen_m_fm), 
    .arsize(arsize_m_fm), 
    .arburst(arburst_m_fm), 
    .arlock(arlock_m_fm), 
    .arcache(arcache_m_fm), 
    .arprot(arprot_m_fm), 
    .arqos(arqos_m_fm), 
    .arvalid(arvalid_m_fm), 
    .arready(arready_m_fm), 
    .rid(rid_m_fm), 
    .rdata(rdata_m_fm), 
    .rresp(rresp_m_fm), 
    .rlast(rlast_m_fm), 
    .rvalid(rvalid_m_fm), 
    .rready(rready_m_fm) 
  );
`endif

`ifdef REPLACE_BD_AXI_M_FMTOP 

  svt_axi_master_connector#(1) bd_axi_m_fmtop(
    .master_if(coretop_axi_if_0.master_if[3]), 
    .master_bind_if(`CORETOP.u_fmtop.bd_axi_m_fmtop_bind_if) 
  );

`elsif CONNECT_BD_AXI_M_FMTOP 

  svt_axi_master_connector#(0) bd_axi_m_fmtop(
    .master_if(coretop_axi_if_0.master_if[3]), 
    .master_bind_if(`CORETOP.u_fmtop.bd_axi_m_fmtop_bind_if) 
  );

`endif

`ifdef BINDP_BD_APB_S_FMTOP 
  bind `CORETOP.u_fmtop svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(20), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_fmtop_bind_if (
    .paddr(paddr_s_fm), 
    .psel(psel_s_fm), 
    .penable(penable_s_fm), 
    .pwrite(pwrite_s_fm), 
    .prdata(prdata_s_fm), 
    .pwdata(pwdata_s_fm), 
    .pprot(pprot_s_fm), 
    .pstrb(pstrb_s_fm), 
    .pready(pready_s_fm) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[2].pslverr = 0;  
end

`ifdef REPLACE_BD_APB_S_FMTOP 

  svt_apb_slave_connector#(1) bd_apb_s_fmtop(
    .slave_if(coretop_apb_if_0.slave_if[2]), 
    .slave_bind_if(`CORETOP.u_fmtop.bd_apb_s_fmtop_bind_if) 
  );

`elsif CONNECT_BD_APB_S_FMTOP 

  svt_apb_slave_connector#(0) bd_apb_s_fmtop(
    .slave_if(coretop_apb_if_0.slave_if[2]), 
    .slave_bind_if(`CORETOP.u_fmtop.bd_apb_s_fmtop_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_GTOP 
  bind `CORETOP.u_gtop svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(20), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_gtop_bind_if (
    .paddr(paddr_s_gtop), 
    .psel(psel_s_gtop), 
    .penable(penable_s_gtop), 
    .pwrite(pwrite_s_gtop), 
    .prdata(prdata_s_gtop), 
    .pwdata(pwdata_s_gtop), 
    .pprot(pprot_s_gtop), 
    .pstrb(pstrb_s_gtop), 
    .pready(pready_s_gtop) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[3].pslverr = 0;  
end

`ifdef REPLACE_BD_APB_S_GTOP 

  svt_apb_slave_connector#(1) bd_apb_s_gtop(
    .slave_if(coretop_apb_if_0.slave_if[3]), 
    .slave_bind_if(`CORETOP.u_gtop.bd_apb_s_gtop_bind_if) 
  );

`elsif CONNECT_BD_APB_S_GTOP 

  svt_apb_slave_connector#(0) bd_apb_s_gtop(
    .slave_if(coretop_apb_if_0.slave_if[3]), 
    .slave_bind_if(`CORETOP.u_gtop.bd_apb_s_gtop_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_M_PERITOP 
  bind `CORETOP.u_peritop svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(3), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(64), 
    .WSTRB_WIDTH_PARAM(8), 
    .BID_WIDTH_PARAM(3), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(3), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(3), 
    .RDATA_WIDTH_PARAM(64), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m_peritop_bind_if (
    .awid(awid_m_peri), 
    .awaddr(awaddr_m_peri), 
    .awlen(awlen_m_peri), 
    .awsize(awsize_m_peri), 
    .awburst(awburst_m_peri), 
    .awlock(awlock_m_peri), 
    .awcache(awcache_m_peri), 
    .awprot(awprot_m_peri), 
    .awqos(awqos_m_peri), 
    .awvalid(awvalid_m_peri), 
    .awready(awready_m_peri), 
    .wdata(wdata_m_peri), 
    .wstrb(wstrb_m_peri), 
    .wlast(wlast_m_peri), 
    .wvalid(wvalid_m_peri), 
    .wready(wready_m_peri), 
    .bid(bid_m_peri), 
    .bresp(bresp_m_peri), 
    .bvalid(bvalid_m_peri), 
    .bready(bready_m_peri), 
    .arid(arid_m_peri), 
    .araddr(araddr_m_peri), 
    .arlen(arlen_m_peri), 
    .arsize(arsize_m_peri), 
    .arburst(arburst_m_peri), 
    .arlock(arlock_m_peri), 
    .arcache(arcache_m_peri), 
    .arprot(arprot_m_peri), 
    .arqos(arqos_m_peri), 
    .arvalid(arvalid_m_peri), 
    .arready(arready_m_peri), 
    .rid(rid_m_peri), 
    .rdata(rdata_m_peri), 
    .rresp(rresp_m_peri), 
    .rlast(rlast_m_peri), 
    .rvalid(rvalid_m_peri), 
    .rready(rready_m_peri) 
  );
`endif

`ifdef REPLACE_BD_AXI_M_PERITOP 

  svt_axi_master_connector#(1) bd_axi_m_peritop(
    .master_if(coretop_axi_if_0.master_if[4]), 
    .master_bind_if(`CORETOP.u_peritop.bd_axi_m_peritop_bind_if) 
  );

`elsif CONNECT_BD_AXI_M_PERITOP 

  svt_axi_master_connector#(0) bd_axi_m_peritop(
    .master_if(coretop_axi_if_0.master_if[4]), 
    .master_bind_if(`CORETOP.u_peritop.bd_axi_m_peritop_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_M_PERITOP 
  bind `CORETOP.u_peritop svt_apb_master_bind_if #(
    .PADDR_WIDTH_PARAM(40), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_m_peritop_bind_if (
    .paddr(paddr_m_peri), 
    .psel(psel_m_peri), 
    .penable(penable_m_peri), 
    .pwrite(pwrite_m_peri), 
    .prdata(prdata_m_peri), 
    .pwdata(pwdata_m_peri), 
    .pprot(pprot_m_peri), 
    .pstrb(pstrb_m_peri), 
    .pready(pready_m_peri) 
  );
`endif

initial begin
  force `CORETOP.u_peritop.bd_apb_m_peritop_bind_if.pslverr = 0;
end

`ifdef REPLACE_BD_APB_M_PERITOP 

  svt_apb_master_connector#(1) bd_apb_m_peritop(
    .master_if(coretop_apb_if_1), 
    .master_bind_if(`CORETOP.u_peritop.bd_apb_m_peritop_bind_if) 
  );

`elsif CONNECT_BD_APB_M_PERITOP 

  svt_apb_master_connector#(0) bd_apb_m_peritop(
    .master_if(coretop_apb_if_1), 
    .master_bind_if(`CORETOP.u_peritop.bd_apb_m_peritop_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S0_PERITOP 
  bind `CORETOP.u_peritop svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(20), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s0_peritop_bind_if (
    .paddr(paddr_s0_peri), 
    .psel(psel_s0_peri), 
    .penable(penable_s0_peri), 
    .pwrite(pwrite_s0_peri), 
    .prdata(prdata_s0_peri), 
    .pwdata(pwdata_s0_peri), 
    .pprot(pprot_s0_peri), 
    .pstrb(pstrb_s0_peri), 
    .pready(pready_s0_peri) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[4].pslverr = 0;  
end

`ifdef REPLACE_BD_APB_S0_PERITOP 

  svt_apb_slave_connector#(1) bd_apb_s0_peritop(
    .slave_if(coretop_apb_if_0.slave_if[4]), 
    .slave_bind_if(`CORETOP.u_peritop.bd_apb_s0_peritop_bind_if) 
  );

`elsif CONNECT_BD_APB_S0_PERITOP 

  svt_apb_slave_connector#(0) bd_apb_s0_peritop(
    .slave_if(coretop_apb_if_0.slave_if[4]), 
    .slave_bind_if(`CORETOP.u_peritop.bd_apb_s0_peritop_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S1_PERITOP 
  bind `CORETOP.u_peritop svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(16), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s1_peritop_bind_if (
    .paddr(paddr_s1_peri), 
    .psel(psel_s1_peri), 
    .penable(penable_s1_peri), 
    .pwrite(pwrite_s1_peri), 
    .prdata(prdata_s1_peri), 
    .pwdata(pwdata_s1_peri), 
    .pprot(pprot_s1_peri), 
    .pstrb(pstrb_s1_peri), 
    .pready(pready_s1_peri) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[5].pslverr = 0;  
end

`ifdef REPLACE_BD_APB_S1_PERITOP 

  svt_apb_slave_connector#(1) bd_apb_s1_peritop(
    .slave_if(coretop_apb_if_0.slave_if[5]), 
    .slave_bind_if(`CORETOP.u_peritop.bd_apb_s1_peritop_bind_if) 
  );

`elsif CONNECT_BD_APB_S1_PERITOP 

  svt_apb_slave_connector#(0) bd_apb_s1_peritop(
    .slave_if(coretop_apb_if_0.slave_if[5]), 
    .slave_bind_if(`CORETOP.u_peritop.bd_apb_s1_peritop_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_M_HSMTOP 
  bind `CORETOP.u_hsmtop svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(3), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(64), 
    .WSTRB_WIDTH_PARAM(8), 
    .BID_WIDTH_PARAM(3), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(3), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(3), 
    .RDATA_WIDTH_PARAM(64), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m_hsmtop_bind_if (
    .awid(awid_m_hsm), 
    .awaddr(awaddr_m_hsm), 
    .awlen(awlen_m_hsm), 
    .awsize(awsize_m_hsm), 
    .awburst(awburst_m_hsm), 
    .awlock(awlock_m_hsm), 
    .awcache(awcache_m_hsm), 
    .awprot(awprot_m_hsm), 
    .awqos(awqos_m_hsm), 
    .awvalid(awvalid_m_hsm), 
    .awready(awready_m_hsm), 
    .wdata(wdata_m_hsm), 
    .wstrb(wstrb_m_hsm), 
    .wlast(wlast_m_hsm), 
    .wvalid(wvalid_m_hsm), 
    .wready(wready_m_hsm), 
    .bid(bid_m_hsm), 
    .bresp(bresp_m_hsm), 
    .bvalid(bvalid_m_hsm), 
    .bready(bready_m_hsm), 
    .arid(arid_m_hsm), 
    .araddr(araddr_m_hsm), 
    .arlen(arlen_m_hsm), 
    .arsize(arsize_m_hsm), 
    .arburst(arburst_m_hsm), 
    .arlock(arlock_m_hsm), 
    .arcache(arcache_m_hsm), 
    .arprot(arprot_m_hsm), 
    .arqos(arqos_m_hsm), 
    .arvalid(arvalid_m_hsm), 
    .arready(arready_m_hsm), 
    .rid(rid_m_hsm), 
    .rdata(rdata_m_hsm), 
    .rresp(rresp_m_hsm), 
    .rlast(rlast_m_hsm), 
    .rvalid(rvalid_m_hsm), 
    .rready(rready_m_hsm) 
  );
`endif

`ifdef REPLACE_BD_AXI_M_HSMTOP 

  svt_axi_master_connector#(1) bd_axi_m_hsmtop(
    .master_if(coretop_axi_if_0.master_if[5]), 
    .master_bind_if(`CORETOP.u_hsmtop.bd_axi_m_hsmtop_bind_if) 
  );

`elsif CONNECT_BD_AXI_M_HSMTOP 

  svt_axi_master_connector#(0) bd_axi_m_hsmtop(
    .master_if(coretop_axi_if_0.master_if[5]), 
    .master_bind_if(`CORETOP.u_hsmtop.bd_axi_m_hsmtop_bind_if) 
  );

`endif

`ifdef BIND_BD_AHB_M_HSMTOP 
  bind `CORETOP.u_hsmtop svt_ahb_master_bind_if #(
    .HADDR_WIDTH_PARAM(32), 
    .HBURST_WIDTH_PARAM(3), 
    .HSIZE_WIDTH_PARAM(3), 
    .HTRANS_WIDTH_PARAM(2), 
    .HWDATA_WIDTH_PARAM(32), 
    .HRDATA_WIDTH_PARAM(32) 
  ) bd_ahb_m_hsmtop_bind_if (
    .haddr(haddr_m_hsm), 
    .hburst(hburst_m_hsm), 
    .hsize(hsize_m_hsm), 
    .htrans(htrans_m_hsm), 
    .hwdata(hwdata_m_hsm), 
    .hwrite(hwrite_m_hsm), 
    .hrdata(hrdata_m_hsm), 
    .hready(hready_m_hsm), 
    .hresp(hresp_m_hsm) 
  );
`endif

`ifdef REPLACE_BD_AHB_M_HSMTOP 

  svt_ahb_master_connector#(1) bd_ahb_m_hsmtop(
    .master_if(coretop_ahb_if_0.master_if[0]), 
    .master_bind_if(`CORETOP.u_hsmtop.bd_ahb_m_hsmtop_bind_if) 
  );

`elsif CONNECT_BD_AHB_M_HSMTOP 

  svt_ahb_master_connector#(0) bd_ahb_m_hsmtop(
    .master_if(coretop_ahb_if_0.master_if[0]), 
    .master_bind_if(`CORETOP.u_hsmtop.bd_ahb_m_hsmtop_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_M_HSMTOP 
  bind `CORETOP.u_hsmtop svt_apb_master_bind_if #(
    .PADDR_WIDTH_PARAM(16), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_m_hsmtop_bind_if (
    .paddr(paddr_m_hsm), 
    .psel(psel_m_hsm), 
    .penable(penable_m_hsm), 
    .pwrite(pwrite_m_hsm), 
    .prdata(prdata_m_hsm), 
    .pwdata(pwdata_m_hsm), 
    .pprot(pprot_m_hsm), 
    .pstrb(pstrb_m_hsm), 
    .pready(pready_m_hsm) 
  );
`endif

initial begin
   force `CORETOP.u_hsmtop.bd_apb_m_hsmtop_bind_if.pslverr = 0; 
end

`ifdef REPLACE_BD_APB_M_HSMTOP 

  svt_apb_master_connector#(1) bd_apb_m_hsmtop(
    .master_if(coretop_apb_if_2), 
    .master_bind_if(`CORETOP.u_hsmtop.bd_apb_m_hsmtop_bind_if) 
  );

`elsif CONNECT_BD_APB_M_HSMTOP 

  svt_apb_master_connector#(0) bd_apb_m_hsmtop(
    .master_if(coretop_apb_if_2), 
    .master_bind_if(`CORETOP.u_hsmtop.bd_apb_m_hsmtop_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_HSMTOP 
  bind `CORETOP.u_hsmtop svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(20), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_hsmtop_bind_if (
    .paddr(paddr_s_hsm), 
    .psel(psel_s_hsm), 
    .penable(penable_s_hsm), 
    .pwrite(pwrite_s_hsm), 
    .prdata(prdata_s_hsm), 
    .pwdata(pwdata_s_hsm), 
    .pprot(pprot_s_hsm), 
    .pstrb(pstrb_s_hsm), 
    .pready(pready_s_hsm) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[6].pslverr = 0;  
end

`ifdef REPLACE_BD_APB_S_HSMTOP 

  svt_apb_slave_connector#(1) bd_apb_s_hsmtop(
    .slave_if(coretop_apb_if_0.slave_if[6]), 
    .slave_bind_if(`CORETOP.u_hsmtop.bd_apb_s_hsmtop_bind_if) 
  );

`elsif CONNECT_BD_APB_S_HSMTOP 

  svt_apb_slave_connector#(0) bd_apb_s_hsmtop(
    .slave_if(coretop_apb_if_0.slave_if[6]), 
    .slave_bind_if(`CORETOP.u_hsmtop.bd_apb_s_hsmtop_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_S_UCIE 
  bind `CORETOP.u_ucie_0 svt_axi_slave_bind_if #(
    .AWID_WIDTH_PARAM(16), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(16), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(16), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(16), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_s_ucie_bind_if (
    .awid(awid_s_ucie), 
    .awaddr(awaddr_s_ucie), 
    .awlen(awlen_s_ucie), 
    .awsize(awsize_s_ucie), 
    .awburst(awburst_s_ucie), 
    .awlock(awlock_s_ucie), 
    .awcache(awcache_s_ucie), 
    .awprot(awprot_s_ucie), 
    .awqos(awqos_s_ucie), 
    .awvalid(awvalid_s_ucie), 
    .awready(awready_s_ucie), 
    .wdata(wdata_s_ucie), 
    .wstrb(wstrb_s_ucie), 
    .wlast(wlast_s_ucie), 
    .wvalid(wvalid_s_ucie), 
    .wready(wready_s_ucie), 
    .bid(bid_s_ucie), 
    .bresp(bresp_s_ucie), 
    .bvalid(bvalid_s_ucie), 
    .bready(bready_s_ucie), 
    .arid(arid_s_ucie), 
    .araddr(araddr_s_ucie), 
    .arlen(arlen_s_ucie), 
    .arsize(arsize_s_ucie), 
    .arburst(arburst_s_ucie), 
    .arlock(arlock_s_ucie), 
    .arcache(arcache_s_ucie), 
    .arprot(arprot_s_ucie), 
    .arqos(arqos_s_ucie), 
    .arvalid(arvalid_s_ucie), 
    .arready(arready_s_ucie), 
    .rid(rid_s_ucie), 
    .rdata(rdata_s_ucie), 
    .rresp(rresp_s_ucie), 
    .rlast(rlast_s_ucie), 
    .rvalid(rvalid_s_ucie), 
    .rready(rready_s_ucie) 
  );
`endif

`ifdef REPLACE_BD_AXI_S_UCIE 

  svt_axi_slave_connector#(1) bd_axi_s_ucie(
    .slave_if(coretop_axi_if_0.slave_if[0]), 
    .slave_bind_if(`CORETOP.u_ucie_0.bd_axi_s_ucie_bind_if) 
  );

`elsif CONNECT_BD_AXI_S_UCIE 

  svt_axi_slave_connector#(0) bd_axi_s_ucie(
    .slave_if(coretop_axi_if_0.slave_if[0]), 
    .slave_bind_if(`CORETOP.u_ucie_0.bd_axi_s_ucie_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_M_UCIE 
  bind `CORETOP.u_ucie_0 svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(8), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(8), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(8), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(8), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m_ucie_bind_if (
    .awid(awid_m_ucie), 
    .awaddr(awaddr_m_ucie), 
    .awlen(awlen_m_ucie), 
    .awsize(awsize_m_ucie), 
    .awburst(awburst_m_ucie), 
    .awlock(awlock_m_ucie), 
    .awcache(awcache_m_ucie), 
    .awprot(awprot_m_ucie), 
    .awqos(awqos_m_ucie), 
    .awvalid(awvalid_m_ucie), 
    .awready(awready_m_ucie), 
    .wdata(wdata_m_ucie), 
    .wstrb(wstrb_m_ucie), 
    .wlast(wlast_m_ucie), 
    .wvalid(wvalid_m_ucie), 
    .wready(wready_m_ucie), 
    .bid(bid_m_ucie), 
    .bresp(bresp_m_ucie), 
    .bvalid(bvalid_m_ucie), 
    .bready(bready_m_ucie), 
    .arid(arid_m_ucie), 
    .araddr(araddr_m_ucie), 
    .arlen(arlen_m_ucie), 
    .arsize(arsize_m_ucie), 
    .arburst(arburst_m_ucie), 
    .arlock(arlock_m_ucie), 
    .arcache(arcache_m_ucie), 
    .arprot(arprot_m_ucie), 
    .arqos(arqos_m_ucie), 
    .arvalid(arvalid_m_ucie), 
    .arready(arready_m_ucie), 
    .rid(rid_m_ucie), 
    .rdata(rdata_m_ucie), 
    .rresp(rresp_m_ucie), 
    .rlast(rlast_m_ucie), 
    .rvalid(rvalid_m_ucie), 
    .rready(rready_m_ucie) 
  );
`endif

`ifdef REPLACE_BD_AXI_M_UCIE 

  svt_axi_master_connector#(1) bd_axi_m_ucie(
    .master_if(coretop_axi_if_0.master_if[6]), 
    .master_bind_if(`CORETOP.u_ucie_0.bd_axi_m_ucie_bind_if) 
  );

`elsif CONNECT_BD_AXI_M_UCIE 

  svt_axi_master_connector#(0) bd_axi_m_ucie(
    .master_if(coretop_axi_if_0.master_if[6]), 
    .master_bind_if(`CORETOP.u_ucie_0.bd_axi_m_ucie_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_UCIE 
  bind `CORETOP.u_ucie_0 svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(20), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_ucie_bind_if (
    .paddr(paddr_s_ucie), 
    .psel(psel_s_ucie), 
    .penable(penable_s_ucie), 
    .pwrite(pwrite_s_ucie), 
    .prdata(prdata_s_ucie), 
    .pwdata(pwdata_s_ucie), 
    .pprot(pprot_s_ucie), 
    .pstrb(pstrb_s_ucie), 
    .pready(pready_s_ucie) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[7].pslverr = 0;  
end


`ifdef REPLACE_BD_APB_S_UCIE 

  svt_apb_slave_connector#(1) bd_apb_s_ucie(
    .slave_if(coretop_apb_if_0.slave_if[7]), 
    .slave_bind_if(`CORETOP.u_ucie_0.bd_apb_s_ucie_bind_if) 
  );

`elsif CONNECT_BD_APB_S_UCIE 

  svt_apb_slave_connector#(0) bd_apb_s_ucie(
    .slave_if(coretop_apb_if_0.slave_if[7]), 
    .slave_bind_if(`CORETOP.u_ucie_0.bd_apb_s_ucie_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_M_SS_CDEC 
  bind `CORETOP.u_ss_cdec svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(3), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(3), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(3), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(3), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m_ss_cdec_bind_if (
    .awid(awid_m_ss_cdec), 
    .awaddr(awaddr_m_ss_cdec), 
    .awlen(awlen_m_ss_cdec), 
    .awsize(awsize_m_ss_cdec), 
    .awburst(awburst_m_ss_cdec), 
    .awlock(awlock_m_ss_cdec), 
    .awcache(awcache_m_ss_cdec), 
    .awprot(awprot_m_ss_cdec), 
    .awqos(awqos_m_ss_cdec), 
    .awvalid(awvalid_m_ss_cdec), 
    .awready(awready_m_ss_cdec), 
    .wdata(wdata_m_ss_cdec), 
    .wstrb(wstrb_m_ss_cdec), 
    .wlast(wlast_m_ss_cdec), 
    .wvalid(wvalid_m_ss_cdec), 
    .wready(wready_m_ss_cdec), 
    .bid(bid_m_ss_cdec), 
    .bresp(bresp_m_ss_cdec), 
    .bvalid(bvalid_m_ss_cdec), 
    .bready(bready_m_ss_cdec), 
    .arid(arid_m_ss_cdec), 
    .araddr(araddr_m_ss_cdec), 
    .arlen(arlen_m_ss_cdec), 
    .arsize(arsize_m_ss_cdec), 
    .arburst(arburst_m_ss_cdec), 
    .arlock(arlock_m_ss_cdec), 
    .arcache(arcache_m_ss_cdec), 
    .arprot(arprot_m_ss_cdec), 
    .arqos(arqos_m_ss_cdec), 
    .arvalid(arvalid_m_ss_cdec), 
    .arready(arready_m_ss_cdec), 
    .rid(rid_m_ss_cdec), 
    .rdata(rdata_m_ss_cdec), 
    .rresp(rresp_m_ss_cdec), 
    .rlast(rlast_m_ss_cdec), 
    .rvalid(rvalid_m_ss_cdec), 
    .rready(rready_m_ss_cdec) 
  );
`endif

`ifdef REPLACEC_BD_AXI_M_SS_CDEC 

  svt_axi_master_connector#(1) bd_axi_m_ss_cdec(
    .master_if(coretop_axi_if_0.master_if[7]), 
    .master_bind_if(`CORETOP.u_ss_cdec.bd_axi_m_ss_cdec_bind_if) 
  );

`elsif CONNECT_BD_AXI_M_SS_CDEC 

  svt_axi_master_connector#(0) bd_axi_m_ss_cdec(
    .master_if(coretop_axi_if_0.master_if[7]), 
    .master_bind_if(`CORETOP.u_ss_cdec.bd_axi_m_ss_cdec_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_SS_CDEC 
  bind `CORETOP.u_ss_cdec svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(24), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_ss_cdec_bind_if (
    .paddr(paddr_s_ss_cdec), 
    .psel(psel_s_ss_cdec), 
    .penable(penable_s_ss_cdec), 
    .pwrite(pwrite_s_ss_cdec), 
    .prdata(prdata_s_ss_cdec), 
    .pwdata(pwdata_s_ss_cdec), 
    .pprot(pprot_s_ss_cdec), 
    .pstrb(pstrb_s_ss_cdec), 
    .pready(pready_s_ss_cdec) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[8].pslverr = 0;  
end

`ifdef REPLACEC_BD_APB_S_SS_CDEC 

  svt_apb_slave_connector#(1) bd_apb_s_ss_cdec(
    .slave_if(coretop_apb_if_0.slave_if[8]), 
    .slave_bind_if(`CORETOP.u_ss_cdec.bd_apb_s_ss_cdec_bind_if) 
  );

`elsif CONNECT_BD_APB_S_SS_CDEC 

  svt_apb_slave_connector#(0) bd_apb_s_ss_cdec(
    .slave_if(coretop_apb_if_0.slave_if[8]), 
    .slave_bind_if(`CORETOP.u_ss_cdec.bd_apb_s_ss_cdec_bind_if) 
  );

`endif

`ifdef BIND_BD_ACE_M0_SS_CMP 
  bind `CORETOP.u_ss_cmp svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(9), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWDOMAIN_WIDTH_PARAM(2), 
    .AWSNOOP_WIDTH_PARAM(3), 
    .AWBAR_WIDTH_PARAM(2), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(128), 
    .WSTRB_WIDTH_PARAM(16), 
    .BID_WIDTH_PARAM(9), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(9), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARDOMAIN_WIDTH_PARAM(2), 
    .ARSNOOP_WIDTH_PARAM(4), 
    .ARBAR_WIDTH_PARAM(2), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(9), 
    .RDATA_WIDTH_PARAM(128), 
    .RRESP_WIDTH_PARAM(4), 
    .ACADDR_WIDTH_PARAM(40), 
    .ACSNOOP_WIDTH_PARAM(4), 
    .ACPROT_WIDTH_PARAM(3), 
    .CRRESP_WIDTH_PARAM(5), 
    .CDDATA_WIDTH_PARAM(128), 
    .AWUSER_WIDTH_PARAM(9), 
    .ARUSER_WIDTH_PARAM(9) 
  ) bd_ace_m0_ss_cmp_bind_if (
    .awid(awid_m0_ss_cmp), 
    .awaddr(awaddr_m0_ss_cmp), 
    .awdomain(awdomain_m0_ss_cmp), 
    .awsnoop(awsnoop_m0_ss_cmp), 
    .awbar(awbar_m0_ss_cmp), 
    .awlen(awlen_m0_ss_cmp), 
    .awsize(awsize_m0_ss_cmp), 
    .awburst(awburst_m0_ss_cmp), 
    .awlock(awlock_m0_ss_cmp), 
    .awcache(awcache_m0_ss_cmp), 
    .awprot(awprot_m0_ss_cmp), 
    .awqos(awqos_m0_ss_cmp), 
    .awvalid(awvalid_m0_ss_cmp), 
    .awready(awready_m0_ss_cmp), 
    .wdata(wdata_m0_ss_cmp), 
    .wstrb(wstrb_m0_ss_cmp), 
    .wlast(wlast_m0_ss_cmp), 
    .wvalid(wvalid_m0_ss_cmp), 
    .wready(wready_m0_ss_cmp), 
    .bid(bid_m0_ss_cmp), 
    .bresp(bresp_m0_ss_cmp), 
    .bvalid(bvalid_m0_ss_cmp), 
    .bready(bready_m0_ss_cmp), 
    .arid(arid_m0_ss_cmp), 
    .araddr(araddr_m0_ss_cmp), 
    .ardomain(ardomain_m0_ss_cmp), 
    .arsnoop(arsnoop_m0_ss_cmp), 
    .arbar(arbar_m0_ss_cmp), 
    .arlen(arlen_m0_ss_cmp), 
    .arsize(arsize_m0_ss_cmp), 
    .arburst(arburst_m0_ss_cmp), 
    .arlock(arlock_m0_ss_cmp), 
    .arcache(arcache_m0_ss_cmp), 
    .arprot(arprot_m0_ss_cmp), 
    .arqos(arqos_m0_ss_cmp), 
    .arvalid(arvalid_m0_ss_cmp), 
    .arready(arready_m0_ss_cmp), 
    .rid(rid_m0_ss_cmp), 
    .rdata(rdata_m0_ss_cmp), 
    .rresp(rresp_m0_ss_cmp), 
    .rlast(rlast_m0_ss_cmp), 
    .rvalid(rvalid_m0_ss_cmp), 
    .rready(rready_m0_ss_cmp), 
    .acaddr(acaddr_m0_ss_cmp), 
    .acsnoop(acsnoop_m0_ss_cmp), 
    .acprot(acprot_m0_ss_cmp), 
    .acvalid(acvalid_m0_ss_cmp), 
    .acready(acready_m0_ss_cmp), 
    .crresp(crresp_m0_ss_cmp), 
    .crvalid(crvalid_m0_ss_cmp), 
    .crready(crready_m0_ss_cmp), 
    .cddata(cddata_m0_ss_cmp), 
    .cdlast(cdlast_m0_ss_cmp), 
    .cdvalid(cdvalid_m0_ss_cmp), 
    .cdready(cdready_m0_ss_cmp), 
    .rack(rack_m0_ss_cmp), 
    .wack(wack_m0_ss_cmp), 
    .awuser(awuser_m0_ss_cmp), 
    .wuser(wuser_m0_ss_cmp), 
    .buser(buser_m0_ss_cmp), 
    .aruser(aruser_m0_ss_cmp), 
    .ruser(ruser_m0_ss_cmp) 
  );
`endif

`ifdef REPLACE_BD_ACE_M0_SS_CMP 

  svt_axi_master_connector#(1) bd_ace_m0_ss_cmp(
    .master_if(coretop_axi_if_0.master_if[8]), 
    .master_bind_if(`CORETOP.u_ss_cmp.bd_ace_m0_ss_cmp_bind_if) 
  );

`elsif CONNECT_BD_ACE_M0_SS_CMP 

  svt_axi_master_connector#(0) bd_ace_m0_ss_cmp(
    .master_if(coretop_axi_if_0.master_if[8]), 
    .master_bind_if(`CORETOP.u_ss_cmp.bd_ace_m0_ss_cmp_bind_if) 
  );

`endif

`ifdef BIND_BD_ACE_M1_SS_CMP 
  bind `CORETOP.u_ss_cmp svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(9), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWDOMAIN_WIDTH_PARAM(2), 
    .AWSNOOP_WIDTH_PARAM(3), 
    .AWBAR_WIDTH_PARAM(2), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(128), 
    .WSTRB_WIDTH_PARAM(16), 
    .BID_WIDTH_PARAM(9), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(9), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARDOMAIN_WIDTH_PARAM(2), 
    .ARSNOOP_WIDTH_PARAM(4), 
    .ARBAR_WIDTH_PARAM(2), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(9), 
    .RDATA_WIDTH_PARAM(128), 
    .RRESP_WIDTH_PARAM(4), 
    .ACADDR_WIDTH_PARAM(40), 
    .ACSNOOP_WIDTH_PARAM(4), 
    .ACPROT_WIDTH_PARAM(3), 
    .CRRESP_WIDTH_PARAM(5), 
    .CDDATA_WIDTH_PARAM(128), 
    .AWUSER_WIDTH_PARAM(9), 
    .ARUSER_WIDTH_PARAM(9) 
  ) bd_ace_m1_ss_cmp_bind_if (
    .awid(awid_m1_ss_cmp), 
    .awaddr(awaddr_m1_ss_cmp), 
    .awdomain(awdomain_m1_ss_cmp), 
    .awsnoop(awsnoop_m1_ss_cmp), 
    .awbar(awbar_m1_ss_cmp), 
    .awlen(awlen_m1_ss_cmp), 
    .awsize(awsize_m1_ss_cmp), 
    .awburst(awburst_m1_ss_cmp), 
    .awlock(awlock_m1_ss_cmp), 
    .awcache(awcache_m1_ss_cmp), 
    .awprot(awprot_m1_ss_cmp), 
    .awqos(awqos_m1_ss_cmp), 
    .awvalid(awvalid_m1_ss_cmp), 
    .awready(awready_m1_ss_cmp), 
    .wdata(wdata_m1_ss_cmp), 
    .wstrb(wstrb_m1_ss_cmp), 
    .wlast(wlast_m1_ss_cmp), 
    .wvalid(wvalid_m1_ss_cmp), 
    .wready(wready_m1_ss_cmp), 
    .bid(bid_m1_ss_cmp), 
    .bresp(bresp_m1_ss_cmp), 
    .bvalid(bvalid_m1_ss_cmp), 
    .bready(bready_m1_ss_cmp), 
    .arid(arid_m1_ss_cmp), 
    .araddr(araddr_m1_ss_cmp), 
    .ardomain(ardomain_m1_ss_cmp), 
    .arsnoop(arsnoop_m1_ss_cmp), 
    .arbar(arbar_m1_ss_cmp), 
    .arlen(arlen_m1_ss_cmp), 
    .arsize(arsize_m1_ss_cmp), 
    .arburst(arburst_m1_ss_cmp), 
    .arlock(arlock_m1_ss_cmp), 
    .arcache(arcache_m1_ss_cmp), 
    .arprot(arprot_m1_ss_cmp), 
    .arqos(arqos_m1_ss_cmp), 
    .arvalid(arvalid_m1_ss_cmp), 
    .arready(arready_m1_ss_cmp), 
    .rid(rid_m1_ss_cmp), 
    .rdata(rdata_m1_ss_cmp), 
    .rresp(rresp_m1_ss_cmp), 
    .rlast(rlast_m1_ss_cmp), 
    .rvalid(rvalid_m1_ss_cmp), 
    .rready(rready_m1_ss_cmp), 
    .acaddr(acaddr_m1_ss_cmp), 
    .acsnoop(acsnoop_m1_ss_cmp), 
    .acprot(acprot_m1_ss_cmp), 
    .acvalid(acvalid_m1_ss_cmp), 
    .acready(acready_m1_ss_cmp), 
    .crresp(crresp_m1_ss_cmp), 
    .crvalid(crvalid_m1_ss_cmp), 
    .crready(crready_m1_ss_cmp), 
    .cddata(cddata_m1_ss_cmp), 
    .cdlast(cdlast_m1_ss_cmp), 
    .cdvalid(cdvalid_m1_ss_cmp), 
    .cdready(cdready_m1_ss_cmp), 
    .rack(rack_m1_ss_cmp), 
    .wack(wack_m1_ss_cmp), 
    .awuser(awuser_m1_ss_cmp), 
    .wuser(wuser_m1_ss_cmp), 
    .buser(buser_m1_ss_cmp), 
    .aruser(aruser_m1_ss_cmp), 
    .ruser(ruser_m1_ss_cmp) 
  );
`endif

`ifdef REPLACE_BD_ACE_M1_SS_CMP 

  svt_axi_master_connector#(1) bd_ace_m1_ss_cmp(
    .master_if(coretop_axi_if_0.master_if[9]), 
    .master_bind_if(`CORETOP.u_ss_cmp.bd_ace_m1_ss_cmp_bind_if) 
  );

`elsif CONNECT_BD_ACE_M1_SS_CMP 

  svt_axi_master_connector#(0) bd_ace_m1_ss_cmp(
    .master_if(coretop_axi_if_0.master_if[9]), 
    .master_bind_if(`CORETOP.u_ss_cmp.bd_ace_m1_ss_cmp_bind_if) 
  );

`endif

`ifdef BIND_BD_ACE_M2_SS_CMP 
  bind `CORETOP.u_ss_cmp svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(9), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWDOMAIN_WIDTH_PARAM(2), 
    .AWSNOOP_WIDTH_PARAM(3), 
    .AWBAR_WIDTH_PARAM(2), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(128), 
    .WSTRB_WIDTH_PARAM(16), 
    .BID_WIDTH_PARAM(9), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(9), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARDOMAIN_WIDTH_PARAM(2), 
    .ARSNOOP_WIDTH_PARAM(4), 
    .ARBAR_WIDTH_PARAM(2), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(9), 
    .RDATA_WIDTH_PARAM(128), 
    .RRESP_WIDTH_PARAM(4), 
    .ACADDR_WIDTH_PARAM(40), 
    .ACSNOOP_WIDTH_PARAM(4), 
    .ACPROT_WIDTH_PARAM(3), 
    .CRRESP_WIDTH_PARAM(5), 
    .CDDATA_WIDTH_PARAM(128), 
    .AWUSER_WIDTH_PARAM(9), 
    .ARUSER_WIDTH_PARAM(9) 
  ) bd_ace_m2_ss_cmp_bind_if (
    .awid(awid_m2_ss_cmp), 
    .awaddr(awaddr_m2_ss_cmp), 
    .awdomain(awdomain_m2_ss_cmp), 
    .awsnoop(awsnoop_m2_ss_cmp), 
    .awbar(awbar_m2_ss_cmp), 
    .awlen(awlen_m2_ss_cmp), 
    .awsize(awsize_m2_ss_cmp), 
    .awburst(awburst_m2_ss_cmp), 
    .awlock(awlock_m2_ss_cmp), 
    .awcache(awcache_m2_ss_cmp), 
    .awprot(awprot_m2_ss_cmp), 
    .awqos(awqos_m2_ss_cmp), 
    .awvalid(awvalid_m2_ss_cmp), 
    .awready(awready_m2_ss_cmp), 
    .wdata(wdata_m2_ss_cmp), 
    .wstrb(wstrb_m2_ss_cmp), 
    .wlast(wlast_m2_ss_cmp), 
    .wvalid(wvalid_m2_ss_cmp), 
    .wready(wready_m2_ss_cmp), 
    .bid(bid_m2_ss_cmp), 
    .bresp(bresp_m2_ss_cmp), 
    .bvalid(bvalid_m2_ss_cmp), 
    .bready(bready_m2_ss_cmp), 
    .arid(arid_m2_ss_cmp), 
    .araddr(araddr_m2_ss_cmp), 
    .ardomain(ardomain_m2_ss_cmp), 
    .arsnoop(arsnoop_m2_ss_cmp), 
    .arbar(arbar_m2_ss_cmp), 
    .arlen(arlen_m2_ss_cmp), 
    .arsize(arsize_m2_ss_cmp), 
    .arburst(arburst_m2_ss_cmp), 
    .arlock(arlock_m2_ss_cmp), 
    .arcache(arcache_m2_ss_cmp), 
    .arprot(arprot_m2_ss_cmp), 
    .arqos(arqos_m2_ss_cmp), 
    .arvalid(arvalid_m2_ss_cmp), 
    .arready(arready_m2_ss_cmp), 
    .rid(rid_m2_ss_cmp), 
    .rdata(rdata_m2_ss_cmp), 
    .rresp(rresp_m2_ss_cmp), 
    .rlast(rlast_m2_ss_cmp), 
    .rvalid(rvalid_m2_ss_cmp), 
    .rready(rready_m2_ss_cmp), 
    .acaddr(acaddr_m2_ss_cmp), 
    .acsnoop(acsnoop_m2_ss_cmp), 
    .acprot(acprot_m2_ss_cmp), 
    .acvalid(acvalid_m2_ss_cmp), 
    .acready(acready_m2_ss_cmp), 
    .crresp(crresp_m2_ss_cmp), 
    .crvalid(crvalid_m2_ss_cmp), 
    .crready(crready_m2_ss_cmp), 
    .cddata(cddata_m2_ss_cmp), 
    .cdlast(cdlast_m2_ss_cmp), 
    .cdvalid(cdvalid_m2_ss_cmp), 
    .cdready(cdready_m2_ss_cmp), 
    .rack(rack_m2_ss_cmp), 
    .wack(wack_m2_ss_cmp), 
    .awuser(awuser_m2_ss_cmp), 
    .wuser(wuser_m2_ss_cmp), 
    .buser(buser_m2_ss_cmp), 
    .aruser(aruser_m2_ss_cmp), 
    .ruser(ruser_m2_ss_cmp) 
  );
`endif

`ifdef REPLACE_BD_ACE_M2_SS_CMP 

  svt_axi_master_connector#(1) bd_ace_m2_ss_cmp(
    .master_if(coretop_axi_if_0.master_if[10]), 
    .master_bind_if(`CORETOP.u_ss_cmp.bd_ace_m2_ss_cmp_bind_if) 
  );

`elsif CONNECT_BD_ACE_M2_SS_CMP 

  svt_axi_master_connector#(0) bd_ace_m2_ss_cmp(
    .master_if(coretop_axi_if_0.master_if[10]), 
    .master_bind_if(`CORETOP.u_ss_cmp.bd_ace_m2_ss_cmp_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_SS_CMP 
  bind `CORETOP.u_ss_cmp svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(24), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_ss_cmp_bind_if (
    .paddr(paddr_s_ss_cmp), 
    .psel(psel_s_ss_cmp), 
    .penable(penable_s_ss_cmp), 
    .pwrite(pwrite_s_ss_cmp), 
    .prdata(prdata_s_ss_cmp), 
    .pwdata(pwdata_s_ss_cmp), 
    .pprot(pprot_s_ss_cmp), 
    .pstrb(pstrb_s_ss_cmp), 
    .pready(pready_s_ss_cmp) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[9].pslverr = 0;  
end

`ifdef REPLACE_BD_APB_S_SS_CMP 

  svt_apb_slave_connector#(1) bd_apb_s_ss_cmp(
    .slave_if(coretop_apb_if_0.slave_if[9]), 
    .slave_bind_if(`CORETOP.u_ss_cmp.bd_apb_s_ss_cmp_bind_if) 
  );

`elsif CONNECT_BD_APB_S_SS_CMP 

  svt_apb_slave_connector#(0) bd_apb_s_ss_cmp(
    .slave_if(coretop_apb_if_0.slave_if[9]), 
    .slave_bind_if(`CORETOP.u_ss_cmp.bd_apb_s_ss_cmp_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_M_SS_CON 
  bind `CORETOP.u_ss_con svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(8), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(8), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(8), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(8), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m_ss_con_bind_if (
    .awid(awid_m_ss_con), 
    .awaddr(awaddr_m_ss_con), 
    .awlen(awlen_m_ss_con), 
    .awsize(awsize_m_ss_con), 
    .awburst(awburst_m_ss_con), 
    .awlock(awlock_m_ss_con), 
    .awcache(awcache_m_ss_con), 
    .awprot(awprot_m_ss_con), 
    .awqos(awqos_m_ss_con), 
    .awvalid(awvalid_m_ss_con), 
    .awready(awready_m_ss_con), 
    .wdata(wdata_m_ss_con), 
    .wstrb(wstrb_m_ss_con), 
    .wlast(wlast_m_ss_con), 
    .wvalid(wvalid_m_ss_con), 
    .wready(wready_m_ss_con), 
    .bid(bid_m_ss_con), 
    .bresp(bresp_m_ss_con), 
    .bvalid(bvalid_m_ss_con), 
    .bready(bready_m_ss_con), 
    .arid(arid_m_ss_con), 
    .araddr(araddr_m_ss_con), 
    .arlen(arlen_m_ss_con), 
    .arsize(arsize_m_ss_con), 
    .arburst(arburst_m_ss_con), 
    .arlock(arlock_m_ss_con), 
    .arcache(arcache_m_ss_con), 
    .arprot(arprot_m_ss_con), 
    .arqos(arqos_m_ss_con), 
    .arvalid(arvalid_m_ss_con), 
    .arready(arready_m_ss_con), 
    .rid(rid_m_ss_con), 
    .rdata(rdata_m_ss_con), 
    .rresp(rresp_m_ss_con), 
    .rlast(rlast_m_ss_con), 
    .rvalid(rvalid_m_ss_con), 
    .rready(rready_m_ss_con) 
  );
`endif

`ifdef REPLACE_BD_AXI_M_SS_CON 

  svt_axi_master_connector#(1) bd_axi_m_ss_con(
    .master_if(coretop_axi_if_0.master_if[11]), 
    .master_bind_if(`CORETOP.u_ss_con.bd_axi_m_ss_con_bind_if) 
  );

`elsif CONNECT_BD_AXI_M_SS_CON 

  svt_axi_master_connector#(0) bd_axi_m_ss_con(
    .master_if(coretop_axi_if_0.master_if[11]), 
    .master_bind_if(`CORETOP.u_ss_con.bd_axi_m_ss_con_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_S_SS_CON 
  bind `CORETOP.u_ss_con svt_axi_slave_bind_if #(
    .AWID_WIDTH_PARAM(16), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(16), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(16), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(16), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_s_ss_con_bind_if (
    .awid(awid_s_ss_con), 
    .awaddr(awaddr_s_ss_con), 
    .awlen(awlen_s_ss_con), 
    .awsize(awsize_s_ss_con), 
    .awburst(awburst_s_ss_con), 
    .awlock(awlock_s_ss_con), 
    .awcache(awcache_s_ss_con), 
    .awprot(awprot_s_ss_con), 
    .awqos(awqos_s_ss_con), 
    .awvalid(awvalid_s_ss_con), 
    .awready(awready_s_ss_con), 
    .wdata(wdata_s_ss_con), 
    .wstrb(wstrb_s_ss_con), 
    .wlast(wlast_s_ss_con), 
    .wvalid(wvalid_s_ss_con), 
    .wready(wready_s_ss_con), 
    .bid(bid_s_ss_con), 
    .bresp(bresp_s_ss_con), 
    .bvalid(bvalid_s_ss_con), 
    .bready(bready_s_ss_con), 
    .arid(arid_s_ss_con), 
    .araddr(araddr_s_ss_con), 
    .arlen(arlen_s_ss_con), 
    .arsize(arsize_s_ss_con), 
    .arburst(arburst_s_ss_con), 
    .arlock(arlock_s_ss_con), 
    .arcache(arcache_s_ss_con), 
    .arprot(arprot_s_ss_con), 
    .arqos(arqos_s_ss_con), 
    .arvalid(arvalid_s_ss_con), 
    .arready(arready_s_ss_con), 
    .rid(rid_s_ss_con), 
    .rdata(rdata_s_ss_con), 
    .rresp(rresp_s_ss_con), 
    .rlast(rlast_s_ss_con), 
    .rvalid(rvalid_s_ss_con), 
    .rready(rready_s_ss_con) 
  );
`endif

`ifdef REPLACE_BD_AXI_S_SS_CON 

  svt_axi_slave_connector#(1) bd_axi_s_ss_con(
    .slave_if(coretop_axi_if_0.slave_if[1]), 
    .slave_bind_if(`CORETOP.u_ss_con.bd_axi_s_ss_con_bind_if) 
  );

`elsif CONNECT_BD_AXI_S_SS_CON 

  svt_axi_slave_connector#(0) bd_axi_s_ss_con(
    .slave_if(coretop_axi_if_0.slave_if[1]), 
    .slave_bind_if(`CORETOP.u_ss_con.bd_axi_s_ss_con_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_SS_CON 
  bind `CORETOP.u_ss_con svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(24), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_ss_con_bind_if (
    .paddr(paddr_s_ss_con), 
    .psel(psel_s_ss_con), 
    .penable(penable_s_ss_con), 
    .pwrite(pwrite_s_ss_con), 
    .prdata(prdata_s_ss_con), 
    .pwdata(pwdata_s_ss_con), 
    .pprot(pprot_s_ss_con), 
    .pstrb(pstrb_s_ss_con), 
    .pready(pready_s_ss_con) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[10].pslverr = 0;  
end

`ifdef REPLACE_BD_APB_S_SS_CON 

  svt_apb_slave_connector#(1) bd_apb_s_ss_con(
    .slave_if(coretop_apb_if_0.slave_if[10]), 
    .slave_bind_if(`CORETOP.u_ss_con.bd_apb_s_ss_con_bind_if) 
  );

`elsif CONNECT_BD_APB_S_SS_CON 

  svt_apb_slave_connector#(0) bd_apb_s_ss_con(
    .slave_if(coretop_apb_if_0.slave_if[10]), 
    .slave_bind_if(`CORETOP.u_ss_con.bd_apb_s_ss_con_bind_if) 
  );

`endif

`ifdef BIND_BD_ACE_M_SS_CPU 
  bind `CORETOP.u_ss_cpu svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(9), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWDOMAIN_WIDTH_PARAM(2), 
    .AWSNOOP_WIDTH_PARAM(3), 
    .AWBAR_WIDTH_PARAM(2), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(128), 
    .WSTRB_WIDTH_PARAM(16), 
    .BID_WIDTH_PARAM(9), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(9), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARDOMAIN_WIDTH_PARAM(2), 
    .ARSNOOP_WIDTH_PARAM(4), 
    .ARBAR_WIDTH_PARAM(2), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(9), 
    .RDATA_WIDTH_PARAM(128), 
    .RRESP_WIDTH_PARAM(4), 
    .ACADDR_WIDTH_PARAM(40), 
    .ACSNOOP_WIDTH_PARAM(4), 
    .ACPROT_WIDTH_PARAM(3), 
    .CRRESP_WIDTH_PARAM(5), 
    .CDDATA_WIDTH_PARAM(128), 
    .AWUSER_WIDTH_PARAM(9), 
    .ARUSER_WIDTH_PARAM(9) 
  ) bd_ace_m_ss_cpu_bind_if (
    .awid(awid_m_ss_cpu), 
    .awaddr(awaddr_m_ss_cpu), 
    .awdomain(awdomain_m_ss_cpu), 
    .awsnoop(awsnoop_m_ss_cpu), 
    .awbar(awbar_m_ss_cpu), 
    .awlen(awlen_m_ss_cpu), 
    .awsize(awsize_m_ss_cpu), 
    .awburst(awburst_m_ss_cpu), 
    .awlock(awlock_m_ss_cpu), 
    .awcache(awcache_m_ss_cpu), 
    .awprot(awprot_m_ss_cpu), 
    .awqos(awqos_m_ss_cpu), 
    .awvalid(awvalid_m_ss_cpu), 
    .awready(awready_m_ss_cpu), 
    .wdata(wdata_m_ss_cpu), 
    .wstrb(wstrb_m_ss_cpu), 
    .wlast(wlast_m_ss_cpu), 
    .wvalid(wvalid_m_ss_cpu), 
    .wready(wready_m_ss_cpu), 
    .bid(bid_m_ss_cpu), 
    .bresp(bresp_m_ss_cpu), 
    .bvalid(bvalid_m_ss_cpu), 
    .bready(bready_m_ss_cpu), 
    .arid(arid_m_ss_cpu), 
    .araddr(araddr_m_ss_cpu), 
    .ardomain(ardomain_m_ss_cpu), 
    .arsnoop(arsnoop_m_ss_cpu), 
    .arbar(arbar_m_ss_cpu), 
    .arlen(arlen_m_ss_cpu), 
    .arsize(arsize_m_ss_cpu), 
    .arburst(arburst_m_ss_cpu), 
    .arlock(arlock_m_ss_cpu), 
    .arcache(arcache_m_ss_cpu), 
    .arprot(arprot_m_ss_cpu), 
    .arqos(arqos_m_ss_cpu), 
    .arvalid(arvalid_m_ss_cpu), 
    .arready(arready_m_ss_cpu), 
    .rid(rid_m_ss_cpu), 
    .rdata(rdata_m_ss_cpu), 
    .rresp(rresp_m_ss_cpu), 
    .rlast(rlast_m_ss_cpu), 
    .rvalid(rvalid_m_ss_cpu), 
    .rready(rready_m_ss_cpu), 
    .acaddr(acaddr_m_ss_cpu), 
    .acsnoop(acsnoop_m_ss_cpu), 
    .acprot(acprot_m_ss_cpu), 
    .acvalid(acvalid_m_ss_cpu), 
    .acready(acready_m_ss_cpu), 
    .crresp(crresp_m_ss_cpu), 
    .crvalid(crvalid_m_ss_cpu), 
    .crready(crready_m_ss_cpu), 
    .cddata(cddata_m_ss_cpu), 
    .cdlast(cdlast_m_ss_cpu), 
    .cdvalid(cdvalid_m_ss_cpu), 
    .cdready(cdready_m_ss_cpu), 
    .rack(rack_m_ss_cpu), 
    .wack(wack_m_ss_cpu), 
    .awuser(awuser_m_ss_cpu), 
    .wuser(wuser_m_ss_cpu), 
    .buser(buser_m_ss_cpu), 
    .aruser(aruser_m_ss_cpu), 
    .ruser(ruser_m_ss_cpu) 
  );
`endif

`ifdef REPLACE_BD_ACE_M_SS_CPU 

  svt_axi_master_connector#(1) bd_ace_m_ss_cpu(
    .master_if(coretop_axi_if_0.master_if[12]), 
    .master_bind_if(`CORETOP.u_ss_cpu.bd_ace_m_ss_cpu_bind_if) 
  );

`elsif CONNECT_BD_ACE_M_SS_CPU 

  svt_axi_master_connector#(0) bd_ace_m_ss_cpu(
    .master_if(coretop_axi_if_0.master_if[12]), 
    .master_bind_if(`CORETOP.u_ss_cpu.bd_ace_m_ss_cpu_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_S_SS_CPU 
  bind `CORETOP.u_ss_cpu svt_axi_slave_bind_if #(
    .AWID_WIDTH_PARAM(12), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(128), 
    .WSTRB_WIDTH_PARAM(16), 
    .BID_WIDTH_PARAM(12), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(12), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(12), 
    .RDATA_WIDTH_PARAM(128), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_s_ss_cpu_bind_if (
    .awid(awid_s_ss_cpu), 
    .awaddr(awaddr_s_ss_cpu), 
    .awlen(awlen_s_ss_cpu), 
    .awsize(awsize_s_ss_cpu), 
    .awburst(awburst_s_ss_cpu), 
    .awlock(awlock_s_ss_cpu), 
    .awcache(awcache_s_ss_cpu), 
    .awprot(awprot_s_ss_cpu), 
    .awqos(awqos_s_ss_cpu), 
    .awvalid(awvalid_s_ss_cpu), 
    .awready(awready_s_ss_cpu), 
    .wdata(wdata_s_ss_cpu), 
    .wstrb(wstrb_s_ss_cpu), 
    .wlast(wlast_s_ss_cpu), 
    .wvalid(wvalid_s_ss_cpu), 
    .wready(wready_s_ss_cpu), 
    .bid(bid_s_ss_cpu), 
    .bresp(bresp_s_ss_cpu), 
    .bvalid(bvalid_s_ss_cpu), 
    .bready(bready_s_ss_cpu), 
    .arid(arid_s_ss_cpu), 
    .araddr(araddr_s_ss_cpu), 
    .arlen(arlen_s_ss_cpu), 
    .arsize(arsize_s_ss_cpu), 
    .arburst(arburst_s_ss_cpu), 
    .arlock(arlock_s_ss_cpu), 
    .arcache(arcache_s_ss_cpu), 
    .arprot(arprot_s_ss_cpu), 
    .arqos(arqos_s_ss_cpu), 
    .arvalid(arvalid_s_ss_cpu), 
    .arready(arready_s_ss_cpu), 
    .rid(rid_s_ss_cpu), 
    .rdata(rdata_s_ss_cpu), 
    .rresp(rresp_s_ss_cpu), 
    .rlast(rlast_s_ss_cpu), 
    .rvalid(rvalid_s_ss_cpu), 
    .rready(rready_s_ss_cpu) 
  );
`endif

`ifdef REPLACE_BD_AXI_S_SS_CPU 

  svt_axi_slave_connector#(1) bd_axi_s_ss_cpu(
    .slave_if(coretop_axi_if_0.slave_if[2]), 
    .slave_bind_if(`CORETOP.u_ss_cpu.bd_axi_s_ss_cpu_bind_if) 
  );

`elsif CONNECT_BD_AXI_S_SS_CPU 

  svt_axi_slave_connector#(0) bd_axi_s_ss_cpu(
    .slave_if(coretop_axi_if_0.slave_if[2]), 
    .slave_bind_if(`CORETOP.u_ss_cpu.bd_axi_s_ss_cpu_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_M_SS_CPU 
  bind `CORETOP.u_ss_cpu svt_apb_master_bind_if #(
    .PADDR_WIDTH_PARAM(40), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_m_ss_cpu_bind_if (
    .paddr(paddr_m_ss_cpu), 
    .psel(psel_m_ss_cpu), 
    .penable(penable_m_ss_cpu), 
    .pwrite(pwrite_m_ss_cpu), 
    .prdata(prdata_m_ss_cpu), 
    .pwdata(pwdata_m_ss_cpu), 
    .pprot(pprot_m_ss_cpu), 
    .pstrb(pstrb_m_ss_cpu), 
    .pready(pready_m_ss_cpu) 
  );
`endif

initial begin
  force `CORETOP.u_ss_cpu.bd_apb_m_ss_cpu_bind_if.pslverr = 0; 
end

`ifdef REPLACE_BD_APB_M_SS_CPU 

  svt_apb_master_connector#(1) bd_apb_m_ss_cpu(
    .master_if(coretop_apb_if_3), 
    .master_bind_if(`CORETOP.u_ss_cpu.bd_apb_m_ss_cpu_bind_if) 
  );

`elsif CONNECT_BD_APB_M_SS_CPU 

  svt_apb_master_connector#(0) bd_apb_m_ss_cpu(
    .master_if(coretop_apb_if_3), 
    .master_bind_if(`CORETOP.u_ss_cpu.bd_apb_m_ss_cpu_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_SS_CPU 
  bind `CORETOP.u_ss_cpu svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(24), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_ss_cpu_bind_if (
    .paddr(paddr_s_ss_cpu), 
    .psel(psel_s_ss_cpu), 
    .penable(penable_s_ss_cpu), 
    .pwrite(pwrite_s_ss_cpu), 
    .prdata(prdata_s_ss_cpu), 
    .pwdata(pwdata_s_ss_cpu), 
    .pprot(pprot_s_ss_cpu), 
    .pstrb(pstrb_s_ss_cpu), 
    .pready(pready_s_ss_cpu) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[11].pslverr = 0;  
end

`ifdef REPLACE_BD_APB_S_SS_CPU 

  svt_apb_slave_connector#(1) bd_apb_s_ss_cpu(
    .slave_if(coretop_apb_if_0.slave_if[11]), 
    .slave_bind_if(`CORETOP.u_ss_cpu.bd_apb_s_ss_cpu_bind_if) 
  );

`elsif CONNECT_BD_APB_S_SS_CPU 

  svt_apb_slave_connector#(0) bd_apb_s_ss_cpu(
    .slave_if(coretop_apb_if_0.slave_if[11]), 
    .slave_bind_if(`CORETOP.u_ss_cpu.bd_apb_s_ss_cpu_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_M0_SS_VIS 
  bind `CORETOP.u_ss_vis svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(3), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(3), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(3), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(3), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m0_ss_vis_bind_if (
    .awid(awid_m0_ss_vis), 
    .awaddr(awaddr_m0_ss_vis), 
    .awlen(awlen_m0_ss_vis), 
    .awsize(awsize_m0_ss_vis), 
    .awburst(awburst_m0_ss_vis), 
    .awlock(awlock_m0_ss_vis), 
    .awcache(awcache_m0_ss_vis), 
    .awprot(awprot_m0_ss_vis), 
    .awqos(awqos_m0_ss_vis), 
    .awvalid(awvalid_m0_ss_vis), 
    .awready(awready_m0_ss_vis), 
    .wdata(wdata_m0_ss_vis), 
    .wstrb(wstrb_m0_ss_vis), 
    .wlast(wlast_m0_ss_vis), 
    .wvalid(wvalid_m0_ss_vis), 
    .wready(wready_m0_ss_vis), 
    .bid(bid_m0_ss_vis), 
    .bresp(bresp_m0_ss_vis), 
    .bvalid(bvalid_m0_ss_vis), 
    .bready(bready_m0_ss_vis), 
    .arid(arid_m0_ss_vis), 
    .araddr(araddr_m0_ss_vis), 
    .arlen(arlen_m0_ss_vis), 
    .arsize(arsize_m0_ss_vis), 
    .arburst(arburst_m0_ss_vis), 
    .arlock(arlock_m0_ss_vis), 
    .arcache(arcache_m0_ss_vis), 
    .arprot(arprot_m0_ss_vis), 
    .arqos(arqos_m0_ss_vis), 
    .arvalid(arvalid_m0_ss_vis), 
    .arready(arready_m0_ss_vis), 
    .rid(rid_m0_ss_vis), 
    .rdata(rdata_m0_ss_vis), 
    .rresp(rresp_m0_ss_vis), 
    .rlast(rlast_m0_ss_vis), 
    .rvalid(rvalid_m0_ss_vis), 
    .rready(rready_m0_ss_vis) 
  );
`endif

`ifdef REPLACE_BD_AXI_M0_SS_VIS 

  svt_axi_master_connector#(1) bd_axi_m0_ss_vis(
    .master_if(coretop_axi_if_0.master_if[13]), 
    .master_bind_if(`CORETOP.u_ss_vis.bd_axi_m0_ss_vis_bind_if) 
  );

`elsif CONNECT_BD_AXI_M0_SS_VIS 

  svt_axi_master_connector#(0) bd_axi_m0_ss_vis(
    .master_if(coretop_axi_if_0.master_if[13]), 
    .master_bind_if(`CORETOP.u_ss_vis.bd_axi_m0_ss_vis_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_M1_SS_VIS 
  bind `CORETOP.u_ss_vis svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(3), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(3), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(3), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(3), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m1_ss_vis_bind_if (
    .awid(awid_m1_ss_vis), 
    .awaddr(awaddr_m1_ss_vis), 
    .awlen(awlen_m1_ss_vis), 
    .awsize(awsize_m1_ss_vis), 
    .awburst(awburst_m1_ss_vis), 
    .awlock(awlock_m1_ss_vis), 
    .awcache(awcache_m1_ss_vis), 
    .awprot(awprot_m1_ss_vis), 
    .awqos(awqos_m1_ss_vis), 
    .awvalid(awvalid_m1_ss_vis), 
    .awready(awready_m1_ss_vis), 
    .wdata(wdata_m1_ss_vis), 
    .wstrb(wstrb_m1_ss_vis), 
    .wlast(wlast_m1_ss_vis), 
    .wvalid(wvalid_m1_ss_vis), 
    .wready(wready_m1_ss_vis), 
    .bid(bid_m1_ss_vis), 
    .bresp(bresp_m1_ss_vis), 
    .bvalid(bvalid_m1_ss_vis), 
    .bready(bready_m1_ss_vis), 
    .arid(arid_m1_ss_vis), 
    .araddr(araddr_m1_ss_vis), 
    .arlen(arlen_m1_ss_vis), 
    .arsize(arsize_m1_ss_vis), 
    .arburst(arburst_m1_ss_vis), 
    .arlock(arlock_m1_ss_vis), 
    .arcache(arcache_m1_ss_vis), 
    .arprot(arprot_m1_ss_vis), 
    .arqos(arqos_m1_ss_vis), 
    .arvalid(arvalid_m1_ss_vis), 
    .arready(arready_m1_ss_vis), 
    .rid(rid_m1_ss_vis), 
    .rdata(rdata_m1_ss_vis), 
    .rresp(rresp_m1_ss_vis), 
    .rlast(rlast_m1_ss_vis), 
    .rvalid(rvalid_m1_ss_vis), 
    .rready(rready_m1_ss_vis) 
  );
`endif

`ifdef REPLACE_BD_AXI_M1_SS_VIS 

  svt_axi_master_connector#(1) bd_axi_m1_ss_vis(
    .master_if(coretop_axi_if_0.master_if[14]), 
    .master_bind_if(`CORETOP.u_ss_vis.bd_axi_m1_ss_vis_bind_if) 
  );

`elsif CONNECT_BD_AXI_M1_SS_VIS 

  svt_axi_master_connector#(0) bd_axi_m1_ss_vis(
    .master_if(coretop_axi_if_0.master_if[14]), 
    .master_bind_if(`CORETOP.u_ss_vis.bd_axi_m1_ss_vis_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_SS_VIS 
  bind `CORETOP.u_ss_vis svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(24), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_ss_vis_bind_if (
    .paddr(paddr_s_ss_vis), 
    .psel(psel_s_ss_vis), 
    .penable(penable_s_ss_vis), 
    .pwrite(pwrite_s_ss_vis), 
    .prdata(prdata_s_ss_vis), 
    .pwdata(pwdata_s_ss_vis), 
    .pprot(pprot_s_ss_vis), 
    .pstrb(pstrb_s_ss_vis), 
    .pready(pready_s_ss_vis) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[12].pslverr = 0;  
end

`ifdef REPLACE_BD_APB_S_SS_VIS 

  svt_apb_slave_connector#(1) bd_apb_s_ss_vis(
    .slave_if(coretop_apb_if_0.slave_if[12]), 
    .slave_bind_if(`CORETOP.u_ss_vis.bd_apb_s_ss_vis_bind_if) 
  );

`elsif CONNECT_BD_APB_S_SS_VIS 

  svt_apb_slave_connector#(0) bd_apb_s_ss_vis(
    .slave_if(coretop_apb_if_0.slave_if[12]), 
    .slave_bind_if(`CORETOP.u_ss_vis.bd_apb_s_ss_vis_bind_if) 
  );

`endif

`ifdef BIND_AXI_S0_DDR_CHIP 
  bind `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip svt_axi_slave_bind_if #(
    .AWID_WIDTH_PARAM(16), 
    .AWADDR_WIDTH_PARAM(32), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .AWREGION_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(128), 
    .WSTRB_WIDTH_PARAM(16), 
    .BID_WIDTH_PARAM(16), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(16), 
    .ARADDR_WIDTH_PARAM(32), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .ARREGION_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(16), 
    .RDATA_WIDTH_PARAM(128), 
    .RRESP_WIDTH_PARAM(2) 
  ) axi_s0_ddr_chip_bind_if (
    .awid(awid_0), 
    .awaddr(awaddr_0), 
    .awlen(awlen_0), 
    .awsize(awsize_0), 
    .awburst(awburst_0), 
    .awlock(awlock_0), 
    .awcache(awcache_0), 
    .awprot(awprot_0), 
    .awqos(awqos_0), 
    .awregion(awregion_0), 
    .awvalid(awvalid_0), 
    .awready(awready_0), 
    .wdata(wdata_0), 
    .wstrb(wstrb_0), 
    .wlast(wlast_0), 
    .wvalid(wvalid_0), 
    .wready(wready_0), 
    .bid(bid_0), 
    .bresp(bresp_0), 
    .bvalid(bvalid_0), 
    .bready(bready_0), 
    .arid(arid_0), 
    .araddr(araddr_0), 
    .arlen(arlen_0), 
    .arsize(arsize_0), 
    .arburst(arburst_0), 
    .arlock(arlock_0), 
    .arcache(arcache_0), 
    .arprot(arprot_0), 
    .arqos(arqos_0), 
    .arregion(arregion_0), 
    .arvalid(arvalid_0), 
    .arready(arready_0), 
    .rid(rid_0), 
    .rdata(rdata_0), 
    .rresp(rresp_0), 
    .rlast(rlast_0), 
    .rvalid(rvalid_0), 
    .rready(rready_0) 
  );
`endif

`ifdef REPLACE_AXI_S0_DDR_CHIP 

  svt_axi_slave_connector#(1) axi_s0_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[3]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s0_ddr_chip_bind_if) 
  );

`elsif CONNECT_AXI_S0_DDR_CHIP 

  svt_axi_slave_connector#(0) axi_s0_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[3]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s0_ddr_chip_bind_if) 
  );

`endif

`ifdef BIND_AXI_S1_DDR_CHIP 
  bind `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip svt_axi_slave_bind_if #(
    .AWID_WIDTH_PARAM(16), 
    .AWADDR_WIDTH_PARAM(32), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .AWREGION_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(128), 
    .WSTRB_WIDTH_PARAM(16), 
    .BID_WIDTH_PARAM(16), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(16), 
    .ARADDR_WIDTH_PARAM(32), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .ARREGION_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(16), 
    .RDATA_WIDTH_PARAM(128), 
    .RRESP_WIDTH_PARAM(2) 
  ) axi_s1_ddr_chip_bind_if (
    .awid(awid_1), 
    .awaddr(awaddr_1), 
    .awlen(awlen_1), 
    .awsize(awsize_1), 
    .awburst(awburst_1), 
    .awlock(awlock_1), 
    .awcache(awcache_1), 
    .awprot(awprot_1), 
    .awqos(awqos_1), 
    .awregion(awregion_1), 
    .awvalid(awvalid_1), 
    .awready(awready_1), 
    .wdata(wdata_1), 
    .wstrb(wstrb_1), 
    .wlast(wlast_1), 
    .wvalid(wvalid_1), 
    .wready(wready_1), 
    .bid(bid_1), 
    .bresp(bresp_1), 
    .bvalid(bvalid_1), 
    .bready(bready_1), 
    .arid(arid_1), 
    .araddr(araddr_1), 
    .arlen(arlen_1), 
    .arsize(arsize_1), 
    .arburst(arburst_1), 
    .arlock(arlock_1), 
    .arcache(arcache_1), 
    .arprot(arprot_1), 
    .arqos(arqos_1), 
    .arregion(arregion_1), 
    .arvalid(arvalid_1), 
    .arready(arready_1), 
    .rid(rid_1), 
    .rdata(rdata_1), 
    .rresp(rresp_1), 
    .rlast(rlast_1), 
    .rvalid(rvalid_1), 
    .rready(rready_1) 
  );
`endif

`ifdef REPLACE_AXI_S1_DDR_CHIP 

  svt_axi_slave_connector#(1) axi_s1_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[4]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s1_ddr_chip_bind_if) 
  );

`elsif CONNECT_AXI_S1_DDR_CHIP 

  svt_axi_slave_connector#(0) axi_s1_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[4]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s1_ddr_chip_bind_if) 
  );

`endif

`ifdef BIND_AXI_S2_DDR_CHIP 
  bind `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip svt_axi_slave_bind_if #(
    .AWID_WIDTH_PARAM(16), 
    .AWADDR_WIDTH_PARAM(32), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .AWREGION_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(16), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(16), 
    .ARADDR_WIDTH_PARAM(32), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .ARREGION_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(16), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) axi_s2_ddr_chip_bind_if (
    .awid(awid_2), 
    .awaddr(awaddr_2), 
    .awlen(awlen_2), 
    .awsize(awsize_2), 
    .awburst(awburst_2), 
    .awlock(awlock_2), 
    .awcache(awcache_2), 
    .awprot(awprot_2), 
    .awqos(awqos_2), 
    .awregion(awregion_2), 
    .awvalid(awvalid_2), 
    .awready(awready_2), 
    .wdata(wdata_2), 
    .wstrb(wstrb_2), 
    .wlast(wlast_2), 
    .wvalid(wvalid_2), 
    .wready(wready_2), 
    .bid(bid_2), 
    .bresp(bresp_2), 
    .bvalid(bvalid_2), 
    .bready(bready_2), 
    .arid(arid_2), 
    .araddr(araddr_2), 
    .arlen(arlen_2), 
    .arsize(arsize_2), 
    .arburst(arburst_2), 
    .arlock(arlock_2), 
    .arcache(arcache_2), 
    .arprot(arprot_2), 
    .arqos(arqos_2), 
    .arregion(arregion_2), 
    .arvalid(arvalid_2), 
    .arready(arready_2), 
    .rid(rid_2), 
    .rdata(rdata_2), 
    .rresp(rresp_2), 
    .rlast(rlast_2), 
    .rvalid(rvalid_2), 
    .rready(rready_2) 
  );
`endif

`ifdef REPLACE_AXI_S2_DDR_CHIP 

  svt_axi_slave_connector#(1) axi_s2_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[5]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s2_ddr_chip_bind_if) 
  );

`elsif CONNECT_AXI_S2_DDR_CHIP 

  svt_axi_slave_connector#(0) axi_s2_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[5]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s2_ddr_chip_bind_if) 
  );

`endif

`ifdef BIND_AXI_S3_DDR_CHIP 
  bind `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip svt_axi_slave_bind_if #(
    .AWID_WIDTH_PARAM(16), 
    .AWADDR_WIDTH_PARAM(32), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .AWREGION_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(16), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(16), 
    .ARADDR_WIDTH_PARAM(32), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .ARREGION_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(16), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) axi_s3_ddr_chip_bind_if (
    .awid(awid_3), 
    .awaddr(awaddr_3), 
    .awlen(awlen_3), 
    .awsize(awsize_3), 
    .awburst(awburst_3), 
    .awlock(awlock_3), 
    .awcache(awcache_3), 
    .awprot(awprot_3), 
    .awqos(awqos_3), 
    .awregion(awregion_3), 
    .awvalid(awvalid_3), 
    .awready(awready_3), 
    .wdata(wdata_3), 
    .wstrb(wstrb_3), 
    .wlast(wlast_3), 
    .wvalid(wvalid_3), 
    .wready(wready_3), 
    .bid(bid_3), 
    .bresp(bresp_3), 
    .bvalid(bvalid_3), 
    .bready(bready_3), 
    .arid(arid_3), 
    .araddr(araddr_3), 
    .arlen(arlen_3), 
    .arsize(arsize_3), 
    .arburst(arburst_3), 
    .arlock(arlock_3), 
    .arcache(arcache_3), 
    .arprot(arprot_3), 
    .arqos(arqos_3), 
    .arregion(arregion_3), 
    .arvalid(arvalid_3), 
    .arready(arready_3), 
    .rid(rid_3), 
    .rdata(rdata_3), 
    .rresp(rresp_3), 
    .rlast(rlast_3), 
    .rvalid(rvalid_3), 
    .rready(rready_3) 
  );
`endif

`ifdef REPLACE_AXI_S3_DDR_CHIP 

  svt_axi_slave_connector#(1) axi_s3_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[6]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s3_ddr_chip_bind_if) 
  );

`elsif CONNECT_AXI_S3_DDR_CHIP 

  svt_axi_slave_connector#(0) axi_s3_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[6]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s3_ddr_chip_bind_if) 
  );

`endif

`ifdef BIND_AXI_S4_DDR_CHIP 
  bind `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip svt_axi_slave_bind_if #(
    .AWID_WIDTH_PARAM(16), 
    .AWADDR_WIDTH_PARAM(32), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .AWREGION_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(16), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(16), 
    .ARADDR_WIDTH_PARAM(32), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .ARREGION_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(16), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) axi_s4_ddr_chip_bind_if (
    .awid(awid_4), 
    .awaddr(awaddr_4), 
    .awlen(awlen_4), 
    .awsize(awsize_4), 
    .awburst(awburst_4), 
    .awlock(awlock_4), 
    .awcache(awcache_4), 
    .awprot(awprot_4), 
    .awqos(awqos_4), 
    .awregion(awregion_4), 
    .awvalid(awvalid_4), 
    .awready(awready_4), 
    .wdata(wdata_4), 
    .wstrb(wstrb_4), 
    .wlast(wlast_4), 
    .wvalid(wvalid_4), 
    .wready(wready_4), 
    .bid(bid_4), 
    .bresp(bresp_4), 
    .bvalid(bvalid_4), 
    .bready(bready_4), 
    .arid(arid_4), 
    .araddr(araddr_4), 
    .arlen(arlen_4), 
    .arsize(arsize_4), 
    .arburst(arburst_4), 
    .arlock(arlock_4), 
    .arcache(arcache_4), 
    .arprot(arprot_4), 
    .arqos(arqos_4), 
    .arregion(arregion_4), 
    .arvalid(arvalid_4), 
    .arready(arready_4), 
    .rid(rid_4), 
    .rdata(rdata_4), 
    .rresp(rresp_4), 
    .rlast(rlast_4), 
    .rvalid(rvalid_4), 
    .rready(rready_4) 
  );
`endif

`ifdef REPLACE_AXI_S4_DDR_CHIP 

  svt_axi_slave_connector#(1) axi_s4_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[7]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s4_ddr_chip_bind_if) 
  );

`elsif CONNECT_AXI_S4_DDR_CHIP 

  svt_axi_slave_connector#(0) axi_s4_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[7]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s4_ddr_chip_bind_if) 
  );

`endif

`ifdef BIND_AXI_S5_DDR_CHIP 
  bind `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip svt_axi_slave_bind_if #(
    .AWID_WIDTH_PARAM(16), 
    .AWADDR_WIDTH_PARAM(32), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .AWREGION_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(16), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(16), 
    .ARADDR_WIDTH_PARAM(32), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .ARREGION_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(16), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) axi_s5_ddr_chip_bind_if (
    .awid(awid_5), 
    .awaddr(awaddr_5), 
    .awlen(awlen_5), 
    .awsize(awsize_5), 
    .awburst(awburst_5), 
    .awlock(awlock_5), 
    .awcache(awcache_5), 
    .awprot(awprot_5), 
    .awqos(awqos_5), 
    .awregion(awregion_5), 
    .awvalid(awvalid_5), 
    .awready(awready_5), 
    .wdata(wdata_5), 
    .wstrb(wstrb_5), 
    .wlast(wlast_5), 
    .wvalid(wvalid_5), 
    .wready(wready_5), 
    .bid(bid_5), 
    .bresp(bresp_5), 
    .bvalid(bvalid_5), 
    .bready(bready_5), 
    .arid(arid_5), 
    .araddr(araddr_5), 
    .arlen(arlen_5), 
    .arsize(arsize_5), 
    .arburst(arburst_5), 
    .arlock(arlock_5), 
    .arcache(arcache_5), 
    .arprot(arprot_5), 
    .arqos(arqos_5), 
    .arregion(arregion_5), 
    .arvalid(arvalid_5), 
    .arready(arready_5), 
    .rid(rid_5), 
    .rdata(rdata_5), 
    .rresp(rresp_5), 
    .rlast(rlast_5), 
    .rvalid(rvalid_5), 
    .rready(rready_5) 
  );
`endif

`ifdef REPLACE_AXI_S5_DDR_CHIP 

  svt_axi_slave_connector#(1) axi_s5_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[8]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s5_ddr_chip_bind_if) 
  );

`elsif CONNECT_AXI_S5_DDR_CHIP 

  svt_axi_slave_connector#(0) axi_s5_ddr_chip(
    .slave_if(coretop_axi_if_0.slave_if[8]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.axi_s5_ddr_chip_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S0_DDR_CHIP 
  bind `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(32), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s0_ddr_chip_bind_if (
    .paddr(paddr_ctl), 
    .psel(psel_ctl), 
    .penable(penable_ctl), 
    .pwrite(pwrite_ctl), 
    .prdata(prdata_ctl), 
    .pwdata(pwdata_ctl), 
    .pstrb(pstrb_ctl), 
    .pready(pready_ctl), 
    .pslverr(pslverr_ctl) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[13].pstrb = '1;
  force coretop_apb_if_0.slave_if[13].pprot = 0;
end

`ifdef REPLACE_BD_APB_S0_DDR_CHIP 

  svt_apb_slave_connector#(1) bd_apb_s0_ddr_chip(
    .slave_if(coretop_apb_if_0.slave_if[13]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.bd_apb_s0_ddr_chip_bind_if) 
  );

`elsif CONNECT_BD_APB_S0_DDR_CHIP 

  svt_apb_slave_connector#(0) bd_apb_s0_ddr_chip(
    .slave_if(coretop_apb_if_0.slave_if[13]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.bd_apb_s0_ddr_chip_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S1_DDR_CHIP 
  bind `CORETOP.u_ss_mem.u_dram_top.u_ddr_chip svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(32), 
    .PRDATA_WIDTH_PARAM(16), 
    .PWDATA_WIDTH_PARAM(16), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s1_ddr_chip_bind_if (
    .paddr(paddr_phy), 
    .psel(psel_phy), 
    .penable(penable_phy), 
    .pwrite(pwrite_phy), 
    .prdata(prdata_phy), 
    .pwdata(pwdata_phy), 
    .pstrb(pstrb_phy), 
    .pready(pready_phy), 
    .pslverr(pslverr_phy) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[14].pstrb = '1; 
  force coretop_apb_if_0.slave_if[14].pprot = 0;  
end

`ifdef REPLACE_BD_APB_S1_DDR_CHIP 

  svt_apb_slave_connector#(1) bd_apb_s1_ddr_chip(
    .slave_if(coretop_apb_if_0.slave_if[14]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.bd_apb_s1_ddr_chip_bind_if) 
  );

`elsif CONNECT_BD_APB_S1_DDR_CHIP 

  svt_apb_slave_connector#(0) bd_apb_s1_ddr_chip(
    .slave_if(coretop_apb_if_0.slave_if[14]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_dram_top.u_ddr_chip.bd_apb_s1_ddr_chip_bind_if) 
  );

`endif

`ifdef BIND_AXI_S_SRAM_SLAVE_GROUP 
  bind `CORETOP.u_ss_mem.u_sram_slave_group svt_axi_slave_bind_if #(
    .AWID_WIDTH_PARAM(16), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .WDATA_WIDTH_PARAM(512), 
    .WSTRB_WIDTH_PARAM(64), 
    .BID_WIDTH_PARAM(16), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(16), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .RID_WIDTH_PARAM(16), 
    .RDATA_WIDTH_PARAM(512), 
    .RRESP_WIDTH_PARAM(2) 
  ) axi_s_sram_slave_group_bind_if (
    .awid(awid_sram), 
    .awaddr(awaddr_sram), 
    .awlen(awlen_sram), 
    .awsize(awsize_sram), 
    .awburst(awburst_sram), 
    .awlock(awlock_sram), 
    .awcache(awcache_sram), 
    .awprot(awprot_sram), 
    .awvalid(awvalid_sram), 
    .awready(awready_sram), 
    .wdata(wdata_sram), 
    .wstrb(wstrb_sram), 
    .wlast(wlast_sram), 
    .wvalid(wvalid_sram), 
    .wready(wready_sram), 
    .bid(bid_sram), 
    .bresp(bresp_sram), 
    .bvalid(bvalid_sram), 
    .bready(bready_sram), 
    .arid(arid_sram), 
    .araddr(araddr_sram), 
    .arlen(arlen_sram), 
    .arsize(arsize_sram), 
    .arburst(arburst_sram), 
    .arlock(arlock_sram), 
    .arcache(arcache_sram), 
    .arprot(arprot_sram), 
    .arvalid(arvalid_sram), 
    .arready(arready_sram), 
    .rid(rid_sram), 
    .rdata(rdata_sram), 
    .rresp(rresp_sram), 
    .rlast(rlast_sram), 
    .rvalid(rvalid_sram), 
    .rready(rready_sram) 
  );
`endif

`ifdef REPLACE_AXI_S_SRAM_SLAVE_GROUP 

  svt_axi_slave_connector#(1) axi_s_sram_slave_group(
    .slave_if(coretop_axi_if_0.slave_if[9]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_sram_slave_group.axi_s_sram_slave_group_bind_if) 
  );

`elsif CONNECT_AXI_S_SRAM_SLAVE_GROUP 

  svt_axi_slave_connector#(0) axi_s_sram_slave_group(
    .slave_if(coretop_axi_if_0.slave_if[9]), 
    .slave_bind_if(`CORETOP.u_ss_mem.u_sram_slave_group.axi_s_sram_slave_group_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_M_SS_SF 
  bind `CORETOP.u_ss_sf svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(8), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(128), 
    .WSTRB_WIDTH_PARAM(16), 
    .BID_WIDTH_PARAM(8), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(8), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(8), 
    .RDATA_WIDTH_PARAM(128), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m_ss_sf_bind_if (
    .awid(awid_m_ss_sf), 
    .awaddr(awaddr_m_ss_sf), 
    .awlen(awlen_m_ss_sf), 
    .awsize(awsize_m_ss_sf), 
    .awburst(awburst_m_ss_sf), 
    .awlock(awlock_m_ss_sf), 
    .awcache(awcache_m_ss_sf), 
    .awprot(awprot_m_ss_sf), 
    .awqos(awqos_m_ss_sf), 
    .awvalid(awvalid_m_ss_sf), 
    .awready(awready_m_ss_sf), 
    .wdata(wdata_m_ss_sf), 
    .wstrb(wstrb_m_ss_sf), 
    .wlast(wlast_m_ss_sf), 
    .wvalid(wvalid_m_ss_sf), 
    .wready(wready_m_ss_sf), 
    .bid(bid_m_ss_sf), 
    .bresp(bresp_m_ss_sf), 
    .bvalid(bvalid_m_ss_sf), 
    .bready(bready_m_ss_sf), 
    .arid(arid_m_ss_sf), 
    .araddr(araddr_m_ss_sf), 
    .arlen(arlen_m_ss_sf), 
    .arsize(arsize_m_ss_sf), 
    .arburst(arburst_m_ss_sf), 
    .arlock(arlock_m_ss_sf), 
    .arcache(arcache_m_ss_sf), 
    .arprot(arprot_m_ss_sf), 
    .arqos(arqos_m_ss_sf), 
    .arvalid(arvalid_m_ss_sf), 
    .arready(arready_m_ss_sf), 
    .rid(rid_m_ss_sf), 
    .rdata(rdata_m_ss_sf), 
    .rresp(rresp_m_ss_sf), 
    .rlast(rlast_m_ss_sf), 
    .rvalid(rvalid_m_ss_sf), 
    .rready(rready_m_ss_sf) 
  );
`endif

`ifdef REPLACE_BD_AXI_M_SS_SF 

  svt_axi_master_connector#(1) bd_axi_m_ss_sf(
    .master_if(coretop_axi_if_0.master_if[15]), 
    .master_bind_if(`CORETOP.u_ss_sf.bd_axi_m_ss_sf_bind_if) 
  );

`elsif CONNECT_BD_AXI_M_SS_SF 

  svt_axi_master_connector#(0) bd_axi_m_ss_sf(
    .master_if(coretop_axi_if_0.master_if[15]), 
    .master_bind_if(`CORETOP.u_ss_sf.bd_axi_m_ss_sf_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_S_SS_SF 
  bind `CORETOP.u_ss_sf svt_axi_slave_bind_if #(
    .AWID_WIDTH_PARAM(16), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(128), 
    .WSTRB_WIDTH_PARAM(16), 
    .BID_WIDTH_PARAM(16), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(16), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(16), 
    .RDATA_WIDTH_PARAM(128), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_s_ss_sf_bind_if (
    .awid(awid_s_ss_sf), 
    .awaddr(awaddr_s_ss_sf), 
    .awlen(awlen_s_ss_sf), 
    .awsize(awsize_s_ss_sf), 
    .awburst(awburst_s_ss_sf), 
    .awlock(awlock_s_ss_sf), 
    .awcache(awcache_s_ss_sf), 
    .awprot(awprot_s_ss_sf), 
    .awqos(awqos_s_ss_sf), 
    .awvalid(awvalid_s_ss_sf), 
    .awready(awready_s_ss_sf), 
    .wdata(wdata_s_ss_sf), 
    .wstrb(wstrb_s_ss_sf), 
    .wlast(wlast_s_ss_sf), 
    .wvalid(wvalid_s_ss_sf), 
    .wready(wready_s_ss_sf), 
    .bid(bid_s_ss_sf), 
    .bresp(bresp_s_ss_sf), 
    .bvalid(bvalid_s_ss_sf), 
    .bready(bready_s_ss_sf), 
    .arid(arid_s_ss_sf), 
    .araddr(araddr_s_ss_sf), 
    .arlen(arlen_s_ss_sf), 
    .arsize(arsize_s_ss_sf), 
    .arburst(arburst_s_ss_sf), 
    .arlock(arlock_s_ss_sf), 
    .arcache(arcache_s_ss_sf), 
    .arprot(arprot_s_ss_sf), 
    .arqos(arqos_s_ss_sf), 
    .arvalid(arvalid_s_ss_sf), 
    .arready(arready_s_ss_sf), 
    .rid(rid_s_ss_sf), 
    .rdata(rdata_s_ss_sf), 
    .rresp(rresp_s_ss_sf), 
    .rlast(rlast_s_ss_sf), 
    .rvalid(rvalid_s_ss_sf), 
    .rready(rready_s_ss_sf) 
  );
`endif

`ifdef REPLACE_BD_AXI_S_SS_SF 

  svt_axi_slave_connector#(1) bd_axi_s_ss_sf(
    .slave_if(coretop_axi_if_0.slave_if[10]), 
    .slave_bind_if(`CORETOP.u_ss_sf.bd_axi_s_ss_sf_bind_if) 
  );

`elsif CONNECT_BD_AXI_S_SS_SF 

  svt_axi_slave_connector#(0) bd_axi_s_ss_sf(
    .slave_if(coretop_axi_if_0.slave_if[10]), 
    .slave_bind_if(`CORETOP.u_ss_sf.bd_axi_s_ss_sf_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_M_SS_SF 
  bind `CORETOP.u_ss_sf svt_apb_master_bind_if #(
    .PADDR_WIDTH_PARAM(40), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_m_ss_sf_bind_if (
    .paddr(paddr_m_ss_sf), 
    .psel(psel_m_ss_sf), 
    .penable(penable_m_ss_sf), 
    .pwrite(pwrite_m_ss_sf), 
    .prdata(prdata_m_ss_sf), 
    .pwdata(pwdata_m_ss_sf), 
    .pprot(pprot_m_ss_sf), 
    .pstrb(pstrb_m_ss_sf), 
    .pready(pready_m_ss_sf), 
    .pslverr(pslverr_m_ss_sf) 
  );
`endif

`ifdef REPLACE_BD_APB_M_SS_SF 

  svt_apb_master_connector#(1) bd_apb_m_ss_sf(
    .master_if(coretop_apb_if_4), 
    .master_bind_if(`CORETOP.u_ss_sf.bd_apb_m_ss_sf_bind_if) 
  );

`elsif CONNECT_BD_APB_M_SS_SF 

  svt_apb_master_connector#(0) bd_apb_m_ss_sf(
    .master_if(coretop_apb_if_4), 
    .master_bind_if(`CORETOP.u_ss_sf.bd_apb_m_ss_sf_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_SS_SF 
  bind `CORETOP.u_ss_sf svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(24), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_ss_sf_bind_if (
    .paddr(paddr_s_ss_sf), 
    .psel(psel_s_ss_sf), 
    .penable(penable_s_ss_sf), 
    .pwrite(pwrite_s_ss_sf), 
    .prdata(prdata_s_ss_sf), 
    .pwdata(pwdata_s_ss_sf), 
    .pprot(pprot_s_ss_sf), 
    .pstrb(pstrb_s_ss_sf), 
    .pready(pready_s_ss_sf) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[15].pslverr = 0;  
end

`ifdef REPLACE_BD_APB_S_SS_SF 

  svt_apb_slave_connector#(1) bd_apb_s_ss_sf(
    .slave_if(coretop_apb_if_0.slave_if[15]), 
    .slave_bind_if(`CORETOP.u_ss_sf.bd_apb_s_ss_sf_bind_if) 
  );

`elsif CONNECT_BD_APB_S_SS_SF 

  svt_apb_slave_connector#(0) bd_apb_s_ss_sf(
    .slave_if(coretop_apb_if_0.slave_if[15]), 
    .slave_bind_if(`CORETOP.u_ss_sf.bd_apb_s_ss_sf_bind_if) 
  );

`endif

`ifdef BIND_BD_AXI_M_SS_VOUT 
  bind `CORETOP.u_ss_vout svt_axi_master_bind_if #(
    .AWID_WIDTH_PARAM(3), 
    .AWADDR_WIDTH_PARAM(40), 
    .AWLEN_WIDTH_PARAM(8), 
    .AWSIZE_WIDTH_PARAM(3), 
    .AWBURST_WIDTH_PARAM(2), 
    .AWCACHE_WIDTH_PARAM(4), 
    .AWPROT_WIDTH_PARAM(3), 
    .AWQOS_WIDTH_PARAM(4), 
    .WDATA_WIDTH_PARAM(256), 
    .WSTRB_WIDTH_PARAM(32), 
    .BID_WIDTH_PARAM(3), 
    .BRESP_WIDTH_PARAM(2), 
    .ARID_WIDTH_PARAM(3), 
    .ARADDR_WIDTH_PARAM(40), 
    .ARLEN_WIDTH_PARAM(8), 
    .ARSIZE_WIDTH_PARAM(3), 
    .ARBURST_WIDTH_PARAM(2), 
    .ARCACHE_WIDTH_PARAM(4), 
    .ARPROT_WIDTH_PARAM(3), 
    .ARQOS_WIDTH_PARAM(4), 
    .RID_WIDTH_PARAM(3), 
    .RDATA_WIDTH_PARAM(256), 
    .RRESP_WIDTH_PARAM(2) 
  ) bd_axi_m_ss_vout_bind_if (
    .awid(awid_m_ss_vout), 
    .awaddr(awaddr_m_ss_vout), 
    .awlen(awlen_m_ss_vout), 
    .awsize(awsize_m_ss_vout), 
    .awburst(awburst_m_ss_vout), 
    .awlock(awlock_m_ss_vout), 
    .awcache(awcache_m_ss_vout), 
    .awprot(awprot_m_ss_vout), 
    .awqos(awqos_m_ss_vout), 
    .awvalid(awvalid_m_ss_vout), 
    .awready(awready_m_ss_vout), 
    .wdata(wdata_m_ss_vout), 
    .wstrb(wstrb_m_ss_vout), 
    .wlast(wlast_m_ss_vout), 
    .wvalid(wvalid_m_ss_vout), 
    .wready(wready_m_ss_vout), 
    .bid(bid_m_ss_vout), 
    .bresp(bresp_m_ss_vout), 
    .bvalid(bvalid_m_ss_vout), 
    .bready(bready_m_ss_vout), 
    .arid(arid_m_ss_vout), 
    .araddr(araddr_m_ss_vout), 
    .arlen(arlen_m_ss_vout), 
    .arsize(arsize_m_ss_vout), 
    .arburst(arburst_m_ss_vout), 
    .arlock(arlock_m_ss_vout), 
    .arcache(arcache_m_ss_vout), 
    .arprot(arprot_m_ss_vout), 
    .arqos(arqos_m_ss_vout), 
    .arvalid(arvalid_m_ss_vout), 
    .arready(arready_m_ss_vout), 
    .rid(rid_m_ss_vout), 
    .rdata(rdata_m_ss_vout), 
    .rresp(rresp_m_ss_vout), 
    .rlast(rlast_m_ss_vout), 
    .rvalid(rvalid_m_ss_vout), 
    .rready(rready_m_ss_vout) 
  );
`endif

`ifdef REPLACE_BD_AXI_M_SS_VOUT 

  svt_axi_master_connector#(1) bd_axi_m_ss_vout(
    .master_if(coretop_axi_if_0.master_if[16]), 
    .master_bind_if(`CORETOP.u_ss_vout.bd_axi_m_ss_vout_bind_if) 
  );

`elsif CONNECT_BD_AXI_M_SS_VOUT 

  svt_axi_master_connector#(0) bd_axi_m_ss_vout(
    .master_if(coretop_axi_if_0.master_if[16]), 
    .master_bind_if(`CORETOP.u_ss_vout.bd_axi_m_ss_vout_bind_if) 
  );

`endif

`ifdef BIND_BD_APB_S_SS_VOUT 
  bind `CORETOP.u_ss_vout svt_apb_slave_bind_if #(
    .PADDR_WIDTH_PARAM(24), 
    .PRDATA_WIDTH_PARAM(32), 
    .PWDATA_WIDTH_PARAM(32), 
    .PPROT_WIDTH_PARAM(3), 
    .PSTRB_WIDTH_PARAM(4) 
  ) bd_apb_s_ss_vout_bind_if (
    .paddr(paddr_s_ss_vout), 
    .psel(psel_s_ss_vout), 
    .penable(penable_s_ss_vout), 
    .pwrite(pwrite_s_ss_vout), 
    .prdata(prdata_s_ss_vout), 
    .pwdata(pwdata_s_ss_vout), 
    .pprot(pprot_s_ss_vout), 
    .pstrb(pstrb_s_ss_vout), 
    .pready(pready_s_ss_vout) 
  );
`endif

initial begin
  force coretop_apb_if_0.slave_if[16].pslverr = 0;  
end

`ifdef REPLACE_BD_APB_S_SS_VOUT 

  svt_apb_slave_connector#(1) bd_apb_s_ss_vout(
    .slave_if(coretop_apb_if_0.slave_if[16]), 
    .slave_bind_if(`CORETOP.u_ss_vout.bd_apb_s_ss_vout_bind_if) 
  );

`elsif CONNECT_BD_APB_S_SS_VOUT 

  svt_apb_slave_connector#(0) bd_apb_s_ss_vout(
    .slave_if(coretop_apb_if_0.slave_if[16]), 
    .slave_bind_if(`CORETOP.u_ss_vout.bd_apb_s_ss_vout_bind_if) 
  );

`endif

// Check that replace/connect macros are used correctly
initial begin
 
`ifdef REPLACE_BD_AXI_M_AUDTOP 
`ifdef CONNECT_BD_AXI_M_AUDTOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M_AUDTOP / CONNECT_BD_AXI_M_AUDTOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_AUDTOP 
`ifdef CONNECT_BD_APB_S_AUDTOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_AUDTOP / CONNECT_BD_APB_S_AUDTOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_M_CQTOP 
`ifdef CONNECT_BD_AXI_M_CQTOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M_CQTOP / CONNECT_BD_AXI_M_CQTOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_M_DMATOP 
`ifdef CONNECT_BD_AXI_M_DMATOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M_DMATOP / CONNECT_BD_AXI_M_DMATOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_DMATOP 
`ifdef CONNECT_BD_APB_S_DMATOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_DMATOP / CONNECT_BD_APB_S_DMATOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AHB_S_FMTOP 
`ifdef CONNECT_BD_AHB_S_FMTOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AHB_S_FMTOP / CONNECT_BD_AHB_S_FMTOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_M_FMTOP 
`ifdef CONNECT_BD_AXI_M_FMTOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M_FMTOP / CONNECT_BD_AXI_M_FMTOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_FMTOP 
`ifdef CONNECT_BD_APB_S_FMTOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_FMTOP / CONNECT_BD_APB_S_FMTOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_GTOP 
`ifdef CONNECT_BD_APB_S_GTOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_GTOP / CONNECT_BD_APB_S_GTOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_M_PERITOP 
`ifdef CONNECT_BD_AXI_M_PERITOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M_PERITOP / CONNECT_BD_AXI_M_PERITOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_M_PERITOP 
`ifdef CONNECT_BD_APB_M_PERITOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_M_PERITOP / CONNECT_BD_APB_M_PERITOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S0_PERITOP 
`ifdef CONNECT_BD_APB_S0_PERITOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S0_PERITOP / CONNECT_BD_APB_S0_PERITOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S1_PERITOP 
`ifdef CONNECT_BD_APB_S1_PERITOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S1_PERITOP / CONNECT_BD_APB_S1_PERITOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_M_HSMTOP 
`ifdef CONNECT_BD_AXI_M_HSMTOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M_HSMTOP / CONNECT_BD_AXI_M_HSMTOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AHB_M_HSMTOP 
`ifdef CONNECT_BD_AHB_M_HSMTOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AHB_M_HSMTOP / CONNECT_BD_AHB_M_HSMTOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_M_HSMTOP 
`ifdef CONNECT_BD_APB_M_HSMTOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_M_HSMTOP / CONNECT_BD_APB_M_HSMTOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_HSMTOP 
`ifdef CONNECT_BD_APB_S_HSMTOP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_HSMTOP / CONNECT_BD_APB_S_HSMTOP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_S_UCIE 
`ifdef CONNECT_BD_AXI_S_UCIE 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_S_UCIE / CONNECT_BD_AXI_S_UCIE");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_M_UCIE 
`ifdef CONNECT_BD_AXI_M_UCIE 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M_UCIE / CONNECT_BD_AXI_M_UCIE");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_UCIE 
`ifdef CONNECT_BD_APB_S_UCIE 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_UCIE / CONNECT_BD_APB_S_UCIE");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACEC_BD_AXI_M_SS_CDEC 
`ifdef CONNECT_BD_AXI_M_SS_CDEC 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACEC_BD_AXI_M_SS_CDEC / CONNECT_BD_AXI_M_SS_CDEC");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACEC_BD_APB_S_SS_CDEC 
`ifdef CONNECT_BD_APB_S_SS_CDEC 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACEC_BD_APB_S_SS_CDEC / CONNECT_BD_APB_S_SS_CDEC");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_ACE_M0_SS_CMP 
`ifdef CONNECT_BD_ACE_M0_SS_CMP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_ACE_M0_SS_CMP / CONNECT_BD_ACE_M0_SS_CMP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_ACE_M1_SS_CMP 
`ifdef CONNECT_BD_ACE_M1_SS_CMP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_ACE_M1_SS_CMP / CONNECT_BD_ACE_M1_SS_CMP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_ACE_M2_SS_CMP 
`ifdef CONNECT_BD_ACE_M2_SS_CMP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_ACE_M2_SS_CMP / CONNECT_BD_ACE_M2_SS_CMP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_SS_CMP 
`ifdef CONNECT_BD_APB_S_SS_CMP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_SS_CMP / CONNECT_BD_APB_S_SS_CMP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_M_SS_CON 
`ifdef CONNECT_BD_AXI_M_SS_CON 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M_SS_CON / CONNECT_BD_AXI_M_SS_CON");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_S_SS_CON 
`ifdef CONNECT_BD_AXI_S_SS_CON 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_S_SS_CON / CONNECT_BD_AXI_S_SS_CON");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_SS_CON 
`ifdef CONNECT_BD_APB_S_SS_CON 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_SS_CON / CONNECT_BD_APB_S_SS_CON");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_ACE_M_SS_CPU 
`ifdef CONNECT_BD_ACE_M_SS_CPU 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_ACE_M_SS_CPU / CONNECT_BD_ACE_M_SS_CPU");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_S_SS_CPU 
`ifdef CONNECT_BD_AXI_S_SS_CPU 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_S_SS_CPU / CONNECT_BD_AXI_S_SS_CPU");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_M_SS_CPU 
`ifdef CONNECT_BD_APB_M_SS_CPU 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_M_SS_CPU / CONNECT_BD_APB_M_SS_CPU");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_SS_CPU 
`ifdef CONNECT_BD_APB_S_SS_CPU 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_SS_CPU / CONNECT_BD_APB_S_SS_CPU");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_M0_SS_VIS 
`ifdef CONNECT_BD_AXI_M0_SS_VIS 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M0_SS_VIS / CONNECT_BD_AXI_M0_SS_VIS");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_M1_SS_VIS 
`ifdef CONNECT_BD_AXI_M1_SS_VIS 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M1_SS_VIS / CONNECT_BD_AXI_M1_SS_VIS");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_SS_VIS 
`ifdef CONNECT_BD_APB_S_SS_VIS 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_SS_VIS / CONNECT_BD_APB_S_SS_VIS");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_AXI_S0_DDR_CHIP 
`ifdef CONNECT_AXI_S0_DDR_CHIP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_AXI_S0_DDR_CHIP / CONNECT_AXI_S0_DDR_CHIP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_AXI_S1_DDR_CHIP 
`ifdef CONNECT_AXI_S1_DDR_CHIP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_AXI_S1_DDR_CHIP / CONNECT_AXI_S1_DDR_CHIP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_AXI_S2_DDR_CHIP 
`ifdef CONNECT_AXI_S2_DDR_CHIP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_AXI_S2_DDR_CHIP / CONNECT_AXI_S2_DDR_CHIP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_AXI_S3_DDR_CHIP 
`ifdef CONNECT_AXI_S3_DDR_CHIP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_AXI_S3_DDR_CHIP / CONNECT_AXI_S3_DDR_CHIP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_AXI_S4_DDR_CHIP 
`ifdef CONNECT_AXI_S4_DDR_CHIP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_AXI_S4_DDR_CHIP / CONNECT_AXI_S4_DDR_CHIP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_AXI_S5_DDR_CHIP 
`ifdef CONNECT_AXI_S5_DDR_CHIP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_AXI_S5_DDR_CHIP / CONNECT_AXI_S5_DDR_CHIP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S0_DDR_CHIP 
`ifdef CONNECT_BD_APB_S0_DDR_CHIP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S0_DDR_CHIP / CONNECT_BD_APB_S0_DDR_CHIP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S1_DDR_CHIP 
`ifdef CONNECT_BD_APB_S1_DDR_CHIP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S1_DDR_CHIP / CONNECT_BD_APB_S1_DDR_CHIP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_AXI_S_SRAM_SLAVE_GROUP 
`ifdef CONNECT_AXI_S_SRAM_SLAVE_GROUP 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_AXI_S_SRAM_SLAVE_GROUP / CONNECT_AXI_S_SRAM_SLAVE_GROUP");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_M_SS_SF 
`ifdef CONNECT_BD_AXI_M_SS_SF 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M_SS_SF / CONNECT_BD_AXI_M_SS_SF");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_S_SS_SF 
`ifdef CONNECT_BD_AXI_S_SS_SF 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_S_SS_SF / CONNECT_BD_AXI_S_SS_SF");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_M_SS_SF 
`ifdef CONNECT_BD_APB_M_SS_SF 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_M_SS_SF / CONNECT_BD_APB_M_SS_SF");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_SS_SF 
`ifdef CONNECT_BD_APB_S_SS_SF 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_SS_SF / CONNECT_BD_APB_S_SS_SF");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_AXI_M_SS_VOUT 
`ifdef CONNECT_BD_AXI_M_SS_VOUT 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_AXI_M_SS_VOUT / CONNECT_BD_AXI_M_SS_VOUT");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

 
`ifdef REPLACE_BD_APB_S_SS_VOUT 
`ifdef CONNECT_BD_APB_S_SS_VOUT 
  $display("ATB replace/connect macros are mutually exclusive.  Please ensure that only one of the following are set: REPLACE_BD_APB_S_SS_VOUT / CONNECT_BD_APB_S_SS_VOUT");
`ifndef CONNECT_CONFLICT
`define CONNECT_CONFLICT
`endif
`endif
`endif

`ifdef CONNECT_CONFLICT
  $finish;
`endif

end

// -----------------------------------------------------------------------------
// Use uvm_config_db to pass interfaces into the testbench
// -----------------------------------------------------------------------------
initial begin
    uvm_config_db#(virtual svt_axi_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.axi_system_env_0", "vif", coretop_axi_if_0);
    uvm_config_db#(virtual svt_apb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.apb_system_env_0", "vif", coretop_apb_if_0);
    uvm_config_db#(virtual svt_ahb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.ahb_system_env_0", "vif", coretop_ahb_if_0);
    uvm_config_db#(virtual svt_apb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.apb_system_env_1", "vif", coretop_apb_if_1);
    uvm_config_db#(virtual svt_apb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.apb_system_env_2", "vif", coretop_apb_if_2);
    uvm_config_db#(virtual svt_apb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.apb_system_env_3", "vif", coretop_apb_if_3);
    uvm_config_db#(virtual svt_apb_if)::set(uvm_root::get(), "uvm_test_top.uvm_coretop_env.apb_system_env_4", "vif", coretop_apb_if_4);
end

endmodule

