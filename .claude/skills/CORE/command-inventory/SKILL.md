---
name: command-inventory
description: Treats existing DE command.txt/scenario files as reusable capability baseline and backward-compatibility reference, not verification scope.
allowed-tools: Read Grep Glob PowerShell
---
# Existing Command Capability Inventory

DE existing command.txt is:
- reference
- seed
- reusable capability baseline
- backward-compatibility contract

It is NOT the source of truth for verification completeness.

Discover:
command syntax, parameters, parser/handler, branch_fw dispatch, VIP mapping, user scope, examples.

Produce `.dv-workflow/command_inventory.csv`:
COMMAND_ID,PROTOCOL,COMMAND,PARAMETERS,SOURCE,USER_SCOPE,HANDLER,VIP_SEQUENCE,STATUS,CONFIDENCE

USER_SCOPE:
DE_DV / DV_ONLY / DE_ONLY if truly required.

## Change-Impact Check（每次檔案修改前後都要做）

任何原始碼/環境/generator schema 修改前，先用 `.dv-workflow/command_inventory.csv` 檢查該修改是否影響到
現有任一 command.txt/scenario（因為 command.txt 是 backward-compatibility contract，不是可隨意破壞的東西）。
修改後，針對被影響到的 COMMAND_ID 清單重新比對/重新跑對應 testing case，確認沒有 regression；
若清單顯示「零影響」，也要在報告中明講是根據哪些 COMMAND_ID/HANDLER 交叉比對得出的，不能只是省略未講。
