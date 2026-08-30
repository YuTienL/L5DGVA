---
name: interrupt-event-dispatch
description: 將 branch_fw 定義為 DUT interrupt/event-driven firmware command dispatcher，負責 IRQ/event decode、mapping、dispatch 與 resource-local coordination。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Interrupt / Event Driven branch_fw

branch_fw 不是 Global Scheduler。

branch_fw 的主要觸發來源：
DUT / SoC Interrupt 或明確 Event。

流程：
Interrupt/Event
→ decode source/status
→ mask/enable/status/clear semantics
→ map 到 vPlan scenario / command
→ dispatch 到對應 branch-B VIP testing scenario
→ 等待/檢查預期 response
→ interrupt clear/ack
→ completion / timeout

## CPU Task 層級實作模式

正確作法：
1. 先了解事件觸發 register 與其設定（enable/mask/trigger condition）。
2. 用 CPU WRITE task 設定/啟動該 trigger register。
3. 直接 wait 該 register 觸發後產生的 interrupt 訊號事件（event-driven wait，而非間隔檢查）。
4. 收到 interrupt 後才讀取 status/data，並執行 clear/ack。

禁止：
以固定間隔的 CPU READ task 輪詢（polling）trigger/status register 作為主要偵測手段。

必須從以下 evidence 推導：
- DUT RTL
- interrupt controller RTL
- register map
- programming guide
- interrupt guide
- PHY/protocol docs（若相關）
- existing branch_fw implementation

事件/控制 register 實際所在的 RTL instance/signal hierarchy path 必須以目前 RTL evidence 查證確認，不得假設或沿用舊 hierarchy path。
SOURCE_HIER 欄位必須填入實查得到的 instance path，而非推測值。

記錄：
IRQ_ID,IRQ_NAME,SOURCE_HIER,STATUS_REG,MASK_REG,CLEAR_REG,TRIGGER,BRANCH_B,PATTERN_ID,COMMAND_ID,RESOURCE_SCOPE,TIMEOUT,SOURCE,CONFIDENCE

多 interrupt：
- 不相關 resource 預設可平行
- 同 shared resource 才 local arbitration
- 禁止 branch_fw 形成跨所有 port 的 global lock

## FW Service Loop（support parallel Port1/2/3...）

branch_fw 的具體實作結構是「每個 Port 一個獨立 service loop」，不是單一序列迴圈輪流服務所有 port：

1. 每個 Port（Port0/Port1/Port2...）各自維持一個獨立 service loop instance（例如以 fork/join_none 或
   獨立 CPU task 平行啟動），每個 loop 只 wait/處理該 Port 自己相關的 interrupt/event 子集合
   （對照 `IRQ_ID...RESOURCE_SCOPE` 記錄中屬於該 Port 的項目）。
2. 單一 loop 內部仍是上面定義的事件驅動流程（wait event → decode → dispatch → 等 response → clear/ack →
   loop 回到 wait 下一個 event），同一個 port 內部順序處理是正常的，不是問題。
3. 不相關 Port 之間的 loop 必須維持獨立平行，禁止用單一 loop 依序輪流服務所有 port（那等同於把
   不相關 port 序列化，變相退化成 polling/輪詢式排程，違反上面的 event-driven 原則）。
4. 若不同 Port 的 loop 會存取同一個 shared resource/register block，則該 access 必須遵循
   `branch-mapper` 已定義的 AMBA arbitration policy（見「AMBA M×N Mapping」/「APB/AXI transaction」段落），
   不能各自 loop 自己隨意仲裁。

記錄（新增於既有 IRQ 記錄之外）：
SERVICE_LOOP_ID,PORT_ID,WAIT_EVENT_SET(IRQ_ID list),DISPATCH_TARGETS(BRANCH_B list),SHARED_RESOURCE,
ARBITRATION_REF(對應 branch-mapper 的 MAP_ID),SOURCE,CONFIDENCE
