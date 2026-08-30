---
name: independent-evidence-synthesis
description: Independent synthesis of multi-source evidence into root-cause candidates, counter-evidence, conflicts, solution, impact and verification plan.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Independent Evidence Synthesis
Synthesis Agent 必須與 evidence-acquisition task 分離。
輸出 Supporting Evidence / Counter Evidence / Missing Evidence / Conflicts / Root Cause Ranking / Solution / Change Impact / Verification Plan。
Evidence 不完整時不得進 Implement。

## 具體做法（2026-08-29，真實跑過一輪驗證有效，不是空泛規則）

**分歧處理的鐵則：遇到多個獨立來源意見不一致時，絕不能用「投票」或「取平均」解決**——正確做法是 synthesis agent 自己立刻回頭去看真實來源（RTL/VIP/文件本身），用直接觀察裁定誰對，而不是「兩個人這樣說、一個人那樣說，所以採多數」。這次session的真實案例：3份獨立報告在某個statement數量上有分歧，synthesis agent 沒有用多數決，而是自己重新讀了一次真實檔案，用實際證據裁定正確答案。

**輸出必須是「自成一體」的最終規格，不能只是把三份原始報告貼在一起**：下游的實作agent不會、也不應該去讀三份原始的獨立報告——synthesis 的產出必須是一份完整、明確、可以直接照做的規格，把所有分歧都已經裁定完畢、原始報告的存在對實作階段是透明的。如果實作階段還需要回頭看原始報告才能理解要做什麼，代表 synthesis 沒有做完整。

**流程銜接**：Evidence Consensus（平行獨立蒐證）→ Independent Synthesis（本skill，裁定分歧+產出最終規格）→ Implement（照規格實作，遇到規格與真實程式碼對不上要停下回報，不可自行即興改規格）→ 獨立驗證（另一個agent重新核對程式碼是否真的符合規格、重新對真實來源抽查、跑完整測試套件+self-audit）。四個階段各自獨立，不可省略或合併其中任何一段。
