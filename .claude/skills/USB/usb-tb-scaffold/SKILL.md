---
name: usb-tb-scaffold
description: Use when creating or modifying files under tb/ in this USB project — adding a UVM agent, env, scoreboard, sequence, or test; wiring the TB top to the DUT; connecting a VIP interface to lan063 ports; or deciding where a new testbench file belongs.
---

# USB TB 檔案配置與接線慣例

## 目錄與命名

| 目錄 | 放什麼 | 檔名 |
|---|---|---|
| `tb/top/` | TB top、DUT 實例化、介面連接、config_db 設定 | `sys063.sv`、`sys063_connect.svh` |
| `tb/env/` | env、scoreboard、coverage、config object、virtual sequencer | `usb_top_env.sv`、`usb_<x>_scoreboard.sv`、`usb_coverage_collector.sv`、`usb_virtual_sequencer.sv`、`usb_reg_map.sv` |
| `tb/agents/<name>_agent/` | 自建 agent | `<name>_if.sv` `<name>_config.sv` `<name>_driver.sv` `<name>_monitor.sv` `<name>_agent.sv` |
| `tb/seq/` | virtual sequence | `usb_<x>_vseq.sv` |
| `tb/tests/` | uvm_test | `usb_<x>_test.sv` |

VIP 範例用 `ts.<name>.sv` 命名 test，**本專案不沿用**，改 `usb_<x>_test.sv`。

自建 agent 目前規劃兩個：`clk_rst_agent`（`xtali` / `xprstn` / `bypasspll` /
PLL force）、`sideband_agent`（`xtestmode` / `xtrap`）。

## TB top 的階層

RTL 裡**沒有** `sys063`。chip top 是 `lan063`，在 TB top 實例化為 `u_lan063`：

```systemverilog
module sys063;
  lan063 u_lan063 ( ... );
```

所有既有文件與 force 路徑都假設這個名字，**不要改**。

## 接線慣例

### USB 2.0 dp/dm — 用 `tran`

VIP 的 `dp`/`dm`/`vbus` 宣告為 `wor`（`$VIP_HOME/include/sverilog/svt_usb_20_serial_if_signals.svi:35-44`），
DUT pad 是 `inout wire`。雙向，必須用 `tran` 原語，不能 `assign`：

```systemverilog
tran u0_dp ( sys063.u_lan063.xusb0_dp,    usb0_if.usb_20_serial_if.dp   );
tran u0_dm ( sys063.u_lan063.xusb0_dm,    usb0_if.usb_20_serial_if.dm   );
tran u0_vb ( sys063.u_lan063.xusb0_vbus0, usb0_if.usb_20_serial_if.vbus );
```

範例出處：`$VIP_HOME/Examples/usb_svt/tb_usb_svt_uvm_20_b2b_phy/top_test.sv:513-514`

### USB SS — 方向明確處用 `assign`

```systemverilog
// DUT tx (output) → VIP rx
assign usb0_if.usb_ss_serial_if.ssrxp = sys063.u_lan063.xusb0_tx_p[LANE];
assign usb0_if.usb_ss_serial_if.ssrxm = sys063.u_lan063.xusb0_tx_m[LANE];
// VIP tx → DUT rx（DUT 端是 inout）
tran u0_rxp ( sys063.u_lan063.xusb0_rx_p[LANE], usb0_if.usb_ss_serial_if.sstxp );
tran u0_rxm ( sys063.u_lan063.xusb0_rx_m[LANE], usb0_if.usb_ss_serial_if.sstxm );
```

兩條 lane **都是 USB**（lan063 port 註解寫 "for eDP" 是封裝層共用，RTL 無 mux）。
lane0 → `usb_ss_serial_if`，lane1 → `usb_ss_serial_lane1_if`。

### Sideband — `inout`，要用 `reg` 驅動

`xtestmode` / `xprstn`（**低有效**）/ `xtrap` / `xtali` 都是 `inout`。
不能 `assign` 死值，要用 `reg` + 時序驅動，或搭配 pullup/pulldown。

### AXI / APB — force，不是接線

force 目標用 lan063 層的 wire（比 module port 乾淨）：

```systemverilog
force sys063.u_lan063.ss_cpu_m_awvalid = axi_if.awvalid;
```

**只 force CPU 的 output**（`aw*` `w*` `ar*` `bready` `rready`）。
CPU 的 input（`awready` `wready` `b*` `r*`）只觀測，force 了會打壞握手。

USB 暫存器走 **APB**（`ss_cpu_m_p*`），AXI 是 DMA 用。兩條都要掛。

### 介面 handle 傳遞

```systemverilog
initial begin
  uvm_config_db#(virtual svt_usb_if)::set(uvm_root::get(), "uvm_test_top.env",
                                          "usb0_if", usb0_if);
end
```

範例出處：`top_test.sv:393-395`

## 尚未解決、會改變接線的事

**A2 — SS PHY 是否真的產生序列波形尚未證實。** `SS_VOUT_USB_PHY.v` 內是
PCS/UPCS 數位邏輯，類比 SerDes 模型是否存在並驅動 pad 未知。
**若沒有，序列層接法整套不成立，要改走 PIPE 層**（另一套編譯配置，
不是 config_db 開關）。詳見 `docs/usb-uvm-port-analysis.md` §6、§9.1。

在 A2 有結論前，`tb/` 下先只寫不受影響的部分：agent 介面定義、
config object、目錄骨架。

## 除錯時發現的暫存器欄位（歷史證據，需重新驗證）

**Confirmed drift (2026-08-29):** real debug sessions on a sibling project
found these chirp/disconnect-timing register fields in a generated
`usb_cfg_port0.rpt`: `tdchbit`, `tdchse0`, `twtdch`, `tuch_hs`, `tfilt`,
plus a `GCTL[5:4]` global-control field watched via
`grep 'GCTL.5:4. changed to'`. **These are historical facts observed once
against one DUT revision's config report — per this project's own Evidence
Truth Rule, re-derive the current field names/values from the *current*
`usb_cfg_port0.rpt` and current RTL before relying on them; do not assume
they still apply verbatim.**

## 常見錯誤

| 錯誤 | 後果 |
|---|---|
| 用 `assign` 接 dp/dm | VIP 端是 `wor` 且雙向，`assign` 會單向鎖死 |
| force CPU 的 input 訊號 | 打壞 AXI/APB 握手，DUT 永遠等不到 ready |
| 只掛 AXI VIP | USB 暫存器走 APB，不設定就什麼都不會動 |
| 忘了 `awuser[8:0]` / `aruser[8:0]` | `USER[8:4]`=RBC、`[3:0]`=TZC，值錯會被 fabric 擋掉 |
| 用 `u_usbtop.xxx` 當階層路徑 | 現況是 `u_usbtop[1:0]` 陣列，要帶 index |
| 寫 `xprst` | 實際是 `xprstn`，低有效 |
