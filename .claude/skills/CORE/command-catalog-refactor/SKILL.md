---
name: command-catalog-refactor
description: 掃描並分析專案內所有 command.txt 的驗證內容，依驗證層級與驗證項目建立正確目錄分類，將 command.txt 分配/移動到適合位置，修正引用，最後清除確認過時且無引用的舊目錄；全程保留 dry-run、mapping manifest 與 audit evidence。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Command Catalog Refactor

## 目的
將歷史累積、散落、命名不一致的 `command.txt` 整理成可維護、可追蹤、可由 DV Agent Harness 自動路由的 Verification Command Catalog。

本 Skill 不依賴原目錄名稱做真相判斷；分類以 `command.txt` 的實際驗證內容、對應 DUT/VIP/test/sequence/checker/coverage evidence 為主。

## 強制流程

1. **Inventory**：掃描 project 內全部 `command.txt`，記錄原始 path、Git state、引用者、內容 hash。
2. **Content Analysis**：解析 command/test/pattern/VIP sequence/expected result/negative condition/coverage intent。
3. **Verification Level Classification**：判定驗證層級。
4. **Verification Item Classification**：判定主要驗證項目與次分類。
5. **Confidence + Evidence**：對每個分類附 evidence、confidence；不確定不得強搬。
6. **Canonical Directory Plan**：建立新的正規目錄樹與 mapping plan。
7. **Dry Run**：先輸出 move/rename/reference-update/delete plan，不直接 destructive cleanup。
8. **Move / Rename**：以唯一 canonical destination 搬移 command；重名時依 scenario/feature 加 suffix，不可覆蓋。
9. **Reference Repair**：修正 regression list、script、README、vPlan、manifest、CI、command index 等引用。
10. **Post-Move Validation**：重新掃描，確認所有 command 可被找到、無 broken references、無 duplicate ID/path collision。
11. **Obsolete Directory Cleanup**：只刪除空目錄，或已證明沒有 command、沒有有效 artifact、沒有任何 reference 的過時目錄。
12. **Regression / Audit**：執行適用 pytest/command parser/regression discovery 測試，輸出 final catalog manifest 與 audit report。

## 驗證層級分類

Canonical level：

- `00_PLATFORM_INFRA`
  - Harness/tooling/parser/remote/CI/LSF/infrastructure 驗證。
- `10_IP_BLOCK`
  - 單一 IP / Block / controller / PHY unit 驗證。
- `20_SUBSYSTEM`
  - PCIe/USB/Ethernet/MIPI/eMMC/SD/UCIe 等 subsystem environment 驗證。
- `30_MULTI_SUBSYSTEM`
  - 兩個以上 subsystem 的 dependency / concurrency / data-flow 驗證。
- `40_SYSTEM_LEVEL_SOC`
  - Full-SoC / boot / OS / end-to-end / real-world scenario。
- `90_UNCLASSIFIED_REVIEW`
  - Evidence 不足或 mixed purpose，必須人工/Expert Review 後再移動。

## 驗證項目分類

每個 level 下使用以下 canonical category（只建立實際需要的目錄）：

- `01_BUILD_COMPILE`
- `02_RESET_INIT`
- `03_BRINGUP_LINK_TRAINING`
- `04_ENUM_DISCOVERY_CONFIGURATION`
- `05_BASIC_FUNCTIONAL`
- `06_DATA_TRANSFER_TRAFFIC`
- `07_PROTOCOL_FEATURE`
- `08_CONCURRENCY_STRESS`
- `09_ERROR_INJECTION_NEGATIVE`
- `10_RECOVERY_ROBUSTNESS`
- `11_POWER_CLOCK_RESET`
- `12_PERFORMANCE_QOS`
- `13_SECURITY_PROTECTION`
- `14_CHECKER_SCOREBOARD_ASSERTION`
- `15_COVERAGE_CLOSURE`
- `16_REGRESSION_SOAK`
- `17_INTEROP_COMPATIBILITY`
- `18_SYSTEM_SCENARIO`
- `19_DEBUG_DIAGNOSTIC`
- `20_QUALIFICATION_SIGNOFF`
- `90_MISC_REVIEW`

## Protocol / Domain Subdirectory

若可確認 protocol/domain，在 category 下再分：

`PCIe / USB / Ethernet / MIPI_CSI2 / MIPI_DSI / AMBA4 / eDP / eMMC / SD_SDIO / UCIe / Generic / New_Interface`

例如：

```text
verification_commands/
  20_SUBSYSTEM/
    03_BRINGUP_LINK_TRAINING/
      PCIe/
        pcie_gen4_x4_link_train/
          command.txt
    09_ERROR_INJECTION_NEGATIVE/
      USB/
        usb3_bad_crc_recovery/
          command.txt
```

## command.txt 分析規則

至少擷取：

- `COMMAND_ID`
- 原始 path
- command body / executable invocation
- Pattern/Test name
- DUT scope / instance
- Protocol / interface
- VIP role / topology（若有）
- Positive / Negative / Error Injection
- Expected result / checker
- Coverage purpose
- Regression group
- Dependencies / prerequisites
- Verification level
- Primary category
- Secondary tags
- Evidence
- Confidence
- Proposed destination

不得只根據 filename 或 parent directory 分類。

## 分類優先規則

若一個 command 同時涵蓋多個項目：

1. 以「主要驗證目的 / signoff intent」為 Primary Category。
2. 其他用途保留為 `secondary_tags`，不要複製多份 `command.txt`。
3. 若主要目的無法由內容/evidence 判定，放 `90_UNCLASSIFIED_REVIEW`。
4. System-Level command 不因內含 PCIe/USB traffic 就降級到 Subsystem。
5. Error injection command 即使最後檢查 recovery，Primary 通常為 `09_ERROR_INJECTION_NEGATIVE`，Recovery 作 secondary tag；若主要目的明確是 recovery state closure，則放 `10_RECOVERY_ROBUSTNESS`。

## 去重規則

計算 normalized content hash + semantic identity：

`Protocol + Scope + Test/Pattern + Primary Intent + Key Args`

結果：

- 完全相同：保留 canonical 一份，其餘標 `DUPLICATE_EXACT`。
- 同功能不同參數：不可刪除，標 `VARIANT`。
- 同名不同內容：必須重新命名，不得覆蓋。

## 舊目錄刪除鐵則

只能刪除符合全部條件的目錄：

- 搬移後沒有有效 `command.txt`；
- 不含仍被使用的 sequence/script/config/data；
- repository search 無任何有效 reference；
- 不在 active regression/testlist/vPlan/CI manifest；
- Git evidence 不顯示為仍在使用的 canonical entry；
- dry-run manifest 已列入 `safe_to_delete=true`。

不確定時標 `RETAIN_REVIEW`，禁止刪除。

## 必須產生的 artifacts

```text
.dv-harness/command-catalog/
  inventory.json
  classification.json
  move_plan.json
  reference_updates.json
  duplicate_report.json
  obsolete_directory_report.json
  final_catalog.json
  audit_report.md
```

`move_plan.json` 至少包含：

```json
{
  "source": "old/path/command.txt",
  "destination": "verification_commands/20_SUBSYSTEM/.../command.txt",
  "level": "20_SUBSYSTEM",
  "category": "03_BRINGUP_LINK_TRAINING",
  "protocol": "PCIe",
  "reason": "LTSSM/link bring-up is primary verification intent",
  "evidence": [],
  "confidence": "HIGH",
  "references_to_update": [],
  "action": "MOVE"
}
```

## Safety / Git

- 預設先 `--dry-run`。
- 不得覆蓋 user unrelated changes。
- 不得 `git reset --hard` / `git clean -f`。
- 刪目錄前輸出 explicit cleanup list。
- Move 後保留 old→new mapping，方便 Git review。
- 若 project 使用 Git，優先使用可保留 rename history 的 move 操作。

## 最終驗證

至少確認：

- 所有原始有效 command 均有 final disposition。
- 所有 final command path 唯一。
- command parser / catalog loader 可找到全部 commands。
- regression/testlist 引用沒有 broken path。
- vPlan → command trace 仍成立。
- duplicate report 已 disposition。
- obsolete directory 只有在 evidence 足夠時才刪除。
- pytest / project catalog tests PASS。

## 回報格式

輸出 Summary：

- Commands scanned
- Commands moved
- Commands renamed
- Exact duplicates removed
- Variants retained
- Unclassified/review required
- References updated
- Obsolete directories deleted
- Directories retained for review
- Broken references before/after
- Final pytest/catalog validation
