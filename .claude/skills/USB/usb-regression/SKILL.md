---
name: usb-regression
description: Use when writing or modifying anything under scripts/ in this USB project — VCS compile and elaborate commands, filelists, run scripts, Verdi/FSDB debug setup, regression drivers, or coverage merge and reporting.
---

# 編譯 / 模擬 / Regression / Coverage

## 工具鏈

| 用途 | 工具 |
|---|---|
| Simulator | **Synopsys VCS** |
| Debug / 波形 | **Synopsys Verdi**（FSDB） |
| 執行環境 | **Linux server** |
| Coverage | `urg` |

`D:/DV/Task/USB` 是 Windows 上的 authoring 目錄，**不是執行環境**。
腳本一律寫 bash、forward slash、Linux 路徑。不要產生 `.bat`、不要用 Windows 路徑。

VIP `lib/` 只有 `linux64` / `linux` / `aarch64`，沒有 Windows。

## 執行方式：Makefile 驅動

**所有工作（compile / simulation / debug / regression / coverage）都走 Makefile。**
不要寫一堆獨立的 `.sh` 讓使用者記指令；shell 腳本只當 Makefile 呼叫的輔助。

主 Makefile 放 `scripts/Makefile`（或專案根目錄，擇一並固定）。

規劃中的 target：

| Target | 用途 |
|---|---|
| `help` | 列出所有 target 與變數。**一定要有** |
| `analyze` | 階段一：`vlogan` 分析，建 work library |
| `elab` | 階段二：`vcs` elaborate，產出 `simv` |
| `compile` | `analyze` + `elab` |
| `sim TEST=<name>` | 跑單一 test |
| `debug TEST=<name>` | 帶 `+fsdb` 跑，結束後開 Verdi |
| `verdi TEST=<name>` | 只開 Verdi 看既有 FSDB |
| `regress` | 全部 test（LSF 派送） |
| `cov` | urg merge + report |
| `clean` / `distclean` | 清除產物 |

**Confirmed drift (2026-08-29):** the table above is the *planned* target
set. A real sibling project's actual command-approval history shows a
strictly larger, already-in-use interface:
`make compile FLOW=fourstep DUT_ROOT_PATH=...`, `make compile NTB_COMPAT=`,
`make elab PARTCOMP_EN=`, `make -n regress SUITE=list`,
`make regress SUITE=sanity FLOW=fourstep DUT_ROOT_PATH=...`,
`make sim PATTERN=smoke FLOW=fourstep DUT_ROOT_PATH=...`,
`make list_patterns`, `make list_patterns SUITE=list`, `make pattern_pool`,
`make ADD_PAT PAT_NAME=axi_selftest.txt PAT_DIR=.`, `make lsf_queues`,
`make lsf_report SUITE=basic`, `make analyze_uvm DUT_ROOT_PATH=...`,
`make cov_hier.cfg`, `make check DUT_ROOT_PATH=...`. In particular,
**`FLOW=fourstep` was the mode actually used in practice**, not merely one
of two documented options — treat it as the de-facto default to scaffold
for, not a secondary path.

變數慣例：`TEST=` 指定 test、`SEED=` 指定 random seed、`WAVE=1` 開 FSDB、
`IF=serial\|pipe` 選介面配置（見下）。

## 兩階段 VCS 流程（必須）

**不用單階段 `vcs -f`，改用 `vlogan` → `vcs` 兩階段。**
整顆 SoC 很大，兩階段讓 RTL 分析結果可重用，只改 TB 時不必重新分析 DUT。

```bash
# 階段一：分析（產生 work library，預設 ./AN.DB）
vlogan -full64 -sverilog -kdb -nc \
       -timescale=1ps/1ps \
       -f scripts/usb.f \
       -l $(SIMDIR)/vlogan.log

# 階段二：elaborate
vcs -full64 -sverilog -kdb -lca \
    -debug_access+all \
    -partcomp -fastpartcomp=j1 -j4 \
    -Xcheck_p1800_2009=char +error+10000 \
    $(TOP) \
    -o $(SIMDIR)/simv \
    -l $(SIMDIR)/vcs.log

# 階段三：執行
$(SIMDIR)/simv +UVM_TESTNAME=$(TEST) +ntb_random_seed=$(SEED) \
    -l $(SIMDIR)/$(TEST)/sim.log
```

Makefile 裡把 `analyze` 與 `elab` 拆成獨立 target，`elab` 依賴 `analyze` 的
stamp 檔，避免每次都重跑 `vlogan`。

分階段的 log 分開：`vlogan.log` / `vcs.log` / `sim.log`。
沿用 DUT 既有慣例另抽出 warning 與 error：

```make
	grep Warning $(SIMDIR)/vcs.log > $(SIMDIR)/vcs_w.log
	grep Error   $(SIMDIR)/vcs.log > $(SIMDIR)/vcs_e.log
```

## KDB（Verdi 用，必須）

**`-kdb` 兩個階段都要加。** 只在 `vcs` 加而 `vlogan` 沒加，Verdi 會看不到
RTL 的完整設計資訊（原始碼追蹤、訊號 trace 會殘缺）。

| 階段 | 必要旗標 |
|---|---|
| `vlogan` | `-kdb` |
| `vcs` | `-kdb -lca -debug_access+all` |

`-kdb` 產生的資料庫預設在 `simv.daidir/kdb`（或 `AN.DB/kdb`），
Verdi 用 `-dbdir` 指過去。

`-lca` 是 `-kdb` 的前置需求，不能省。

**本專案只支援 VCS**，所以模擬器**硬寫在 Makefile 裡，不要做成變數**。
VIP 範例的 `USE_SIMULATOR=<simulator>` 那套多模擬器抽象**不要沿用**。

### VIP 範例的 Makefile 慣例

`$VIP_HOME/Examples/usb_svt/tb_usb_svt_uvm_basic_sys/Makefile`（143KB，`dw_vip_setup` 自動產生）：

- `export SHELL = /bin/csh -f`
- 必要變數 `USE_SIMULATOR` 與 `DESIGNWARE_HOME`，未設就 `$(error)` 中止
- 每個 test 一個 target（`basic_ss_serial`、`basic_additional_20_enumeration`…）
- 另有 `all`、`clean`、`help`

本專案不照抄那 143KB。值得沿用的只有兩點：
**「必要變數未設就 `$(error)` 即早中止」**（本專案只剩 `DESIGNWARE_HOME`）
與**「`help` target」**。

## 執行前提

```bash
setenv DESIGNWARE_HOME <VIP 安裝路徑>    # VIP 範例的 Makefile/run script 依賴此變數
```

VIP / SVT 版本查 `<design_dir>/.dw_vip.cfg`。
**模擬器版本相容性查 `$DESIGNWARE_HOME/vip/svt/usb_svt/<ver>/doc/usb_svt_relnotes.pdf`** ——
本專案 VIP 是 svt W-2024.09，`DUT/runver_precomp` 註解提到 VCS V-2023.12-SP2，
**這組搭配尚未驗證**（未決事項 A3）。
**Confirmed drift (2026-08-29):** VIP version drift mid-project is a
*recurring, expected* condition, not a one-time anomaly — a later real
command history references
`/eda/synopsys/DesignWare/iCatchDW/vip/svt/usb_svt/W-2025.03`, i.e. the
actual VIP install advanced to **W-2025.03** at some point after this A3
note was written, and the skill's own recorded pairing never caught up.
Always re-check the live `$VIP_HOME` path's actual version string before
trusting a previously-recorded VCS×VIP pairing.

## VIP 範例的建置慣例

`$VIP_HOME/Examples/usb_svt/tb_usb_svt_uvm_basic_sys/` 是最貼近本專案的參考（host↔device system-level）。

| 檔案 | 內容 |
|---|---|
| `sim_build_options` | `+define+UVM_DISABLE_AUTO_ITEM_RECORDING +define+UVM_PACKER_MAX_BYTES=24000 +define+SVT_USB_INCLUDE_SSIC` |
| `vcs_build_options` | `-unit_timescale=1ps/1ps` |
| `sim_run_options` | `+UVM_TESTNAME=$scenario` |
| `vcs_run_options` | `+ntb_solver_array_size_warn=100000` |
| `modellist` | `mphy_mport_lm_agent_svt mphy_mport_lm_monitor_svt mphy_mport_lm_txrx_svt mphy_agent_svt mphy_txrx_svt mphy_monitor_svt usb_agent_svt` |
| `pc.optcfg` | `partition package uvm_pkg; svt_uvm_pkg; svt_usb_uvm_pkg;` |
| `prescript` | 依 test 選定的介面，把 `top.<interface>.sv` 複製成 `test_top.sv` |
| `hdl_interconnect/` | **各介面的 DUT 接線模板**（`usb_ss_serial_dut.v`、`usb_ss_pipe3_dut.v`、`usb_20_serial_dut.v`…，各含 `_sv_wrapper.sv`） |

`b2b_phy` 範例的 `sim_build_options` 另有 `+define+SVT`、
`+define+SVT_USB_INCLUDE_USER_DEFINES`（搭配 `svt_usb_user_defines.svi`）。

`top.<interface>.sv` 的多版本機制值得沿用 —— 本專案要同時支援序列層與 PIPE 層
兩套配置（見 `docs/usb-uvm-port-analysis.md` §7.6），正好對應
`top.usb_20_serial.sv` / `top.usb_ss_serial.sv` / `top.usb_ss_pipe3.sv` 的作法。

## DUT 側現況

`DUT/runver_precomp` 顯示既有的 VCS 呼叫方式（**單階段 `-R`，本專案不沿用**）：

```
vcs -lsfint -VERSION V-2023.12-SP2 \
    -R -j4 -partcomp -fastpartcomp=j1 -sverilog \
    -debug_access+all -kdb -lca -full64 \
    +define+MISC_NOCHECK -f vcs.opt -l vcs.log \
    -Xcheck_p1800_2009=char +error+10000
grep Warning vcs.log > vcs_w.log
grep Error   vcs.log > vcs_e.log
```

可沿用的部分：`-lsfint`（**LSF** 平台）、`-partcomp -fastpartcomp=j1 -j4`、
`-Xcheck_p1800_2009=char +error+10000`、warning/error 抽取。
不沿用的：`-R`（單階段編譯即執行）。

**`DUT/vcs.opt` 目前不可用**：引用 `./ENV`、`./MODEL`、`./MACRO`、`./DUMMY_TOP`
四個目錄，皆不在 `DUT/` 下（未決事項 A1）。IP-level 要另寫 `scripts/usb.f`。

## Verdi / FSDB

**波形只支援 FSDB。** 不要產生 VCD、不要用 `$vcdpluson` / VPD。
VIP 範例的 `WAVES_VCD` / `WAVES`（VPD）分支**不要沿用**，只保留 FSDB 那條路徑。

VCS 端已有 `-kdb -debug_access+all -lca`，不需再加。TB 端加 dump：

```systemverilog
initial begin
  if ($test$plusargs("fsdb")) begin
    $fsdbDumpfile("sim.fsdb");
    $fsdbDumpvars(0, sys063, "+all");
    $fsdbDumpMDA();      // 多維陣列
    $fsdbDumpSVA();      // assertion
  end
end
```

FSDB 對整顆 SoC 很大，**預設關閉**，由 `make debug` / `WAVE=1` 加 `+fsdb` 開。

Verdi 開啟包成 target：
```make
verdi:
	verdi -dbdir $(SIMDIR)/simv.daidir -ssf $(SIMDIR)/$(TEST)/sim.fsdb &
```

## 除錯重跑慣例（usbrun.sh / RUNTAG）

**Confirmed drift (2026-08-29):** real debug sessions used a second driver
script alongside `make`: `sim/scripts/usbrun.sh`, launched
`setsid nohup env PAT=<pattern> SPD=usb20 PHYSIM=fast WAVE=0|1 PARTCOMP=0|1
RUNTAG=<tag> sh scripts/usbrun.sh > /tmp/usbrun_*.out 2>&1 &`. Real `RUNTAG`
values observed: `arb1`, `enum4`..`enum15`, `enum_rerun`, `hs1`, `hs2`,
`ssv1`, `trace1`, `all1` — **one tag per hypothesis/attempt, never
overwriting a prior run's log or FSDB.** The same discipline showed up at
the artifact level: a superseded FSDB gets renamed, not deleted or
overwritten (`mv -f usb20_enumeration_1.fsdb stale_1557.fsdb`), living in a
separate `fsdb/` dir. Generalizes directly to every protocol's regression
debugging: never let a rerun silently clobber the previous attempt's
evidence.

## 長跑 LSF job 的即時健康檢查（真實作法）

**Confirmed drift (2026-08-29):** a real debug session polled a running LSF
job's log incrementally rather than waiting for completion — e.g.
`grep -c 'RUN TRUNCATED' <log>` / `grep '\[alive\]' <log> | tail -1` — and
used the result to decide whether to `bkill` the job early. Real log-tag
vocabulary observed: `[stage]`, `[alive]`, `[scale]`, `[utmi]`, `[pattern]`,
`[launcher] port`, `GLOBAL_INIT done`, `RUN TRUNCATED`, `SvtTestEpilog`,
`FINAL_CHECK`, `CNST-CIF`, `VERDICT`. This is the real, working
implementation of CLAUDE.md's "terminate at first relevant failure" +
named-bring-up-stages ideas — cite these concrete markers and the cheap
incremental-tail-then-targeted-`bkill` technique as the real operational
form of that abstract rule. (See also
`tools/verification_flow/lsf_per_job_monitor_gate.py` for this harness's own
LSF-job monitoring contract — checked in this pass: it keys off UVM_ERROR/
UVM_FATAL markers only, no conflict with the log-tag vocabulary above.)

**Confirmed drift (2026-08-29):** a real constraint-solver failure triage
recipe: `grep -n "Solver failed\|inconsistent constraint\|Error-\|RNDF" sim.log`,
then dump ±N lines around the first hit to see which constraint block is
actually inconsistent. One more real log tag not previously captured above:
`CNST-RONV` (appears alongside the already-captured `CNST-CIF`).

**Confirmed drift (2026-08-29):** a "decoy" same-named file trap — a real
session found an identically-named file (e.g. `wave.txt`) present at BOTH
the true `DUT_ROOT_PATH` and a second, unexpected path, and had to
md5sum+timestamp-compare both before trusting either. Generalizes the
`remote-linux-execution-bridge/SKILL.md` three-way-diff recipe: check
whether a same-named file exists somewhere unexpected too, not only
compare a fixed LOCAL/REMOTE pair.

## Timescale（未定，影響很大）

USB SS Gen2 序列層需 4×10GHz 時脈（`$VIP_HOME/include/sverilog/svt_usb_ss_serial_if.svi:181-184`），
半週期 **12.5ps**。

| 設定 | 可行性 |
|---|---|
| `1ns/10ps`（`runver_precomp` 註解的範例） | **完全不可行** |
| `1ps/1ps`（VIP 範例用的） | USB 2.0 可以；SS Gen2 表示不出 12.5ps，時脈會失真 |
| `1ps/100fs` 或更細 | 理論可行，但 DUT 加密模型（`SE_*_enc.v.e`、`M31SOCPLL*.vp.vcs`、`CL12812M8RIP_r103.vp`）能否接受**需實測** |

只跑 USB 2.0 時沿用 `1ps/1ps`。

## Coverage

```make
cov:
	urg -dir $(SIMDIR)/*/simv.vdb -format both -report $(SIMDIR)/urgReport
```

各 test 開自己的子目錄（`sim/<test>/`），避免 vdb 與 fsdb 互相覆蓋。

## 常見錯誤

| 錯誤 | 後果 |
|---|---|
| 用單階段 `vcs -f ... -R` | 本專案要求兩階段 `vlogan` → `vcs` |
| `-kdb` 只加在 `vcs` 沒加在 `vlogan` | Verdi 的設計資訊殘缺，訊號 trace 不完整 |
| 省略 `-lca` | `-kdb` 需要它 |
| 把模擬器做成變數（`USE_SIMULATOR=`） | 只支援 VCS，硬寫即可。（**Confirmed drift (2026-08-29):** 這條只對本專案*自己的* Makefile 成立，不適用於呼叫 VIP vendor 自帶範例 Makefile 時它自己既有的 `USE_SIMULATOR=` 慣例——真實指令紀錄顯示曾實際跑過 `make USE_SIMULATOR=vcs base_test`，但對象是 `$VIP_HOME/Examples/.../Makefile`，不是本專案 Makefile；那個慣例不在本專案控制範圍內，不是同一種違規。） |
| 產生 VCD / VPD 波形 | 只支援 FSDB |
| 寫成一堆獨立 `.sh` 給人記指令 | 執行方式定為 Makefile 驅動 |
| Makefile 沒有 `help` target | 沒人知道有哪些 target 和變數 |
| 必要變數沒設卻讓 make 繼續跑 | 錯誤訊息會出現在很後面。用 `$(error)` 即早中止 |
| 產生 `.bat` 或 Windows 路徑 | 執行環境是 Linux server |
| 直接用 `DUT/vcs.opt` | 缺 4 個目錄，elaborate 失敗 |
| 沿用 `-override_timescale=1ns/10ps` | SS 序列層完全無法建模 |
| 預設開 FSDB dump | 整顆 SoC 的波形檔會爆掉磁碟 |
| 假設 VCS 2023.12 能跑 VIP W-2024.09 | 未驗證。先查 `usb_svt_relnotes.pdf` |
| 忘了設 `$DESIGNWARE_HOME` | VIP 範例的 run script 起不來 |
