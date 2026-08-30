---
name: usb-vip-lookup
description: Use when you need to find a class, sequence, interface, configuration field, or callback inside the Synopsys USB SVT VIP source tree under VIP/src and VIP/include — including when you don't know the exact class name, when a search returned hundreds of files, or when you're about to read a large VIP file to find one symbol.
---

# 在 USB SVT VIP source 裡找東西

## 為什麼需要這個

`$VIP_HOME/src/sverilog/vcs/` 有 **688 個 `.sv`**（458 個 `svt_usb_*.sv` + 230 個
`svt_*` 共用基礎建設）。`$VIP_HOME/Docs/` 沒有 HTML Class Reference。
盲目 grep 會回傳幾百個結果；整檔讀會炸掉 context。

檔名本身就是索引 —— **先解檔名，再讀檔**。

## 路徑

| 內容 | 路徑 |
|---|---|
| Source | `$VIP_HOME/src/sverilog/vcs/`（`mti/`、`ncv/` 是給其他模擬器的，不要看） |
| 介面 / pkg / defines | `$VIP_HOME/include/sverilog/` |
| 唯一 TB 範例 | `$VIP_HOME/Examples/usb_svt/tb_usb_svt_uvm_20_b2b_phy/` |

## 檔名解碼

### Sequence collection

```
svt_usb_<20模式>_<3x模式>_<主題>_[system_]virtual_sequence_collection.sv
```

`20_hs_fs_ls_30_na_transfer_...` = USB 2.0 支援 HS/FS/LS、USB 3.0 不適用、傳輸類
`20_na_30_pipe3_ss_link_initialization_...` = 2.0 不適用、3.0 走 PIPE3、SS link 初始化

模式欄位：`20_{na,hs,fs,ls,utmi,ulpi,otg}`、`30_{na,pipe3,pipe_serial,serial,ss,ssic,compliance}`、`31_{pipe4_serial_ssp,pipe4_serial_ess,ssp}`

### 一般類別

```
svt_usb_[<層>_]<名稱>_<角色後綴>.sv
```

**層**（第一段，出現次數）：`protocol`(121) `link`(99) `physical`(80) `20`(26)
`ssic`(25) `agent`(21) `device`(9) `transfer`/`packet`/`data`(各 5) `xhci`(4) `otg`(4) `hub`(4)

**角色後綴**：`callback`(62) `callbacks`(59) `sequence_collection`(45)
`configuration`(16) `exception`/`exception_list`(各 9) `status`(8) `adapter`(6)
`service`(5) `transaction`(4) `agent`(3) `sequencer`(2) `coverage_group`(2)

## 搜尋順序

1. **Glob 縮小候選**：`$VIP_HOME/src/sverilog/vcs/svt_usb_*<關鍵字>*.sv`
2. **看檔名決定讀哪個**，用上面的解碼規則
3. **Grep 定位行號**：`class |function |task |rand |constraint `
4. **Read 指定 offset/limit 讀片段**

**不要**先 `Grep -r` 整棵樹再讀 —— 那會回傳幾百筆。

## 主要進入點

| 要找什麼 | 起點檔案 |
|---|---|
| Agent 本體 | `svt_usb_agent.sv` |
| Agent 設定 | `svt_usb_agent_configuration.sv` |
| 全域設定（速度、generation、host/device 角色） | `svt_usb_configuration.sv` |
| Transaction | `svt_usb_transaction.sv`、`svt_usb_transaction_exception.sv` |
| Virtual sequencer | `svt_usb_system_virtual_sequencer.sv` |
| Virtual sequence base | `svt_usb_system_base_sequence.sv` |
| Coverage | `svt_usb_agent_20_coverage_group.sv`、`svt_usb_agent_3x_coverage_group.sv` |
| 介面實例清單 | `$VIP_HOME/include/sverilog/svt_usb_if.svi:187-218` |
| UVM 用的頂層介面 | `svt_usb_if.uvm.svi`（**不是** `.svi`） |

### 已知除錯用設定值

**Confirmed drift (2026-08-29):** `VIP_RXDET_DELAY_US=900` — 一個真實存在的
receiver-detect delay 可調參數（單位微秒），在 `svt_usb_agent_configuration`
上，用於真實 USB 2.0 chirp/attach-detection 除錯過程中（與反覆搜尋
`CHIRP ATTEMPT`、`kj pair` 的紀錄相關）。這是某次真實除錯 session 的歷史證據，
不是目前的預設值——沿用前務必依本專案自己的 Evidence Truth Rule，對照目前
VIP 版本的實際欄位/預設值重新驗證。

## 已知缺口

- **沒有 `svt_usb_system_env.sv`。** system env 的正確類別名未確認，
  要從 `$VIP_HOME/include/sverilog/svt_usb.uvm.pkg` 反查。
- **沒有 HTML Class Reference。** `$VIP_HOME/Docs/` 只有 5 份 PDF。
  PDF 讀法：`pdftotext -layout <pdf> <txt>`（本機無 `pdftoppm`，Read 工具讀不了 PDF）。
- **`examples/` 仍在陸續放入。** 目前只有 `tb_usb_svt_uvm_20_b2b_phy`（USB 2.0
  PHY-level、VIP↔VIP），與本專案（VIP host ↔ DUT device）架構不同，只能借寫法。
- **VIP config 欄位可能是 `protected`。**（**Confirmed drift (2026-08-29)：**
  真實除錯 session 對 `svt_usb_agent_configuration.svp` 搜尋 `protected` 這個字，
  發現不是每個欄位都能從 testbench 端直接讀取——用前先確認可見性，一個
  `protected` 欄位需要走 accessor method 或換一個觀察點，不能假設能直接偷看。）
  **`protected` 這個字有兩種完全不相干的意思，不要混淆：** (a) SystemVerilog
  的 member-visibility modifier（上面講的那種，單一欄位不可從外部存取）；
  (b) `` `protected``/`` `endprotected `` 這個編譯器加密指令，會把**整個檔案**
  變成不可讀（比單一欄位不可見更強），實測見於 `svt_usb_agent_configuration.svp`
  和 `svt_usb_performance_status.sv`——遇到整檔看起來像亂碼/加密內容時，先確認
  是不是這種情況，而不是以為檔案損毀。

## 常見錯誤

| 錯誤 | 後果 |
|---|---|
| 讀 `mti/` 或 `ncv/` 下的檔 | 那是給 Questa / Xcelium 的，本專案用 VCS |
| include `svt_usb_if.svi` | UVM flow 要用 `svt_usb_if.uvm.svi`（無參數版） |
| 用 `Grep -r` 全樹搜關鍵字 | 回傳數百筆。先用 Glob 靠檔名縮小 |
| 整檔 Read VIP 大檔 | 先 Grep 拿行號再讀片段 |
| 假設某個 example 目錄有內容 | examples 仍在放入中，先 `ls` 確認 |
