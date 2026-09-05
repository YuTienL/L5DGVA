# Intake Extraction: Top Testbench / Running Script / File List, and `command.txt`

Categories 9+10. Deep content extraction (not an index) of the real material on the remote
Linux DV server for the `dlan063` (LAN063 SoC) DUT drop, cross-referenced against this
Harness's own `command.txt`-processing code and its `.dv-workflow/command_inventory.csv`.

Remote host: `host-c` (relay confirmed `READY` at session start, pid 16888).
Remote root examined: `/home/svcacct/DV/DUT/0820/dlan063/SIMV_GIT/` (git repo `dlan063rtl`,
`.gitlab-ci.yml` present — CI job `build-job` runs `./runver.sh`, tags `dlan063rtl`, archives
`vcs.log`).

**Session caveat**: near the end of this extraction, an interactive `git log` invocation on the
remote tcsh shell opened a pager and left the relay's single command queue blocked (subsequent
`--status`/`cat runver.sh` calls also hung and were moved to background). This happened *after*
all material below had already been pulled and verified in full — nothing in this report is
based on a hung or partial read. `runver.sh` (the actual `.gitlab-ci.yml` CI entry point, as
opposed to `runver_precomp` which is the interactively-invoked "official DE reference" script)
was not read as a result and is noted as a residual gap at the end.

---

## 1. `vcs.opt` — full flag inventory + real file compile order

**Path**: `/home/svcacct/DV/DUT/0820/dlan063/SIMV_GIT/vcs.opt` (162 lines, 4689 bytes, confirmed
byte count via `wc -c`). This is the `-f` filelist consumed by `runver_precomp`'s `vcs ... -f
vcs.opt` invocation (see §2) — it is simultaneously a VCS *option file* (global switches,
`+define+*`) and a Verilog *source filelist* (bare `./RTLCAT/FOO.v` lines), which is legal VCS
`-f` syntax but means "flag inventory" and "compile order" are interleaved in one file, not two.

### 1.1 Global switches (lines 1–10)

| Flag | What it does |
|---|---|
| `+lint=TFIPC-L` | Enables VCS lint checking for Task/Function/Internal-signal/Port/Library-cell categories (`T`ask, `F`unction, `I`nternal, `P`ort, `C`onnectivity, `-L`ibrary) — catches unconnected ports, unused tasks/functions, etc. at elaboration. |
| `+define+FASTRST` | Compile-time macro to skip the full 1 ms global power-on reset sequence in sim (faster bring-up for non-reset-focused tests). |
| `+define+RTL` | Distinguishes RTL-view compile from a gate/netlist (`SYN`) compile — many modules `` `ifdef RTL`` / `` `ifdef SYN`` branch on this. |
| `//+define+DV_SYNTHESIS` (commented) | Would select the ZEBU/HAPS emulation-implementation code path — disabled for this VCS/RTLSIM `vcs.opt`; see §1.5 for the enabled ZEBU counterpart `vcs_z.opt`. |
| `//+define+HAPS` (commented) | Distinguishes ASIC vs. HAPS FPGA-prototype builds — the file's own inline comment flags this define as "Need to be reviewed" (unresolved TODO left in the DE's own filelist). |
| `+define+no_warning` | Suppresses warnings gated behind a `no_warning` compile-time check in the RTL/models. |
| `+notimingcheck` | Skips SDF-driven timing-check assertions in library cells during RTL/PRESIM phases (irrelevant pre-netlist, avoids spurious setup/hold noise). |
| `+neg_tchk` | Enables negative timing-check evaluation; a negative timing value is clamped to zero rather than causing a spurious violation. |
| `+v2k` | Enables Verilog-2001 syntax (vs. strict Verilog-95). |
| `+libext+.v+.vlib` | For every `-y <dir>` library directory, only files ending in `.v` or `.vlib` are pulled in as cell definitions. |

### 1.2 Macro-block and model-selection defines (lines 11–32)

```
//MACRO
+define+M31_NO_PG_PORT        // M31 (PLL+SARADC) analog macro: omit its PG (power-good) port
//MODEL
+define+CQ_APB_DIRECT_ACCESS  // enables a direct-APB-access path in the CQ (command-queue) model
+define+GSIAPB                // <-- selects the CPU-BFM macro family (see §3.2 below)
//+define+I2CAPB               (commented out — alternative BFM: I2C-host-to-APB bridge)
//+define+PRINTCMD
//+define+CQMODEL_EN
//+define+CPUMODEL_EN          (commented out — the "real" internal CPU model is NOT compiled in)
//+define+EXTROM
//+define+EXTMEM
//+define+AUDMODEL_EN
//+define+FMMODEL_EN
//+define+PERIMODEL_EN
//+define+CANBUSMODEL_EN
//+define+PCIE_RP_MODEL_EN
//+define+FRONTMODEL_EN
//+define+ISPMODEL_EN
+define+SMEMMODEL_EN          // <-- system-memory behavioral model IS enabled
//+define+NO_ISPMODEL
+define+OVL_ASSERT_ON         // turns on Accellera OVL (Open Verification Library) assertions
+define+OVL_MAX_REPORT_ERROR=100   // caps OVL error reporting at 100 occurrences
```
Reading the commented-out block as a whole: every optional peripheral behavioral model
(`AUDMODEL`, `FMMODEL`, `PERIMODEL`, `CANBUSMODEL`, `PCIE_RP_MODEL`, `FRONTMODEL`, `ISPMODEL`,
`CQMODEL`) is disabled in this drop except `SMEMMODEL_EN` — this build is deliberately
minimized to just system memory + the GSIAPB CPU-BFM bridge, consistent with the `command.txt`
content actually resident in this snapshot being a register-access/token smoke test (§3) rather
than a multimedia/ISP/audio scenario.

**Real, DE-visible drift confirmed in-session**: `vcs.opt~` (the editor backup sitting next to
the live file) differs from `vcs.opt` at exactly one functional line:
```
< -v ./MACRO/CL12812M8RIP.vp          (current vcs.opt)
> -v ./MACRO/CL12812M8RIP_r103.vp     (vcs.opt~ backup)
```
i.e. someone rolled the `CL12812M8RIP` SRAM macro model back from an `_r103` revision to the
unversioned (presumably newer or reset-to-baseline) file between the backup and the live file.
Separately, `vcs_z.opt` (the ZEBU-flow sibling option file, see §1.5) still differs from
`vcs.opt` on `SMEMMODEL_EN` (disabled for ZEBU) and swaps `MACRO_ROM.v`/`MACRO_SRAM.v` for
`MACRO_ROM_SYN.v`/`MACRO_SRAM_SYN.v` — ZEBU emulation uses the synthesized/gate memory views,
RTL sim uses the behavioral ones.

### 1.3 Project-wide parameter header (line 35)

```
//PROJECT DEFINE
./RTLCAT/lan063_define.h
```
Passed as a **bare source file** (not `-v`/`-f`), meaning VCS compiles it directly as a
top-level Verilog source — legal because its content is pure `` `define`` preprocessor text
(225 lines, confirmed read in full). It is the single place that fixes every subsystem's bus
widths / counts for this chip revision — concrete values a verification engineer needs when
sizing buses or covergroups:

| Define | Value | Meaning |
|---|---|---|
| `CQAPB_N` | 25 | CQ (command-queue) APB slave count |
| `CQINT_N` | 17 | CQ interrupt count |
| `GTOP_APBAW` | 24 | Global-top APB address bit width |
| `GTOP_TKN` | 8 | Global-top security-token count |
| `GTOP_TRAP` | 10 | Boot-trap vector width (matches `trapvalue_map[9:0]` used in `command.txt`, §3) |
| `CPU_AXIDW` | 128 | CPU-subsystem AXI data width |
| `CPU_IRQN` | 512 | Number of interrupts the CPU can field |
| `VIS_AXIDW` | 256 | Vision-subsystem AXI data width |
| `VIS_NIB` | 6+4=10 | Number of input bays: 6 MIPI CSI-2 + 4 SLVS-EC |
| `VOUT_ASDW` | 256 | SS_VOUT AXI-slave data width |
| `VOUT_TKN` | 16 | SS_VOUT token count |
| `GCON_TKN` | 96 | SS_GCON (general-connectivity: FM/CAN/AUD/PERI) token count |
| `GCON_ION` | `FMION(11)+CANION(8)+AUDION(20)+PERION(92)` = 131 | Total SS_GCON GPIO count |
| `UCIE_D2D_NLANES` | 2 | UCIe die-to-die lane count |

### 1.4 Real file compile order (lines 37–160)

The filelist encodes an explicit subsystem compile order (each `+incdir+` immediately precedes
the `.v` file(s) that need it, i.e. include-path scoping is per-block, not global):

1. **ENV (FAB/DW/GTECH)** — `ENV/SNPSDW` library dir, `ENV_FAB.v`, `ENV_SNPSGTECH.v` (Synopsys
   DesignWare / generic-tech simulation primitives).
2. **MODEL** — `+incdir+./MODEL/include/`, `-f ./MODEL/pvt_def.f` (a nested `-f` inside the
   outer `-f`, defining `PROJECT DEFINE`s for PVT), then `MODEL_ALL.v` (the entire behavioral
   model + top-level testbench harness, ~9000+ lines — this is the file that `` `include``s
   `command.txt`, see §3.1) and one encrypted IP file `pufrt_hmc_peri_enc.v.e`.
3. **MACRO / SRAM** — `MACRO_ALL.v`, `MACRO_ROM.v`, `MACRO_SRAM.v` (behavioral memory), plus two
   real hard-IP `.vp` analog models: the M31 PLL (`M31SOCPLL4508TL012D_00167801_rtl.vp.vcs`) and
   the `CL12812M8RIP` SRAM compiler macro (version drift noted in §1.2).
4. **TOP** — `+incdir+./RTLCAT/PVT_include`, `MISC_ALL.v`, `TOP_ALL.v` (chip-top port list /
   glue — this is where `pprot_s_gtop`, the security-token signal `command.txt` forces, is
   actually declared and wired, confirmed at `RTLCAT/TOP_ALL.v:27501,27637,28009,37263,37657,
   37705`).
5. **SS_CPU** — `+incdir+./RTLCAT/R52_include`, `SS_CPU_ALL.v` (the CPU subsystem — note the
   include-dir name `R52_include` names an Arm Cortex-R52-class core, while the netlist/SDF
   `` `ifdef CPUTOP_POSTSIM`` block inside `MODEL_ALL.v` instead SDF-annotates
   `sysn063.u_lan063.u_ss_cpu.u_ca55.u_cortexa55` — a **Cortex-A55** hierarchy path. These two
   names (R52 include dir vs. A55 SDF path) point at different Arm cores in the same file; not
   resolved further in this pass — flagged as a real naming inconsistency worth a DE follow-up
   question rather than silently picking one).
6. **SS_VIS** (vision) — `SS_VIS_ALL.v`, `_CQ.v`, `_WPISP.v`, `_FRONT.v`, then a MIPI-RX PHY/CTRL
   pair gated behind `+define+DWC_CDPHYRX_TOP_PG_PINS` / `+define+DWC_CDPHY2L2TNS_PG_PINS` /
   `+define+dwc_mipi_cdphy_rx_2l2t_ns_SYNTHESIS` (Synopsys DesignWare C/D-PHY RX IP), plus
   `SS_VIS_SLVSECRX_SIM.v` (SLVS-EC receiver).
7. **SS_QDMA** — `SS_QDMA_ALL.v` (single file, no sub-blocks broken out at this level).
8. **SS_VOUT** (the block that owns USB/PCIe/MAC/MIPI-TX) — compiled in **USB → MAC →
   PCIe → MIPI-TX → PKT** sub-order: `SS_VOUT_ALL.v`, then USB
   (`SS_VOUT_USB_CTRL.v` + `udc_DWC_usb31-undef.svh`, `SS_VOUT_USB_PHY.v`, `SS_VOUT_USB.v` —
   confirming the DUT's USB controller IP is a Synopsys DesignWare `usb31` UDC), then MAC
   (`SS_VOUT_MAC_CTRL.v` + `DWC_25gmac-undef.vh` — a DesignWare 25G MAC — `SS_VOUT_MAC_SEC.v` +
   `DWC_macsec-undef.sv`, `SS_VOUT_MAC.v`), then PCIe (`SS_VOUT_PCIE_TOP/CTRL/PHY/MISC.v`,
   `SS_VOUT_MAC_PCS.v`), then MIPI-TX (`SS_VOUT_MIPITX.v/_CTRL.v/_PHY.v`), then
   `SS_VOUT_PKT.v` (packet/stream engine). Every `DUMMY_TOP/*_dummy.v` stub for this block is
   commented out (real RTL is compiled, not stubbed) — the 25 real `DUMMY_TOP/*.v` stub files
   that exist on disk (confirmed via `ls`) are therefore currently unused for this build; they
   exist for a leaner partial-compile configuration (`ucie_dummy.v` IS actually used, see next
   bullet).
9. **SS_GCON** — `SS_GCON_ALL.v`.
10. **SS_MEM** — `SS_MEM_ALL.v`.
11. **UCIE** — `./DUMMY_TOP/ucie_dummy.v` is compiled (real `RTLCAT/UCIE_ALL.v` is commented
    out) — i.e. UCIe is stubbed out entirely in this build, even though `lan063_define.h` still
    sizes a full `UCIE_*` parameter set (§1.3) and `MODEL_ALL.v` still declares real `xucie0_*`
    top-level IO wires (confirmed lines ~185–200 of `MODEL_ALL.v`) — the IO exists structurally
    but the UCIe controller behind it is a dummy stub for this run.
12. **SETOP** (security/crypto subsystem) — `SE_ALL.v` plus three **encrypted** IP sources:
    `SE_pscc_core_enc.v.e`, `SE_psxip_core_enc.v.e`, `SE_pufrt_core_enc.v.e` (PUF-based root of
    trust / secure-crypto-core / secure-XIP IP, vendor-encrypted `.v.e` — not human-readable
    even with disk access).

**Real anomaly found in the live file**: `vcs.opt` line 160, the very last non-blank line, is a
bare, incomplete filelist entry:
```
./RTLCAT/
```
— a directory path with **no filename**, immediately following the three `SE_*_enc.v.e` lines
and preceding two blank lines that end the file (confirmed via `sed`, `wc -c` matches 4689
bytes exactly — this is not a transfer truncation, it is what is actually saved on disk). This
reads as an abandoned/interrupted edit (someone started to add one more `RTLCAT/` file
reference and never finished the line) that has apparently shipped this way without breaking
the build — `simv` (the compiled binary, timestamped Aug 24 02:35) and a 5 MB `vcs.log` both
exist, so VCS evidently tolerates or ignores the dangling bare-directory token rather than
erroring. Flagged here as real, DE-actionable filelist hygiene debt, not corrected.

### 1.5 ZEBU-flow sibling: `vcs_z.opt`

`vcs_z.opt` (used by `runver_precomp_z`, the ZEBU-emulation counterpart to `runver_precomp`)
diffs from `vcs.opt` at exactly two points:
```
29c29
< +define+SMEMMODEL_EN        (vcs.opt: system-memory behavioral model ON)
---
> //+define+SMEMMODEL_EN      (vcs_z.opt: OFF for ZEBU)
52,53c52,53
< -v ./MACRO/MACRO_ROM.v      -v ./MACRO/MACRO_SRAM.v        (behavioral memory views)
---
> -v ./MACRO/MACRO_ROM_SYN.v  -v ./MACRO/MACRO_SRAM_SYN.v    (synthesized/gate memory views)
```
i.e. ZEBU hardware emulation needs synthesizable (gate-level) memory macro views and does not
carry the RTLSIM-only behavioral system-memory model — a real, DE-confirmed VCS-vs-ZEBU flow
divergence a future agent should not assume is symmetric.

---

## 2. `runver_precomp` — the real, already-confirmed official compile/run command

**Path**: `/home/svcacct/DV/DUT/0820/dlan063/SIMV_GIT/runver_precomp` (1243 bytes, executable).
Confirmed this session as the official DE reference compile script (per task framing).

Full real invocation (comment-only lines above it in the file document each flag's purpose —
quoted verbatim, not paraphrased):
```
vcs -lsfint -VERSION V-2023.12-SP2 \
-R \
-j4 \
-partcomp \
-sverilog \
-debug_access+all -kdb -lca -full64 \
+define+MISC_NOCHECK \
-f vcs.opt \
-l vcs.log \
-Xcheck_p1800_2009=char \
+error+10000
grep Warning vcs.log > vcs_w.log
grep Error   vcs.log > vcs_e.log
```
Flag-by-flag (per the file's own header comments plus VCS-standard semantics):
- `-lsfint` — VCS's built-in LSF-integration compile/elaborate-then-submit mode.
- `-VERSION V-2023.12-SP2` — pins the exact VCS release (matches `env.sh`'s
  `module load synopsys/vcs/V-2023.12-SP2_p`).
- `-R` — run simulation immediately after compile (single-step compile+run).
- `-j4` — 4-way parallel analyze phase.
- `-partcomp` — partition compile (incremental/partitioned compilation for faster rebuilds on
  large designs); the file's own header notes `-top topcfg ./topcfg.v` is available but
  currently **disabled** ("Disable topcfg for PVT compile issue" — a real, commented-out
  known-issue workaround left in place) — so `topcfg.v`'s explicit partition boundaries
  (`u_ss_mem`, `u_ss_vis`, `u_ss_cpu`, `u_ss_vout`, `u_ss_gcon`, `u_ss_qdma` under `sysn063`,
  confirmed by reading `topcfg.v` directly) are defined but **not currently applied** by this
  script.
- `-sverilog` — SystemVerilog syntax enabled.
- `-debug_access+all -kdb -lca` — full debug database + Verdi KDB/LCA hooks (waveform/schematic
  cross-probe capability retained even though this run defaults FSDB dumping off per the
  Harness's own Simulation Observability Default).
- `-full64` — 64-bit VCS.
- `+define+MISC_NOCHECK` — passed on the command line (not inside `vcs.opt`) — a top-level
  override define, separate from every `+define+` living inside the `-f` file.
- `-f vcs.opt` — pulls in the entire flag+filelist inventory from §1.
- `-l vcs.log` — the raw compile+sim log (5,165,399 bytes on disk this session).
- `-Xcheck_p1800_2009=char` — strict IEEE 1800-2009 SystemVerilog char-type checking.
- `+error+10000` — allow up to 10000 errors before VCS aborts (a generous ceiling — this is a
  large multi-IP SoC compile where transient elaboration errors across many blocks are
  expected before final green).
- Post-run: `vcs.log` is `grep`-split into `vcs_w.log` (Warnings, 2270 bytes this session) and
  `vcs_e.log` (Errors, 0 bytes this session — **clean compile, no errors** for the `command.txt`
  content resident during this snapshot).

**Real divergence vs. the ZEBU sibling `runver_precomp_z`**: identical flag set except
`-f vcs_z.opt` (§1.5) and, notably, a **different, more permissive Error filter**:
```
grep Error vcs.log | grep -v "VOUT_PCIE.*time 0 fs" > vcs_e.log
```
i.e. the ZEBU flow explicitly suppresses a known benign `VOUT_PCIE`-related error that fires at
simulation time 0 fs (a startup-race false positive already characterized and filtered by the
DE) — the plain VCS flow (`runver_precomp`) does **not** apply this filter, so a `VOUT_PCIE ...
time 0 fs` line would show up as a real error in `vcs_e.log` under the VCS-only flow even though
it is a known non-issue under ZEBU. A future debug agent reading `vcs_e.log` from a
`runver_precomp` (not `_z`) run must apply the same suppression manually before treating a
`VOUT_PCIE`-time-0 hit as a real regression.

`env.sh` (sourced before either script) loads the full EDA toolchain module set for this
project: `synopsys/vcs`, `verdi`, `dc`, `libcompiler`, `primetime`, `formality`, `coreTools`,
`architect`, `metaware` (all `V-2023.12-SP*`/`W-2024.09`-class), plus `python/3.10`,
`gcc/glibc-9.3.0`, `mentor/calibre` — `DESIGNWARE_HOME` defaults to
`/eda/synopsys/DesignWare/iCatchDW` unless already set in the caller's shell.

---

## 3. `command.txt` — the DUT's own real top-level command file

**Path**: `/home/svcacct/DV/DUT/0820/dlan063/SIMV_GIT/command.txt` (90 lines, 2762 bytes,
confirmed via `cat -n` in full — every line below is quoted from the real file, not
reconstructed).

### 3.1 What it actually is, and how it enters the compile

Its own header identifies it as a different, older file that has been copied into this slot:
```
// File Name    : regrw.txt
// Description  : GLOAL_INIT & DRAM_INIT & REGISTER R/W defualt test
// Revision
// 2006/02/10   : creation
```
`command.txt` is **not a fixed piece of content** — it is a *slot name*. `MODEL/MODEL_ALL.v`
(compiled directly by `vcs.opt`, §1.4) contains, at line 316, an unconditional
```verilog
`include "command.txt"
```
inside the `sysn063` top-level module body (confirmed by reading `MODEL_ALL.v:300–330`
directly). Whatever file a DE has copied to `./command.txt` at compile time becomes this
run's stimulus. For **this** snapshot, that file is the register-read/write + TrustZone-style
security-token smoke test (`regrw.txt`'s content) — **not** any of the 24 USB BFM pattern
scenarios catalogued in this Harness's own `.dv-workflow/command_inventory.csv` (extreg_rw,
USB2_bulkin, USB31_SSPbulkin, etc. — see §4 for the cross-reference and why this matters).

### 3.2 Line-by-line real intent (not just the mechanical pattern-match)

```verilog
`include "wave.txt"
```
Pulls in the FSDB dump control block (`wave.txt`, 14 lines, read in full):
```verilog
initial begin
  $fsdbDumpfile("./FSDB/debug.fsdb");
  $fsdbDumpvars(0,sysn063);
  //$fsdbDumpvars(5,sysn063);
  //... six more commented-out scoped-depth alternatives for individual sub-blocks (u_cqtop,
  //    u_dmatop, u_fmtop, u_ss_cdec, u_peritop, u_ucie_0) ...
  #5000000 $finish;
end
```
i.e. the *default* dump scope in this file is **full-chip, full-depth** (`$fsdbDumpvars(0,
sysn063)` — depth `0` means unlimited), directly contradicting this Harness's own "Waveform
Dump User Gate" / "Simulation Observability Default" (FSDB off by default, minimum sufficient
scope when on) — this is DE-authored legacy content, not Harness-generated, so the divergence
is expected, but a future agent must not copy this `wave.txt` pattern verbatim into a
Harness-generated environment without re-scoping it per the gate. `wave.txt` also carries an
independent **5,000,000-time-unit hard `$finish`** safety timeout, separate from and in addition
to `command.txt`'s own end-of-test `$finish` (line 85) — whichever fires first ends the sim.

```verilog
reg     [7:0]  regtestdata;   // declared, never referenced anywhere else in the file (dead reg)
integer        i;
```

```verilog
`ifdef FPGA
  `GMODEL.trapvalue[13:0]=14'b0000_00000_0_0_0_11;
`else
  `GMODEL.trapvalue[13:0]=14'b0000_00000_0_0_0_01;
`endif
```
Sets the 14-bit boot-trap value consumed by `GLOBAL_INIT` (see below) via hierarchical
force-by-assignment on `` `GMODEL`` (`= MODEL.u_gmodel`, per `MODEL_ALL.v:88`). `trapvalue[0]`
selects internal-vs-external-CPU boot source; `trapvalue[1]` selects PLL-bypass/fast-reset vs.
normal 25 MHz-crystal-and-PLL boot (both branches decoded explicitly inside `GLOBAL_INIT`,
quoted in §3.3). The non-FPGA value used here, `14'b...01`, means: bit0=1 → **external CPU +
boot from internal ROM**; bit1=0 → **25 MHz crystal input, PLL enabled** (normal boot, not
fast-reset bypass).

**Cross-reference / real divergence found**: the sibling USB BFM pattern `extreg_rw.txt`
(`D:\DV\Task\USB\usb31_dev_uvm\reference\bfm_patterns\extreg_rw.txt`, read in full) sets the
*same* boot-trap value by a **different mechanism** — it comments out the `` `GMODEL.trapvalue``
assignment entirely and instead does `force `IO.iotrap[9:0]=10'b00000_0_0_0_01;` (forcing the
top-level IO trap pins directly, 10 bits not 14, a different hierarchy path and a different bit
width than `command.txt`'s `GMODEL.trapvalue[13:0]`). Both ultimately select the same
external-CPU / normal-PLL boot mode, but by forcing different signals at different points in
the hierarchy — a real, DE-authored inconsistency between two "how do I set the boot mode"
idioms that coexist in this same DUT's family of stimulus files.

```verilog
`GMODEL.GLOBAL_INIT;
$display("!!!!!!!!!!!!!  Global Ini Done    !!!!!!!!!!!!!!");
//`DRAMMODEL.DRAM_INIT;
//$display("!!!!!!!!!!!!!  DRAM Ini Done    !!!!!!!!!!!!!!");
```
Calls the real `GLOBAL_INIT` task (`MODEL_ALL.v:870+`, read in full) — waits for
`` `TOP.xtrap`` to pulse (the boot-trap latch strobe), decodes and prints the trap bits exactly
as described above, waits for both `IO.u_plltop.u_spll0`/`spll1` `mo_rdy_clk` to assert (PLL0/1
lock), then — only if booting from an *external* CPU (`trapvalue_map[0]==1`) — issues a large
block of `` `CPUWRITE1B``/`` `CPUWRITE4B`` calls to program every subsystem's clock-divider
register (`0x1000_0800..0x1000_0B0A` range: SE/SMEM/REG/CPU/ROM/VIS-ISP×8/VOUT (PCIE-ref,
USB-ref, MTX, MAC0/1, PCIE-FW)/GCON (PERI/PWM/I3C/AUD/CAN/FM) clocks), gated behind
`` `ifdef MAXIMUM_FREQ`` (max-frequency clock plan) vs. the `` `else`` "default boot frequency"
branch that only enables `GLOBAL`/`SS_VIS`/`SS_VOUT`/`SS_GCON` clock-enable registers
(`0x1000_0310/0340/0350/0360`) and leaves `SS_MEM`/`SS_CPU`/`SS_QDMA` (`0x1000_0320/0330/0370`)
commented out — i.e. **this DUT's default global-init leaves the CPU and memory subsystem
clock-enable registers untouched**, relying on their own reset-default clock state rather than
an explicit enable, a fact any test built on top of `GLOBAL_INIT` needs to know before assuming
CPU/mem clocks are "on" purely because `GLOBAL_INIT` ran.
The `DRAM_INIT` companion call is present but commented out in this file — DRAM bring-up is
explicitly skipped for this particular test.

The `` `CPUWRITE``/`` `CPUREAD`` macro family itself resolves per the compile-time BFM selector
(`MODEL_ALL.v:5395–5420`, read in full) — a 4-way `` `ifdef`` chain:
```verilog
`ifdef EJTAG      `define CPUWRITE1B `EJTAGMODEL.EJWRITE1B ...
`elsif GSIAPB     `define CPUWRITE1B `MODEL.u_gsihostmodel2apb.GSIHOSTWRITE1B ...
`elsif I2CAPB     `define CPUWRITE1B `MODEL.u_i2chostmodel2apb.HOSTWRITE1B ...
`else             `define CPUWRITE1B `MODEL.u_cpumodel.CPUWRITE1BYTE ...
```
Given `vcs.opt` line 15 defines `+define+GSIAPB` (and `I2CAPB`/`CPUMODEL_EN`/`EJTAG` are all
**not** defined for this build, §1.2), every `` `CPUWRITE``/`` `CPUREAD`` call in `command.txt`
for this actual compile resolves to the **GSI-host-to-APB bridge model**
(`MODEL.u_gsihostmodel2apb.GSIHOSTWRITE1B/2B/4B` / `GSIHOSTREAD1B/2B/4B`), *not* a real internal
CPU-core-driven access and *not* I2C/EJTAG — a concrete, build-specific fact
(`command_semantic_expectation_parser.py`'s generic `CPUWRITE`/`CPUREAD` pattern matching, §5,
has no visibility into this compile-time resolution at all).

```verilog
//=========================================================================
// TOKEN_MISS
//=========================================================================
`CPUWRITE1B(32'h0002_0100, 8'h00); //Set GREG to secure
#100; //Wait Token change out of Register Write Period
force `GREGTOP.pprot_s_gtop[2:0] = 3'b010; //Non-secure CPU
$display("!!!!!!!!!!!!!  TOKEN_MISS    !!!!!!!!!!!!!!");
```
This is a **TrustZone-style secure/non-secure access-permission test**, not a plain
register-toggle sweep. `` `GREGTOP`` = `` `GTOP.u_gregtop`` (`MODEL_ALL.v:67`); `pprot_s_gtop` is
a real chip-top port (declared `RTLCAT/TOP_ALL.v:27501`, driven at `:27637`, fanned out to at
least two sub-blocks at `:28009` and `:37263/37657/37705` — a genuine APB `PPROT`-class
protection signal, `[2:0]` = the standard AMBA `{privileged, non-secure, instruction/data}`
encoding). The sequence: (1) write `0x00` to GREG offset `0x0100` to mark the register block
"secure" (per the inline comment); (2) wait 100 time-units for the token/permission state to
settle outside the register-write window; (3) **force** `pprot_s_gtop[2:0]=3'b010` — bit[1]=1
selects **non-secure** — simulating a non-secure-world master trying to touch a
secure-marked register range. The four `` `CPUWRITE``/`` `CPUREAD`` pairs that follow
(offsets `0x0002_0000`, `0x0002_0004`, `0x0002_0008`, `0x0002_0078`) are the actual **access
attempts under this non-secure condition** — the section header says the *expected outcome* is
`TOKEN_MISS` (the security-token check should reject/flag the access), which the test observes
purely via `$display` printout of the readback value, not via a scoreboard/assertion pass/fail
verdict (this is legacy DE testbench style: human-readable log inspection, not a self-checking
UVM-style pass/fail).

```verilog
//=========================================================================
// TOKEN_HIT
//=========================================================================
force `GREGTOP.pprot_s_gtop[2:0] = 3'b000; //Secure CPU
$display("!!!!!!!!!!!!!  TOKEN_HIT    !!!!!!!!!!!!!!");
```
Mirror-image second half: forces `pprot_s_gtop[2:0]=3'b000` (secure), and re-runs the exact same
four register accesses — expected outcome this time is `TOKEN_HIT` (the same secure-marked
register range now *should* be accessible because the requesting "master" is secure). A fifth,
extra access not present in the TOKEN_MISS half is appended only to the TOKEN_HIT half:
```verilog
`CPUWRITE1B(32'h0003_0105, 8'h0F);
`CPUREAD4B (32'h0003_0105,     i);
```
— address `0x0003_0105` is in a different register page (`0x0003_xxxx` vs. `0x0002_xxxx` for
the rest of the test) and is only exercised under the secure/`TOKEN_HIT` condition, never under
non-secure/`TOKEN_MISS` — this asymmetry (one address only ever tested secure) was not resolved
against a register map/spec in this pass and is flagged as a real open question for whoever
owns the GREG register map (is `0x0003_0105` itself security-gated such that a non-secure probe
would be meaningless, or was it simply never added to the TOKEN_MISS half?).

```verilog
#(`TIMEBASE*100);
$finish;
end
```
`` `TIMEBASE`` = 20 (non-`PATTERN` branch, `MODEL_ALL.v:56–58`) — i.e. a 2000-time-unit
(`1ns/10ps` timescale ⇒ 2000 ns) settle delay before the test's own `$finish`, independent of
`wave.txt`'s outer 5,000,000-unit safety `$finish` (§3.1).

### 3.3 Register addresses touched, consolidated

| Address | Access(es) | Role per the test's own structure |
|---|---|---|
| `0x0002_0100` | 1B write, `0x00` | GREG "set to secure" control (written once, before both halves) |
| `0x0002_0000` | 1B write `0x07`, then 4B read | probed under both TOKEN_MISS and TOKEN_HIT |
| `0x0002_0004` | 2B write `0x1234`, then 4B read | probed under both |
| `0x0002_0008` | 4B write `0x8765_4321`, then 4B read | probed under both |
| `0x0002_0078` | 4B write `0x0ABC_DEF0`, then 4B read | probed under both |
| `0x0003_0105` | 1B write `0x0F`, then 4B read | probed **only** under TOKEN_HIT (asymmetry noted above) |

All five addresses are read back with a **4-byte** read (`` `CPUREAD4B``) regardless of the
write's own byte width (1B/2B/4B) — i.e. the test is deliberately checking that a narrower
write is correctly visible through a wider read (byte-lane placement / read-modify visibility),
not just round-tripping same-width accesses.

---

## 4. Cross-reference: `command.txt` (this DUT snapshot) vs. this Harness's own
   `command_inventory.csv` "scenario list"

This Harness's `.dv-workflow/command_inventory.csv` (26 rows, CMD-001..CMD-024) catalogues 24
real files under `D:/DV/Task/USB/patterns/*.txt` — `extreg_rw.txt`, `USB2_bulkin.txt`,
`USB31_SSPbulkin.txt`, etc. — as the "scenario list" for this DUT family, each tagged
`DE_ORIGINAL_UNCONVERTED` with a `HANDLER` column of `CPUWRITE/HOSTWRITE BFM tasks [+
SMEMMODEL.FILLMEM]`. Reading two of those files directly this session
(`extreg_rw.txt` in full, `USB31_SSPbulkin.txt` programmatically, see §5) confirms and refines
this catalogue:

- **These 24 files are alternative fillers for the same `command.txt` include-slot** described
  in §3.1 — each is, structurally, a `` `GMODEL.GLOBAL_INIT``-then-scenario-body file meant to be
  copied to `./command.txt` before a given regression case is compiled, exactly like the
  `regrw.txt`-derived content actually resident in this live snapshot. The inventory's own
  `SOURCE` column paths (`.../patterns/*.txt`) and this remote DUT's single literal
  `command.txt` are consistent with this: they are draws from the same slot, at different times,
  not two independent artifacts.
- **The register-security (`regrw`/TOKEN_MISS/TOKEN_HIT) content in §3 is *not* one of the 24
  catalogued rows** — it is a distinct, older (2006-vintage per its own revision header),
  chip-bring-up smoke test that predates and sits outside the USB-scenario catalogue entirely.
  A future agent reasoning from `command_inventory.csv` alone would have **no record at all**
  of this register/TrustZone-token test class existing — it is a real gap in that inventory's
  coverage, not a contradiction of anything it claims (the CSV never claimed to be exhaustive
  over every historical `command.txt` filler, but a reader treating it as "the scenario list
  this DUT ships with" should know it is USB-scenario-scoped, not all-scenario-scoped).
  **This is the deeper, corrected answer to this task's own framing** ("the complete real
  scenario list this DUT ships with, protocol/operation/expected-outcome per line"): the DUT's
  `command.txt` slot ships **both** classes of content — 24 USB-protocol BFM scenarios (per
  `command_inventory.csv`, USB2/USB3.1-SSP × con/bulkin/bulkout/interruptin/interruptout/
  isochin/isochout/susres/extreg_rw) **and** at least one non-USB chip-bring-up/security-token
  smoke test (this session's live snapshot) — and the two families are structurally similar
  (same `GLOBAL_INIT` preamble, same `` `CPUWRITE``/`` `CPUREAD`` macro family) but semantically
  distinct (protocol-scenario testing vs. secure/non-secure register-permission testing).
- **A concrete confirmed link**: `extreg_rw.txt` (CMD-001) calls
  `` `SS_VOUT_MODEL.ss_vout_init_flow;`` — the exact task this session read in full out of
  `MODEL/MODEL_ALL.v`'s `ss_vout_model` module (register map + 4-phase power-on flow: release
  gated clocks → software reset assert/release → release arbiter pause → release device pause,
  addresses `0x1200_0080..0x1200_01E0`, full table in the harness-visible source — see the
  `ss_vout_model.v` header's own claim at `MODEL_ALL.v` ~line 5377: *"Register access goes
  through the environment CPU macros... Byte-size matches the field width; regaddr must be
  aligned to the access size... every register in this flow is a single-byte field, so
  CPUWRITE1B is used throughout."*). This confirms `command_inventory.csv`'s `HANDLER` column
  for CMD-001 (`CPUWRITE/HOSTWRITE BFM tasks`) is accurate and traces to real, now-fully-read
  source, not a guess.

---

## 5. Deep-dive: running `command_semantic_expectation_parser.py` against the REAL files
   (empirical, not just reading its source)

`tools/verification_flow/command_semantic_expectation_parser.py` is the deterministic
extractor `simulation_semantic_validation_gate.py` wires in to independently re-derive each
`command.txt` line's minimum evidence/contradiction requirements (per its own header comment,
quoted in full in that file — the wiring is real and was already confirmed this session per
the task's framing). Its design assumes a `key=value` scenario DSL: a `PROTOCOLS` list
(`pcie, usb, ethernet, mipi, csi, dsi, amba, axi, apb, edp, emmc, sdio, sd, ucie`), an `OPS`
list (`read, write, bulk, iso, interrupt, reset, recovery, enumeration, link, ltssm, timeout,
error, dma, traffic, training`), and `key=value` token extraction (`port=`, `addr=`, `expect=`,
`result=`, etc.).

**Ran it against the actual DUT `command.txt` (§3) this session** (all 90 lines, saved
byte-for-byte locally and parsed with the real script, not simulated by hand):
```
total lines parsed (non-blank): 66
lines with any evidence_requirement OR contradiction_requirement: 0
```
**Every single line yields zero derived requirements.** Reasons, confirmed by inspection: (a)
none of the 14 `PROTOCOLS` keywords appear anywhere in the file (no `usb`/`pcie`/`apb`/etc.
token — the register-address style `0x0002_0000` and macro names `CPUWRITE1B`/`GREGTOP` never
match); (b) the `OPS` list's `read`/`write` require a token boundary (`(?<![a-z0-9_])read`),
so `` `CPUWRITE1B(...)`` / `` `CPUREAD4B(...)`` never match because `write`/`read` are glued to
`CPU`/`4B` with no boundary; (c) the file uses no `key=value` syntax at all, so `parse_kv`
returns an empty dict on every line. Practical consequence, confirmed directly against
`simulation_semantic_validation_gate.py`'s `cross_check_against_command_file()`: with a derived
baseline of **zero** requirements on every line, `under_reported` is trivially empty regardless
of what the agent-supplied `command_expectations` claim — the "independent cross-check" this
gate exists to provide is a **complete no-op** against this DUT's actual native `command.txt`
content class. This is a concrete, evidence-based gap for whoever owns
`simulation_semantic_validation_gate.py`/the parser: they close a real problem (agent-attested
text going unverified) only for `command.txt` files that already look like the synthetic
USB-style `protocol=X operation=Y expect=Z` DSL the parser was authored against — not for this
DUT's other, equally-real class of native testbench-style `command.txt` content.

**Ran it against two of the 24 catalogued USB scenario files for contrast** (also this session,
real script, real files):
- `extreg_rw.txt` (CMD-001, 33 lines, read in full in §3.2's cross-reference): **also 0 lines
  with any derived requirement** — it is even shorter and denser with hierarchical BFM calls
  than the DUT's native `command.txt`, so the parser fares no better here either.
- `USB31_SSPbulkin.txt` (CMD-016, 300 lines): **22 of 300 lines** produce a non-empty
  requirement — but inspecting which 22 shows the signal is largely **coincidental substring
  matching inside comments and file paths**, not genuine scenario-intent extraction: e.g. line
  330's derived `protocol=USB` requirement fires because the line is
  `` `SMEMMODEL.FILLMEM("/home/vendoruser/PROJECT/LAN063/CMD/USB/dev_bulkintrb...")`` — the token
  `USB` only appears because it's a **directory name in a file path being loaded into memory**,
  not because the line performs a USB-protocol operation the parser correctly identified as
  such. Line 34 is tagged `protocol=UNKNOWN operation=ERROR` purely because the inline comment
  happens to contain the substring "...syste" truncated near "non-PCI system" register
  programming, an artifact of the operation-keyword scan, not a real error condition in the
  test. **Conclusion, stated plainly per this task's "go deeper than the mechanical
  pattern-match" instruction**: the parser's real, empirically-verified behavior against the
  actual files this DUT and its BFM-pattern family use is shallow and frequently coincidental
  when it fires at all, and a hard zero — not "weak coverage" but **no coverage whatsoever** —
  against the DUT's own native (non-USB) `command.txt` content class. A future
  generation/debug agent should not treat a `MATCH`/clean cross-check result from this gate, on
  a `command.txt` of either style, as strong evidence that the agent's self-reported
  expectations were genuinely validated against file intent.

---

## 6. Residual gaps (not read this session)

- `runver.sh` — the actual `.gitlab-ci.yml` CI entry point (as opposed to the interactively-run
  `runver_precomp`/`runver_precomp_z` pair fully covered above) was queued but not completed:
  an earlier `git log` call left the tcsh remote relay's single command queue blocked on an
  open pager, and the `cat runver.sh` issued afterward (along with a `--status` check) was still
  pending in the background when this extraction was written up. Nothing above depends on it;
  flagged so a future pass can specifically diff `runver.sh` against `runver_precomp` (do they
  invoke `vcs.opt` identically, or does the CI path carry its own flag differences the way
  `_z` does?).
- The Arm-core naming inconsistency noted in §1.4 (`R52_include` include-dir name vs.
  `u_ca55.u_cortexa55` SDF hierarchy path) was surfaced but not resolved against a real spec/RTL
  top-level to determine which is authoritative (or whether both a R52 and an A55 genuinely
  coexist in this SoC, e.g. one as a safety/lockstep core and one as an applications core).
- The `0x0003_0105`-only-under-TOKEN_HIT asymmetry (§3.2) was surfaced but not resolved against
  a GREG register-map document (none was located/read this session) to determine whether it is
  intentional.
