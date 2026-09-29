import sys
sys.path.insert(0, r"D:\DV\Task\DV_Agent_Harness_L5\v50")
from pathlib import Path
from dv_harness.memory_router import route_and_store

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")
PROV = "intake-extraction-usb workflow, 2026-09-03"

records = []

# 1. SoC address-map formula + USB port-1 base dispute + core-register gap
records.append({
    "kind": "project_fact",
    "verified": True,
    "scope": "project",
    "title": "PAISB SoC address-map formula + USB port-1 base and GCTL/DCTL core-register gap",
    "summary": (
        "Triangulated across 4 independent docs: system_address = 0x1000_0000 | local28, where "
        "local28 is the 28-bit 'Address[27:0]' nibble map given at the top of "
        "SS_QDMA\\PAISB_CQ_Reg_260810.docx (bits[27:24] select a subsystem directly except when "
        "0, in which case bits[23:20] sub-select Global/CQ/CPU-SS/QDMA-SS/SE). Verified: "
        "PAISB_Global_Reg_260731.doc states its own base is 0x1000_0000 (local 0x0000000, bucket "
        "'Global'). SS_QDMA\\PAISB_SS_QDMA_Reg_260605.docx states 'CQ at 0x1010_0000' and 'SS_QDMA "
        "at 0x1030_0000, DMA at 0x1031_0000' -- exact matches to local 0x0100000/0x0300000/0x0310000 "
        "(bucket 'CQ'=0x01XXXXX, 'QDMA SS'=0x03XXXXX). register__ssvout_0806.xlsx states its own "
        "base is 0x1200_0000, matching local 0x2000000 = top-level bucket 'Video Out subsystem' "
        "(0x2XXXXXX) from the CQ doc's map. USB_Reg_260727.docx's usbtop[0] register blocks "
        "(0x1270_0000-0x1273_FFFF) fall inside that 16MB Video-Out-SS window, confirming the USB "
        "controller instances are a sub-region of what PAISB_Global_Reg_260731.doc calls the "
        "'VideoOut Sub-system' (swrst_ss_vout / clken_ss_vout, which explicitly lists usbrefclk and "
        "usblclk as member clocks) and what register__ssvout_0806.xlsx's cqint0Nen bit-map and "
        "mswrst/usbN_clken registers call 'usb0'/'usb1'. "
        "CRITICAL GAP #1 (DUT-007, disputed port-1 base): USB_Reg_260727.docx's table for "
        "usbtop[1] (lines 34-51) is byte-for-byte IDENTICAL to usbtop[0]'s (lines 16-32) -- same "
        "0x1270_0000-0x1273_FFFF repeated verbatim, no distinct address given for instance 1. This is "
        "either a template/copy-paste artifact or a genuine documentation gap; the 16MB SS_VOUT "
        "window has ample unused space (usbtop[0] only occupies 16KB of it) so a second base is "
        "architecturally plausible but NOT SOURCED anywhere in the provided doc/excel material. "
        "Do not assume port-1's base equals port-0's in the live system, and do not assume any "
        "specific alternate offset without an RTL/address-map citation. "
        "CRITICAL GAP #2: the 'DWC_usb31 controller register' block (0x1271_0000-0x1271_FFFF) in "
        "USB_Reg_260727.docx is documented ONLY as a pointer: 'IP Control register (reference to "
        "...DWC_usb31_programming.pdf CH1)'. That programming-guide PDF is ABSENT from "
        "D:\\DV\\Task\\USB\\DOC\\ entirely. The only other candidate PDF present, "
        "DWC_usb31_databook_WM-25380.pdf, is a DIFFERENT document and is password-protected against "
        "text extraction (pdftotext returns 'Incorrect password'). CONSEQUENCE: none of "
        "GCTL/DALEPENA/DCTL/DCFG/DSTS/GEVNTCOUNT/GSTS's addresses, bit-ranges, reset values, or "
        "access types can be sourced from this document set. The only two functional cross-references "
        "found anywhere: USB_Reg_260727.docx line 352 names 'DCFG.DEVSPD' (as the field its "
        "devspd_ovrd wrapper-register at 0x1270_022A can override) without giving DCFG's address; "
        "rtl_vip_scaledown_mapping.xls names 'GUCTL.DS_RXDET_MAX_TOUT_CTRL' (USB3.0 ECN20 downstream-"
        "port timeout enable) and 'GUSB2PHYCFG.XCVRDLY' (chirp-duration-reduction enable) similarly "
        "without addresses. Any register-level claim about GCTL/DCTL/DCFG/DSTS/GEVNTCOUNT/GSTS/DALEPENA "
        "must be flagged as unsourced from this doc set and cited from the (currently inaccessible) "
        "programming guide instead. "
        "usbswrst (DUT-003, now-resolved) IS fully documented: USB_Reg_260727.docx line 168, address "
        "0x1270_0034~0035, bit[15:0], attr RW, reset 16'h0, 'USB top software reset. Write 1 to "
        "activate reset. Write 0 to deactivate.' with 10 named per-clock-domain sub-bits: [0]cr_para_clk "
        "[1]pclk [2]aclk [3]rupz [4]wupz [5]ram0clk [6]ram1clk [7]ram2clk [8]phyramclk [9]ctrl -- it is "
        "a multi-bit per-domain reset register, not a single monolithic reset bit."
    ),
    "source_paths": [
        r"D:\DV\Task\USB\DOC\PAISB_Global_Reg_260731.doc",
        r"D:\DV\Task\USB\DOC\USB_Reg_260727.docx",
        r"D:\DV\Task\USB\DOC\register__ssvout_0806.xlsx",
        r"D:\DV\Task\USB\DOC\SS_QDMA\PAISB_CQ_Reg_260810.docx",
        r"D:\DV\Task\USB\DOC\SS_QDMA\PAISB_SS_QDMA_Reg_260605.docx",
        r"D:\DV\Task\USB\DOC\rtl_vip_scaledown_mapping.xls",
    ],
    "category": "dut_registers",
    "provenance": PROV,
})

# 2. USB_Reg_260727.docx wrapper register content + PAISB_Global_Reg clock/reset for VideoOut/USB
records.append({
    "kind": "project_fact",
    "verified": True,
    "scope": "project",
    "title": "USB_Reg_260727.docx usbtop wrapper register map (regclk/axiclk/controller/sram/usb3phy/usb2phy)",
    "summary": (
        "USB_Reg_260727.docx (D:\\DV\\Task\\USB\\DOC\\USB_Reg_260727.docx; cover printed 'JUN. 08, "
        "2026' Version 0.0 despite filename date 260727=Jul27 -- stale cover date) documents the SoC "
        "integration ('usbtop') wrapper registers around the licensed DWC_usb31 controller + its PHYs, "
        "for TWO instances usbtop[0]/usbtop[1] (see the separate address-map-formula memory record for "
        "the port-1 base ambiguity). Six register pages, all base 0x1270_0000 + page offset: "
        "regclk page (0x1270_0000-00FF): usbintsts/usbinten (24-bit, [19:0]=DWC_usb31 core int, "
        "[20]=pslverr_usb31, [21]=reg-guard, [22]=tca_int, [23]=apb_s_pty_err), 16x cqNintsel (5-bit "
        "CQ event-select, default 5'h1F), pipeclken/utmiclken/phyclksel/ramclksel at 0x0030, "
        "pipeclk_phase/utmiclk_phase at 0x0031/0x0032, paraclkdiv at 0x0033, usbswrst at 0x0034 (see "
        "other memory record), probe/debug regs, date-code at 0x00FC-FF. "
        "axiclk page (0x1270_0100-01FF): usb_m_aruser/awuser (9-bit, TZC400 ID + 16-ring-buffer-select "
        "+ bypass/ring-buffer-mode bit), QoS (arqos_s_ups/awqos_s_ups), low-power handshake "
        "(csysack_s/m, cactive_s/m), AXI up-sizer block (rupsen/wupsen family, all default 1). "
        "controller page (0x1270_0200-0231): logic-analyzer trace, pme_en, star_fix_disable_ctl_inp "
        "(32-bit Synopsys STAR-fix disable), bus_filter_bypass (default 4'h3), fladj_30mhz_reg "
        "(default 6'h20), devspd_ovrd at 0x1270_022A (4-bit, overrides DCFG.DEVSPD externally -- only "
        "place any document names a DWC_usb31 core register field), startrxdetu3rxdet, "
        "ltssm_clk_state, pme_generation, pipe_phy_mode/compliance/txmargin/txswing, pipe4_pclk_rate/"
        "rxstandby(status). "
        "sram ctrl page (0x1270_0300-0367): sramsd/sramds/sramslp (6-bit shutdown/deep-sleep/"
        "light-sleep, one bit per macro: DESC/TXFIFO/RXFIFO/UPHY/WUPZ/RUPZ RAM), SRAM BIST "
        "(bistmode/bistfinish/bistfail/errmap), gated-clock disables (disreggatedclk/disgatedsmcken "
        "both default 1), per-bank column-repair fields. "
        "usb3phy page (0x1270_0400+, largest, ~230 fields): u3phyrst (default 1'h1, active by default), "
        "full MPLLA/MPLLB control set (force-enable, SSC-enable, div/multiplier/bandwidth/fracn-ctrl/"
        "ssc-freq-cnt-init+peak/clk-sel/range/tx-clk-div), reference-clock divider/range select "
        "(phy_ext_ref_range 3-bit code table 19.2MHz-200MHz), power-gating handshake, RX adaptation/"
        "DFE enables, resistor-tune handshake, boundary-scan controls -- matches DWC USB3.1 SS PHY "
        "raw-PCS signal names 1:1 (this is the PHY-side CSR wrapper, not the controller). "
        "usb2phy page (0x1270_0500+): standard UTMI+-level femtoPHY surface -- u2phyrst, atereset, "
        "fsel (ref-clock-freq select, default 3'h1=20MHz), refclksel, commononn, vregbypass (default 1), "
        "dppulldown/dmpulldown, txbitstuffen(h), hostdisconnect (RO), vbusvalid0 (RO), FS/LS "
        "transceiver bits, siddq, testburnin, PLL tune fields (pllitune/pllbtune/pllptune default "
        "4'hC=4x), compdistune (disconnect-threshold, default 3'h3=0%). "
        "apb parity check page (0x1270_0600-060F): AXI-master fault-injection register set "
        "(usb_m_*_inj, all RW) paired with matching W1C interrupt-status shadow registers -- a "
        "design-for-test block for error-injection DV. "
        "Cross-reference: PAISB_Global_Reg_260731.doc (D:\\DV\\Task\\USB\\DOC\\PAISB_Global_Reg_260731.doc, "
        "base 0x1000_0000, chip-wide) implements a TWO-TIER clock/reset architecture over this same "
        "USB block: chip-level swrst_set/clr_ss_vout (0x00_0250/58) and clken_set/clr_ss_vout "
        "(0x00_0350~1/58~9, bitmap [00]pcierefclk [01]usbrefclk(PHY) [02]mtxrefclk [03]macptpclk "
        "[04]macclk0 [05]macclk1 [06]macaclk [08]pciefwclk [10]usblclk [12]mtxscclk [13]mtxdispclk "
        "[14]mtxdsiclk) gate the WHOLE VideoOut/USB/PCIe/MAC/MIPI subsystem, with usbrefclksrc "
        "(0x00_0483, 3-bit source select) and usbrefclkdiv/usblclkdiv (divider ratio registers) "
        "feeding into it; register__ssvout_0806.xlsx's usb0_clken/usb1_clken (0x0097/0x0098, 3-bit "
        "each, default 0x7) then fan the enabled clock out to the two individual instances. Also "
        "note swrst_set_ss_qdma (0x00_0270) carries an explicit erratum comment in the same doc: "
        "'Keep 3 APB clocks and auto-recover to 0 to avoid CQ APB dead-lock'."
    ),
    "source_paths": [
        r"D:\DV\Task\USB\DOC\USB_Reg_260727.docx",
        r"D:\DV\Task\USB\DOC\PAISB_Global_Reg_260731.doc",
        r"D:\DV\Task\USB\DOC\register__ssvout_0806.xlsx",
    ],
    "category": "dut_registers",
    "provenance": PROV,
})

# 3. SS_VOUT subsystem-level register set
records.append({
    "kind": "project_fact",
    "verified": True,
    "scope": "project",
    "title": "register__ssvout_0806.xlsx SS_VOUT subsystem register set (usb0/usb1 fabric-level view)",
    "summary": (
        "D:\\DV\\Task\\USB\\DOC\\register__ssvout_0806.xlsx documents the SS_VOUT ('VideoOut') "
        "subsystem's own control-plane registers (interrupt aggregation, ring-buffer/stream-buffer "
        "management, AXI bus-matrix arbitration, per-sub-module clock+reset) -- a DIFFERENT register "
        "domain from USB_Reg_260727.docx's per-instance USB CSR pages: this doc sits 'around' "
        "usb0/usb1, USB_Reg_260727.docx documents what's 'inside' them. Do not conflate the two. "
        "6 sheets, base addresses: ss_vout_reg00=0x1200_0000 (interrupt/CQ-INT/reset/clock/probe/date, "
        "70 rows), ss_vout_reg01=0x1200_0100 (AXI arbiter + device bus-matrix, 35 rows), "
        "ss_vout_reg02=0x1200_0200 (ring-buffer level-detect, 67 rows), ss_vout_reg03=0x1200_0300 "
        "(67 rows, same family as reg02), ss_vout_reg_str (per-stream config, base 0x1200_02/4/5/600 "
        "per its 'duplicate Address' column, X=4/5/6 for stream0/1/2, 64 rows), ss_vout_reg_trb=0x1201_0000 "
        "(TRB engine incl. trb_axid_mask, 512-byte page, 58 rows). "
        "Key registers: ss_vout_intevt (0x0000~8, RWC, 73-bit) with bit layout [3:0]/[7:4]/[11:8]="
        "str0/1/2 input-stream {SOF,SOL,EOF,EOL}, [15:12]/[19:16]/[23:20]=str0/1/2 output-stream same, "
        "[39:24]=ring-buffer-0..15 read-half-level event, [55:40]=write-half-level event, [56]=top "
        "register-guard violation, [57]/[58]=AXI read/write arbiter error, [59]-[70]=various "
        "stream-buffer error/timeout classes (3 distinct timeout types: Grant-No-Valid, Backpressure, "
        "Busy), [72]=ring-oscillator done; matching ss_vout_irqen/fiqen. ss_vout_esmen (0x0030, [6:0]) "
        "drives ctl_esmerr, consumed by PAISB_Global_Reg's ssvout_esmerr/esmen at 0x02_0221x. "
        "16x cqintNNsel (0x0040-004F, [6:0], default 0x7F) select 1-of-73 events per CQ. 16x cqintNNen "
        "(0x0050~1...006E~F, [11:0], default 0x0) is the per-CQ enable mask with explicit bit "
        "assignment [0]=ss_vout-int [1]=pkt [2]=trb [4]=mac0 [5]=mac1 [8]=pcie [9]=usb0 [10]=usb1 "
        "[11]=mipitx -- this is the concrete evidence that usb0/usb1 are peer sub-modules alongside "
        "mac0/mac1(Ethernet)/pcie/mipitx inside this subsystem. mswrst (0x0080, [5:0], default 0x0): "
        "[0]mac0 [1]mac1 [2]pcie [3]usb0 [4]usb1 [5]mipitx -- per-submodule software reset. pclken/"
        "aclken (0x0090/91, [5:0], default 0x3F) same 6-bit map. usb0_clken (0x0097, [2:0], default "
        "0x7) and usb1_clken (0x0098, [2:0], default 0x7) are independent per-instance clock enables. "
        "ss_vout_reg01 (0x1200_0100) has AXI write/read arbiter reset/pause/priority/busy/error "
        "per-master (n=0..3) plus a device bus-matrix block (devbm_rst, pause_dev[4:0] for 5 devices, "
        "idle_dev/busy_dev [9:0]) and 3-stream buffer control (str_swrst[3:0] incl. a 4th "
        "stream-wrapper bit, str_rout_sel: 0=AXI-slave-in-bus-matrix / 1=AXI-stream-master-to-MIPITX)."
    ),
    "source_paths": [r"D:\DV\Task\USB\DOC\register__ssvout_0806.xlsx"],
    "category": "dut_registers",
    "provenance": PROV,
})

# 4. CQ engine register map + version diffs
records.append({
    "kind": "project_fact",
    "verified": True,
    "scope": "project",
    "title": "PAISB_CQ_Reg (SS_QDMA Command Queue) register map + v0.2-to-v0.3/0.4 version deltas",
    "summary": (
        "SS_QDMA\\PAISB_CQ_Reg_260810.docx (latest of 3 dated copies: 260603, 260625, 260810; used per "
        "task instructions) documents the 16-instance programmable Command-Queue micro-sequencer "
        "engine. Cover says Version 0.3 (Aug 8 2026) but the revision-history table inside actually "
        "lists a further 0.4 'Fixed a typo' entry (2026/08/10, p.11) -- the file content is really "
        "rev 0.4 despite a stale 0.3 cover string. Full history: 0.1 File Creation (06/03) -> 0.2 "
        "'Fixing minor issues' (06/25) -> 0.3 'Add cqprot reg' (08/03, p.19) -> 0.4 'Fixed a typo' "
        "(08/10, p.11). "
        "MEANINGFUL VERSION DELTA (260625 v0.2 -> 260810 v0.3/0.4, verified by direct diff, only 2 "
        "real content changes): (1) rdytimeoutaddr field (0x010_1094~) WIDENED from bits[18:2]/reset "
        "0x1_FFFF to bits[24:2]/reset 0x7F_FFFF; the v0.2 doc carried an explicit erratum note removed "
        "in v0.3+: 'rdytimeoutaddr[18:2] can only represent register address [18:0]. Therefore, it "
        "cannot correctly indicate Vivanate(VIP) registers which is in the range 0x8_0000~0xF_FFFF.' "
        "Any VIP/checker code written against the v0.2 18-bit field width or its stated blind-spot is "
        "now stale. (2) NEW register cqprot[2:0] added at 0x010_121C+base, RW, default 0x2: "
        "'Protection attribute carried on this CQ's APB accesses (APB PPROT[2:0]). Set per CQ before "
        "it runs.' [0]privilege(0=normal/1=privileged) [1]NS(0=secure/1=non-secure) [2]instr(0=data/"
        "1=instruction); doc states 'Under Secure lock, a CQ whose [1]=1 (non-secure) cannot access "
        "the CQ register space.' This register is ABSENT from both earlier dated copies. The "
        "260603->260625 diff is dominated by table-reflow noise (~3270 of ~2341 lines differ from a "
        "table-structure edit) and its changelog cites no page, so no register-level content delta was "
        "confirmed there. "
        "Top-level address map (source of the cross-doc address-formula finding, see separate memory "
        "record): 28-bit 'Address[27:0]' nibble table -- 0x00XXXXX=Global, 0x01XXXXX=CQ, "
        "0x02XXXXX=CPU SS, 0x03XXXXX=QDMA SS, 0x04XXXXX=SE, 0x05-0FXXXXX=Reserved, 0x1XXXXXX=Reserved, "
        "0x2XXXXXX=Video Out SS, 0x3XXXXXX=Reserved, 0x4XXXXXX=Vision SS, 0x5XXXXXX=Vision SS(FRONT), "
        "0x6XXXXXX=General Connectivity SS, 0x7XXXXXX=Reserved, 0x8XXXXXX=Memory Controller, "
        "0x9-FXXXXXX=Reserved. CQ Mailbox: 0x010_2000-0x010_3FFF (8KB, RW, general-purpose). "
        "'To CPU interrupt status' bank (base 0x010_1000, 88 bits across 9 registers): [15:0]=per-CQ "
        "job-done, [31:16]=per-CQ to-CPU software interrupt, [39:32]=4x monitored-address-region "
        "write/read events, [55:40]=per-CQ instruction execution timeout, [59:56]=4x HUM-apply-"
        "succeeded (per CPU channel), [70:64]=engine-level events (job-section-fetched, "
        "arbiter-logger-done, invalid-AXI-read-address, register-guard-violation, SMEM-read "
        "pre-buffer full, apply/release-without-authorization errors), [87:72]=per-CQ error interrupt "
        "(each cross-referencing its own 0x010_119X/0x010_11AX status registers); plus cqapberrint "
        "(0x010_100B[0], RWC) = register APB interface ready timeout. 'To CQ interrupt status' bank "
        "(base 0x010_1010): tocqNintstatus[15:0] per CQ, peer-to-peer CQ-to-CQ software interrupt "
        "matrix. Software-reset block (0x010_1060-1061): dramifrst, cqbuffrst, apbrst(W), apbabtrst "
        "(hold/release semantics: write-1-and-KEEP for hold, write-0 to release, not a pulse), "
        "humabtrst ('clears all 64 hardware-unit occupancy states, owner records, and HUM apply/"
        "release error flags'), abtlogrst; rprst (0x010_1061[0]) uniquely defaults to 1 (all other "
        "reset bits in this block default 0). inschken[15:0] (0x010_1062~3, default 0xFFFF) = per-CQ "
        "pause-on-instruction-format-error enable, doc notes error reporting still works even if "
        "disabled. "
        "CQ core control registers: 16 identical 0x20-byte per-CQ blocks at base=0x000,0x020,...,0x1E0 "
        "(CQ0-CQF), each at 0x010_12xx+base: cqcorestatus_0/1[0:1](RW/R enable+waiting-status), "
        "bp_halt[2](R), cqrst[0]/cqpause[1]/cq_step[2](WS single-step)/cq_resume[3](WS)/"
        "CQm_to_CPU_swint[4](WS) at +0x01, CQm_to_CQn[15:0](WS) at +0x02~03 (peer software-interrupt "
        "vector), cqbaseaddr[31:2](RW) at +0x04~07 (job-program base in SMEM), cqcurcmddramaddr[31:2](R) "
        "at +0x08~0B, cqcurcmd[31:0](R) at +0x0C~0F (debug visibility of current instruction), "
        "cqcmdtimernum[24:0](RW default 0x1FF_FFFF) at +0x10~13 with formula "
        "time-out=(cqcmdtimernum+1)/25MHz, cqcmdtimermode[31] (0=reset-per-instruction / "
        "1=reset-at-job-done-only), sectionvldmode[0](RW default 1, doc states 'Reserved for future "
        "use; currently has no effect on CQ behavior' -- a vestigial bit), randomallocate[1](RW "
        "default 1, job-buffer section-jump-target-match enforcement, bypassable), arqos_reg[3:0](RW) "
        "at +0x15, cqprot[2:0](RW default 0x2, new in v0.3) at +0x1C. CQ core internal registers: "
        "cq_r0..cq_r15 general-purpose register file per CQ (mostly R, default 0), cq_r12[31:0] is "
        "special ([3:0]=CQID self-identifier, [12:8]=ALU flags N/Z/C/V/G, [31:16]=Abase[27:12] current "
        "address), cq_r15 defaults to 0x4 (not 0). CQ JOB SRAM: 0x010_1600-0x010_167F (128 bytes, RW), "
        "CQ_job_section[1023:0], accessed via jobsecsel/jobpartsel/jobsramwenable, 4-byte-aligned "
        "access. Other sections present but only structurally noted: APB arbiter history (8x 5-bit "
        "records, 19 possible masters CPU/MCU/APB_PORT1/CQ0-F), 4-region register-address monitor "
        "(25-bit ranges), Hardware Unit Management (4 CPU channels x 64 hardware units, "
        "cpuhumdevid/cpuhumctrl per channel, humstate_dev_N occupancy bitmaps, humrecord_devN[4:0] "
        "ownership encoding 0-3=CPU-ch0-3/4-19=CQ0-CQF), Arbiter logger, CQ/CPU HUM error status, "
        "Instruction format error status, Multiple WFE, Parser for CQX, CQ SRAM BIST/mode-control, "
        "Lock register APB requester, CQ probe, Date code."
    ),
    "source_paths": [
        r"D:\DV\Task\USB\DOC\SS_QDMA\PAISB_CQ_Reg_260810.docx",
        r"D:\DV\Task\USB\DOC\SS_QDMA\PAISB_CQ_Reg_260625.docx",
        r"D:\DV\Task\USB\DOC\SS_QDMA\PAISB_CQ_Reg_260603.docx",
    ],
    "category": "dut_registers",
    "provenance": PROV,
})

# 5. SS_QDMA glue + DMA engine register map, and xlsx-vs-docx delta
records.append({
    "kind": "project_fact",
    "verified": True,
    "scope": "project",
    "title": "SS_QDMA glue registers + DMA engine register map, and docx-vs-xlsx version deltas",
    "summary": (
        "SS_QDMA\\PAISB_SS_QDMA_Reg_260605.docx (only 1 dated copy, fully read, 155 lines) documents "
        "the SS_QDMA subsystem glue registers, base 0x1030_0000. Confirms (and is used as evidence "
        "for) the SoC address-formula: 'the CQ at 0x1010_0000 and the DMA at 0x1031_0000 onward'. "
        "ss_qdma_reg00 (0x1030_0000): ss_qdma_intevt[14:0](RWC, default 0) = [0]register-guard-"
        "violation, [1]-[8]=CQ/DMA AXI write/read error (bid/rid empty vs mismatch, 4 combos x2 for "
        "CQ vs DMA), matching irqen/fiqen; 16x cqintNNsel[3:0](RW default 0xF, 0-8 map to intevt bits, "
        "15=none); 16x cqintNNen[1:0](RW default 0, [0]=ss_qdma-enable [1]=DMA-enable of CQ-INT); "
        "cqintmode[15:0](OR/AND per CQ); mswrst[1:0](RW default 0, [0]=CQ [1]=DMA); pclken/aclken/"
        "xtlclken[2:0] (RW, [0]=SS_QDMA-top [1]=CQ [2]=DMA; xtlclken is the 25MHz Xtal clock). "
        "ss_qdma_reg01 (0x1030_0100): two AXI arbiters (write/read) merging CQ+DMA onto one shared "
        "external AXI-4 bus; warb_pause/rarb_pause[1:0] DEFAULT 0x3 (both sources paused at reset) -- "
        "doc explicitly warns 'software must clear them during the initial flow' (a required, "
        "documented bring-up step, not optional); warb_priority/rarb_priority[7:0] 4-bit-per-source; "
        "warb_busy/rarb_busy[1:0](R); warb_error/rarb_error[3:0](R, 2-bit-per-source error code). "
        "SS_QDMA\\PAISB_DMA_Reg_260605.docx (only 1 dated copy, fully read, 749 lines) documents the "
        "8-channel streaming-DMA engine, base 0x1031_0000: 5 shared 256-byte 'topctl' pages "
        "(dma_reg00-04) plus 8 per-channel 256-byte pages (dma_core[0..7] at 0x1031_8000+n*0x100). "
        "dma_reg00 (0x1031_0000): 4x dma_strin_intevt0-3[31:0](RWC) + 4x dma_strout_intevt0-3, each "
        "packing 8 tid's x4-bit {SOF,SOL/SOP,EOF,EOL/EOP}, covers tid 0-31; dma_intevt[15:0]([7:0]=ch0-7 "
        "src-done [15:8]=ch0-7 dst-done); dma_err_intevt[31:0]([7:0]=ch0-7 src-err [15:8]=ch0-7 dst-err "
        "[23:16]=ch0-7 reg-guard-violation [24]=DMA-top reg-guard [25]-[28]=source-stream-0/1 multi-/"
        "null-destination errors); matching irqen(+0x40)/fiqen(+0x80)/esmen(+0xC0) shadow blocks per "
        "event register (explicitly documented offset pattern); mswrst[7:0](0x00D0, per-channel), "
        "mclken[7:0](0x00D4, default 0xFF all-on), mtoken[7:0](0x00D8, per-channel secure token). "
        "dma_reg01 (0x1031_0100): 2-layer CQ-interrupt mechanism -- per-CQ 80-bit enable "
        "(cqintNNen0/1/2, dma_intevt[16]+org-stream-evt[32]+out-stream-evt[32]) x AND/OR mode "
        "(cqintmode) x 7-bit cqintNNsel selecting 1-of-82 (0-15=dma_intevt, 16-47=org-stream-tid0-31, "
        "48-79=out-stream-tid0-31, 80=aggregated, 81=none); cqintNNsel DEFAULTS to 0x51=81=none for "
        "all 16 CQs (no DMA event routed to any CQ at reset by default). dma_reg02 (0x1031_0200): "
        "AXI write/read arbiters for 8 channels (warb/rarb_axi_pause[7:0] DEFAULT 0xFF = ALL 8 "
        "CHANNELS PAUSED at reset, priority 4-bit-per-channel), 2 MailBox arbiters, arben[3:0] DEFAULT "
        "0x0 (all four arbiters disabled at reset), stream-pipe pause/priority for a 14-source output "
        "arbiter (DSRCN=14: m0:ch0-3+s0, m1:ch4-7+s1, m2:ch2/3/6/7; default pause=0x1F priority=0x0), "
        "SRAM arbiter+power+BIST. Doc's own explicit bring-up warning: 'Note the safe defaults: "
        "arben=0, sram_arb_en=0, cfg_src_pause=0x3, cfg_dst_pause=0x7, arbiter pause=0xFF -- software "
        "must release these in the initial flow.' dma_reg03/04 (0x1031_0300/0400): per-tid (0-31) "
        "stats, 16-bit values packed 2-per-32-bit-register (framecnt/hsize/line-CRC/frame-CRC), "
        "identical layout for origin(input,reg03) vs output(reg04) side. "
        "dma_core[n] per-channel page (0x1031_8000+n*0x100, n=0..7): dma_chx_id/token(R) at 0x00; "
        "sts_src_error[5:0]/sts_dst_error[9:0](R) at 0x04/0x05~6; trigger[1:0](W, [0]=source-trigger "
        "[1]=destination/pipe-trigger, a 2-STAGE trigger) at 0x08; sts_busy[2:0](R) at 0x09; "
        "axi_src_mlen/axi_dst_mlen[7:0](RW default 3) at 0x0C/0D; srcsel[2:0](RW, 0=SMEM/AXI4 "
        "1=AXI-Stream 2=Mail-Box 3=PIO 4=Register-Fill) at 0x10; src_size[19:0](RW default 0x10000) "
        "at 0x14~6; src_addr[31:0](RW default 0x20000000) at 0x18~B; src_aruser[8:0](RW default 0x6, "
        "[3:0]TZC400-ID [7:4]ring-buffer-select-1-of-16 [8]bypass-vs-ring-buffer-mode) at 0x1C; "
        "src_arqos[3:0] at 0x1E; symmetric dstsel/dst_size/dst_addr/dst_awuser/dst_awqos at "
        "0x30/34~6/38~B/3C/3E; dst_tuser[19:0](RW, [0]SOF [1]EOF [2]SOL/SOP [3]EOL/EOP "
        "[19:4]Beat-Count/HSIZE) at 0x44~6; PIO FIFO ports (piowr_data/ready/full, piord_data/valid/"
        "empty) at 0x50-5C; swrst[7:0](RW, [0]src [1]dst [2]pipe [4]monitor-crc32 [5]monitor-checksum) "
        "at 0x60; disgclken[0](RW default 1=always-on) at 0x68; in-core CRC32/checksum monitor block "
        "at 0x80-0xA5 (mon_crc_en/checksum_en, mon_crc_idle/checksum_idle default 1, mon_crc_mden "
        "[0]line/packet [1]frame-with-restore, mon_crc_restore+restore_din default 0xFFFFFFFF, "
        "mon_crc32_line/frame + mon_cur_crc32_line/frame(default 0xFFFFFFFF) + mon_checksum32/16). "
        "CROSS-REFERENCE / VERSION DELTA vs SS_QDMA\\register__ssqdma_dma_260719.xlsx (latest of 2 "
        "dated xlsx copies, 260701 and 260719 -- diffed directly): the xlsx is MORE COMPLETE than "
        "this 260605 docx for the per-channel page. (a) The xlsx has FOUR fields entirely absent "
        "from the docx: src_arprot[6:4](RW default 0, packed into byte 0x1E alongside src_arqos), "
        "src_arcache[3:0](RW default 0x3, byte 0x1F), dst_arprot[6:4](byte 0x3E alongside dst_awqos), "
        "dst_arcache[3:0](RW default 0x3, byte 0x3F) -- AXI PROT/CACHE attribute control the docx "
        "never mentions. (b) The 260701->260719 xlsx diff adds a wholly NEW register dst_rbc_thres "
        "(0xB0~3, RW, default 0x400, 'destination ring buffer control threshold value') that exists "
        "in NEITHER the docx NOR the 260701 xlsx -- newest addition, docx's per-channel table jumps "
        "straight from mon_checksum16(0xA4~5) to reserved(0xF0+) with nothing at 0xB0. (c) The "
        "260701->260719 xlsx diff also renamed 7 DOC-FACING register names in the dma_reg02 sheet "
        "(added a '_str_' infix to disambiguate from per-channel names) while the RTL Register Name "
        "column (a column the docx doesn't even carry) stayed IDENTICAL: cfg_src_rst->cfg_str_src_rst, "
        "cfg_dst_rst->cfg_str_dst_rst, cfg_src_pause->cfg_str_src_pause, cfg_dst_pause->"
        "cfg_str_dst_pause, cfg_dst_s_pause_g0/g1/g2->cfg_str_dst_s_pause_g0/g1/g2, cfg_dst_s_prio_g0/"
        "g1/g2->cfg_str_dst_s_prio_g0/g1/g2, cfg_src_idmask->cfg_str_src_idmask. The 260605 docx uses "
        "the OLD (pre-rename) names throughout its dma_reg02 section. CONSEQUENCE: cite the stable RTL "
        "Register Name, not the doc-facing name, when the doc-facing name might be version-dependent; "
        "use the xlsx (not the 260605 docx) as the authoritative source for the per-channel page's "
        "AXI-attribute fields and dst_rbc_thres."
    ),
    "source_paths": [
        r"D:\DV\Task\USB\DOC\SS_QDMA\PAISB_SS_QDMA_Reg_260605.docx",
        r"D:\DV\Task\USB\DOC\SS_QDMA\PAISB_DMA_Reg_260605.docx",
        r"D:\DV\Task\USB\DOC\SS_QDMA\register__ssqdma_dma_260719.xlsx",
        r"D:\DV\Task\USB\DOC\SS_QDMA\register__ssqdma_dma_260701.xlsx",
    ],
    "category": "dut_registers",
    "provenance": PROV,
})

# 6. RTL/VIP scaledown timing mapping
records.append({
    "kind": "project_fact",
    "verified": True,
    "scope": "project",
    "title": "rtl_vip_scaledown_mapping.xls -- RTL LTSSM/chirp timer constants mapped to SVT_USB VIP config",
    "summary": (
        "D:\\DV\\Task\\USB\\DOC\\rtl_vip_scaledown_mapping.xls cross-references the DUT RTL's "
        "ss_scaledown_mode-gated LTSSM/PRTSM/USB2-chirp timer constants against the corresponding "
        "Synopsys svt_usb_* VIP config fields, with concrete Default-vs-Scaled numeric pairs -- this "
        "is a timing/config cross-reference, not a register-address map, but is the primary source "
        "for 'what should this scaled-mode LTSSM/chirp timing value be' checker/scoreboard questions. "
        "8 sheets, all read: 'RTL and VIP' (105 rows) pairs literal RTL Verilog snippets "
        "(e.g. ONE_MSEC = pwr_down_clk_en&&scale ? pwr_down_scale[12:2]+1 : scale?'d10:'d1000) against "
        "SVT_USB_* macro-driven VIP fields with Default/Scaled values -- notable: RX_DET_ATTEMPTS "
        "(RTL scales 7->2) maps to rx_detect_termination_detect_count which is 8.0 in BOTH Default "
        "and Scaled VIP columns (not actually scaled in the VIP despite the RTL having a scale-down "
        "path -- a real non-uniform-scaling case). Also captures the full LT_* LTSSM per-state "
        "timeout family (LT_RX_DET_QUIET_MS, LT_SSI_QUIET_MS, LT_POLL_LFPS_MS, LT_POLL_ACTIVE_MS, "
        "LT_POLL_CONFIG_MS, LT_POLL_IDLE_US, LT_RECOV_ACTIVE_MS, LT_RECOV_CONFIG_MS, LT_RECOV_IDLE_US, "
        "LT_HRESET_ACT_MS, LT_HRESET_EXIT_US) each with its VIP-side *_timeout knob. Contains an "
        "explicit in-sheet note: 'This is for USB3.0 ECN20, and is used only for a downstream port. "
        "The default behaviour does not use this. To enable this, set GUCTL.DS_RXDET_MAX_TOUT_CTRL' -- "
        "the only place in this whole extraction that names a specific DWC_usb31 core register+field "
        "(GUCTL.DS_RXDET_MAX_TOUT_CTRL) with functional meaning, though its address is not given here "
        "(see the GCTL/DCTL address-gap memory record). Sheet 'Scaled VIP Variables' (126 rows) lists "
        "two flat pre-scaled config columns: 'for SS operation' (credit_hp_timer=50us, "
        "hot_reset_active_timeout=130us, full lfps_t1x_t1x_uN_min/max family, "
        "ux_exit_timer_timeout=6000us, usb_ss_symbol_clock_period=400ps) and 'for 2.0 operation' "
        "(tattdb, tdchbit=750ns, tdchse0=1.5us, tdrst=115us-IF-DWC_USB3_FREECLK_USB2_EXISTS-"
        "else-15us, twtrsths=450us). Sheet 'USB2-Device' (File=DWC_usb3_u2dssr.v, 18 rows): device-mode "
        "chirp/reset timing mapped to spec params TDCHSE0/TDETRST/TWTRSTHS/TUCH/TWTFS/TFILT; notable "
        "footnote: 'If GUSB2PHYCFG[XCVRDLY] is set, then the chirp duration is reduced by 2.5us for "
        "both fullscale/scaledown modes' -- second core-register+field name (GUSB2PHYCFG.XCVRDLY) "
        "named with functional effect but no address. Sheet 'USB2-Host' (File=DWC_usb3_u2prtsm.v, 32 "
        "rows): host-mode chirp/reset (reset_duration/TDRSTR cites USB2.0 spec section 7.1.7.5 "
        "directly: 'resets from root ports have a duration of at least 50 ms'); revert_time(TWTREV) "
        "RTL fullscale=4ms is intentionally looser than the 3-3.125ms spec range, doc comment: 'This "
        "is ok to account for clock accuracy.' Sheets 'USB2-OTG' (102 rows), 'USB3-OTG3' (22 rows, "
        "a3_/b3_ port-A/port-B dual-role LTSSM timer pairs), 'USB3-LTSSM' (18 rows, a second "
        "state-name-labeled restatement of the LT_* timers: RxDetect.Quiet, Polling.LFPS, "
        "Polling.Active, etc.), 'USB3-SSIC' (58 rows, M-PHY/SSIC variant with a 3-way "
        "scaled/SNPS-M-PHY-sim-scaled/non-scaled value split, e.g. tRESET_DIFFN: 100us/400us/70ms, "
        "plus inline ifdef DWC_USB3_SNPS_MPHY_SIM_SUPPORT-conditioned RTL timer variants)."
    ),
    "source_paths": [r"D:\DV\Task\USB\DOC\rtl_vip_scaledown_mapping.xls"],
    "category": "dut_registers",
    "provenance": PROV,
})

for i, r in enumerate(records, 1):
    result = route_and_store(ROOT, r)
    print(i, r["title"][:70], "->", result)
