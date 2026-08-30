---
name: usb-vplan
description: Use when producing or updating the verification plan for this USB project — writing the vPlan xlsx, deriving test pattern lists, mapping patterns to spec sections or constraints, or deciding which coverage items belong in the plan.
---

# USB vPlan 產出

## 輸出

檔案放 `vplan/`，xlsx 格式。必備欄位：

| 欄位 | 說明 |
|---|---|
| `testing pattern name` | 對應 `tb/tests/usb_<x>_test.sv` 的 test 名 |
| `testing pattern description` | 這個 pattern 驗什麼 |
| `spec section` | 對應的 USB 規格章節／段落 |
| `constraint items` | 用到的 SystemVerilog constraint |
| `random or directed` | constraint random / directed |

其餘欄位可自行增加。

## 硬性限制：目前沒有 USB 規格書

`$VIP_HOME/Docs/` 只有 5 份 VIP 手冊（`usb_svt_uvm_user_guide`、`usb_svt_hdl_user_guide`、
`usb_svt_uvm_getting_started`、`usb_svt_faq`、`usb_svt_performance_metrics`），
**沒有 USB 2.0 / 3.1 / 3.2 規格**。

→ `spec section` 欄位在取得規格前**填不了**。不要編造章節號。
先把該欄留空並標 `TBD-spec`，其餘欄位照填。

PDF 讀法：`pdftotext -layout <pdf> <txt>`（本機無 `pdftoppm`）。

## Pattern 從哪裡來

### 來源 1：VIP 的 sequence collection 檔名

`$VIP_HOME/src/sverilog/vcs/*sequence_collection*.sv` 的檔名直接標示測試面向。
解碼規則見 skill `usb-vip-lookup`。已存在的主題（節錄）：

- USB 2.0：`20_hs_fs_ls_30_na_transfer`、`20_hs_fs_ls_30_na_phy_layer`、
  `20_hs_30_na_fs_ls_split_transfer`、`20_ulpi_utmi_hs_fs_30_na_bulk_transfer`
- SS link：`20_na_30_pipe3_ss_link_initialization`、`..._ss_inband_reset`、
  `..._ss_low_power`、`..._ss_timeout_condition`、`20_na_30_pipe_serial_ss_link_errors`
- SS protocol：`20_na_30_ss_transfer`、`..._ss_random_protocol_layer`、
  `..._ss_random_link_layer`、`..._ss_itp`、`20_na_30_serial_ss_physical_command`
- SSP：`20_na_31_pipe4_serial_ssp_transfer`、`..._ssp_link_errors`、
  `20_na_31_pipe4_serial_ess_speed_switching`、`20_na_31_ssp_transfer`
- 合規：`30_compliance_link_layer`、`30_compliance_protocol_layer`
- 其他：`xhci`、`device_framework`、`otg`、`hub`、`ssic`

### 來源 2：現有 TB 範例的 test

`$VIP_HOME/Examples/usb_svt/tb_usb_svt_uvm_20_b2b_phy/tests/` 有 13 個 USB 2.0 PHY 層 test：
attach/bulk/detach、EOP detect（1b/2b）、suspend/resume、rx random transfers，
各含 HS/FS/LS 變體。可直接作為 USB 2.0 的 pattern 起點。

### 來源 3：DUT 配置決定哪些不用驗

從 `DUT/RTLCAT/USB_FPGA/include_ctrl/udc_DWC_usb31_params.svh` 已確認：

| 參數 | 值 | 對 vPlan 的含意 |
|---|---|---|
| `MODE` | 0 = Device | **不驗 host 功能**。VIP 當 host |
| `EN_OTG` / `EN_OTG_SS` / `EN_ADP` / `EN_BC` | 0 | **OTG / ADP / Battery Charging 全部不用驗** |
| `EN_USB30_ONLY` | 0 | SSP 有支援，要納入 |
| `SSPHY_INTERFACE_NUM_PIPE` | 2 | dual-lane，要驗 Gen1x2 / Gen2x2 |

## 速度範圍的現實限制

環境要支援 USB 2.0 + SS + SSP，但**序列層的 SS/SSP 模擬效能不可行** ——
Gen2 需 4×10GHz 時脈（半週期 12.5ps，1ps 解析度表示不出來）。

規劃 vPlan 時分三類標註：

| 類別 | 內容 | 標註 |
|---|---|---|
| USB 2.0 序列層 | 全功能覆蓋 | regression 主力 |
| SS / SSP link 層 | LTSSM 轉換、link training、in-band reset 等**極短**測項 | 可跑，但限制模擬長度 |
| SS / SSP 資料傳輸 | bulk / isoch / control transfer | **標為需 PIPE 層配置**（另一套編譯），或暫緩 |

依據見 `docs/usb-uvm-port-analysis.md` §7.3。

## 常見錯誤

| 錯誤 | 後果 |
|---|---|
| 憑印象填 `spec section` | 沒有規格書，編出來的章節號是假的 |
| 把 OTG / hub / xhci pattern 放進來 | DUT 是 device 模式、OTG 停用，驗不到 |
| 把 SS/SSP 資料傳輸排進序列層 regression | 模擬跑不完 |
| constraint 欄位與實際 `tb/` 程式碼不同步 | vPlan 失去追溯價值。constraint 必須來自實際寫出來的 SV code |
