---
name: multi-source-evidence-consensus
description: Parallel acquisition of DUT RTL, PHY documents, programming/register documentation, and VIP references before important fixes.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Multi-Source Evidence Consensus
重要修改前必須平行取得 DUT RTL、PHY Documents、Programming Guide/Register、VIP Examples/Manual/Source/Class Reference。
所有 evidence 寫入 Blackboard；研究 Agent 不得自行完成最終裁決。

## 具體做法（2026-08-29，真實跑過一輪驗證有效，不是空泛規則）

**人數**：2-3個agent，跟改動的重要程度成正比，不是「越多越好」——這次session實際驗證用3個agent對同一份真實檔案（`usb_top_env.sv`的`connect_phase`函式）做獨立分析。

**核心規則：每個agent必須真的互相看不到對方在做什麼**，不是象徵性地平行呼叫。具體做法：每個agent的prompt都要明講「你看不到另外N個agent的發現，自己從頭讀一次真實檔案，獨立回報你自己觀察到的東西，不要假設任何先前的分析是完整或正確的」。這樣才能抓到「兩個人剛好看漏同一個地方」的風險——如果只是把同一份分析結果複製給3個agent各自簽名，那不是共識，只是背書。

**每個agent都要做完整重新枚舉，不是只確認別人的假設**：不要叫agent「確認這5個地方對不對」，要叫agent「重新完整列出這個函式裡的每一個statement」——完整重新枚舉才會意外抓到先前分析漏掉、或搞錯的地方（這次session round 7 真實驗證結果：3個agent各自完整讀完`connect_phase`後，consensus synthesis agent 直接回頭查證真實檔案，發現先前round 5/6 認定的「11個已建模 + 5個待建模＝16個」其實少算了一條——`payload_cb[p] = new(...)` (line 506) 是第三種型態`construct`，既非單純assign也非call，真實總數是17個，不是16個。這正是「完整重新枚舉」抓到「先前分析漏算」的真實案例，不是憑空舉例）。

**Blackboard寫入**：每個agent的原始發現各自獨立寫入（不要在寫入前先合併/平均化），讓分歧真的看得到，交給 `independent-evidence-synthesis` 那個階段處理，不要在證據蒐集階段就悄悄調和掉。
