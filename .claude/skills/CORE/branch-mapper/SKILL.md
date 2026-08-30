---
name: branch-mapper
description: Maps DUT-side branch_a ports through branch_fw to VIP-side branch_b ports with N:M relationships, direction and configuration.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Branch Mapper

Inputs:
dut_ports.csv
vip_topology.csv
vip_binding.csv

Map:
branch_a* <-> branch_fw <-> branch_b*

Record:
MAP_ID,A_BRANCH,B_BRANCH,DIRECTION,PROTOCOL,CONFIG,STATUS,SOURCE,CONFIDENCE

Allow:
1:1
1:M
N:1
N:M

Do not silently merge independent ports.


# AMBA M×N Mapping
Map 不固定 A1→B1。必須表示 Master→Slave/resource、address/routing condition、arbitration scope、concurrency policy。
不相關 resource 不得互相 blocking。

APB/AXI transaction 若可能在 block、branch_a0、branch_a1（及其他 branch_a*）同時對同一 shared resource/slave
發起存取，必須明確表示該 shared resource 的 arbitration policy（e.g. round-robin/priority/QoS，依 RTL 仲裁器
evidence 而非假設），並記錄哪些 branch_a* 共用同一個 arbitration domain。不相關 resource 之間仍維持可平行、
不得因為模型化了某個 shared-resource 仲裁就連帶把不相關 port 也序列化。


# Interrupt to branch-B Mapping

Mapping 必須同時描述：
DUT interrupt/event
→ branch_fw handler/map
→ command/pattern
→ branch-B
→ VIP instance
→ VIP sequence/API
→ expected response/IRQ clear。

AMBA M×N 時 branch-B mapping 可為 M×N VIP fabric，不得強制 A/B 1:1。


## Initialization Task Hierarchy（block / branch_a* / branch_fw / branch_b*）

四層架構各自負責不同層級的 init task，對稱於已定義的 runtime 平行語意
（`interrupt-event-dispatch` 的 FW Service Loop、`vip-scenario-branch` 的 VIP Parallel Tasks）：

1. **`block`（SoC global init task，單一、非per-port）**：SoC 層級的全域初始化，例如 power-on
   sequencing、global clock/reset de-assertion 順序、global register 預設值/PLL lock 等跨所有
   port 共用的前置條件。這一層預設是單一 task，不依 port 拆分——因為它本來就是所有 branch_a*
   共用的前提，不是可平行的 per-port 工作。
2. **`branch_a0/branch_a1/branch_a2/branch_a3...`（DUT+PHY init task，per-port，預設平行）**：
   每個 DUT port 各自的 DUT-side + PHY-side 初始化（例如 PHY calibration、per-port reset 釋放、
   per-port register/mode 設定、link training 等，依實際 RTL/PHY evidence 而非假設）。不相關的
   port 之間預設可平行跑各自的 init task，不得因為要跑某個 port 的 PHY 校準就序列化其他 port。
3. **順序依賴**：`block` 的 global init 必須先達到其 ready 條件（或至少該 port 依賴的那部分全域
   前提已就緒），對應 `branch_a{i}` 的 per-port init 才能開始；`branch_a{i}` 的 per-port init
   完成後，該 port 對應的 `branch_fw` FW Service Loop 才開始等待該 port 的 interrupt/event；
   `branch_b{i}` 的 VIP Parallel Task 何時可以開始跑，依該 scenario 是否需要 DUT/PHY 已就緒而定
   （不是每個 VIP scenario 都需要等，需依實際 evidence 判斷，不可一律假設要等）。
4. 若某個 `branch_a{i}` 的 init 需要存取與其他 `branch_a*` 共用的 shared resource（例如共用的
   PHY common block、共用的 reset controller），該存取需遵循上面「AMBA M×N Mapping」/
   「APB/AXI transaction」段落已定義的 arbitration policy，不能自行假設誰先誰後。

記錄：
INIT_TASK_ID,LAYER(block|branch_a{i}),PORT_ID(null for block),STEPS,DEPENDS_ON(INIT_TASK_ID list),
SHARED_RESOURCE,ARBITRATION_REF(對應 branch-mapper MAP_ID),SOURCE,CONFIDENCE


## Real-World Reference Mapping（`block`/`branch_a*`/`branch_fw`/`branch_b*` 用法範例）

抽象的四層命名不能只停留在理論——必須參考真實環境驗證過的用法。本 session 已對
`D:\DV\Task\DV_Agent_Harness_L5\USB_UVM_Handoff\uvm\tb\env\usb_top_env.sv`（真實 USB VIP-based
環境）做過完整 evidence 蒐證，四層對應如下（僅供理解概念用；實際做 branch_a/branch_fw 修改時仍必須
依上面規則重新查證當下真實檔案，不可直接沿用此處記載當作當下證據）：

- **`block`** = `usb_top_env`（整個 SoC/chip-top 層級環境本身），負責 21 個真實 top-level 元件的
  build_phase 建立與 connect_phase 統一接線入口（見 line 456 起的 `connect_phase`），對應
  「SoC global init task」概念。
- **`branch_a0/branch_a1/...`** = DUT-side per-port 介面/binding（例如每個 `NUM_USB_PORTS` 對應的
  DUT pin-level virtual interface 綁定），是 DUT+PHY init task 實際發生的層級——做 branch_a 修改時
  仍必須依規則 3/7 重新查證當下 DUT RTL/PHY 文件，不可只憑此處記載的抽象角色假設細節。
- **`branch_fw`** = `virt_seqr`（`usb_virtual_sequencer`）與 `sys_virt_seqr[p]`：非 global scheduler，
  依 per-port 建立的 `virt_seqr.usb_xfer_seqr[p]`/`usb_sys_seqr[p]` 欄位，把 DUT 側事件驅動的
  sequence 派送到對應 port 的 VIP sequencer——對應「FW Service Loop, per-port 獨立」的實際落地。
- **`branch_b0/branch_b1/...`** = `usb_host_agent[p]`（Synopsys USB VIP host agent，per-port array）
  及其餘 VIP-side 元件（`apb_env`/`axi_env`/`dma_env` 等），是 VIP testing scenario/sequence 實際
  執行的層級——對應「VIP Parallel Tasks, per-port 獨立」的實際落地。

這組對應是本 session 真實跑過 evidence-consensus 驗證得到的，不是憑空假設；但套用到其他協定/其他
DUT 時，四層各自對應到哪個真實元件仍要重新查證（不同 VIP/不同 DUT 的實際物件命名一定不同），
此處只提供「如何辨認哪個真實元件扮演哪一層角色」的參考範例，不是可以跨專案直接複製的具體值。
